"""Order books, Bitvavo listings, DexScreener liquidity, RugCheck safety reports, stablecoin supply."""

from datetime import UTC, date, datetime

from app.providers.base import Provider, ProviderError, to_decimal


class CoinbaseBookProvider(Provider):
    """Coinbase level-2 order book (separate entry so its large raw responses get a short retention)."""

    name = "coinbase_book"

    def depth(self, product: str, within: float = 0.02) -> tuple[dict[str, float], int | None]:
        """{'depth_quote': value of bids+asks within `within` of mid, 'spread': (ask-bid)/mid} in quote currency."""
        res = self.get_json(f"/products/{product}/book", {"level": 2})
        bids = [(float(p), float(s)) for p, s, *_ in res.data.get("bids", [])]
        asks = [(float(p), float(s)) for p, s, *_ in res.data.get("asks", [])]
        if not bids or not asks:
            raise ProviderError(f"coinbase_book {product}: empty book", 400)
        best_bid, best_ask = bids[0][0], asks[0][0]
        mid = (best_bid + best_ask) / 2
        depth = sum(p * s for p, s in bids if p >= mid * (1 - within))
        depth += sum(p * s for p, s in asks if p <= mid * (1 + within))
        return {"depth_quote": depth, "spread": (best_ask - best_bid) / mid}, res.call_id


class BitvavoProvider(Provider):
    """Bitvavo (Dutch exchange with a MiCA licence): EUR markets and 24-hour volume."""

    name = "bitvavo"

    def eur_markets(self) -> tuple[dict[str, dict], int | None]:
        """{BASE: {'last': price EUR, 'volume_eur': 24h quote volume}} for trading EUR markets."""
        markets = self.get_json("/v2/markets")
        trading = {m["base"].upper() for m in markets.data if m.get("quote") == "EUR" and m.get("status") == "trading"}
        ticker = self.get_json("/v2/ticker/24h")
        out = {}
        for t in ticker.data:
            market = t.get("market", "")
            if not market.endswith("-EUR"):
                continue
            base = market[:-4].upper()
            last, volume = to_decimal(t.get("last")), to_decimal(t.get("volumeQuote"))
            if base in trading and last is not None:
                out[base] = {"last": float(last), "volume_eur": float(volume) if volume is not None else None}
        return out, ticker.call_id


class DexScreenerProvider(Provider):
    name = "dexscreener"

    def liquidity_usd(self, chain: str, address: str) -> tuple[float | None, int | None]:
        res = self.get_json(f"/tokens/v1/{chain}/{address}")
        pairs = res.data if isinstance(res.data, list) else []
        total = sum(float((p.get("liquidity") or {}).get("usd") or 0) for p in pairs)
        return (total if pairs else None), res.call_id


class RugCheckProvider(Provider):
    name = "rugcheck"

    def report(self, mint: str) -> tuple[dict[str, float], int | None]:
        """Safety facts for a Solana token: authorities (1 = active), LP locked %, top-10 holders % (ex. pools)."""
        res = self.get_json(f"/v1/tokens/{mint}/report")
        d = res.data
        known = set((d.get("knownAccounts") or {}).keys())
        holders = [h for h in d.get("topHolders") or []
                   if h.get("address") not in known and h.get("owner") not in known]
        facts = {
            "mint_authority_active": 1.0 if d.get("mintAuthority") else 0.0,
            "freeze_authority_active": 1.0 if d.get("freezeAuthority") else 0.0,
            "holders_top10_pct": sum(float(h.get("pct") or 0) for h in holders[:10]),
        }
        markets = d.get("markets") or []
        liquidity = []
        for m in markets:
            lp = m.get("lp") or {}
            value = float(lp.get("quoteUSD") or 0) + float(lp.get("baseUSD") or 0)
            liquidity.append((float(lp.get("lpLockedPct") or 0), value))
        total = sum(w for _, w in liquidity)
        if total > 0:
            facts["lp_locked_pct"] = sum(p * w for p, w in liquidity) / total
        return facts, res.call_id


class StablecoinSupplyProvider(Provider):
    """DefiLlama stablecoin dashboard: total circulating supply of all stablecoins (USD)."""

    name = "defillama_stablecoins"

    def total_supply(self) -> list[tuple[date, float, int | None]]:
        res = self.get_json("/stablecoincharts/all")
        today = datetime.now(UTC).date()
        out = []
        for row in res.data or []:
            day = datetime.fromtimestamp(int(row["date"]), UTC).date()
            total = sum(float(v) for v in (row.get("totalCirculatingUSD") or {}).values() if v is not None)
            if day < today and total > 0:
                out.append((day, total, res.call_id))
        return out
