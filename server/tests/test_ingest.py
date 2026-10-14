"""End-to-end ingest against a fake set of providers and a real PostgreSQL test database."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ingest.crypto import run_crypto
from app.ingest.fx_macro import run_fx_macro
from app.ingest.store import insert_facts
from app.jobs import JobContext, run_job
from app.providers.base import Fact
from app.providers.config import load_providers_config
from app.providers.recorder import DbRecorder
from app.providers.registry import Providers
from app.universes import load_universes

TODAY = datetime.now(UTC).date()
YESTERDAY = TODAY - timedelta(days=1)
DATA_TABLES = ("price_bar", "fundamental_fact", "universe_membership", "asset_alias", "asset", "fx_rate",
               "macro_observation", "provider_response", "provider_call_log", "job_run", "grade_snapshot",
               "market_regime")


def ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


MARKETS = [
    {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 100.0, "market_cap": 1000,
     "market_cap_rank": 1, "fully_diluted_valuation": 1100, "total_volume": 50, "circulating_supply": 10,
     "total_supply": 10, "max_supply": 21},
    {"id": "tether", "symbol": "usdt", "name": "Tether", "current_price": 0.909, "market_cap": 900,
     "market_cap_rank": 2, "total_volume": 80, "circulating_supply": 900, "total_supply": 900, "max_supply": None},
    {"id": "wrapped-bitcoin", "symbol": "wbtc", "name": "Wrapped Bitcoin", "current_price": 100.0,
     "market_cap": 800, "market_cap_rank": 3},
    {"id": "collide", "symbol": "col", "name": "Collide", "current_price": 5.0, "market_cap": 700,
     "market_cap_rank": 4},
    {"id": "fakecoin", "symbol": "fake", "name": "Fakecoin", "current_price": 2.0, "market_cap": 600,
     "market_cap_rank": 5},
    {"id": "dogwif", "symbol": "dwif", "name": "Dogwif", "current_price": 0.5, "market_cap": 500,
     "market_cap_rank": 6, "fully_diluted_valuation": 500},
]
CATEGORIES = {"bitcoin": ["Layer 1 (L1)"], "tether": ["Stablecoins"], "collide": ["Layer 1 (L1)"],
              "fakecoin": ["Decentralized Finance (DeFi)"], "dogwif": ["Meme"]}
VENUE_PRICE = {"BTCUSDT": "110", "COLUSDT": "500", "BTC-USD": 110.0, "USDT-USD": 1.0}


def fake_world(request: httpx.Request) -> httpx.Response:
    host, path, q = request.url.host, request.url.path, request.url.params
    if host == "data-api.ecb.europa.eu":
        body = "KEY,TIME_PERIOD,OBS_VALUE\n" + "".join(
            f"x,{d.isoformat()},2.5\n" for d in days(TODAY - timedelta(days=10), YESTERDAY) if d.weekday() < 5)
        return httpx.Response(200, text=body, headers={"content-type": "text/csv"})
    if host == "api.frankfurter.dev":
        start, end = (date.fromisoformat(x) for x in path.removeprefix("/v1/").split(".."))
        rates = {d.isoformat(): {"USD": 1.1, "GBP": 0.85} for d in days(start, end) if d.weekday() < 5}
        return httpx.Response(200, json={"rates": rates})
    if host == "api.stlouisfed.org":
        start = date.fromisoformat(q["observation_start"])
        obs = [{"date": d.isoformat(), "value": "3.0" if d.weekday() < 5 else "."} for d in days(start, YESTERDAY)]
        return httpx.Response(200, json={"observations": obs})
    if host == "api.coingecko.com":
        if path.endswith("/coins/markets"):
            category = q.get("category")
            if category == "stablecoins":
                return httpx.Response(200, json=[MARKETS[1]])
            if category == "wrapped-tokens":
                return httpx.Response(200, json=[MARKETS[2]])
            if category:
                return httpx.Response(200, json=[])
            if q.get("ids"):
                extra = {"newcoin": {"id": "newcoin", "symbol": "new", "name": "Newcoin", "current_price": 3.0,
                                     "market_cap": 300, "market_cap_rank": 900}}
                hit = [m for m in MARKETS if m["id"] == q["ids"]] or ([extra[q["ids"]]] if q["ids"] in extra else [])
                return httpx.Response(200, json=hit)
            return httpx.Response(200, json=MARKETS)
        if path.endswith("/search"):
            return httpx.Response(200, json={"coins": [
                {"id": "newcoin", "name": "Newcoin", "symbol": "new", "market_cap_rank": 900}]})
        if "/contract/" in path:
            if path.endswith("0x" + "a" * 40) and "/ethereum/" in path:
                return httpx.Response(200, json={"id": "newcoin", "name": "Newcoin", "symbol": "new"})
            return httpx.Response(404, json={"error": "coin not found"})
        if path.endswith("/market_chart"):
            n = int(q["days"])
            points = [[ms(TODAY - timedelta(days=i)), 2.0] for i in range(n - 1, -1, -1)]
            return httpx.Response(200, json={"prices": points + [[ms(TODAY) + 3_600_000, 2.1]],
                                             "total_volumes": points})
        coin = path.rsplit("/", 1)[-1]
        platforms = {"solana": "DwifMint111"} if coin == "dogwif" else {"": ""}
        return httpx.Response(200, json={"id": coin, "categories": CATEGORIES.get(coin, []), "platforms": platforms,
                                         "developer_data": {"commit_count_4_weeks": 12},
                                         "watchlist_portfolio_users": 1000})
    if host == "data-api.binance.vision":
        if path.endswith("exchangeInfo"):
            symbols = [{"symbol": s, "baseAsset": s[:-4], "quoteAsset": "USDT", "status": "TRADING"}
                       for s in ("BTCUSDT", "COLUSDT")]
            return httpx.Response(200, json={"symbols": symbols})
        start = datetime.fromtimestamp(int(q["startTime"]) / 1000, UTC).date()
        end = min(datetime.fromtimestamp(int(q["endTime"]) / 1000, UTC).date(), YESTERDAY)
        price = VENUE_PRICE[q["symbol"]]
        rows = [[ms(d), price, price, price, price, "1", ms(d + timedelta(days=1)) - 1] for d in days(start, end)]
        return httpx.Response(200, json=rows)
    if host == "api.exchange.coinbase.com":
        if path == "/products":
            return httpx.Response(200, json=[
                {"id": p, "base_currency": p.split("-")[0], "quote_currency": "USD", "status": "online",
                 "trading_disabled": False} for p in ("BTC-USD", "USDT-USD")])
        if path.endswith("/book"):
            return httpx.Response(200, json={"bids": [["109", "1", 1]], "asks": [["111", "1", 1]]})
        product = path.split("/")[2]
        start, end = date.fromisoformat(q["start"][:10]), date.fromisoformat(q["end"][:10])
        price = VENUE_PRICE[product]
        rows = [[ms(d) // 1000, price, price, price, price, 1] for d in reversed(days(start, end))]
        return httpx.Response(200, json=rows)
    if host == "api.llama.fi":
        if path == "/protocols":
            return httpx.Response(200, json=[
                {"gecko_id": "bitcoin", "slug": "bitcoin-treasury", "category": "Treasury", "tvl": 9},
                {"gecko_id": "fakecoin", "slug": "fake-exchange", "category": "CEX", "tvl": 9},
                {"gecko_id": "collide", "slug": "collide-dex", "category": "Dexs", "tvl": 3},
            ])
        if path == "/v2/chains":
            return httpx.Response(200, json=[{"gecko_id": "bitcoin", "name": "Bitcoin"}])
        if path.startswith("/v2/historicalChainTvl/"):
            points = [{"date": ms(d) // 1000, "tvl": 7} for d in days(TODAY - timedelta(5), TODAY)]
            return httpx.Response(200, json=points)
        return httpx.Response(404, text="not found")
    if host == "community-api.coinmetrics.io":
        if "catalog-v2" in path:
            return httpx.Response(200, json={"data": [{"asset": "btc", "metrics": [
                {"metric": "CapMVRVCur", "frequencies": [{"frequency": "1d"}]}]}]})
        if "reference-data" in path:
            return httpx.Response(200, json={"data": [{"asset": "btc", "full_name": "Bitcoin"}]})
        start = date.fromisoformat(q["start_time"])
        rows = [{"asset": "btc", "time": f"{d.isoformat()}T00:00:00Z", "CapMVRVCur": "1.5"}
                for d in days(max(start, TODAY - timedelta(days=10)), TODAY)]
        return httpx.Response(200, json={"data": rows})
    if host in ("fapi.binance.com", "api.bybit.com"):
        return httpx.Response(451, text="restricted location")
    if host == "www.okx.com":
        if "instruments" in path:
            return httpx.Response(200, json={"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "state": "live"}]})
        if "funding" in path:
            rows = [{"fundingTime": str(ms(d)), "fundingRate": "0.0001"} for d in days(TODAY - timedelta(10), TODAY)]
            return httpx.Response(200, json={"code": "0", "data": list(reversed(rows))})
        return httpx.Response(200, json={"code": "0", "data": [{"oiUsd": "110"}]})
    if host == "api.bitvavo.com":
        if path == "/v2/markets":
            return httpx.Response(200, json=[{"market": "BTC-EUR", "base": "BTC", "quote": "EUR", "status": "trading"}])
        return httpx.Response(200, json=[{"market": "BTC-EUR", "last": "100", "volumeQuote": "5000"}])
    if host == "stablecoins.llama.fi":
        return httpx.Response(200, json=[{"date": str(ms(d) // 1000), "totalCirculatingUSD": {"peggedUSD": 100}}
                                         for d in days(TODAY - timedelta(5), TODAY)])
    if host == "api.dexscreener.com":
        return httpx.Response(200, json=[{"liquidity": {"usd": 1000.0}}])
    if host == "api.rugcheck.xyz":
        return httpx.Response(200, json={"mintAuthority": None, "freezeAuthority": None, "knownAccounts": {},
                                         "topHolders": [{"address": "a", "owner": "a", "pct": 30}],
                                         "markets": [{"lp": {"lpLockedPct": 100, "quoteUSD": 1, "baseUSD": 1}}]})
    return httpx.Response(500, text=f"unexpected {request.url}")


@pytest.fixture
def db(test_database_url):
    engine = create_engine(test_database_url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"))
    yield engine, sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def world(config_dir, db):
    cfg = load_providers_config(config_dir / "providers.yaml")
    crypto = cfg.crypto.model_copy(update={"history_start": (TODAY - timedelta(days=30)).isoformat()})
    fx = cfg.fx.model_copy(update={"history_start": (TODAY - timedelta(days=40)).isoformat()})
    macro = cfg.macro.model_copy(update={"history_start": (TODAY - timedelta(days=20)).isoformat(),
                                         "fred_series": {"DGS10": "test"}})
    # No real waiting in tests: lift every rate limit.
    fast = {name: e.model_copy(update={"rate_limit": {"calls": 10_000, "per_seconds": 1}})
            for name, e in cfg.providers.items()}
    cfg = cfg.model_copy(update={"crypto": crypto, "fx": fx, "macro": macro, "providers": fast})
    recorder = DbRecorder(db[1])
    providers = Providers(cfg, recorder, client=httpx.Client(transport=httpx.MockTransport(fake_world)),
                          sleep=lambda s: None, env={"COINGECKO_API_KEY": "CG-test", "FRED_API_KEY": "k"})
    return cfg, providers, load_universes(config_dir / "universes.yaml")


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


def scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def table_counts(engine):
    return {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in DATA_TABLES[:7]}



def test_crypto_run_is_idempotent_and_complete(db, world):
    engine, sf = db
    cfg, providers, universes = world
    first = run_crypto(sf, providers, cfg, universes, today=TODAY)
    assert first.errors == [], first.errors
    counts = table_counts(engine)
    second = run_crypto(sf, providers, cfg, universes, today=TODAY)
    assert table_counts(engine) == counts
    for key in ("bars_added", "membership_added", "fx_rates_added", "facts_added"):
        assert second.counts.get(key, 0) == 0, key

    # Membership: stablecoin and wrapped token are recorded but excluded from the list.
    rows = dict(scalar_rows(engine, "SELECT a.coingecko_id, m.exclusion FROM universe_membership m "
                                    "JOIN asset a ON a.id = m.asset_id"))
    assert rows == {"bitcoin": None, "tether": "stablecoin", "wrapped-bitcoin": "wrapped", "collide": None,
                    "fakecoin": None, "dogwif": None}
    tracked = {r for (r,) in scalar_rows(engine, "SELECT coingecko_id FROM asset WHERE tracked")}
    assert tracked == {"bitcoin", "tether", "collide", "fakecoin", "dogwif"}  # largest stablecoins too


def test_wrong_ticker_is_never_mapped(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    sources = dict(scalar_rows(engine, "SELECT coingecko_id, price_sources FROM asset WHERE tracked"))
    assert sources["bitcoin"] == ["coinbase", "binance", "coingecko"]
    # COLUSDT on Binance trades at 500 USDT while CoinGecko says EUR 5: a different coin with the same ticker.
    assert sources["collide"] == ["coingecko"]
    assert scalar(engine, "SELECT count(*) FROM asset_alias WHERE value = 'COLUSDT'") == 0


def test_prices_use_first_source_and_convert_to_euro(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    by_source = dict(scalar_rows(engine, "SELECT a.coingecko_id || ':' || b.source, count(*) FROM price_bar b "
                                         "JOIN asset a ON a.id = b.asset_id GROUP BY 1"))
    # Every mapped venue is kept; CoinGecko only where no venue is available.
    assert by_source == {"bitcoin:coinbase": 30, "bitcoin:binance": 30, "tether:coinbase": 30,
                         "collide:coingecko": 30, "fakecoin:coingecko": 30, "dogwif:coingecko": 30}
    assert scalar(engine, "SELECT max(ts) FROM price_bar") == YESTERDAY
    # 110 USD at 1 EUR = 1.10 USD is 100 EUR.
    eur = scalar(engine, "SELECT close_eur FROM price_bar_eur e JOIN asset a ON a.id = e.asset_id "
                         "WHERE a.coingecko_id = 'bitcoin' AND ts = :d", d=YESTERDAY)
    assert eur == pytest.approx(Decimal("100"))


def test_daily_view_prefers_first_source_and_falls_back(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    gap = TODAY - timedelta(days=5)
    with engine.begin() as conn:
        # Simulate a missing Coinbase day by removing it (bypassing the app; test only).
        conn.execute(text("DELETE FROM price_bar WHERE source = 'coinbase' AND ts = :d AND asset_id = "
                          "(SELECT id FROM asset WHERE coingecko_id = 'bitcoin')"), {"d": gap})
    rows = dict(scalar_rows(engine, "SELECT d.ts, d.source FROM price_daily_eur d JOIN asset a ON a.id = d.asset_id "
                                    "WHERE a.coingecko_id = 'bitcoin'"))
    assert len(rows) == 30
    assert rows[gap] == "binance"
    assert {v for k, v in rows.items() if k != gap} == {"coinbase"}


def test_usdt_quotes_need_the_usdt_usd_close(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    with engine.begin() as conn:
        btc = conn.execute(text("SELECT id FROM asset WHERE coingecko_id = 'bitcoin'")).scalar()
        conn.execute(text("DELETE FROM price_bar WHERE source = 'binance'"))
        for d, close in ((YESTERDAY, 110), (TODAY - timedelta(days=60), 110)):
            conn.execute(text(
                "INSERT INTO price_bar (asset_id, interval, ts, source, close, quote_currency, fetched_at) "
                "VALUES (:a, '1d', :d, 'binance', :c, 'USDT', now())"), {"a": btc, "d": d, "c": close})
    rows = dict(scalar_rows(engine, "SELECT ts, close_eur FROM price_bar_eur WHERE source = 'binance'"))
    assert rows[YESTERDAY] == pytest.approx(Decimal("100"))   # USDT-USD close 1.0 exists for that day
    assert rows[TODAY - timedelta(days=60)] is None           # no USDT-USD close: no euro value, no guess


def test_fx_and_macro_are_idempotent(db, world):
    engine, sf = db
    cfg, providers, _ = world
    first = run_fx_macro(sf, providers, cfg)
    assert first.counts["fx_rates_added"] > 0 and first.counts["macro_added"] > 0
    second = run_fx_macro(sf, providers, cfg)
    assert second.counts.get("fx_rates_added", 0) == 0 and second.counts.get("macro_added", 0) == 0
    # Weekend "." values from FRED are skipped.
    weekend = scalar(engine, "SELECT count(*) FROM macro_observation WHERE extract(isodow FROM date) > 5")
    assert weekend == 0


def test_revised_fact_is_appended_not_overwritten(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    asset_id = scalar(engine, "SELECT id FROM asset WHERE coingecko_id = 'bitcoin'")
    day = TODAY - timedelta(days=3)
    t1, t2 = datetime.now(UTC), datetime.now(UTC) + timedelta(hours=1)
    with sf() as s:
        assert insert_facts(s, asset_id, "test", [Fact("x", day, Decimal("1"), "usd")], t1) == 1
        assert insert_facts(s, asset_id, "test", [Fact("x", day, Decimal("1"), "usd")], t2) == 0
        assert insert_facts(s, asset_id, "test", [Fact("x", day, Decimal("2"), "usd")], t2) == 1
        s.commit()
    values = scalar_rows(engine, "SELECT value, available_at FROM fundamental_fact WHERE source = 'test' "
                                 "ORDER BY available_at")
    assert [v for v, _ in values] == [Decimal("1"), Decimal("2")]
    assert values[1][1] == t2  # the revision is only known from the moment it was seen
    with engine.connect() as conn, pytest.raises(Exception, match="append-only"):
        conn.execute(text("UPDATE fundamental_fact SET value = 3"))


def test_live_snapshot_keeps_first_value_of_the_day(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    MARKETS[0]["market_cap"] = 1234  # the market moved between two runs on the same day
    try:
        second = run_crypto(sf, providers, cfg, universes, today=TODAY)
    finally:
        MARKETS[0]["market_cap"] = 1000
    assert second.counts.get("facts_added", 0) == 0
    values = scalar_rows(engine, "SELECT value FROM fundamental_fact f JOIN asset a ON a.id = f.asset_id "
                                 "WHERE a.coingecko_id = 'bitcoin' AND field = 'market_cap_eur'")
    assert values == [(Decimal("1000"),)]


def test_job_runner_records_runs_and_skips_overlap(db, world):
    engine, sf = db
    cfg, providers, universes = world
    ctx = JobContext(engine, sf, providers, cfg, universes)
    run = run_job(ctx, "fx_macro", trigger="test")
    assert run.status == "ok" and run.summary["counts"]["fx_rates_added"] > 0
    import zlib

    key = zlib.crc32(b"graadmeter-job-fx_macro")
    with engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        skipped = run_job(ctx, "fx_macro", trigger="test")
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    assert skipped.status == "skipped"


def test_budget_stops_coingecko_but_run_continues(db, world):
    engine, sf = db
    cfg, providers, universes = world
    cg_settings = cfg.providers["coingecko"].model_copy(update={"monthly_budget": 0})
    cfg2 = cfg.model_copy(update={"providers": {**cfg.providers, "coingecko": cg_settings}})
    providers2 = Providers(cfg2, DbRecorder(sf), client=providers.client, sleep=lambda s: None,
                           env={"COINGECKO_API_KEY": "CG-test"})
    report = run_crypto(sf, providers2, cfg2, universes, today=TODAY)
    assert any("budget" in e for e in report.errors)
    assert report.counts.get("fx_rates_added", 0) > 0  # other sources still ran


def test_defillama_prefers_chain_and_skips_exchanges(db, world):
    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY)
    aliases = set(scalar_rows(engine, "SELECT a.coingecko_id, al.kind, al.value FROM asset_alias al "
                                      "JOIN asset a ON a.id = al.asset_id WHERE al.kind LIKE 'defillama%'"))
    assert aliases == {("bitcoin", "defillama_chain", "Bitcoin"), ("collide", "defillama_protocol", "collide-dex")}


def test_phase2_market_data(db, world, model):
    engine, sf = db
    cfg, providers, universes = world
    report = run_crypto(sf, providers, cfg, universes, today=TODAY, model=model)
    assert report.errors == [], report.errors
    # Binance futures and Bybit refuse the region; OKX is used instead and the skip is noted.
    assert any("binance_futures niet bereikbaar" in n for n in report.notes)
    facts = dict(scalar_rows(engine, "SELECT a.coingecko_id || ':' || f.field || ':' || f.source, count(*) "
                                     "FROM fundamental_fact f JOIN asset a ON a.id = f.asset_id GROUP BY 1"))
    assert facts["bitcoin:funding_rate_daily:okx"] == 10
    assert facts["bitcoin:open_interest_usd:okx"] == 1
    assert facts["bitcoin:orderbook_depth_2pct_usd:coinbase"] == 1
    assert facts["bitcoin:bitvavo_volume_24h_eur:derived"] == 1
    assert facts["dogwif:holders_top10_pct:rugcheck"] == 1
    assert facts["dogwif:dex_liquidity_usd:dexscreener"] == 1
    flags = dict(scalar_rows(engine, "SELECT a.coingecko_id, f.value FROM fundamental_fact f JOIN asset a "
                                     "ON a.id = f.asset_id WHERE f.field = 'flag_not_on_mica_venue'"))
    assert flags["bitcoin"] == 0 and flags["collide"] == 1   # BTC on Coinbase and Bitvavo; COL nowhere
    assert scalar(engine, "SELECT count(*) FROM macro_observation WHERE series_id = 'STABLECOIN_SUPPLY_USD'") == 5


def test_grading_gives_every_tracked_coin_a_snapshot_and_reproduces_it(db, world, model):
    from app.grading.crypto import grade_crypto
    from app.grading.recompute import verify_all
    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, universes = world
    run_crypto(sf, providers, cfg, universes, today=TODAY, model=model)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE grade_snapshot"))
    with sf() as s:
        version_id = register_model_version(s, model).id
    report = grade_crypto(sf, model, version_id, YESTERDAY, TODAY - timedelta(days=30))
    assert report.counts["snapshots_added"] == 5
    rows = dict(scalar_rows(engine, "SELECT a.coingecko_id, g.template_id || ':' || g.status FROM grade_snapshot g "
                                    "JOIN asset a ON a.id = g.asset_id"))
    assert rows["bitcoin"].startswith("crypto_bitcoin:")
    # Only 30 days of prices: too short for the peg deviation (needs 60), so no peg safety yet.
    assert rows["tether"] == "crypto_stablecoin:no_grade"
    assert rows["dogwif"] == "crypto_memecoin:speculative"
    # Every snapshot without a grade states why.
    reasons = scalar_rows(engine, "SELECT result->>'reason_nl' FROM grade_snapshot WHERE status = 'no_grade'")
    assert all(r for (r,) in reasons)
    # Dogwif: top-10 holders own 30% (> 15%) so the memecoin is capped at D.
    assert scalar(engine, "SELECT letter FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id "
                          "WHERE a.coingecko_id = 'dogwif'") == "D"
    with sf() as s:
        checks = verify_all(s)
    assert len(checks) == 5 and all(c.ok for c in checks), [c.differences for c in checks if not c.ok]
    again = grade_crypto(sf, model, version_id, YESTERDAY, TODAY - timedelta(days=30))
    assert again.counts.get("snapshots_added", 0) == 0
    with engine.connect() as conn, pytest.raises(Exception, match="append-only"):
        conn.execute(text("UPDATE grade_snapshot SET letter = 'A+'"))


def scalar_rows(engine, sql):
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


def test_fake_world_is_json_safe():
    # Guard against the fake drifting from what adapters accept.
    assert json.dumps(MARKETS)
