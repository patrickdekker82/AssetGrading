"""Chart data (chapter 7): candles in euro, indicators computed on the server, aggregated per interval.

Indicators are computed on daily data and then sampled at the end of each week or month, so a 200-day
average means the same in every view. Weekly RSI is computed on weekly closes, as the spec asks.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib


@dataclass(frozen=True)
class IndicatorDef:
    id: str
    label_nl: str
    pane: str          # "price" = drawn over the candles, otherwise the name of a separate pane
    group: str         # "score" = used in the technical score, "context" = chart only
    color: str


CRYPTO_INDICATORS = [
    IndicatorDef("sma50", "Gemiddelde 50 dagen", "price", "score", "#2962ff"),
    IndicatorDef("sma200", "Gemiddelde 200 dagen", "price", "score", "#e91e63"),
    IndicatorDef("sma20w", "Gemiddelde 20 weken", "price", "score", "#ff9800"),
    IndicatorDef("ema21w", "EMA 21 weken", "price", "score", "#fbc02d"),
    IndicatorDef("sma200w", "Gemiddelde 200 weken", "price", "score", "#7b1fa2"),
    IndicatorDef("mayer_multiple", "Mayer-multiple", "mayer", "score", "#00897b"),
    IndicatorDef("rs_btc", "Sterkte t.o.v. Bitcoin", "rs", "score", "#5d4037"),
    IndicatorDef("rsi14w", "RSI 14 (week)", "rsi", "context", "#6a1b9a"),
    IndicatorDef("rvol30", "Gerealiseerde volatiliteit 30 dagen", "vol", "context", "#c62828"),
    IndicatorDef("rvol90", "Gerealiseerde volatiliteit 90 dagen", "vol", "context", "#ef6c00"),
    IndicatorDef("atr_pct", "ATR 14 in %", "atr", "context", "#455a64"),
    IndicatorDef("funding", "Funding rate (8 uur)", "funding", "context", "#1565c0"),
    IndicatorDef("open_interest", "Open interest (USD)", "oi", "context", "#2e7d32"),
]

DEFAULT_ON = {"sma50", "sma200", "sma20w", "sma200w"}

# Stocks: technical.yaml chart_sets.stocks. A sector index (rs_sector) and an earnings-anchored VWAP need
# data no free source offers; they are left out rather than approximated.
STOCK_INDICATORS = [
    IndicatorDef("sma50", "Gemiddelde 50 dagen", "price", "score", "#2962ff"),
    IndicatorDef("sma200", "Gemiddelde 200 dagen", "price", "score", "#e91e63"),
    IndicatorDef("sma10w", "Gemiddelde 10 weken", "price", "score", "#ff9800"),
    IndicatorDef("sma40w", "Gemiddelde 40 weken", "price", "score", "#7b1fa2"),
    IndicatorDef("mom_12_1", "Momentum 12-1 maanden (%)", "mom", "score", "#00897b"),
    IndicatorDef("dist_52w_high", "Afstand tot 52-weekshoogte (%)", "high", "score", "#5d4037"),
    IndicatorDef("rs_index", "Sterkte t.o.v. index", "rs", "score", "#3949ab"),
    IndicatorDef("rsi14", "RSI 14", "rsi", "context", "#6a1b9a"),
    IndicatorDef("macd", "MACD 12-26", "macd", "context", "#1565c0"),
    IndicatorDef("macd_signal", "MACD-signaallijn 9", "macd", "context", "#ef6c00"),
    IndicatorDef("volume_vs_sma50", "Volume t.o.v. 50-daags gemiddelde", "volume_ratio", "context", "#2e7d32"),
    IndicatorDef("atr_pct", "ATR 14 in %", "atr", "context", "#455a64"),
    IndicatorDef("bb_upper", "Bollinger boven (20, 2)", "price", "context", "#90a4ae"),
    IndicatorDef("bb_lower", "Bollinger onder (20, 2)", "price", "context", "#90a4ae"),
]

STOCK_DEFAULT_ON = {"sma50", "sma200"}


def stock_indicators(ohlc: pd.DataFrame, benchmark: pd.Series | None) -> dict[str, pd.Series]:
    """`ohlc` in the stock's own currency, adjusted for splits and dividends."""
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    weekly = week_end(close)
    w = weekly.to_numpy(dtype=np.float64)
    out: dict[str, pd.Series] = {
        "sma50": _clean(talib.SMA(c, 50), close.index),
        "sma200": _clean(talib.SMA(c, 200), close.index),
        "sma10w": _clean(talib.SMA(w, 10), weekly.index).reindex(close.index).ffill(),
        "sma40w": _clean(talib.SMA(w, 40), weekly.index).reindex(close.index).ffill(),
        "rsi14": _clean(talib.RSI(c, 14), close.index),
    }
    # 12-1 momentum: return from twelve months ago to one month ago (about 252 and 21 trading days).
    out["mom_12_1"] = (close.shift(21) / close.shift(252) - 1) * 100
    out["dist_52w_high"] = (close / close.rolling(252, min_periods=200).max() - 1) * 100
    if benchmark is not None and not benchmark.empty:
        out["rs_index"] = close / benchmark.reindex(close.index).ffill()
    macd, signal, _ = talib.MACD(c, 12, 26, 9)
    out["macd"], out["macd_signal"] = _clean(macd, close.index), _clean(signal, close.index)
    if "volume" in ohlc and ohlc["volume"].notna().sum() > 50:
        vol = ohlc["volume"].astype(float)
        out["volume_vs_sma50"] = vol / vol.rolling(50).mean()
    if ohlc[["high", "low"]].notna().all(axis=1).sum() > 14:
        hl = ohlc.dropna(subset=["high", "low"])
        atr = talib.ATR(hl["high"].to_numpy(np.float64), hl["low"].to_numpy(np.float64),
                        hl["close"].to_numpy(np.float64), 14)
        out["atr_pct"] = _clean(atr, hl.index) / hl["close"] * 100
    upper, _, lower = talib.BBANDS(c, 20, 2, 2)
    out["bb_upper"], out["bb_lower"] = _clean(upper, close.index), _clean(lower, close.index)
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}


def _clean(values: np.ndarray, index) -> pd.Series:
    s = pd.Series(values, index=index, dtype=float)
    return s.replace([np.inf, -np.inf], np.nan)


def daily_indicators(ohlc: pd.DataFrame, benchmark: pd.Series | None, funding: pd.Series | None,
                     open_interest: pd.Series | None) -> dict[str, pd.Series]:
    """`ohlc` indexed by date with columns open, high, low, close (euro); open/high/low may be NaN."""
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    out: dict[str, pd.Series] = {
        "sma50": _clean(talib.SMA(c, 50), close.index),
        "sma200": _clean(talib.SMA(c, 200), close.index),
        "sma20w": _clean(talib.SMA(c, 140), close.index),
        "ema21w": _clean(talib.EMA(c, 147), close.index),
        "sma200w": _clean(talib.SMA(c, 1400), close.index),
    }
    out["mayer_multiple"] = close / out["sma200"]
    if benchmark is not None and not benchmark.empty:
        aligned = benchmark.reindex(close.index)
        out["rs_btc"] = close / aligned
    log_ret = np.log(close).diff()
    out["rvol30"] = log_ret.rolling(30).std(ddof=1) * math.sqrt(365) * 100
    out["rvol90"] = log_ret.rolling(90).std(ddof=1) * math.sqrt(365) * 100
    if ohlc[["high", "low"]].notna().all(axis=1).sum() > 14:
        hl = ohlc.dropna(subset=["high", "low"])
        atr = talib.ATR(hl["high"].to_numpy(np.float64), hl["low"].to_numpy(np.float64),
                        hl["close"].to_numpy(np.float64), 14)
        out["atr_pct"] = _clean(atr, hl.index) / hl["close"] * 100
    weekly = week_end(close)
    rsi_w = _clean(talib.RSI(weekly.to_numpy(np.float64), 14), weekly.index)
    out["rsi14w"] = rsi_w.reindex(close.index).ffill()
    if funding is not None and not funding.empty:
        out["funding"] = funding * 100   # in percent per funding interval
    if open_interest is not None and not open_interest.empty:
        out["open_interest"] = open_interest
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}


def _period_keys(index, interval: str) -> np.ndarray:
    """Integer period key per date: ISO year*100+week, or year*100+month."""
    if interval == "1w":
        return np.array([d.isocalendar()[0] * 100 + d.isocalendar()[1] for d in index])
    return np.array([d.year * 100 + d.month for d in index])


def _last_dates(index, keys: np.ndarray) -> list:
    last: dict[int, object] = {}
    for d, k in zip(index, keys, strict=True):
        last[k] = d
    return list(last.values())


def week_end(close: pd.Series) -> pd.Series:
    return sample(close, "1w")


def aggregate_ohlc(ohlc: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Daily candles to weekly (ISO weeks) or monthly candles, labelled with the period's last day."""
    if interval == "1d":
        return ohlc
    keys = _period_keys(ohlc.index, interval)
    g = ohlc.groupby(keys, sort=False)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
        "volume": g["volume"].sum(min_count=1),
    })
    out.index = _last_dates(ohlc.index, keys)
    return out


def sample(series: pd.Series, interval: str) -> pd.Series:
    """Value at the end of each period."""
    if interval == "1d" or series.empty:
        return series
    keys = _period_keys(series.index, interval)
    values = series.groupby(keys, sort=False).last().to_numpy()
    return pd.Series(values, index=_last_dates(series.index, keys))


def sig(value: float, digits: int = 7) -> float:
    """Round to significant digits: enough for any chart, much smaller JSON."""
    if value == 0 or not math.isfinite(value):
        return value
    return round(value, digits - 1 - int(math.floor(math.log10(abs(value)))))


def to_points(series: pd.Series, digits: int = 7) -> list[dict]:
    return [{"time": d.isoformat(), "value": sig(float(v), digits)} for d, v in series.items()
            if v is not None and math.isfinite(float(v))]


# Indices and ETFs (technical.yaml chart_sets.indices_etfs).
INDEX_INDICATORS = [
    IndicatorDef("sma200", "Gemiddelde 200 dagen", "price", "score", "#e91e63"),
    IndicatorDef("sma10m", "Gemiddelde 10 maanden", "price", "score", "#7b1fa2"),
    IndicatorDef("drawdown", "Daling vanaf de top (%)", "drawdown", "score", "#c62828"),
    IndicatorDef("rs_index", "Sterkte t.o.v. vergelijking", "rs", "score", "#3949ab"),
    IndicatorDef("vix", "VIX", "vix", "context", "#6a1b9a"),
    IndicatorDef("vix_ratio", "VIX / VIX 3 maanden", "vix_ratio", "context", "#ef6c00"),
    IndicatorDef("breadth", "Aandelen boven 200-daags gemiddelde (%)", "breadth", "context", "#2e7d32"),
]

INDEX_DEFAULT_ON = {"sma200", "sma10m"}

# Bond ETFs (technical.yaml chart_sets.bonds): the price of a bond fund moves against its yield, plus the
# yield curve as context. The MOVE index has no free source and is left out.
BOND_INDICATORS = [
    # Context only: the bond template has no trend pillar; these feed Timing, not the score.
    IndicatorDef("sma200", "Gemiddelde 200 dagen", "price", "context", "#e91e63"),
    IndicatorDef("sma10m", "Gemiddelde 10 maanden", "price", "context", "#7b1fa2"),
    IndicatorDef("drawdown", "Daling vanaf de top (%)", "drawdown", "context", "#c62828"),
    IndicatorDef("curve_us_2_10", "Rentecurve VS 10 jaar min 2 jaar (pp)", "curve", "context", "#1565c0"),
    IndicatorDef("curve_us_3m_10", "Rentecurve VS 10 jaar min 3 maanden (pp)", "curve", "context", "#00897b"),
    IndicatorDef("curve_ea_2_10", "Rentecurve eurozone AAA 10 jaar min 2 jaar (pp)", "curve", "context", "#ef6c00"),
]
BOND_DEFAULT_ON = {"sma200", "curve_us_2_10", "curve_ea_2_10"}


def bond_indicators(ohlc: pd.DataFrame, curves: dict[str, pd.Series]) -> dict[str, pd.Series]:
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    months = sample(close, "1M")
    out: dict[str, pd.Series] = {
        "sma200": _clean(talib.SMA(c, 200), close.index),
        "sma10m": months.rolling(10).mean().reindex(close.index).ffill(),
        "drawdown": (close / close.cummax() - 1) * 100,
    }
    for key, series in curves.items():
        if series is not None and not series.empty:
            out[key] = series.loc[series.index >= close.index[0]]
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}


def index_indicators(ohlc: pd.DataFrame, benchmark: pd.Series | None, vix: pd.Series | None,
                     vix3m: pd.Series | None, breadth: pd.Series | None) -> dict[str, pd.Series]:
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    months = sample(close, "1M")
    out: dict[str, pd.Series] = {
        "sma200": _clean(talib.SMA(c, 200), close.index),
        "sma10m": months.rolling(10).mean().reindex(close.index).ffill(),
        "drawdown": (close / close.cummax() - 1) * 100,
    }
    if benchmark is not None and not benchmark.empty:
        out["rs_index"] = close / benchmark.reindex(close.index).ffill()
    if vix is not None and not vix.empty:
        out["vix"] = vix.loc[vix.index >= close.index[0]]
        if vix3m is not None and not vix3m.empty:
            out["vix_ratio"] = (vix / vix3m).dropna().loc[lambda s: s.index >= close.index[0]]
    if breadth is not None and not breadth.empty:
        out["breadth"] = breadth * 100
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}


# Commodities (technical.yaml chart_sets.commodities). Seasonal line: the average path of the last 15 years
# by calendar month, drawn over the current year; chart context only, it is not in any score.
COMMODITY_INDICATORS = [
    IndicatorDef("donchian20_high", "Donchian 20 hoog", "price", "score", "#90a4ae"),
    IndicatorDef("donchian20_low", "Donchian 20 laag", "price", "score", "#90a4ae"),
    IndicatorDef("donchian55_high", "Donchian 55 hoog", "price", "score", "#546e7a"),
    IndicatorDef("donchian55_low", "Donchian 55 laag", "price", "score", "#546e7a"),
    IndicatorDef("sma50", "Gemiddelde 50 dagen", "price", "score", "#2962ff"),
    IndicatorDef("sma100", "Gemiddelde 100 dagen", "price", "score", "#ff9800"),
    IndicatorDef("sma200", "Gemiddelde 200 dagen", "price", "score", "#e91e63"),
    IndicatorDef("mom12m", "Momentum 12 maanden (%)", "mom", "score", "#00897b"),
    IndicatorDef("adx14", "ADX 14", "adx", "context", "#6a1b9a"),
    IndicatorDef("atr20_pct", "ATR 20 in %", "atr", "context", "#455a64"),
    IndicatorDef("seasonal", "Seizoenslijn (15 jaar)", "price", "context", "#8d6e63"),
    IndicatorDef("cftc_index", "CFTC-index 3 jaar (0-100)", "cftc", "context", "#1565c0"),
]
COMMODITY_DEFAULT_ON = {"sma50", "sma200"}

# ECB reference rates are one fixing a day: ADX, ATR and Ichimoku are computed on those closes (the high and
# low of a day are not published), which the labels say.
FX_INDICATORS = [
    IndicatorDef("ema50", "EMA 50 dagen", "price", "score", "#2962ff"),
    IndicatorDef("ema200", "EMA 200 dagen", "price", "score", "#e91e63"),
    IndicatorDef("mom3m", "Momentum 3 maanden (%)", "mom", "score", "#00897b"),
    IndicatorDef("mom12m", "Momentum 12 maanden (%)", "mom", "score", "#5d4037"),
    IndicatorDef("rate_diff", "Renteverschil 3 maanden (procentpunt)", "rate", "score", "#00695c"),
    IndicatorDef("ichimoku_tenkan", "Ichimoku 9 (slotkoersen)", "price", "context", "#26a69a"),
    IndicatorDef("ichimoku_kijun", "Ichimoku 26 (slotkoersen)", "price", "context", "#ef5350"),
    IndicatorDef("ichimoku_span_a", "Ichimoku wolk A", "price", "context", "#a5d6a7"),
    IndicatorDef("ichimoku_span_b", "Ichimoku wolk B (52)", "price", "context", "#ef9a9a"),
    IndicatorDef("adx14", "ADX 14 (slotkoersen)", "adx", "context", "#6a1b9a"),
    IndicatorDef("atr14_pct", "ATR 14 in % (slotkoersen)", "atr", "context", "#455a64"),
    IndicatorDef("cftc_index", "CFTC-index 3 jaar (0-100)", "cftc", "context", "#1565c0"),
]
FX_DEFAULT_ON = {"ema50", "ema200"}


def _cftc_index(cftc: pd.Series | None, start) -> pd.Series | None:
    """Where the speculators' net position stands within its range of the last three years (0-100)."""
    if cftc is None or len(cftc) < 60:
        return None
    lo, hi = cftc.rolling(156, min_periods=52).min(), cftc.rolling(156, min_periods=52).max()
    idx = ((cftc - lo) / (hi - lo) * 100).dropna()
    return idx[idx.index >= start]


def seasonal_line(close: pd.Series, years: int = 15) -> pd.Series | None:
    if close.empty:
        return None
    last = close.index[-1]
    months = sample(close, "1M")
    rets = months.pct_change().dropna()
    rets = rets[[d.year >= last.year - years and d.year < last.year for d in rets.index]]
    if len(rets) < 60:
        return None
    avg = rets.groupby([d.month for d in rets.index]).mean()
    prior = close[[d.year < last.year for d in close.index]]
    if prior.empty:
        return None
    level, points = float(prior.iloc[-1]), {}
    for month in range(1, 13):
        level *= 1 + float(avg.get(month, 0.0))
        day = pd.Timestamp(last.year, month, 1) + pd.offsets.MonthEnd(0)
        points[day.date()] = level
    return pd.Series(points)


def commodity_indicators(ohlc: pd.DataFrame, cftc: pd.Series | None) -> dict[str, pd.Series]:
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    high = ohlc["high"].astype(float).fillna(close)
    low = ohlc["low"].astype(float).fillna(close)
    out: dict[str, pd.Series] = {
        "donchian20_high": high.rolling(20).max(), "donchian20_low": low.rolling(20).min(),
        "donchian55_high": high.rolling(55).max(), "donchian55_low": low.rolling(55).min(),
        "sma50": _clean(talib.SMA(c, 50), close.index), "sma100": _clean(talib.SMA(c, 100), close.index),
        "sma200": _clean(talib.SMA(c, 200), close.index),
        "mom12m": (close / close.shift(252) - 1) * 100,
    }
    h, lo_ = high.to_numpy(np.float64), low.to_numpy(np.float64)
    out["adx14"] = _clean(talib.ADX(h, lo_, c, 14), close.index)
    out["atr20_pct"] = _clean(talib.ATR(h, lo_, c, 20), close.index) / close * 100
    season = seasonal_line(close)
    if season is not None:
        out["seasonal"] = season
    idx = _cftc_index(cftc, close.index[0])
    if idx is not None:
        out["cftc_index"] = idx
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}


def ichimoku(close: pd.Series) -> dict[str, pd.Series]:
    """Ichimoku 9-26-52 on closes; the cloud is drawn 26 days ahead, as usual (shifted on the trading days)."""
    def mid(n: int) -> pd.Series:
        return (close.rolling(n).max() + close.rolling(n).min()) / 2

    tenkan, kijun = mid(9), mid(26)
    return {"ichimoku_tenkan": tenkan, "ichimoku_kijun": kijun,
            "ichimoku_span_a": ((tenkan + kijun) / 2).shift(26), "ichimoku_span_b": mid(52).shift(26)}


def fx_indicators(ohlc: pd.DataFrame, cftc: pd.Series | None,
                  rate_diff: pd.Series | None = None) -> dict[str, pd.Series]:
    close = ohlc["close"].astype(float)
    c = close.to_numpy(dtype=np.float64)
    out: dict[str, pd.Series] = {
        "ema50": _clean(talib.EMA(c, 50), close.index), "ema200": _clean(talib.EMA(c, 200), close.index),
        "mom3m": (close / close.shift(63) - 1) * 100, "mom12m": (close / close.shift(255) - 1) * 100,
        "adx14": _clean(talib.ADX(c, c, c, 14), close.index),
        "atr14_pct": _clean(talib.ATR(c, c, c, 14), close.index) / close * 100,
        **ichimoku(close),
    }
    if rate_diff is not None and not rate_diff.empty:
        out["rate_diff"] = rate_diff.reindex(close.index.union(rate_diff.index)).ffill().reindex(close.index)
    idx = _cftc_index(cftc, close.index[0])
    if idx is not None:
        out["cftc_index"] = idx
    cleaned = {k: v.dropna() for k, v in out.items()}
    return {k: v for k, v in cleaned.items() if not v.empty}
