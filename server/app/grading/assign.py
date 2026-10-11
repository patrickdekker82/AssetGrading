"""Which template grades an asset (chapter 6, "Toewijzing"). Pure functions of model configuration."""

from collections.abc import Iterable

from app.modelconfig.schema import AssignmentConfig


def _norm(values: Iterable[str]) -> set[str]:
    return {v.strip().lower() for v in values}


def assign_crypto(coingecko_id: str, categories: list[str] | None, override: str | None,
                  cfg: AssignmentConfig) -> str:
    """Manual override first, then the configured overrides, then the first matching category rule."""
    if override:
        return override
    rules = cfg.crypto
    if coingecko_id in rules.overrides:
        return rules.overrides[coingecko_id]
    cats = _norm(categories or [])
    for rule in rules.rules:
        if cats & _norm(rule.any_category):
            return rule.template
    return rules.default


def crypto_tags(categories: list[str] | None, alias_kinds: Iterable[str], cfg: AssignmentConfig) -> list[str]:
    cats, kinds = _norm(categories or []), set(alias_kinds)
    tags = []
    for tag, rule in cfg.crypto.tags.items():
        if rule.any_category and cats & _norm(rule.any_category):
            tags.append(tag)
        elif rule.alias_kind and rule.alias_kind in kinds:
            tags.append(tag)
    return sorted(tags)
