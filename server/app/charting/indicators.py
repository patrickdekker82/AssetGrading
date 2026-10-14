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
