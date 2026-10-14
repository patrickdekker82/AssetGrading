"""Load config/providers.yaml into typed settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.providers.base import ProviderSettings, RateLimit


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderEntry(_Strict):
    base_url: str
    rate_limit: dict[str, float]
    monthly_budget: int | None = None
    raw_retention_days: int = 400
    api_key_env: str | None = None
    attribution: str | None = None


class CryptoSettings(_Strict):
    history_start: str
    markets_page_size: int
    excluded_categories: dict[str, str]
    track_stablecoins: int
    price_sources: list[str]
    binance_quotes: list[str]
    coinbase_quotes: list[str]
    mapping_price_tolerance: float
    metadata_refresh_days: int
    coinmetrics_metrics: list[str]
    coinmetrics_overrides: dict[str, str] = {}
    derivatives_sources: list[str]
    derivatives_backfill_days: int
    mica_venues: list[str]


class FxSettings(_Strict):
    base: str
    currencies: list[str]
    history_start: str


class MacroSettings(_Strict):
    history_start: str
    fred_series: dict[str, str]
    ecb_series: dict[str, dict[str, str]] = {}   # stored id -> {key, label}


class ProvidersConfig(_Strict):
    providers: dict[str, ProviderEntry]
    crypto: CryptoSettings
    fx: FxSettings
    macro: MacroSettings
    schedule: dict[str, str]

    def settings_for(self, name: str) -> ProviderSettings:
        e = self.providers[name]
        return ProviderSettings(
            name=name,
            base_url=e.base_url.rstrip("/"),
            rate_limit=RateLimit(calls=int(e.rate_limit["calls"]), per_seconds=float(e.rate_limit["per_seconds"])),
            monthly_budget=e.monthly_budget,
            raw_retention_days=e.raw_retention_days,
            api_key_env=e.api_key_env,
            attribution=e.attribution,
        )


def load_providers_config(path: Path) -> ProvidersConfig:
    with path.open(encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh)
    return ProvidersConfig.model_validate(data)
