"""Fundamental metrics for stocks from point-in-time SEC facts (see providers/sec.py for the items).

A *snapshot* describes the company at a period end E: flows over the twelve months up to E (trailing
twelve months, TTM) and balance sheet values at E. Metrics compare the snapshot at E with the one a year
earlier. Nothing is estimated: a metric whose inputs are missing stays empty, with two stated
conventions:

- A balance sheet item that a company has not reported for two years (goodwill, preferred shares, debt)
  counts as zero: XBRL filers leave out items they do not have.
- EBIT is the reported operating income, or pre-tax income plus interest expense when none is tagged.
- Beneish M: the depreciation and SG&A indices count as 1 (no change) when a company does not report
  those lines; the other six indices are required.
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

TOLERANCE_DAYS = 12        # 52/53-week fiscal years end on slightly different dates
MAX_AGE_DAYS = 550         # annual filers: the last report may be ~16 months old before the next one
ZERO_IF_ABSENT_DAYS = 730

FLOW_ITEMS = [
    "revenue", "cost_of_revenue", "gross_profit", "operating_income", "pretax_income", "income_tax",
    "net_income", "net_income_common", "income_continuing", "sga", "depreciation", "interest_expense", "cfo",
    "capex", "dividends_paid", "buybacks", "share_issuance", "net_interest_income", "noninterest_income",
    "noninterest_expense", "premiums_earned", "claims_incurred",
]
INSTANT_ITEMS = [
    "total_assets", "current_assets", "current_liabilities", "total_liabilities", "equity", "retained_earnings",
    "cash", "receivables", "ppe", "deposits", "loans",
]
OPTIONAL_INSTANTS = ["preferred_equity", "goodwill", "intangibles", "long_term_debt", "long_term_debt_noncurrent",
                     "long_term_debt_current", "short_term_debt"]
OPTIONAL_FLOWS = ["dividends_paid", "buybacks", "share_issuance"]


def _near(series: dict[date, float], target: date, tol: int = TOLERANCE_DAYS) -> float | None:
    best, best_gap = None, tol + 1
    for d, v in series.items():
        gap = abs((d - target).days)
        if gap < best_gap:
            best, best_gap = v, gap
    return best


@dataclass
class FactTable:
    """Latest known value per (item:period, period end)."""

    values: dict[str, dict[date, float]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows) -> "FactTable":
        """`rows`: (field, as_of, value) in order of availability; a later version replaces an earlier one."""
        t = cls()
        for f, d, v in rows:
            t.values.setdefault(f, {})[d] = float(v)
        return t

    def get(self, key: str, end: date) -> float | None:
        s = self.values.get(key)
        return _near(s, end) if s else None

    def ttm(self, item: str, end: date) -> float | None:
        v = self.get(f"{item}:12m", end)
        if v is not None:
            return v
        for k in (9, 6, 3):
            ytd = self.get(f"{item}:{k}m", end)
            if ytd is None:
                continue
            fy = self.get(f"{item}:12m", end - timedelta(days=round(k * 30.44)))
            prior = self.get(f"{item}:{k}m", end - timedelta(days=365))
            if fy is not None and prior is not None:
                return ytd + fy - prior
            return None
        return None

    def optional_instant(self, item: str, end: date) -> float | None:
        s = self.values.get(f"{item}:i") or {}
        v = _near(s, end)
        if v is not None:
            return v
        recent = [d for d in s if end - timedelta(days=ZERO_IF_ABSENT_DAYS) <= d <= end]
        return None if recent else 0.0

    def optional_flow(self, item: str, end: date) -> float | None:
        v = self.ttm(item, end)
        if v is not None:
            return v
        recent = [d for k, s in self.values.items() if k.startswith(f"{item}:") for d in s
                  if end - timedelta(days=ZERO_IF_ABSENT_DAYS) <= d <= end]
        return None if recent else 0.0

    def shares(self, end: date) -> float | None:
        """Diluted share count for the period ending at `end`. Checked against net income / diluted EPS of the
        same period: that also covers companies that tag no share count (several share classes) and fixes a
        count tagged in thousands or millions."""
        for k in ("3m", "12m", "6m", "9m"):
            reported = self.get(f"diluted_shares:{k}", end)
            ni, eps = self.get(f"net_income_common:{k}", end), self.get(f"eps_diluted:{k}", end)
            implied = ni / eps if ni and eps and ni / eps > 0 else None
            if reported and implied:
                ratio = implied / reported
                if ratio > 500:
                    return reported * 1000 ** round(math.log(ratio, 1000))
                return reported
            if reported or implied:
                return reported or implied
        return None

    def period_ends(self, as_of: date) -> list[date]:
        """Balance sheet dates up to `as_of`, newest first."""
        return sorted((d for d in (self.values.get("total_assets:i") or {}) if d <= as_of), reverse=True)

    def annual(self, item: str, as_of: date) -> list[tuple[date, float]]:
        return sorted((d, v) for d, v in (self.values.get(f"{item}:12m") or {}).items() if d <= as_of)


@dataclass
class Snapshot:
    end: date
    v: dict[str, float | None]

    def __getitem__(self, k: str) -> float | None:
        return self.v.get(k)


def snapshot(t: FactTable, end: date) -> Snapshot:
    v: dict[str, float | None] = {i: t.ttm(i, end) for i in FLOW_ITEMS}
    for i in OPTIONAL_FLOWS:
        v[i] = t.optional_flow(i, end)
    for i in INSTANT_ITEMS:
        v[i] = t.get(f"{i}:i", end)
    for i in OPTIONAL_INSTANTS:
        v[i] = t.optional_instant(i, end)
    if v["gross_profit"] is None and v["revenue"] is not None and v["cost_of_revenue"] is not None:
        v["gross_profit"] = v["revenue"] - v["cost_of_revenue"]
    if v["operating_income"] is None and v["pretax_income"] is not None and v["interest_expense"] is not None:
        # EBIT by its definition (earnings before interest and taxes) when no operating income is tagged.
        v["operating_income"] = v["pretax_income"] + v["interest_expense"]
        v["ebit_derived"] = 1.0
    if v["total_liabilities"] is None and v["total_assets"] is not None and v["equity"] is not None:
        v["total_liabilities"] = v["total_assets"] - v["equity"]
    ltd = v["long_term_debt"] or 0.0
    if not ltd:
        ltd = (v["long_term_debt_noncurrent"] or 0.0) + (v["long_term_debt_current"] or 0.0)
    parts = [v["long_term_debt"], v["long_term_debt_noncurrent"], v["short_term_debt"]]
    v["debt"] = None if all(p is None for p in parts) else ltd + (v["short_term_debt"] or 0.0)
    v["long_term_debt_total"] = ltd if v["debt"] is not None else None
    v["shares"] = t.shares(end)
    return Snapshot(end, v)


def current_and_prior(t: FactTable, as_of: date) -> tuple[Snapshot | None, Snapshot | None]:
    """The newest period end with a balance sheet and a TTM net income, and the snapshot a year before."""
    for end in t.period_ends(as_of):
        if (as_of - end).days > MAX_AGE_DAYS:
            break
        cur = snapshot(t, end)
        if cur["net_income"] is None or cur["total_assets"] is None:
            continue
        prior_end = next((d for d in t.period_ends(end - timedelta(days=365 - TOLERANCE_DAYS))
                          if abs((end - timedelta(days=365) - d).days) <= TOLERANCE_DAYS), None)
        return cur, snapshot(t, prior_end) if prior_end else None
    return None, None


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    r = a / b
    return r if math.isfinite(r) else None


# --- published formulas -------------------------------------------------------------------------

def altman_z(working_capital: float, retained_earnings: float, ebit: float, market_value_equity: float,
             sales: float, total_assets: float, total_liabilities: float) -> float:
    """Altman (1968), original formula for listed manufacturers:
    Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5."""
    return (1.2 * working_capital / total_assets + 1.4 * retained_earnings / total_assets
            + 3.3 * ebit / total_assets + 0.6 * market_value_equity / total_liabilities
            + 1.0 * sales / total_assets)


@dataclass(frozen=True)
class BeneishYear:
    sales: float
    cogs: float
    receivables: float
    current_assets: float
    ppe: float
    total_assets: float
    current_liabilities: float
    long_term_debt: float
    depreciation: float | None = None
    sga: float | None = None
    net_income_continuing: float = 0.0
    cfo: float = 0.0


def beneish_indices(t: BeneishYear, p: BeneishYear) -> dict[str, float]:
    gm_t, gm_p = (t.sales - t.cogs) / t.sales, (p.sales - p.cogs) / p.sales
    idx = {
        "DSRI": (t.receivables / t.sales) / (p.receivables / p.sales),
        "GMI": gm_p / gm_t,
        "AQI": (1 - (t.current_assets + t.ppe) / t.total_assets) / (1 - (p.current_assets + p.ppe) / p.total_assets),
        "SGI": t.sales / p.sales,
        "DEPI": 1.0,
        "SGAI": 1.0,
        "LVGI": ((t.current_liabilities + t.long_term_debt) / t.total_assets)
                / ((p.current_liabilities + p.long_term_debt) / p.total_assets),
        "TATA": (t.net_income_continuing - t.cfo) / t.total_assets,
    }
    if None not in (t.depreciation, p.depreciation):
        idx["DEPI"] = (p.depreciation / (p.depreciation + p.ppe)) / (t.depreciation / (t.depreciation + t.ppe))
    if None not in (t.sga, p.sga):
        idx["SGAI"] = (t.sga / t.sales) / (p.sga / p.sales)
    return idx


def beneish_m(t: BeneishYear, p: BeneishYear) -> float:
    """Beneish (1999), eight-variable model:
    M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI."""
    i = beneish_indices(t, p)
    return (-4.84 + 0.920 * i["DSRI"] + 0.528 * i["GMI"] + 0.404 * i["AQI"] + 0.892 * i["SGI"]
            + 0.115 * i["DEPI"] - 0.172 * i["SGAI"] + 4.679 * i["TATA"] - 0.327 * i["LVGI"])


def piotroski_f(c: Snapshot, p: Snapshot, p2_assets: float | None) -> tuple[float | None, int]:
    """Piotroski (2000) F-score, nine binary signals. Returns (score, signals available); with eight of nine
    signals the score is scaled to nine, with fewer it is empty."""
    roa_c = _div(c["net_income"], p["total_assets"])
    roa_p = _div(p["net_income"], p2_assets)
    signals = [
        None if roa_c is None else roa_c > 0,
        None if c["cfo"] is None else c["cfo"] > 0,
        None if roa_c is None or roa_p is None else roa_c > roa_p,
        None if c["cfo"] is None or c["net_income"] is None else c["cfo"] > c["net_income"],
    ]
    lev_c = _div(c["long_term_debt_total"], c["total_assets"])
    lev_p = _div(p["long_term_debt_total"], p["total_assets"])
    signals.append(None if lev_c is None or lev_p is None else lev_c <= lev_p)
    cr_c = _div(c["current_assets"], c["current_liabilities"])
    cr_p = _div(p["current_assets"], p["current_liabilities"])
    signals.append(None if cr_c is None or cr_p is None else cr_c > cr_p)
    signals.append(None if not c["shares"] or not p["shares"] else c["shares"] <= p["shares"] * 1.005)
    gm_c, gm_p = _div(c["gross_profit"], c["revenue"]), _div(p["gross_profit"], p["revenue"])
    signals.append(None if gm_c is None or gm_p is None else gm_c > gm_p)
    at_c, at_p = _div(c["revenue"], p["total_assets"]), _div(p["revenue"], p2_assets)
    signals.append(None if at_c is None or at_p is None else at_c > at_p)
    known = [s for s in signals if s is not None]
    if len(known) < 8:
        return None, len(known)
    return sum(known) * 9 / len(known), len(known)


# --- metric sets --------------------------------------------------------------------------------

@dataclass
class FundamentalResult:
    values: dict[str, float] = field(default_factory=dict)
    raw: dict[str, float | None] = field(default_factory=dict)
    period_end: date | None = None
    notes: list[str] = field(default_factory=list)

    def set(self, k: str, v: float | None) -> None:
        if v is not None and math.isfinite(v):
            self.values[k] = float(v)


def valuation_inputs(c: Snapshot) -> dict[str, float | None]:
    """The parts of the valuation metrics that change only with a new filing (market value aside)."""
    ebit = c["operating_income"]
    fcf = None if c["cfo"] is None or c["capex"] is None else c["cfo"] - c["capex"]
    payout = None
    if c["dividends_paid"] is not None and c["buybacks"] is not None:
        payout = c["dividends_paid"] + c["buybacks"] - (c["share_issuance"] or 0.0)
    tce = None
    if c["equity"] is not None:
        tce = c["equity"] - (c["preferred_equity"] or 0) - (c["goodwill"] or 0) - (c["intangibles"] or 0)
    net_debt = None if c["debt"] is None or c["cash"] is None else c["debt"] - c["cash"]
    return {"ebit": ebit, "fcf": fcf, "payout": payout, "dividends": c["dividends_paid"],
            "earnings": c["net_income_common"], "net_debt": net_debt, "tce": tce, "shares": c["shares"]}


def valuation_metrics(vi: dict[str, float | None], market_value: float | None) -> dict[str, float | None]:
    mv = market_value if market_value and market_value > 0 else None
    ev = None if mv is None or vi["net_debt"] is None else mv + vi["net_debt"]
    rotce = _div(vi["earnings"], vi["tce"]) if (vi["tce"] or 0) > 0 else None
    ptbv = _div(mv, vi["tce"]) if (vi["tce"] or 0) > 0 else None
    return {
        "ebit_to_ev": _div(vi["ebit"], ev) if ev and ev > 0 else None,
        "fcf_yield": _div(vi["fcf"], mv),
        "shareholder_yield": _div(vi["payout"], mv),
        "earnings_yield": _div(vi["earnings"], mv),
        "dividend_yield": _div(vi["dividends"], mv),
        "ptbv_vs_rotce": _div(rotce, ptbv) if rotce is not None and ptbv else None,
    }


def fundamental_metrics(t: FactTable, as_of: date, market_value: float | None) -> FundamentalResult:
    """All fundamental metrics known at `as_of`; `market_value` is in the reporting currency."""
    out = FundamentalResult()
    c, p = current_and_prior(t, as_of)
    if c is None:
        out.notes.append("geen recente jaar- of kwartaalcijfers")
        return out
    out.period_end = c.end
    if c["ebit_derived"]:
        out.notes.append("EBIT = winst voor belasting + rentelasten (geen bedrijfsresultaat gerapporteerd)")
    vi = valuation_inputs(c)
    for k, v in valuation_metrics(vi, market_value).items():
        out.set(k, v)
    ebit, ta = c["operating_income"], c["total_assets"]
    out.raw.update({"revenue_ttm": c["revenue"], "ebit_ttm": ebit, "net_income_ttm": c["net_income"],
                    "total_assets": ta, "debt": c["debt"], "cash": c["cash"], "market_value": market_value,
                    "shares": c["shares"]})
    out.set("gross_profit_to_assets", _div(c["gross_profit"], ta))
    if c["pretax_income"] and c["pretax_income"] > 0 and c["income_tax"] is not None and ebit is not None:
        tax = min(max(c["income_tax"] / c["pretax_income"], 0.0), 0.5)
        invested = None if None in (c["equity"], c["debt"], c["cash"]) else c["equity"] + c["debt"] - c["cash"]
        if invested and invested > 0:
            out.set("roic", ebit * (1 - tax) / invested)
    if c["net_income"] is not None and c["cfo"] is not None:
        out.set("accruals", _div(c["net_income"] - c["cfo"], ta))
    ebitda = None if ebit is None or c["depreciation"] is None else ebit + c["depreciation"]
    if ebitda and ebitda > 0 and vi["net_debt"] is not None:
        out.set("net_debt_to_ebitda", vi["net_debt"] / ebitda)
    if c["interest_expense"] and c["interest_expense"] > 0 and ebit is not None:
        out.set("interest_coverage", ebit / c["interest_expense"])
    if None not in (c["current_assets"], c["current_liabilities"], c["retained_earnings"], ebit, c["revenue"],
                    c["total_liabilities"], market_value) and ta and c["total_liabilities"]:
        out.set("altman_z", altman_z(c["current_assets"] - c["current_liabilities"], c["retained_earnings"], ebit,
                                     market_value, c["revenue"], ta, c["total_liabilities"]))
    # Banks and insurers.
    if c["net_interest_income"] is not None:
        out.set("net_interest_margin", _div(c["net_interest_income"], ta))
        if c["noninterest_expense"] is not None and c["noninterest_income"] is not None:
            out.set("cost_income_ratio", _div(c["noninterest_expense"],
                                              c["net_interest_income"] + c["noninterest_income"]))
    out.set("loan_to_deposit", _div(c["loans"], c["deposits"]))
    if (vi["tce"] or 0) > 0:
        out.set("rotce", _div(vi["earnings"], vi["tce"]))
    _stability_and_growth(out, t, c, as_of)
    if p is None:
        out.notes.append("geen cijfers van een jaar eerder: vergelijkingen ontbreken")
        return out
    out.set("asset_growth", _div(ta, p["total_assets"]) - 1 if _div(ta, p["total_assets"]) else None)
    out.set("revenue_growth", _div(c["revenue"], p["revenue"]) - 1 if _div(c["revenue"], p["revenue"]) else None)
    eps_c, eps_p = _div(c["net_income_common"], c["shares"]), _div(p["net_income_common"], p["shares"])
    if eps_c is not None and eps_p is not None and eps_p > 0:
        out.set("earnings_growth", eps_c / eps_p - 1)
    p2_end = next((d for d in t.period_ends(p.end - timedelta(days=365 - TOLERANCE_DAYS))
                   if abs((p.end - timedelta(days=365) - d).days) <= TOLERANCE_DAYS), None)
    p2_assets = t.get("total_assets:i", p2_end) if p2_end else None
    score, n = piotroski_f(c, p, p2_assets)
    out.set("piotroski_f", score)
    out.raw["piotroski_signals"] = n
    _beneish(out, c, p)
    return out


def _beneish_year(s: Snapshot) -> BeneishYear | None:
    need = ["revenue", "receivables", "current_assets", "ppe", "total_assets", "current_liabilities",
            "income_continuing", "cfo"]
    cogs = s["cost_of_revenue"]
    if cogs is None and s["revenue"] is not None and s["gross_profit"] is not None:
        cogs = s["revenue"] - s["gross_profit"]
    if any(s[k] is None for k in need) or cogs is None or s["long_term_debt_total"] is None:
        return None
    return BeneishYear(sales=s["revenue"], cogs=cogs, receivables=s["receivables"], current_assets=s["current_assets"],
                       ppe=s["ppe"], total_assets=s["total_assets"], current_liabilities=s["current_liabilities"],
                       long_term_debt=s["long_term_debt_total"], depreciation=s["depreciation"], sga=s["sga"],
                       net_income_continuing=s["income_continuing"], cfo=s["cfo"])


def _beneish(out: FundamentalResult, c: Snapshot, p: Snapshot) -> None:
    yt, yp = _beneish_year(c), _beneish_year(p)
    if yt is None or yp is None:
        return
    try:
        out.set("beneish_m", beneish_m(yt, yp))
    except ZeroDivisionError:
        return
    if None in (yt.depreciation, yp.depreciation, yt.sga, yp.sga):
        out.notes.append("Beneish: afschrijving of verkoopkosten niet gerapporteerd, die index telt als 1")


def _stability_and_growth(out: FundamentalResult, t: FactTable, c: Snapshot, as_of: date) -> None:
    revenue = dict(t.annual("revenue", c.end))
    ebit = dict(t.annual("operating_income", c.end))
    margins = [ebit[d] / revenue[d] for d in sorted(revenue)[-5:] if d in ebit and revenue[d]]
    if len(margins) >= 3:
        out.set("margin_stability", 1 / (1 + statistics.stdev(margins) * 100))
    years = sorted(revenue)[-6:]
    eps = dict(t.annual("eps_diluted", c.end))
    rev_up = [revenue[b] > revenue[a] for a, b in zip(years, years[1:], strict=False)]
    eps_years = [d for d in years if d in eps]
    eps_up = [eps[b] > eps[a] for a, b in zip(eps_years, eps_years[1:], strict=False)]
    if len(rev_up) >= 3 and len(eps_up) >= 3:
        out.set("growth_consistency", (sum(rev_up) / len(rev_up) + sum(eps_up) / len(eps_up)) / 2)
