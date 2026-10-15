"""Watchdog (phase 10): report a scheduled job that did not run when it should have, once a day per job."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingest.report import Report
from app.ops.config import OpsConfig
from app.ops.notify import send


def overdue(session: Session, ops: OpsConfig, scheduled: set[str], now: datetime) -> list[tuple[str, datetime | None]]:
    first = session.execute(text("SELECT min(started_at) FROM job_run")).scalar()
    out = []
    for job, hours in ops.watchdog_hours.items():
        if job not in scheduled:
            continue
        last = session.execute(text("SELECT max(started_at) FROM job_run WHERE job = :j AND status <> 'skipped'"),
                               {"j": job}).scalar()
        limit = timedelta(hours=hours)
        # A job that never ran counts only once the app itself has been running longer than the limit.
        if (last is None and first is not None and now - first > limit) or (last is not None and now - last > limit):
            out.append((job, last))
    return out


def run_watchdog(session: Session, ops: OpsConfig, scheduled: set[str], labels: dict[str, str],
                 now: datetime | None = None) -> Report:
    now = now or datetime.now(UTC)
    report = Report()
    for job, last in overdue(session, ops, scheduled, now):
        subject = f"{labels.get(job, job)}: niet gedraaid"
        recent = session.execute(text(
            "SELECT 1 FROM notification WHERE kind = 'watchdog' AND subject LIKE :s AND created_at > :t LIMIT 1"),
            {"s": f"%{labels.get(job, job)}: niet gedraaid", "t": now - timedelta(hours=24)}).first()
        report.add("overdue")
        if recent:
            continue
        body = (f"De taak {labels.get(job, job)} ({job}) draaide voor het laatst op "
                f"{last:%d-%m-%Y %H:%M} UTC." if last else f"De taak {labels.get(job, job)} ({job}) heeft nog nooit "
                "gedraaid.") + " Controleer of de server en de planner draaien (Instellingen en verbruik)."
        send(session, ops, subject, body, "watchdog")
        report.add("notified")
    return report
