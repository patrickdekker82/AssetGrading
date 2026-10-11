"""Job runner: records each run in job_run and prevents two runs of the same job at once."""

import logging
import traceback
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.crypto import run_crypto
from app.ingest.fx_macro import run_fx_macro
from app.ingest.prune import run_prune
from app.ingest.report import Report
from app.models import JobRun
from app.providers.config import ProvidersConfig
from app.providers.recorder import current_job_run
from app.providers.registry import Providers
from app.universes import Universes

log = logging.getLogger("graadmeter.jobs")


@dataclass
class JobContext:
    engine: Engine
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    universes: Universes


JOBS: dict[str, Callable[[JobContext], Report]] = {
    "crypto": lambda c: run_crypto(c.sf, c.providers, c.cfg, c.universes),
    "fx_macro": lambda c: run_fx_macro(c.sf, c.providers, c.cfg),
    "prune_raw": lambda c: run_prune(c.sf, c.cfg),
}

JOB_LABELS_NL = {
    "crypto": "Crypto (koersen, lijst, fundamentals)",
    "fx_macro": "Wisselkoersen en macro",
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
    mapping = {"crypto": ["crypto"], "fx_macro": ["fx_macro"], "prune_raw": ["prune_raw"]}
    for key, expr in ctx.cfg.schedule.items():
        for job in mapping.get(key, []):
            scheduler.add_job(
                run_job, CronTrigger.from_crontab(expr, timezone="UTC"), args=[ctx, job, "schedule"],
                id=f"nightly-{job}", replace_existing=True, misfire_grace_time=3600,
            )
