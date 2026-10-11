"""FRED (Federal Reserve Bank of St. Louis). Attribution required on the Bronnen page."""

from datetime import date

from app.providers.base import Provider, ProviderError, to_decimal


class FredProvider(Provider):
    name = "fred"

    def auth_params(self) -> dict[str, str]:
        return {"api_key": self.api_key} if self.api_key else {}

    def observations(self, series_id: str, start: date) -> list[tuple[date, float, int | None]]:
        """[(date, value, call_id)]; FRED's '.' for a missing value is skipped, never filled in."""
        if not self.api_key:
            raise ProviderError("fred: FRED_API_KEY is not set")
        res = self.get_json(
            "/series/observations",
            {"series_id": series_id, "file_type": "json", "observation_start": start.isoformat()},
        )
        out = []
        for obs in res.data.get("observations", []):
            v = to_decimal(obs.get("value"))
            if v is not None:
                out.append((date.fromisoformat(obs["date"]), float(v), res.call_id))
        return out
