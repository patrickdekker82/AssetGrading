"""Perpetual futures: funding rates and open interest (Binance futures, Bybit, OKX).

Funding history at these venues is short, so the app archives a daily mean every night.
Rates are per funding interval (usually 8 hours) as published.
"""

from datetime import UTC, date, datetime

from app.providers.base import Provider, ProviderError, to_decimal


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _moment(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, UTC)


class PerpProvider(Provider):
    """Common interface: perp_bases(), funding_history(base, start), open_interest_usd(base)."""

    def perp_bases(self) -> set[str]:
        raise NotImplementedError

    def funding_history(self, base: str, start: date) -> list[tuple[datetime, float, int | None]]:
        raise NotImplementedError

    def open_interest_usd(self, base: str) -> tuple[float | None, int | None]:
        raise NotImplementedError


class BinanceFuturesProvider(PerpProvider):
    name = "binance_futures"

    def perp_bases(self) -> set[str]:
        res = self.get_json("/fapi/v1/exchangeInfo")
        return {s["baseAsset"] for s in res.data["symbols"]
                if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"}

    def funding_history(self, base: str, start: date):
        out = []
        cursor = _ms(start)
        while True:
            res = self.get_json("/fapi/v1/fundingRate", {"symbol": f"{base}USDT", "startTime": cursor, "limit": 1000})
            for r in res.data:
                out.append((_moment(r["fundingTime"]), float(r["fundingRate"]), res.call_id))
            if len(res.data) < 1000:
                return out
            cursor = int(res.data[-1]["fundingTime"]) + 1

    def open_interest_usd(self, base: str):
        res = self.get_json("/futures/data/openInterestHist", {"symbol": f"{base}USDT", "period": "1d", "limit": 1})
        if not res.data:
            return None, res.call_id
        return float(res.data[-1]["sumOpenInterestValue"]), res.call_id


class BybitProvider(PerpProvider):
    name = "bybit"

    def perp_bases(self) -> set[str]:
        res = self.get_json("/v5/market/instruments-info", {"category": "linear", "limit": 1000})
        return {i["baseCoin"] for i in res.data["result"]["list"]
                if i.get("quoteCoin") == "USDT" and i.get("contractType") == "LinearPerpetual"
                and i.get("status") == "Trading"}

    def funding_history(self, base: str, start: date):
        out = []
        end_ms = None
        while True:
            params = {"category": "linear", "symbol": f"{base}USDT", "startTime": _ms(start), "limit": 200}
            if end_ms:
                params["endTime"] = end_ms
            res = self.get_json("/v5/market/funding/history", params)
            rows = res.data["result"]["list"]  # newest first
            for r in rows:
                out.append((_moment(r["fundingRateTimestamp"]), float(r["fundingRate"]), res.call_id))
            if len(rows) < 200:
                return out
            end_ms = int(rows[-1]["fundingRateTimestamp"]) - 1

    def open_interest_usd(self, base: str):
        res = self.get_json("/v5/market/tickers", {"category": "linear", "symbol": f"{base}USDT"})
        rows = res.data["result"]["list"]
        value = to_decimal(rows[0].get("openInterestValue")) if rows else None
        return (float(value) if value is not None else None), res.call_id


class OkxProvider(PerpProvider):
    name = "okx"
    MAX_PAGES = 4   # about three months of 8-hour funding

    def get_json(self, path, params=None, *, cost=1):
        res = super().get_json(path, params, cost=cost)
        if isinstance(res.data, dict) and res.data.get("code") not in (None, "0"):
            raise ProviderError(f"okx {path}: {res.data.get('msg')}", 400)
        return res

    def perp_bases(self) -> set[str]:
        res = self.get_json("/api/v5/public/instruments", {"instType": "SWAP"})
        return {i["instId"].split("-")[0] for i in res.data["data"]
                if i["instId"].endswith("-USDT-SWAP") and i.get("state") == "live"}

    def funding_history(self, base: str, start: date):
        out = []
        after = None
        for _ in range(self.MAX_PAGES):
            params = {"instId": f"{base}-USDT-SWAP", "limit": 100}
            if after:
                params["after"] = after
            res = self.get_json("/api/v5/public/funding-rate-history", params)
            rows = res.data["data"]  # newest first
            for r in rows:
                moment = _moment(r["fundingTime"])
                if moment.date() >= start:
                    out.append((moment, float(r.get("realizedRate") or r["fundingRate"]), res.call_id))
            if len(rows) < 100 or not rows or _moment(rows[-1]["fundingTime"]).date() < start:
                break
            after = rows[-1]["fundingTime"]
        return out

    def open_interest_usd(self, base: str):
        res = self.get_json("/api/v5/public/open-interest", {"instType": "SWAP", "instId": f"{base}-USDT-SWAP"})
        rows = res.data["data"]
        return (float(rows[0]["oiUsd"]) if rows else None), res.call_id


def daily_mean_funding(
    events: list[tuple[datetime, float, int | None]], before: date
) -> dict[date, tuple[float, int | None]]:
    """Mean funding rate per completed UTC day (days before `before`)."""
    per_day: dict[date, list[float]] = {}
    calls: dict[date, int | None] = {}
    for moment, rate, call_id in events:
        d = moment.date()
        if d < before:
            per_day.setdefault(d, []).append(rate)
            calls[d] = call_id
    return {d: (sum(v) / len(v), calls[d]) for d, v in per_day.items()}


