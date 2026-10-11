from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class Tab(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    slug: str
    label_nl: str
    phase: int
    source: Literal["market_cap_rank", "static_list", "user_selection", "none"]
    description_nl: str
    templates: list[str]
    size: int | None = None
    extra_lists: list[str] = []
    excluded_filters: list[str] = []
    filters: list[str] = []
    group_by: str | None = None


class Universes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    size_options: list[int]
    tabs: list[Tab]

    @model_validator(mode="after")
    def sizes_allowed(self) -> "Universes":
        for tab in self.tabs:
            if tab.size is not None and tab.size not in self.size_options:
                raise ValueError(f"tab {tab.slug}: size {tab.size} not in {self.size_options}")
        slugs = [t.slug for t in self.tabs]
        if len(slugs) != len(set(slugs)):
            raise ValueError("duplicate tab slug")
        return self


def load_universes(path: Path) -> Universes:
    with path.open(encoding="utf-8") as fh:
        return Universes.model_validate(yaml.safe_load(fh))
