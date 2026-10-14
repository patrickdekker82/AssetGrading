"""Market regime (chapter 5): risk on, neutral or risk off, from three inputs read on the completed week.

- World index (MSCI World) at the week's close against the average of its last ten month-end closes.
- High-yield credit spread (FRED BAMLH0A0HYM2) against its own history.
- VIX against its own history over ten years.

Each input votes +1 (calm), 0 or -1 (stress). The regime is decided per week and stored for every day, so
a stock graded on a Wednesday uses the regime of the previous Friday. The regime shifts grades of stock
and crypto templates at most one notch (engine) and gives the metric `regime_score`; gates still apply.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.grading.percentiles import percentile_of
from app.ingest.report import Report
from app.modelconfig import ModelConfig
from app.modelconfig.schema import RegimeSettings, RegimeVote
from app.models import MarketRegime

MIN_VIX_POINTS = 250


def week_end(day: date) -> date:
    """The last Friday on or before `day`."""
    return day - timedelta(days=(day.weekday() - 4) % 7)


@dataclass
class RegimeResult:
    day: date
    week_end: date
    state: str | None
    score: int | None
    inputs: dict = field(default_factory=dict)


def _last(s: pd.Series, on: date) -> tuple[date, float] | None:
    known = s.loc[:on].dropna()
    return None if known.empty else (known.index[-1], float(known.iloc[-1]))


def world_vote(world: pd.Series, we: date, ma_months: int) -> dict | None:
    last = _last(world, we)
    if last is None or (we - last[0]).days > 7:
        return None
    hist = world.loc[:we].dropna()
    months = pd.Series([d.year * 100 + d.month for d in hist.index], index=hist.index)
    month_end = hist.groupby(months).last()
    month_end = month_end[month_end.index < we.year * 100 + we.month]   # completed months only
    if len(month_end) < ma_months:
        return None
    average = float(month_end.iloc[-ma_months:].mean())
    return {"value": last[1], "date": last[0].isoformat(), "average_10m": round(average, 4),
            "vote": 1 if last[1] > average else -1}


def percentile_vote(series: pd.Series, we: date, vote_cfg: RegimeVote) -> dict | None:
    last = _last(series, we)
    if last is None or (we - last[0]).days > 10:
        return None
    hist = series.loc[:we].dropna()
    if vote_cfg.lookback_years:
        hist = hist.loc[we - timedelta(days=int(vote_cfg.lookback_years * 365)):]
    years = (hist.index[-1] - hist.index[0]).days / 365 if len(hist) else 0
    if vote_cfg.min_history_years and years < vote_cfg.min_history_years:
        return None
    if len(hist) < 20:
        return None
    # Percentile of the level: high spreads and a high VIX mean stress.
    pct = percentile_of(last[1], hist.tolist(), higher_is_better=True)
    vote = 1 if pct <= vote_cfg.calm_below_pct else -1 if pct >= vote_cfg.stress_above_pct else 0
    return {"value": last[1], "date": last[0].isoformat(), "percentile": round(pct, 1),
            "history_from": hist.index[0].isoformat(), "vote": vote}


def compute_regime(day: date, world: pd.Series, hy: pd.Series, vix: pd.Series,
                   cfg: RegimeSettings) -> RegimeResult:
    we = week_end(day)
    inputs = {
        "world_index": world_vote(world, we, int(cfg.world_index.get("ma_months", 10))),
        "high_yield_spread": percentile_vote(hy, we, cfg.high_yield_spread),
        "vix": percentile_vote(vix, we, cfg.vix),
    }
    votes = [v["vote"] for v in inputs.values() if v is not None]
    if len(votes) < cfg.min_inputs:
        return RegimeResult(day, we, None, None, inputs)
    score = sum(votes)
    state = "risk_on" if score >= cfg.risk_on_at else "risk_off" if score <= cfg.risk_off_at else "neutral"
    return RegimeResult(day, we, state, score, inputs)


def _series(session: Session, sql: str, params: dict) -> pd.Series:
    rows = session.execute(text(sql), params).all()
    return pd.Series([float(r[1]) for r in rows], index=[r[0] for r in rows], dtype=float)


def load_inputs(session: Session, cfg: RegimeSettings,
                knowledge: datetime) -> tuple[pd.Series, pd.Series, pd.Series]:
    world = _series(session, """
        SELECT p.ts, p.close_native FROM price_daily_eur p JOIN asset a ON a.id = p.asset_id
        WHERE a.slug = :slug ORDER BY p.ts""", {"slug": cfg.world_index.get("index", "msci-world")})
    macro = """
        SELECT DISTINCT ON (date) date, value FROM macro_observation
        WHERE series_id = :s AND available_at <= :k ORDER BY date, available_at DESC, id DESC"""
    hy = _series(session, macro, {"s": cfg.high_yield_spread.series, "k": knowledge})
    vix = _series(session, macro, {"s": cfg.vix.series, "k": knowledge})
    return world, hy, vix


def update_regime(sf: sessionmaker[Session], config: ModelConfig, model_version_id: int, until: date,
                  start: date, report: Report) -> None:
    """Store the regime for every day from the first missing day up to `until` (idempotent)."""
    cfg = config.settings.regime
    if not isinstance(cfg, RegimeSettings):
        return
    knowledge = datetime.now(UTC)
    with sf() as session:
        last = session.scalar(select(MarketRegime.date).where(MarketRegime.model_version_id == model_version_id)
                              .order_by(MarketRegime.date.desc()).limit(1))
        world, hy, vix = load_inputs(session, cfg, knowledge)
    day = last + timedelta(days=1) if last else start
    rows = []
    cache: dict[date, RegimeResult] = {}
    while day <= until:
        we = week_end(day)
        if we not in cache:
            cache[we] = compute_regime(we, world, hy, vix, cfg)
        r = cache[we]
        rows.append({"date": day, "model_version_id": model_version_id, "state": r.state, "score": r.score,
                     "week_end": r.week_end, "inputs": r.inputs, "computed_at": knowledge})
        day += timedelta(days=1)
    with sf() as session:
        for i in range(0, len(rows), 2000):
            session.execute(insert(MarketRegime).values(rows[i:i + 2000]).on_conflict_do_nothing())
        session.commit()
    report.add("regime_days_added", len(rows))


def regime_on(session: Session, day: date, model_version_id: int, knowledge: datetime | None = None) -> str | None:
    q = select(MarketRegime.state).where(MarketRegime.model_version_id == model_version_id, MarketRegime.date <= day)
    if knowledge is not None:
        q = q.where(MarketRegime.computed_at <= knowledge)
    return session.scalar(q.order_by(MarketRegime.date.desc()).limit(1))
