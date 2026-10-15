"""Grading of commodities, their products (ETCs) and currency pairs (chapter 6: Grondstof, Edelmetaal,
Valutapaar).

Commodities get two judgements: the commodity itself (carry from the futures curve, trend, inventories,
macro, speculator positions) and the product you would actually hold (an ETC: physical or futures,
collateral, costs, roll yield or tracking difference). The trend is measured on the ETC where the app
follows one, because an ETC is a roll-adjusted series and the front futures contract is not.

Currency pairs carry a direction score: long the first currency, short the second. Every pair is graded in
both directions; the second direction is built as the exact mirror of the first (every metric negated, the
technical score 100 minus), so the scores of EUR/USD and USD/EUR always add up to 100.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.commodities_config import CommoditiesConfig, FxPair
from app.grading.crypto import LIVE, Prepared, SnapshotSink, write_snapshots
from app.grading.crypto_inputs import Metrics
from app.grading.markets import _cats, realized_vol_series
from app.grading.percentiles import percentile_of
from app.grading.technical import tech_raw, tech_scores
from app.ingest.report import Report
from app.modelconfig import ModelConfig

HISTORY_YEARS = 12
STALE_DAYS = 7
MACRO_STALE_DAYS = 120          # monthly series (OECD rates, BIS exchange rates)
CFTC_WEEKS = 4
NOT_MIRRORED = {"fx_vol_or_vix_percentile"}


@dataclass
class Data:
    as_of: date
    knowledge: datetime
    assets: dict[str, dict]                 # slug -> {id, name, asset_class, sector, categories}
    closes: dict[int, pd.Series]            # own currency
    closes_eur: dict[int, pd.Series]
    facts: dict[int, dict[str, pd.Series]]  # asset -> field -> series (latest version per day)
    macro: dict[str, pd.Series]
    eurusd: pd.Series

    def series(self, sid: str) -> pd.Series | None:
        s = self.macro.get(sid)
        return None if s is None or s.empty else s


def load_data(session: Session, as_of: date, knowledge: datetime) -> Data:
    conn = session.connection()
    p = {"d": as_of, "k": knowledge, "start": as_of - timedelta(days=365 * HISTORY_YEARS)}
    assets = {r.slug: {"id": r.id, "name": r.name, "asset_class": r.asset_class, "sector": r.sector,
                       "categories": _cats(r.categories)}
              for r in session.execute(text(
                  "SELECT id, slug, name, asset_class, sector, categories FROM asset "
                  "WHERE asset_class IN ('commodity', 'etc', 'fx') AND tracked"))}
    ids = [a["id"] for a in assets.values()]
    prices = pd.read_sql(text(
        "SELECT asset_id, ts, close_native::float8 AS c, close_eur::float8 AS e FROM price_daily_eur "
        "WHERE asset_id = ANY(:ids) AND ts <= :d AND ts >= :start ORDER BY asset_id, ts"), conn,
        params={**p, "ids": ids})
    closes, closes_eur = {}, {}
    for k, g in prices.groupby("asset_id"):
        idx = pd.to_datetime(g["ts"]).dt.date
        closes[int(k)] = pd.Series(g["c"].to_numpy(), index=idx)
        closes_eur[int(k)] = pd.Series(g["e"].to_numpy(), index=idx)
    facts_df = pd.read_sql(text(
        """
        SELECT DISTINCT ON (asset_id, field, as_of) asset_id, field, as_of, value::float8 AS value
        FROM fundamental_fact WHERE asset_id = ANY(:ids) AND available_at <= :k AND field <> 'close_raw'
        ORDER BY asset_id, field, as_of, available_at DESC, id DESC
        """), conn, params={**p, "ids": ids})
    facts: dict[int, dict[str, pd.Series]] = {}
    for (aid, fld), g in facts_df.groupby(["asset_id", "field"]):
        facts.setdefault(int(aid), {})[fld] = pd.Series(g["value"].to_numpy(), index=list(g["as_of"]))
    macro_df = pd.read_sql(text(
        """
        SELECT DISTINCT ON (series_id, date) series_id, date, value FROM macro_observation
        WHERE available_at <= :k AND date <= :d AND date >= :start
        ORDER BY series_id, date, available_at DESC, id DESC
        """), conn, params=p)
    macro = {sid: pd.Series(g["value"].to_numpy(dtype=float), index=pd.to_datetime(g["date"]).dt.date)
             for sid, g in macro_df.groupby("series_id")}
    fx = pd.read_sql(text("SELECT date, rate::float8 AS r FROM fx_rate WHERE base = 'EUR' AND quote = 'USD' "
                          "AND date <= :d ORDER BY date"), conn, params=p)
    eurusd = pd.Series(fx["r"].to_numpy(), index=pd.to_datetime(fx["date"]).dt.date)
    return Data(as_of, knowledge, assets, closes, closes_eur, facts, macro, eurusd)


def _fresh_last(s: pd.Series | None, as_of: date, days: int) -> tuple[date, float] | None:
    if s is None:
        return None
    s = s.loc[:as_of].dropna()
    if s.empty or (as_of - s.index[-1]).days > days:
        return None
    return s.index[-1], float(s.iloc[-1])


def _change(s: pd.Series, as_of: date, days: int) -> float | None:
    s = s.loc[:as_of].dropna()
    past = s.loc[:as_of - timedelta(days=days)]
    if s.empty or past.empty or past.iloc[-1] == 0:
        return None
    return float(s.iloc[-1] / past.iloc[-1] - 1)


# --- commodities ----------------------------------------------------------------------------------

def usd_series(data: Data, asset_id: int) -> pd.Series | None:
    """An ETC's price in US dollars (its euro price times the ECB rate), so the trend shows the commodity
    and not the exchange rate."""
    eur = data.closes_eur.get(asset_id)
    if eur is None or eur.dropna().empty or data.eurusd.empty:
        return None
    rate = data.eurusd.reindex(eur.index, method="ffill")
    return (eur * rate).dropna()


def curve_slope(facts: dict[str, pd.Series], as_of: date) -> tuple[float, str] | None:
    """Yearly slope of the futures curve between the first two contracts: positive = backwardation."""
    need = ["curve_f1", "curve_f2", "curve_f1_month", "curve_f2_month"]
    if not all(k in facts for k in need):
        return None
    last = {k: _fresh_last(facts[k], as_of, STALE_DAYS) for k in need}
    if any(v is None for v in last.values()):
        return None
    f1, f2 = last["curve_f1"][1], last["curve_f2"][1]
    m1, m2 = (int(last[k][1]) for k in ("curve_f1_month", "curve_f2_month"))
    months = (m2 // 100 - m1 // 100) * 12 + (m2 % 100 - m1 % 100)
    if f1 <= 0 or f2 <= 0 or months <= 0:
        return None
    return math.log(f1 / f2) * 12 / months, f"contracten {m1} en {m2} ({last['curve_f1'][0]:%d-%m-%Y})"


def inventory_z(s: pd.Series | None, as_of: date) -> tuple[float, date] | None:
    """Latest weekly inventory against the same weeks (±1) of the previous five years."""
    last = _fresh_last(s, as_of, 21)
    if last is None:
        return None
    day, value = last
    week = day.isocalendar()[1]
    hist = [v for d, v in s.items() if day.year - 5 <= d.year < day.year and abs(d.isocalendar()[1] - week) <= 1]
    if len(hist) < 8 or statistics.pstdev(hist) == 0:
        return None
    return (value - statistics.mean(hist)) / statistics.pstdev(hist), day


def prepare_commodities(data: Data, config: ModelConfig, cc: CommoditiesConfig) -> list[Prepared]:
    etcs_by_commodity: dict[str, list[dict]] = {}
    for a in data.assets.values():
        if a["asset_class"] == "etc":
            etcs_by_commodity.setdefault(a["categories"].get("commodity", ""), []).append(a)
    dollar = data.series("DTWEXBGS")
    real = data.series("DFII10")
    out, trends = [], {}
    for c in cc.commodities:
        a = data.assets.get(c.slug)
        if a is None:
            continue
        m = Metrics()
        f = data.facts.get(a["id"], {})
        slope = curve_slope(f, data.as_of)
        if slope:
            m.set("curve_slope_annualized", slope[0], f"termijncurve, {slope[1]}")
        else:
            m.notes.append("geen actuele termijncurve")
        if c.eia:
            z = inventory_z(data.series(f"EIA_{c.eia}"), data.as_of)
            if z:
                m.set("inventory_vs_seasonal", z[0], f"EIA, week van {z[1]:%d-%m-%Y}, t.o.v. 5 jaar")
            else:
                m.notes.append("geen voorraadcijfers (EIA-sleutel ontbreekt of geen recente week)")
        if dollar is not None and _fresh_last(dollar, data.as_of, 10):
            m.set("dollar_index", float(dollar.iloc[-1]), f"FRED DTWEXBGS {dollar.index[-1]:%d-%m-%Y}")
            m.history["dollar_index"] = dollar
        if real is not None and _fresh_last(real, data.as_of, 10):
            metric = "real_rate_10y" if c.template == "precious_metal" else "real_rate"
            m.set(metric, float(real.iloc[-1]) / 100, f"FRED DFII10 {real.index[-1]:%d-%m-%Y}")
            m.history[metric] = real / 100
        if c.cftc:
            pos = data.series(f"CFTC_{c.cftc}")
            if pos is not None and _fresh_last(pos, data.as_of, 14):
                past = pos.loc[:data.as_of - timedelta(weeks=CFTC_WEEKS)]
                if not past.empty:
                    m.set("cftc_speculator_change", float(pos.iloc[-1] - past.iloc[-1]),
                          f"CFTC, netto speculanten t.o.v. open interest, {CFTC_WEEKS} weken")
        # Trend on the roll-adjusted product where one is followed, else on the front contract.
        products = etcs_by_commodity.get(c.slug, [])
        preferred = sorted(products, key=lambda e: (e["categories"].get("structure") != "futures"
                                                    if c.template == "commodity" else
                                                    e["categories"].get("structure") != "physical"))
        trend_series, trend_note = None, None
        for e in preferred:
            s = usd_series(data, e["id"])
            if s is not None and len(s) > 300:
                trend_series, trend_note = s, f"trend gemeten op {e['name']} (in dollar)"
                break
        if trend_series is None:
            trend_series = data.closes.get(a["id"])
            trend_note = "trend gemeten op het eerstvolgende termijncontract (niet voor rollen gecorrigeerd)"
        m.notes.append(trend_note)
        m.notes.append("aankopen door centrale banken en ETF-stromen: geen gratis bron"
                       if c.template == "precious_metal" else "basis-momentum: volgt na een jaar eigen curvedata")
        eur = data.closes_eur.get(a["id"])
        p = Prepared(a["id"], c.slug, c.template, [], m,
                     price_eur=None if eur is None or eur.dropna().empty else float(eur.dropna().iloc[-1]),
                     peer_key=c.group)
        out.append(p)
        if trend_series is not None:
            trends[a["id"]] = trend_series
    params = config.technical.params["commodities"]
    scores = tech_scores({i: tech_raw(s.dropna(), None, params, data.as_of) for i, s in trends.items()},
                         config.technical.blocks, params)
    for p in out:
        if p.asset_id in scores:
            p.metrics.set("technical_score", scores[p.asset_id].score, "technische score (hoofdstuk 7)")
            p.technical = scores[p.asset_id].to_dict()
    return out


def prepare_etcs(data: Data, config: ModelConfig, cc: CommoditiesConfig) -> list[Prepared]:
    templates = {c.slug: c.template for c in cc.commodities}
    out = []
    for a in data.assets.values():
        if a["asset_class"] != "etc":
            continue
        cat = a["categories"]
        commodity = cat.get("commodity", "")
        template = templates.get(commodity)
        if template is None:
            continue
        m = Metrics()
        structure = cat.get("structure")
        if structure:
            m.set("replication_physical", 1.0 if structure == "physical" else 0.0, f"structuur: {structure}")
        if structure == "physical":
            m.set("collateral_score", 1.0, "gedekt door fysiek metaal")
        elif cat.get("collateralized") in ("yes", "no"):
            m.set("collateral_score", 0.8 if cat["collateralized"] == "yes" else 0.0,
                  "met onderpand" if cat["collateralized"] == "yes" else "zonder onderpand")
        ter = data.facts.get(a["id"], {}).get("ongoing_charges")
        if ter is not None and not ter.empty:
            m.set("ongoing_charges", float(ter.iloc[-1]), f"lopende kosten (bestand), {ter.index[-1]:%d-%m-%Y}")
        # Product return in dollars against the front contract over twelve months.
        etc_usd = usd_series(data, a["id"])
        front = data.assets.get(commodity)
        front_s = data.closes.get(front["id"]) if front else None
        diff = None
        if etc_usd is not None and front_s is not None:
            r_etc, r_front = _change(etc_usd, data.as_of, 365), _change(front_s, data.as_of, 365)
            if r_etc is not None and r_front is not None and len(etc_usd.loc[:data.as_of - timedelta(days=365)]):
                diff = r_etc - r_front
        if structure == "physical":
            m.set("roll_yield_12m", 0.0, "fysiek: geen rolkosten")
            if diff is not None:
                m.set("tracking_difference", diff, "12 maanden, in dollar, t.o.v. eerstvolgend termijncontract")
        elif diff is not None:
            m.set("roll_yield_12m", diff, "12 maanden: rendement product min koersverandering eerstvolgend contract")
        m.flags["leveraged_or_inverse"] = cat.get("leveraged_inverse") == "yes"
        m.flags["uncollateralized_note"] = structure != "physical" and cat.get("collateralized") == "no" \
            if structure else None
        eur = data.closes_eur.get(a["id"])
        p = Prepared(a["id"], next(k for k, v in data.assets.items() if v is a), template, [], m,
                     price_eur=None if eur is None or eur.dropna().empty else float(eur.dropna().iloc[-1]),
                     peer_key="etc", product=True)
        out.append(p)
    return out


# --- currency pairs -------------------------------------------------------------------------------

def short_rate(data: Data, cc: CommoditiesConfig, currency: str, as_of: date) -> tuple[pd.Series, str] | None:
    for sid in cc.currencies[currency].rates:
        s = data.series(sid)
        if s is not None and _fresh_last(s, as_of, MACRO_STALE_DAYS):
            return s.loc[:as_of], sid
    return None


def pair_metrics(data: Data, cc: CommoditiesConfig, pair: FxPair, closes: pd.Series) -> Metrics:
    m = Metrics()
    d = data.as_of
    b, q = cc.currencies[pair.base], cc.currencies[pair.quote]
    vol = realized_vol_series(closes)
    vol_now = float(vol.iloc[-1]) if not vol.empty else None
    rb, rq = short_rate(data, cc, pair.base, d), short_rate(data, cc, pair.quote, d)
    if rb and rq and vol_now:
        diff = (float(rb[0].iloc[-1]) - float(rq[0].iloc[-1])) / 100
        m.set("carry_to_vol", diff / vol_now,
              f"renteverschil {diff:+.2%} ({rb[1]} min {rq[1]}) / volatiliteit {vol_now:.1%}")
        past_b, past_q = rb[0].loc[:d - timedelta(days=182)], rq[0].loc[:d - timedelta(days=182)]
        if not past_b.empty and not past_q.empty:
            m.set("rate_path", diff - (float(past_b.iloc[-1]) - float(past_q.iloc[-1])) / 100,
                  "verandering renteverschil over 6 maanden")
    rets = [r for r in (_change(closes, d, n) for n in (91, 182, 365)) if r is not None]
    if len(rets) == 3:
        m.set("fx_momentum_3_12m", sum(rets) / 3, "gemiddelde van 3, 6 en 12 maanden")
    if b.reer and q.reer:
        rb_, rq_ = data.series(b.reer), data.series(q.reer)
        if rb_ is not None and rq_ is not None and _fresh_last(rb_, d, MACRO_STALE_DAYS):
            ratio = np.log(pd.concat([rb_, rq_], axis=1).dropna().iloc[:, 0] /
                           pd.concat([rb_, rq_], axis=1).dropna().iloc[:, 1])
            ratio = ratio.loc[d - timedelta(days=3650):d]
            if len(ratio) >= 60:
                m.set("reer_deviation", float(ratio.iloc[-1] - ratio.mean()),
                      f"reële effectieve koersen (BIS) t.o.v. 10-jaarsgemiddelde, {ratio.index[-1]:%m-%Y}")
    for metric, key, label in (("current_account", "CA", "lopende rekening % bbp"),
                               ("terms_of_trade", "TOT", "ruilvoet, verandering in een jaar")):
        sb = data.series(f"WB_{key}_{b.worldbank}") if b.worldbank else None
        sq = data.series(f"WB_{key}_{q.worldbank}") if q.worldbank else None
        if sb is None or sq is None:
            continue
        if key == "CA":
            m.set(metric, (float(sb.iloc[-1]) - float(sq.iloc[-1])) / 100, f"Wereldbank, {label}, {sb.index[-1].year}")
        elif len(sb) > 1 and len(sq) > 1:
            m.set(metric, float(sb.iloc[-1] / sb.iloc[-2] - sq.iloc[-1] / sq.iloc[-2]),
                  f"Wereldbank, {label}, {sb.index[-1].year}")
    def net(cur):
        if cur == "USD":
            return 0.0
        code = cc.currencies[cur].cftc
        s = data.series(f"CFTC_{code}") if code else None
        last = _fresh_last(s, d, 14)
        return None if last is None else last[1]
    nb, nq = net(pair.base), net(pair.quote)
    if nb is not None and nq is not None:
        m.set("cftc_net_position", nb - nq, "CFTC, netto posities hefboomfondsen t.o.v. open interest")
    if vol_now and len(vol) > 250:
        pct = percentile_of(vol_now, vol.loc[d - timedelta(days=1095):].tolist(), higher_is_better=True)
        vix = data.series("VIXCLS")
        vix_pct = None
        if vix is not None and _fresh_last(vix, d, 10):
            vix_pct = percentile_of(float(vix.iloc[-1]), vix.loc[d - timedelta(days=3650):].tolist(),
                                    higher_is_better=True)
        m.set("fx_vol_or_vix_percentile", max(pct, vix_pct or 0), "hoogste van valutavolatiliteit en VIX (percentiel)")
    m.flags["pegged_or_capital_controls"] = b.managed or q.managed
    if pair.base == "EUR" or pair.quote == "EUR":
        if not (b.worldbank and data.series(f"WB_CA_{b.worldbank}") is not None
                and q.worldbank and data.series(f"WB_CA_{q.worldbank}") is not None):
            m.notes.append("Wereldbank heeft geen cijfers voor de eurozone (lopende rekening, ruilvoet)")
    return m


def mirror(m: Metrics) -> Metrics:
    """The other direction: every metric negated (the technical score: 100 minus), flags unchanged."""
    out = Metrics()
    for k, v in m.values.items():
        if k == "technical_score":
            out.set(k, 100 - v, m.provenance.get(k, "") + " (gespiegeld)")
        elif k in NOT_MIRRORED:
            out.set(k, v, m.provenance.get(k, ""))
        else:
            out.set(k, -v, m.provenance.get(k, "") + " (gespiegeld)")
    out.flags = dict(m.flags)
    out.notes = list(m.notes) + ["Spiegelbeeld van het omgekeerde paar: score is 100 min die score."]
    return out


def prepare_fx(data: Data, config: ModelConfig, cc: CommoditiesConfig) -> list[Prepared]:
    params = config.technical.params["fx"]
    base: list[tuple[FxPair, dict, Metrics]] = []
    raws = {}
    for pair in cc.pairs:
        a = data.assets.get(pair.slug)
        closes = data.closes.get(a["id"]) if a else None
        if a is None or closes is None or closes.empty:
            continue
        base.append((pair, a, pair_metrics(data, cc, pair, closes)))
        raws[a["id"]] = tech_raw(closes, None, params, data.as_of)
    scores = tech_scores(raws, config.technical.blocks, params)
    out = []
    for pair, a, m in base:
        if a["id"] in scores and scores[a["id"]].score is not None:
            m.set("technical_score", scores[a["id"]].score, "technische score (hoofdstuk 7)")
        inv = data.assets.get(pair.inverse().slug)
        out.append(Prepared(a["id"], pair.slug, "fx_pair", [], m, price_eur=None))
        if inv is not None:
            out.append(Prepared(inv["id"], pair.inverse().slug, "fx_pair", [], mirror(m), price_eur=None))
    return out


def grade_commodities(sf: sessionmaker[Session], config: ModelConfig, model_version_id: int, cc: CommoditiesConfig,
                      as_of: date, knowledge: datetime | None = None, sink: SnapshotSink = LIVE) -> Report:
    report = Report()
    knowledge = knowledge or datetime.now(UTC)
    with sf() as session:
        data = load_data(session, as_of, knowledge)
    write_snapshots(sf, prepare_commodities(data, config, cc), config, model_version_id, as_of, knowledge, report, sink)
    write_snapshots(sf, prepare_etcs(data, config, cc), config, model_version_id, as_of, knowledge, report, sink)
    write_snapshots(sf, prepare_fx(data, config, cc), config, model_version_id, as_of, knowledge, report, sink)
    return report
