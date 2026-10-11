"""Asset page, chart, search, fetch-on-request and watchlist endpoints against fake providers."""

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.grading.crypto import grade_crypto
from app.ingest.crypto import run_crypto
from app.providers.recorder import DbRecorder
from app.providers.registry import Providers
from app.settings import get_settings
from tests.test_ingest import TODAY, YESTERDAY, fake_world


@pytest.fixture
def client(db, world, model, test_database_url, monkeypatch):  # noqa: F811 (fixtures from test_ingest)
    engine, sf = db
    cfg, _, universes = world
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        jobs = app.state.jobs
        jobs.cfg = cfg
        jobs.providers = Providers(cfg, DbRecorder(jobs.sf), sleep=lambda s: None,
                                   client=httpx.Client(transport=httpx.MockTransport(fake_world)),
                                   env={"COINGECKO_API_KEY": "CG-test", "FRED_API_KEY": "k"})
        run_crypto(jobs.sf, jobs.providers, cfg, universes, today=TODAY, model=jobs.model)
        grade_crypto(jobs.sf, jobs.model, jobs.model_version_id, YESTERDAY, TODAY - timedelta(days=30))
        yield c
    get_settings.cache_clear()
    get_engine.cache_clear()


from tests.test_ingest import db, model, world  # noqa: E402,F401  (shared fixtures)


def test_asset_detail_has_all_sections(client):
    d = client.get("/api/assets/bitcoin").json()
    assert d["asset"]["template"] == "crypto_bitcoin"
    assert d["snapshot"]["model_version"] and d["snapshot"]["as_of"] == YESTERDAY.isoformat()
    assert d["pillars"] and all("metrics" in p for p in d["pillars"])
    metric = d["pillars"][0]["metrics"][0]
    assert {"unit", "direction", "peer_pct", "source"} <= set(metric)
    assert isinstance(d["gates"], list)
    assert d["explanation"].startswith("Bitcoin")
    assert d["price"]["quote_currency"] == "USD"


def test_unknown_asset_is_404(client):
    assert client.get("/api/assets/does-not-exist").status_code == 404


@pytest.mark.parametrize("interval", ["1d", "1w", "1M"])
def test_chart_data(client, interval):
    d = client.get(f"/api/assets/bitcoin/chart?interval={interval}").json()
    assert d["candles"] and {"time", "open", "high", "low", "close"} <= set(d["candles"][0])
    assert d["benchmark"] is None  # bitcoin is its own benchmark
    assert "sma50" not in d["indicators"] or d["indicators"]["sma50"]  # 30 days: too short, left out
    assert {c["id"] for c in d["catalog"]} >= {"sma200", "rsi14w", "funding"}
    times = [c["time"] for c in d["candles"]]
    assert times == sorted(times)


def test_chart_compares_altcoins_with_bitcoin(client):
    d = client.get("/api/assets/collide/chart").json()
    assert d["benchmark"] and d["benchmark_name"] == "Bitcoin"


def test_bad_interval_is_refused(client):
    assert client.get("/api/assets/bitcoin/chart?interval=1h").status_code == 400


def test_search_finds_local_assets_without_asking_coingecko(client):
    d = client.get("/api/search?q=bitc").json()
    assert [r["id"] for r in d["local"]][:1] == ["bitcoin"]
    assert d["remote"] == []


def test_search_falls_back_to_coingecko_and_contract_addresses(client):
    d = client.get("/api/search?q=newco").json()
    assert d["local"] == [] and d["remote"][0]["id"] == "newcoin"
    d = client.get("/api/search?q=0x" + "a" * 40).json()
    assert d["remote"][0]["platform"] == "ethereum"


def test_search_isin_explains_it_comes_later(client):
    assert "ISIN" in client.get("/api/search?q=IE00B4L5Y983").json()["message"]


def test_fetch_on_request_creates_and_grades_the_asset(client, db):  # noqa: F811
    engine, _ = db
    res = client.post("/api/assets/fetch", json={"coingecko_id": "newcoin"})
    assert res.status_code == 200 and res.json()["snapshots_added"] == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT tracked FROM asset WHERE coingecko_id = 'newcoin'")).scalar() is True
    assert client.get("/api/assets/newcoin").json()["snapshot"] is not None


def test_fetch_of_unknown_coin_says_so(client):
    res = client.post("/api/assets/fetch", json={"coingecko_id": "nothing-here"})
    assert res.status_code == 404 and "geen grade" in res.json()["detail"]


def test_watchlist_round_trip(client):
    assert client.post("/api/watchlist/collide").json()["in_watchlist"] is True
    assert client.get("/api/watchlist").json() == ["collide"]
    rows = client.get("/api/grades?tab=watchlist").json()["rows"]
    assert [r["id"] for r in rows] == ["collide"]
    assert client.delete("/api/watchlist/collide").json()["in_watchlist"] is False
    assert client.get("/api/watchlist").json() == []


def test_grades_rows_carry_sparkline_and_links(client):
    rows = client.get("/api/grades?tab=crypto").json()["rows"]
    btc = next(r for r in rows if r["id"] == "bitcoin")
    assert len(btc["spark"]) == 30 and btc["asset_class"] == "crypto"
