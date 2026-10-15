"""Records provider calls in the database (provider_call_log + provider_response)."""

from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ProviderCallLog, ProviderResponse
from app.providers.base import gzip_body

current_job_run: ContextVar[int | None] = ContextVar("current_job_run", default=None)


class DbRecorder:
    """Each call is committed in its own short transaction, so the log survives a failing job."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any] | None,
        status_code: int | None,
        ok: bool,
        error: str | None,
        cost: int,
        body: bytes | None,
        content_type: str | None,
        duration_ms: int,
        started_at: datetime,
        size: int | None = None,
    ) -> int:
        with self.session_factory() as session:
            row = ProviderCallLog(
                provider=provider, endpoint=endpoint[:200], params=params, status_code=status_code, ok=ok,
                error=error, cost=cost,
                response_bytes=size if size is not None else (len(body) if body is not None else None),
                duration_ms=duration_ms, started_at=started_at, job_run_id=current_job_run.get(),
            )
            session.add(row)
            session.flush()
            if body:
                session.add(ProviderResponse(call_id=row.id, content_type=content_type, body_gzip=gzip_body(body)))
            session.commit()
            return row.id

    def month_usage(self, provider: str) -> int:
        now = datetime.now(UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        with self.session_factory() as session:
            used = session.scalar(
                select(func.coalesce(func.sum(ProviderCallLog.cost), 0)).where(
                    ProviderCallLog.provider == provider, ProviderCallLog.started_at >= month_start
                )
            )
            return int(used or 0)
