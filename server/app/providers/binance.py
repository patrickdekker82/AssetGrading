"""Binance spot market data via the public data endpoint (no key, no trading)."""

from datetime import UTC, date, datetime, timedelta

from app.providers.base import Bar, Provider, to_decimal

DAY_MS = 86_400_000


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


class BinanceProvider(Provider):
    name = "binance"

    def get_meta(self) -> list[dict]:
        """Spot symbols that are trading: [{symbol, base, quote}]."""
        res = self.get_json("/api/v3/exchangeInfo", {"permissions": "SPOT", "symbolStatus": "TRADING"})
        return [
            {"symbol": s["symbol"], "base": s["baseAsset"], "quote": s["quoteAsset"]}
            for s in res.data["symbols"]
            if s.get("status") == "TRADING"
        ]

    def get_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Completed daily bars from `start` to `end` inclusive. `symbol` is e.g. BTCUSDT."""
        quote = "USDT" if symbol.endswith("USDT") else symbol[-3:]
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        bars: list[Bar] = []
        cursor = _ms(start)
        end_ms = _ms(end + timedelta(days=1)) - 1
        while cursor <= end_ms:
            res = self.get_json(
                "/api/v3/klines",
                {"symbol": symbol, "interval": "1d", "startTime": cursor, "endTime": end_ms, "limit": 1000},
            )
            rows = res.data
            for r in rows:
                open_ms, close_ms = int(r[0]), int(r[6])
                if close_ms >= now_ms:  # still running: never use an unfinished day
                    continue
                bars.append(
                    Bar(
                        ts=datetime.fromtimestamp(open_ms / 1000, UTC).date(),
                        open=to_decimal(r[1]), high=to_decimal(r[2]), low=to_decimal(r[3]),
                        close=to_decimal(r[4]), volume=to_decimal(r[5]), quote=quote, call_id=res.call_id,
                    )
                )
            if len(rows) < 1000:
                break
            cursor = int(rows[-1][0]) + DAY_MS
        return bars
