"""Load, validate and fingerprint the model configuration under config/model/.

The fingerprint is a SHA-256 over the parsed YAML (not the raw text), so comments and
formatting do not count as a model change, but every value does. Each fingerprint must be
registered under its version in versions.lock.yaml; changing the model without bumping the
version fails both the tests and server start-up.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.modelconfig.schema import AssignmentConfig, MetricDef, ModelSettings, TechnicalConfig, Template

LOCK_FILE = "versions.lock.yaml"


class ModelConfigError(Exception):
    pass


@dataclass(frozen=True)
class ModelConfig:
    settings: ModelSettings
    technical: TechnicalConfig
    metrics: dict[str, MetricDef]
    templates: dict[str, Template]
    assignment: AssignmentConfig
    raw: dict[str, Any]
    config_hash: str

    @property
    def version(self) -> str:
        return self.settings.version

    def letter_scale_for(self, template_id: str) -> dict[str, float]:
        """The template's calibrated letter bounds, or the global provisional ones."""
        t = self.templates.get(template_id)
        return (t.letter_scale if t is not None and t.letter_scale else None) or self.settings.letter_scale

    def templates_for_tab(self, tab: str) -> list[Template]:
        return [t for t in self.templates.values() if t.tab == tab]


def _read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ModelConfigError(f"cannot read {path}: {exc}") from exc


def fingerprint(raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_model_config(model_dir: Path, *, check_lock: bool = True) -> ModelConfig:
    raw: dict[str, Any] = {
        "model": _read_yaml(model_dir / "model.yaml"),
        "technical": _read_yaml(model_dir / "technical.yaml"),
        "metrics": _read_yaml(model_dir / "metrics.yaml"),
        "assignment": _read_yaml(model_dir / "assignment.yaml"),
        "templates": {},
    }
    for path in sorted((model_dir / "templates").glob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict) or data.get("id") != path.stem:
            raise ModelConfigError(f"{path.name}: `id` must equal the file name ({path.stem})")
        raw["templates"][path.stem] = data
    config = config_from_raw(raw)
    if check_lock:
        verify_lock(config, model_dir)
    return config


def config_from_raw(raw: dict[str, Any]) -> ModelConfig:
    """Build a validated ModelConfig from parsed YAML, e.g. the copy stored in model_version.config."""
    try:
        settings = ModelSettings.model_validate(raw["model"])
        technical = TechnicalConfig.model_validate(raw["technical"])
        metrics = {k: MetricDef.model_validate(v) for k, v in raw["metrics"].items()}
        templates = {k: Template.model_validate(v) for k, v in raw["templates"].items()}
        assignment = AssignmentConfig.model_validate(raw["assignment"])
    except ValidationError as exc:
        raise ModelConfigError(str(exc)) from exc

    _check_metric_references(templates, metrics)
    _check_assignment(assignment, templates)
    return ModelConfig(
        settings=settings,
        technical=technical,
        metrics=metrics,
        templates=templates,
        assignment=assignment,
        raw=raw,
        config_hash=fingerprint(raw),
    )


def _check_assignment(assignment: AssignmentConfig, templates: dict[str, Template]) -> None:
    named = [r.template for r in assignment.crypto.rules] + [assignment.crypto.default]
    named += list(assignment.crypto.overrides.values())
    for template_id in named:
        if template_id not in templates or templates[template_id].tab != "crypto":
            raise ModelConfigError(f"assignment names unknown crypto template {template_id}")
    stocks = assignment.stocks
    stock_named = [] if stocks is None else [r.template for r in stocks.rules] + [stocks.default]
    stock_named += [o.template for o in stocks.overrides.values() if o.template] if stocks else []
    for template_id in stock_named:
        if template_id not in templates or templates[template_id].tab != "stocks":
            raise ModelConfigError(f"assignment names unknown stock template {template_id}")


def _check_metric_references(templates: dict[str, Template], metrics: dict[str, MetricDef]) -> None:
    errors = []
    for t in templates.values():
        for missing in sorted(t.metric_ids() - metrics.keys()):
            errors.append(f"{t.id}: metric `{missing}` is not in metrics.yaml")
        for p in t.pillars:
            for m in p.metrics:
                if m.id in metrics and metrics[m.id].direction == "none":
                    errors.append(f"{t.id}.{p.id}: metric `{m.id}` has no direction and cannot be scored")
    if errors:
        raise ModelConfigError("\n".join(errors))


def read_lock(model_dir: Path) -> dict[str, str]:
    path = model_dir / LOCK_FILE
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in (_read_yaml(path) or {}).items()}


def verify_lock(config: ModelConfig, model_dir: Path) -> None:
    lock = read_lock(model_dir)
    locked = lock.get(config.version)
    if locked == config.config_hash:
        return
    if locked is None:
        hint = "run `python -m app.cli lock-model` to register this version"
    else:
        hint = "the model changed: bump `version` in model.yaml, then run `python -m app.cli lock-model`"
    raise ModelConfigError(f"model version {config.version} does not match {LOCK_FILE}; {hint}")


def write_lock(config: ModelConfig, model_dir: Path) -> None:
    lock = read_lock(model_dir)
    if config.version in lock and lock[config.version] != config.config_hash:
        raise ModelConfigError(
            f"version {config.version} is already locked to another configuration; bump the version"
        )
    if config.config_hash in lock.values() and lock.get(config.version) != config.config_hash:
        raise ModelConfigError("this exact configuration is already locked under another version")
    lock[config.version] = config.config_hash
    header = "# Generated by `python -m app.cli lock-model`. One line per model version; never edit old lines.\n"
    (model_dir / LOCK_FILE).write_text(header + yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
