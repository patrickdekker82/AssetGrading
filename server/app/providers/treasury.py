"""US Treasury daily par yield curve (home.treasury.gov). Free, no key; US government data (public domain).

One CSV per calendar year with a column per maturity. Maturities that exist only in later years (1, 1.5, 2
and 4 months) are skipped: the curve uses the ones with the longest history.
"""

import csv
import io
from datetime import date, datetime

from app.providers.base import Provider, to_decimal

# CSV column -> (stored series id, maturity in years)
MATURITIES: dict[str, tuple[str, float]] = {
    "3 Mo": ("UST_3M", 0.25), "6 Mo": ("UST_6M", 0.5), "1 Yr": ("UST_1Y", 1.0), "2 Yr": ("UST_2Y", 2.0),
    "3 Yr": ("UST_3Y", 3.0), "5 Yr": ("UST_5Y", 5.0), "7 Yr": ("UST_7Y", 7.0), "10 Yr": ("UST_10Y", 10.0),
    "20 Yr": ("UST_20Y", 20.0), "30 Yr": ("UST_30Y", 30.0),
}


class TreasuryProvider(Provider):
    name = "treasury"

    def year_curve(self, year: int) -> dict[str, list[tuple[date, float, int | None]]]:
        """{series id: [(date, yield in percent, call_id)]} for one calendar year."""
        res = self.get_text(
            f"/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all",
            {"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(year), "page": "", "_format": "csv"})
        out: dict[str, list[tuple[date, float, int | None]]] = {sid: [] for sid, _ in MATURITIES.values()}
        for row in csv.DictReader(io.StringIO(res.data)):
            raw = (row.get("Date") or "").strip()
            if not raw:
                continue
            d = datetime.strptime(raw, "%m/%d/%Y").date()
            for column, (sid, _) in MATURITIES.items():
                v = to_decimal((row.get(column) or "").strip() or None)
                if v is not None:
                    out[sid].append((d, float(v), res.call_id))
        return out
