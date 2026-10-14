"""EIA (US Energy Information Administration) API v2: weekly US inventories. Needs a free key (EIA_API_KEY)."""

from datetime import date

from app.providers.base import Provider, ProviderError, to_decimal

# inventory key -> (API route, series id)
SERIES = {
    "crude": ("/v2/petroleum/stoc/wstk/data/", "WCESTUS1"),          # crude oil excl. SPR, thousand barrels
    "gasoline": ("/v2/petroleum/stoc/wstk/data/", "WGTSTUS1"),
    "distillate": ("/v2/petroleum/stoc/wstk/data/", "WDISTUS1"),
    "natural_gas": ("/v2/natural-gas/stor/wkly/data/", "NW2_EPG0_SWO_R48_BCF"),
}


class EiaProvider(Provider):
    name = "eia"

    def auth_params(self) -> dict[str, str]:
        return {"api_key": self.api_key} if self.api_key else {}

    def weekly(self, key: str, start: date) -> list[tuple[date, float, int | None]]:
        if not self.api_key:
            raise ProviderError("eia: EIA_API_KEY is not set")
        route, series = SERIES[key]
        out, offset = [], 0
        while True:
            res = self.get_json(route, {"frequency": "weekly", "data[0]": "value", "facets[series][]": series,
                                        "start": start.isoformat(), "sort[0][column]": "period",
                                        "sort[0][direction]": "asc", "offset": offset, "length": 5000})
            rows = ((res.data or {}).get("response") or {}).get("data") or []
            for r in rows:
                v = to_decimal(r.get("value"))
                if v is not None:
                    out.append((date.fromisoformat(r["period"]), float(v), res.call_id))
            if len(rows) < 5000:
                return out
            offset += 5000
