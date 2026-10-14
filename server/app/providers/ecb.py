"""ECB Data Portal (SDMX): euro area yield curves. Free, no key."""

import csv
import io
from datetime import date

from app.providers.base import Provider, ProviderError, to_decimal


class EcbProvider(Provider):
    name = "ecb"

    def observations(self, key: str, start: date) -> list[tuple[date, float, int | None]]:
        """[(date, value, call_id)] for a series key such as 'YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y'."""
        flow, series = key.split("/", 1)
        try:
            res = self.get_text(f"/service/data/{flow}/{series}",
                                {"startPeriod": start.isoformat(), "format": "csvdata"})
        except ProviderError as exc:
            if exc.not_found:   # ECB answers 404 when there is no observation in the period
                return []
            raise
        out = []
        for row in csv.DictReader(io.StringIO(res.data)):
            v = to_decimal(row.get("OBS_VALUE"))
            if v is not None and row.get("TIME_PERIOD"):
                out.append((date.fromisoformat(row["TIME_PERIOD"]), float(v), res.call_id))
        return out
