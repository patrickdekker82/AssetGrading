from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://graadmeter:graadmeter@localhost:5432/graadmeter"
    config_dir: Path = REPO_ROOT / "config"
    scheduler_enabled: bool = True
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
