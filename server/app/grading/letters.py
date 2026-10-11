"""Letter scale, caps, hysteresis (chapter 5). Pure functions."""

from collections.abc import Mapping, Sequence

# Best to worst. F has no plus or minus.
GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
RANK = {g: i for i, g in enumerate(GRADES)}


def bands(scale: Mapping[str, float]) -> dict[str, tuple[float, float]]:
    """Score band [low, high) per graded letter. Each letter band is split into thirds for - / plain / +."""
    order = ["A", "B", "C", "D"]
    out: dict[str, tuple[float, float]] = {}
    for i, letter in enumerate(order):
        low = scale[letter]
        high = 100.0 + 1e-9 if i == 0 else scale[order[i - 1]]
        third = (high - low) / 3
        out[f"{letter}-"] = (low, low + third)
        out[letter] = (low + third, low + 2 * third)
        out[f"{letter}+"] = (low + 2 * third, high)
    out["F"] = (scale["F"], scale["D"])
    return out


def letter_for(score: float, scale: Mapping[str, float]) -> str:
    for grade, (low, high) in bands(scale).items():
        if low <= score < high:
            return grade
    return "A+" if score >= 100 else "F"


def cap(grade: str, ceiling: str) -> str:
    """The worse of the two grades."""
    return grade if RANK[grade] >= RANK[ceiling] else ceiling


def apply_hysteresis(score: float, raw: str, previous: str | None, recent_raw: Sequence[str],
                     scale: Mapping[str, float], points: float, days: int) -> str:
    """Keep the previous letter unless the score clears its band by `points`, or the raw letter has
    differed from it for `days` consecutive days (today included; `recent_raw` holds earlier days, oldest
    first)."""
    if previous is None or raw == previous:
        return raw
    low, high = bands(scale)[previous]
    if score >= high + points or score < low - points:
        return raw
    streak = list(recent_raw[-(days - 1):]) + [raw] if days > 1 else [raw]
    if len(streak) >= days and all(r != previous for r in streak):
        return raw
    return previous
