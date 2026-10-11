from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.providers.base import (
    BudgetExceeded,
    MemoryRecorder,
    Provider,
    ProviderError,
    ProviderSettings,
    RateLimit,
    RateLimiter,
)
from app.providers.binance import BinanceProvider
from app.providers.coinbase import CoinbaseProvider
from app.providers.coingecko import CoinGeckoProvider
from app.providers.coinmetrics import CoinMetricsProvider
from app.providers.defillama import DefiLlamaProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.fred import FredProvider

TODAY = datetime.now(UTC).date()


def settings(name="test", budget=None):
    return ProviderSettings(name=name, base_url="https://example.test", rate_limit=RateLimit(1000, 1),
                            monthly_budget=budget)


def make(cls, handler, *, budget=None, api_key=None, recorder=None):
    recorder = recorder or MemoryRecorder()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return cls(settings(cls.name, budget), recorder, api_key=api_key, client=client, sleep=lambda s: None), recorder


def ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def secs(d: date) -> int:
    return ms(d) // 1000


# --- base ----------------------------------------------------------------------------------------

def test_rate_limiter_waits_when_window_is_full():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(RateLimit(2, 1.0), clock=lambda: now[0], sleep=sleep)
    limiter.acquire()
    limiter.acquire()
    assert slept == []
    limiter.acquire()
    assert len(slept) == 1 and slept[0] == pytest.approx(1.01)


def test_budget_exceeded_stops_before_any_http_call():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    recorder = MemoryRecorder()
    for _ in range(3):
        recorder.record(provider="test", endpoint="/x", params=None, status_code=200, ok=True, error=None, cost=1,
                        body=b"{}", content_type=None, duration_ms=1, started_at=datetime.now(UTC))
    provider, _ = make(Provider, handler, budget=3, recorder=recorder)
    provider.name = "test"
    with pytest.raises(BudgetExceeded):
        provider.get_json("/x")
    assert calls == []


def test_retries_on_429_and_records_every_attempt():
    responses = iter([httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(200, json={"ok": 1})])
    provider, recorder = make(Provider, lambda r: next(responses))
    res = provider.get_json("/x")
    assert res.data == {"ok": 1}
    assert [c["ok"] for c in recorder.calls] == [False, True]
    assert recorder.calls[1]["body"] == b'{"ok":1}'


def test_client_error_is_not_retried():
    provider, recorder = make(Provider, lambda r: httpx.Response(404, text="nope"))
    with pytest.raises(ProviderError, match="404"):
        provider.get_json("/x")
    assert len(recorder.calls) == 1


def test_api_key_is_sent_but_never_logged():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"observations": [{"date": "2026-01-02", "value": "1.5"},
                                                          {"date": "2026-01-03", "value": "."}]})

    fred, recorder = make(FredProvider, handler, api_key="secret123")
    obs = fred.observations("DGS10", date(2026, 1, 1))
    assert seen["api_key"] == "secret123"
    assert "api_key" not in (recorder.calls[0]["params"] or {})
    assert "secret123" not in str(recorder.calls[0])
    # FRED's "." means missing; it is skipped, never filled in.
    assert [(d, v) for d, v, _ in obs] == [(date(2026, 1, 2), 1.5)]


def test_fred_without_key_fails_clearly():
    fred, _ = make(FredProvider, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ProviderError, match="FRED_API_KEY"):
        fred.observations("DGS10", date(2026, 1, 1))


# --- adapters ------------------------------------------------------------------------------------

def test_binance_drops_the_unfinished_day():
    yesterday, today = TODAY - timedelta(days=1), TODAY

    def handler(request):
        def row(d):
            close_ms = ms(d + timedelta(days=1)) - 1
            return [ms(d), "10", "12", "9", "11", "100", close_ms]
        return httpx.Response(200, json=[row(yesterday), row(today)])

    binance, _ = make(BinanceProvider, handler)
    bars = binance.get_bars("BTCUSDT", yesterday, today)
    assert [b.ts for b in bars] == [yesterday]
    assert bars[0].close == Decimal("11") and bars[0].quote == "USDT" and bars[0].open == Decimal("10")


def test_coinbase_splits_long_ranges_and_skips_today():
    requested = []

    def handler(request):
        start = date.fromisoformat(request.url.params["start"][:10])
        end = date.fromisoformat(request.url.params["end"][:10])
        requested.append((start, end))
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return httpx.Response(200, json=[[secs(d), 1, 3, 2, 2.5, 10] for d in reversed(days)])

    coinbase, _ = make(CoinbaseProvider, handler)
    start = TODAY - timedelta(days=400)
    bars = coinbase.get_bars("BTC-USD", start, TODAY)
    assert len(requested) == 2  # 300-day windows
    assert bars[0].ts == start and bars[-1].ts == TODAY - timedelta(days=1)
    assert len(bars) == 400
    assert bars[0].quote == "USD" and bars[0].close == Decimal("2.5")


def test_coingecko_daily_points_are_closes_of_the_previous_day():
    def handler(request):
        assert request.headers["x-cg-demo-api-key"] == "CG-key"
        assert int(request.url.params["days"]) <= 365
        d1, d2 = TODAY - timedelta(days=1), TODAY
        live = ms(TODAY) + 5 * 3600 * 1000
        return httpx.Response(200, json={
            "prices": [[ms(d1), 10.0], [ms(d2), 11.0], [live, 12.0]],
            "total_volumes": [[ms(d1), 5.0], [ms(d2), 6.0], [live, 7.0]],
        })

    cg, _ = make(CoinGeckoProvider, handler, api_key="CG-key")
    bars = cg.get_bars("bitcoin", date(2017, 1, 1), TODAY - timedelta(days=1))
    assert [(b.ts, b.close) for b in bars] == [
        (TODAY - timedelta(days=2), Decimal("10.0")), (TODAY - timedelta(days=1), Decimal("11.0"))
    ]
    assert bars[0].quote == "EUR"


def test_coingecko_market_facts_skip_missing_values():
    row = {"market_cap": 100, "fully_diluted_valuation": None, "total_volume": 5,
           "circulating_supply": 10, "total_supply": 20, "max_supply": None}
    facts = CoinGeckoProvider.market_facts(row, TODAY, 7)
    assert {f.field for f in facts} == {"market_cap_eur", "volume_24h_eur", "circulating_supply", "total_supply"}


def test_defillama_keeps_only_completed_days():
    def handler(request):
        return httpx.Response(200, json=[
            {"date": secs(TODAY - timedelta(days=2)), "tvl": 5},
            {"date": secs(TODAY - timedelta(days=1)), "tvl": 6},
            {"date": secs(TODAY) + 3600, "tvl": 7},
        ])

    dl, _ = make(DefiLlamaProvider, handler)
    facts = dl.chain_tvl("Ethereum")
    assert [(f.as_of, f.value) for f in facts] == [
        (TODAY - timedelta(days=2), Decimal("5")), (TODAY - timedelta(days=1), Decimal("6"))
    ]


def test_coinmetrics_follows_pages():
    pages = {
        "first": {"data": [{"asset": "btc", "time": "2026-01-01T00:00:00Z", "CapMVRVCur": "1.5"}],
                  "next_page_url": "https://example.test/next?assets=btc&next_page_token=abc"},
        "next": {"data": [{"asset": "btc", "time": "2026-01-02T00:00:00Z", "CapMVRVCur": "1.6", "AdrActCnt": "9"}]},
    }

    def handler(request):
        if request.url.path == "/next":
            # The pagination link must arrive with its own query string intact.
            assert request.url.params["next_page_token"] == "abc" and request.url.params["assets"] == "btc"
            return httpx.Response(200, json=pages["next"])
        return httpx.Response(200, json=pages["first"])

    cm, recorder = make(CoinMetricsProvider, handler)
    out = cm.timeseries(["btc"], ["CapMVRVCur", "AdrActCnt"], date(2026, 1, 1))
    assert [(f.field, f.as_of, f.value) for f in out["btc"]] == [
        ("cm_CapMVRVCur", date(2026, 1, 1), Decimal("1.5")),
        ("cm_CapMVRVCur", date(2026, 1, 2), Decimal("1.6")),
        ("cm_AdrActCnt", date(2026, 1, 2), Decimal("9")),
    ]
    assert len(recorder.calls) == 2


def test_frankfurter_parses_rates():
    def handler(request):
        assert request.url.path == "/2026-01-01..2026-01-05"
        return httpx.Response(200, json={"rates": {"2026-01-02": {"USD": 1.1}, "2026-01-05": {"USD": 1.2}}})

    fx, _ = make(FrankfurterProvider, handler)
    rows = fx.rates(date(2026, 1, 1), date(2026, 1, 5), "EUR", ["USD"])
    assert [(d, q, r) for d, q, r, _ in rows] == [
        (date(2026, 1, 2), "USD", Decimal("1.1")), (date(2026, 1, 5), "USD", Decimal("1.2"))
    ]


# --- phase 2 adapters ---------------------------------------------------------------------------

from app.providers.derivatives import (  # noqa: E402
    BinanceFuturesProvider,
    BybitProvider,
    OkxProvider,
    daily_mean_funding,
)
from app.providers.venues import (  # noqa: E402
    BitvavoProvider,
    CoinbaseBookProvider,
    DexScreenerProvider,
    RugCheckProvider,
    StablecoinSupplyProvider,
)


def test_daily_mean_funding_skips_the_running_day():
    def at(d, h):
        return datetime(d.year, d.month, d.day, h, tzinfo=UTC)

    y = TODAY - timedelta(days=1)
    events = [(at(y, 0), 0.0001, 1), (at(y, 8), 0.0003, 1), (at(TODAY, 0), 0.01, 2)]
    assert daily_mean_funding(events, before=TODAY) == {y: (pytest.approx(0.0002), 1)}


def test_binance_futures_funding_and_open_interest():
    def handler(request):
        if request.url.path == "/fapi/v1/fundingRate":
            return httpx.Response(200, json=[{"fundingTime": ms(TODAY) - 3_600_000, "fundingRate": "0.0001"}])
        return httpx.Response(200, json=[{"sumOpenInterestValue": "123.5"}])

    p, _ = make(BinanceFuturesProvider, handler)
    assert [r for _, r, _ in p.funding_history("BTC", TODAY - timedelta(days=2))] == [0.0001]
    assert p.open_interest_usd("BTC")[0] == 123.5


def test_bybit_and_okx_parse_their_formats():
    def bybit(request):
        if "funding" in request.url.path:
            return httpx.Response(200, json={"result": {"list": [
                {"fundingRate": "0.0002", "fundingRateTimestamp": str(ms(TODAY) - 1)}]}})
        return httpx.Response(200, json={"result": {"list": [{"openInterestValue": "99.5"}]}})

    p, _ = make(BybitProvider, bybit)
    assert [r for _, r, _ in p.funding_history("ETH", TODAY - timedelta(days=2))] == [0.0002]
    assert p.open_interest_usd("ETH")[0] == 99.5

    def okx(request):
        if "funding" in request.url.path:
            return httpx.Response(200, json={"code": "0", "data": [
                {"fundingTime": str(ms(TODAY) - 1), "fundingRate": "0.0003", "realizedRate": "0.00025"}]})
        if "instruments" in request.url.path:
            return httpx.Response(200, json={"code": "0", "data": [{"instId": "SOL-USDT-SWAP", "state": "live"},
                                                                    {"instId": "SOL-USD-SWAP", "state": "live"}]})
        return httpx.Response(200, json={"code": "0", "data": [{"oiUsd": "77"}]})

    p, _ = make(OkxProvider, okx)
    assert p.perp_bases() == {"SOL"}
    assert [r for _, r, _ in p.funding_history("SOL", TODAY - timedelta(days=2))] == [0.00025]
    assert p.open_interest_usd("SOL")[0] == 77.0


def test_okx_error_code_becomes_provider_error():
    error = {"code": "51001", "msg": "Instrument ID does not exist"}
    p, _ = make(OkxProvider, lambda r: httpx.Response(200, json=error))
    with pytest.raises(ProviderError, match="does not exist") as err:
        p.open_interest_usd("NOPE")
    assert err.value.not_found


def test_order_book_depth_within_two_percent():
    book = {"bids": [["99", "1", 1], ["97", "5", 1]], "asks": [["101", "2", 1], ["104", "5", 1]]}
    p, _ = make(CoinbaseBookProvider, lambda r: httpx.Response(200, json=book))
    data, _ = p.depth("BTC-USD")
    # mid 100: bids >= 98 (99*1) and asks <= 102 (101*2)
    assert data["depth_quote"] == pytest.approx(99 + 202)
    assert data["spread"] == pytest.approx(0.02)


def test_bitvavo_keeps_trading_eur_markets():
    def handler(request):
        if request.url.path == "/v2/markets":
            return httpx.Response(200, json=[{"market": "BTC-EUR", "base": "BTC", "quote": "EUR", "status": "trading"},
                                             {"market": "OLD-EUR", "base": "OLD", "quote": "EUR", "status": "halted"}])
        return httpx.Response(200, json=[{"market": "BTC-EUR", "last": "75000", "volumeQuote": "1000000"},
                                         {"market": "OLD-EUR", "last": "1", "volumeQuote": "5"}])

    p, _ = make(BitvavoProvider, handler)
    listing, _ = p.eur_markets()
    assert listing == {"BTC": {"last": 75000.0, "volume_eur": 1000000.0}}


def test_dexscreener_sums_pair_liquidity():
    pairs = [{"liquidity": {"usd": 100.0}}, {"liquidity": {"usd": 50.5}}, {}]
    p, _ = make(DexScreenerProvider, lambda r: httpx.Response(200, json=pairs))
    assert p.liquidity_usd("solana", "Mint")[0] == 150.5


def test_rugcheck_excludes_pools_from_holder_concentration():
    report = {
        "mintAuthority": None, "freezeAuthority": "Auth",
        "knownAccounts": {"PoolAddr": {"name": "Pool", "type": "AMM"}},
        "topHolders": [{"address": "PoolAddr", "owner": "x", "pct": 40}, {"address": "A", "owner": "a", "pct": 6},
                       {"address": "B", "owner": "b", "pct": 4}],
        "markets": [{"lp": {"lpLockedPct": 100, "quoteUSD": 300, "baseUSD": 100}},
                    {"lp": {"lpLockedPct": 0, "quoteUSD": 50, "baseUSD": 50}}],
    }
    p, _ = make(RugCheckProvider, lambda r: httpx.Response(200, json=report))
    facts, _ = p.report("Mint")
    assert facts["mint_authority_active"] == 0 and facts["freeze_authority_active"] == 1
    assert facts["holders_top10_pct"] == 10
    assert facts["lp_locked_pct"] == pytest.approx(80)


def test_stablecoin_supply_sums_all_pegs():
    rows = [{"date": str(secs(TODAY - timedelta(days=1))), "totalCirculatingUSD": {"peggedUSD": 100, "peggedEUR": 5}},
            {"date": str(secs(TODAY)), "totalCirculatingUSD": {"peggedUSD": 101}}]
    p, _ = make(StablecoinSupplyProvider, lambda r: httpx.Response(200, json=rows))
    assert [(d, v) for d, v, _ in p.total_supply()] == [(TODAY - timedelta(days=1), 105.0)]
