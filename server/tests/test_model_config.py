from pathlib import Path

import pytest
import yaml

from app.modelconfig import ModelConfigError, load_model_config
from app.modelconfig.loader import fingerprint, write_lock

EXPECTED_TEMPLATES = {
    "stock_general", "stock_financial", "stock_reit", "etf", "bond", "index",
    "crypto_bitcoin", "crypto_platform", "crypto_defi", "crypto_utility", "crypto_stablecoin",
    "crypto_memecoin", "crypto_rwa", "commodity", "precious_metal", "fx_pair",
}


def edit(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def test_all_sixteen_templates_load(config_dir):
    config = load_model_config(config_dir / "model")
    assert set(config.templates) == EXPECTED_TEMPLATES


def test_weighted_templates_sum_to_100(config_dir):
    config = load_model_config(config_dir / "model")
    for t in config.templates.values():
        if t.grading == "weighted":
            assert sum(p.weight for p in t.pillars) == 100, t.id


@pytest.mark.parametrize(
    ("template", "weights"),
    [
        ("stock_general", {"quality": 25, "value": 20, "momentum": 20, "safety": 15, "revisions": 10, "growth": 10}),
        ("stock_financial", {"valuation": 30, "profitability": 25, "capital_credit": 25, "momentum_revisions": 20}),
        ("etf", {"costs": 40, "tradability": 20, "structure_tax": 20, "survival": 10, "diversification": 10}),
        ("crypto_utility", {"tokenomics": 30, "fundamentals": 20, "trend": 20, "security": 10,
                            "valuation": 10, "liquidity": 10}),
        ("crypto_platform", {"tokenomics": 25, "fundamentals": 20, "trend": 20, "security": 10,
                             "valuation": 10, "liquidity": 10, "attention": 5}),
        ("fx_pair", {"carry": 30, "momentum": 25, "value": 25, "macro": 10, "positioning": 10}),
    ],
)
def test_starting_weights_match_the_specification(config_dir, template, weights):
    config = load_model_config(config_dir / "model")
    assert {p.id: p.weight for p in config.templates[template].pillars} == weights


def test_gate_values_match_the_specification(config_dir):
    t = load_model_config(config_dir / "model").templates
    gates = {g.id: g for g in t["stock_general"].gates}
    assert (gates["beneish_manipulation"].value, gates["beneish_manipulation"].cap) == (-1.78, "C")
    assert (gates["altman_distress"].value, gates["altman_distress"].cap) == (1.81, "C")
    assert (gates["weak_pillar"].threshold, gates["weak_pillar"].cap) == (20, "B-")
    assert {g.id: g.cap for g in t["crypto_memecoin"].gates}["concentrated_holders"] == "D"
    assert t["crypto_memecoin"].max_grade == "C"


def test_every_template_has_a_timing_pillar_or_no_pillars(config_dir):
    for t in load_model_config(config_dir / "model").templates.values():
        if t.grading == "weighted" and t.id not in {"etf", "bond", "crypto_rwa"}:
            assert any(p.timing for p in t.pillars), t.id


def test_lock_file_matches_current_configuration(config_dir):
    # Fails when the model changed without a version bump.
    load_model_config(config_dir / "model", check_lock=True)


def test_change_without_version_bump_is_rejected(model_copy):
    edit(model_copy / "templates" / "etf.yaml", lambda d: d["pillars"][0].update(name_nl="Kosten!"))
    with pytest.raises(ModelConfigError, match="bump"):
        load_model_config(model_copy)


def test_version_bump_and_lock_accepts_change(model_copy):
    edit(model_copy / "templates" / "etf.yaml", lambda d: d["pillars"][0].update(name_nl="Kosten!"))
    edit(model_copy / "model.yaml", lambda d: d.update(version="0.1.1"))
    write_lock(load_model_config(model_copy, check_lock=False), model_copy)
    assert load_model_config(model_copy).version == "0.1.1"


def test_relocking_an_old_version_with_other_content_is_refused(model_copy):
    edit(model_copy / "templates" / "etf.yaml", lambda d: d["pillars"][0].update(name_nl="Kosten!"))
    with pytest.raises(ModelConfigError, match="already locked"):
        write_lock(load_model_config(model_copy, check_lock=False), model_copy)


def test_comments_do_not_change_the_fingerprint(model_copy):
    before = load_model_config(model_copy).config_hash
    path = model_copy / "templates" / "bond.yaml"
    path.write_text("# extra comment\n" + path.read_text())
    assert load_model_config(model_copy).config_hash == before


def test_weights_not_summing_to_100_are_rejected(model_copy):
    edit(model_copy / "templates" / "index.yaml", lambda d: d["pillars"][0].update(weight=31))
    with pytest.raises(ModelConfigError, match="sum to 101"):
        load_model_config(model_copy, check_lock=False)


def test_unknown_metric_is_rejected(model_copy):
    edit(model_copy / "templates" / "index.yaml", lambda d: d["pillars"][1]["metrics"].append("made_up"))
    with pytest.raises(ModelConfigError, match="made_up"):
        load_model_config(model_copy, check_lock=False)


def test_unknown_key_is_rejected(model_copy):
    edit(model_copy / "templates" / "index.yaml", lambda d: d["pillars"][0].update(wieght=30))
    with pytest.raises(ModelConfigError, match="wieght"):
        load_model_config(model_copy, check_lock=False)


def test_gate_without_effect_is_rejected(model_copy):
    def drop_cap(d):
        d["gates"][0].pop("cap")
    edit(model_copy / "templates" / "etf.yaml", drop_cap)
    with pytest.raises(ModelConfigError, match="needs a cap or a label"):
        load_model_config(model_copy, check_lock=False)


def test_unscored_metric_in_pillar_is_rejected(model_copy):
    edit(model_copy / "templates" / "index.yaml", lambda d: d["pillars"][1]["metrics"].append("beneish_m"))
    with pytest.raises(ModelConfigError, match="no direction"):
        load_model_config(model_copy, check_lock=False)


def test_file_name_must_match_id(model_copy):
    edit(model_copy / "templates" / "index.yaml", lambda d: d.update(id="indexx"))
    with pytest.raises(ModelConfigError, match="file name"):
        load_model_config(model_copy, check_lock=False)


def test_letter_scale_must_descend(model_copy):
    edit(model_copy / "model.yaml", lambda d: d["letter_scale"].update(B=80))
    with pytest.raises(ModelConfigError, match="descend"):
        load_model_config(model_copy, check_lock=False)


def test_fingerprint_is_order_independent():
    assert fingerprint({"a": 1, "b": [1, 2]}) == fingerprint({"b": [1, 2], "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})
