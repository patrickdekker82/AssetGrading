"""In-process job scheduler. Nightly data runs are added from phase 1 on."""

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    # One process only: running several uvicorn workers would run every job several times.
    return BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
