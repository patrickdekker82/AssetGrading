"""Coinbase Exchange public market data (no key)."""

from datetime import UTC, date, datetime, timedelta

from app.providers.base import Bar, Provider, to_decimal

MAX_CANDLES = 300


class CoinbaseProvider(Provider):
    name = "coinbase"

    def get_meta(self) -> list[dict]:
        """Online products: [{symbol, base, quote}] with symbol like BTC-USD."""
        res = self.get_json("/products")
        return [
            {"symbol": p["id"], "base": p["base_currency"], "quote": p["quote_currency"]}
            for p in res.data
            if p.get("status") == "online" and not p.get("trading_disabled")
        ]

    def get_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Completed daily bars for a product such as BTC-USD, `start` to `end` inclusive."""
        quote = symbol.split("-")[1]
        today = datetime.now(UTC).date()
        end = min(end, today - timedelta(days=1))
        bars: dict[date, Bar] = {}
        window_start = start
        while window_start <= end:
            window_end = min(end, window_start + timedelta(days=MAX_CANDLES - 1))
            res = self.get_json(
                f"/products/{symbol}/candles",
                {
                    "granularity": 86400,
                    "start": f"{window_start.isoformat()}T00:00:00Z",
                    "end": f"{window_end.isoformat()}T00:00:00Z",
                },
            )
            for t, low, high, open_, close, volume in res.data:
                day = datetime.fromtimestamp(int(t), UTC).date()
                if start <= day <= end:
                    bars[day] = Bar(
                        ts=day, open=to_decimal(open_), high=to_decimal(high), low=to_decimal(low),
                        close=to_decimal(close), volume=to_decimal(volume), quote=quote, call_id=res.call_id,
                    )
            window_start = window_end + timedelta(days=1)
        return [bars[d] for d in sorted(bars)]
