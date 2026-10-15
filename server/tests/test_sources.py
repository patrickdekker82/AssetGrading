"""The free sources added after the build: US Treasury curve, Shiller CAPE, SEC Form 4 insiders, Marketaux news,
and the Yahoo switch and pause."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pytest

from app.grading.crypto_inputs import Metrics
from app.grading.insiders import insider_buyers
from app.grading.markets import MarketData, curve_points, curve_position, known_daily, shiller_valuation, yield_at
from app.ingest.insiders import quarter_end, quarter_of, quarters
from app.providers.base import (
    MemoryRecorder,
    ProviderDisabled,
    ProviderError,
    ProviderPaused,
    ProviderSettings,
    RateLimit,
)
from app.providers.marketaux import MarketauxProvider
from app.providers.sec_insider import parse_form4
from app.providers.shiller import LINK, parse_rows
from app.providers.treasury import TreasuryProvider

FAST = RateLimit(calls=1000, per_seconds=1)


def provider(cls, handler, **settings):
    s = ProviderSettings(name=cls.name, base_url="https://example.org", rate_limit=FAST, **settings)
    return cls(s, MemoryRecorder(), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda x: None)


# --- US Treasury curve and the bond metric ---------------------------------------------------------

def test_treasury_csv_becomes_one_series_per_maturity():
    csv = ('Date,"1 Mo","3 Mo","1 Yr","10 Yr","30 Yr"\n10/14/2026,4.11,4.28,4.53,5.19,\n'
           "10/13/2026,4.10,4.26,4.48,5.21,5.56\n")
    p = provider(TreasuryProvider, lambda r: httpx.Response(200, text=csv))
    curve = p.year_curve(2026)
    assert [v for _, v, _ in curve["UST_10Y"]] == [5.19, 5.21]
    assert [d for d, _, _ in curve["UST_30Y"]] == [date(2026, 10, 13)]   # an empty cell is no value
    assert "UST_1M" not in curve                                         # short-lived maturities are skipped


def test_curve_position_rewards_a_steep_curve_and_punishes_an_inverted_one():
    steep = [(0.25, 1.0), (2, 2.0), (5, 3.0), (10, 4.0), (30, 4.5)]
    flat = [(0.25, 3.0), (2, 3.0), (5, 3.0), (10, 3.0), (30, 3.0)]
    inverted = [(0.25, 5.0), (2, 4.5), (5, 4.0), (10, 3.8), (30, 3.7)]
    assert yield_at(steep, 7.5) == pytest.approx(3.5)
    assert curve_position(flat, 7) == pytest.approx(0)
    assert curve_position(steep, 7) > 0 > curve_position(inverted, 7)
    # At 7 years the yield is 3.4: carry 2.4 over cash (1.0) plus roll-down 7 * (3.4 - 3.2) = 1.4, per year.
    assert curve_position(steep, 7) == pytest.approx((2.4 + 1.4) / 7)


def _market(macro: dict[str, pd.Series], as_of: date) -> MarketData:
    return MarketData(as_of, datetime.now(UTC), [], {}, {}, {}, {}, macro, {}, {})


def test_curve_points_need_fresh_data_and_a_short_end():
    day = date(2026, 10, 14)
    fresh = {sid: pd.Series([3.0], index=[day]) for sid in ("UST_3M", "UST_2Y", "UST_5Y", "UST_10Y")}
    assert len(curve_points(_market(fresh, day), "USD")) == 4
    assert curve_points(_market(fresh, day + timedelta(days=30)), "USD") is None     # stale
    no_short = {k: v for k, v in fresh.items() if k != "UST_3M"}
    assert curve_points(_market(no_short, day), "USD") is None
    assert curve_points(_market(fresh, day), "GBP") is None


# --- Shiller CAPE ---------------------------------------------------------------------------------

def test_shiller_columns_are_found_by_header_and_months_read_right():
    header = [[""] * 18 for _ in range(8)]
    header[6][12], header[7][12] = "P/E10 or", "CAPE"
    header[6][14], header[7][14] = "TR P/E10 or", "TR CAPE"
    header[5][16], header[6][16], header[7][16] = "Excess", "CAPE", "Yield"
    data = [[2024.01] + [0.0] * 11 + [32.0, "", 34.0, "", 0.0186, 0, 0],
            [2024.1] + [0.0] * 11 + [35.4, "", 38.1, "", 0.0139, 0, 0],
            [1871.01] + [0.0] * 11 + ["NA", "", "NA", "", "", 0, 0]]
    rows = parse_rows(header + data)
    assert rows[0] == (date(2024, 1, 31), 32.0, 0.0186)
    assert rows[1] == (date(2024, 10, 31), 35.4, 0.0139)              # 2024.1 is October, not January
    assert rows[2] == (date(1871, 1, 31), None, None)


def test_shiller_link_is_read_from_the_page():
    page = '<a href="https://img1.wsimg.com/blobby/go/abc/downloads/ie_data.xls?ver=1760000000">Download</a>'
    assert LINK.search(page).group(0).endswith("ie_data.xls?ver=1760000000")


def test_cape_counts_from_a_month_after_the_month_and_against_own_history():
    months = pd.date_range("2020-01-31", "2026-08-31", freq="ME").date
    cape = pd.Series([20.0 + i * 0.1 for i in range(len(months))], index=months)
    as_of = date(2026, 10, 14)
    daily = known_daily(cape, as_of)
    # August counts from 1 October (a month after the month); on 30 September July is the latest known.
    assert daily.index[-1] <= as_of and daily.loc[date(2026, 9, 30)] == cape.loc[date(2026, 7, 31)]
    assert daily.loc[date(2026, 10, 1)] == cape.loc[date(2026, 8, 31)]
    m = Metrics()
    shiller_valuation(m, _market({"SHILLER_CAPE": cape, "SHILLER_ECY": cape / 1000}, as_of))
    assert m.values["cape_vs_history"] == cape.iloc[-1] and "08-2026" in m.provenance["cape_vs_history"]
    assert len(m.history["cape_vs_history"]) > 180
    stale = Metrics()
    shiller_valuation(stale, _market({"SHILLER_CAPE": cape}, as_of + timedelta(days=200)))
    assert "cape_vs_history" not in stale.values and any("te oud" in n for n in stale.notes)


# --- SEC Form 4 -----------------------------------------------------------------------------------

def test_quarters_and_their_ends():
    assert quarter_of(date(2024, 2, 1)) == "2024q1" and quarter_end("2024q4") == date(2024, 12, 31)
    assert quarters(date(2025, 11, 1), date(2026, 7, 1)) == ["2025q4", "2026q1", "2026q2"]


def _buys(rows):
    return pd.DataFrame(rows, columns=["owner_cik", "is_director", "is_officer", "plan_10b5_1", "first_trade",
                                       "last_trade", "purchase_value"])


def test_insider_buyers_skip_plans_routine_buyers_and_old_trades():
    as_of = date(2026, 10, 1)
    rows = [("1", True, False, False, date(2026, 8, 1), date(2026, 8, 1), 1e5),     # counts
            ("2", False, True, True, date(2026, 9, 1), date(2026, 9, 1), 1e5),       # 10b5-1 plan
            ("3", False, False, False, date(2026, 9, 1), date(2026, 9, 1), 1e6),     # 10% owner, no officer
            ("4", True, False, None, date(2025, 1, 5), date(2025, 1, 5), 1e5)]       # outside six months
    # Routine: owner 5 bought every March for three years before, and again this March.
    rows += [("5", True, False, None, date(y, 3, 10), date(y, 3, 10), 1e4) for y in (2023, 2024, 2025)]
    assert insider_buyers(_buys(rows), as_of) == 1
    rows.append(("5", True, False, None, date(2026, 6, 10), date(2026, 6, 10), 1e4))  # a June buy is not routine
    assert insider_buyers(_buys(rows), as_of) == 2
    assert insider_buyers(None, as_of) == 0


def test_form4_keeps_open_market_trades_only():
    xml = """<ownershipDocument><documentType>4</documentType><issuer><issuerCik>0000320193</issuerCik></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerCik>0001</rptOwnerCik><rptOwnerName>A</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>true</isDirector></reportingOwnerRelationship></reportingOwner>
    <nonDerivativeTable>
    <nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding><transactionAmounts>
      <transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>5</value>
      </transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts></nonDerivativeTransaction>
    <nonDerivativeTransaction><transactionDate><value>2026-10-02</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding><transactionAmounts>
      <transactionShares><value>1000</value></transactionShares>
      <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts></nonDerivativeTransaction>
    </nonDerivativeTable></ownershipDocument>"""
    [row] = parse_form4(xml, "acc", datetime(2026, 10, 3, tzinfo=UTC))
    assert (row.issuer_cik, row.owner_cik, row.is_director, row.plan_10b5_1) == (320193, "1", True, None)
    assert (row.purchase_shares, row.purchase_value, row.first_trade) == (10, 50, date(2026, 10, 1))  # grant left out


# --- Marketaux ------------------------------------------------------------------------------------

def test_marketaux_reads_articles_with_the_company_sentiment_and_hides_the_key():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r.url)
        page = int(r.url.params["page"])
        data = [{"uuid": f"u{page}{i}", "title": f"T{page}{i}", "description": "d", "url": "https://x",
                 "source": "reuters.com", "published_at": "2026-06-01T10:00:00.000000Z",
                 "entities": [{"symbol": "AAPL", "sentiment_score": -0.4}]} for i in range(3 if page == 1 else 1)]
        return httpx.Response(200, json={"meta": {"returned": len(data), "limit": 3}, "data": data})

    p = provider(MarketauxProvider, handler, api_key_env="MARKETAUX_API_KEY")
    p.api_key = "secret"
    rows = p.news("AAPL", date(2026, 5, 1), date(2026, 7, 1), pages=4)
    assert len(rows) == 4 and len(seen) == 2                         # stops at the last, partial page
    assert rows[0]["sentiment"] == -0.4 and rows[0]["published_at"].tzinfo is not None
    assert all(c["params"] is None or "api_token" not in c["params"] for c in p.recorder.calls)
    with pytest.raises(ProviderError):
        provider(MarketauxProvider, handler).news("AAPL", date(2026, 5, 1), date(2026, 7, 1), 1)


def test_miss_analysis_gets_the_news_in_its_input():
    from app.learning.misses import miss_input

    m = {"name": "Aaa", "as_of": date(2026, 1, 31), "template_id": "stock_general", "letter": "A", "score": 80,
         "result": {"pillars": []}, "total_return": -0.2, "excess_return": -0.35, "benchmark": "sp500",
         "max_drawdown": -0.4}
    news = [{"datum": "2026-02-10", "titel": "Recall", "samenvatting": "s", "bron": "x"}]
    assert miss_input(m, 6, news)["nieuws"] == news and miss_input(m, 6)["nieuws"] is None


# --- Yahoo: switch and pause ----------------------------------------------------------------------

def test_a_switched_off_provider_makes_no_call():
    calls = []
    p = provider(TreasuryProvider, lambda r: calls.append(r) or httpx.Response(200, text=""), enabled=False)
    with pytest.raises(ProviderDisabled):
        p.year_curve(2026)
    assert calls == []


def test_repeated_refusals_pause_the_provider():
    calls = []

    def refuse(r):
        calls.append(r)
        return httpx.Response(403, text="blocked")

    p = provider(TreasuryProvider, refuse)
    for _ in range(p.refusals_before_pause):
        with pytest.raises(ProviderError):
            p.year_curve(2026)
    n = len(calls)
    with pytest.raises(ProviderPaused):
        p.year_curve(2026)
    assert len(calls) == n                                            # no new request while paused


def test_report_notes_a_switched_off_source_and_errors_a_paused_one_once():
    from app.ingest.report import Report

    r = Report()
    r.unavailable(ProviderDisabled("yahoo staat uit"), "koersen")
    r.unavailable(ProviderPaused("yahoo gepauzeerd"), "koersen")
    r.unavailable(ProviderPaused("yahoo gepauzeerd"), "koersen")
    assert r.errors == ["koersen: yahoo gepauzeerd"] and r.notes == ["koersen: yahoo staat uit"]
