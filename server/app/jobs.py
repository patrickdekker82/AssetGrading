"""Job runner: records each run in job_run and prevents two runs of the same job at once."""

import logging
import traceback
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.ai.config import AiConfig
from app.commodities_config import CommoditiesConfig
from app.grading.commodities import grade_commodities
from app.grading.crypto import grade_crypto
from app.grading.markets import grade_markets
from app.grading.regime import update_regime
from app.grading.stocks import grade_stocks
from app.ingest.commodities import run_commodities
from app.ingest.crypto import run_crypto
from app.ingest.fx_macro import run_fx_macro
from app.ingest.markets import run_markets
from app.ingest.prune import run_prune
from app.ingest.report import Report
from app.ingest.stocks import run_stocks
from app.markets_config import MarketsConfig
from app.modelconfig import ModelConfig
from app.models import JobRun
from app.providers.config import ProvidersConfig
from app.providers.recorder import current_job_run
from app.providers.registry import Providers
from app.stocks_config import StocksConfig
from app.universes import Universes

log = logging.getLogger("graadmeter.jobs")


@dataclass
class JobContext:
    engine: Engine
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    universes: Universes
    model: ModelConfig | None = None
    model_version_id: int | None = None
    stocks: StocksConfig | None = None
    markets: MarketsConfig | None = None
    commodities: CommoditiesConfig | None = None
    ai: AiConfig | None = None
    labels: dict[str, str] | None = None     # metric labels from the glossary, for explanations
    llm_client: object | None = None         # None without an API key: template text only


def run_crypto_and_grade(c: JobContext) -> Report:
    """Nightly crypto: ingest, then grade the last completed day."""
    report = run_crypto(c.sf, c.providers, c.cfg, c.universes, model=c.model)
    if c.model is None or c.model_version_id is None:
        report.notes.append("Geen modelconfiguratie geladen; grading overgeslagen.")
        return report
    as_of = datetime.now(UTC).date() - timedelta(days=1)
    try:
        graded = grade_crypto(c.sf, c.model, c.model_version_id, as_of, date.fromisoformat(c.cfg.crypto.history_start))
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("crypto grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    return report


def run_stocks_and_grade(c: JobContext) -> Report:
    """Weekday stock run: ingest, then grade today's close (the run starts after the US close)."""
    if c.model is None or c.model_version_id is None or c.stocks is None:
        report = Report()
        report.error("Geen model- of aandelenconfiguratie geladen.")
        return report
    report = run_stocks(c.sf, c.providers, c.cfg, c.stocks, c.universes, c.model)
    as_of = last_trading_day(datetime.now(UTC))
    try:
        graded = grade_stocks(c.sf, c.model, c.model_version_id, c.stocks, as_of)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("stock grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    return report


REGIME_START = date(2010, 1, 1)


def run_markets_and_grade(c: JobContext) -> Report:
    """Weekday markets run: indices, ETFs and bond ETFs, the market regime, then their grades."""
    if c.model is None or c.model_version_id is None or c.markets is None:
        report = Report()
        report.error("Geen model- of marktconfiguratie geladen.")
        return report
    report = run_markets(c.sf, c.providers, c.cfg, c.markets)
    as_of = last_trading_day(datetime.now(UTC))
    try:
        update_regime(c.sf, c.model, c.model_version_id, datetime.now(UTC).date(), REGIME_START, report)
        graded = grade_markets(c.sf, c.model, c.model_version_id, c.markets, as_of)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("markets grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    return report


def run_commodities_and_grade(c: JobContext) -> Report:
    """Weekday commodities and currencies run, then their grades (commodity, product, currency pair)."""
    if c.model is None or c.model_version_id is None or c.commodities is None:
        report = Report()
        report.error("Geen model- of grondstoffenconfiguratie geladen.")
        return report
    report = run_commodities(c.sf, c.providers, c.cfg, c.commodities)
    try:
        graded = grade_commodities(c.sf, c.model, c.model_version_id, c.commodities,
                                   last_trading_day(datetime.now(UTC)))
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("commodities grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    return report


def run_explanations(c: JobContext) -> Report:
    """Collect finished explanation batches and submit new ones (chapter 9)."""
    if c.model is None or c.model_version_id is None or c.ai is None:
        report = Report()
        report.error("Geen model- of AI-configuratie geladen.")
        return report
    from app.ai.explanation import Explainer

    return Explainer(c.sf, c.ai, c.model, c.model_version_id, c.labels or {}, c.llm_client).run()


def last_trading_day(now: datetime) -> date:
    """The last weekday whose US session has closed (21:00 UTC covers both summer and winter time)."""
    day = now.date() if now.hour >= 21 else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


JOBS: dict[str, Callable[[JobContext], Report]] = {
    "crypto": run_crypto_and_grade,
    "stocks": run_stocks_and_grade,
    "markets": run_markets_and_grade,
    "commodities": run_commodities_and_grade,
    "fx_macro": lambda c: run_fx_macro(c.sf, c.providers, c.cfg),
    "explanations": run_explanations,
    "prune_raw": lambda c: run_prune(c.sf, c.cfg),
}

JOB_LABELS_NL = {
    "crypto": "Crypto (koersen, lijst, fundamentals)",
    "stocks": "Aandelen (koersen, SEC-cijfers, lijst)",
    "markets": "Indices, ETF's, obligaties en marktregime",
    "commodities": "Grondstoffen, ETC's en valuta",
    "fx_macro": "Wisselkoersen en macro",
    "explanations": "Toelichtingen (taalmodel, batch)",
    "prune_raw": "Opruimen ruwe antwoorden",
}


def lock_key(name: str) -> int:
    return zlib.crc32(f"graadmeter-job-{name}".encode())


def fail_orphaned_runs(engine: Engine, sf: sessionmaker[Session]) -> int:
    """Mark runs as failed that say 'running' but whose job lock nobody holds (process stopped).

    A run started from the command line holds its lock in another process and is left alone.
    """
    failed = 0
    with sf() as session, engine.connect() as conn:
        for run in session.query(JobRun).filter(JobRun.status == "running"):
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key(run.job)}).scalar():
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key(run.job)})
                run.status, run.error, run.finished_at = "failed", "proces gestopt tijdens run", datetime.now(UTC)
                failed += 1
        conn.commit()
        session.commit()
    return failed


def run_job(ctx: JobContext, name: str, trigger: str = "manual") -> JobRun:
    if name not in JOBS:
        raise KeyError(name)
    key = lock_key(name)
    with ctx.engine.connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            return _record_skip(ctx, name, trigger)
        try:
            return _execute(ctx, name, trigger)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            lock_conn.commit()


def _record_skip(ctx: JobContext, name: str, trigger: str) -> JobRun:
    now = datetime.now(UTC)
    with ctx.sf() as session:
        run = JobRun(job=name, trigger=trigger, status="skipped", started_at=now, finished_at=now,
                     summary={"notes": ["De vorige run van deze taak liep nog."]})
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def _execute(ctx: JobContext, name: str, trigger: str) -> JobRun:
    with ctx.sf() as session:
        run = JobRun(job=name, trigger=trigger, status="running", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        run_id = run.id
    token = current_job_run.set(run_id)
    status, summary, error = "ok", None, None
    try:
        report = JOBS[name](ctx)
        summary = report.as_dict()
        status = "partial" if report.errors else "ok"
    except Exception as exc:  # noqa: BLE001 - a failed run is recorded, never crashes the server
        status, error = "failed", "".join(traceback.format_exception(exc))[-4000:]
        log.exception("job %s failed", name)
    finally:
        current_job_run.reset(token)
    with ctx.sf() as session:
        run = session.get(JobRun, run_id)
        run.status, run.summary, run.error, run.finished_at = status, summary, error, datetime.now(UTC)
        session.commit()
        session.refresh(run)
        log.info("job %s finished: %s", name, status)
        return run


def schedule_jobs(scheduler: BaseScheduler, ctx: JobContext) -> None:
    mapping = {"crypto": ["crypto"], "stocks": ["stocks"], "markets": ["markets"], "commodities": ["commodities"],
               "fx_macro": ["fx_macro"], "explanations": ["explanations"], "prune_raw": ["prune_raw"]}
    for key, expr in ctx.cfg.schedule.items():
        for job in mapping.get(key, []):
            scheduler.add_job(
                run_job, CronTrigger.from_crontab(expr, timezone="UTC"), args=[ctx, job, "schedule"],
                id=f"nightly-{job}", replace_existing=True, misfire_grace_time=3600,
            )
