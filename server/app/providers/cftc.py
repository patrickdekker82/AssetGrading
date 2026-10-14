"""CFTC Commitments of Traders (public reporting API, free). Positions as of Tuesday, published on Friday.

- Disaggregated report (commodities): managed money = the speculators.
- Traders in Financial Futures (currencies): leveraged funds = the speculators.
The stored value is the speculators' net position as a share of open interest.
"""

from datetime import date

from app.providers.base import Provider, to_decimal

REPORTS = {
    "disaggregated": ("72hh-3qpy", "m_money_positions_long_all", "m_money_positions_short_all"),
    "financial": ("gpe5-46if", "lev_money_positions_long", "lev_money_positions_short"),
}


class CftcProvider(Provider):
    name = "cftc"

    def net_positions(self, report: str, code: str, start: date) -> list[tuple[date, float, int | None]]:
        """[(report date, net speculative position / open interest, call_id)]."""
        dataset, long_col, short_col = REPORTS[report]
        res = self.get_json(f"/resource/{dataset}.json", {
            "cftc_contract_market_code": code,
            "$where": f"report_date_as_yyyy_mm_dd >= '{start.isoformat()}T00:00:00'",
            "$order": "report_date_as_yyyy_mm_dd", "$limit": 5000,
            "$select": f"report_date_as_yyyy_mm_dd,{long_col},{short_col},open_interest_all",
        })
        out = []
        for r in res.data or []:
            long_, short, oi = (to_decimal(r.get(k)) for k in (long_col, short_col, "open_interest_all"))
            if long_ is None or short is None or not oi:
                continue
            out.append((date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10]), float((long_ - short) / oi),
                        res.call_id))
        return out
