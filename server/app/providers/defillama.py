"""DefiLlama free API: TVL, fees and revenue for protocols and chains."""

from datetime import UTC, date, datetime

from app.providers.base import Fact, Provider, to_decimal


def _day(ts: int | float) -> datetime:
    return datetime.fromtimestamp(int(ts), UTC)


class DefiLlamaProvider(Provider):
    name = "defillama"

    def protocols(self) -> list[dict]:
        return self.get_json("/protocols").data

    def chains(self) -> list[dict]:
        return self.get_json("/v2/chains").data

    def protocol_tvl(self, slug: str) -> tuple[dict, list[Fact]]:
        """Daily TVL history of a protocol. Returns (protocol info, facts); unfinished day dropped."""
        res = self.get_json(f"/protocol/{slug}")
        info = {"name": res.data.get("name"), "gecko_id": res.data.get("gecko_id")}
        return info, self._daily(res.data.get("tvl") or [], "totalLiquidityUSD", "tvl_usd", res.call_id)

    def chain_tvl(self, chain: str) -> list[Fact]:
        res = self.get_json(f"/v2/historicalChainTvl/{chain}")
        return self._daily(res.data or [], "tvl", "tvl_usd", res.call_id)

    def fees(self, slug: str, data_type: str) -> tuple[dict, list[Fact]]:
        """Daily fees (dailyFees) or revenue (dailyRevenue) for a protocol or chain slug."""
        res = self.get_json(f"/summary/fees/{slug}", {"dataType": data_type})
        field = "fees_usd" if data_type == "dailyFees" else "revenue_usd"
        info = {"name": res.data.get("name"), "gecko_id": res.data.get("gecko_id")}
        facts = []
        today = datetime.now(UTC).date()
        for ts, value in res.data.get("totalDataChart") or []:
            day = _day(ts).date()
            v = to_decimal(value)
            if day < today and v is not None:
                facts.append(Fact(field=field, as_of=day, value=v, unit="usd", call_id=res.call_id))
        return info, facts

    @staticmethod
    def _daily(points: list[dict], key: str, field: str, call_id: int | None) -> list[Fact]:
        facts = []
        today: date = datetime.now(UTC).date()
        for p in points:
            moment = _day(p["date"])
            v = to_decimal(p.get(key))
            # Only midnight points are completed days; the last point is a live intraday value.
            if (moment.hour, moment.minute) == (0, 0) and moment.date() < today and v is not None:
                facts.append(Fact(field=field, as_of=moment.date(), value=v, unit="usd", call_id=call_id))
        return facts
