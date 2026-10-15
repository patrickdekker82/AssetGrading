"""Outcomes, monthly measurement, the point-in-time backtest, calibration and model proposals (chapter 8)."""

import shutil
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from app.evaluation import metrics
from app.evaluation.backtest import Backtest, end_of_day, evaluate_live
from app.evaluation.outcomes import (
    EvaluationSettings,
    GradeRow,
    add_months,
    compute_outcomes,
    last_weekday,
    month_ends,
    period,
)
from app.evaluation.proposals import apply_proposal, decide, next_version, write_letter_scale
from app.evaluation.report import calibrate_scale, distribution
from app.grading.crypto import SnapshotSink
from app.grading.stocks import grade_stocks
from app.ingest.stocks import run_stocks
from tests.test_ingest import db, scalar  # noqa: F401  (shared fixtures)
from tests.test_stocks import TODAY, stock_world  # noqa: F401


@pytest.fixture
def settings(config_dir):
    return EvaluationSettings.load(config_dir / "evaluation.yaml")


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


# --- calendar --------------------------------------------------------------------------------------


def test_month_end_calendar():
    assert last_weekday(date(2019, 3, 5)) == date(2019, 3, 29)          # 31 March 2019 was a Sunday
    assert add_months(date(2019, 1, 31), 1) == date(2019, 2, 28)
    assert add_months(date(2019, 11, 29), 3) == date(2020, 2, 29)
    assert month_ends(date(2019, 1, 1), date(2019, 4, 30)) == [date(2019, 1, 31), date(2019, 2, 28),
                                                                date(2019, 3, 29), date(2019, 4, 30)]


# --- statistics ------------------------------------------------------------------------------------


def test_newey_west_matches_the_plain_standard_error_without_lags():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(0.02, 0.1, 120))
    nw = metrics.newey_west(x, 0)
    assert nw["se"] == pytest.approx(x.std(ddof=0) / np.sqrt(len(x)))
    # Overlapping (autocorrelated) observations make the error larger, not smaller.
    overlapped = x.rolling(6).mean().dropna()
    assert metrics.newey_west(overlapped, 5)["se"] > metrics.newey_west(overlapped, 0)["se"]
    assert metrics.newey_west(x[:4], 0)["t"] is None                     # too few months for a t-value


def _frame(months=24, assets=30, signal=1.0, seed=2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(months):
        as_of = last_weekday(date(2015, 1, 1) + timedelta(days=31 * m))
        for a in range(assets):
            score = float(rng.uniform(0, 100))
            excess = signal * (score - 50) / 500 + float(rng.normal(0, 0.02))
            letter = "A" if score >= 90 else "B" if score >= 70 else "C" if score >= 30 else "D" if score >= 10 else "F"
            rows.append({"asset_id": a, "as_of": as_of, "score": score, "letter": letter, "excess": excess,
                         "drawdown": -abs(excess), "regime": "neutral" if m % 2 else "risk_on",
                         "p_value": score, "p_noise": float(rng.uniform(0, 100))})
    return pd.DataFrame(rows)


def test_measurement_finds_a_real_signal_and_its_letter_order():
    out = metrics.measure(_frame(), 3, {"min_assets_per_month": 5,
                                        "big_miss": {"letters": ["A", "B"], "excess_below": -0.3}})
    assert out["newey_west_lags"] == 2
    assert out["ic"]["mean"] > 0.5 and out["ic"]["t_newey_west"] > 3 and out["ic"]["share_positive"] == 1
    assert out["letters"]["order"]["holds"] is True
    assert out["letters"]["order"]["rank_correlation"] == pytest.approx(1)
    assert out["letters"]["a_minus_f"]["mean"] > 0
    assert out["pillars"]["ic"]["value"]["mean"] > 0.5 > abs(out["pillars"]["ic"]["noise"]["mean"])
    assert out["coverage"] == {"months": 24, "assets": 30, "assets_per_month": 30.0, "min_assets_per_month": 30,
                               "first": "2015-01-30", "last": out["coverage"]["last"]}
    assert set(out["regime"]) == {"neutral", "risk_on"}
    ci = out["letters"]["per_letter"]["A"]["ci95"]
    assert ci[0] < out["letters"]["per_letter"]["A"]["monthly_mean"] < ci[1]


def test_measurement_without_signal_is_not_significant():
    out = metrics.measure(_frame(signal=0.0, seed=5), 1, {})
    assert abs(out["ic"]["t_newey_west"]) < 3


def test_turnover_counts_letter_changes():
    df = pd.DataFrame({"asset_id": [1, 1, 1, 2, 2], "as_of": [1, 2, 3, 1, 2],
                       "letter": ["B", "B-", "C", "A", "A"]})
    t = metrics.turnover(df)
    assert t["pairs"] == 3 and t["letter_changed"] == pytest.approx(2 / 3) and t["base_letter_changed"] == 1 / 3


# --- outcomes --------------------------------------------------------------------------------------


def _prices(start: date, values: list[float]) -> pd.Series:
    return pd.Series(values, index=[start + timedelta(days=i) for i in range(len(values))])


def test_outcome_return_benchmark_and_drawdown(settings):
    start = date(2020, 1, 31)
    days = (add_months(start, 1) - start).days + 1
    path = list(np.linspace(100, 200, days))
    path[10] = 50                                                     # a fall to half on the way
    asset = _prices(start, path)
    bench = _prices(start, list(np.linspace(100, 110, days)))
    g = GradeRow(1, "stock", "US", "stock_general", start)
    rows = compute_outcomes([g], {1: asset}, {"sp500": bench}, settings, today=date(2026, 1, 1))
    one = next(r for r in rows if r["horizon_months"] == 1)
    assert one["total_return"] == pytest.approx(1.0)
    assert one["benchmark"] == "sp500" and one["excess_return"] == pytest.approx(0.9)
    assert one["max_drawdown"] == pytest.approx(50 / path[9] - 1)
    assert {r["horizon_months"] for r in rows} == {1}                # longer horizons have no prices
    # A horizon that has not ended yet has no outcome.
    assert compute_outcomes([g], {1: asset}, {"sp500": bench}, settings, today=start + timedelta(days=20)) == []


def test_class_average_and_no_benchmark(settings):
    start = date(2020, 1, 31)
    n = 40
    a = _prices(start, list(np.linspace(100, 120, n)))
    b = _prices(start, list(np.linspace(100, 100, n)))
    grades = [GradeRow(1, "commodity", None, "commodity", start), GradeRow(2, "commodity", None, "commodity", start),
              GradeRow(3, "fx", None, "fx_pair", start)]
    rows = compute_outcomes(grades, {1: a, 2: b, 3: a}, {}, settings, today=date(2026, 1, 1))
    by = {(r["asset_id"], r["horizon_months"]): r for r in rows}
    assert by[(1, 1)]["benchmark"] == "class_average"
    assert by[(1, 1)]["excess_return"] == pytest.approx(-by[(2, 1)]["excess_return"])
    assert by[(3, 1)]["benchmark"] is None and by[(3, 1)]["excess_return"] == by[(3, 1)]["total_return"]


def test_stale_prices_give_no_outcome():
    s = _prices(date(2020, 1, 1), [1.0] * 10)
    assert period(s, date(2020, 1, 5), date(2020, 3, 1)) is None


def test_a_price_below_zero_gives_no_outcome():
    s = _prices(date(2020, 4, 1), [20.0, 5.0, -37.6, 10.0, 25.0])      # WTI, April 2020
    assert period(s, date(2020, 4, 1), date(2020, 4, 5)) is None
    assert period(s, date(2020, 4, 4), date(2020, 4, 5)) == pytest.approx((1.5, 0.0))


def test_a_unit_switch_is_not_a_return():
    s = _prices(date(2012, 1, 1), [0.3, 0.31, 30.5, 31.0])           # pence/pound switch in a London ETC
    assert period(s, date(2012, 1, 1), date(2012, 1, 4)) is None
    assert period(s, date(2012, 1, 1), date(2012, 1, 4), None) is not None   # crypto: no such limit


# --- calibration and proposals ---------------------------------------------------------------------


def test_calibration_hits_the_target_distribution():
    scores = pd.Series(np.random.default_rng(3).normal(50, 8, 5000))   # clumped around 50, as in practice
    target = {"A": 0.10, "B": 0.20, "C": 0.40, "D": 0.20, "F": 0.10}
    scale = calibrate_scale(scores, target, 0.5)
    assert scale["A"] > scale["B"] > scale["C"] > scale["D"] > scale["F"] == 0
    dist = distribution(scores, scale)
    for letter, share in target.items():
        assert dist[letter] == pytest.approx(share, abs=0.02)
    provisional = distribution(scores, {"A": 75, "B": 62, "C": 45, "D": 32, "F": 0})
    assert provisional["A"] < 0.01 and provisional["C"] > 0.6            # why calibration is needed


def test_letter_scale_block_is_replaced_not_stacked(tmp_path):
    f = tmp_path / "etf.yaml"
    f.write_text("id: etf\nname_nl: ETF\n")
    write_letter_scale(f, {"A": 60, "B": 55, "C": 45, "D": 40, "F": 0}, "run 1")
    write_letter_scale(f, {"A": 61.5, "B": 55, "C": 45, "D": 40, "F": 0}, "run 2")
    body = f.read_text()
    assert body.count("letter_scale") == 1 and "A: 61.5" in body and "run 2" in body
    assert next_version("0.5.0") == "0.6.0"


# --- the point-in-time backtest --------------------------------------------------------------------


def _backtest(sf, model, version_id, settings, stocks):
    return Backtest(sf, model, version_id, settings, None, stocks, None, None)


def _result(engine, run_id: int, slug: str) -> dict:
    """The engine input (every metric value) and the grade of one asset in one run."""
    return scalar(engine, f"SELECT jsonb_build_object('input', b.inputs->'grade_input', 'result', b.result) "
                          f"FROM backtest_snapshot b JOIN asset a ON a.id = b.asset_id "
                          f"WHERE b.run_id = {run_id} AND a.slug = '{slug}'")


def _new_run(engine, version_id: int) -> int:
    with engine.begin() as conn:
        return conn.execute(text("INSERT INTO backtest_run (model_version_id, params, status) "
                                 "VALUES (:v, '{}', 'running') RETURNING id"), {"v": version_id}).scalar()


def test_backtest_ignores_a_deliberately_shifted_fact(db, stock_world, model, settings):  # noqa: F811
    """The acceptance test of phase 8: a fact (and a price) published after the month-end must not change
    that month's backtest grade; the same fact does change the grade once it is known."""
    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    assert run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY).errors == []
    with sf() as session:
        version_id = register_model_version(session, model).id
    day = last_weekday(add_months(TODAY, -8))
    bt = _backtest(sf, model, version_id, settings, stocks)
    from app.ingest.report import Report

    run_a = _new_run(engine, version_id)
    bt.grade_month(run_a, day, ["stocks"], Report())
    before = _result(engine, run_a, "aaa")
    assert before["input"]["metrics"]["earnings_yield"]["value"] > 0     # the filings were used

    # A restatement of every AAA filing up to that day, filed one day after it, and a wild price the next day.
    shifted = end_of_day(day) + timedelta(days=1)
    with engine.begin() as conn:
        aaa = conn.execute(text("SELECT id FROM asset WHERE slug = 'aaa'")).scalar()
        n = conn.execute(text(
            """
            INSERT INTO fundamental_fact (asset_id, field, as_of, value, unit, source, available_at, fetched_at)
            SELECT asset_id, field, as_of, value * 5, unit, source, :t, :t FROM fundamental_fact
            WHERE asset_id = :a AND source = 'sec' AND as_of <= :d AND field NOT LIKE '%shares%'
            """), {"a": aaa, "d": day, "t": shifted}).rowcount
        conn.execute(text(
            """
            INSERT INTO price_bar (asset_id, interval, ts, open, high, low, close, volume, source, quote_currency,
                                   fetched_at)
            SELECT asset_id, interval, ts + 1, open * 10, high * 10, low * 10, close * 10, volume, source,
                   quote_currency, now()
            FROM price_bar WHERE asset_id = :a AND interval = '1d' AND ts = :d
            ON CONFLICT DO NOTHING
            """), {"a": aaa, "d": day})
    assert n > 10

    run_b = _new_run(engine, version_id)
    bt.grade_month(run_b, day, ["stocks"], Report())
    assert _result(engine, run_b, "aaa") == before                   # nothing from after the month-end

    run_c = _new_run(engine, version_id)                              # the same day, graded after the restatement
    grade_stocks(sf, model, version_id, stocks, day, shifted + timedelta(hours=1), SnapshotSink(run_id=run_c))
    after = _result(engine, run_c, "aaa")
    assert after["input"]["metrics"]["earnings_yield"]["value"] != before["input"]["metrics"]["earnings_yield"]["value"]


def test_backtest_run_is_kept_apart_from_live_grades(db, stock_world, model, settings):  # noqa: F811
    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    with sf() as session:
        version_id = register_model_version(session, model).id
    # The fake world has no S&P 500: measure the stocks against each other.
    settings.benchmarks["stock_general"] = settings.benchmarks["stock_financial"] = "class_average"
    bt = _backtest(sf, model, version_id, settings, stocks)
    run_id, report = bt.run(date(TODAY.year - 1, TODAY.month, 1), add_months(TODAY, -2), ["stocks"], today=TODAY)
    assert report.errors == [], report.errors[:3]
    assert scalar(engine, "SELECT count(*) FROM grade_snapshot") == 0
    assert scalar(engine, f"SELECT count(DISTINCT as_of) FROM backtest_snapshot WHERE run_id = {run_id}") >= 10
    assert scalar(engine, f"SELECT status FROM backtest_run WHERE id = {run_id}") == "ok"
    rep = scalar(engine, f"SELECT report FROM evaluation WHERE run_id = {run_id}")
    assert rep["source"] == "backtest" and "geen behaald resultaat" in rep["label"]
    # Two US stocks are too few to rank, so nothing is graded in this world. Give the rows a score to
    # follow outcomes and the report through.
    from app.evaluation.outcomes import update_outcomes
    from app.evaluation.report import build_report

    with engine.begin() as conn:
        conn.execute(text(f"UPDATE backtest_snapshot SET status = 'graded', score = 40 + asset_id * 5, letter = 'C' "
                          f"WHERE run_id = {run_id}"))
    with sf() as session:
        assert update_outcomes(session, settings, "backtest", run_id, version_id, TODAY) > 0
        session.commit()
        rep = build_report(session, settings, model, "backtest", run_id, version_id)
    cov = rep["templates"]["stock_general"]["coverage"]
    assert cov["months"] >= 10 and cov["assets"] >= 1                 # months and assets per template
    one = rep["templates"]["stock_general"]["horizons"]["1"]
    assert one["letters"]["per_letter"]["C"]["n"] >= 10 and one["newey_west_lags"] == 0
    assert set(rep["templates"]["stock_general"]["horizons"]) >= {"1", "3", "6"}

    live = evaluate_live(sf, settings, model, version_id, today=TODAY)
    assert live.errors == []
    live_rep = scalar(engine, "SELECT report FROM evaluation WHERE source = 'live'")
    assert live_rep["source"] == "live" and live_rep["templates"] == {}   # no live month-ends yet
    assert scalar(engine, "SELECT count(*) FROM outcome WHERE source = 'live'") == 0


def test_approved_calibration_becomes_a_new_model_version(db, model_copy, settings):  # noqa: F811
    from app.modelconfig import load_model_config
    from app.registry import register_model_version

    engine, sf = db
    config = load_model_config(model_copy)
    with sf() as session:
        version_id = register_model_version(session, config).id
    with engine.begin() as conn:
        pid = conn.execute(text(
            """INSERT INTO model_proposal (kind, model_version_id, summary_nl, payload, evidence)
               VALUES ('letter_scale', :v, 'test', :p, '{}') RETURNING id"""),
            {"v": version_id, "p": '{"etf": {"A": 58, "B": 54, "C": 46, "D": 42, "F": 0}}'}).scalar()
    with pytest.raises(ValueError, match="niet goedgekeurd"):
        apply_proposal(sf, model_copy, config, pid)
    with sf() as session:
        assert decide(session, pid, True)["status"] == "approved"
        with pytest.raises(ValueError):
            decide(session, pid, False)                              # a decision is final
    version = apply_proposal(sf, model_copy, config, pid)
    new = load_model_config(model_copy)                               # lock check passes
    assert new.version == version == next_version(config.version)
    assert new.letter_scale_for("etf") == {"A": 58, "B": 54, "C": 46, "D": 42, "F": 0}
    assert new.letter_scale_for("bond") == config.settings.letter_scale
    with pytest.raises(ValueError, match="al in modelversie"):
        apply_proposal(sf, model_copy, new, pid)
    shutil.rmtree(model_copy)
