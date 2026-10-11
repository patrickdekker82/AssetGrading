"""CoinGecko (Demo plan): market data, categories and a one-year EUR price fallback.

Attribution is required ("Data van CoinGecko"), see the Bronnen page.
"""

from datetime import UTC, date, datetime, timedelta

from app.providers.base import Bar, Fact, Provider, to_decimal

DEMO_HISTORY_DAYS = 365

# Fields stored as facts from /coins/markets, with their unit.
MARKET_FACTS = {
    "market_cap": ("market_cap_eur", "eur"),
    "fully_diluted_valuation": ("fdv_eur", "eur"),
    "total_volume": ("volume_24h_eur", "eur"),
    "circulating_supply": ("circulating_supply", "tokens"),
    "total_supply": ("total_supply", "tokens"),
    "max_supply": ("max_supply", "tokens"),
}


class CoinGeckoProvider(Provider):
    name = "coingecko"

    def auth_headers(self) -> dict[str, str]:
        return {"x-cg-demo-api-key": self.api_key} if self.api_key else {}

    def markets(self, *, per_page: int = 250, page: int = 1, category: str | None = None):
        params = {"vs_currency": "eur", "order": "market_cap_desc", "per_page": per_page, "page": page}
        if category:
            params["category"] = category
        return self.get_json("/coins/markets", params)

    def coin_detail(self, coin_id: str):
        return self.get_json(
            f"/coins/{coin_id}",
            {"localization": "false", "tickers": "false", "market_data": "false",
             "community_data": "false", "developer_data": "true", "sparkline": "false"},
        )

    @staticmethod
    def market_facts(row: dict, as_of: date, call_id: int | None) -> list[Fact]:
        facts = []
        for key, (field, unit) in MARKET_FACTS.items():
            value = to_decimal(row.get(key))
            if value is not None:
                facts.append(Fact(field=field, as_of=as_of, value=value, unit=unit, call_id=call_id))
        return facts

    def get_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Daily EUR closes for a CoinGecko id. Demo history is limited to the last 365 days.

        CoinGecko's daily point at 00:00 UTC on day D is the price at the end of day D-1, so it is
        stored as the close of D-1. The extra point with the current time is dropped (unfinished day).
        """
        today = datetime.now(UTC).date()
        # days=365 returns midnight points from today-365 on; the first one is the close of today-366.
        earliest = today - timedelta(days=DEMO_HISTORY_DAYS)
        start = max(start, earliest)
        if start > end:
            return []
        days = min(DEMO_HISTORY_DAYS, (today - start).days)
        res = self.get_json(
            f"/coins/{symbol}/market_chart", {"vs_currency": "eur", "days": days, "interval": "daily"}
        )
        volumes = {int(t): v for t, v in res.data.get("total_volumes", [])}
        bars = []
        for t, price in res.data.get("prices", []):
            moment = datetime.fromtimestamp(int(t) / 1000, UTC)
            if (moment.hour, moment.minute, moment.second) != (0, 0, 0) or price is None:
                continue
            day = moment.date() - timedelta(days=1)
            if start <= day <= end:
                bars.append(
                    Bar(ts=day, close=to_decimal(price), volume=to_decimal(volumes.get(int(t))),
                        quote="EUR", call_id=res.call_id)
                )
        return bars
