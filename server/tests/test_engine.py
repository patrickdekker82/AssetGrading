"""Grading engine: letters, percentiles, pillars, coverage, gates, hysteresis, bandwidth (chapter 5)."""

import pytest

from app.grading.engine import GradeInput, MetricInput, grade, peg_factor_score
from app.grading.letters import GRADES, apply_hysteresis, bands, cap, letter_for
from app.grading.percentiles import percentile_of, weighted_percentile_of, winsorize
from app.modelconfig import load_model_config
from app.modelconfig.schema import (
    FlagGate,
    MetricThresholdGate,
    PillarAgreementGate,
    PillarFloorGate,
)
from app.settings import REPO_ROOT

CONFIG = load_model_config(REPO_ROOT / "config" / "model")
SCALE = CONFIG.settings.letter_scale


# --- letters ------------------------------------------------------------------------------------

@pytest.mark.parametrize(("score", "letter"), [
    (100, "A+"), (91.67, "A+"), (91.6, "A"), (83.34, "A"), (83.3, "A-"), (75, "A-"), (74.99, "B+"),
    (66.34, "B"), (62, "B-"), (61.9, "C+"), (45, "C-"), (44.9, "D+"), (32, "D-"), (31.9, "F"), (0, "F"),
])
def test_letter_scale_uses_thirds(score, letter):
    assert letter_for(score, SCALE) == letter


def test_bands_cover_0_to_100_without_gaps():
    ordered = sorted(bands(SCALE).values())
    assert ordered[0][0] == 0
    for (_, hi), (lo, _) in zip(ordered, ordered[1:], strict=False):
        assert hi == pytest.approx(lo)


def test_cap_keeps_the_worse_grade():
    assert cap("A", "C") == "C"
    assert cap("D", "C") == "D"
    assert cap("B-", "B-") == "B-"
    assert GRADES[0] == "A+" and GRADES[-1] == "F"


def test_hysteresis_keeps_letter_inside_two_point_margin():
    # B band is [66.33, 70.67); 65.5 is below it but within 2 points.
    assert apply_hysteresis(65.5, "B-", "B", [], SCALE, 2, 5) == "B"


def test_hysteresis_switches_when_margin_is_cleared():
    assert apply_hysteresis(64.0, "B-", "B", [], SCALE, 2, 5) == "B-"


def test_hysteresis_switches_after_five_days_beyond_the_bound():
    assert apply_hysteresis(65.5, "B-", "B", ["B-", "B-", "B-"], SCALE, 2, 5) == "B"
    assert apply_hysteresis(65.5, "B-", "B", ["B-", "B-", "B-", "B-"], SCALE, 2, 5) == "B-"


def test_hysteresis_without_history_uses_raw_letter():
    assert apply_hysteresis(65.5, "B-", None, [], SCALE, 2, 5) == "B-"


# --- percentiles --------------------------------------------------------------------------------

def test_percentile_mid_rank_and_direction():
    group = [1, 2, 3, 4]
    assert percentile_of(4, group, higher_is_better=True) == 87.5
    assert percentile_of(1, group, higher_is_better=True) == 12.5
    assert percentile_of(1, group, higher_is_better=False) == 87.5
    assert percentile_of(2, [2, 2, 2], higher_is_better=True) == 50


def test_winsorize_clips_outliers_before_ranking():
    values = list(range(1, 20)) + [1_000_000]
    clipped = winsorize(values, 0.05, 0.95)
    assert max(clipped) < 1_000_000
    # The outlier and the next-highest value now tie at the top.
    assert percentile_of(1_000_000, values, higher_is_better=True, winsor=(0.05, 0.95)) == pytest.approx(
        percentile_of(19, values, higher_is_better=True, winsor=(0.05, 0.95)), abs=2.6)


def test_weighted_percentile_favours_recent_history():
    history, value = [1, 1, 10, 10], 5
    assert weighted_percentile_of(value, history, [1, 1, 1, 1], higher_is_better=True) == 50
    assert weighted_percentile_of(value, history, [1, 1, 3, 3], higher_is_better=True) == 25


# --- engine helpers -----------------------------------------------------------------------------

def full_input(template_id: str, pct: float = 90, tags: list[str] | None = None) -> GradeInput:
    """Every metric of the template present at the same percentile; flags clear."""
    t = CONFIG.templates[template_id]
    metrics = {}
    for p in t.pillars:
        for m in p.metrics:
            direct = CONFIG.metrics[m.id].scoring == "direct"
            metrics[m.id] = MetricInput(value=pct if direct else 1.0, peer_pct=None if direct else pct)
    for g in t.gates:
        if isinstance(g, MetricThresholdGate) and g.metric not in metrics:
            metrics[g.metric] = MetricInput(value=_safe_value(g))
        if isinstance(g, MetricThresholdGate) and g.metric in metrics:
            metrics[g.metric].value = _safe_value(g)
    flags = {g.flag: False for g in t.gates if isinstance(g, FlagGate)}
    return GradeInput(template_id=template_id, tags=tags or ["bank", "government", "l2", "solana"],
                      metrics=metrics, flags=flags)


def _safe_value(g: MetricThresholdGate) -> float:
    return g.value - 1 if g.op in (">", ">=") else g.value + 1


def _hit(inp: GradeInput, g) -> None:
    if isinstance(g, MetricThresholdGate):
        inp.metrics[g.metric].value = g.value + 1 if g.op in (">", ">=") else g.value - 1
    elif isinstance(g, FlagGate):
        inp.flags[g.flag] = True
    elif isinstance(g, PillarFloorGate):
        first = CONFIG.templates[inp.template_id].pillars[0]
        for m in first.metrics:
            inp.metrics[m.id].peer_pct = 5
            if CONFIG.metrics[m.id].scoring == "direct":
                inp.metrics[m.id].value = 5
    elif isinstance(g, PillarAgreementGate):
        for i, p in enumerate(CONFIG.templates[inp.template_id].pillars):
            for m in p.metrics:
                inp.metrics[m.id].peer_pct = 50
                if CONFIG.metrics[m.id].scoring == "direct":
                    inp.metrics[m.id].value = 50
            if i == 0:
                for m in p.metrics:
                    inp.metrics[m.id].peer_pct = 90


ALL_GATES = [(t.id, g) for t in CONFIG.templates.values() for g in t.gates]


@pytest.mark.parametrize(("template_id", "gate"), ALL_GATES, ids=[f"{t}:{g.id}" for t, g in ALL_GATES])
def test_every_gate_caps_the_grade_when_hit_and_only_then(template_id, gate):
    clear = grade(full_input(template_id), CONFIG)
    assert next(g for g in clear.gates if g.id == gate.id).status == "clear"
    inp = full_input(template_id)
    _hit(inp, gate)
    hit = grade(inp, CONFIG)
    result = next(g for g in hit.gates if g.id == gate.id)
    assert result.status == "hit"
    template = CONFIG.templates[template_id]
    uncapped = hit.hysteresis_letter or template.base_grade
    if isinstance(gate, PillarAgreementGate):
        assert hit.letter == gate.set_grade  # the input was better than C
    elif getattr(gate, "cap", None):
        expected = cap(uncapped, gate.cap)
        if template.max_grade:
            expected = cap(expected, template.max_grade)
        assert hit.letter == expected
        assert GRADES.index(hit.letter) >= GRADES.index(gate.cap)
    if getattr(gate, "label_nl", None):
        assert gate.label_nl in hit.labels


def test_gate_is_unknown_when_its_metric_is_missing():
    inp = full_input("stock_general")
    inp.metrics["beneish_m"] = MetricInput(value=None)
    res = grade(inp, CONFIG)
    gate = next(g for g in res.gates if g.id == "beneish_manipulation")
    assert gate.status == "unknown"
    assert res.letter == "A"  # score 90: an unknown gate never lowers the grade, but it is shown


# --- weighted templates -------------------------------------------------------------------------

def test_all_metrics_at_90th_percentile_give_score_90():
    res = grade(full_input("crypto_platform"), CONFIG)
    assert res.score == pytest.approx(90)
    assert res.coverage == pytest.approx(1.0)
    assert res.status == "graded"


def test_missing_pillar_redistributes_weight_and_lowers_coverage():
    inp = full_input("stock_general")
    for m in CONFIG.templates["stock_general"].pillars[0].metrics:  # quality, weight 25
        inp.metrics[m.id] = MetricInput(value=None)
    inp.metrics["roic"] = MetricInput(value=None)
    res = grade(inp, CONFIG)
    assert res.coverage == pytest.approx(0.75)
    assert res.score == pytest.approx(90)  # the remaining pillars still all score 90
    quality = next(p for p in res.pillars if p.id == "quality")
    assert quality.score is None and quality.effective_weight == 0
    assert sum(p.effective_weight for p in res.pillars) == pytest.approx(100)


def test_partly_filled_pillar_counts_partly_for_coverage():
    inp = full_input("crypto_platform")
    tokenomics = CONFIG.templates["crypto_platform"].pillars[0]
    for m in tokenomics.metrics[2:]:  # keep 2 of 8 metrics
        inp.metrics[m.id] = MetricInput(value=None)
    res = grade(inp, CONFIG)
    assert res.coverage == pytest.approx(1 - 0.25 * 6 / 8)


def test_coverage_thresholds_set_provisional_and_no_grade():
    inp = full_input("crypto_utility")
    for p in CONFIG.templates["crypto_utility"].pillars[:2]:  # tokenomics 30 + fundamentals 20 missing
        for m in p.metrics:
            inp.metrics[m.id] = MetricInput(value=None)
    res = grade(inp, CONFIG)
    assert res.coverage == pytest.approx(0.5) and res.status == "provisional" and "voorlopig" in res.labels
    for p in CONFIG.templates["crypto_utility"].pillars[2:4]:  # trend 20 + security 10
        for m in p.metrics:
            inp.metrics[m.id] = MetricInput(value=None)
    res = grade(inp, CONFIG)
    assert res.coverage == pytest.approx(0.2) and res.status == "no_grade"
    assert res.letter is None and "onder 40%" in res.reason_nl


def test_metrics_that_do_not_apply_are_left_out():
    bank = grade(full_input("stock_financial", tags=["bank"]), CONFIG)
    used = {m.id for p in bank.pillars for m in p.metrics}
    assert "combined_ratio" not in used and "cet1_buffer" in used
    assert bank.coverage == pytest.approx(1.0)
    insurer = grade(full_input("stock_financial", tags=["insurer"]), CONFIG)
    assert "solvency2_ratio" in {m.id for p in insurer.pillars for m in p.metrics}


def test_fallback_metric_is_used_only_when_primary_is_missing():
    inp = full_input("etf")
    inp.metrics["ongoing_charges"].peer_pct = 10
    with_primary = grade(inp, CONFIG)
    costs = next(p for p in with_primary.pillars if p.id == "costs")
    assert costs.score == pytest.approx(90) and not costs.metrics[0].used_as_fallback
    inp.metrics["tracking_difference"] = MetricInput(value=None)
    fallback = next(p for p in grade(inp, CONFIG).pillars if p.id == "costs")
    assert fallback.score == pytest.approx(10) and fallback.metrics[0].used_as_fallback
    assert fallback.coverage == pytest.approx(1.0)


def test_valuation_mixes_80_percent_peers_and_20_percent_own_history():
    inp = full_input("crypto_platform")
    inp.metrics["mcap_to_fees"] = MetricInput(value=1.0, peer_pct=50, own_pct=100)
    inp.metrics["mcap_to_active_addresses"] = MetricInput(value=1.0, peer_pct=50, own_pct=None)
    val = next(p for p in grade(inp, CONFIG).pillars if p.id == "valuation")
    assert val.score == pytest.approx((60 + 50) / 2)


def test_technical_score_is_used_directly():
    inp = full_input("index")
    inp.metrics["technical_score"] = MetricInput(value=37.5)
    res = grade(inp, CONFIG)
    assert res.timing == 37.5
    assert next(p for p in res.pillars if p.id == "trend").score == 37.5
    assert res.quality == pytest.approx(90)  # quality leaves out trend and momentum


def test_bandwidth_brackets_the_score():
    inp = full_input("stock_general")
    for m in CONFIG.templates["stock_general"].pillars[0].metrics:
        inp.metrics[m.id].peer_pct = 20
    res = grade(inp, CONFIG)
    assert res.score_low < res.score < res.score_high
    assert GRADES.index(res.letter_high) <= GRADES.index(res.letter) <= GRADES.index(res.letter_low)


def test_fx_carry_weight_halves_in_stress():
    calm, stressed = full_input("fx_pair"), full_input("fx_pair")
    calm.metrics["fx_vol_or_vix_percentile"] = MetricInput(value=50)
    stressed.metrics["fx_vol_or_vix_percentile"] = MetricInput(value=85)
    carry = lambda r: next(p for p in r.pillars if p.id == "carry")  # noqa: E731
    assert carry(grade(calm, CONFIG)).weight == 30
    assert carry(grade(stressed, CONFIG)).weight == 15


def test_same_input_gives_same_result():
    a, b = grade(full_input("crypto_defi", 73), CONFIG), grade(full_input("crypto_defi", 73), CONFIG)
    assert a.to_dict() == b.to_dict()
    assert GradeInput.from_dict(full_input("crypto_defi").to_dict()) == full_input("crypto_defi")


# --- memecoin and stablecoin --------------------------------------------------------------------

def test_memecoin_without_solana_is_c_speculative():
    res = grade(GradeInput(template_id="crypto_memecoin", tags=[], metrics={}), CONFIG)
    assert res.letter == "C" and "speculatie" in res.labels and res.status == "speculative"
    assert res.gates == []


def test_memecoin_solana_gates():
    base = dict(template_id="crypto_memecoin", tags=["solana"],
                metrics={"holders_top10": MetricInput(value=0.05)},
                flags={"mint_authority_active": False, "freeze_authority_active": False,
                       "liquidity_not_locked": False})
    assert grade(GradeInput(**base), CONFIG).letter == "C"
    risky = GradeInput(**{**base, "flags": {**base["flags"], "mint_authority_active": True}})
    assert grade(risky, CONFIG).letter == "F"
    concentrated = GradeInput(**{**base, "metrics": {"holders_top10": MetricInput(value=0.30)}})
    assert grade(concentrated, CONFIG).letter == "D"
    unknown = GradeInput(template_id="crypto_memecoin", tags=["solana"], metrics={}, flags={})
    res = grade(unknown, CONFIG)
    assert res.status == "no_grade" and "veiligheidscontrole" in res.reason_nl


@pytest.mark.parametrize(("deviation", "mica", "peg"), [(0.0, 1, 1), (0.0, 0, 3), (0.01, 0, 5), (0.005, 1, 2)])
def test_stablecoin_peg_safety(deviation, mica, peg):
    inp = GradeInput(template_id="crypto_stablecoin", tags=[], metrics={
        "peg_deviation": MetricInput(value=deviation), "mica_status": MetricInput(value=mica)})
    res = grade(inp, CONFIG)
    assert res.peg_safety == peg and res.letter is None and res.status == "peg_safety"
    assert "voorlopig" in res.labels  # 2 of 5 factors: coverage 40%


def test_peg_deviation_scoring_in_basis_points():
    t = CONFIG.templates["crypto_stablecoin"]
    assert peg_factor_score("peg_deviation", 0.0, t) == 100
    assert peg_factor_score("peg_deviation", 0.005, t) == pytest.approx(50)
    assert peg_factor_score("peg_deviation", 0.02, t) == 0
