"""Percentile ranks within a comparison group (chapter 5). Pure functions."""

import math
from collections.abc import Sequence


def winsorize(values: Sequence[float], lower: float, upper: float) -> list[float]:
    """Clip at the given quantiles (linear interpolation, like numpy's default)."""
    if not values:
        return []
    ordered = sorted(values)
    lo, hi = _quantile(ordered, lower), _quantile(ordered, upper)
    return [min(max(v, lo), hi) for v in values]


def _quantile(ordered: Sequence[float], q: float) -> float:
    pos = (len(ordered) - 1) * q
    i, frac = int(math.floor(pos)), pos - math.floor(pos)
    if i + 1 >= len(ordered):
        return ordered[-1]
    return ordered[i] + (ordered[i + 1] - ordered[i]) * frac


def percentile_of(value: float, group: Sequence[float], *, higher_is_better: bool,
                  winsor: tuple[float, float] | None = None) -> float:
    """Mid-rank percentile (0-100) of `value` within `group` (which should include `value`).

    Ties share the average rank. With one member the result is 50. Lower-is-better metrics are flipped.
    """
    members = list(group)
    if winsor and len(members) >= 3:
        clipped = winsorize(members + [value], *winsor)
        members, value = clipped[:-1], clipped[-1]
    n = len(members)
    if n == 0:
        raise ValueError("empty comparison group")
    below = sum(1 for v in members if v < value)
    equal = sum(1 for v in members if v == value)
    pct = (below + 0.5 * equal) / n * 100 if equal else below / n * 100
    return pct if higher_is_better else 100 - pct


def weighted_percentile_of(value: float, history: Sequence[float], weights: Sequence[float], *,
                           higher_is_better: bool) -> float:
    """Percentile of `value` in its own history, with weights (e.g. heavier on the latest cycle)."""
    total = sum(weights)
    if total <= 0:
        raise ValueError("no weight")
    below = sum(w for v, w in zip(history, weights, strict=True) if v < value)
    equal = sum(w for v, w in zip(history, weights, strict=True) if v == value)
    pct = (below + 0.5 * equal) / total * 100
    return pct if higher_is_better else 100 - pct
