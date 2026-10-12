"""Technical score (chapter 7). Pure functions on daily closes in euro.

Blocks: trend state (absolute tests), momentum, distance to the 52-week high and relative strength
(percentiles within the asset class), volatility (against the asset's own history). Oscillators are
chart context only and never enter the score.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
import talib

from app.grading.percentiles import percentile_of
from app.modelconfig.schema import TechnicalBlock, TechnicalParams

STALE_DAYS = 3


@dataclass
class TechRaw:
    trend_tests: dict[str, bool] = field(default_factory=dict)
    momentum_long: float | None = None    # 12-month return skipping the last month, divided by volatility
    momentum_short: float | None = None   # 6-month return divided by volatility
    distance_to_high: float | None = None  # close / highest close of the past 52 weeks
    relative: float | None = None         # mean excess return over the benchmark (3, 6, 12 months)
    volatility_score: float | None = None  # 100 - percentile of current volatility in own history
    note: str | None = None

    @property
    def trend_state(self) -> float | None:
        return 100 * sum(self.trend_tests.values()) / len(self.trend_tests) if self.trend_tests else None


@dataclass
class TechResult:
    score: float | None
    coverage: float
    blocks: dict[str, float | None]
    raw: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _at(closes: pd.Series, day: date) -> float | None:
    """Last close on or before `day`; None when the series starts later."""
    sub = closes.loc[:day]
    return None if sub.empty else float(sub.iloc[-1])


def _window(closes: pd.Series, end: date, days: int) -> pd.Series:
    return closes.loc[end - timedelta(days=days - 1):end]


def _ann_vol(closes: pd.Series, days_per_year: int = 365) -> float | None:
    rets = np.log(closes.astype(float)).diff().dropna()
    if len(rets) < 20:
        return None
    return float(rets.std(ddof=1) * math.sqrt(days_per_year))


def tech_raw(closes: pd.Series, benchmark: pd.Series | None, p: TechnicalParams, as_of: date) -> TechRaw:
    """Per-asset inputs. `closes` is indexed by date (ascending), values in euro."""
    closes = closes.loc[:as_of].astype(float)
    raw = TechRaw()
    if closes.empty or (as_of - closes.index[-1]).days > STALE_DAYS:
        raw.note = "geen recente koers"
        return raw
    last = float(closes.iloc[-1])
    values = closes.to_numpy(dtype=np.float64)

    if len(values) >= p.sma_long + p.sma_long_rising_lag:
        sma_long = talib.SMA(values, timeperiod=p.sma_long)
        sma_short = talib.SMA(values, timeperiod=p.sma_short)
        months = pd.Series([d.year * 100 + d.month for d in closes.index], index=closes.index)
        monthly = closes.groupby(months).last()  # month-end closes (the current month: latest close)
        tests = {
            "price_above_sma200": last > sma_long[-1],
            "sma50_above_sma200": sma_short[-1] > sma_long[-1],
            "sma200_rising": sma_long[-1] > sma_long[-1 - p.sma_long_rising_lag],
        }
        if len(monthly) >= p.months_for_10m_average:
            tests["price_above_sma_10m"] = last > float(monthly.iloc[-p.months_for_10m_average:].mean())
        raw.trend_tests = {k: bool(v) for k, v in tests.items()}

    start_long = _at(closes, as_of - timedelta(days=p.momentum_long))
    if start_long is not None and closes.index[0] <= as_of - timedelta(days=p.momentum_long):
        end_skip = _at(closes, as_of - timedelta(days=p.momentum_skip))
        vol = _ann_vol(_window(closes, as_of, p.momentum_long), p.days_per_year)
        if end_skip is not None and vol:
            raw.momentum_long = (end_skip / start_long - 1) / vol
    if closes.index[0] <= as_of - timedelta(days=p.momentum_short):
        start_short = _at(closes, as_of - timedelta(days=p.momentum_short))
        vol = _ann_vol(_window(closes, as_of, p.momentum_short), p.days_per_year)
        if start_short and vol:
            raw.momentum_short = (last / start_short - 1) / vol

    if closes.index[0] <= as_of - timedelta(days=p.high_window - 1):
        raw.distance_to_high = last / float(_window(closes, as_of, p.high_window).max())

    if benchmark is not None and not benchmark.empty:
        bench = benchmark.loc[:as_of].astype(float)
        excess = []
        for w in p.relative_windows:
            start_day = as_of - timedelta(days=w)
            if closes.index[0] > start_day or bench.index[0] > start_day:
                continue
            a0, b0, b1 = _at(closes, start_day), _at(bench, start_day), _at(bench, as_of)
            if a0 and b0 and b1:
                excess.append((last / a0 - 1) - (b1 / b0 - 1))
        if excess:
            raw.relative = sum(excess) / len(excess)

    if closes.index[0] <= as_of - timedelta(days=p.volatility_window + 365):
        hist = _window(closes, as_of, p.volatility_history + p.volatility_window)
        rets = np.log(hist).diff()
        # Window and minimum history in trading rows: 91 calendar days of a stock are about 63 rows.
        rows = max(20, round(p.volatility_window * p.days_per_year / 365))
        rolling = (rets.rolling(rows).std(ddof=1) * math.sqrt(p.days_per_year)).dropna()
        if len(rolling) >= p.days_per_year:
            current = float(rolling.iloc[-1])
            pct = percentile_of(current, rolling.tolist(), higher_is_better=True)
            raw.volatility_score = 100 - pct
    return raw


def tech_scores(raws: dict[int, TechRaw], blocks: list[TechnicalBlock], p: TechnicalParams) -> dict[int, TechResult]:
    """Combine per-asset inputs into scores; class-relative blocks use percentiles within `raws`."""
    def pct_map(attr: str) -> dict[int, float]:
        vals = {k: getattr(r, attr) for k, r in raws.items() if getattr(r, attr) is not None}
        group = list(vals.values())
        return {k: percentile_of(v, group, higher_is_better=True) for k, v in vals.items()}

    mom_long, mom_short = pct_map("momentum_long"), pct_map("momentum_short")
    dist, rel = pct_map("distance_to_high"), pct_map("relative")
    out = {}
    weights = {b.id: b.weight for b in blocks}
    for k, r in raws.items():
        moms = [x for x in (mom_long.get(k), mom_short.get(k)) if x is not None]
        block_scores = {
            "trend_state": r.trend_state,
            "momentum": sum(moms) / len(moms) if moms else None,
            "distance_to_high": dist.get(k),
            "relative_strength": rel.get(k),
            "volatility": r.volatility_score,
        }
        available = {b: s for b, s in block_scores.items() if s is not None}
        coverage = sum(weights[b] for b in available) / sum(weights.values())
        score = None
        if available and coverage >= p.min_block_coverage:
            score = sum(weights[b] * s for b, s in available.items()) / sum(weights[b] for b in available)
        out[k] = TechResult(score=score, coverage=coverage, blocks=block_scores, raw=asdict(r))
    return out
