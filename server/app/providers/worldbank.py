"""World Bank Indicators API (free, no key): yearly macro figures per country."""

from app.providers.base import Provider


class WorldBankProvider(Provider):
    name = "worldbank"

    def indicator(self, indicator: str, countries: list[str], first_year: int, last_year: int
                  ) -> list[tuple[str, int, float, int | None]]:
        """[(country code, year, value, call_id)]; years without a value are left out."""
        res = self.get_json(f"/v2/country/{';'.join(countries)}/indicator/{indicator}",
                            {"format": "json", "date": f"{first_year}:{last_year}", "per_page": 2000})
        rows = res.data[1] if isinstance(res.data, list) and len(res.data) > 1 and res.data[1] else []
        return [(r["countryiso3code"], int(r["date"]), float(r["value"]), res.call_id)
                for r in rows if r.get("value") is not None]
