"""Technical score (chapter 7) and template assignment, with fixed inputs and outcomes."""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.grading.assign import assign_crypto, crypto_tags
from app.grading.technical import TechRaw, tech_raw, tech_scores
from app.modelconfig import load_model_config
from app.settings import REPO_ROOT

CONFIG = load_model_config(REPO_ROOT / "config" / "model")
P = CONFIG.technical.params["crypto"]
BLOCKS = CONFIG.technical.blocks
END = date(2026, 10, 10)


def series(values) -> pd.Series:
    values = list(values)
    days = [END - timedelta(days=len(values) - 1 - i) for i in range(len(values))]
    return pd.Series(values, index=days, dtype=float)


def growth(days: int, daily: float, start: float = 100.0) -> pd.Series:
    return series(start * (1 + daily) ** i for i in range(days))


def test_steady_uptrend_passes_all_trend_tests():
    raw = tech_raw(growth(1500, 0.001), None, P, END)
    assert raw.trend_tests == {"price_above_sma200": True, "sma50_above_sma200": True, "sma200_rising": True,
                               "price_above_sma_10m": True}
    assert raw.trend_state == 100
    assert raw.distance_to_high == pytest.approx(1.0)


def test_steady_downtrend_fails_all_trend_tests():
    raw = tech_raw(growth(1500, -0.001), None, P, END)
    assert raw.trend_state == 0
    assert raw.distance_to_high == pytest.approx((1 - 0.001) ** 363)


def test_momentum_is_return_divided_by_volatility():
    rng = np.random.default_rng(1)
    closes = series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 1500))))
    raw = tech_raw(closes, None, P, END)
    start, skip = closes.loc[:END - timedelta(days=365)].iloc[-1], closes.loc[:END - timedelta(days=30)].iloc[-1]
    window = closes.loc[END - timedelta(days=364):END]
    vol = np.log(window).diff().dropna().std(ddof=1) * math.sqrt(365)
    assert raw.momentum_long == pytest.approx((skip / start - 1) / vol)


def test_relative_strength_against_benchmark():
    asset, bench = growth(1500, 0.002), growth(1500, 0.001)
    raw = tech_raw(asset, bench, P, END)
    expected = np.mean([(1.002 ** w - 1) - (1.001 ** w - 1) for w in P.relative_windows])
    assert raw.relative == pytest.approx(expected)
    assert tech_raw(asset, None, P, END).relative is None


def test_calm_period_scores_high_on_volatility():
    rng = np.random.default_rng(2)
    noisy = rng.normal(0, 0.04, 1400)
    calm = rng.normal(0, 0.005, 100)
    closes = series(100 * np.exp(np.cumsum(np.concatenate([noisy, calm]))))
    assert tech_raw(closes, None, P, END).volatility_score > 90


def test_short_history_leaves_blocks_empty():
    raw = tech_raw(growth(100, 0.001), None, P, END)
    assert raw.trend_tests == {} and raw.momentum_long is None and raw.distance_to_high is None


def test_stale_prices_give_no_technical_inputs():
    old = growth(1500, 0.001)
    raw = tech_raw(old, None, P, END + timedelta(days=10))
    assert raw.note == "geen recente koers" and raw.trend_state is None


def test_scores_combine_blocks_with_weights_and_class_percentiles():
    raws = {
        1: TechRaw(trend_tests={"a": True, "b": True}, momentum_long=2, momentum_short=2, distance_to_high=1.0,
                   relative=0.5, volatility_score=80),
        2: TechRaw(trend_tests={"a": False, "b": False}, momentum_long=-1, momentum_short=-1, distance_to_high=0.5,
                   relative=-0.5, volatility_score=20),
    }
    out = tech_scores(raws, BLOCKS, P)
    # Asset 1: trend 100, momentum 75, distance 75, relative 75, volatility 80.
    assert out[1].score == pytest.approx((35 * 100 + 25 * 75 + 15 * 75 + 15 * 75 + 10 * 80) / 100)
    assert out[2].score == pytest.approx((35 * 0 + 25 * 25 + 15 * 25 + 15 * 25 + 10 * 20) / 100)
    assert out[1].coverage == 1


def test_score_missing_below_half_the_block_weight():
    out = tech_scores({1: TechRaw(volatility_score=50, distance_to_high=0.9)}, BLOCKS, P)
    assert out[1].coverage == pytest.approx(0.25) and out[1].score is None


# --- template assignment ------------------------------------------------------------------------

@pytest.mark.parametrize(("gecko_id", "categories", "template"), [
    ("bitcoin", ["Layer 1 (L1)"], "crypto_bitcoin"),
    ("tether", ["Stablecoins", "Fiat-backed Stablecoin"], "crypto_stablecoin"),
    ("pax-gold", ["Tokenized Gold", "Real World Assets (RWA)"], "crypto_rwa"),
    ("stellar", ["Layer 1 (L1)", "Real World Assets (RWA)"], "crypto_platform"),  # RWA chain, not an RWA token
    ("dogecoin", ["Smart Contract Platform", "Meme"], "crypto_memecoin"),
    ("hyperliquid", ["Layer 1 (L1)", "Decentralized Exchange (DEX)"], "crypto_defi"),
    ("pump-fun", ["Meme", "Launchpad"], "crypto_defi"),  # configured override
    ("ethereum", ["Smart Contract Platform", "Layer 1 (L1)"], "crypto_platform"),
    ("leo-token", ["Exchange-based Tokens"], "crypto_utility"),
    ("whatever", None, "crypto_utility"),
])
def test_crypto_template_assignment(gecko_id, categories, template):
    assert assign_crypto(gecko_id, categories, None, CONFIG.assignment) == template


def test_manual_override_wins():
    assert assign_crypto("dogecoin", ["Meme"], "crypto_utility", CONFIG.assignment) == "crypto_utility"


def test_tags_from_categories_and_aliases():
    assert crypto_tags(["Layer 2 (L2)"], ["contract:solana"], CONFIG.assignment) == ["l2", "solana"]
    assert crypto_tags(["Layer 1 (L1)"], ["contract:ethereum"], CONFIG.assignment) == []
