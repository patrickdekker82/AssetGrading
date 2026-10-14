"""Commodities, ETC products and currency pairs."""

from datetime import date, timedelta

import pandas as pd
import pytest

from app.commodities_config import CommodityEntry, FxPair
from app.grading.commodities import curve_slope, inventory_z, mirror
from app.grading.crypto import Prepared, build_inputs
from app.grading.crypto_inputs import Metrics
from app.grading.engine import GradeInput, MetricInput, grade
from app.ingest.commodities import contract_candidates

DAY = date(2026, 10, 13)


@pytest.fixture
def model(config_dir):
    from app.modelconfig import load_model_config

    return load_model_config(config_dir / "model")


def test_contract_candidates_follow_the_listed_months():
    gold = CommodityEntry(slug="gold", name="Goud", template="precious_metal", group="Edelmetalen", front="GC=F",
                          root="GC", exchange="CMX", months="GJMQVZ")
    symbols = [s for s, _ in contract_candidates(gold, DAY)][:4]
    assert symbols == ["GCV26.CMX", "GCZ26.CMX", "GCG27.CMX", "GCJ27.CMX"]


def facts(f1, f2, m1, m2) -> dict:
    return {k: pd.Series([v], index=[DAY]) for k, v in
            {"curve_f1": f1, "curve_f2": f2, "curve_f1_month": m1, "curve_f2_month": m2}.items()}


def test_curve_slope_backwardation_is_positive_and_annualised():
    # Two months apart, 2% lower: ln(100/98) * 12 / 2 = 0.1212
    slope, _ = curve_slope(facts(100.0, 98.0, 202611, 202701), DAY)
    assert slope == pytest.approx(0.12121, abs=1e-4)
    contango, _ = curve_slope(facts(98.0, 100.0, 202612, 202702), DAY)
    assert contango < 0
    assert curve_slope(facts(100.0, 98.0, 202611, 202611), DAY) is None


def test_inventory_against_the_same_weeks_of_five_years():
    days = [DAY - timedelta(weeks=w) for w in range(0, 6 * 52 + 2)]
    values = [100.0 + (5 if d.year < DAY.year and d.isocalendar()[1] % 2 else 0) for d in days]
    s = pd.Series(values, index=days).sort_index()
    s.iloc[-1] = 130.0        # far above the seasonal average
    z, when = inventory_z(s, DAY)
    assert when == DAY and z > 3


def fx_metrics(carry, mom, reer, tech) -> Metrics:
    m = Metrics()
    m.set("carry_to_vol", carry, "test")
    m.set("fx_momentum_3_12m", mom, "test")
    m.set("reer_deviation", reer, "test")
    m.set("rate_path", carry / 2, "test")
    m.set("technical_score", tech, "test")
    m.set("fx_vol_or_vix_percentile", 40.0, "test")
    m.flags["pegged_or_capital_controls"] = False
    return m


def test_currency_pairs_are_exact_mirrors(model):
    pairs = [("eur-usd", fx_metrics(0.3, 0.04, -0.05, 72.0)), ("eur-gbp", fx_metrics(-0.2, -0.01, 0.02, 41.0)),
             ("usd-jpy", fx_metrics(0.8, 0.06, 0.10, 65.0)), ("eur-chf", fx_metrics(0.5, -0.02, -0.08, 30.0))]
    prepared, ids = [], 0
    for slug, m in pairs:
        ids += 1
        prepared.append(Prepared(ids, slug, "fx_pair", [], m))
        ids += 1
        inverse = "-".join(reversed(slug.split("-")))
        prepared.append(Prepared(ids, inverse, "fx_pair", [], mirror(m)))
    inputs = build_inputs(prepared, model, DAY)
    scores = {p.key: grade(inputs[p.asset_id][0], model) for p in prepared}
    for slug, _ in pairs:
        inverse = "-".join(reversed(slug.split("-")))
        a, b = scores[slug], scores[inverse]
        assert a.score + b.score == pytest.approx(100.0, abs=1e-9), slug
        assert a.coverage == b.coverage
    assert FxPair("EUR", "USD").inverse().slug == "usd-eur"


def product_input(**metrics) -> GradeInput:
    mi = {k: MetricInput(value=v, peer_pct=60.0) for k, v in metrics.items()}
    return GradeInput(template_id="commodity", tags=[], metrics=mi, product=True,
                      flags={"leveraged_or_inverse": False, "uncollateralized_note": False})


def test_product_judgement_and_roll_loss_gate(model):
    ok = grade(product_input(replication_physical=0.0, collateral_score=0.8, ongoing_charges=0.0049,
                             roll_yield_12m=-0.03), model)
    assert ok.status == "graded" and ok.pillars[0].id == "product"
    bad = grade(product_input(replication_physical=0.0, collateral_score=0.8, ongoing_charges=0.0049,
                              roll_yield_12m=-0.15), model)
    assert "roll_loss" in [g.id for g in bad.gates if g.status == "hit"]
    assert bad.letter in ("C", "C-", "D+", "D", "D-", "F")


def test_uncollateralized_product_is_capped(model):
    inp = product_input(replication_physical=0.0, collateral_score=0.0, ongoing_charges=0.001, roll_yield_12m=0.02)
    inp.flags["uncollateralized_note"] = True
    for k in inp.metrics.values():
        k.peer_pct = 95.0
    res = grade(inp, model)
    assert "uncollateralized" in [g.id for g in res.gates if g.status == "hit"]
    assert res.letter == "B-"


# --- the commodities run end to end ---------------------------------------------------------------

from app.commodities_config import CommoditiesConfig, CurrencyEntry  # noqa: E402
from app.grading.commodities import grade_commodities  # noqa: E402
from app.ingest.commodities import run_commodities  # noqa: E402
from app.markets_config import FundRow  # noqa: E402
from tests.test_ingest import db, scalar  # noqa: E402,F401
from tests.test_stocks import TODAY, stock_world  # noqa: E402,F401


def small_config() -> CommoditiesConfig:
    gold = CommodityEntry(slug="gold", name="Goud", template="precious_metal", group="Edelmetalen", front="GC=F",
                          root="GC", exchange="CMX", months="FGHJKMNQUVXZ", cftc="088691")
    wti = CommodityEntry(slug="wti", name="WTI", template="commodity", group="Energie", front="CL=F", root="CL",
                         exchange="NYM", months="FGHJKMNQUVXZ", cftc="067651", eia="crude")
    etc = FundRow({"isin": "JE0000000001", "yahoo": "CRUD.L", "name": "WTI ETC", "commodity": "wti",
                   "structure": "futures", "collateralized": "yes", "ter_pct": "0.54", "domicile": "JE",
                   "verified_on": "2026-10-14", "leveraged_inverse": "no"})
    currencies = {"EUR": CurrencyEntry(rates=["DGS2"], worldbank="EMU", cftc="099741"),
                  "USD": CurrencyEntry(rates=["DGS10"], worldbank="USA"),
                  "GBP": CurrencyEntry(rates=["DGS2"], worldbank="GBR", cftc="096742")}
    return CommoditiesConfig([gold, wti], "2023-01-01", [FxPair("EUR", "USD"), FxPair("EUR", "GBP")], currencies,
                             [etc])


def test_commodities_run_grades_commodity_product_and_mirrored_pairs(db, stock_world, model):  # noqa: F811
    from sqlalchemy import text as sql

    from app.registry import register_model_version

    engine, sf = db
    cfg, providers, _, _ = stock_world
    cc = small_config()
    report = run_commodities(sf, providers, cfg, cc, today=TODAY)
    assert report.errors == [], report.errors
    assert scalar(engine, "SELECT count(*) FROM asset WHERE asset_class = 'fx'") == 4
    assert scalar(engine, "SELECT count(*) FROM fundamental_fact WHERE field = 'curve_f2'") == 2
    with sf() as session:
        version_id = register_model_version(session, model).id
    as_of = scalar(engine, "SELECT max(ts) FROM price_bar b JOIN asset a ON a.id = b.asset_id "
                           "WHERE a.asset_class = 'fx'")
    graded = grade_commodities(sf, model, version_id, cc, as_of)
    assert graded.errors == []
    with engine.connect() as conn:
        rows = {r[0]: r[1:] for r in conn.execute(sql(
            "SELECT a.slug, g.score, g.template_id, g.result->'pillars'->0->>'id' FROM grade_snapshot g "
            "JOIN asset a ON a.id = g.asset_id"))}
    assert rows["eur-usd"][0] + rows["usd-eur"][0] == pytest.approx(100.0, abs=1e-6)
    assert rows["eur-gbp"][0] + rows["gbp-eur"][0] == pytest.approx(100.0, abs=1e-6)
    assert rows["crud-l"][1] == "commodity" and rows["crud-l"][2] == "product"     # the product judgement
    assert rows["wti"][2] != "product" and rows["gold"][1] == "precious_metal"
