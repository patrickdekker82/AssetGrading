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


def _in(code: int | None, ranges) -> bool:
    return code is not None and any(lo <= code <= hi for lo, hi in ranges)


def assign_stock(key: str, sic: int | None, cfg: AssignmentConfig) -> tuple[str, list[str], str]:
    """(template, tags, sector) for a stock: by SIC code, with manual overrides by asset key (slug)."""
    rules = cfg.stocks
    over = rules.overrides.get(key)
    template, tags = rules.default, []
    for rule in rules.rules:
        if _in(sic, rule.sic):
            template, tags = rule.template, [rule.tag] if rule.tag else []
            break
    sector = next((s.sector for s in rules.sectors if _in(sic, s.sic)), rules.default_sector)
    if over:
        if over.template:
            template, tags = over.template, []   # a template override also replaces the rule's tag
        tags = [over.tag] if over.tag else tags
        sector = over.sector or sector
    return template, tags, sector
