from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str
    uitleg: str


class Glossary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    terms: dict[str, Entry]
    metrics: dict[str, Entry]


def load_glossary(path: Path) -> Glossary:
    with path.open(encoding="utf-8") as fh:
        return Glossary.model_validate(yaml.safe_load(fh))


@lru_cache
def cached_glossary(path: Path) -> Glossary:
    return load_glossary(path)
