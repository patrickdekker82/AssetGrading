"""Register the loaded model configuration in `model_version` (append-only)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelconfig import ModelConfig, ModelConfigError
from app.models import ModelVersion


def register_model_version(session: Session, config: ModelConfig) -> ModelVersion:
    existing = session.scalar(select(ModelVersion).where(ModelVersion.version == config.version))
    if existing is not None:
        if existing.config_hash != config.config_hash:
            raise ModelConfigError(
                f"model version {config.version} is already stored with another configuration"
            )
        return existing
    row = ModelVersion(
        version=config.version,
        config_hash=config.config_hash,
        description=config.settings.description,
        config=config.raw,
    )
    session.add(row)
    session.commit()
    return row
