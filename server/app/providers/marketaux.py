"""Marketaux news API (free key: 100 requests a day, three articles per request). Used only to give the
analysis of large misses the news around the asset in the months after the grade (chapter 9)."""

from datetime import date, datetime

from app.providers.base import Provider, ProviderError


class MarketauxProvider(Provider):
    name = "marketaux"

    def auth_params(self) -> dict[str, str]:
        return {"api_token": self.api_key} if self.api_key else {}

    def news(self, symbol: str, start: date, end: date, pages: int) -> list[dict]:
        """Articles that mention `symbol` (as a recognised company) between `start` and `end`, newest first:
        [{uuid, published_at, title, description, url, source_name, sentiment, call_id}]."""
        if not self.api_key:
            raise ProviderError("marketaux: geen sleutel (MARKETAUX_API_KEY)")
        out: list[dict] = []
        for page in range(1, pages + 1):
            res = self.get_json("/v1/news/all", {
                "symbols": symbol, "filter_entities": "true", "language": "en",
                "published_after": f"{start.isoformat()}T00:00", "published_before": f"{end.isoformat()}T23:59",
                "sort": "published_desc", "page": page})
            rows = (res.data or {}).get("data") or []
            for a in rows:
                entity = next((e for e in a.get("entities") or [] if (e.get("symbol") or "").upper() == symbol.upper()),
                              None)
                published = a.get("published_at")
                if not a.get("uuid") or not a.get("title") or not published:
                    continue
                out.append({"uuid": a["uuid"], "title": a["title"], "description": a.get("description"),
                            "url": a.get("url"), "source_name": a.get("source"),
                            "published_at": datetime.fromisoformat(published.replace("Z", "+00:00")),
                            "sentiment": entity.get("sentiment_score") if entity else None,
                            "call_id": res.call_id})
            meta = (res.data or {}).get("meta") or {}
            if not rows or int(meta.get("returned") or 0) < int(meta.get("limit") or 3):
                break
        return out
