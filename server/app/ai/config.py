"""config/ai.yaml: model per component, prices and the monthly budget (chapter 9)."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ExplanationSettings:
    model: str
    prompt_version: str
    max_tokens: int
    effort: str
    regenerate_shift_points: float
    min_words: int
    max_words: int
    batch_poll_hours: int


@dataclass(frozen=True)
class ComponentSettings:
    model: str
    prompt_version: str
    max_tokens: int
    effort: str
    extra: dict


@dataclass(frozen=True)
class AiConfig:
    api_key_env: str
    monthly_budget_usd: float
    pricing: dict[str, dict[str, float]]
    cache_write_factor: float
    cache_read_factor: float
    batch_discount: float
    explanation: ExplanationSettings
    components: dict[str, ComponentSettings]

    def cost_usd(self, model: str, usage: dict, batch: bool) -> float:
        """Cost of one call from its token usage; unknown models are priced as the most expensive one."""
        price = self.pricing.get(model) or max(self.pricing.values(), key=lambda p: p["output"])
        per = 1_000_000
        cost = (usage.get("input_tokens", 0) * price["input"]
                + usage.get("cache_creation_input_tokens", 0) * price["input"] * self.cache_write_factor
                + usage.get("cache_read_input_tokens", 0) * price["input"] * self.cache_read_factor
                + usage.get("output_tokens", 0) * price["output"]) / per
        return cost * (self.batch_discount if batch else 1.0)


def load_ai_config(path: Path) -> AiConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    e = raw["components"]["explanation"]
    for name, c in raw["components"].items():
        if c["model"] not in raw["pricing"]:
            raise ValueError(f"ai.yaml: geen prijs voor model {c['model']} ({name})")
    base = {"model", "prompt_version", "max_tokens", "effort"}
    components = {name: ComponentSettings(c["model"], c["prompt_version"], int(c["max_tokens"]), c["effort"],
                                          {k: v for k, v in c.items() if k not in base})
                  for name, c in raw["components"].items()}
    return AiConfig(
        api_key_env=raw["api_key_env"], monthly_budget_usd=float(raw["monthly_budget_usd"]),
        pricing={k: {"input": float(v["input"]), "output": float(v["output"])} for k, v in raw["pricing"].items()},
        cache_write_factor=float(raw["cache_write_factor"]), cache_read_factor=float(raw["cache_read_factor"]),
        batch_discount=float(raw["batch_discount"]),
        explanation=ExplanationSettings(
            model=e["model"], prompt_version=e["prompt_version"], max_tokens=int(e["max_tokens"]),
            effort=e["effort"], regenerate_shift_points=float(e["regenerate_shift_points"]),
            min_words=int(e["words"]["min"]), max_words=int(e["words"]["max"]),
            batch_poll_hours=int(e["batch_poll_hours"]),
        ),
        components=components,
    )
