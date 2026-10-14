"""Stock ingest and grading end to end, against fake SEC and Yahoo responses and a real test database."""

import json
import math
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.grading.stocks import grade_stocks
from app.ingest.stocks import run_stocks
from app.jobs import last_trading_day
from app.providers.config import load_providers_config
from app.providers.recorder import DbRecorder
from app.providers.registry import Providers
from app.providers.stockprices import YahooProvider
from app.stocks_config import load_stocks_config
from app.universes import load_universes
from tests.test_ingest import db, fake_world, scalar  # noqa: F401  (db is a fixture)

TODAY = datetime.now(UTC).date()
HISTORY_DAYS = 1300
TICKERS = {"0": {"cik_str": 1, "ticker": "AAA", "title": "Aaa Corp"},
           "1": {"cik_str": 2, "ticker": "BNK", "title": "Bank Corp"},
           "2": {"cik_str": 2, "ticker": "BNK-P", "title": "Bank Corp"},      # second share class
           "3": {"cik_str": 3, "ticker": "FOR", "title": "Foreign plc"}}     # files a 20-F
SUBMISSIONS = {1: ("Aaa Corp", "3571", "10-K"), 2: ("Bank Corp", "6021", "10-K"), 3: ("Foreign plc", "2834", "20-F")}
DIVIDEND_FACTOR = {"value": 1.0}


def concept_entries(values: dict[int, float], unit: str = "USD", instant: bool = False) -> dict:
    out = []
    for year, v in values.items():
        end = f"{year}-12-31"
        e = {"end": end, "val": v, "filed": f"{year + 1}-02-15", "form": "10-K", "accn": f"a{year}"}
        if not instant:
            e["start"] = f"{year}-01-01"
        out.append(e)
    return {"units": {unit: out}}


def company_facts(cik: int) -> dict:
    years = [TODAY.year - 4 + i for i in range(3)] + [TODAY.year - 1]
    years = sorted(set(years))
    g = {y: 1.08 ** i for i, y in enumerate(years)}
    k = 1.0 if cik == 1 else 3.0
    flows = {"Revenues": 1000, "CostOfRevenue": 600, "OperatingIncomeLoss": 150, "NetIncomeLoss": 100,
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 130,
             "IncomeTaxExpenseBenefit": 30, "NetCashProvidedByUsedInOperatingActivities": 140,
             "PaymentsToAcquirePropertyPlantAndEquipment": 40, "PaymentsOfDividends": 20,
             "PaymentsForRepurchaseOfCommonStock": 30, "DepreciationDepletionAndAmortization": 50,
             "SellingGeneralAndAdministrativeExpense": 120, "InterestExpense": 10,
             "InterestIncomeExpenseNet": 300, "NoninterestIncome": 200, "NoninterestExpense": 280}
    instants = {"Assets": 2000, "AssetsCurrent": 800, "LiabilitiesCurrent": 400, "Liabilities": 1200,
                "StockholdersEquity": 800, "RetainedEarningsAccumulatedDeficit": 500,
                "CashAndCashEquivalentsAtCarryingValue": 200, "AccountsReceivableNetCurrent": 150,
                "PropertyPlantAndEquipmentNet": 500, "LongTermDebt": 400, "Goodwill": 100, "Deposits": 1500,
                "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss": 1000}
    facts = {name: concept_entries({y: v * k * g[y] for y in years}) for name, v in flows.items()}
    facts.update({name: concept_entries({y: v * k * g[y] for y in years}, instant=True)
                  for name, v in instants.items()})
    facts["WeightedAverageNumberOfDilutedSharesOutstanding"] = concept_entries({y: 10.0 * k for y in years}, "shares")
    facts["EarningsPerShareDiluted"] = concept_entries({y: 10 * g[y] for y in years}, "USD/shares")
    return {"cik": cik, "facts": {"us-gaap": facts}}


def chart(symbol: str, p1: int, p2: int) -> dict:
    start = max(datetime.fromtimestamp(p1, UTC).date(), TODAY - timedelta(days=HISTORY_DAYS))
    end = min(datetime.fromtimestamp(p2, UTC).date(), TODAY)
    seed = sum(map(ord, symbol))
    stamps, closes = [], []
    d = start
    while d <= end:
        if d.weekday() < 5:
            i = (d - (TODAY - timedelta(days=HISTORY_DAYS))).days
            stamps.append(int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC).timestamp()))
            closes.append(round(100 + seed % 50 + i * 0.05 * (1 + seed % 3) + 5 * math.sin(i / 20 + seed), 4))
        d += timedelta(days=1)
    adj = [c * DIVIDEND_FACTOR["value"] for c in closes]
    currency = "EUR" if symbol.endswith(".AS") or symbol == "^AEX" else "USD"
    return {"chart": {"result": [{
        "meta": {"currency": currency, "exchangeTimezoneName": "UTC"},
        "timestamp": stamps,
        "indicators": {"quote": [{"open": closes, "high": [c * 1.01 for c in closes],
                                  "low": [c * 0.99 for c in closes], "close": closes,
                                  "volume": [1000] * len(closes)}],
                       "adjclose": [{"adjclose": adj}]},
    }], "error": None}}


def fake_markets(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "www.sec.gov":
        assert "@" in request.headers["user-agent"]
        return httpx.Response(200, json=TICKERS)
    if host == "data.sec.gov":
        cik = int(path.split("CIK")[1].split(".")[0])
        if path.startswith("/submissions/"):
            name, sic, form = SUBMISSIONS[cik]
            return httpx.Response(200, json={
                "name": name, "sic": sic, "sicDescription": "x", "tickers": [], "exchanges": [],
                "addresses": {"business": {"isForeignLocation": 1 if cik == 3 else 0,
                                           "countryCode": "GB" if cik == 3 else None}},
                "filings": {"recent": {"form": [form], "filingDate": [f"{TODAY.year}-02-15"],
                                       "reportDate": [f"{TODAY.year - 1}-12-31"]}},
            })
        return httpx.Response(200, json=company_facts(cik))
    if host == "api.openfigi.com":
        isin = json.loads(request.content)[0]["idValue"]
        if isin == "US0000000AA1":
            return httpx.Response(200, json=[{"data": [{"ticker": "AAA", "exchCode": "US", "name": "AAA CORP"}]}])
        return httpx.Response(200, json=[{"warning": "No identifier found."}])
    if host == "publicreporting.cftc.gov":
        start = TODAY - timedelta(days=800)
        rows = [{"report_date_as_yyyy_mm_dd": f"{d.isoformat()}T00:00:00.000", "m_money_positions_long_all": "100",
                 "m_money_positions_short_all": str(40 + i % 30), "lev_money_positions_long": "50",
                 "lev_money_positions_short": str(30 + i % 20), "open_interest_all": "1000"}
                for i, d in enumerate(start + timedelta(weeks=w) for w in range(110)) if d <= TODAY]
        return httpx.Response(200, json=rows)
    if host == "api.worldbank.org":
        codes = path.split("/country/")[1].split("/")[0].split(";")
        rows = [{"countryiso3code": c, "date": str(y), "value": 1.0 + i + (y - 2020) * 0.1}
                for i, c in enumerate(codes) if c != "EMU" for y in range(2018, TODAY.year)]
        return httpx.Response(200, json=[{"page": 1}, rows])
    if host == "fc.yahoo.com":
        return httpx.Response(404, text="not found")
    if path == "/v1/test/getcrumb":
        return httpx.Response(200, text="crumb123")
    if host == "query2.finance.yahoo.com" and "quoteSummary" in path:
        holdings = [{"holdingName": f"H{i}", "holdingPercent": {"raw": 0.05}} for i in range(10)]
        return httpx.Response(200, json={"quoteSummary": {"result": [{"topHoldings": {"holdings": holdings}}]}})
    if host == "query1.finance.yahoo.com":
        symbol = path.rsplit("/", 1)[1]
        q = request.url.params
        return httpx.Response(200, json=chart(symbol, int(q["period1"]), int(q["period2"])))
    return fake_world(request)


@pytest.fixture
def stock_world(config_dir, db):  # noqa: F811
    cfg = load_providers_config(config_dir / "providers.yaml")
    fx = cfg.fx.model_copy(update={"history_start": (TODAY - timedelta(days=HISTORY_DAYS + 10)).isoformat()})
    fast = {name: e.model_copy(update={"rate_limit": {"calls": 10_000, "per_seconds": 1}})
            for name, e in cfg.providers.items()}
    macro = cfg.macro.model_copy(update={"history_start": (TODAY - timedelta(days=800)).isoformat()})
    cfg = cfg.model_copy(update={"fx": fx, "providers": fast, "macro": macro})
    stocks = load_stocks_config(config_dir / "stocks.yaml")
    aex = stocks.aex.model_copy(update={"members": [m for m in stocks.aex.members if m.ticker in ("ABN", "HEIA")]})
    stocks = stocks.model_copy(update={"aex": aex})
    providers = Providers(cfg, DbRecorder(db[1]), client=httpx.Client(transport=httpx.MockTransport(fake_markets)),
                          sleep=lambda s: None, env={"SEC_USER_AGENT": "test test@example.org", "FRED_API_KEY": "k"})
    DIVIDEND_FACTOR["value"] = 1.0
    return cfg, providers, stocks, load_universes(config_dir / "universes.yaml")


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


def test_stock_run_builds_lists_and_is_idempotent(db, stock_world, model):  # noqa: F811
    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    report = run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    assert report.errors == [], report.errors
    with engine.connect() as conn:
        assets = dict(conn.execute(text("SELECT slug, asset_class FROM asset")).all())
    assert assets == {"aaa": "stock", "bnk": "stock", "abn-as": "stock", "heia-as": "stock",
                      "sp500": "index", "aex": "index"}       # no second share class, no 20-F filer
    sectors = dict(scalar_rows(engine, "SELECT slug, sector FROM asset WHERE asset_class = 'stock'"))
    assert sectors == {"aaa": "Technologie", "bnk": "Financieel", "abn-as": "Financieel", "heia-as": "Consument"}
    us = scalar_rows(engine, "SELECT a.slug, m.rank, m.included FROM universe_membership m "
                             "JOIN asset a ON a.id = m.asset_id WHERE universe = 'stocks_us' ORDER BY rank")
    assert [r[0] for r in us] == ["bnk", "aaa"]               # Bank Corp is three times larger
    assert all(r[2] for r in us)
    assert scalar(engine, "SELECT count(*) FROM universe_membership WHERE universe = 'stocks_aex'") == 2
    assert scalar(engine, "SELECT count(*) FROM fundamental_fact WHERE source = 'sec'") > 0
    assert scalar(engine, "SELECT count(*) FROM asset_alias WHERE kind = 'isin'") == 2
    counts = {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in ("price_bar", "fundamental_fact")}

    second = run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    assert second.errors == []
    assert {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in counts} == counts
    assert "company_facts_fetched" not in second.counts        # no new filing, fetched less than a month ago


def test_dividend_readjusts_price_history(db, stock_world, model):  # noqa: F811
    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    before = scalar(engine, "SELECT close FROM price_bar b JOIN asset a ON a.id = b.asset_id "
                            "WHERE a.slug = 'aaa' ORDER BY ts LIMIT 1")
    DIVIDEND_FACTOR["value"] = 0.98
    report = run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    assert report.counts.get("price_history_readjusted", 0) >= 1
    after = scalar(engine, "SELECT close FROM price_bar b JOIN asset a ON a.id = b.asset_id "
                           "WHERE a.slug = 'aaa' ORDER BY ts LIMIT 1")
    assert float(after) == pytest.approx(float(before) * 0.98, rel=1e-6)
    # The price as traded is not affected by the adjustment.
    assert scalar(engine, "SELECT count(DISTINCT (as_of, value)) FROM fundamental_fact f JOIN asset a "
                          "ON a.id = f.asset_id WHERE a.slug = 'aaa' AND field = 'close_raw'") == \
        scalar(engine, "SELECT count(*) FROM fundamental_fact f JOIN asset a "
                       "ON a.id = f.asset_id WHERE a.slug = 'aaa' AND field = 'close_raw'")


def test_stock_grading_uses_bank_template_and_recomputes(db, stock_world, model):  # noqa: F811
    from app.grading.recompute import verify_all
    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    with sf() as session:
        version_id = register_model_version(session, model).id
    as_of = scalar(engine, "SELECT max(ts) FROM price_bar")
    report = grade_stocks(sf, model, version_id, stocks, as_of)
    assert report.errors == []
    rows = {r[0]: r[1:] for r in scalar_rows(engine, """
        SELECT a.slug, g.template_id, g.inputs->'grade_input'->'tags', g.status,
               g.inputs->'grade_input'->'metrics' ? 'altman_z', g.inputs->'grade_input'->'metrics' ? 'rotce'
        FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id""")}
    assert rows["bnk"][0] == "stock_financial" and rows["bnk"][1] == ["bank"]
    assert rows["bnk"][4] is True                             # bank metrics present
    assert rows["aaa"][0] == "stock_general" and rows["aaa"][3] is True
    assert rows["abn-as"][2] == "no_grade"                    # no free fundamentals for ABN AMRO
    with sf() as session:
        checks = verify_all(session, None)
    assert checks and all(c.ok for c in checks), [c.differences for c in checks if not c.ok]


def test_yahoo_undoes_split_adjustment_for_the_traded_close():
    split_day = TODAY - timedelta(days=5)
    stamps = [int(datetime.combine(TODAY - timedelta(days=d), datetime.min.time(), UTC).timestamp()) + 50_000
              for d in (8, 7, 3)]
    body = {"chart": {"result": [{
        "meta": {"currency": "USD", "exchangeTimezoneName": "UTC"}, "timestamp": stamps,
        "events": {"splits": {"x": {"date": int(datetime.combine(split_day, datetime.min.time(), UTC).timestamp()),
                                    "numerator": 4, "denominator": 1}}},
        "indicators": {"quote": [{"open": [25, 26, 27], "high": [25, 26, 27], "low": [25, 26, 27],
                                  "close": [25, 26, 27], "volume": [1, 1, 1]}],
                       "adjclose": [{"adjclose": [24, 25, 27]}]},
    }]}}
    from app.providers.base import MemoryRecorder, ProviderSettings, RateLimit

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    y = YahooProvider(ProviderSettings("yahoo", "https://q", RateLimit(100, 1)), MemoryRecorder(), client=client)
    s = y.series("X", TODAY - timedelta(days=10), TODAY)
    assert [float(v) for _, v in s.raw_closes] == [100.0, 104.0, 27.0]    # before the 4:1 split: x4
    assert [float(b.close) for b in s.bars] == [24.0, 25.0, 27.0]
    assert float(s.bars[0].open) == pytest.approx(24.0)


@pytest.mark.parametrize(("now", "expected"), [
    (datetime(2026, 10, 12, 22, 30, tzinfo=UTC), date(2026, 10, 12)),    # Monday evening
    (datetime(2026, 10, 12, 10, 0, tzinfo=UTC), date(2026, 10, 9)),      # Monday morning -> Friday
    (datetime(2026, 10, 11, 22, 30, tzinfo=UTC), date(2026, 10, 9)),     # Sunday -> Friday
])
def test_last_trading_day(now, expected):
    assert last_trading_day(now) == expected


def scalar_rows(engine, sql):
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]
