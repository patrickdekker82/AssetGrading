"""Daily stock grading: SEC facts and prices known at `knowledge` -> metrics -> technical score ->
percentiles within the sector -> engine -> grade_snapshot.

Prices are used in the stock's own currency (a US trend in dollars, an AEX trend in euros), compared with
the index of its own market. Market value is converted to the reporting currency of the company's
filings with the ECB rate of that day.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.grading.assign import assign_stock
from app.grading.crypto import Prepared, write_snapshots
from app.grading.crypto_inputs import Metrics
from app.grading.fundamentals import (
    FactTable,
    current_and_prior,
    fundamental_metrics,
    valuation_inputs,
    valuation_metrics,
)
from app.grading.technical import TechRaw, tech_raw, tech_scores
from app.ingest.report import Report
from app.modelconfig import ModelConfig
from app.stocks_config import StocksConfig

log = logging.getLogger("graadmeter.grading")

PRICE_HISTORY_YEARS = 5
BETA_WEEKS, BETA_MIN_WEEKS = 156, 100
VOL_DAYS, VOL_MIN_DAYS = 365, 200
OWN_HISTORY_METRICS = ["ebit_to_ev", "fcf_yield", "shareholder_yield", "earnings_yield", "dividend_yield"]
MIN_REGRESSION_POINTS = 5


@dataclass
class StockRow:
    id: int
    slug: str
    symbol: str
    sic: int | None
    benchmark: str          # slug of the index the stock is compared with
    multiplier: float = 1.0


@dataclass
class StockData:
    as_of: date
    knowledge: datetime
    stocks: list[StockRow]
    facts: dict[int, pd.DataFrame]            # sec facts, all versions: field, as_of, value, unit, available_at
    raw_closes: dict[int, pd.Series]          # close as traded, by date
    raw_currency: dict[int, str]
    closes: dict[int, pd.Series]              # adjusted, own currency
    closes_eur: dict[int, float]              # last euro close
    benchmarks: dict[str, pd.Series]
    fx: pd.DataFrame                          # index date, columns currency -> units per EUR
    manual_shares: dict[int, list[tuple[datetime, float]]] = field(default_factory=dict)  # (known from, count)

    def rate(self, currency: str, day: date) -> float | None:
        if currency == "EUR":
            return 1.0
        if currency not in self.fx.columns:
            return None
        s = self.fx[currency].loc[:day].dropna()
        return None if s.empty else float(s.iloc[-1])

    def convert(self, amount: float, from_ccy: str, to_ccy: str, day: date) -> float | None:
        a, b = self.rate(from_ccy, day), self.rate(to_ccy, day)
        return None if a is None or b is None else amount / a * b


def load_stock_data(session: Session, stocks_cfg: StocksConfig, as_of: date, knowledge: datetime) -> StockData:
    conn = session.connection()
    start = as_of - timedelta(days=365 * PRICE_HISTORY_YEARS)
    params = {"d": as_of, "k": knowledge, "start": start}
    us_bench, aex_bench = stocks_cfg.us.benchmark.slug, stocks_cfg.aex.benchmark.slug
    multipliers = {t.lower(): m for t, m in stocks_cfg.us.share_multiplier.items()}
    rows = session.execute(text(
        """
        SELECT a.id, a.slug, a.symbol, a.categories,
               bool_or(al.kind = 'us_ticker') AS us
        FROM asset a LEFT JOIN asset_alias al ON al.asset_id = a.id
        WHERE a.asset_class = 'stock' AND a.tracked
        GROUP BY a.id ORDER BY a.id
        """
    )).all()
    stocks = []
    for r in rows:
        sic = next((int(c[4:]) for c in (r.categories or []) if isinstance(c, str) and c.startswith("sic:")), None)
        stocks.append(StockRow(r.id, r.slug, r.symbol, sic, us_bench if r.us else aex_bench,
                               multipliers.get(r.slug, 1.0)))

    facts_df = pd.read_sql(text(
        """
        SELECT asset_id, field, as_of, value::float8 AS value, unit, available_at
        FROM fundamental_fact
        WHERE source = 'sec' AND available_at <= :k AND as_of <= :d
        ORDER BY asset_id, available_at, id
        """
    ), conn, params=params)
    facts = {int(k): g.drop(columns="asset_id") for k, g in facts_df.groupby("asset_id")}

    raw = pd.read_sql(text(
        """
        SELECT DISTINCT ON (asset_id, as_of) asset_id, as_of, value::float8 AS value, unit
        FROM fundamental_fact
        WHERE field = 'close_raw' AND available_at <= :k AND as_of <= :d AND as_of >= :start
        ORDER BY asset_id, as_of, available_at DESC, id DESC
        """
    ), conn, params=params)
    raw_closes, raw_currency = {}, {}
    for k, g in raw.groupby("asset_id"):
        raw_closes[int(k)] = pd.Series(g["value"].to_numpy(), index=pd.to_datetime(g["as_of"]).dt.date)
        raw_currency[int(k)] = str(g["unit"].iloc[-1])

    prices = pd.read_sql(text(
        """
        SELECT p.asset_id, p.ts, p.close_native::float8 AS close, p.close_eur::float8 AS close_eur, a.slug
        FROM price_daily_eur p JOIN asset a ON a.id = p.asset_id
        WHERE a.asset_class IN ('stock', 'index') AND p.ts <= :d AND p.ts >= :start
        ORDER BY p.asset_id, p.ts
        """
    ), conn, params=params)
    closes, closes_eur, benchmarks = {}, {}, {}
    for (k, slug), g in prices.groupby(["asset_id", "slug"]):
        s = pd.Series(g["close"].to_numpy(), index=pd.to_datetime(g["ts"]).dt.date)
        closes[int(k)] = s
        closes_eur[int(k)] = float(g["close_eur"].iloc[-1])
        if slug in (us_bench, aex_bench):
            benchmarks[slug] = s

    manual: dict[int, list[tuple[datetime, float]]] = {}
    for r in session.execute(text(
        "SELECT asset_id, available_at, value::float8 AS value FROM fundamental_fact "
        "WHERE source = 'manual' AND field = 'shares_outstanding' AND available_at <= :k ORDER BY available_at"
    ), params):
        manual.setdefault(r.asset_id, []).append((r.available_at, r.value))

    fx = pd.read_sql(text(
        "SELECT date, quote, rate::float8 AS rate FROM fx_rate WHERE base = 'EUR' AND date <= :d "
        "AND date >= :fx_start ORDER BY date"
    ), conn, params={**params, "fx_start": start - timedelta(days=400)})
    fx_table = fx.pivot(index="date", columns="quote", values="rate") if not fx.empty else pd.DataFrame()
    if not fx_table.empty:
        fx_table.index = pd.to_datetime(fx_table.index).date
    return StockData(as_of, knowledge, stocks, facts, raw_closes, raw_currency, closes, closes_eur, benchmarks,
                     fx_table, manual)


def manual_share_count(data: StockData, asset_id: int, day: date) -> float | None:
    """Share count entered by hand (set-fact), from the day it was entered."""
    known = [v for t, v in data.manual_shares.get(asset_id, []) if t.date() <= day]
    return known[-1] if known else None


def reporting_currency(df: pd.DataFrame) -> str | None:
    money = df[df["field"].str.startswith(("revenue:", "net_income:", "total_assets:"))]
    return None if money.empty else str(money["unit"].mode().iloc[0])


def fact_table(df: pd.DataFrame, knowledge: datetime | None = None) -> FactTable:
    if knowledge is not None:
        df = df[df["available_at"] <= knowledge]
    return FactTable.from_rows(zip(df["field"], df["as_of"], df["value"], strict=True))


@dataclass
class MarketValue:
    report_ccy: str
    value: float | None = None       # in the reporting currency
    note: str | None = None


def market_value(data: StockData, s: StockRow, t: FactTable, df: pd.DataFrame, day: date) -> MarketValue:
    ccy = reporting_currency(df) or "USD"
    out = MarketValue(ccy)
    c, _ = current_and_prior(t, day)
    closes = data.raw_closes.get(s.id)
    shares = (c["shares"] if c is not None else None) or manual_share_count(data, s.id, day)
    if c is None or not shares or closes is None:
        out.note = "geen aantal aandelen of koers"
        return out
    known = closes.loc[:day]
    if known.empty or (day - known.index[-1]).days > 7:
        out.note = "geen recente koers"
        return out
    native = shares * s.multiplier * float(known.iloc[-1])
    out.value = data.convert(native, data.raw_currency[s.id], ccy, day)
    if out.value is None:
        out.note = f"geen wisselkoers voor {data.raw_currency[s.id]}/{ccy}"
    return out


def beta_and_volatility(closes: pd.Series | None, bench: pd.Series | None,
                        as_of: date) -> tuple[float | None, float | None]:
    if closes is None or closes.empty:
        return None, None
    c = closes.loc[:as_of]
    vol = None
    daily = c.loc[as_of - timedelta(days=VOL_DAYS):]
    rets = np.log(daily.astype(float)).diff().dropna()
    if len(rets) >= VOL_MIN_DAYS:
        vol = float(rets.std(ddof=1) * math.sqrt(252))
    beta = None
    if bench is not None and not bench.empty:
        idx = pd.to_datetime(pd.Index(c.index))
        weekly = pd.Series(c.to_numpy(dtype=float), index=idx).resample("W-FRI").last()
        b = bench.loc[:as_of]
        bweekly = pd.Series(b.to_numpy(dtype=float), index=pd.to_datetime(pd.Index(b.index))).resample("W-FRI").last()
        joined = pd.concat([weekly, bweekly], axis=1, keys=["a", "b"]).dropna().iloc[-(BETA_WEEKS + 1):]
        r = np.log(joined).diff().dropna()
        if len(r) >= BETA_MIN_WEEKS and r["b"].var(ddof=1) > 0:
            beta = float(r["a"].cov(r["b"]) / r["b"].var(ddof=1))
    return beta, vol


def valuation_history(data: StockData, s: StockRow, df: pd.DataFrame, years: float) -> dict[str, pd.Series]:
    """Daily valuation metrics over the past `years` as they were known on each day: the filing figures
    change at each filing, the market value every day."""
    as_of = data.as_of
    start = as_of - timedelta(days=int(years * 365))
    closes = data.raw_closes.get(s.id)
    if closes is None or df.empty:
        return {}
    closes = closes.loc[start:as_of]
    ccy = reporting_currency(df) or "USD"
    epochs = sorted({t for t in df["available_at"] if t.date() <= as_of})
    # The figures known on day d come from the last filing moment before the end of day d.
    epoch_dates = [e.date() for e in epochs]
    cache: dict[int, dict | None] = {}
    out: dict[str, list[tuple[date, float]]] = {m: [] for m in OWN_HISTORY_METRICS}
    fx_ok = ccy == data.raw_currency.get(s.id)
    for d, price in closes.items():
        i = int(np.searchsorted(epoch_dates, d, side="left")) - 1
        if i < 0:
            continue
        if i not in cache:
            t = fact_table(df, epochs[i])
            c, _ = current_and_prior(t, d)
            cache[i] = None if c is None else valuation_inputs(c)
        vi = cache[i]
        shares = (vi or {}).get("shares") or manual_share_count(data, s.id, d)
        if vi is None or not shares:
            continue
        mv = shares * s.multiplier * float(price)
        if not fx_ok:
            mv = data.convert(mv, data.raw_currency[s.id], ccy, d)
            if mv is None:
                continue
        for k, v in valuation_metrics(vi, mv).items():
            if k in out and v is not None:
                out[k].append((d, v))
    return {k: pd.Series(dict(v)) for k, v in out.items() if v}


@dataclass
class StockPrepared:
    p: Prepared
    row: StockRow
    sector: str
    raw_tech: TechRaw | None = None
    extra: dict = field(default_factory=dict)


def prepare(data: StockData, config: ModelConfig) -> list[Prepared]:
    years = config.settings.peers.own_history_years
    items: list[StockPrepared] = []
    for s in data.stocks:
        template_id, tags, sector = assign_stock(s.slug, s.sic, config.assignment)
        m = Metrics()
        df = data.facts.get(s.id)
        if df is None or df.empty:
            m.notes.append("geen jaarcijfers beschikbaar uit een gratis bron (geen SEC-registratie)")
        else:
            t = fact_table(df)
            mv = market_value(data, s, t, df, data.as_of)
            res = fundamental_metrics(t, data.as_of, mv.value)
            src = f"SEC-cijfers t/m {res.period_end:%d-%m-%Y}" if res.period_end else "SEC"
            for k, v in res.values.items():
                m.set(k, v, src)
            m.raw.update(res.raw)
            m.notes.append(f"cijfers in {mv.report_ccy}")
            m.notes += ([f"beurswaarde: {mv.note}"] if mv.note else []) + res.notes
            for k, series in valuation_history(data, s, df, years).items():
                m.history[k] = series
            c, _ = current_and_prior(t, data.as_of)
            if c is not None:
                vi = valuation_inputs(c)
                if (vi["tce"] or 0) > 0 and mv.value:
                    m.raw["ptbv"] = mv.value / vi["tce"]
                    m.raw["rotce"] = res.values.get("rotce")
        beta, vol = beta_and_volatility(data.closes.get(s.id), data.benchmarks.get(s.benchmark), data.as_of)
        m.set("beta", beta, f"weekrendementen 3 jaar t.o.v. {s.benchmark}")
        m.set("volatility", vol, "dagrendementen 1 jaar")
        p = Prepared(s.id, s.slug, template_id, tags, m, price_eur=data.closes_eur.get(s.id), peer_key=sector)
        items.append(StockPrepared(p, s, sector))
    _ptbv_vs_rotce(items, config)
    _technical(items, data, config)
    return [i.p for i in items]


def _ptbv_vs_rotce(items: list[StockPrepared], config: ModelConfig) -> None:
    """Price/tangible book against return on tangible equity: a line fitted through the comparison group
    gives the price/book each return would justify; the metric is how far the actual price/book is below
    it (0.2 = 20% cheaper than its return suggests)."""
    fin = [i for i in items if i.p.template_id == "stock_financial"
           and i.p.metrics.raw.get("ptbv") is not None and i.p.metrics.raw.get("rotce") is not None]
    for i in fin:
        sector = [j for j in fin if j.sector == i.sector]
        group = sector if len(sector) >= config.settings.peers.min_group_size else fin
        if len(group) < MIN_REGRESSION_POINTS:
            continue
        x = np.array([j.p.metrics.raw["rotce"] for j in group])
        y = np.array([j.p.metrics.raw["ptbv"] for j in group])
        if np.ptp(x) == 0:
            continue
        slope, intercept = np.polyfit(x, y, 1)
        justified = intercept + slope * i.p.metrics.raw["rotce"]
        if justified > 0:
            i.p.metrics.set("ptbv_vs_rotce", justified / i.p.metrics.raw["ptbv"] - 1,
                            f"lijn door {len(group)} financials: P/TBV = {intercept:.2f} + {slope:.2f} x ROTCE")
            i.p.metrics.raw["ptbv_justified"] = float(justified)


def _technical(items: list[StockPrepared], data: StockData, config: ModelConfig) -> None:
    params = config.technical.params["stocks"]
    raws = {}
    for i in items:
        closes = data.closes.get(i.row.id)
        if closes is None:
            continue
        raws[i.row.id] = tech_raw(closes, data.benchmarks.get(i.row.benchmark), params, data.as_of)
    scores = tech_scores(raws, config.technical.blocks, params)
    for i in items:
        if i.row.id in scores:
            res = scores[i.row.id]
            i.p.metrics.set("technical_score", res.score, "technische score (hoofdstuk 7)")
            i.p.technical = res.to_dict()


def grade_stocks(sf: sessionmaker[Session], config: ModelConfig, model_version_id: int, stocks_cfg: StocksConfig,
                 as_of: date, knowledge: datetime | None = None) -> Report:
    report = Report()
    knowledge = knowledge or datetime.now(UTC)
    with sf() as session:
        data = load_stock_data(session, stocks_cfg, as_of, knowledge)
    prepared = prepare(data, config)
    write_snapshots(sf, prepared, config, model_version_id, as_of, knowledge, report)
    return report
