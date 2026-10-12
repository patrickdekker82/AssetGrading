"""Fundamental formulas against hand-computed examples, and the TTM / point-in-time plumbing."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.grading.assign import assign_stock
from app.grading.engine import GradeInput, MetricInput, grade
from app.grading.fundamentals import (
    BeneishYear,
    FactTable,
    altman_z,
    beneish_indices,
    beneish_m,
    current_and_prior,
    fundamental_metrics,
    piotroski_f,
    snapshot,
    valuation_metrics,
)
from app.providers.sec import parse_company_facts
from tests.test_ingest import db  # noqa: F401  (database fixture)


# --- Altman Z (1968) ------------------------------------------------------------------------------
# Healthy company: WC 100, RE 200, EBIT 150, market value 1000, sales 1200, assets 1000, liabilities 500.
#   1.2 x 0.10 + 1.4 x 0.20 + 3.3 x 0.15 + 0.6 x 2.00 + 1.0 x 1.20
#   = 0.120 + 0.280 + 0.495 + 1.200 + 1.200 = 3.295
# Distressed: WC -50, RE -100, EBIT 10, market value 200, sales 500, assets 1000, liabilities 900.
#   1.2 x -0.05 + 1.4 x -0.10 + 3.3 x 0.01 + 0.6 x 0.2222 + 1.0 x 0.50
#   = -0.060 - 0.140 + 0.033 + 0.13333 + 0.500 = 0.46633
def test_altman_z_matches_hand_computation():
    assert altman_z(100, 200, 150, 1000, 1200, 1000, 500) == pytest.approx(3.295, abs=1e-9)
    assert altman_z(-50, -100, 10, 200, 500, 1000, 900) == pytest.approx(0.466333, abs=1e-6)


# --- Beneish M (1999) -----------------------------------------------------------------------------
# Year t: sales 1100, COGS 700, receivables 200, current assets 500, PPE 300, assets 1000, current
# liabilities 200, long-term debt 300, depreciation 50, SG&A 110, net income 100, operating cash flow 40.
# Year t-1: sales 1000, COGS 600, receivables 150, current assets 450, PPE 300, assets 900, current
# liabilities 200, long-term debt 250, depreciation 50, SG&A 100.
#   DSRI = (200/1100)/(150/1000) = 1.212121   GMI = 0.400/0.363636 = 1.1   AQI = 0.2/0.166667 = 1.2
#   SGI = 1.1   DEPI = (50/350)/(50/350) = 1   SGAI = 0.1/0.1 = 1   LVGI = 0.5/0.5 = 1
#   TATA = (100 - 40)/1000 = 0.06
#   M = -4.84 + 0.920 x 1.212121 + 0.528 x 1.1 + 0.404 x 1.2 + 0.892 x 1.1 + 0.115 - 0.172
#       + 4.679 x 0.06 - 0.327
#     = -4.84 + 1.115152 + 0.5808 + 0.4848 + 0.9812 + 0.115 - 0.172 + 0.28074 - 0.327 = -1.781308
# Just below the -1.78 threshold. With net income 120 (TATA 0.08) M rises by 4.679 x 0.02 to -1.687728.
YEAR_P = BeneishYear(sales=1000, cogs=600, receivables=150, current_assets=450, ppe=300, total_assets=900,
                     current_liabilities=200, long_term_debt=250, depreciation=50, sga=100)


def year_t(net_income: float = 100) -> BeneishYear:
    return BeneishYear(sales=1100, cogs=700, receivables=200, current_assets=500, ppe=300, total_assets=1000,
                       current_liabilities=200, long_term_debt=300, depreciation=50, sga=110,
                       net_income_continuing=net_income, cfo=40)


def test_beneish_indices_and_score_match_hand_computation():
    idx = beneish_indices(year_t(), YEAR_P)
    assert idx["DSRI"] == pytest.approx(1.212121, abs=1e-6)
    assert idx["GMI"] == pytest.approx(1.1, abs=1e-9)
    assert idx["AQI"] == pytest.approx(1.2, abs=1e-9)
    assert idx["SGI"] == pytest.approx(1.1)
    assert idx["DEPI"] == pytest.approx(1.0)
    assert idx["SGAI"] == pytest.approx(1.0)
    assert idx["LVGI"] == pytest.approx(1.0)
    assert idx["TATA"] == pytest.approx(0.06)
    assert beneish_m(year_t(), YEAR_P) == pytest.approx(-1.781308, abs=1e-6)
    assert beneish_m(year_t(120), YEAR_P) == pytest.approx(-1.687728, abs=1e-6)


def test_beneish_missing_depreciation_and_sga_count_as_no_change():
    t = BeneishYear(**{**year_t().__dict__, "depreciation": None, "sga": None})
    idx = beneish_indices(t, YEAR_P)
    assert idx["DEPI"] == 1.0 and idx["SGAI"] == 1.0


@pytest.mark.parametrize(("m_score", "capped"), [(-1.781308, False), (-1.687728, True)])
def test_beneish_gate_caps_stock_general(model, m_score, capped):
    metrics = {k: MetricInput(value=1.0, peer_pct=90.0) for k in
               ["gross_profit_to_assets", "roic", "margin_stability", "piotroski_f", "ebit_to_ev", "fcf_yield",
                "interest_coverage", "revenue_growth", "earnings_growth", "growth_consistency"]}
    metrics["technical_score"] = MetricInput(value=90.0)
    metrics["beneish_m"] = MetricInput(value=m_score)
    metrics["altman_z"] = MetricInput(value=3.295, peer_pct=90.0)
    result = grade(GradeInput(template_id="stock_general", tags=[], metrics=metrics), model)
    assert result.status == "graded"
    hit = [g.id for g in result.gates if g.status == "hit"]
    assert ("beneish_manipulation" in hit) is capped
    if capped:
        assert result.letter == "C"


def test_altman_gate_caps_stock_general(model):
    metrics = {k: MetricInput(value=1.0, peer_pct=90.0) for k in
               ["gross_profit_to_assets", "roic", "margin_stability", "piotroski_f", "ebit_to_ev", "fcf_yield",
                "interest_coverage", "revenue_growth", "earnings_growth", "growth_consistency"]}
    metrics["technical_score"] = MetricInput(value=90.0)
    metrics["altman_z"] = MetricInput(value=0.466333, peer_pct=5.0)
    result = grade(GradeInput(template_id="stock_general", tags=[], metrics=metrics), model)
    assert "altman_distress" in [g.id for g in result.gates if g.status == "hit"]
    assert result.letter == "C"


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


# --- assignment -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("key", "sic", "expected"), [
    ("jpm", 6021, ("stock_financial", ["bank"], "Financieel")),
    ("gs", 6211, ("stock_financial", ["bank"], "Financieel")),
    ("brk-b", 6331, ("stock_financial", ["insurer"], "Financieel")),
    ("unh", 6324, ("stock_general", [], "Financieel")),     # health plan: not a risk carrier template
    ("blk", 6211, ("stock_general", [], "Financieel")),     # override: asset manager
    ("pld", 6798, ("stock_reit", [], "Vastgoed")),
    ("aapl", 3571, ("stock_general", [], "Technologie")),
    ("v", 7389, ("stock_general", [], "Financieel")),       # override: sector only
    ("abn-as", None, ("stock_financial", ["bank"], "Financieel")),
    ("heia-as", None, ("stock_general", [], "Consument")),
    ("zzz", None, ("stock_general", [], "Overig")),
])
def test_stock_assignment(model, key, sic, expected):
    assert assign_stock(key, sic, model.assignment) == expected


# --- SEC facts, TTM and point in time -------------------------------------------------------------
def entry(start, end, val, filed, form="10-Q"):
    e = {"end": end, "val": val, "filed": filed, "form": form, "accn": "x"}
    if start:
        e["start"] = start
    return e


def company_facts(concepts: dict) -> dict:
    facts: dict = {"us-gaap": {}}
    for name, (unit, entries) in concepts.items():
        facts["us-gaap"][name] = {"units": {unit: entries}}
    return {"facts": facts}


def test_parse_company_facts_prefers_concepts_per_period_and_keeps_restatements():
    data = company_facts({
        # Old concept until 2016, new concept afterwards: each period uses the first concept that has it.
        "LoansAndLeasesReceivableNetReportedAmount": ("USD", [entry(None, "2016-06-30", 800, "2016-08-01")]),
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss": (
            "USD", [entry(None, "2024-06-30", 1500, "2024-08-01")]),
        # The same quarter reported again a year later as a comparative, then restated.
        "NetIncomeLoss": ("USD", [
            entry("2024-04-01", "2024-06-30", 100, "2024-08-01"),
            entry("2024-04-01", "2024-06-30", 100, "2025-08-01"),
            entry("2024-04-01", "2024-06-30", 90, "2025-11-01", "10-K/A"),
            entry("2023-07-01", "2024-06-30", 380, "2024-08-15", "10-K"),
            entry("2024-01-01", "2024-06-30", 50, "2024-08-01", "8-K"),        # not a periodic report
        ]),
    })
    facts = parse_company_facts(data, call_id=7)
    loans = sorted((f.as_of, f.value) for f in facts if f.field == "loans:i")
    assert loans == [(date(2016, 6, 30), 800), (date(2024, 6, 30), 1500)]
    q = [(f.value, f.available_at.date()) for f in facts if f.field == "net_income:3m"]
    assert q == [(100, date(2024, 8, 1)), (100, date(2025, 8, 1)), (90, date(2025, 11, 1))]
    assert [f.value for f in facts if f.field == "net_income:12m"] == [380]
    assert all(f.call_id == 7 for f in facts)


def table(rows: dict) -> FactTable:
    return FactTable.from_rows((k, date.fromisoformat(d), v) for (k, d), v in rows.items())


def test_ttm_from_year_to_date_figures():
    t = table({
        ("revenue:12m", "2025-12-31"): 400, ("revenue:9m", "2026-09-30"): 330, ("revenue:9m", "2025-09-30"): 300,
        ("revenue:3m", "2026-09-30"): 115,
    })
    # 9 months this year + full last year - first 9 months of last year = 330 + 400 - 300.
    assert t.ttm("revenue", date(2026, 9, 30)) == 430
    assert t.ttm("revenue", date(2025, 12, 31)) == 400
    assert t.ttm("revenue", date(2026, 6, 30)) is None


def test_share_count_checked_against_net_income_per_share():
    t = table({("diluted_shares:3m", "2026-06-30"): 711.1, ("net_income_common:3m", "2026-06-30"): 2_200e6,
               ("eps_diluted:3m", "2026-06-30"): 3.09})
    assert t.shares(date(2026, 6, 30)) == pytest.approx(711.1e6)        # tagged in millions
    t = table({("net_income_common:3m", "2026-03-31"): 5_000e6, ("eps_diluted:3m", "2026-03-31"): 2.5})
    assert t.shares(date(2026, 3, 31)) == pytest.approx(2_000e6)        # no share count tagged
    t = table({("diluted_shares:3m", "2026-03-31"): 1_990e6, ("net_income_common:3m", "2026-03-31"): 5_000e6,
               ("eps_diluted:3m", "2026-03-31"): 2.5})
    assert t.shares(date(2026, 3, 31)) == 1_990e6                         # close enough: reported count wins


def test_optional_items_count_as_zero_only_when_never_reported_recently():
    t = table({("total_assets:i", "2026-06-30"): 1000, ("goodwill:i", "2015-06-30"): 50,
               ("short_term_debt:i", "2026-03-31"): 20})
    s = snapshot(t, date(2026, 6, 30))
    assert s["goodwill"] == 0.0           # last reported 2015
    assert s["short_term_debt"] is None   # reported last quarter, missing now: unknown, not zero


def full_company(year_end: date, scale: float = 1.0) -> dict:
    d = year_end.isoformat()
    base = {
        "revenue": 1100, "cost_of_revenue": 700, "operating_income": 150, "pretax_income": 140, "income_tax": 30,
        "net_income": 110, "net_income_common": 110, "income_continuing": 110, "sga": 110, "depreciation": 50,
        "interest_expense": 10, "cfo": 160, "capex": 40, "dividends_paid": 20, "buybacks": 30,
        "share_issuance": 0, "diluted_shares": 100,
    }
    instants = {"total_assets": 1000, "current_assets": 500, "current_liabilities": 200, "total_liabilities": 500,
                "equity": 500, "retained_earnings": 200, "cash": 100, "receivables": 200, "ppe": 300,
                "long_term_debt": 300}
    rows = {(f"{k}:12m", d): v * scale for k, v in base.items()}
    rows.update({(f"{k}:i", d): v * scale for k, v in instants.items()})
    rows[("diluted_shares:12m", d)] = 100
    return rows


def test_fundamental_metrics_end_to_end():
    rows = full_company(date(2025, 12, 31))
    rows.update(full_company(date(2024, 12, 31), scale=0.9))
    rows.update(full_company(date(2023, 12, 31), scale=0.8))   # Piotroski compares with assets two years back
    t = table(rows)
    res = fundamental_metrics(t, date(2026, 3, 1), market_value=1000.0)
    v = res.values
    assert res.period_end == date(2025, 12, 31)
    assert v["gross_profit_to_assets"] == pytest.approx(0.4)
    assert v["ebit_to_ev"] == pytest.approx(150 / (1000 + 300 - 100))
    assert v["fcf_yield"] == pytest.approx(0.12)
    assert v["shareholder_yield"] == pytest.approx(0.05)
    assert v["accruals"] == pytest.approx(-0.05)
    assert v["roic"] == pytest.approx(150 * (1 - 30 / 140) / 700)
    assert v["net_debt_to_ebitda"] == pytest.approx(200 / 200)
    assert v["interest_coverage"] == pytest.approx(15)
    assert v["altman_z"] == pytest.approx(altman_z(300, 200, 150, 1000, 1100, 1000, 500))
    assert v["revenue_growth"] == pytest.approx(1 / 0.9 - 1)
    assert "piotroski_f" in v
    assert "beneish_m" in v


def test_periods_ending_after_the_grading_day_are_ignored():
    rows = full_company(date(2025, 12, 31))
    t = table(rows)
    cur, _ = current_and_prior(t, date(2025, 11, 30))
    assert cur is None   # the period end is after the knowledge date


def test_valuation_metrics_and_piotroski_scaling():
    vm = valuation_metrics({"ebit": 10, "fcf": 5, "payout": 2, "dividends": 1, "earnings": 8, "net_debt": -20,
                            "tce": 50, "shares": 1}, 100)
    assert vm["ebit_to_ev"] == pytest.approx(10 / 80)
    assert vm["earnings_yield"] == pytest.approx(0.08)
    rows = full_company(date(2025, 12, 31))
    rows.update(full_company(date(2024, 12, 31), scale=0.9))
    t = table(rows)
    c, p = current_and_prior(t, date(2026, 3, 1))
    score, n = piotroski_f(c, p, p2_assets=None)   # two signals need assets two years back
    assert n == 7 and score is None
    score, n = piotroski_f(c, p, p2_assets=850)
    assert n == 9 and 0 <= score <= 9


def test_dated_facts_keep_filing_history(db):  # noqa: F811
    from app.ingest.store import insert_facts
    from app.models import Asset
    from app.providers.base import Fact

    engine, sf = db
    with sf() as session:
        a = Asset(asset_class="stock", symbol="T", name="Test", slug="t")
        session.add(a)
        session.flush()
        filed = [datetime(2024, 8, 1, 23, 59, tzinfo=UTC), datetime(2025, 8, 1, 23, 59, tzinfo=UTC),
                 datetime(2025, 11, 1, 23, 59, tzinfo=UTC)]
        facts = [Fact("net_income:3m", date(2024, 6, 30), v, "USD", available_at=t)
                 for v, t in zip([100, 100, 90], filed, strict=True)]
        now = datetime.now(UTC)
        assert insert_facts(session, a.id, "sec", facts, now) == 2     # the unchanged comparative is skipped
        assert insert_facts(session, a.id, "sec", facts, now) == 0     # idempotent
        session.commit()
        rows = session.execute(text("SELECT value, available_at FROM fundamental_fact ORDER BY available_at")).all()
    assert [(float(v), t.date()) for v, t in rows] == [(100.0, date(2024, 8, 1)), (90.0, date(2025, 11, 1))]

