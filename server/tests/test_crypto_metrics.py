"""Crypto metric derivations with fixed inputs (no database)."""

import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.grading.crypto_inputs import STABLECOIN_SERIES, AssetRow, CryptoData, compute_metrics

D = date(2026, 10, 10)


def days(n: int, end: date = D) -> list[date]:
    return [end - timedelta(days=n - 1 - i) for i in range(n)]


def facts(rows: list[tuple[str, str, date, float]], asset_id: int = 1) -> pd.DataFrame:
    return pd.DataFrame([{"asset_id": asset_id, "field": f, "source": s, "as_of": d, "value": v}
                         for f, s, d, v in rows])


COLUMNS = ["asset_id", "field", "source", "as_of", "value"]


def make_data(fact_rows, closes=None, volume=None, macro=None, usd_per_eur=1.25) -> CryptoData:
    fx = pd.Series([usd_per_eur] * 800, index=days(800))
    return CryptoData(
        as_of=D, knowledge=datetime(2026, 10, 11, tzinfo=UTC),
        assets=[], closes={1: closes} if closes is not None else {},
        coinbase_volume_eur={1: volume} if volume is not None else {},
        facts=facts(fact_rows) if fact_rows else pd.DataFrame(columns=COLUMNS),
        usd_per_eur=fx, macro=macro or {},
    )


ASSET = AssetRow(id=1, coingecko_id="x", symbol="X", name="X", categories=[], template_override=None, alias_kinds=[])


def test_market_cap_ratios_and_fees():
    rows = [("market_cap_eur", "coingecko", D, 1000.0), ("fdv_eur", "coingecko", D, 4000.0)]
    rows += [("fees_usd", "defillama", d, 1.0) for d in days(30)]
    rows += [("revenue_usd", "defillama", d, 0.5) for d in days(30)]
    rows += [("holders_revenue_usd", "defillama", d, 0.1) for d in days(30)]
    rows += [("cm_AdrActCnt", "coinmetrics", d, 50.0) for d in days(30)]
    m = compute_metrics(make_data(rows), ASSET, "crypto_defi", {})
    eur = 1 / 1.25
    assert m.values["mcap_to_fdv"] == pytest.approx(0.25)
    assert m.values["protocol_fees"] == pytest.approx(30 * 365 / 30 * eur)
    assert m.values["protocol_revenue"] == pytest.approx(15 * 365 / 30 * eur)
    assert m.values["holder_payout"] == pytest.approx(0.2)
    assert m.values["active_addresses"] == 50
    assert m.values["mcap_to_active_addresses"] == pytest.approx(20)
    assert m.values["mcap_to_fees"] == pytest.approx(1000 / (365 * eur))
    assert "defillama" in m.provenance["protocol_fees"]


def test_stale_market_cap_is_not_used():
    rows = [("market_cap_eur", "coingecko", D - timedelta(days=10), 1000.0), ("fdv_eur", "coingecko", D, 4000.0)]
    m = compute_metrics(make_data(rows), ASSET, "crypto_platform", {})
    assert "mcap_to_fdv" not in m.values


def test_too_few_fee_days_leave_fees_empty():
    rows = [("fees_usd", "defillama", d, 1.0) for d in days(10)]
    assert "protocol_fees" not in compute_metrics(make_data(rows), ASSET, "crypto_defi", {}).values


def test_net_inflation_from_supply_a_year_apart():
    rows = [("cm_SplyCur", "coinmetrics", d, 100.0 + i * 0.01) for i, d in enumerate(days(400))]
    m = compute_metrics(make_data(rows), ASSET, "crypto_platform", {})
    now, then = 100 + 399 * 0.01, 100 + (399 - 365) * 0.01
    assert m.values["net_inflation"] == pytest.approx(now / then - 1)


def test_liquidity_metrics():
    vol = pd.Series([1000.0] * 30, index=days(30))
    rows = [("bitvavo_volume_24h_eur", "derived", D, 500.0), ("orderbook_depth_2pct_usd", "coinbase", D, 125.0),
            ("bid_ask_spread", "coinbase", D, 0.001), ("flag_not_on_mica_venue", "derived", D, 0.0)]
    m = compute_metrics(make_data(rows, volume=vol), ASSET, "crypto_platform", {})
    assert m.values["regulated_volume"] == 1500
    assert m.values["orderbook_depth_2pct"] == pytest.approx(100)
    assert m.values["bid_ask_spread"] == 0.001
    assert m.flags["not_on_mica_venue"] is False


def test_derivatives_metrics_use_one_venue():
    rows = [("market_cap_eur", "coingecko", D, 1000.0)]
    rows += [("funding_rate_daily", "okx", d, 0.0001) for d in days(30)]
    rows += [("open_interest_usd", "okx", D, 250.0)]
    m = compute_metrics(make_data(rows), ASSET, "crypto_platform", {})
    assert m.values["funding_rate"] == pytest.approx(0.0001)
    assert m.values["open_interest_to_mcap"] == pytest.approx(250 / 1.25 / 1000)


def test_bitcoin_onchain_metrics():
    n = 900
    mc = [1000.0 + 10 * i for i in range(n)]
    mvrv = [1.5] * n
    rows = [("cm_CapMrktCurUSD", "coinmetrics", d, v) for d, v in zip(days(n), mc, strict=True)]
    rows += [("cm_CapMVRVCur", "coinmetrics", d, v) for d, v in zip(days(n), mvrv, strict=True)]
    rows += [("cm_IssTotUSD", "coinmetrics", d, 10.0 if i < n - 1 else 20.0) for i, d in enumerate(days(n))]
    macro = {"DFII10": pd.Series([1.5, 1.6], index=[D - timedelta(days=1), D]),
             STABLECOIN_SERIES: pd.Series([100.0 + i for i in range(500)], index=days(500))}
    m = compute_metrics(make_data(rows, macro=macro), ASSET, "crypto_bitcoin", {})
    last_mc = mc[-1]
    std = pd.Series(mc).std(ddof=1)
    assert m.values["mvrv_z"] == pytest.approx((last_mc - last_mc / 1.5) / std)
    assert m.values["nupl"] == pytest.approx(1 - 1 / 1.5)
    assert m.values["price_to_realized"] == pytest.approx(1.5)
    assert m.values["puell_multiple"] == pytest.approx(20 / ((364 * 10 + 20) / 365))
    assert m.values["real_rate"] == pytest.approx(0.016)   # FRED gives percent; the metric is a ratio
    assert m.values["stablecoin_supply_growth"] == pytest.approx(599 / 569 - 1)
    assert len(m.history["mvrv_z"]) > 0


def test_stablecoin_peg_deviation_in_usd():
    usd_closes = [1.0, 1.002, 0.998, 1.0] * 25
    closes = pd.Series([v / 1.25 for v in usd_closes], index=days(100))  # stored in euro
    asset = AssetRow(1, "usdx", "USDX", "USDX", ["Stablecoins", "MiCA-Compliant Stablecoin"], None, [])
    m = compute_metrics(make_data([], closes=closes), asset, "crypto_stablecoin", {})
    assert m.values["peg_deviation"] == pytest.approx(0.001)
    assert m.values["mica_status"] == 1.0
    assert m.raw["peg_max_deviation"] == pytest.approx(0.002)


def test_memecoin_flags_from_rugcheck():
    rows = [("mint_authority_active", "rugcheck", D, 0.0), ("freeze_authority_active", "rugcheck", D, 1.0),
            ("lp_locked_pct", "rugcheck", D, 30.0), ("holders_top10_pct", "rugcheck", D, 12.0),
            ("dex_liquidity_usd", "dexscreener", D, 125.0)]
    m = compute_metrics(make_data(rows), ASSET, "crypto_memecoin", {"lp_locked_min_pct": 50})
    assert m.flags == {"not_on_mica_venue": None, "mint_authority_active": False, "freeze_authority_active": True,
                       "liquidity_not_locked": True}
    assert m.values["holders_top10"] == pytest.approx(0.12)
    assert m.values["dex_liquidity"] == pytest.approx(100)


def test_manual_facts_fill_gaps_and_set_flags():
    rows = [("unlock_90d", "manual", D - timedelta(days=200), 0.05), ("flag_unresolved_exploit", "manual", D, 1.0)]
    m = compute_metrics(make_data(rows), ASSET, "crypto_platform", {})
    assert m.values["unlock_90d"] == 0.05 and "handmatig" in m.provenance["unlock_90d"]
    assert m.flags["unresolved_exploit"] is True


def test_attention_is_log_of_watchlists():
    m = compute_metrics(make_data([("watchlist_users", "coingecko", D, 999.0)]), ASSET, "crypto_platform", {})
    assert m.values["attention_score"] == pytest.approx(math.log10(1000))
