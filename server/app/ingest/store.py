"""Idempotent writes. Running any ingest twice never creates duplicate rows.

- Bars, FX rates and membership rows: insert, ignore when the key already exists.
- Facts and macro observations are point-in-time: a row is only added when the value differs from
  the latest known value for that day, so revisions are kept next to the original.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.models import FundamentalFact, FxRate, MacroObservation, PriceBar, UniverseMembership
from app.providers.base import Bar, Fact


def end_of_day(d: date) -> datetime:
    """Moment a daily value is assumed public when the true publication time is unknown (backfill)."""
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=UTC)


def last_bar_date(session: Session, asset_id: int, source: str, interval: str = "1d") -> date | None:
    return session.scalar(
        select(func.max(PriceBar.ts)).where(
            PriceBar.asset_id == asset_id, PriceBar.source == source, PriceBar.interval == interval
        )
    )


def insert_bars(session: Session, asset_id: int, source: str, bars: Iterable[Bar], fetched_at: datetime) -> int:
    rows = [
        {
            "asset_id": asset_id, "interval": "1d", "ts": b.ts, "source": source, "open": b.open, "high": b.high,
            "low": b.low, "close": b.close, "volume": b.volume, "quote_currency": b.quote,
            "fetched_at": fetched_at, "call_id": b.call_id,
        }
        for b in bars
        if b.close is not None
    ]
    return _insert_ignore(session, PriceBar, rows)


def insert_fx(session: Session, rows: Iterable[tuple[date, str, Decimal, int | None]], base: str, source: str,
              fetched_at: datetime) -> int:
    payload = [
        {"date": d, "base": base, "quote": q, "source": source, "rate": r, "fetched_at": fetched_at, "call_id": c}
        for d, q, r, c in rows
        if r is not None
    ]
    return _insert_ignore(session, FxRate, payload)


def insert_membership(session: Session, rows: list[dict]) -> int:
    return _insert_ignore(session, UniverseMembership, rows)


def _insert_ignore(session: Session, model, rows: list[dict], chunk: int = 2000) -> int:
    added = 0
    for i in range(0, len(rows), chunk):
        stmt = insert(model).values(rows[i:i + chunk]).on_conflict_do_nothing().returning(text("1"))
        added += len(session.execute(stmt).all())
    return added


def insert_facts(session: Session, asset_id: int, source: str, facts: Iterable[Fact], fetched_at: datetime,
                 *, snapshot: bool = False) -> int:
    """Append new and revised facts.

    `snapshot=True` is for live values such as today's market cap: they change by the minute, so the
    first value stored for a day is kept and later ones that day are ignored.
    """
    facts = list(facts)
    if not facts:
        return 0
    fields = {f.field for f in facts}
    latest = _latest_fact_values(session, asset_id, source, fields)
    if any(f.available_at is not None for f in facts):
        return _insert_dated_facts(session, asset_id, source, facts, latest, fetched_at)
    known_fields = {field for field, _ in latest}
    rows = []
    seen: set[tuple[str, date]] = set()
    for f in facts:
        key = (f.field, f.as_of)
        if key in seen:
            continue
        seen.add(key)
        if key in latest and (snapshot or Decimal(latest[key]) == f.value):
            continue
        # New day of a field we already follow: public now. Backfilled history: assume end of day.
        backfill = f.field not in known_fields
        available_at = end_of_day(f.as_of) if backfill else max(fetched_at, end_of_day(f.as_of))
        if key in latest:  # a revision is only known from the moment we saw it
            available_at = fetched_at
        rows.append({
            "asset_id": asset_id, "field": f.field, "as_of": f.as_of, "value": f.value, "unit": f.unit,
            "source": source, "available_at": available_at, "fetched_at": fetched_at, "call_id": f.call_id,
        })
    if rows:
        session.execute(insert(FundamentalFact), rows)
    return len(rows)


def _insert_dated_facts(session: Session, asset_id: int, source: str, facts: list[Fact],
                        latest: dict[tuple[str, date], Decimal], fetched_at: datetime) -> int:
    """Facts whose publication moment is known (filings): every version in filing order, each kept only
    when it differs from the version before it. A version filed before an already stored, different
    version is not inserted again (the stored history is never rewritten)."""
    known_at = _latest_fact_times(session, asset_id, source, {f.field for f in facts})
    rows = []
    current = dict(latest)
    for f in sorted(facts, key=lambda x: (x.field, x.as_of, x.available_at or fetched_at)):
        key = (f.field, f.as_of)
        available_at = f.available_at or fetched_at
        if key in current and Decimal(current[key]) == f.value:
            continue
        if key in known_at and available_at <= known_at[key]:
            continue
        current[key] = f.value
        known_at[key] = available_at
        rows.append({
            "asset_id": asset_id, "field": f.field, "as_of": f.as_of, "value": f.value, "unit": f.unit,
            "source": source, "available_at": available_at, "fetched_at": fetched_at, "call_id": f.call_id,
        })
    for i in range(0, len(rows), 5000):
        session.execute(insert(FundamentalFact), rows[i:i + 5000])
    return len(rows)


def _latest_fact_times(session: Session, asset_id: int, source: str,
                       fields: set[str]) -> dict[tuple[str, date], datetime]:
    stmt = (
        select(FundamentalFact.field, FundamentalFact.as_of, func.max(FundamentalFact.available_at))
        .where(FundamentalFact.asset_id == asset_id, FundamentalFact.source == source,
               FundamentalFact.field.in_(fields))
        .group_by(FundamentalFact.field, FundamentalFact.as_of)
    )
    return {(field, as_of): t for field, as_of, t in session.execute(stmt)}


def upsert_bars(session: Session, asset_id: int, source: str, bars: Iterable[Bar], fetched_at: datetime) -> int:
    """Insert or replace bars: adjusted stock prices change for all earlier days after a dividend or split."""
    rows = [
        {
            "asset_id": asset_id, "interval": "1d", "ts": b.ts, "source": source, "open": b.open, "high": b.high,
            "low": b.low, "close": b.close, "volume": b.volume, "quote_currency": b.quote,
            "fetched_at": fetched_at, "call_id": b.call_id,
        }
        for b in bars
        if b.close is not None
    ]
    for i in range(0, len(rows), 2000):
        stmt = insert(PriceBar).values(rows[i:i + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["asset_id", "interval", "ts", "source"],
            set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "volume", "quote_currency",
                                                "fetched_at", "call_id")},
        )
        session.execute(stmt)
    return len(rows)


def _latest_fact_values(
    session: Session, asset_id: int, source: str, fields: set[str]
) -> dict[tuple[str, date], Decimal]:
    stmt = (
        select(FundamentalFact.field, FundamentalFact.as_of, FundamentalFact.value)
        .where(FundamentalFact.asset_id == asset_id, FundamentalFact.source == source,
               FundamentalFact.field.in_(fields))
        .ext(distinct_on(FundamentalFact.field, FundamentalFact.as_of))
        .order_by(FundamentalFact.field, FundamentalFact.as_of, FundamentalFact.available_at.desc(),
                  FundamentalFact.id.desc())
    )
    return {(field, as_of): value for field, as_of, value in session.execute(stmt)}


def last_fact_date(session: Session, asset_id: int, source: str, field_prefix: str = "") -> date | None:
    return session.scalar(
        select(func.max(FundamentalFact.as_of)).where(
            FundamentalFact.asset_id == asset_id, FundamentalFact.source == source,
            FundamentalFact.field.startswith(field_prefix),
        )
    )


def insert_macro(session: Session, series_id: str, source: str, obs: Iterable[tuple[date, float, int | None]],
                 fetched_at: datetime, release_lag: timedelta | None = None) -> int:
    """`release_lag`: for series published some time after the date they describe (CFTC on Friday for
    Tuesday, World Bank months after the year): a value never counts as known before date + lag."""
    obs = list(obs)
    if not obs:
        return 0
    stmt = (
        select(MacroObservation.date, MacroObservation.value)
        .where(MacroObservation.series_id == series_id, MacroObservation.source == source)
        .ext(distinct_on(MacroObservation.date))
        .order_by(MacroObservation.date, MacroObservation.available_at.desc(), MacroObservation.id.desc())
    )
    latest = {d: v for d, v in session.execute(stmt)}
    backfill = not latest
    rows = []
    for d, value, call_id in obs:
        if d in latest and latest[d] == value:
            continue
        if d in latest:
            available_at = fetched_at
        elif backfill:
            available_at = end_of_day(d)
        else:
            available_at = max(fetched_at, end_of_day(d))
        if release_lag is not None:
            available_at = max(available_at, datetime.combine(d, time.min, tzinfo=UTC) + release_lag)
        rows.append({"series_id": series_id, "date": d, "value": value, "source": source,
                     "available_at": available_at, "fetched_at": fetched_at, "call_id": call_id})
        latest[d] = value
    if rows:
        session.execute(insert(MacroObservation), rows)
    return len(rows)
