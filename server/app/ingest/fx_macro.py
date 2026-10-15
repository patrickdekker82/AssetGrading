"""Nightly ECB reference rates (Frankfurter) and macro series (FRED)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.report import Report
from app.ingest.store import insert_fx, insert_macro
from app.models import FxRate, MacroObservation
from app.providers import ProviderError
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers

REVISION_WINDOW_DAYS = 60   # re-read recent macro data so revisions are captured
FX_CHUNK_DAYS = 3 * 365


def update_fx(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, report: Report,
              today: date | None = None) -> None:
    today = today or datetime.now(UTC).date()
    with sf() as session:
        last = session.scalar(
            select(func.max(FxRate.date)).where(FxRate.base == cfg.fx.base, FxRate.source == "frankfurter")
        )
    with sf() as session:
        known = set(session.scalars(select(FxRate.quote).where(FxRate.base == cfg.fx.base).distinct()))
    new = [c for c in cfg.fx.currencies if c not in known]
    if last and new:   # a currency added to the configuration gets its full history first
        _fetch_fx(sf, providers, cfg, report, date.fromisoformat(cfg.fx.history_start), last, new)
    start = last + timedelta(days=1) if last else date.fromisoformat(cfg.fx.history_start)
    _fetch_fx(sf, providers, cfg, report, start, today, cfg.fx.currencies)


def _fetch_fx(sf, providers: Providers, cfg: ProvidersConfig, report: Report, start: date, until: date,
              currencies: list[str]) -> None:
    while start <= until:
        end = min(until, start + timedelta(days=FX_CHUNK_DAYS))
        try:
            rows = providers.frankfurter.rates(start, end, cfg.fx.base, currencies)
        except ProviderError as exc:
            report.error(f"fx: {exc}")
            return
        with sf() as session:
            report.add("fx_rates_added", insert_fx(session, rows, cfg.fx.base, "frankfurter", datetime.now(UTC)))
            session.commit()
        start = end + timedelta(days=1)


def update_macro(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, report: Report) -> None:
    for series_id in cfg.macro.fred_series:
        with sf() as session:
            last = session.scalar(
                select(func.max(MacroObservation.date)).where(
                    MacroObservation.series_id == series_id, MacroObservation.source == "fred"
                )
            )
        history_start = date.fromisoformat(cfg.macro.history_start)
        start = max(last - timedelta(days=REVISION_WINDOW_DAYS), history_start) if last else history_start
        try:
            obs = providers.fred.observations(series_id, start)
        except ProviderError as exc:
            report.error(f"fred {series_id}: {exc}")
            continue
        with sf() as session:
            report.add("macro_added", insert_macro(session, series_id, "fred", obs, datetime.now(UTC)))
            session.commit()
    for series_id, spec in cfg.macro.ecb_series.items():
        with sf() as session:
            last = session.scalar(select(func.max(MacroObservation.date)).where(
                MacroObservation.series_id == series_id, MacroObservation.source == "ecb"))
        history_start = date.fromisoformat(cfg.macro.history_start)
        start = max(last - timedelta(days=REVISION_WINDOW_DAYS), history_start) if last else history_start
        try:
            obs = providers.get("ecb").observations(spec["key"], start)
        except ProviderError as exc:
            report.error(f"ecb {series_id}: {exc}")
            continue
        with sf() as session:
            report.add("macro_added", insert_macro(session, series_id, "ecb", obs, datetime.now(UTC)))
            session.commit()


def update_treasury(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, report: Report,
                    today: date | None = None) -> None:
    """The US Treasury par yield curve, one request per calendar year: the full history once, then the
    previous and current year every run (late corrections at the turn of the year)."""
    from app.providers.treasury import MATURITIES

    if "treasury" not in cfg.providers:
        return
    today = today or datetime.now(UTC).date()
    with sf() as session:
        last = session.scalar(select(func.max(MacroObservation.date)).where(
            MacroObservation.series_id == "UST_10Y", MacroObservation.source == "treasury"))
    first = max(date.fromisoformat(cfg.macro.history_start).year, 1990)
    start = max(last.year - 1, first) if last else first
    for year in range(start, today.year + 1):
        try:
            curve = providers.get("treasury").year_curve(year)
        except ProviderError as exc:
            report.error(f"treasury {year}: {exc}")
            continue
        with sf() as session:
            for sid, _ in MATURITIES.values():
                report.add("macro_added", insert_macro(session, sid, "treasury", curve.get(sid, []), datetime.now(UTC)))
            session.commit()


def run_fx_macro(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig) -> Report:
    report = Report()
    update_fx(sf, providers, cfg, report)
    update_macro(sf, providers, cfg, report)
    update_treasury(sf, providers, cfg, report)
    return report
