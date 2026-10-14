"""Load config/indices.yaml, config/etfs.yaml and the hand-maintained ETF files (etfs.csv, bond_etfs.csv)."""

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IndexEntry(_Strict):
    slug: str
    name: str
    yahoo: str
    currency: str
    region: str
    curve: str | None = None
    breadth: str | None = None
    world: bool = False


class IndexGroup(_Strict):
    name: str
    index: str | None = None
    us_dividends: bool
    reference: str | None = None


class RateEntry(_Strict):
    series: str
    name: str


@dataclass(frozen=True)
class FundRow:
    """One row of etfs.csv or bond_etfs.csv; empty cells are None."""

    values: dict[str, str | None]

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def num(self, key: str) -> float | None:
        v = self.values.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    @property
    def isin(self) -> str:
        return self.values["isin"] or ""

    @property
    def slug(self) -> str:
        """URL key: the Yahoo symbol, e.g. IWDA.AS -> iwda-as."""
        return (self.values.get("yahoo") or self.isin).replace(".", "-").replace("^", "").lower()


@dataclass(frozen=True)
class MarketsConfig:
    indices: list[IndexEntry]
    index_history_start: str
    index_groups: dict[str, IndexGroup]
    bond_categories: dict[str, str]
    rates: list[RateEntry]
    etfs: list[FundRow]
    bonds: list[FundRow]

    @property
    def world_index(self) -> IndexEntry | None:
        return next((i for i in self.indices if i.world), None)


def _read_csv(path: Path) -> list[FundRow]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [{k.strip(): (v.strip() or None) if isinstance(v, str) else None for k, v in r.items() if k}
                for r in csv.DictReader(line for line in fh if not line.startswith("#"))]
    return [FundRow(r) for r in rows if r.get("isin") and r.get("yahoo")]


def load_markets_config(config_dir: Path) -> MarketsConfig:
    with (config_dir / "indices.yaml").open(encoding="utf-8") as fh:
        idx = yaml.safe_load(fh)
    with (config_dir / "etfs.yaml").open(encoding="utf-8") as fh:
        etf = yaml.safe_load(fh)
    return MarketsConfig(
        indices=[IndexEntry.model_validate(i) for i in idx["indices"]],
        index_history_start=str(idx["history_start"]),
        index_groups={k: IndexGroup.model_validate(v) for k, v in etf["index_groups"].items()},
        bond_categories=dict(etf["bond_categories"]),
        rates=[RateEntry.model_validate(r) for r in etf.get("rates", [])],
        etfs=_read_csv(config_dir / "etfs.csv"),
        bonds=_read_csv(config_dir / "bond_etfs.csv"),
    )
