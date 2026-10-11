"""Delete raw responses older than each provider's retention. The call log itself is kept."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.report import Report
from app.models import ProviderCallLog, ProviderResponse
from app.providers.config import ProvidersConfig


def run_prune(sf: sessionmaker[Session], cfg: ProvidersConfig) -> Report:
    report = Report()
    now = datetime.now(UTC)
    with sf() as session:
        for name, entry in cfg.providers.items():
            cutoff = now - timedelta(days=entry.raw_retention_days)
            old_calls = select(ProviderCallLog.id).where(
                ProviderCallLog.provider == name, ProviderCallLog.started_at < cutoff
            )
            result = session.execute(delete(ProviderResponse).where(ProviderResponse.call_id.in_(old_calls)))
            report.add(f"raw_pruned_{name}", result.rowcount or 0)
        session.commit()
    return report
