"""Load config/commodities.yaml (commodities, currency pairs) and the hand-maintained config/etcs.csv."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.markets_config import FundRow, _read_csv


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CommodityEntry(_Strict):
    slug: str
    name: str
    template: str
    # `class` is a keyword in Python; the YAML key is `class`.
    group: str
    front: str
    root: str
    exchange: str
    months: str
    cftc: str | None = None
    eia: str | None = None


class CurrencyEntry(_Strict):
    rates: list[str]
    reer: str | None = None
    worldbank: str | None = None
    cftc: str | None = None
    managed: bool = False


@dataclass(frozen=True)
class FxPair:
    base: str
    quote: str

    @property
    def slug(self) -> str:
        return f"{self.base}-{self.quote}".lower()

    @property
    def name(self) -> str:
        return f"{self.base}/{self.quote}"

    def inverse(self) -> "FxPair":
        return FxPair(self.quote, self.base)


@dataclass(frozen=True)
class CommoditiesConfig:
    commodities: list[CommodityEntry]
    history_start: str
    pairs: list[FxPair]                  # as configured (the base direction)
    currencies: dict[str, CurrencyEntry]
    etcs: list[FundRow]

    @property
    def all_pairs(self) -> list[FxPair]:
        return self.pairs + [p.inverse() for p in self.pairs]


def load_commodities_config(config_dir: Path) -> CommoditiesConfig:
    with (config_dir / "commodities.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    commodities = [CommodityEntry.model_validate({**{k: v for k, v in c.items() if k != "class"},
                                                  "group": c["class"]}) for c in raw["commodities"]]
    pairs = [FxPair(*p.split("/")) for p in raw["fx_pairs"]]
    currencies = {k: CurrencyEntry.model_validate(v) for k, v in raw["currencies"].items()}
    for p in pairs:
        if p.base not in currencies or p.quote not in currencies:
            raise ValueError(f"fx pair {p.name}: currency not configured")
    return CommoditiesConfig(commodities, str(raw["history_start"]), pairs, currencies,
                             _read_csv(config_dir / "etcs.csv"))
