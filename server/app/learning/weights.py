"""The quarterly weight proposal and its guardrails (chapter 8). Pure functions.

`check_weights` is the one fixed check every proposal passes through, whoever made it (this module, the
language model or the owner): a proposal with any violation is refused, never trimmed into shape.
`propose_weights` builds a proposal that respects the guardrails by construction.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.evaluation import metrics


@dataclass(frozen=True)
class Guardrails:
    weight_min: float = 5.0
    weight_max: float = 40.0
    ratio_low: float = 0.5
    ratio_high: float = 1.5
    max_change: float = 3.0
    min_backtest_months: int = 120
    min_assets_per_month: float = 30
    min_live_months: int = 12

    @classmethod
    def from_settings(cls, raw: dict) -> "Guardrails":
        g = raw["learning"]["guardrails"]
        return cls(float(g["weight_min_pct"]), float(g["weight_max_pct"]), float(g["ratio_to_start"][0]),
                   float(g["ratio_to_start"][1]), float(g["max_change_pp"]), int(g["min_backtest_months"]),
                   float(g["min_assets_per_month"]), int(g["min_live_months"]))


@dataclass
class DataCoverage:
    backtest_months: int
    assets_per_month: float
    live_months: int


def data_shortfall(cov: DataCoverage, g: Guardrails) -> list[str]:
    out = []
    if cov.backtest_months < g.min_backtest_months:
        out.append(f"{cov.backtest_months} maanden terugtest, minimaal {g.min_backtest_months}")
    if cov.assets_per_month < g.min_assets_per_month:
        out.append(f"gemiddeld {cov.assets_per_month:.1f} assets per maand, minimaal {g.min_assets_per_month:.0f}")
    if cov.live_months < g.min_live_months:
        out.append(f"{cov.live_months} maanden live snapshots, minimaal {g.min_live_months}")
    return out


def check_weights(w0: dict[str, float], current: dict[str, float], proposed: dict[str, float],
                  g: Guardrails, cov: DataCoverage | None) -> list[str]:
    """Every guardrail a proposed weight set breaks (empty: allowed). Weights are percentages."""
    problems = []
    if set(proposed) != set(w0):
        missing, extra = sorted(set(w0) - set(proposed)), sorted(set(proposed) - set(w0))
        problems.append("pijlers kloppen niet" + (f"; ontbreekt: {', '.join(missing)}" if missing else "")
                        + (f"; onbekend: {', '.join(extra)}" if extra else ""))
        return problems
    total = sum(proposed.values())
    if abs(total - 100) > 0.01:
        problems.append(f"gewichten tellen op tot {total:g}, niet 100")
    for p, w in proposed.items():
        if not (isinstance(w, int | float) and np.isfinite(w)):
            problems.append(f"{p}: geen geldig gewicht")
            continue
        if w < g.weight_min - 1e-9 or w > g.weight_max + 1e-9:
            problems.append(f"{p}: {w:g}% ligt buiten {g.weight_min:g}% tot {g.weight_max:g}%")
        if w < g.ratio_low * w0[p] - 1e-9 or w > g.ratio_high * w0[p] + 1e-9:
            problems.append(f"{p}: {w:g}% ligt buiten {g.ratio_low:g} tot {g.ratio_high:g} keer het startgewicht "
                            f"{w0[p]:g}%")
        if abs(w - current[p]) > g.max_change + 1e-9:
            problems.append(f"{p}: {w - current[p]:+g} procentpunt in één kwartaal, hoogstens {g.max_change:g}")
    if cov is not None:
        problems += [f"te weinig data: {s}" for s in data_shortfall(cov, g)]
    return problems


def bounds(w0: dict[str, float], current: dict[str, float], g: Guardrails) -> dict[str, tuple[float, float]]:
    return {p: (max(g.weight_min, g.ratio_low * w0[p], current[p] - g.max_change),
                min(g.weight_max, g.ratio_high * w0[p], current[p] + g.max_change)) for p in w0}


def project(target: dict[str, float], b: dict[str, tuple[float, float]]) -> dict[str, float] | None:
    """The weights closest to `target` within the bounds that sum to 100, or None when impossible."""
    lo, hi = sum(v[0] for v in b.values()), sum(v[1] for v in b.values())
    if lo > 100 + 1e-9 or hi < 100 - 1e-9:
        return None
    w = {p: min(max(target[p], b[p][0]), b[p][1]) for p in target}
    for _ in range(100):
        gap = 100 - sum(w.values())
        if abs(gap) < 1e-9:
            break
        free = [p for p in w if (gap > 0 and w[p] < b[p][1] - 1e-12) or (gap < 0 and w[p] > b[p][0] + 1e-12)]
        share = gap / len(free)
        for p in free:
            w[p] = min(max(w[p] + share, b[p][0]), b[p][1])
    return w


def round_weights(w: dict[str, float], b: dict[str, tuple[float, float]], step: float = 0.1) -> dict[str, float]:
    """Round to `step` keeping the sum at exactly 100 and every weight within its bounds."""
    r = {p: round(v / step) * step for p, v in w.items()}
    gap = round((100 - sum(r.values())) / step)
    order = sorted(r, key=lambda p: -(w[p] - r[p]) if gap > 0 else (w[p] - r[p]))
    i = 0
    while gap != 0 and i < 10 * len(order):
        p = order[i % len(order)]
        d = step if gap > 0 else -step
        if b[p][0] - 1e-9 <= r[p] + d <= b[p][1] + 1e-9:
            r[p] += d
            gap += -1 if gap > 0 else 1
        i += 1
    return {p: round(v, 1) for p, v in r.items()}


@dataclass
class WeightProposal:
    weights: dict[str, float] | None
    evidence: dict
    reason_nl: str | None = None


def propose_weights(w0: dict[str, float], current: dict[str, float], ic: dict[str, pd.Series], t_months: int,
                    g: Guardrails, cov: DataCoverage, shrink: float = 60, max_lambda: float = 0.5) -> WeightProposal:
    """Steps 1 to 6 of the quarterly proposal for one template."""
    evidence: dict = {"T": t_months, "pillars": {}}
    short = data_shortfall(cov, g)
    if short:
        return WeightProposal(None, evidence, "Onder het minimum (" + "; ".join(short) + "); het sjabloon blijft op "
                                              "de startgewichten.")
    k = t_months / (t_months + shrink)
    lam = min(max_lambda, k)
    raw = {}
    for p in w0:
        s = ic.get(p, pd.Series(dtype=float)).dropna()
        mean = float(s.mean()) if len(s) else 0.0
        std = float(s.std()) if len(s) > 1 else None
        shrunk = max(mean * k, 0.0)
        raw[p] = shrunk / std if std else 0.0
        evidence["pillars"][p] = {"ic": mean, "ic_std": std, "ic_shrunk": shrunk, "months": int(len(s))}
    total = sum(raw.values())
    if total <= 0:
        return WeightProposal(None, evidence, "Geen pijler met een positieve gekrompen rangcorrelatie; het sjabloon "
                                              "blijft op de startgewichten.")
    target = {p: 100 * v / total for p, v in raw.items()}
    mixed = {p: (1 - lam) * w0[p] + lam * target[p] for p in w0}
    b = bounds(w0, current, g)
    projected = project(mixed, b)
    if projected is None:
        return WeightProposal(None, evidence, "De vangrails laten geen gewichten toe die optellen tot 100.")
    weights = round_weights(projected, b)
    evidence.update({"lambda": lam, "target": target, "mixed": mixed})
    if all(abs(weights[p] - current[p]) < 0.05 for p in w0):
        return WeightProposal(None, evidence, "Geen wijziging ten opzichte van de huidige gewichten.")
    return WeightProposal(weights, evidence)


def quarterly_ic(df: pd.DataFrame, pillars: list[str], min_assets: int) -> dict[str, pd.Series]:
    """Rank correlation per pillar against the 3-month outcome, at quarter-ends only (no overlap)."""
    q = df[df["as_of"].map(lambda d: d.month % 3 == 0)]
    return {p: metrics.ic_series(q, f"p_{p}", "excess", min_assets) for p in pillars if f"p_{p}" in q.columns}
