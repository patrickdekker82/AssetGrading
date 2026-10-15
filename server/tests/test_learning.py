"""The learning loop (phase 9): guardrails, challengers in the shadow, promotion, rollback and the language-model
components. The three acceptance criteria each have their own test, marked ACCEPTANCE."""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.ai import load_ai_config
from app.ai.client import LlmResult
from app.evaluation.outcomes import EvaluationSettings
from app.ingest.report import Report
from app.learning import registry, stats
from app.learning.qualitative import quote_found, verify
from app.learning.quarterly import store_weight_proposal
from app.learning.weights import DataCoverage, Guardrails, check_weights, propose_weights
from tests.test_ingest import db, scalar  # noqa: F401  (shared fixtures)

W0 = {"value": 25.0, "quality": 20.0, "momentum": 20.0, "safety": 15.0, "growth": 10.0, "sentiment": 10.0}
ENOUGH = DataCoverage(backtest_months=150, assets_per_month=50, live_months=14)
G = Guardrails()


@pytest.fixture
def settings(config_dir):
    return EvaluationSettings.load(config_dir / "evaluation.yaml")


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


@pytest.fixture
def ai(config_dir):
    return load_ai_config(config_dir / "ai.yaml")


# --- guardrails ------------------------------------------------------------------------------------


def test_check_weights_names_every_broken_guardrail():
    assert check_weights(W0, W0, W0, G, ENOUGH) == []
    ok = {**W0, "value": 28.0, "growth": 7.0}
    assert check_weights(W0, W0, ok, G, ENOUGH) == []
    assert any("tellen op tot 101" in p for p in check_weights(W0, W0, {**W0, "value": 26.0}, G, ENOUGH))
    big = {**W0, "value": 41.0, "quality": 4.0}
    problems = check_weights(W0, W0, big, G, ENOUGH)
    assert any("value: 41% ligt buiten 5% tot 40%" in p for p in problems)
    assert any("quality: 4% ligt buiten 5% tot 40%" in p for p in problems)
    assert any("value: +16 procentpunt" in p for p in problems)
    assert any("quality" in p and "keer het startgewicht" in p for p in problems)
    assert check_weights(W0, W0, {"value": 100.0}, G, ENOUGH)[0].startswith("pijlers kloppen niet")
    short = DataCoverage(backtest_months=60, assets_per_month=12, live_months=0)
    assert len([p for p in check_weights(W0, W0, ok, G, short) if p.startswith("te weinig data")]) == 3


def _ic(strong: str, months: int = 40, seed: int = 4) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = [date(2014, 3, 31) + timedelta(days=91 * i) for i in range(months)]
    return {p: pd.Series(rng.normal(0.08 if p == strong else 0.0, 0.05, months), index=idx) for p in W0}


def test_proposal_moves_toward_the_measured_pillar_within_the_guardrails():
    res = propose_weights(W0, W0, _ic("momentum"), 120, G, ENOUGH)
    assert res.weights is not None
    assert check_weights(W0, W0, res.weights, G, ENOUGH) == []
    assert sum(res.weights.values()) == pytest.approx(100)
    assert res.weights["momentum"] == pytest.approx(23.0)               # +3 points: the quarterly limit
    assert res.evidence["lambda"] == pytest.approx(0.5)                 # min(0.5, 120 / 180)
    # The next quarter starts from the new weights and may move at most 3 points again.
    nxt = propose_weights(W0, res.weights, _ic("momentum"), 123, G, ENOUGH)
    assert nxt.weights["momentum"] <= 26.0 + 1e-9 and nxt.weights["momentum"] <= 1.5 * 20


def test_no_proposal_below_the_minimum_data_or_without_signal():
    short = DataCoverage(backtest_months=200, assets_per_month=40, live_months=3)
    res = propose_weights(W0, W0, _ic("momentum"), 120, G, short)
    assert res.weights is None and "startgewichten" in res.reason_nl and "live" in res.reason_nl
    neg = {p: s * 0 - 0.05 for p, s in _ic("value").items()}
    assert propose_weights(W0, W0, neg, 120, G, ENOUGH).weights is None


# --- statistics ------------------------------------------------------------------------------------


def test_deflated_sharpe_punishes_many_trials():
    rng = np.random.default_rng(7)
    skill = pd.Series(rng.normal(0.02, 0.03, 180))
    luck = pd.Series(rng.normal(0.002, 0.03, 180))
    assert stats.deflated_sharpe(skill, 3)["dsr"] > 0.95
    assert stats.deflated_sharpe(luck, 200)["dsr"] < 0.5


def test_pbo_separates_skill_from_data_mining():
    t = 160
    # Picking the best of pure noise: on average close to a coin flip whether it stays in the top half.
    noise_pbo = [stats.pbo(pd.DataFrame(np.random.default_rng(s).normal(0, 0.03, (t, 20))))["pbo"] for s in range(8)]
    assert np.mean(noise_pbo) > 0.3
    rng = np.random.default_rng(8)
    noise = pd.DataFrame(rng.normal(0, 0.03, (t, 20)))
    good = noise.copy()
    good[0] = rng.normal(0.03, 0.03, t)                                  # one configuration really is better
    assert stats.pbo(good)["pbo"] < 0.2


# --- registry: challengers, promotion, rollback ----------------------------------------------------


def _setup(sf, model):
    with sf() as session:
        _, vid = registry.load_active(session, model)
    return vid


def _valid_proposal(sf, model, vid, weights=None) -> int:
    t = "stock_general"
    w0 = registry.weights_of(model, t)
    first = next(iter(w0))
    weights = weights or {**w0, first: w0[first] + 2, list(w0)[-1]: w0[list(w0)[-1]] - 2}
    with sf() as session:
        pid, problems = store_weight_proposal(session, t, weights, w0, w0, G, ENOUGH, "model", "test", {}, vid)
    assert problems == []
    return pid


PASSED = [{"id": "all", "label_nl": "alles", "passed": True}]


def test_ACCEPTANCE_a_proposal_that_breaks_a_guardrail_is_refused(db, model, ai, settings):  # noqa: F811
    engine, sf = db
    vid = _setup(sf, model)
    w0 = registry.weights_of(model, "stock_general")
    first = next(iter(w0))
    bad = {**w0, first: w0[first] + 6, list(w0)[-1]: w0[list(w0)[-1]] - 6}      # 6 points in one quarter
    with sf() as session:
        pid, problems = store_weight_proposal(session, "stock_general", bad, w0, w0, G, ENOUGH, "model", "test",
                                              {}, vid)
    assert problems and scalar(engine, f"SELECT status FROM model_proposal WHERE id = {pid}") == "refused"
    assert "procentpunt" in scalar(engine, f"SELECT refusal::text FROM model_proposal WHERE id = {pid}")
    from app.evaluation.proposals import decide

    with sf() as session, pytest.raises(ValueError, match="refused"):
        decide(session, pid, True)                                       # a refused proposal cannot be approved
    # Even a proposal forced to 'approved' is checked again before it becomes a challenger.
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE model_proposal SET status = 'approved' WHERE id = {pid}"))
    with sf() as session, pytest.raises(registry.LearningError, match="Vangrail geschonden"):
        registry.create_challenger(session, pid, model, vid, G)
    # The language model's proposals pass the same check.
    from app.learning.review import quarterly_review

    class FakeReview:
        def create(self, params):
            body = {"samenvatting": "test", "voorstellen": [
                {"sjabloon": "stock_general", "gewichten": [{"pijler": p, "gewicht": 100 / len(w0)} for p in w0],
                 "bewijs": "x", "verwacht_effect": "y", "risicos": "z"}]}
            return LlmResult("end_turn", json.dumps(body), {"input_tokens": 10, "output_tokens": 10},
                             "claude-opus-5-5", "req")

    with sf() as session:
        ids = quarterly_review(session, ai, FakeReview(), settings, model, vid, Report())
    row = scalar(engine, f"SELECT jsonb_build_object('s', status, 'src', source, 'r', refusal) FROM model_proposal "
                         f"WHERE id = {ids[0]}")
    assert row["s"] == "refused" and row["src"] == "taalmodel" and row["r"]
    assert scalar(engine, "SELECT count(*) FROM llm_call WHERE component = 'quarterly_review'") == 1


def test_ACCEPTANCE_an_approved_switch_is_a_new_version_and_one_click_undoes_it(db, model):  # noqa: F811
    engine, sf = db
    vid = _setup(sf, model)
    pid = _valid_proposal(sf, model, vid)
    from app.evaluation.proposals import decide

    with sf() as session:
        decide(session, pid, True)
        cid = registry.create_challenger(session, pid, model, vid, G)
        challenger_vid = scalar(engine, f"SELECT model_version_id FROM challenger WHERE id = {cid}")
        new = registry.config_of(session, challenger_vid)
        assert new.version != model.version
        assert registry.weights_of(new, "stock_general") != registry.weights_of(model, "stock_general")
        assert registry.load_active(session, model)[1] == vid            # shadow: not active
        with pytest.raises(registry.LearningError, match="toetsen"):
            registry.promote(session, cid, [{"label_nl": "t", "passed": False}], 6)
        assert registry.promote(session, cid, PASSED, 6) == challenger_vid
        assert registry.load_active(session, model) == (new, challenger_vid) or \
            registry.load_active(session, model)[1] == challenger_vid
        assert registry.rollback(session) == vid                         # one click back
        assert registry.load_active(session, model)[1] == vid
        with pytest.raises(registry.LearningError):
            registry.rollback(session)                                   # cannot ping-pong back without checks
    with engine.connect() as conn:
        kinds = [r[0] for r in conn.execute(text("SELECT kind FROM model_activation ORDER BY id"))]
    assert kinds == ["baseline", "promote", "rollback"]


def test_at_most_one_switch_per_six_months(db, model):  # noqa: F811
    _, sf = db
    vid = _setup(sf, model)
    from app.evaluation.proposals import decide

    with sf() as session:
        p1 = _valid_proposal(sf, model, vid)
        decide(session, p1, True)
        c1 = registry.create_challenger(session, p1, model, vid, G)
        registry.promote(session, c1, PASSED, 6)
        active, active_id = registry.load_active(session, model)
        w = registry.weights_of(active, "stock_general")
        last = list(w)[-1]
        p2 = _valid_proposal(sf, active, active_id, {**w, last: w[last] + 1, list(w)[1]: w[list(w)[1]] - 1})
        decide(session, p2, True)
        c2 = registry.create_challenger(session, p2, active, active_id, G)
        with pytest.raises(registry.LearningError, match="6 maanden"):
            registry.promote(session, c2, PASSED, 6)
        assert registry.promote(session, c2, PASSED, 6, now=datetime.now(UTC) + timedelta(days=200))


def test_ACCEPTANCE_no_path_changes_weights_without_approval(db, model, ai, settings, stock_world):  # noqa: F811
    """Run everything that runs on its own (nightly grading with a challenger in the shadow, the monthly
    measurement with promotion checks, the quarterly round with the language model) and check that the active
    model never changed. And: only the registry can write the activation log, through promote and rollback."""
    from app.evaluation.proposals import decide
    from app.grading.stocks import grade_stocks
    from app.ingest.stocks import run_stocks
    from app.jobs import JobContext, grade_shadows, run_evaluation, run_quarterly

    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    run_stocks(sf, providers, cfg, stocks, universes, model, today=date.today())
    vid = _setup(sf, model)
    pid = _valid_proposal(sf, model, vid)
    with sf() as session:
        decide(session, pid, True)
        cid = registry.create_challenger(session, pid, model, vid, G)

    class FakeLlm:
        def create(self, params):
            body = {"samenvatting": "s", "voorstellen": []}
            return LlmResult("end_turn", json.dumps(body), {}, "claude-opus-5-5", "r")

    ctx = JobContext(engine, sf, providers, cfg, universes, model, vid, stocks=stocks, ai=ai, labels={},
                     llm_client=FakeLlm(), evaluation=settings)
    as_of = scalar(engine, "SELECT max(ts) FROM price_bar")
    rep = Report()
    grade_stocks(sf, model, vid, stocks, as_of)
    grade_shadows(ctx, rep, lambda c, v, sink: grade_stocks(sf, c, v, stocks, as_of, None, sink))
    assert rep.counts.get("shadow_snapshots_added", 0) > 0 and rep.errors == []
    run_evaluation(ctx)
    run_quarterly(ctx)
    assert scalar(engine, f"SELECT checks IS NOT NULL FROM challenger WHERE id = {cid}") is True
    with sf() as session:
        assert registry.load_active(session, model)[1] == vid
    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(text("SELECT kind FROM model_activation"))] == ["baseline"]

    # Structural guarantee: the only code that writes model_activation is the registry module.
    root = Path(__file__).resolve().parents[1] / "app"
    writers = {p.relative_to(root).as_posix() for p in root.rglob("*.py")
               if re.search(r"INSERT INTO model_activation", p.read_text(encoding="utf-8"))}
    assert writers == {"learning/registry.py"}
    src = (root / "learning" / "registry.py").read_text(encoding="utf-8")
    inserting = re.findall(r"def (\w+)\([^)]*\)[^:]*:(?:(?!\ndef ).)*INSERT INTO model_activation", src, re.S)
    assert sorted(inserting) == ["promote", "rollback", "sync_baseline"]


def test_promotion_checks_refuse_a_fresh_challenger_via_the_app(db, model, settings, test_database_url,  # noqa: F811
                                                               monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import get_engine
    from app.settings import get_settings

    engine, sf = db
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as client:
        vid = app.state.jobs.model_version_id
        pid = _valid_proposal(sf, model, vid)
        started = client.post(f"/api/model/proposals/{pid}/approve").json()
        assert started["status"] == "shadow"
        learning = client.get("/api/model/learning").json()
        assert learning["active"]["id"] == vid and learning["challengers"][0]["changes"]
        r = client.post(f"/api/model/challengers/{started['challenger']}/promote")
        assert r.status_code == 409 and "Minstens 6 maanden" in r.json()["detail"]
        assert client.post("/api/model/rollback").status_code == 409
        assert client.get("/api/model/learning").json()["active"]["id"] == vid
        assert client.post("/api/assets/nothing/qualitative", json={"source_name": "x", "text": "y"}).status_code \
            == 503
    get_settings.cache_clear()
    get_engine.cache_clear()


# --- qualitative features --------------------------------------------------------------------------


def test_quotes_must_be_in_the_source():
    source = "Het  bestuur keurde een aandeleninkoop goed van 2 miljard. Insiders houden 60% van de tokens."
    assert quote_found("het bestuur keurde een aandeleninkoop goed", source)
    assert not quote_found("het bestuur keurde een dividend goed", source)
    assert not quote_found("Insiders", source)                          # too short to prove anything
    data = {"rubrieken": [
        {"rubriek": "bestuur", "oordeel": "zwak", "toelichting": "t", "citaat": "keurde een aandeleninkoop goed"},
        {"rubriek": "concurrentievoordeel", "oordeel": "sterk", "toelichting": "t", "citaat": "een sterk merk"}],
        "rode_vlaggen": [{"omschrijving": "concentratie", "citaat": "Insiders houden 60% van de tokens"},
                         {"omschrijving": "verzonnen", "citaat": "de oprichter is vertrokken"}]}
    rubrics, flags, rejected = verify(data, source)
    assert rubrics["bestuur"]["oordeel"] == "zwak"
    assert rubrics["concurrentievoordeel"]["oordeel"] == "onvoldoende_bewijs"   # quote not in the source
    assert rubrics["tokenomics"]["oordeel"] == "onvoldoende_bewijs"
    assert [f["omschrijving"] for f in flags] == ["concentratie"] and rejected == 2


def test_qualitative_assessment_is_logged_and_kept(db, ai):  # noqa: F811
    from app.learning.qualitative import assess

    engine, sf = db
    with engine.begin() as conn:
        aid = conn.execute(text("INSERT INTO asset (asset_class, symbol, name, slug) VALUES ('crypto', 'T', 'Test', "
                                "'test') RETURNING id")).scalar()
    source = "Het team ontvangt 40% van alle tokens zonder lock-up. De code is open source."

    class Fake:
        def create(self, params):
            assert "Invoer" in params["messages"][0]["content"] and params["model"] == "claude-haiku-5-5"
            body = {"rubrieken": [{"rubriek": "tokenomics", "oordeel": "zwak", "toelichting": "t",
                                   "citaat": "ontvangt 40% van alle tokens zonder lock-up"}],
                    "rode_vlaggen": [{"omschrijving": "geen lock-up", "citaat": "40% van alle tokens zonder lock-up"}]}
            return LlmResult("end_turn", json.dumps(body), {"input_tokens": 5, "output_tokens": 5},
                             "claude-haiku-5-5", "r")

    with sf() as session:
        out = assess(session, ai, Fake(), aid, "whitepaper", source)
    assert out["rubrics"]["tokenomics"]["oordeel"] == "zwak" and len(out["red_flags"]) == 1
    assert scalar(engine, "SELECT count(*) FROM llm_call WHERE component = 'qualitative'") == 1
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE qualitative_assessment SET red_flags = '[]'"))


from tests.test_stocks import stock_world  # noqa: E402,F401


def test_a_month_with_live_grades_is_not_counted_twice(monkeypatch):
    import pandas as pd

    from app.learning import quarterly

    def frame(months):
        return pd.DataFrame([{"template_id": "t", "as_of": m, "asset_id": a, "excess": 0.01 * a}
                             for m in months for a in range(6)])

    bt, live = frame(["2026-07-31", "2026-08-31", "2026-09-30"]), frame(["2026-09-30"])
    monkeypatch.setattr(quarterly, "latest_run", lambda s, v: 1)
    monkeypatch.setattr(quarterly, "measurement_frame",
                        lambda s, kind, run, v, h: bt if kind == "backtest" else live)
    cov, df = quarterly.coverage_for(None, "t", 1, 6)
    assert (cov.backtest_months, cov.live_months) == (3, 1)
    assert len(df) == 18 and df.groupby("as_of").size().max() == 6
