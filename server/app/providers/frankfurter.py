"""Frankfurter: ECB euro reference rates (published on TARGET working days around 16:00 CET)."""

from datetime import date

from app.providers.base import Provider, to_decimal


class FrankfurterProvider(Provider):
    name = "frankfurter"

    def rates(
        self, start: date, end: date, base: str, symbols: list[str]
    ) -> list[tuple[date, str, object, int | None]]:
        """[(date, quote, rate, call_id)] where 1 `base` = rate `quote`."""
        res = self.get_json(f"/{start.isoformat()}..{end.isoformat()}", {"base": base, "symbols": ",".join(symbols)})
        out = []
        for day, quotes in (res.data.get("rates") or {}).items():
            d = date.fromisoformat(day)
            if start <= d <= end:
                for quote, rate in quotes.items():
                    out.append((d, quote, to_decimal(rate), res.call_id))
        return out
