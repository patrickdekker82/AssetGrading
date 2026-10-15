"""News around a missed grade (Marketaux), stored once per article and reused."""

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingest.report import Report
from app.providers import ProviderError
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers


def news_fetcher(session: Session, providers: Providers, cfg: ProvidersConfig, report: Report,
                 today: date | None = None) -> Callable[[int, date, int], list[dict] | None] | None:
    """A function (asset id, grade date, horizon in months) -> articles, or None without a Marketaux key."""
    if "marketaux" not in cfg.providers:
        return None
    provider = providers.get("marketaux")
    if not provider.api_key:
        return None
    today = today or datetime.now(UTC).date()
    per_miss, budget = cfg.news.per_miss, [cfg.news.max_calls_per_run]

    def fetch(asset_id: int, as_of: date, horizon: int) -> list[dict] | None:
        row = session.execute(text(
            """SELECT a.asset_class, coalesce(max(al.value) FILTER (WHERE al.kind = 'us_ticker'), a.symbol) AS symbol
               FROM asset a LEFT JOIN asset_alias al ON al.asset_id = a.id WHERE a.id = :a
               GROUP BY a.id"""), {"a": asset_id}).first()
        if row is None or row.asset_class != "stock" or not row.symbol:
            return None                                   # Marketaux recognises companies, not coins or indices
        end = min(as_of + timedelta(days=round(30.5 * horizon)), today)
        stored = _stored(session, asset_id, as_of, end, per_miss)
        if stored:
            return stored
        pages = math.ceil(per_miss / 3)
        if budget[0] < pages:
            report.notes.append("nieuws: daglimiet van Marketaux voor deze run bereikt")
            return None
        budget[0] -= pages
        try:
            articles = provider.news(row.symbol, as_of, end, pages)
        except ProviderError as exc:
            report.error(f"nieuws {row.symbol}: {exc}")
            return None
        now = datetime.now(UTC)
        for a in articles:
            session.execute(text(
                """INSERT INTO news_item (asset_id, uuid, published_at, title, description, url, source_name,
                       sentiment, source, fetched_at, call_id)
                   VALUES (:asset, :uuid, :pub, :title, :desc, :url, :src, :sent, 'marketaux', :now, :call)
                   ON CONFLICT (asset_id, uuid) DO NOTHING"""),
                {"asset": asset_id, "uuid": a["uuid"], "pub": a["published_at"], "title": a["title"],
                 "desc": a["description"], "url": a["url"], "src": a["source_name"], "sent": a["sentiment"],
                 "now": now, "call": a["call_id"]})
        session.commit()
        report.add("news_items", len(articles))
        return _stored(session, asset_id, as_of, end, per_miss)

    return fetch


def _stored(session: Session, asset_id: int, start: date, end: date, limit: int) -> list[dict]:
    rows = session.execute(text(
        """SELECT published_at, title, description, source_name FROM news_item
           WHERE asset_id = :a AND published_at >= :s AND published_at < :e
           ORDER BY published_at LIMIT :n"""),
        {"a": asset_id, "s": start, "e": end + timedelta(days=1), "n": limit}).all()
    return [{"datum": r.published_at.date().isoformat(), "titel": r.title, "samenvatting": r.description,
             "bron": r.source_name} for r in rows]
