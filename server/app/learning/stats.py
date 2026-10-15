"""Statistics for promoting a challenger (chapter 8): the Deflated Sharpe Ratio and the probability of backtest
overfitting (PBO, combinatorially symmetric cross-validation). Pure functions.

References: Bailey and Lopez de Prado (2014), "The Deflated Sharpe Ratio"; Bailey, Borwein, Lopez de Prado and
Zhu (2017), "The Probability of Backtest Overfitting".
"""

import itertools
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

N = NormalDist()
EULER = 0.5772156649


def long_short(df: pd.DataFrame, share: float = 0.2, min_assets: int = 5) -> pd.Series:
    """Per month: average excess of the best-scored fifth minus the worst-scored fifth (1-month horizon)."""
    out = {}
    for as_of, g in df.dropna(subset=["score", "excess"]).groupby("as_of"):
        if len(g) < min_assets:
            continue
        k = max(1, int(len(g) * share))
        g = g.sort_values("score")
        out[as_of] = float(g["excess"].iloc[-k:].mean() - g["excess"].iloc[:k].mean())
    return pd.Series(out, dtype=float).sort_index()


def sharpe(x: pd.Series | np.ndarray) -> float | None:
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 2 or a.std(ddof=1) == 0:
        return None
    return float(a.mean() / a.std(ddof=1))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """The Sharpe ratio the best of n unskilled trials reaches by luck."""
    if n_trials < 2:
        return 0.0
    return math.sqrt(sr_variance) * ((1 - EULER) * N.inv_cdf(1 - 1 / n_trials)
                                     + EULER * N.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(returns: pd.Series, n_trials: int, sr_variance: float | None = None) -> dict:
    """Probability that the true Sharpe ratio is above what the best of `n_trials` reaches by chance."""
    a = np.asarray(pd.Series(returns).dropna(), dtype=float)
    t = len(a)
    sr = sharpe(a)
    if sr is None or t < 3:
        return {"sharpe": sr, "months": t, "trials": n_trials, "dsr": None}
    var = sr_variance if sr_variance is not None and sr_variance > 0 else 1.0 / (t - 1)
    sr0 = expected_max_sharpe(n_trials, var)
    d = a - a.mean()
    skew = float((d ** 3).mean() / (d ** 2).mean() ** 1.5) if (d ** 2).mean() > 0 else 0.0
    kurt = float((d ** 4).mean() / (d ** 2).mean() ** 2) if (d ** 2).mean() > 0 else 3.0
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    dsr = N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)) if denom > 0 else None
    return {"sharpe": sr, "months": t, "trials": n_trials, "expected_max_sharpe": sr0, "skew": skew,
            "kurtosis": kurt, "dsr": dsr}


def pbo(matrix: pd.DataFrame, blocks: int = 16) -> dict:
    """Probability of backtest overfitting: how often the configuration that is best in-sample ranks in the
    bottom half out-of-sample. `matrix`: one column per trial, one row per month (performance per period)."""
    m = matrix.dropna()
    n_trials = m.shape[1]
    s = min(blocks, (len(m) // 2) * 2)
    s -= s % 2
    if n_trials < 2 or s < 4:
        return {"pbo": None, "trials": n_trials, "months": len(m), "splits": 0}
    parts = np.array_split(np.arange(len(m)), s)
    values = m.to_numpy(dtype=float)
    logits = []
    for chosen in itertools.combinations(range(s), s // 2):
        ins = np.concatenate([parts[i] for i in chosen])
        oos = np.concatenate([parts[i] for i in range(s) if i not in chosen])
        is_perf = _sharpe_cols(values[ins])
        oos_perf = _sharpe_cols(values[oos])
        best = int(np.nanargmax(is_perf))
        rank = 1 + int(np.sum(oos_perf < oos_perf[best])) + 0.5 * int(np.sum(oos_perf == oos_perf[best]) - 1)
        omega = rank / (n_trials + 1)
        logits.append(math.log(omega / (1 - omega)))
    return {"pbo": float(np.mean(np.array(logits) <= 0)), "trials": n_trials, "months": len(m),
            "splits": len(logits)}


def _sharpe_cols(a: np.ndarray) -> np.ndarray:
    sd = a.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, a.mean(axis=0) / sd, 0.0)
