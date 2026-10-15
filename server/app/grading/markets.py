"""Grading of indices, ETFs and bond ETFs (chapter 6: Index, ETF, Obligatie).

- Index: compared with its own history (trend, macro, breadth, volatility). Valuation only for the S&P 500,
  from Shiller's CAPE data; no free source has earnings or CAPE for the other indices.
- ETF: the product, not the market in it. Compared only with ETFs on the same index. Tracking difference is
  the ETF's yearly total return in euro minus that of the index's total-return series (where free) or of the
  median ETF on the same index; ongoing charges stand in when the ETF is too young.
- Bond ETF: yield minus expected default loss and costs; ratings, duration and concentration from the
  hand-maintained file. Compared within its category, or with all bond ETFs when the category is small.
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.grading.crypto import LIVE, Prepared, SnapshotSink, write_snapshots
from app.grading.crypto_inputs import Metrics
from app.grading.technical import tech_raw, tech_scores
from app.ingest.report import Report
from app.markets_config import MarketsConfig
from app.modelconfig import ModelConfig

HISTORY_YEARS = 12
VOL_ROWS = 63                      # three months of trading days
STALE_PRICE_DAYS = 7


@dataclass
class AssetInfo:
    id: int
    slug: str
    name: str
    asset_class: str
    sector: str | None
    categories: dict[str, str]


@dataclass
class MarketData:
    as_of: date
    knowledge: datetime
    assets: list[AssetInfo]
    closes: dict[int, pd.Series]          # own currency, adjusted
    closes_eur: dict[int, pd.Series]
    volume: dict[int, pd.Series]
    facts: dict[int, dict[str, tuple[date, float]]]   # latest known value per field
    macro: dict[str, pd.Series]
    members: dict[str, list[int]]         # breadth universe -> stock asset ids
    index_snapshots: dict[str, dict]      # index slug -> latest snapshot of this model version


def _cats(raw: list | None) -> dict[str, str]:
    out = {}
    for c in raw or []:
        if isinstance(c, str):
            k, _, v = c.partition(":")
            out[k] = v or "1"
    return out


def load_market_data(session: Session, as_of: date, knowledge: datetime, model_version_id: int,
                     sink: SnapshotSink = LIVE) -> MarketData:
    conn = session.connection()
    start = as_of - timedelta(days=365 * HISTORY_YEARS)
    p = {"d": as_of, "k": knowledge, "start": start, "v": model_version_id}
    assets = [AssetInfo(r.id, r.slug, r.name, r.asset_class, r.sector, _cats(r.categories)) for r in session.execute(
        text("SELECT id, slug, name, asset_class, sector, categories FROM asset "
             "WHERE asset_class IN ('index', 'etf', 'bond', 'reference') AND tracked ORDER BY id"))]
    stock_lists = session.execute(text(
        """
        SELECT DISTINCT ON (asset_id, universe) asset_id, universe, included FROM universe_membership
        WHERE universe IN ('stocks_us', 'stocks_aex') AND as_of <= :d + 4 ORDER BY asset_id, universe, as_of DESC
        """), p).all()
    members: dict[str, list[int]] = {}
    for r in stock_lists:
        if r.included:
            members.setdefault(r.universe, []).append(r.asset_id)
    ids = [a.id for a in assets] + [i for v in members.values() for i in v]
    prices = pd.read_sql(text(
        "SELECT asset_id, ts, close_native::float8 AS c, close_eur::float8 AS e, volume::float8 AS v "
        "FROM price_daily_eur WHERE asset_id = ANY(:ids) AND ts <= :d AND ts >= :start ORDER BY asset_id, ts"),
        conn, params={**p, "ids": ids})
    closes, closes_eur, volume = {}, {}, {}
    for k, g in prices.groupby("asset_id"):
        idx = pd.to_datetime(g["ts"]).dt.date
        closes[int(k)] = pd.Series(g["c"].to_numpy(), index=idx)
        closes_eur[int(k)] = pd.Series(g["e"].to_numpy(), index=idx)
        volume[int(k)] = pd.Series(g["v"].to_numpy(), index=idx)
    # Fund characteristics: what was known at `knowledge` (their own date may be a day after the grading day,
    # e.g. a fund size checked the next morning).
    facts: dict[int, dict[str, tuple[date, float]]] = {}
    for r in session.execute(text(
        """
        SELECT DISTINCT ON (asset_id, field) asset_id, field, as_of, value::float8 AS value
        FROM fundamental_fact WHERE asset_id = ANY(:ids) AND available_at <= :k
          AND source IN ('csv', 'yahoo', 'manual') AND field <> 'close_raw'
        ORDER BY asset_id, field, as_of DESC, available_at DESC, id DESC
        """), {**p, "ids": [a.id for a in assets]}):
        facts.setdefault(r.asset_id, {})[r.field] = (r.as_of, r.value)
    macro_rows = pd.read_sql(text(
        """
        SELECT DISTINCT ON (series_id, date) series_id, date, value FROM macro_observation
        WHERE available_at <= :k AND date <= :d AND date >= :start
        ORDER BY series_id, date, available_at DESC, id DESC
        """), conn, params=p)
    macro = {sid: pd.Series(g["value"].to_numpy(dtype=float), index=pd.to_datetime(g["date"]).dt.date)
             for sid, g in macro_rows.groupby("series_id")}
    snaps = {r.slug: {"letter": r.letter, "timing": r.timing, "score": r.score, "as_of": r.as_of}
             for r in session.execute(text(
                 f"""
                 SELECT DISTINCT ON (a.slug) a.slug, g.letter, g.timing, g.score, g.as_of
                 FROM {sink.source_sql()} g JOIN asset a ON a.id = g.asset_id
                 WHERE a.asset_class = 'index' AND g.model_version_id = :v AND g.as_of <= :d
                 ORDER BY a.slug, g.as_of DESC
                 """), p)}
    return MarketData(as_of, knowledge, assets, closes, closes_eur, volume, facts, macro, members, snaps)


def _fresh(s: pd.Series | None, as_of: date) -> pd.Series | None:
    if s is None or s.empty:
        return None
    s = s.loc[:as_of].dropna()
    return s if not s.empty and (as_of - s.index[-1]).days <= STALE_PRICE_DAYS else None


# --- indices --------------------------------------------------------------------------------------

def curve_slope(data: MarketData, curve: str | None) -> pd.Series | None:
    pairs = {"us": ("DGS10", "DGS2"), "ea": ("EA_AAA_10Y", "EA_AAA_2Y")}
    if curve not in pairs:
        return None
    long, short = (data.macro.get(s) for s in pairs[curve])
    if long is None or short is None:
        return None
    slope = (long - short).dropna() / 100     # percent points -> ratio
    return slope if not slope.empty else None


def breadth_series(data: MarketData, universe: str | None, as_of: date) -> pd.Series | None:
    """Share of the followed members above their own 200-day average, per day over the last years."""
    ids = data.members.get(universe or "")
    if not ids:
        return None
    frames = {}
    for i in ids:
        c = data.closes.get(i)
        if c is not None and len(c) > 220:
            frames[i] = c
    if len(frames) < 10:
        return None
    df = pd.DataFrame(frames).sort_index().ffill(limit=5)
    above = (df > df.rolling(200, min_periods=200).mean()).where(df.notna())
    known = above.notna().sum(axis=1)
    share = (above.sum(axis=1) / known).where(known >= 10).dropna()
    return share.loc[:as_of] if not share.empty else None


def realized_vol_series(closes: pd.Series) -> pd.Series:
    rets = np.log(closes.astype(float)).diff()
    return (rets.rolling(VOL_ROWS).std(ddof=1) * math.sqrt(252)).dropna()


SHILLER_LAG = timedelta(days=31)     # as in the ingest: a month's value is known a month after it ends
SHILLER_FRESH_DAYS = 100             # the latest month plus one late update


def known_daily(monthly: pd.Series, as_of: date) -> pd.Series:
    """A monthly series as it was known on each weekday: every value from the day it became known (month end
    plus the release lag), carried forward. Used as the index's own history for the percentile."""
    known = pd.Series(monthly.to_numpy(), index=[d + SHILLER_LAG for d in monthly.index])
    known = known[known.index <= as_of]
    if known.empty:
        return known
    days = list(pd.bdate_range(known.index[0], as_of).date)
    return known.reindex(sorted(set(known.index) | set(days))).ffill().reindex(days).dropna()


def shiller_valuation(m: Metrics, data: MarketData) -> None:
    """S&P 500 valuation from Shiller's data: the CAPE ratio and the excess CAPE yield (earnings yield of the
    CAPE minus the real 10-year rate, his own calculation), each against the index's own history."""
    pairs = (("cape_vs_history", "SHILLER_CAPE", "CAPE"),
             ("earnings_yield_minus_real_rate", "SHILLER_ECY", "CAPE-winstrendement min reële rente"))
    for metric, sid, label in pairs:
        series = data.macro.get(sid)
        if series is None or series.empty:
            m.notes.append(f"{label}: nog geen data van Shiller")
            continue
        month = series.index[-1]
        if (data.as_of - month).days > SHILLER_FRESH_DAYS:
            m.notes.append(f"{label}: de laatste maand van Shiller ({month:%m-%Y}) is te oud en telt niet mee")
            continue
        m.set(metric, float(series.iloc[-1]), f"{label}, Shiller, maand {month:%m-%Y}")
        m.history[metric] = known_daily(series, data.as_of)


def prepare_indices(data: MarketData, config: ModelConfig) -> list[Prepared]:
    out = []
    for a in (x for x in data.assets if x.asset_class == "index"):
        m = Metrics()
        closes = _fresh(data.closes.get(a.id), data.as_of)
        if closes is None:
            m.notes.append("geen recente koers")
        else:
            vol = realized_vol_series(closes)
            if not vol.empty:
                m.set("volatility_vs_history", float(vol.iloc[-1]), "koersen, 3 maanden, op jaarbasis")
                m.history["volatility_vs_history"] = vol
        slope = curve_slope(data, a.categories.get("curve"))
        if slope is not None and (data.as_of - slope.index[-1]).days <= 10:
            m.set("yield_curve_slope", float(slope.iloc[-1]),
                  "FRED 10 min 2 jaar" if a.categories.get("curve") == "us" else "ECB AAA 10 min 2 jaar")
            m.history["yield_curve_slope"] = slope
        breadth = breadth_series(data, a.categories.get("breadth"), data.as_of)
        if breadth is not None and (data.as_of - breadth.index[-1]).days <= STALE_PRICE_DAYS:
            n = len(data.members.get(a.categories.get("breadth") or "", []))
            m.set("pct_above_sma200", float(breadth.iloc[-1]), f"{n} gevolgde aandelen uit deze markt")
            m.history["pct_above_sma200"] = breadth
        if a.categories.get("valuation") == "shiller":
            shiller_valuation(m, data)
        else:
            m.notes.append("geen gratis bron voor winst of CAPE van deze index: de pijler Waardering blijft leeg "
                           "(alleen de S&P 500 heeft er een, de data van Shiller)")
        p = Prepared(a.id, a.slug, "index", [], m, price_eur=_last_eur(data, a.id))
        out.append(p)
    # In euro: an index in yen or pounds is compared with MSCI World (in dollars) only after conversion
    # (chapter 7: never compare series in different currencies). From model 0.6.0.
    _technical(out, data, config, benchmark_slug=config.technical.params["indices"].benchmark, eur=True)
    return out


def _last_eur(data: MarketData, asset_id: int) -> float | None:
    s = data.closes_eur.get(asset_id)
    return None if s is None or s.dropna().empty else float(s.dropna().iloc[-1])


def _technical(prepared: list[Prepared], data: MarketData, config: ModelConfig, benchmark_slug: str,
               eur: bool = False) -> None:
    params = config.technical.params["indices"]
    bench_id = next((a.id for a in data.assets if a.slug == benchmark_slug), None)
    source = data.closes_eur if eur else data.closes
    bench = source.get(bench_id) if bench_id else None
    raws = {}
    for p in prepared:
        closes = source.get(p.asset_id)
        if closes is not None:
            raws[p.asset_id] = tech_raw(closes.dropna(), None if p.asset_id == bench_id else bench, params,
                                        data.as_of)
    scores = tech_scores(raws, config.technical.blocks, params)
    for p in prepared:
        if p.asset_id in scores:
            res = scores[p.asset_id]
            p.metrics.set("technical_score", res.score, "technische score (hoofdstuk 7)")
            p.technical = res.to_dict()


# --- ETFs -----------------------------------------------------------------------------------------

def annual_return(closes: pd.Series, as_of: date, years: int) -> float | None:
    s = closes.loc[:as_of].dropna()
    start = as_of - timedelta(days=round(365.25 * years))
    if s.empty or s.index[0] > start + timedelta(days=7):
        return None
    first = s.loc[:start]
    if first.empty:
        return None
    a, b = float(first.iloc[-1]), float(s.iloc[-1])
    return (b / a) ** (1 / years) - 1 if a > 0 else None


@dataclass
class TrackingResult:
    years: int | None = None
    reference: str | None = None
    values: dict[int, float] = field(default_factory=dict)
    returns: dict[int, float] = field(default_factory=dict)
    reference_return: float | None = None


def tracking_differences(etf_ids: list[int], data: MarketData, reference_id: int | None,
                         years_options: list[int]) -> TrackingResult:
    """Yearly total return in euro minus the reference's, over the longest window that at least two ETFs
    (or one ETF and the index series) fully cover."""
    for years in years_options:
        rets = {i: r for i in etf_ids if (c := data.closes_eur.get(i)) is not None
                and (r := annual_return(c, data.as_of, years)) is not None}
        ref_ret = None
        if reference_id is not None and (c := data.closes_eur.get(reference_id)) is not None:
            ref_ret = annual_return(c, data.as_of, years)
        if ref_ret is not None and rets:
            return TrackingResult(years, "index", {i: r - ref_ret for i, r in rets.items()}, rets, ref_ret)
        if len(rets) >= 2:
            median = statistics.median(rets.values())
            return TrackingResult(years, "median", {i: r - median for i, r in rets.items()}, rets, median)
    return TrackingResult()


def prepare_etfs(data: MarketData, config: ModelConfig, markets: MarketsConfig) -> list[Prepared]:
    s = config.settings
    tax = s.etf_tax.get("withholding_us_dividends", {})
    preference = s.etf_tax.get("distribution_preference")
    etfs = [a for a in data.assets if a.asset_class == "etf"]
    groups: dict[str, list[AssetInfo]] = {}
    for a in etfs:
        groups.setdefault(a.categories.get("index_group", ""), []).append(a)
    out = []
    for group_key, members in groups.items():
        group = markets.index_groups.get(group_key)
        ref = next((x.id for x in data.assets if x.slug == f"ref-{group_key}"), None)
        td = tracking_differences([a.id for a in members], data, ref, s.etf.tracking_years if s.etf else [5, 3])
        underlying = data.index_snapshots.get(group.index) if group and group.index else None
        for a in members:
            m = Metrics()
            f = data.facts.get(a.id, {})
            limit = s.etf.max_plausible_tracking_difference if s.etf else None
            if a.id in td.values and limit is not None and abs(td.values[a.id]) > limit:
                m.notes.append(f"koersreeks wijkt {td.values[a.id]:+.2%} per jaar af van de index: niet geloofwaardig "
                               "voor een indexfonds, tracking difference niet gebruikt (kosten tellen in de plaats)")
                m.raw["implausible_tracking_difference"] = td.values[a.id]
            elif a.id in td.values:
                ref_text = "indexreeks met totaalrendement" if td.reference == "index" else \
                    "mediaan van de ETF's op deze index"
                m.set("tracking_difference", td.values[a.id], f"{td.years} jaar, in euro, t.o.v. {ref_text}")
                m.raw[f"annual_return_{td.years}y"] = td.returns[a.id]
                m.raw["reference_return"] = td.reference_return
            _fact_metric(m, f, "ongoing_charges", "ongoing_charges", "lopende kosten (bestand)")
            _fact_metric(m, f, "fund_size_eur", "fund_size", "fondsomvang (bestand)")
            _fact_metric(m, f, "top10_weight", "top10_weight", "tien grootste posities (Yahoo)")
            _fact_metric(m, f, "index_constituents", "index_breadth", "aantal aandelen in de index (bestand)")
            vol, close = data.volume.get(a.id), data.closes_eur.get(a.id)
            if vol is not None and close is not None:
                turnover = (vol * close).loc[data.as_of - timedelta(days=45):data.as_of].dropna()
                if len(turnover) >= 10:
                    m.set("daily_turnover", float(turnover.tail(30).mean()),
                          "gemiddelde dagomzet op deze beurs (Yahoo)")
            c = a.categories
            replication = c.get("replication")
            if group is not None:
                if not group.us_dividends:
                    m.set("domicile_tax_score", 0.0, "geen Amerikaanse dividenden in de index")
                elif replication == "synthetic":
                    m.set("domicile_tax_score", 0.0, "synthetisch: geen bronbelasting op Amerikaanse dividenden")
                elif tax.get(c.get("domicile")) is not None:
                    m.set("domicile_tax_score", -float(tax[c["domicile"]]),
                          f"bronbelasting VS-dividend bij domicilie {c['domicile']}")
                else:
                    m.notes.append(f"fiscale behandeling bij domicilie {c.get('domicile')} niet geverifieerd")
            if s.etf and replication in s.etf.replication_scores:
                m.set("replication_score", s.etf.replication_scores[replication], f"replicatie: {replication}")
            if s.etf and c.get("securities_lending") in s.etf.lending_scores:
                m.set("securities_lending_score", s.etf.lending_scores[c["securities_lending"]],
                      f"uitlenen van effecten: {c['securities_lending']}")
            if preference in ("accumulating", "distributing") and c.get("distribution") in ("acc", "dist"):
                wanted = "acc" if preference == "accumulating" else "dist"
                m.set("distribution_policy_score", 1.0 if c["distribution"] == wanted else 0.5,
                      f"{'herbeleggend' if c['distribution'] == 'acc' else 'uitkerend'}; voorkeur {preference}")
            if c.get("launch_date"):
                launched = date.fromisoformat(c["launch_date"])
                m.set("fund_age", (data.as_of - launched).days / 365.25, f"start {launched:%d-%m-%Y}")
            m.flags["leveraged_or_inverse"] = c.get("leveraged_inverse") == "yes"
            m.flags["no_eu_kid"] = False   # every fund in the file is a UCITS fund with a KID
            if underlying:
                m.raw["underlying_timing"] = underlying.get("timing")
                m.raw["underlying_score"] = underlying.get("score")
                m.notes.append(f"Timing van de index ({group.name}): "
                               + (f"{underlying['timing']:.0f}" if underlying.get("timing") is not None else "–"))
            p = Prepared(a.id, a.slug, "etf", [], m, price_eur=_last_eur(data, a.id), peer_key=group_key)
            out.append(p)
    return out


def _fact_metric(m: Metrics, facts: dict, field_name: str, metric: str, label: str) -> None:
    if field_name in facts:
        as_of, value = facts[field_name]
        m.set(metric, value, f"{label}, {as_of:%d-%m-%Y}")


# --- bond ETFs ------------------------------------------------------------------------------------

RATINGS = ["aaa", "aa", "a", "bbb", "bb", "b", "ccc_lower", "nr"]


def govt_yield(data: MarketData, currency: str, duration: float) -> float | None:
    """Government yield of the same currency at the fund's duration (straight line between 2 and 10 years)."""
    short, long = ("DGS2", "DGS10") if currency == "USD" else ("EA_AAA_2Y", "EA_AAA_10Y")
    s, lng = data.macro.get(short), data.macro.get(long)
    if s is None or lng is None or s.empty or lng.empty:
        return None
    y2, y10 = float(s.iloc[-1]) / 100, float(lng.iloc[-1]) / 100
    w = min(max((duration - 2) / 8, 0.0), 1.0)
    return y2 + w * (y10 - y2)


# Government curves per currency: (stored series, maturity in years). US from the Treasury, euro area AAA from
# the ECB. A curve counts when at least four points are fresh and the shortest is a year or less.
CURVES = {
    "USD": [("UST_3M", 0.25), ("UST_6M", 0.5), ("UST_1Y", 1.0), ("UST_2Y", 2.0), ("UST_3Y", 3.0), ("UST_5Y", 5.0),
            ("UST_7Y", 7.0), ("UST_10Y", 10.0), ("UST_20Y", 20.0), ("UST_30Y", 30.0)],
    "EUR": [("EA_AAA_3M", 0.25), ("EA_AAA_1Y", 1.0), ("EA_AAA_2Y", 2.0), ("EA_AAA_5Y", 5.0), ("EA_AAA_10Y", 10.0),
            ("EA_AAA_20Y", 20.0), ("EA_AAA_30Y", 30.0)],
}
CURVE_STALE_DAYS = 10


def curve_points(data: MarketData, currency: str) -> list[tuple[float, float]] | None:
    """[(maturity in years, yield in percent)] of the latest government curve, or None."""
    points = []
    for sid, years in CURVES.get(currency, []):
        s = data.macro.get(sid)
        if s is not None and not s.empty and (data.as_of - s.index[-1]).days <= CURVE_STALE_DAYS:
            points.append((years, float(s.iloc[-1])))
    return points if len(points) >= 4 and points[0][0] <= 1.0 else None


def yield_at(points: list[tuple[float, float]], years: float) -> float:
    """Straight line between curve points; flat beyond the shortest and longest maturity."""
    return float(np.interp(years, [p[0] for p in points], [p[1] for p in points]))


def curve_position(points: list[tuple[float, float]], duration: float) -> float:
    """How attractive the fund's spot on the curve is (chapter 6, Obligatie, renterisico): the yearly carry
    (yield at the duration minus the shortest yield) plus the roll-down (the price gain as the bonds age along
    the curve), per year of duration. In percentage points: how far yields could rise in a year before the
    position does worse than cash. A steep curve at the fund's maturity scores high, an inverted one low."""
    step = min(1.0, duration / 2)
    y = yield_at(points, duration)
    carry = y - points[0][1]
    roll = duration * (y - yield_at(points, duration - step)) / step
    return (carry + roll) / duration


def prepare_bonds(data: MarketData, config: ModelConfig) -> list[Prepared]:
    s = config.settings.bond
    out = []
    for a in (x for x in data.assets if x.asset_class == "bond"):
        m = Metrics()
        f = data.facts.get(a.id, {})
        c = a.categories
        tags = ["government"] if c.get("category") == "government" else []
        portfolio_date = f.get("yield_to_maturity", (None,))[0]
        stale = portfolio_date is None or (s and (data.as_of - portfolio_date).days > s.stale_days)
        if stale and portfolio_date is not None:
            m.notes.append(f"portefeuillecijfers van {portfolio_date:%d-%m-%Y} zijn te oud en tellen niet mee")
        if not stale and s:
            ytm = f["yield_to_maturity"][1]
            src = f"bestand, {portfolio_date:%d-%m-%Y}"
            weights = {r: f[f"rating_{r}"][1] for r in RATINGS if f"rating_{r}" in f}
            total = sum(weights.values())
            loss = None
            if total >= 0.8:     # at least 80% of the fund has a rating split
                loss = sum(w * s.expected_loss_pct[r] / 100 for r, w in weights.items()) / total
                m.set("rating_quality", sum(w * s.rating_points[r] for r, w in weights.items()) / total, src)
                m.raw["expected_default_loss"] = loss
            ter = f.get("ongoing_charges", (None, None))[1]
            if loss is not None and ter is not None:
                m.set("expected_net_yield", ytm - loss - ter, f"rendement {ytm:.2%} min wanbetaling en kosten; {src}")
            duration = f.get("duration", (None, None))[1]
            currency = c.get("fund_currency") or "USD"   # currency of the bonds, or of the hedge
            if duration is not None:
                m.set("duration", duration, src)
                if duration >= 0.25:
                    m.set("yield_per_duration", ytm / duration, src)
                    points = curve_points(data, currency)
                    if points is not None:
                        m.set("curve_position_score", curve_position(points, duration),
                              f"carry en roll-down per jaar duration, staatscurve {currency} "
                              f"({'US Treasury' if currency == 'USD' else 'ECB AAA'})")
            if "government" in tags and currency == "USD":
                be = data.macro.get("T10YIE" if (duration or 0) > 7 else "T5YIE")
                if be is not None and not be.empty:
                    m.set("real_yield", ytm - float(be.iloc[-1]) / 100, "rendement min verwachte inflatie (FRED)")
            if loss is not None and loss >= 0.0005 and duration is not None:
                gov = govt_yield(data, currency, duration)
                if gov is not None:
                    m.set("spread_per_default_risk", (ytm - gov) / loss,
                          "opslag t.o.v. staat, gedeeld door verwacht verlies")
            _fact_metric(m, f, "issuer_concentration", "issuer_concentration", "tien grootste uitgevers (bestand)")
        _fact_metric(m, f, "ongoing_charges", "ongoing_charges", "lopende kosten (bestand)")
        p = Prepared(a.id, a.slug, "bond", tags, m, price_eur=_last_eur(data, a.id), peer_key=c.get("category"))
        out.append(p)
    # Timing for bond funds (chapter 7): the trend of the fund price, which moves against its yield. Shown as
    # Timing only; the bond template has no trend pillar, so it does not enter the score.
    _technical(out, data, config, benchmark_slug="", eur=True)
    return out


# --- run ------------------------------------------------------------------------------------------

def grade_markets(sf: sessionmaker[Session], config: ModelConfig, model_version_id: int, markets: MarketsConfig,
                  as_of: date, knowledge: datetime | None = None, sink: SnapshotSink = LIVE) -> Report:
    """Indices first (ETFs show the Timing of their index), then ETFs and bond ETFs."""
    report = Report()
    knowledge = knowledge or datetime.now(UTC)
    with sf() as session:
        data = load_market_data(session, as_of, knowledge, model_version_id, sink)
    write_snapshots(sf, prepare_indices(data, config), config, model_version_id, as_of, knowledge, report, sink)
    with sf() as session:
        data = load_market_data(session, as_of, knowledge, model_version_id, sink)
    write_snapshots(sf, prepare_etfs(data, config, markets), config, model_version_id, as_of, knowledge, report, sink)
    write_snapshots(sf, prepare_bonds(data, config), config, model_version_id, as_of, knowledge, report, sink)
    return report
