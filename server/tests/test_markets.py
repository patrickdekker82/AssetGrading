"""Market regime, its effect on grades, and ETF tracking difference."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from app.grading.engine import GradeInput, MetricInput, grade
from app.grading.letters import shift
from app.grading.markets import MarketData, annual_return, govt_yield, tracking_differences
from app.grading.regime import compute_regime, week_end


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


def daily(start: date, end: date, f) -> pd.Series:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return pd.Series([f(i, d) for i, d in enumerate(days)], index=days, dtype=float)


START, DAY = date(2014, 1, 1), date(2026, 10, 9)   # DAY is a Friday


def test_week_end_is_the_last_friday():
    assert week_end(date(2026, 10, 9)) == date(2026, 10, 9)
    assert week_end(date(2026, 10, 12)) == date(2026, 10, 9)    # Monday uses the previous week
    assert week_end(date(2026, 10, 15)) == date(2026, 10, 9)


@pytest.mark.parametrize(("world_up", "hy_level", "vix_level", "state", "score"), [
    (True, "low", "low", "risk_on", 3),
    (False, "high", "high", "risk_off", -3),
    (True, "mid", "high", "neutral", 0),
    (False, "low", "mid", "neutral", 0),
    (False, "high", "mid", "risk_off", -2),
])
def test_regime_votes(model, world_up, hy_level, vix_level, state, score):
    world = daily(START, DAY, lambda i, d: 100 + (i * 0.05 if world_up else -i * 0.05))
    # History rises evenly, then the last value is placed at a low, middle or high percentile.
    level = {"low": 0.1, "mid": 0.65, "high": 0.95}

    def series(kind):
        s = daily(START, DAY, lambda i, d: float(i))
        s.iloc[-1] = (len(s) - 1) * level[kind]
        return s

    r = compute_regime(DAY, world, series(hy_level), series(vix_level), model.settings.regime)
    assert (r.state, r.score) == (state, score)
    assert set(r.inputs) == {"world_index", "high_yield_spread", "vix"}
    assert all(v is not None for v in r.inputs.values())


def test_regime_needs_two_inputs(model):
    world = daily(START, DAY, lambda i, d: 100 + i)
    empty = pd.Series(dtype=float)
    r = compute_regime(DAY, world, empty, empty, model.settings.regime)
    assert r.state is None and r.inputs["vix"] is None


def test_world_index_uses_completed_months_only(model):
    # Flat at 100 for years; in the current month the index jumps to 200. The average of the last ten
    # completed month-ends stays 100.
    world = daily(START, DAY, lambda i, d: 200.0 if d >= date(2026, 10, 1) else 100.0)
    r = compute_regime(DAY, world, pd.Series(dtype=float), pd.Series(dtype=float), model.settings.regime)
    assert r.inputs["world_index"]["average_10m"] == 100.0
    assert r.inputs["world_index"]["vote"] == 1


def stock_input(regime: str | None, altman: float = 3.0) -> GradeInput:
    metrics = {k: MetricInput(value=1.0, peer_pct=70.0) for k in
               ["gross_profit_to_assets", "roic", "margin_stability", "piotroski_f", "ebit_to_ev", "fcf_yield",
                "interest_coverage", "revenue_growth", "earnings_growth", "growth_consistency"]}
    metrics["technical_score"] = MetricInput(value=70.0)
    metrics["altman_z"] = MetricInput(value=altman, peer_pct=70.0)
    return GradeInput(template_id="stock_general", tags=[], metrics=metrics, regime=regime)


def test_risk_off_moves_stock_grade_one_notch_and_gates_still_win(model):
    neutral = grade(stock_input("neutral"), model)
    off = grade(stock_input("risk_off"), model)
    on = grade(stock_input("risk_on"), model)
    assert neutral.letter == on.letter                           # risk on does not move grades
    assert off.letter == shift(neutral.letter, -1)
    assert off.score == neutral.score                            # only the letter moves
    assert any("Marktregime" in n for n in off.notes)
    capped = grade(stock_input("risk_off", altman=1.0), model)   # Altman gate: at most C
    assert capped.letter in ("C", "C-")


def test_regime_does_not_move_templates_without_regime_adjust(model):
    metrics = {"tracking_difference": MetricInput(value=-0.001, peer_pct=80.0),
               "fund_size": MetricInput(value=1e9, peer_pct=80.0)}
    a = grade(GradeInput(template_id="etf", tags=[], metrics=metrics, regime="neutral"), model)
    b = grade(GradeInput(template_id="etf", tags=[], metrics=metrics, regime="risk_off"), model)
    assert a.letter == b.letter


def test_shift_stays_within_scale():
    assert shift("B", -1) == "B-" and shift("B", 1) == "B+"
    assert shift("F", -1) == "F" and shift("A+", 1) == "A+"


def market_data(closes_eur: dict[int, pd.Series], macro: dict | None = None) -> MarketData:
    return MarketData(as_of=DAY, knowledge=datetime(2026, 10, 10), assets=[], closes={}, closes_eur=closes_eur,
                      volume={}, facts={}, macro=macro or {}, members={}, index_snapshots={})


def growth(rate: float) -> pd.Series:
    return daily(DAY - timedelta(days=6 * 366), DAY, lambda i, d: 100 * (1 + rate) ** (i / 365.25))


def test_annual_return():
    assert annual_return(growth(0.08), DAY, 5) == pytest.approx(0.08, abs=1e-3)
    assert annual_return(growth(0.08).loc[DAY - timedelta(days=400):], DAY, 3) is None   # too young


def test_tracking_difference_against_the_index_series():
    data = market_data({1: growth(0.0780), 2: growth(0.0795), 9: growth(0.0800)})
    td = tracking_differences([1, 2], data, reference_id=9, years_options=[5, 3])
    assert td.years == 5 and td.reference == "index"
    assert td.values[1] == pytest.approx(-0.0020, abs=2e-4)
    assert td.values[2] == pytest.approx(-0.0005, abs=2e-4)


def test_tracking_difference_against_the_median_etf_without_index_series():
    young = growth(0.07).loc[DAY - timedelta(days=4 * 365):]   # only 4 years: not in the 5-year window
    data = market_data({1: growth(0.080), 2: growth(0.078), 3: growth(0.075), 4: young})
    td = tracking_differences([1, 2, 3, 4], data, reference_id=None, years_options=[5, 3])
    assert td.years == 5 and td.reference == "median" and 4 not in td.values
    assert td.values[2] == pytest.approx(0.0, abs=1e-9)
    assert td.values[1] > 0 > td.values[3]


def test_government_yield_interpolates_between_2_and_10_years():
    macro = {"DGS2": pd.Series([4.0], index=[DAY]), "DGS10": pd.Series([5.0], index=[DAY])}
    data = market_data({}, macro)
    assert govt_yield(data, "USD", 6.0) == pytest.approx(0.045)
    assert govt_yield(data, "USD", 1.0) == pytest.approx(0.04)
    assert govt_yield(data, "EUR", 6.0) is None


# --- the markets run end to end, against fake Yahoo, FRED and ECB ---------------------------------

from app.grading.markets import grade_markets  # noqa: E402
from app.grading.regime import update_regime  # noqa: E402
from app.ingest.markets import run_markets  # noqa: E402
from app.ingest.report import Report  # noqa: E402
from app.markets_config import FundRow, IndexEntry, IndexGroup, MarketsConfig  # noqa: E402
from tests.test_ingest import db, scalar  # noqa: E402,F401
from tests.test_stocks import stock_world  # noqa: E402,F401


def fund(isin, yahoo, **kw) -> FundRow:
    base = {"isin": isin, "yahoo": yahoo, "name": yahoo, "index_group": "aex", "domicile": "IE",
            "replication": "full", "distribution": "acc", "securities_lending": "no", "ter_pct": "0.30",
            "launch_date": "2010-01-01", "fund_size_eur_m": "500", "fund_size_date": "2026-09-30",
            "index_constituents": "25", "leveraged_inverse": "no"}
    return FundRow({**base, **kw})


def small_markets() -> MarketsConfig:
    return MarketsConfig(
        indices=[IndexEntry(slug="msci-world", name="MSCI World", yahoo="^WORLD", currency="USD", region="Wereld",
                            curve="us", world=True),
                 IndexEntry(slug="aex", name="AEX", yahoo="^AEX", currency="EUR", region="Nederland", curve="ea")],
        index_history_start="2020-01-01",
        index_groups={"aex": IndexGroup(name="AEX", index="aex", us_dividends=False)},
        bond_categories={"government": "Staatsobligaties"}, rates=[],
        etfs=[fund("IE0000000001", "AAA1.AS", ter_pct="0.30"), fund("NL0000000002", "BBB2.AS", domicile="NL",
              ter_pct="0.20", fund_size_eur_m="30"), fund("IE0000000003", "CCC3.AS", ter_pct="0.10")],
        bonds=[FundRow({"isin": "IE0000000009", "yahoo": "BND9.AS", "name": "Govt bond", "category": "government",
                        "fund_currency": "EUR", "ter_pct": "0.09", "ytm_pct": "3.0", "effective_duration": "6.5",
                        "rating_aaa": "40", "rating_aa": "40", "rating_a": "20", "as_of_date": "2026-09-30"})],
    )


def test_markets_run_stores_regime_and_grades_etfs_side_by_side(db, stock_world, model):  # noqa: F811
    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, _, _ = stock_world
    markets = small_markets()
    report = run_markets(sf, providers, cfg, markets, today=DAY)
    assert report.errors == [], report.errors
    with sf() as session:
        version_id = register_model_version(session, model).id
    regime_report = Report()
    update_regime(sf, model, version_id, DAY, DAY - timedelta(days=30), regime_report)
    rows = scalar(engine, "SELECT count(*) FROM market_regime")
    assert rows == 31
    inputs = scalar(engine, "SELECT inputs FROM market_regime ORDER BY date DESC LIMIT 1")
    assert set(inputs) == {"world_index", "high_yield_spread", "vix"}
    as_of = scalar(engine, "SELECT max(ts) FROM price_bar")
    graded = grade_markets(sf, model, version_id, markets, as_of)
    assert graded.errors == []
    from sqlalchemy import text as sql

    with engine.connect() as conn:
        snaps = {r[0]: r[1:] for r in conn.execute(sql(
            """
            SELECT a.slug, g.template_id, g.inputs->'grade_input'->'metrics'->'ongoing_charges'->>'value',
                   g.inputs->'peers'->'ongoing_charges'->>'group', g.result->'gates'
            FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id"""))}
    assert snaps["aaa1-as"][0] == "etf" and float(snaps["aaa1-as"][1]) == pytest.approx(0.003)
    assert snaps["aaa1-as"][2] == "etf:aex"                     # compared only with ETFs on the same index
    small = next(g for g in snaps["bbb2-as"][3] if g["id"] == "small_fund")
    assert small["status"] == "hit"                              # 30 million euro: at most C
    assert snaps["bnd9-as"][0] == "bond" and snaps["aex"][0] == "index"
