"""Load config/stocks.yaml: which stocks are followed and where their data comes from."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Benchmark(_Strict):
    slug: str
    name: str
    yahoo: str


class UsSettings(_Strict):
    candidates: int
    forms: list[str]
    benchmark: Benchmark
    # Shares reported in another unit than the listed class (Berkshire reports Class A equivalents).
    share_multiplier: dict[str, float] = {}


class AexMember(_Strict):
    name: str
    isin: str | None
    ticker: str
    yahoo: str
    sec_ticker: str | None = None
    country: str | None = None


class AexSettings(_Strict):
    verified_on: str
    benchmark: Benchmark
    members: list[AexMember]


class PriceSettings(_Strict):
    history_start: str
    us_sources: list[str]
    eu_sources: list[str]
    recheck_days: int


class FundamentalSettings(_Strict):
    history_start: str
    refresh_days: int


class StocksConfig(_Strict):
    us: UsSettings
    aex: AexSettings
    prices: PriceSettings
    fundamentals: FundamentalSettings


def load_stocks_config(path: Path) -> StocksConfig:
    with path.open(encoding="utf-8") as fh:
        return StocksConfig.model_validate(yaml.safe_load(fh))
