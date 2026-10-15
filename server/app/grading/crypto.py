"""Daily crypto grading: inputs -> technical score -> percentiles -> engine -> grade_snapshot.

Runs after the nightly crypto ingest for the last completed day. Every tracked coin gets a snapshot:
a grade, a peg-safety score, or a stated reason why there is none.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.grading.assign import assign_crypto, crypto_tags
from app.grading.crypto_inputs import MIN_HISTORY_POINTS, CryptoData, Metrics, compute_metrics, load_crypto_data
from app.grading.engine import GradeInput, GradeResult, MetricInput, grade
from app.grading.letters import letter_for
from app.grading.percentiles import percentile_of, weighted_percentile_of
from app.grading.technical import TechRaw, tech_raw, tech_scores
from app.ingest.report import Report
from app.modelconfig import ModelConfig
from app.models import BacktestSnapshot, GradeSnapshot

log = logging.getLogger("graadmeter.grading")
MIN_PEERS = 3


@dataclass
class Prepared:
    asset_id: int
    key: str                      # coingecko id or stock slug
    template_id: str
    tags: list[str]
    metrics: Metrics
    technical: dict | None = None
    btc_relative: dict | None = None
    price_eur: float | None = None
    peer_key: str | None = None   # stocks: the sector, compared within the template
    product: bool = False         # an ETC graded with its commodity template's product judgement


def percentile_metric_ids(config: ModelConfig, template_id: str, product: bool = False) -> list[str]:
    t = config.templates[template_id]
    ids = list(t.product.metrics) if product and t.product else [m.id for p in t.pillars for m in p.metrics]
    return [i for i in dict.fromkeys(ids) if config.metrics[i].scoring == "percentile"]


def valuation_metric_ids(config: ModelConfig, template_id: str) -> set[str]:
    t = config.templates[template_id]
    return {m.id for p in t.pillars if p.valuation for m in p.metrics}


def peer_group(config: ModelConfig, template_id: str, counts: dict[str, int]) -> tuple[str, list[str]]:
    """Comparison group: the template itself, or a broader group when it has too few members."""
    peers = config.settings.peers
    if counts.get(template_id, 0) < peers.min_group_size and template_id in peers.broaden:
        group = peers.broaden[template_id]
        return group, peers.groups[group]
    return template_id, [template_id]


def min_peers(config: ModelConfig, template_id: str) -> int:
    """ETFs on the same index are compared even when there are only two of them."""
    if config.templates[template_id].peer_group == "same_index" and config.settings.etf:
        return config.settings.etf.min_peers
    return MIN_PEERS


def peer_members(p: "Prepared", prepared: list["Prepared"], config: ModelConfig,
                 counts: dict[str, int]) -> tuple[str, list["Prepared"]]:
    """Members of the comparison group of `p`. Stocks compare within their sector (same template); a sector
    with fewer than `min_group_size` members falls back to all stocks with that template."""
    kind = config.templates[p.template_id].peer_group
    prepared = [q for q in prepared if q.product == p.product]   # products only compare with products
    if kind in ("sector", "bond_category", "same_index", "commodity_class") and p.peer_key:
        sector = [q for q in prepared if q.template_id == p.template_id and q.peer_key == p.peer_key]
        if kind == "same_index" or len(sector) >= config.settings.peers.min_group_size:
            return f"{p.template_id}:{p.peer_key}", sector    # ETFs: only ever the same index
        return p.template_id, [q for q in prepared if q.template_id == p.template_id]
    group_name, group_templates = peer_group(config, p.template_id, counts)
    return group_name, [q for q in prepared if q.template_id in group_templates]


def _own_history_pct(value: float, history: pd.Series, as_of: date, years: float, higher: bool,
                     half_life: float | None = None) -> float | None:
    hist = history.loc[:as_of].dropna()
    if half_life is None:
        hist = hist.loc[as_of - timedelta(days=int(years * 365)):]
    if len(hist) < MIN_HISTORY_POINTS:
        return None
    if half_life is None:
        return percentile_of(value, hist.tolist(), higher_is_better=higher)
    ages = [(as_of - d).days / 365 for d in hist.index]
    weights = [0.5 ** (a / half_life) for a in ages]
    return weighted_percentile_of(value, hist.tolist(), weights, higher_is_better=higher)


def prepare(data: CryptoData, config: ModelConfig) -> list[Prepared]:
    prepared = []
    for a in data.assets:
        template_id = assign_crypto(a.coingecko_id, a.categories, a.template_override, config.assignment)
        tags = crypto_tags(a.categories, a.alias_kinds, config.assignment)
        template = config.templates[template_id]
        metrics = compute_metrics(data, a, template_id, template.safety_params)
        closes = data.closes.get(a.id)
        price = float(closes.iloc[-1]) if closes is not None and not closes.empty else None
        prepared.append(Prepared(a.id, a.coingecko_id, template_id, tags, metrics, price_eur=price))
    _technical(prepared, data, config)
    return prepared


def _technical(prepared: list[Prepared], data: CryptoData, config: ModelConfig) -> None:
    params = config.technical.params["crypto"]
    btc = next((p for p in prepared if p.key == params.benchmark), None)
    bench = data.closes.get(btc.asset_id) if btc else None
    raws: dict[int, TechRaw] = {}
    rel_raws: dict[int, TechRaw] = {}
    for p in prepared:
        if p.template_id == "crypto_stablecoin":
            continue  # a peg is not a trend; stablecoins are not in the technical comparison class
        closes = data.closes.get(p.asset_id)
        if closes is None:
            continue
        is_bench = btc is not None and p.asset_id == btc.asset_id
        raws[p.asset_id] = tech_raw(closes, None if is_bench else bench, params, data.as_of)
        if config.templates[p.template_id].show_btc_relative and bench is not None and not is_bench:
            ratio = (closes / bench).dropna()
            rel_raws[p.asset_id] = tech_raw(ratio, None, params, data.as_of)
    scores = tech_scores(raws, config.technical.blocks, params)
    rel_scores = tech_scores(rel_raws, config.technical.blocks, params) if rel_raws else {}
    scale = config.settings.letter_scale
    for p in prepared:
        if p.asset_id in scores:
            res = scores[p.asset_id]
            p.metrics.set("technical_score", res.score, "technische score (hoofdstuk 7)")
            p.technical = res.to_dict()
        if p.asset_id in rel_scores and rel_scores[p.asset_id].score is not None:
            s = rel_scores[p.asset_id].score
            p.btc_relative = {"score": s, "letter": letter_for(s, scale), "blocks": rel_scores[p.asset_id].blocks}


def build_inputs(prepared: list[Prepared], config: ModelConfig, as_of: date) -> dict[int, tuple[GradeInput, dict]]:
    """GradeInput per asset plus the peer values used, so each percentile can be recomputed."""
    counts: dict[str, int] = {}
    for p in prepared:
        counts[p.template_id] = counts.get(p.template_id, 0) + 1
    winsor = tuple(config.settings.scoring.winsorize)
    years = config.settings.peers.own_history_years
    out = {}
    for p in prepared:
        template = config.templates[p.template_id]
        metrics: dict[str, MetricInput] = {k: MetricInput(value=v) for k, v in p.metrics.values.items()}
        peers_used: dict[str, dict] = {}
        if template.grading == "weighted":
            own_history = template.peer_group == "own_history"
            half_life = (template.own_history or {}).get("recency_half_life_years") if own_history else None
            group_name, members = peer_members(p, prepared, config, counts)
            valuation = valuation_metric_ids(config, p.template_id)
            for metric_id in percentile_metric_ids(config, p.template_id, p.product):
                mi = metrics.get(metric_id)
                if mi is None or mi.value is None:
                    continue
                higher = config.metrics[metric_id].direction == "higher"
                if own_history or metric_id in template.own_history_metrics:
                    hist = p.metrics.history.get(metric_id)
                    if hist is not None:
                        mi.peer_pct = _own_history_pct(mi.value, hist, as_of, years, higher, half_life)
                    peers_used[metric_id] = {"group": "own_history",
                                             "half_life_years": half_life if own_history else None}
                    continue
                values = [q.metrics.values[metric_id] for q in members if q.metrics.values.get(metric_id) is not None]
                if len(values) >= min_peers(config, p.template_id):
                    mi.peer_pct = percentile_of(mi.value, values, higher_is_better=higher, winsor=winsor,
                                              winsor_excludes_self=config.settings.scoring.winsor_excludes_self)
                peers_used[metric_id] = {"group": group_name, "values": values}
                hist = p.metrics.history.get(metric_id)
                if metric_id in valuation and hist is not None:
                    mi.own_pct = _own_history_pct(mi.value, hist, as_of, years, higher)
        inp = GradeInput(template_id=p.template_id, tags=p.tags, metrics=metrics, flags=dict(p.metrics.flags),
                         product=p.product)
        out[p.asset_id] = (inp, peers_used)
    return out


@dataclass
class SnapshotSink:
    """Where grades go. Live: grade_snapshot. Backtest: backtest_snapshot of one run, with the regime of that
    month computed from the data known then (the stored live regime history is not point in time)."""

    run_id: int | None = None
    regime: str | None = None
    regime_version_id: int | None = None    # shadow grading: use the champion's stored regime

    @property
    def live(self) -> bool:
        return self.run_id is None

    @property
    def table(self):
        return GradeSnapshot if self.live else BacktestSnapshot

    def source_sql(self) -> str:
        """A FROM clause for reading snapshots written to this sink (e.g. index letters for ETFs)."""
        return "grade_snapshot" if self.live else f"(SELECT * FROM backtest_snapshot WHERE run_id = {int(self.run_id)})"

    def regime_on(self, session: Session, as_of: date, model_version_id: int) -> str | None:
        from app.grading.regime import regime_on

        if not self.live:
            return self.regime
        return regime_on(session, as_of, self.regime_version_id or model_version_id)

    def previous_state(self, session: Session, asset_id: int, model_version_id: int, as_of: date,
                       days: int) -> tuple[str | None, list[str]]:
        t = self.table
        q = (select(t.result["hysteresis_letter"].astext, t.result["raw_letter"].astext)
             .where(t.asset_id == asset_id, t.model_version_id == model_version_id, t.as_of < as_of))
        if not self.live:
            q = q.where(t.run_id == self.run_id)
        rows = session.execute(q.order_by(t.as_of.desc()).limit(max(days - 1, 1))).all()
        if not rows:
            return None, []
        return rows[0][0], [r[1] for r in reversed(rows) if r[1]]

    def row(self, row: dict) -> dict:
        if self.live:
            return row
        # Backtest rows keep the engine input (to recompute) but not the bulky peer lists and raw values.
        return {**row, "run_id": self.run_id,
                "inputs": {"grade_input": row["inputs"]["grade_input"], "notes": row["inputs"].get("notes", [])}}


LIVE = SnapshotSink()


def grade_crypto(sf: sessionmaker[Session], config: ModelConfig, model_version_id: int, as_of: date,
                 history_start: date, knowledge: datetime | None = None, sink: SnapshotSink = LIVE) -> Report:
    report = Report()
    knowledge = knowledge or datetime.now(UTC)
    with sf() as session:
        data = load_crypto_data(session, as_of, knowledge, history_start)
    prepared = prepare(data, config)
    write_snapshots(sf, prepared, config, model_version_id, as_of, knowledge, report, sink)
    return report


def write_snapshots(sf: sessionmaker[Session], prepared: list[Prepared], config: ModelConfig, model_version_id: int,
                    as_of: date, knowledge: datetime, report: Report, sink: SnapshotSink = LIVE) -> None:
    """Grade every prepared asset and store the snapshots (an existing snapshot for the day is kept)."""
    with sf() as session:
        regime = sink.regime_on(session, as_of, model_version_id)
    if regime is None and sink.live and sink.regime_version_id is None:
        # First day of a new model version: its regime history may not exist yet (the markets run stores it).
        from app.grading.regime import REGIME_START, update_regime

        update_regime(sf, config, model_version_id, as_of, REGIME_START, Report())
        with sf() as session:
            regime = sink.regime_on(session, as_of, model_version_id)
    apply_regime_metric(prepared, config, regime)
    inputs = build_inputs(prepared, config, as_of)
    days = config.settings.stability.hysteresis_days
    rows = []
    with sf() as session:
        for p in prepared:
            inp, peers = inputs[p.asset_id]
            inp.prev_letter, inp.recent_raw = sink.previous_state(session, p.asset_id, model_version_id, as_of, days)
            inp.regime = regime
            result = grade(inp, config)
            report.add(f"status_{result.status}")
            rows.append(sink.row(snapshot_row(p, inp, peers, result, model_version_id, as_of, knowledge)))
        if rows:
            t = sink.table
            keys = ["asset_id", "as_of", "model_version_id"] if sink.live else ["run_id", "asset_id", "as_of"]
            added = 0
            for i in range(0, len(rows), 500):
                stmt = insert(t).values(rows[i:i + 500]).on_conflict_do_nothing(index_elements=keys)
                added += len(session.execute(stmt.returning(t.id)).all())
            report.add("snapshots_added", added)
        session.commit()


def apply_regime_metric(prepared: list[Prepared], config: ModelConfig, regime: str | None) -> None:
    """The metric regime_score (index and Bitcoin macro pillars) from the day's market regime."""
    cfg = config.settings.regime
    if regime is None or isinstance(cfg, dict) or regime not in cfg.scores:
        return
    for p in prepared:
        ids = {m.id for pl in config.templates[p.template_id].pillars for m in pl.metrics}
        if "regime_score" in ids:
            p.metrics.set("regime_score", cfg.scores[regime], f"marktregime: {regime}")


def snapshot_row(p: Prepared, inp: GradeInput, peers: dict, result: GradeResult, model_version_id: int,
                 as_of: date, knowledge: datetime) -> dict:
    res = result.to_dict()
    res["btc_relative"] = p.btc_relative
    return {
        "asset_id": p.asset_id, "as_of": as_of, "model_version_id": model_version_id, "template_id": p.template_id,
        "status": result.status, "score": result.score, "quality": result.quality, "timing": result.timing,
        "coverage": result.coverage, "letter": result.letter, "peg_safety": result.peg_safety,
        "price_eur": p.price_eur, "knowledge_time": knowledge,
        "inputs": {
            "grade_input": inp.to_dict(), "peers": peers, "provenance": p.metrics.provenance,
            "raw": p.metrics.raw, "technical": p.technical, "notes": p.metrics.notes,
        },
        "result": res,
    }
