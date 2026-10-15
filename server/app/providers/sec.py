"""SEC EDGAR: company list, filing metadata and XBRL company facts (free, max 10 requests per second).

SEC requires a User-Agent with a contact address (`SEC_USER_AGENT` in .env); without it SEC answers
with an error page.

Company facts are stored per financial item instead of per XBRL concept: companies switch concepts over
the years (JPMorgan reported loans under one concept until 2016 and another since), so each item lists
its concepts in order of preference and, per period, the first concept that has a value is used.
Every filed version is kept with its filing date as `available_at`, so a restated figure appears next to
the original from the day it was filed.
"""

import os
import time as clock
from collections import defaultdict
from datetime import UTC, date, datetime, time

from app.providers.base import Fact, Provider, to_decimal

# item -> concepts in preference order ("taxonomy:Concept"). Durations are stored as :3m, :6m, :9m or
# :12m (fiscal year-to-date for 6m and 9m), balance sheet values as :i.
CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:SalesRevenueNet", "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap:RevenuesNetOfInterestExpense", "ifrs-full:Revenue",
    ],
    "cost_of_revenue": [
        "us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold", "us-gaap:CostOfGoodsSold",
        "ifrs-full:CostOfSales",
    ],
    "gross_profit": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "operating_income": ["us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"],
    "pretax_income": [
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ifrs-full:ProfitLossBeforeTax",
    ],
    "income_tax": ["us-gaap:IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"],
    # ProfitLoss (including minority interests) only when the company tags nothing narrower.
    "net_income": [
        "us-gaap:NetIncomeLoss", "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic", "us-gaap:ProfitLoss",
        "ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss",
    ],
    "net_income_common": [
        "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic", "us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss",
        "ifrs-full:ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity",
        "ifrs-full:ProfitLossAttributableToOwnersOfParent",
    ],
    "income_continuing": [
        "us-gaap:IncomeLossFromContinuingOperations", "us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss",
        "ifrs-full:ProfitLossFromContinuingOperations", "ifrs-full:ProfitLoss",
    ],
    "sga": ["us-gaap:SellingGeneralAndAdministrativeExpense", "ifrs-full:SellingGeneralAndAdministrativeExpense"],
    "depreciation": [
        "us-gaap:DepreciationDepletionAndAmortization", "us-gaap:DepreciationAndAmortization",
        "us-gaap:DepreciationAmortizationAndAccretionNet", "us-gaap:Depreciation",
        "ifrs-full:DepreciationAndAmortisationExpense",
        "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense",
    ],
    "interest_expense": [
        "us-gaap:InterestExpense", "us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpenseDebt",
        "us-gaap:InterestAndDebtExpense", "ifrs-full:FinanceCosts", "ifrs-full:InterestExpense",
    ],
    "cfo": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    ],
    "capex": [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets",
        "us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "dividends_paid": [
        "us-gaap:PaymentsOfDividendsCommonStock", "us-gaap:PaymentsOfDividends",
        "ifrs-full:DividendsPaidClassifiedAsFinancingActivities", "ifrs-full:DividendsPaid",
    ],
    "buybacks": [
        "us-gaap:PaymentsForRepurchaseOfCommonStock",
        "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares",
    ],
    "share_issuance": ["us-gaap:ProceedsFromIssuanceOfCommonStock", "ifrs-full:ProceedsFromIssuingShares"],
    "diluted_shares": [
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
        "ifrs-full:AdjustedWeightedAverageShares", "ifrs-full:WeightedAverageShares",
    ],
    "eps_diluted": ["us-gaap:EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"],
    "total_assets": ["us-gaap:Assets", "ifrs-full:Assets"],
    "current_assets": ["us-gaap:AssetsCurrent", "ifrs-full:CurrentAssets"],
    "current_liabilities": ["us-gaap:LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"],
    "total_liabilities": ["us-gaap:Liabilities", "ifrs-full:Liabilities"],
    "equity": [
        "us-gaap:StockholdersEquity", "ifrs-full:EquityAttributableToOwnersOfParent",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "ifrs-full:Equity",
    ],
    "preferred_equity": ["us-gaap:PreferredStockValue", "us-gaap:PreferredStockValueOutstanding"],
    "retained_earnings": ["us-gaap:RetainedEarningsAccumulatedDeficit", "ifrs-full:RetainedEarnings"],
    "cash": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "ifrs-full:CashAndCashEquivalents",
    ],
    "receivables": [
        "us-gaap:AccountsReceivableNetCurrent", "us-gaap:ReceivablesNetCurrent",
        "ifrs-full:TradeAndOtherCurrentReceivables", "ifrs-full:CurrentTradeReceivables",
    ],
    "ppe": [
        "us-gaap:PropertyPlantAndEquipmentNet",
        "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        "ifrs-full:PropertyPlantAndEquipment",
    ],
    "goodwill": ["us-gaap:Goodwill", "ifrs-full:Goodwill"],
    "intangibles": [
        "us-gaap:IntangibleAssetsNetExcludingGoodwill", "us-gaap:FiniteLivedIntangibleAssetsNet",
        "ifrs-full:IntangibleAssetsOtherThanGoodwill",
    ],
    "long_term_debt": [
        "us-gaap:LongTermDebt", "us-gaap:LongTermDebtAndCapitalLeaseObligations",
        "us-gaap:DebtLongtermAndShorttermCombinedAmount",
    ],
    "long_term_debt_noncurrent": [
        "us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligationsNoncurrent",
        "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings", "ifrs-full:NoncurrentBorrowings",
    ],
    "long_term_debt_current": [
        "us-gaap:LongTermDebtCurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
        "ifrs-full:CurrentPortionOfNoncurrentBorrowings",
    ],
    "short_term_debt": [
        "us-gaap:ShortTermBorrowings", "us-gaap:CommercialPaper",
        "ifrs-full:CurrentBorrowings", "ifrs-full:ShorttermBorrowings",
    ],
    # Banks.
    "net_interest_income": [
        "us-gaap:InterestIncomeExpenseNet", "us-gaap:InterestIncomeExpenseAfterProvisionForLoanLoss",
        "ifrs-full:InterestIncomeExpense", "ifrs-full:NetInterestIncomeExpense",
    ],
    "noninterest_income": ["us-gaap:NoninterestIncome", "ifrs-full:FeeAndCommissionIncomeExpense"],
    "noninterest_expense": ["us-gaap:NoninterestExpense", "ifrs-full:OperatingExpense"],
    "deposits": ["us-gaap:Deposits", "ifrs-full:DepositsFromCustomers"],
    "loans": [
        "us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
        "us-gaap:LoansAndLeasesReceivableNetReportedAmount",
        "us-gaap:LoansAndLeasesReceivableNetOfDeferredIncome",
        "ifrs-full:LoansAndAdvancesToCustomers",
    ],
    # Insurers.
    "premiums_earned": ["us-gaap:PremiumsEarnedNet", "ifrs-full:InsuranceRevenue"],
    "claims_incurred": [
        "us-gaap:PolicyholderBenefitsAndClaimsIncurredNet",
        "us-gaap:LiabilityForClaimsAndClaimsAdjustmentExpenseIncurredClaims1",
    ],
}

DURATION_MONTHS = {3, 6, 9, 12}
FILING_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K"}


def _period_suffix(start: str | None, end: str) -> str | None:
    if not start:
        return "i"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    months = round(days / 30.44)
    return f"{months}m" if months in DURATION_MONTHS and abs(days - months * 30.44) < 20 else None


def _filed_at(filed: str) -> datetime:
    # EDGAR gives only the filing date; filings accepted after 17:30 ET count as the next day, so the
    # end of the filing day (UTC) is the safe moment to treat the figure as public.
    return datetime.combine(date.fromisoformat(filed), time(23, 59), tzinfo=UTC)


def parse_company_facts(data: dict, call_id: int | None, start: date | None = None) -> list[Fact]:
    """Normalise a companyfacts response into item facts (see module docstring)."""
    facts_by_tax = data.get("facts") or {}
    out: list[Fact] = []
    for item, concepts in CONCEPTS.items():
        # period key (suffix, end) -> entries of the first concept that reports it
        chosen: dict[tuple[str, str], list[tuple[dict, str]]] = {}
        for concept in concepts:
            tax, name = concept.split(":", 1)
            units = ((facts_by_tax.get(tax) or {}).get(name) or {}).get("units") or {}
            if not units:
                continue
            unit = max(units, key=lambda u: len(units[u]))  # the reporting currency or 'shares'
            per_period: dict[tuple[str, str], list[tuple[dict, str]]] = defaultdict(list)
            for e in units[unit]:
                if e.get("form") not in FILING_FORMS or e.get("val") is None or not e.get("filed"):
                    continue
                suffix = _period_suffix(e.get("start"), e["end"])
                if suffix is None or (start and date.fromisoformat(e["end"]) < start):
                    continue
                per_period[(suffix, e["end"])].append((e, unit))
            for key, entries in per_period.items():
                chosen.setdefault(key, entries)
        for (suffix, end), entries in chosen.items():
            for e, unit in sorted(entries, key=lambda x: x[0]["filed"]):
                value = to_decimal(e["val"])
                if value is None:
                    continue
                out.append(Fact(field=f"{item}:{suffix}", as_of=date.fromisoformat(end), value=value,
                                unit=unit[:20], call_id=call_id, available_at=_filed_at(e["filed"])))
    return out


class SecProvider(Provider):
    name = "sec"
    _tickers: tuple[float, list[dict]] | None = None
    TICKERS_CACHE_SECONDS = 6 * 3600

    def auth_headers(self) -> dict[str, str]:
        agent = os.environ.get("SEC_USER_AGENT") or "Graadmeter private research tool admin@example.org"
        return {"User-Agent": agent}

    def company_tickers(self) -> list[dict]:
        """All SEC-registered companies with a ticker, largest first: [{cik, ticker, title}]. Cached for six
        hours (searches use it too)."""
        if self._tickers and clock.monotonic() - self._tickers[0] < self.TICKERS_CACHE_SECONDS:
            return self._tickers[1]
        res = self.get_json("https://www.sec.gov/files/company_tickers.json")
        ordered = [res.data[k] for k in sorted(res.data or {}, key=int)]  # keys "0", "1", ... are the ranks
        rows = [{"cik": int(r["cik_str"]), "ticker": r["ticker"], "title": r["title"]} for r in ordered]
        self._tickers = (clock.monotonic(), rows)
        return rows

    def submissions(self, cik: int) -> dict:
        """Company metadata: SIC code, country, fiscal year end and recent filings."""
        res = self.get_json(f"/submissions/CIK{cik:010d}.json")
        d = res.data
        recent = (d.get("filings") or {}).get("recent") or {}
        filings = [
            {"form": f, "filed": fd, "report": rd}
            for f, fd, rd in zip(recent.get("form", []), recent.get("filingDate", []), recent.get("reportDate", []),
                                 strict=False)
            if f in FILING_FORMS
        ]
        # Form 4 insider filings in the recent list (the newest 1,000 filings of any kind).
        insider = [
            {"accession": a, "filed": fd, "accepted": acc, "primary": doc}
            for f, a, fd, acc, doc in zip(recent.get("form", []), recent.get("accessionNumber", []),
                                          recent.get("filingDate", []), recent.get("acceptanceDateTime", []),
                                          recent.get("primaryDocument", []), strict=False)
            if f == "4" and a and doc
        ]
        business = (d.get("addresses") or {}).get("business") or {}
        return {
            "cik": cik, "name": d.get("name"), "sic": int(d["sic"]) if d.get("sic") else None,
            "sic_description": d.get("sicDescription"), "tickers": d.get("tickers") or [],
            "exchanges": d.get("exchanges") or [], "fiscal_year_end": d.get("fiscalYearEnd"),
            "foreign": bool(business.get("isForeignLocation")), "country_code": business.get("countryCode"),
            "filings": filings, "insider_filings": insider, "call_id": res.call_id,
        }

    def get_fundamentals(self, symbol: str, start: date | None = None) -> list[Fact]:
        """`symbol` is the CIK as a string."""
        res = self.get_json(f"/api/xbrl/companyfacts/CIK{int(symbol):010d}.json")
        return parse_company_facts(res.data, res.call_id, start)
