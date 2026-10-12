"""Daily stock prices: Tiingo (key), EODHD (key, optional) and Yahoo Finance (no key; unofficial, used as
the fallback the build plan allows).

Every adapter returns `PriceSeries`: bars adjusted for splits and dividends (used for charts, momentum,
beta and volatility) and the closes as traded (used for market value, which is shares times the price
of that day).
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.providers.base import Bar, Provider, ProviderError, to_decimal


@dataclass
class PriceSeries:
    currency: str
    bars: list[Bar] = field(default_factory=list)            # adjusted
    raw_closes: list[tuple[date, Decimal]] = field(default_factory=list)
    call_id: int | None = None


def _adjusted_bar(d: date, o, h, lo, c, adj, v, currency: str, call_id: int | None, scale: Decimal) -> Bar | None:
    c, adj = to_decimal(c), to_decimal(adj)
    if c is None or adj is None or c == 0:
        return None
    f = adj / c

    def a(x):
        x = to_decimal(x)
        return None if x is None else x * f * scale

    return Bar(ts=d, close=adj * scale, quote=currency, open=a(o), high=a(h), low=a(lo),
               volume=to_decimal(v), call_id=call_id)


def _completed(d: date, today: date) -> bool:
    return d < today


class YahooProvider(Provider):
    name = "yahoo"

    def auth_headers(self) -> dict[str, str]:
        return {"User-Agent": "Mozilla/5.0 (compatible; Graadmeter private research)"}

    def series(self, symbol: str, start: date, end: date) -> PriceSeries:
        p1 = int(datetime.combine(start, time.min, tzinfo=UTC).timestamp())
        p2 = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC).timestamp())
        res = self.get_json(f"/v8/finance/chart/{symbol}",
                            {"period1": p1, "period2": p2, "interval": "1d", "events": "div,split"})
        chart = (res.data or {}).get("chart") or {}
        if chart.get("error"):
            raise ProviderError(f"yahoo {symbol}: {chart['error'].get('description')}", 404)
        result = (chart.get("result") or [None])[0]
        if not result:
            raise ProviderError(f"yahoo {symbol}: no data", 404)
        meta = result.get("meta") or {}
        currency, scale = meta.get("currency") or "USD", Decimal(1)
        if currency in ("GBp", "GBX", "ZAc", "ILA"):  # prices in pence / cents
            currency, scale = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}[currency], Decimal("0.01")
        tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
        stamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        adjclose = (indicators.get("adjclose") or [{}])[0].get("adjclose") or [None] * len(stamps)
        splits = sorted(
            (datetime.fromtimestamp(int(s["date"]), tz).date(),
             Decimal(str(s["numerator"])) / Decimal(str(s["denominator"])))
            for s in ((result.get("events") or {}).get("splits") or {}).values()
            if s.get("numerator") and s.get("denominator")
        )
        today = datetime.now(tz).date()
        out = PriceSeries(currency=currency, call_id=res.call_id)
        seen: set[date] = set()
        for i, ts in enumerate(stamps):
            d = datetime.fromtimestamp(ts, tz).date()
            if d in seen or not (start <= d <= end) or not _completed(d, today):
                continue
            seen.add(d)
            bar = _adjusted_bar(d, quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i],
                                adjclose[i], quote["volume"][i], currency, res.call_id, scale)
            if bar is None:
                continue
            out.bars.append(bar)
            # Yahoo's close is adjusted for later splits; undo that to get the price as traded that day.
            factor = Decimal(1)
            for split_day, ratio in splits:
                if split_day > d:
                    factor *= ratio
            out.raw_closes.append((d, to_decimal(quote["close"][i]) * scale * factor))
        return out


class TiingoProvider(Provider):
    name = "tiingo"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.api_key}"} if self.api_key else {}

    def series(self, symbol: str, start: date, end: date) -> PriceSeries:
        if not self.api_key:
            raise ProviderError("tiingo: no API key (TIINGO_API_KEY)")
        res = self.get_json(f"/tiingo/daily/{symbol.lower()}/prices",
                            {"startDate": start.isoformat(), "endDate": end.isoformat()})
        today = datetime.now(ZoneInfo("America/New_York")).date()
        out = PriceSeries(currency="USD", call_id=res.call_id)
        for r in res.data or []:
            d = date.fromisoformat(r["date"][:10])
            if not _completed(d, today):
                continue
            bar = _adjusted_bar(d, r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("adjClose"),
                                r.get("volume"), "USD", res.call_id, Decimal(1))
            if bar is not None:
                out.bars.append(bar)
                out.raw_closes.append((d, to_decimal(r["close"])))
        return out


class EodhdProvider(Provider):
    """EODHD end-of-day prices; only used when EODHD_API_KEY is set (paid, see README)."""

    name = "eodhd"

    def series(self, symbol: str, start: date, end: date) -> PriceSeries:
        if not self.api_key:
            raise ProviderError("eodhd: no API key (EODHD_API_KEY)")
        res = self.get_json(f"/eod/{symbol}", {"from": start.isoformat(), "to": end.isoformat(), "fmt": "json",
                                               "api_token": self.api_key})
        currency = "EUR" if symbol.endswith((".AS", ".PA", ".XETRA", ".BR")) else "USD"
        today = datetime.now(UTC).date()
        out = PriceSeries(currency=currency, call_id=res.call_id)
        for r in res.data or []:
            d = date.fromisoformat(r["date"])
            if not _completed(d, today):
                continue
            bar = _adjusted_bar(d, r.get("open"), r.get("high"), r.get("low"), r.get("close"),
                                r.get("adjusted_close"), r.get("volume"), currency, res.call_id, Decimal(1))
            if bar is not None:
                out.bars.append(bar)
                out.raw_closes.append((d, to_decimal(r["close"])))
        return out


class OpenFigiProvider(Provider):
    """OpenFIGI: turns an ISIN into tickers per exchange (25 requests per minute without a key)."""

    name = "openfigi"

    def isin(self, isin: str) -> list[dict]:
        res = self.post_json("/v3/mapping", [{"idType": "ID_ISIN", "idValue": isin}])
        first = (res.data or [{}])[0]
        return [
            {k: r.get(k) for k in ("ticker", "exchCode", "name", "securityType", "marketSector")}
            for r in first.get("data") or []
        ]
