"""Monthly measurement (chapter 8). Pure functions on a table of month-end grades with their outcomes.

The input frame has one row per asset and month-end: as_of, asset_id, score, letter, excess (return above the
benchmark over the horizon), drawdown (largest fall within the horizon), regime and one column per pillar
score ("p_<id>"). Overlapping horizons make neighbouring months dependent, so every t-value uses Newey-West
with a lag of at least the horizon minus one month.
"""

import math

import numpy as np
import pandas as pd

LETTER_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
BASE_ORDER = ["A", "B", "C", "D", "F"]


def base_letter(letter: str | None) -> str | None:
    return letter[0] if letter else None


def spearman(x: pd.Series, y: pd.Series) -> float | None:
    """Rank correlation; None when either side has no spread."""
    rx, ry = x.rank(), y.rank()
    if rx.std(ddof=0) == 0 or ry.std(ddof=0) == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


MIN_MONTHS_FOR_T = 6     # fewer independent-ish observations: no t-value at all


def newey_west(values: pd.Series | list[float], lags: int, min_n: int = MIN_MONTHS_FOR_T) -> dict:
    """Mean with a Newey-West (Bartlett) standard error and t-value."""
    x = np.asarray(pd.Series(values).dropna(), dtype=float)
    n = len(x)
    if n < max(min_n, 2):
        return {"n": n, "mean": float(x.mean()) if n else None, "se": None, "t": None, "p": None}
    d = x - x.mean()
    lags = max(0, min(lags, n - 1))
    var = float(d @ d) / n
    for lag in range(1, lags + 1):
        var += 2 * (1 - lag / (lags + 1)) * float(d[lag:] @ d[:-lag]) / n
    se = math.sqrt(max(var, 0.0) / n)
    t = float(x.mean() / se) if se > 0 else None
    # Two-sided p-value from the normal distribution (good enough for the sample sizes here).
    p = math.erfc(abs(t) / math.sqrt(2)) if t is not None else None
    return {"n": n, "mean": float(x.mean()), "se": se, "t": t, "p": p}


def ic_series(df: pd.DataFrame, score: str = "score", target: str = "excess", min_assets: int = 5) -> pd.Series:
    """Rank correlation between score and later excess return, per month-end."""
    out = {}
    for as_of, g in df.dropna(subset=[score, target]).groupby("as_of"):
        if len(g) >= min_assets:
            ic = spearman(g[score], g[target])
            if ic is not None:
                out[as_of] = ic
    return pd.Series(out, dtype=float).sort_index()


def summarize_ic(series: pd.Series, lags: int) -> dict:
    nw = newey_west(series, lags)
    return {
        "months": int(len(series)),
        "mean": nw["mean"], "std": float(series.std()) if len(series) > 1 else None,
        "share_positive": float((series > 0).mean()) if len(series) else None,
        "t_newey_west": nw["t"], "p": nw["p"],
        "by_month": {str(k): round(float(v), 4) for k, v in series.items()},
    }


def letter_stats(df: pd.DataFrame, lags: int, big_miss_letters: list[str], big_miss_below: float) -> dict:
    """Return above the benchmark per letter with a Newey-West interval, the A-F spread and the order test."""
    graded = df.dropna(subset=["letter", "excess"])
    per_letter = {}
    for letter in LETTER_ORDER:
        g = graded[graded["letter"] == letter]
        if g.empty:
            continue
        monthly = g.groupby("as_of")["excess"].mean()
        nw = newey_west(monthly, lags)
        ci = [nw["mean"] - 1.96 * nw["se"], nw["mean"] + 1.96 * nw["se"]] if nw["se"] is not None else None
        per_letter[letter] = {
            "n": int(len(g)), "months": int(monthly.size),
            "mean_excess": float(g["excess"].mean()), "median_excess": float(g["excess"].median()),
            "monthly_mean": nw["mean"], "ci95": ci,
            "share_beat_benchmark": float((g["excess"] > 0).mean()),
            "worst_drawdown": float(g["drawdown"].min()) if "drawdown" in g else None,
            "mean_drawdown": float(g["drawdown"].mean()) if "drawdown" in g else None,
        }
    base = graded.assign(base=graded["letter"].map(base_letter))
    base_means = {b: float(base[base["base"] == b]["excess"].mean()) for b in BASE_ORDER if (base["base"] == b).any()}
    spread = None
    a_m = base[base["base"] == "A"].groupby("as_of")["excess"].mean()
    f_m = base[base["base"] == "F"].groupby("as_of")["excess"].mean()
    both = pd.concat([a_m, f_m], axis=1, keys=["a", "f"]).dropna()
    if not both.empty:
        nw = newey_west(both["a"] - both["f"], lags)
        spread = {"months": nw["n"], "mean": nw["mean"], "t_newey_west": nw["t"], "p": nw["p"]}
    order = monotonic(base_means)
    misses = graded[graded["letter"].isin(big_miss_letters) & (graded["excess"] < big_miss_below)]
    return {"per_letter": per_letter, "base_means": base_means, "a_minus_f": spread, "order": order,
            "big_misses": int(len(misses))}


def monotonic(base_means: dict[str, float]) -> dict:
    """Does the average return fall from A to F? Rank correlation between letter rank and mean (1 = perfect)."""
    letters = [b for b in BASE_ORDER if b in base_means]
    if len(letters) < 3:
        return {"letters": letters, "rank_correlation": None, "holds": None, "inversions": None}
    means = pd.Series([base_means[b] for b in letters])
    rank = pd.Series(range(len(letters), 0, -1), dtype=float)
    inversions = sum(1 for i in range(len(letters) - 1) if means[i] < means[i + 1])
    return {"letters": letters, "rank_correlation": spearman(rank, means), "holds": inversions == 0,
            "inversions": inversions}


def pillar_stats(df: pd.DataFrame, lags: int, min_assets: int) -> dict:
    cols = [c for c in df.columns if c.startswith("p_")]
    ics = {}
    for c in cols:
        s = ic_series(df, c, "excess", min_assets)
        if len(s):
            nw = newey_west(s, lags)
            ics[c[2:]] = {"months": int(len(s)), "mean": nw["mean"], "t_newey_west": nw["t"]}
    corr = None
    usable = [c for c in cols if df[c].notna().sum() >= 10]
    if len(usable) >= 2:
        m = df[usable].rank().corr()
        corr = {a[2:]: {b[2:]: (None if pd.isna(m.loc[a, b]) else round(float(m.loc[a, b]), 3)) for b in usable}
                for a in usable}
    return {"ic": ics, "correlation": corr}


def turnover(df: pd.DataFrame) -> dict:
    """How often the letter changes from one month-end to the next, per asset."""
    d = df.dropna(subset=["letter"]).sort_values(["asset_id", "as_of"])
    prev = d.groupby("asset_id")["letter"].shift()
    pairs = d[prev.notna()]
    if pairs.empty:
        return {"pairs": 0, "letter_changed": None, "base_letter_changed": None}
    p = prev[prev.notna()]
    return {"pairs": int(len(pairs)), "letter_changed": float((pairs["letter"] != p).mean()),
            "base_letter_changed": float((pairs["letter"].str[0] != p.str[0]).mean())}


def by_regime(df: pd.DataFrame, lags: int, min_assets: int) -> dict:
    out = {}
    for state, g in df.dropna(subset=["regime"]).groupby("regime"):
        s = ic_series(g, "score", "excess", min_assets)
        if len(s):
            nw = newey_west(s, lags)
            out[state] = {"months": int(len(s)), "mean_ic": nw["mean"], "t_newey_west": nw["t"],
                          "mean_excess": float(g["excess"].mean())}
    return out


def coverage(df: pd.DataFrame) -> dict:
    """How many month-ends and assets a template covers (chapter 8: report it per template)."""
    if df.empty:
        return {"months": 0, "assets": 0, "assets_per_month": None, "first": None, "last": None}
    per_month = df.groupby("as_of")["asset_id"].nunique()
    return {"months": int(per_month.size), "assets": int(df["asset_id"].nunique()),
            "assets_per_month": round(float(per_month.mean()), 1), "min_assets_per_month": int(per_month.min()),
            "first": str(min(df["as_of"])), "last": str(max(df["as_of"]))}


def measure(df: pd.DataFrame, horizon: int, settings: dict) -> dict:
    """Everything chapter 8 asks for, for one template and horizon."""
    lags = max(horizon - 1, 0)
    min_assets = settings.get("min_assets_per_month", 5)
    miss = settings.get("big_miss", {})
    return {
        "horizon_months": horizon,
        "newey_west_lags": lags,
        "coverage": coverage(df),
        "ic": summarize_ic(ic_series(df, "score", "excess", min_assets), lags),
        "letters": letter_stats(df, lags, miss.get("letters", []), miss.get("excess_below", -0.3)),
        "pillars": pillar_stats(df, lags, min_assets),
        "turnover": turnover(df),
        "regime": by_regime(df, lags, min_assets),
    }
