"""Explanations by a language model (chapter 9): number check, retry, template fallback, budget, batches.

No test calls the real API: a fake client writes texts from the input, some of them with invented numbers.
"""

import dataclasses
import json
import random
import re
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.ai import load_ai_config, make_client
from app.ai.client import LlmResult
from app.ai.explanation import (
    SYSTEM_PROMPT,
    Explainer,
    build_input,
    check_result,
    needs_new,
    request_params,
    snapshot_on,
)
from app.ai.numbers import check_text, interpretations, numbers_in
from app.glossary import load_glossary
from app.grading.engine import GradeInput, MetricInput, grade
from app.grading.explain import explain
from app.models import Asset, GradeSnapshot
from tests.test_ingest import db, scalar  # noqa: F401  (shared fixtures)

AS_OF = date(2026, 10, 13)


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


@pytest.fixture
def ai(config_dir):
    return load_ai_config(config_dir / "ai.yaml")


@pytest.fixture
def labels(config_dir):
    return {k: v.label for k, v in load_glossary(config_dir / "glossary.nl.yaml").metrics.items()}


# --- the number check ------------------------------------------------------------------------------


def test_numbers_are_read_in_dutch_and_english_notation():
    assert interpretations("4,9") == {4.9}
    assert interpretations("1.234") == {1.234, 1234.0}
    assert interpretations("1.234,5") == {1234.5}
    assert interpretations("2026") == {2026.0}
    found = {tok for tok, _ in numbers_in("Een score van 72, een daling van -3% en vijfentwintig dagen.")}
    assert found == {"72", "3", "vijfentwintig"}
    # "in acht nemen" is not a number; "acht maanden" is.
    assert [t for t, _ in numbers_in("Neem dat in acht.")] == []
    assert [t for t, _ in numbers_in("Over acht maanden.")] == ["acht"]


def test_check_text_flags_invented_numbers_grades_and_forbidden_words():
    payload = {"score": 72, "grade": "B", "pijlers": [{"naam": "Waardering", "score": 4.9}], "datum": "2026-10-13"}
    assert check_text("Score 72 en grade B op 13-10-2026; waardering 4,9.", payload) == []
    problems = check_text("Score 73, grade A- en drie punten. Nu kopen.", payload)
    assert "getallen die niet in de invoer staan: 73, drie" in problems
    assert "grades die niet in de invoer staan: A-" in problems
    assert "verboden woorden: kopen" in problems
    assert any("woorden" in p for p in check_text("kort", payload, min_words=110))
    # S&P 500 and F-score are not grades; a sign is ignored.
    assert check_text("De S&P 500 en de Piotroski F-score dalen -72.", {"x": "S&P 500", "y": 72}) == []


def _good_answer(payload: dict, used: list[str] | None = None) -> str:
    return json.dumps({"tekst": _text_from(payload), "gebruikte_maatstaven": used or []})


FILLER = ("De berekening vergelijkt de asset met assets die er sterk op lijken en zegt daarom iets over de "
          "rangorde binnen die groep, niet over de toekomst. ")


def _text_from(payload: dict, invent: str = "") -> str:
    parts = [f"{payload['asset']} staat op {payload['datum']} in het sjabloon {payload['sjabloon']}."]
    if payload.get("grade") and payload.get("score") is not None:
        parts.append(f"De grade is {payload['grade']} met een score van {payload['score']}.")
    for m in payload["sterkste_punten"]:
        parts.append(f"Sterk is {m['naam']} met {m['score']}.")
    for m in payload["zwakste_punten"]:
        parts.append(f"Zwak is {m['naam']} met {m['score']}.")
    if invent:
        parts.append(invent)
    body = " ".join(parts)
    while len(body.split()) < 125:
        body += " " + FILLER
    return " ".join(body.split()[:200])


def test_check_result_needs_end_turn_valid_json_and_known_metrics(model, labels, ai):
    res = grade(_random_input(model, "crypto_platform", random.Random(1)), model).to_dict()
    payload = build_input("Testmunt", AS_OF, res, model, labels)
    ok = check_result(LlmResult(stop_reason="end_turn", text=_good_answer(payload)), payload, ai)
    assert ok.passed, ok.problems
    cut = check_result(LlmResult(stop_reason="max_tokens", text=_good_answer(payload)[:40]), payload, ai)
    assert not cut.passed and cut.problems == ["stopreden max_tokens"]
    refused = check_result(LlmResult(stop_reason="refusal", text=""), payload, ai)
    assert refused.problems == ["stopreden refusal"]
    broken = check_result(LlmResult(stop_reason="end_turn", text="geen json"), payload, ai)
    assert broken.problems == ["antwoord volgt het schema niet"]
    unknown = check_result(LlmResult(stop_reason="end_turn", text=_good_answer(payload, ["verzonnen"])), payload, ai)
    assert unknown.problems == ["onbekende maatstaven: verzonnen"]


def test_request_asks_json_by_schema_with_the_cached_instruction(model, labels, ai):
    res = grade(_random_input(model, "stock_general", random.Random(2)), model).to_dict()
    params = request_params(ai, build_input("Test NV", AS_OF, res, model, labels))
    assert params["model"] == ai.explanation.model == "claude-haiku-5-5"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == SYSTEM_PROMPT
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in params and "thinking" not in params


def test_regenerate_only_when_grade_or_pillar_moves_more_than_five_points(model, labels):
    res = grade(_random_input(model, "crypto_platform", random.Random(3)), model).to_dict()
    snap = _snap(res)
    prev = {"status": snap.status, "letter": snap.letter, "score": snap.score, "peg_safety": None,
            "pillars": snap.pillars()}
    assert not needs_new(prev, snap, 5)
    first = next(k for k, v in prev["pillars"].items() if v is not None)
    assert not needs_new({**prev, "pillars": {**prev["pillars"], first: prev["pillars"][first] + 5}}, snap, 5)
    assert needs_new({**prev, "pillars": {**prev["pillars"], first: prev["pillars"][first] + 5.1}}, snap, 5)
    assert needs_new({**prev, "letter": "F" if snap.letter != "F" else "A"}, snap, 5)
    assert needs_new(None, snap, 5)


def test_without_api_key_there_is_no_client(ai):
    assert make_client(ai, env={}) is None
    assert make_client(ai, env={"ANTHROPIC_API_KEY": "  "}) is None


def test_cost_follows_prices_cache_and_batch_discount(ai):
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert ai.cost_usd("claude-haiku-5-5", usage, batch=False) == pytest.approx(0.10 + 0.50 + 0.01)
    assert ai.cost_usd("claude-haiku-5-5", usage, batch=True) == pytest.approx((0.10 + 0.50 + 0.01) / 2)


# --- 100 generated explanations through the whole pipeline -----------------------------------------


def _random_input(model, template_id: str, rng: random.Random) -> GradeInput:
    template = model.templates[template_id]
    metrics = {}
    for p in template.pillars:
        for m in p.metrics:
            if rng.random() < 0.85:
                metrics[m.id] = MetricInput(value=rng.uniform(-2, 50), peer_pct=rng.uniform(0, 100))
    return GradeInput(template_id=template_id, tags=[], metrics=metrics, flags={})


def _snap(res: dict, asset_id: int = 1, name: str = "Testmunt"):
    from app.ai.explanation import Snapshot

    return Snapshot(asset_id, name, AS_OF, 1, res, res["status"], res["letter"], res["score"], res["peg_safety"])


class FakeLlm:
    """Batch and direct calls; asset i invents a number when i % 4 == 0 (and again on retry when i % 12 == 0),
    is cut off at max_tokens when i % 7 == 0 and refused when i % 25 == 1."""

    def __init__(self):
        self.batches: dict[str, list] = {}
        self.direct: list[dict] = []

    @staticmethod
    def _payload(params: dict) -> dict:
        content = params["messages"][0]["content"]
        return json.loads(content.removeprefix("Invoer:\n").split("\n\nEen eerdere")[0])

    def _answer(self, params: dict, retry: bool) -> LlmResult:
        payload = self._payload(params)
        i = int(re.search(r"(\d+)$", payload["asset"]).group(1))
        usage = {"input_tokens": 1500, "output_tokens": 400, "cache_read_input_tokens": 900}
        if not retry and i % 7 == 0:
            return LlmResult("max_tokens", '{"tekst": "Afgebroken', usage, "claude-haiku-5-5", f"req_{i}")
        if not retry and i % 25 == 1:
            return LlmResult("refusal", "", usage, "claude-haiku-5-5", f"req_{i}")
        invent = ""
        if (not retry and i % 4 == 0) or (retry and i % 12 == 0):
            invent = "Het rendement lag 987,65 procent hoger dan vorig jaar."
        used = [m["id"] for m in payload["sterkste_punten"]]
        body = json.dumps({"tekst": _text_from(payload, invent), "gebruikte_maatstaven": used}, ensure_ascii=False)
        return LlmResult("end_turn", body, usage, "claude-haiku-5-5", f"req_{i}")

    def submit_batch(self, requests):
        batch_id = f"msgbatch_{len(self.batches) + 1:03d}"
        self.batches[batch_id] = requests
        return batch_id

    def batch_status(self, batch_id):
        return "ended"

    def cancel_batch(self, batch_id):
        pass

    def batch_results(self, batch_id):
        for custom_id, params in self.batches[batch_id]:
            yield custom_id, self._answer(params, retry=False)

    def create(self, params):
        self.direct.append(params)
        return self._answer(params, retry="Een eerdere tekst" in params["messages"][0]["content"])


TEMPLATES = ["crypto_platform", "crypto_defi", "crypto_bitcoin", "crypto_memecoin", "crypto_stablecoin",
             "stock_general", "stock_financial", "stock_reit", "etf", "bond", "index", "commodity",
             "precious_metal", "fx_pair", "crypto_utility", "crypto_rwa"]


@pytest.fixture
def hundred(db, model):  # noqa: F811
    """100 assets across all 16 templates, each with a random grade snapshot."""
    from app.registry import register_model_version

    _, sf = db
    rng = random.Random(7)
    with sf() as session:
        version_id = register_model_version(session, model).id
        for i in range(1, 101):
            template_id = TEMPLATES[i % len(TEMPLATES)]
            asset = Asset(asset_class="crypto", symbol=f"T{i}", name=f"Testasset {i}", slug=f"testasset-{i}")
            session.add(asset)
            session.flush()
            res = grade(_random_input(model, template_id, rng), model)
            session.add(GradeSnapshot(
                asset_id=asset.id, as_of=AS_OF, model_version_id=version_id, template_id=template_id,
                status=res.status, score=res.score, quality=res.quality, timing=res.timing, coverage=res.coverage,
                letter=res.letter, peg_safety=res.peg_safety, price_eur=1.0, knowledge_time=datetime.now(UTC),
                inputs={}, result=res.to_dict()))
        session.commit()
    return sf, version_id


def test_hundred_explanations_contain_no_number_outside_the_input(hundred, model, ai, labels, db):  # noqa: F811
    sf, version_id = hundred
    engine, _ = db
    fake = FakeLlm()
    explainer = Explainer(sf, ai, model, version_id, labels, fake)

    first = explainer.run()                      # nothing to collect yet; submits one batch of 100
    assert first.counts == {"explanations_submitted": 100}
    assert scalar(engine, "SELECT count(*) FROM explanation") == 0
    second = explainer.run()                     # collects the batch, retries what failed, falls back
    assert second.counts["batches_collected"] == 1

    with sf() as session:
        rows = session.execute(text(
            "SELECT e.*, a.name FROM explanation e JOIN asset a ON a.id = e.asset_id ORDER BY e.asset_id")).all()
        assert len(rows) == 100
        for row in rows:
            snap = snapshot_on(session, version_id, row.asset_id, row.snapshot_as_of)
            payload = build_input(snap.name, snap.as_of, snap.result, model, labels)
            # The acceptance criterion: no number (and no grade) that was not in the input.
            assert check_text(row.text, payload) == [], (row.name, row.source, row.text)
            if row.source == "template":
                assert row.text == explain(snap.name, snap.result, model, labels)
            else:
                assert set(row.used_metrics) <= {m["id"] for m in payload["maatstaven"]}

    failing_first = {i for i in range(1, 101) if i % 4 == 0 or i % 7 == 0 or i % 25 == 1}
    failing_twice = {i for i in range(1, 101) if i % 12 == 0}
    assert second.counts["explanations_rejected"] == len(failing_first)
    assert len(fake.direct) == len(failing_first)                     # exactly one new attempt each
    assert second.counts["explanations_template"] == len(failing_twice)
    assert second.counts["explanations_written"] == 100 - len(failing_twice)
    assert scalar(engine, "SELECT count(*) FROM explanation WHERE source = 'template'") == len(failing_twice)

    # Every call is logged: model, prompt version, input hash and the raw output.
    assert scalar(engine, "SELECT count(*) FROM llm_call") == 100 + len(failing_first)
    assert scalar(engine, "SELECT count(*) FROM llm_call WHERE length(input_hash) = 64 AND model = "
                          "'claude-haiku-5-5' AND prompt_version = 'explanation-1'") == 100 + len(failing_first)
    assert scalar(engine, "SELECT count(DISTINCT input_hash) FROM llm_call") == 100
    assert scalar(engine, "SELECT count(*) FROM llm_call WHERE mode = 'batch' AND cost_usd > 0") == 100
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE explanation SET text = 'x'"))

    third = explainer.run()                      # nothing moved: nothing is rewritten
    assert third.counts == {} and "Alle toelichtingen zijn actueel." in third.notes
    assert len(fake.batches) == 1


def test_monthly_budget_is_a_hard_stop(hundred, model, ai, labels, db):  # noqa: F811
    sf, version_id = hundred
    engine, _ = db
    fake = FakeLlm()
    one = Explainer(sf, ai, model, version_id, labels, fake)
    with sf() as session:
        from app.ai.explanation import estimate_usd

        cost = estimate_usd(ai, request_params(ai, one.payload(one.candidates(session)[0])), batch=True)
    tight = dataclasses.replace(ai, monthly_budget_usd=cost * 10.5)
    report = Explainer(sf, tight, model, version_id, labels, fake).run()
    assert report.counts["explanations_submitted"] == 10
    assert any("Maandbudget" in n for n in report.notes)
    # The reservation of the running batch counts: nothing more is sent until it has ended.
    again = Explainer(sf, tight, model, version_id, labels, FakeLlm())
    with sf() as session:
        assert again._budget_left(session) < cost
    assert scalar(engine, "SELECT count(*) FROM llm_batch WHERE status = 'submitted'") == 1


def test_without_a_client_the_job_only_notes_the_template(hundred, model, ai, labels, db):  # noqa: F811
    sf, version_id = hundred
    report = Explainer(sf, ai, model, version_id, labels, None).run()
    assert report.errors == [] and report.counts == {}
    assert "sjabloontekst" in report.notes[0]
