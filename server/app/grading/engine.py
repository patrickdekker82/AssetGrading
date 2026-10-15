"""The grading engine (chapter 5): a pure function of model configuration and inputs.

Same inputs, same model version -> same grade. Everything the engine needs is in `GradeInput`, which is
stored in grade_snapshot so any grade can be recomputed later.
"""

import math
import operator
from dataclasses import asdict, dataclass, field
from typing import Any

from app.grading.letters import RANK, apply_hysteresis, cap, letter_for, shift
from app.modelconfig import ModelConfig
from app.modelconfig.schema import (
    FlagGate,
    MetricThresholdGate,
    PillarAgreementGate,
    PillarFloorGate,
    Template,
)

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
VALUATION_PEER_SHARE_KEY = "peer"


@dataclass
class MetricInput:
    value: float | None
    peer_pct: float | None = None   # percentile within the comparison group
    own_pct: float | None = None    # percentile within the asset's own history


@dataclass
class GradeInput:
    template_id: str
    tags: list[str]
    metrics: dict[str, MetricInput]
    flags: dict[str, bool | None] = field(default_factory=dict)
    prev_letter: str | None = None          # last published letter before caps (hysteresis state)
    recent_raw: list[str] = field(default_factory=list)  # raw letters of previous days, oldest first
    regime: str | None = None               # market regime of the day (risk_on | neutral | risk_off)
    product: bool = False                   # grade the product (ETC) with the template's product judgement

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradeInput":
        metrics = {k: MetricInput(**v) for k, v in data["metrics"].items()}
        return cls(template_id=data["template_id"], tags=list(data["tags"]), metrics=metrics,
                   flags=dict(data.get("flags", {})), prev_letter=data.get("prev_letter"),
                   recent_raw=list(data.get("recent_raw", [])), regime=data.get("regime"),
                   product=bool(data.get("product", False)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricResult:
    id: str
    value: float | None
    score: float | None
    weight: float
    used_as_fallback: bool = False


@dataclass
class PillarResult:
    id: str
    name_nl: str
    weight: float                 # configured weight (after weight rules)
    effective_weight: float       # share of the final score after redistribution (0-100)
    score: float | None
    coverage: float
    timing: bool
    metrics: list[MetricResult]

    @property
    def contribution(self) -> float | None:
        return None if self.score is None else self.score * self.effective_weight / 100


@dataclass
class GateResult:
    id: str
    status: str                   # hit | clear | unknown
    cap: str | None
    label_nl: str | None
    reason_nl: str
    detail: str | None = None


@dataclass
class GradeResult:
    template_id: str
    status: str                   # graded | provisional | no_grade | speculative | peg_safety
    score: float | None
    quality: float | None
    timing: float | None
    coverage: float
    raw_letter: str | None
    hysteresis_letter: str | None
    letter: str | None
    letter_low: str | None
    letter_high: str | None
    score_low: float | None
    score_high: float | None
    peg_safety: int | None
    labels: list[str]
    reason_nl: str | None
    pillars: list[PillarResult]
    gates: list[GateResult]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for p_out, p in zip(out["pillars"], self.pillars, strict=True):
            p_out["contribution"] = p.contribution
        return out


def grade(inp: GradeInput, config: ModelConfig) -> GradeResult:
    template = config.templates[inp.template_id]
    if inp.product:
        return _product(inp, template, config)
    if template.grading == "peg_safety":
        return _peg_safety(inp, template, config)
    if template.grading == "safety_only":
        return _safety_only(inp, template, config)
    return _weighted(inp, template, config)


# --- weighted templates --------------------------------------------------------------------------

def _applies(applies_to: list[str] | None, tags: list[str]) -> bool:
    return applies_to is None or bool(set(applies_to) & set(tags))


def _metric_score(metric_id: str, mi: MetricInput | None, valuation: bool, config: ModelConfig) -> float | None:
    if mi is None or mi.value is None:
        return None
    if config.metrics[metric_id].scoring == "direct":
        return max(0.0, min(100.0, float(mi.value)))
    if mi.peer_pct is None:
        return None
    if valuation and mi.own_pct is not None:
        peer_share = config.settings.scoring.valuation_mix[VALUATION_PEER_SHARE_KEY]
        return peer_share * mi.peer_pct + (1 - peer_share) * mi.own_pct
    return mi.peer_pct


def _pillars(inp: GradeInput, template: Template, config: ModelConfig, notes: list[str]) -> list[PillarResult]:
    weights = {p.id: p.weight for p in template.pillars}
    for rule in template.weight_rules:
        mi = inp.metrics.get(rule.when.metric)
        if mi is None or mi.value is None:
            notes.append(f"Regel {rule.id} niet te controleren: {rule.when.metric} ontbreekt.")
        elif OPS[rule.when.op](mi.value, rule.when.value):
            weights[rule.scale_pillar.pillar] *= rule.scale_pillar.factor
            notes.append(rule.reason_nl)

    results = []
    for p in template.pillars:
        metrics: list[MetricResult] = []
        available = total = weighted_sum = 0.0
        applicable = [m for m in p.metrics if _applies(m.applies_to, inp.tags)]
        for m in applicable:
            if m.fallback_for is not None:
                continue  # handled together with its primary
            score = _metric_score(m.id, inp.metrics.get(m.id), p.valuation, config)
            used, fallback = m, False
            if score is None:
                fb = next((f for f in applicable if f.fallback_for == m.id), None)
                if fb is not None:
                    fb_score = _metric_score(fb.id, inp.metrics.get(fb.id), p.valuation, config)
                    if fb_score is not None:
                        score, used, fallback = fb_score, fb, True
            total += m.weight
            mi = inp.metrics.get(used.id)
            metrics.append(MetricResult(id=used.id, value=None if mi is None else mi.value, score=score,
                                        weight=m.weight, used_as_fallback=fallback))
            if score is not None:
                available += m.weight
                weighted_sum += m.weight * score
        if total == 0:
            continue  # nothing in this pillar applies to this asset: leave it out entirely
        results.append(PillarResult(
            id=p.id, name_nl=p.name_nl, weight=weights[p.id], effective_weight=0.0,
            score=weighted_sum / available if available else None, coverage=available / total,
            timing=p.timing, metrics=metrics,
        ))
    scored_weight = sum(r.weight for r in results if r.score is not None)
    for r in results:
        r.effective_weight = r.weight / scored_weight * 100 if r.score is not None and scored_weight else 0.0
    return results


def _combine(pillars: list[PillarResult], multipliers: dict[str, float] | None = None,
             include=lambda p: True) -> float | None:
    multipliers = multipliers or {}
    parts = [(p.weight * multipliers.get(p.id, 1.0), p.score) for p in pillars if p.score is not None and include(p)]
    total = sum(w for w, _ in parts)
    return sum(w * s for w, s in parts) / total if total else None


def _evaluate_gates(template: Template, inp: GradeInput, pillars: list[PillarResult]) -> list[GateResult]:
    out = []
    for g in template.gates:
        if not _applies(g.applies_to, inp.tags):
            continue
        status, detail = "clear", None
        if isinstance(g, MetricThresholdGate):
            mi = inp.metrics.get(g.metric)
            if mi is None or mi.value is None:
                status, detail = "unknown", f"{g.metric} ontbreekt"
            elif OPS[g.op](mi.value, g.value):
                status, detail = "hit", f"{g.metric} = {mi.value:.4g}"
        elif isinstance(g, PillarFloorGate):
            weak = [p for p in pillars if p.score is not None and p.score < g.threshold]
            if weak:
                status, detail = "hit", ", ".join(f"{p.name_nl} {p.score:.0f}" for p in weak)
        elif isinstance(g, FlagGate):
            flag = inp.flags.get(g.flag)
            if flag is None:
                status, detail = "unknown", f"{g.flag} onbekend"
            elif flag:
                status = "hit"
        elif isinstance(g, PillarAgreementGate):
            pos = sum(1 for p in pillars if p.score is not None and p.score > 50)
            neg = sum(1 for p in pillars if p.score is not None and p.score < 50)
            if max(pos, neg) < g.min_pillars:
                status, detail = "hit", f"{pos} positief, {neg} negatief"
        out.append(GateResult(
            id=g.id, status=status, cap=getattr(g, "cap", None) or getattr(g, "set_grade", None),
            label_nl=getattr(g, "label_nl", None), reason_nl=g.reason_nl, detail=detail,
        ))
    return out


def _apply_gates(letter: str, gates: list[GateResult], template: Template) -> tuple[str, list[str]]:
    labels = []
    for g in gates:
        if g.status != "hit":
            continue
        if g.label_nl:
            labels.append(g.label_nl)
        gate_def = next(x for x in template.gates if x.id == g.id)
        if isinstance(gate_def, PillarAgreementGate):
            letter = gate_def.set_grade if RANK[letter] < RANK[gate_def.set_grade] else letter
        elif g.cap:
            letter = cap(letter, g.cap)
    if template.max_grade:
        letter = cap(letter, template.max_grade)
    return letter, labels


def _status(coverage: float, config: ModelConfig) -> str:
    if coverage < config.settings.coverage.hidden_below:
        return "no_grade"
    if coverage < config.settings.coverage.provisional_below:
        return "provisional"
    return "graded"


def _weighted(inp: GradeInput, template: Template, config: ModelConfig) -> GradeResult:
    notes: list[str] = []
    pillars = _pillars(inp, template, config, notes)
    applicable_weight = sum(p.weight for p in pillars)
    coverage = sum(p.weight * p.coverage for p in pillars) / applicable_weight if applicable_weight else 0.0
    score = _combine(pillars)
    quality = _combine(pillars, include=lambda p: not p.timing)
    tech = inp.metrics.get("technical_score")
    timing = None if tech is None or tech.value is None else float(tech.value)
    status = _status(coverage, config) if score is not None else "no_grade"
    gates = _evaluate_gates(template, inp, pillars)
    scale = config.letter_scale_for(template.id)
    stab = config.settings.stability

    if score is None:
        return GradeResult(template.id, "no_grade", None, quality, timing, coverage, None, None, None, None, None,
                           None, None, None, [], _no_grade_reason(coverage, pillars, config), pillars, gates, notes)

    raw = letter_for(score, scale)
    held = apply_hysteresis(score, raw, inp.prev_letter, inp.recent_raw, scale, stab.hysteresis_points,
                            stab.hysteresis_days)
    if template.flag_macro_price_divergence:
        _macro_price_divergence(pillars, notes)
    notches = _regime_notches(inp, template, config)
    if notches:
        notes.append(f"Marktregime {REGIME_NL.get(inp.regime or '', inp.regime)}: grade {notches:+d} stap, "
                     "vóór de gates.")
    letter, labels = _apply_gates(shift(held, notches), gates, template)

    # Bandwidth: every pillar weight 20% higher and lower, one at a time.
    variants = [score]
    for p in pillars:
        if p.score is None:
            continue
        for factor in (1 + stab.band_weight_shift, 1 - stab.band_weight_shift):
            variants.append(_combine(pillars, {p.id: factor}))
    low, high = min(variants), max(variants)
    letter_low, _ = _apply_gates(shift(letter_for(low, scale), notches), gates, template)
    letter_high, _ = _apply_gates(shift(letter_for(high, scale), notches), gates, template)

    reason = None
    if status == "no_grade":
        letter = letter_low = letter_high = None
        reason = _no_grade_reason(coverage, pillars, config)
    elif status == "provisional":
        labels.append("voorlopig")
    if template.label_nl:
        labels.append(template.label_nl)
    return GradeResult(template.id, status, score, quality, timing, coverage, raw, held, letter, letter_low,
                       letter_high, low, high, None, labels, reason, pillars, gates, notes)


def _macro_price_divergence(pillars: list[PillarResult], notes: list[str]) -> None:
    """Precious metals: say so when macro and the price trend point opposite ways (chapter 6)."""
    macro = next((p.score for p in pillars if p.id == "macro"), None)
    trend = next((p.score for p in pillars if p.timing), None)
    if macro is not None and trend is not None and (macro - 50) * (trend - 50) < 0 and abs(macro - trend) >= 30:
        notes.append(f"Macro ({macro:.0f}) en koerstrend ({trend:.0f}) spreken elkaar tegen.")


def _product(inp: GradeInput, template: Template, config: ModelConfig) -> GradeResult:
    """Product judgement for an ETC (chapter 6): the template's product metrics, equally weighted, and the
    product gates. The commodity itself is graded separately with the normal pillars."""
    prod = template.product
    if prod is None:
        raise ValueError(f"template {template.id} has no product judgement")
    metrics, total, available, weighted = [], 0.0, 0.0, 0.0
    for metric_id in prod.metrics:
        mi = inp.metrics.get(metric_id)
        score = _metric_score(metric_id, mi, False, config)
        metrics.append(MetricResult(id=metric_id, value=None if mi is None else mi.value, score=score, weight=1.0))
        total += 1
        if score is not None:
            available, weighted = available + 1, weighted + score
    coverage = available / total if total else 0.0
    score = weighted / available if available else None
    pillar = PillarResult(id="product", name_nl=prod.name_nl, weight=100, effective_weight=100.0 if score else 0.0,
                          score=score, coverage=coverage, timing=False, metrics=metrics)
    product_template = template.model_copy(update={"gates": prod.gates, "max_grade": None})
    gates = _evaluate_gates(product_template, inp, [pillar])
    status = _status(coverage, config) if score is not None else "no_grade"
    if status == "no_grade":
        return GradeResult(template.id, "no_grade", score, score, None, coverage, None, None, None, None, None,
                           None, None, None, [], _no_grade_reason(coverage, [pillar], config), [pillar], gates, [])
    raw = letter_for(score, config.letter_scale_for(template.id))
    held = apply_hysteresis(score, raw, inp.prev_letter, inp.recent_raw, config.letter_scale_for(template.id),
                            config.settings.stability.hysteresis_points, config.settings.stability.hysteresis_days)
    letter, labels = _apply_gates(held, gates, product_template)
    if status == "provisional":
        labels.append("voorlopig")
    notes = [prod.note_nl] if prod.note_nl else []
    return GradeResult(template.id, status, score, score, None, coverage, raw, held, letter, letter, letter,
                       score, score, None, labels, None, [pillar], gates, notes)


REGIME_NL = {"risk_on": "risico aan", "neutral": "neutraal", "risk_off": "risico uit"}


def _regime_notches(inp: GradeInput, template: Template, config: ModelConfig) -> int:
    """Grade shift from the market regime for templates with regime_adjust (at most max_grade_shift_steps)."""
    regime = config.settings.regime
    if not template.regime_adjust or inp.regime is None or isinstance(regime, dict):
        return 0
    limit = regime.max_grade_shift_steps
    return max(-limit, min(limit, regime.grade_shift.get(inp.regime, 0)))


def _no_grade_reason(coverage: float, pillars: list[PillarResult], config: ModelConfig) -> str:
    missing = [p.name_nl for p in pillars if p.score is None]
    # Rounded down, so coverage never looks higher than it is (39.6% shows as 39%).
    text = (f"Datadekking {math.floor(coverage * 100)}% ligt onder {config.settings.coverage.hidden_below:.0%}, "
            "daarom geen grade.")
    if missing:
        text += " Geen data voor: " + ", ".join(missing) + "."
    return text


# --- memecoin: safety check only -----------------------------------------------------------------

def _safety_only(inp: GradeInput, template: Template, config: ModelConfig) -> GradeResult:
    gates = _evaluate_gates(template, inp, [])
    tech = inp.metrics.get("technical_score")
    timing = None if tech is None or tech.value is None else float(tech.value)
    applicable = len(gates)
    known = sum(1 for g in gates if g.status != "unknown")
    coverage = known / applicable if applicable else 1.0
    notes = [] if applicable else ["Veiligheidscontrole niet van toepassing: geen Solana-token."]
    if coverage < config.settings.coverage.hidden_below:
        reason = "De veiligheidscontrole kon niet worden uitgevoerd, daarom geen grade."
        return GradeResult(template.id, "no_grade", None, None, timing, coverage, None, None, None, None, None,
                           None, None, None, [], reason, [], gates, notes)
    letter, labels = _apply_gates(template.base_grade or "C", gates, template)
    if coverage < config.settings.coverage.provisional_below:
        labels.append("voorlopig")
    if template.label_nl:
        labels.append(template.label_nl)
    return GradeResult(template.id, "speculative", None, None, timing, coverage, template.base_grade, None, letter,
                       letter, letter, None, None, None, labels, None, [], gates, notes)


# --- stablecoin: peg safety 1 (strong) to 5 (weak) -----------------------------------------------

def peg_factor_score(metric_id: str, value: float, template: Template) -> float:
    if metric_id == "peg_deviation":
        max_bp = template.peg_safety.peg_deviation_max_bp
        return max(0.0, 100.0 * (1 - value * 10_000 / max_bp))
    if metric_id == "mica_status":
        return 100.0 if value >= 1 else 0.0
    return max(0.0, min(100.0, float(value)))  # qualitative factors are entered on a 0-100 scale


def _peg_safety(inp: GradeInput, template: Template, config: ModelConfig) -> GradeResult:
    factors = template.peg_safety.factors
    scored = []
    metrics = []
    for f in factors:
        mi = inp.metrics.get(f)
        s = None if mi is None or mi.value is None else peg_factor_score(f, float(mi.value), template)
        metrics.append(MetricResult(id=f, value=None if mi is None else mi.value, score=s, weight=1.0))
        if s is not None:
            scored.append(s)
    coverage = len(scored) / len(factors)
    pillar = PillarResult(id="peg", name_nl="Pegveiligheid", weight=100, effective_weight=100,
                          score=sum(scored) / len(scored) if scored else None, coverage=coverage, timing=False,
                          metrics=metrics)
    if coverage < config.settings.coverage.hidden_below or not scored:
        reason = (f"Te weinig gegevens over de stablecoin ({len(scored)} van {len(factors)} onderdelen), "
                  "daarom geen pegveiligheid.")
        return GradeResult(template.id, "no_grade", None, None, None, coverage, None, None, None, None, None,
                           None, None, None, [], reason, [pillar], [], [])
    lo, hi = template.peg_safety.scale
    avg = pillar.score
    peg = int(round(lo + (100 - avg) / 100 * (hi - lo)))
    labels = ["voorlopig"] if coverage < config.settings.coverage.provisional_below else []
    return GradeResult(template.id, "peg_safety", avg, None, None, coverage, None, None, None, None, None,
                       None, None, peg, labels, None, [pillar], [], [])
