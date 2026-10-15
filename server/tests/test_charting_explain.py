"""Chart indicators and the template explanation, with fixed inputs."""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.charting.indicators import aggregate_ohlc, daily_indicators, sample, to_points
from app.grading.engine import GradeInput, MetricInput, grade
from app.grading.explain import explain
from app.modelconfig import load_model_config
from app.settings import REPO_ROOT

CONFIG = load_model_config(REPO_ROOT / "config" / "model")
START = date(2024, 1, 1)  # a Monday


def ohlc(n: int) -> pd.DataFrame:
    idx = [START + timedelta(days=i) for i in range(n)]
    close = pd.Series(np.arange(1, n + 1, dtype=float), index=idx)
    return pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0})


def test_weekly_candles_follow_iso_weeks():
    weekly = aggregate_ohlc(ohlc(14), "1w")
    assert list(weekly.index) == [date(2024, 1, 7), date(2024, 1, 14)]
    first = weekly.iloc[0]
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (0.5, 8, 0, 7, 7)


def test_monthly_sampling_takes_the_last_value():
    s = pd.Series(range(60), index=[START + timedelta(days=i) for i in range(60)], dtype=float)
    m = sample(s, "1M")
    assert list(m.index) == [date(2024, 1, 31), date(2024, 2, 29)]
    assert list(m) == [30, 59]


def test_daily_indicators_match_their_definitions():
    data = ohlc(300)
    ind = daily_indicators(data, benchmark=data["close"] * 2, funding=None, open_interest=None)
    assert ind["sma50"].iloc[-1] == pytest.approx(np.mean(np.arange(251, 301)))
    assert ind["mayer_multiple"].iloc[-1] == pytest.approx(300 / np.mean(np.arange(101, 301)))
    assert ind["rs_btc"].iloc[-1] == pytest.approx(0.5)
    assert "sma200w" not in ind  # needs 1,400 days
    assert ind["rsi14w"].iloc[-1] == pytest.approx(100)  # only rising weeks


def test_points_skip_missing_values():
    s = pd.Series([1.0, float("nan"), 3.0], index=[START, START + timedelta(1), START + timedelta(2)])
    assert to_points(s) == [{"time": "2024-01-01", "value": 1.0}, {"time": "2024-01-03", "value": 3.0}]


# --- explanation --------------------------------------------------------------------------------

def _graded_result():
    t = CONFIG.templates["crypto_platform"]
    metrics = {}
    for i, p in enumerate(t.pillars):
        for j, m in enumerate(p.metrics):
            direct = CONFIG.metrics[m.id].scoring == "direct"
            pct = 30 + (i * 7 + j * 5) % 60
            metrics[m.id] = MetricInput(value=pct if direct else 1.0, peer_pct=None if direct else pct)
    inp = GradeInput(template_id="crypto_platform", tags=[], metrics=metrics, flags={"not_on_mica_venue": False})
    return grade(inp, CONFIG).to_dict()


LABELS = {k: k for k in CONFIG.metrics}


def test_explanation_length_is_120_to_200_words():
    text = explain("Testmunt", _graded_result(), CONFIG, LABELS)
    assert 120 <= len(text.split()) <= 200, text


def test_explanation_numbers_all_come_from_the_result():
    result = _graded_result()
    text = explain("Testmunt", result, CONFIG, LABELS)
    allowed = {f"{v:.0f}" for v in (result["score"], result["quality"], result["timing"])}
    allowed |= {f"{p['score']:.0f}" for p in result["pillars"] if p["score"] is not None}
    allowed |= {f"{m['score']:.0f}" for p in result["pillars"] for m in p["metrics"] if m["score"] is not None}
    allowed |= {str(int(result["coverage"] * 100)), "0", "100", "20", "2", "10", "90", "1", "21"}
    from app.grading.letters import bands
    allowed |= {f"{max(lo - 2, 0):.0f}" for lo, _ in bands(CONFIG.settings.letter_scale).values()}
    allowed |= {f"{min(hi + 2, 100):.0f}" for _, hi in bands(CONFIG.settings.letter_scale).values()}
    found = set(re.findall(r"(?<![A-Za-z_\d])\d+(?:[.,]\d+)?", text))
    assert found <= allowed, found - allowed


def test_explanation_mentions_strengths_weaknesses_and_what_changes():
    text = explain("Testmunt", _graded_result(), CONFIG, LABELS)
    assert "Sterkste punten" in text and "Zwakste punten" in text and "Wat de grade zou veranderen" in text


def test_explanation_for_stablecoin_and_no_grade():
    peg = grade(GradeInput(template_id="crypto_stablecoin", tags=[], metrics={
        "peg_deviation": MetricInput(value=0.0), "mica_status": MetricInput(value=1)}), CONFIG).to_dict()
    assert "pegveiligheid van 1" in explain("USDX", peg, CONFIG, LABELS)
    empty = grade(GradeInput(template_id="crypto_utility", tags=[], metrics={}), CONFIG).to_dict()
    text = explain("Leeg", empty, CONFIG, LABELS)
    assert "geen grade" in text and "handmatig" in text


def test_fx_indicators_include_trend_strength_cloud_and_rate_difference():
    from app.charting.indicators import FX_INDICATORS, fx_indicators

    data = ohlc(300)
    rates = pd.Series([1.5, 2.0], index=[START, START + timedelta(days=200)])
    ind = fx_indicators(data, None, rate_diff=rates)
    assert {"adx14", "atr14_pct", "ichimoku_tenkan", "ichimoku_kijun", "ichimoku_span_a", "ichimoku_span_b",
            "rate_diff"} <= set(ind) <= {i.id for i in FX_INDICATORS} | {"cftc_index"}
    # A steady rise of 1 a day: the 9-day midpoint lags the price by 4, the 26-day one by 12.5.
    assert ind["ichimoku_tenkan"].iloc[-1] == pytest.approx(296)
    assert ind["ichimoku_kijun"].iloc[-1] == pytest.approx(287.5)
    assert ind["adx14"].iloc[-1] > 90  # one-way trend
    assert ind["rate_diff"].iloc[-1] == 2.0 and ind["rate_diff"].iloc[150] == 1.5


def test_bond_indicators_show_trend_drawdown_and_curves():
    from app.charting.indicators import BOND_DEFAULT_ON, BOND_INDICATORS, bond_indicators

    data = ohlc(400)
    curve = pd.Series([0.4, -0.2], index=[START - timedelta(days=30), START + timedelta(days=10)])
    ind = bond_indicators(data, {"curve_us_2_10": curve, "curve_ea_2_10": None})
    assert set(ind) == {"sma200", "sma10m", "drawdown", "curve_us_2_10"}
    assert list(ind["curve_us_2_10"]) == [-0.2]  # only from the first price on
    assert ind["drawdown"].max() == 0
    assert BOND_DEFAULT_ON <= {i.id for i in BOND_INDICATORS}


def test_forbidden_words_come_from_the_model_configuration():
    from app.ai.numbers import check_text

    payload = {"letter": "B"}
    assert check_text("Een mooi beeld.", payload, forbidden=["advies"]) == []
    assert any("advies" in p or "verboden" in p for p in check_text("Dit is adviesmatig.", payload,
                                                                      forbidden=["advies"]))
    assert check_text("U moet nu kopen.", payload, forbidden=CONFIG.settings.forbidden_words_nl)
