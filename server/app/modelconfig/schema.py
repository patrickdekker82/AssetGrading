"""Typed schema for the YAML model configuration (chapter 5 and 6).

Validation is strict (`extra="forbid"`) so a typo in a YAML key fails loudly instead of
silently changing the model.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Grade = Literal["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]
Op = Literal["<", "<=", ">", ">="]
Direction = Literal["higher", "lower", "none"]
TabSlug = Literal["crypto", "stocks", "etfs", "commodities", "fx", "bonds", "indices"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricDef(Strict):
    direction: Direction
    unit: Literal["ratio", "multiple", "score", "eur", "years", "days", "count", "z"]
    scoring: Literal["percentile", "direct"] = "percentile"


class MetricRef(Strict):
    id: str
    weight: float = Field(default=1.0, gt=0)
    applies_to: list[str] | None = None
    fallback_for: str | None = None

    @model_validator(mode="before")
    @classmethod
    def from_string(cls, value: Any) -> Any:
        return {"id": value} if isinstance(value, str) else value


class Pillar(Strict):
    id: str
    name_nl: str
    weight: float = Field(gt=0, le=100)
    timing: bool = False          # excluded from the Kwaliteit sub-score
    valuation: bool = False       # 80% peer / 20% own-history mix applies
    horizon_months: list[int] | None = None
    metrics: list[MetricRef] = Field(min_length=1)

    @model_validator(mode="after")
    def check_metrics(self) -> "Pillar":
        ids = [m.id for m in self.metrics]
        if len(ids) != len(set(ids)):
            raise ValueError(f"pillar {self.id}: duplicate metric")
        for m in self.metrics:
            if m.fallback_for and m.fallback_for not in ids:
                raise ValueError(f"pillar {self.id}: {m.id} is fallback for unknown metric {m.fallback_for}")
        return self


class GateBase(Strict):
    id: str
    reason_nl: str
    applies_to: list[str] | None = None


class MetricThresholdGate(GateBase):
    kind: Literal["metric_threshold"]
    metric: str
    op: Op
    value: float
    cap: Grade


class PillarFloorGate(GateBase):
    kind: Literal["pillar_floor"]
    threshold: float = Field(ge=0, le=100)
    cap: Grade


class FlagGate(GateBase):
    kind: Literal["flag"]
    flag: str
    cap: Grade | None = None
    label_nl: str | None = None

    @model_validator(mode="after")
    def needs_effect(self) -> "FlagGate":
        if self.cap is None and self.label_nl is None:
            raise ValueError(f"gate {self.id}: needs a cap or a label")
        return self


class PillarAgreementGate(GateBase):
    kind: Literal["pillar_agreement"]
    min_pillars: int = Field(ge=1)
    set_grade: Grade
    label_nl: str
    # "at_most": only pulls better letters down to set_grade (model 0.5.0 and earlier). "exact": the letter
    # becomes set_grade, also from below, as chapter 6 asks for currency pairs ("C met het label geen voordeel").
    mode: Literal["at_most", "exact"] = "at_most"


Gate = Annotated[
    MetricThresholdGate | PillarFloorGate | FlagGate | PillarAgreementGate,
    Field(discriminator="kind"),
]


class Condition(Strict):
    metric: str
    op: Op
    value: float


class PillarScale(Strict):
    pillar: str
    factor: float = Field(gt=0)


class WeightRule(Strict):
    id: str
    when: Condition
    scale_pillar: PillarScale
    reason_nl: str


class ProductJudgement(Strict):
    name_nl: str
    note_nl: str | None = None
    metrics: list[str] = Field(min_length=1)
    gates: list[Gate] = []


class PegSafety(Strict):
    scale: tuple[int, int]
    peg_deviation_max_bp: float = Field(gt=0)
    factors: list[str] = Field(min_length=1)


def check_letter_scale(v: dict[str, float]) -> dict[str, float]:
    order = [v[k] for k in ("A", "B", "C", "D", "F")]
    if order != sorted(order, reverse=True) or len(set(order)) != 5 or v["F"] != 0:
        raise ValueError("letter_scale must strictly descend from A to F, with F at 0")
    return v


class Template(Strict):
    id: str
    name_nl: str
    tab: TabSlug
    grading: Literal["weighted", "safety_only", "peg_safety"]
    assign_on: Literal["sector_code", "product_type", "coingecko_category"]
    peer_group: str
    regime_adjust: bool
    pillars: list[Pillar]
    gates: list[Gate]
    horizon_months: list[int] | None = None
    note_nl: str | None = None
    label_nl: str | None = None
    base_grade: Grade | None = None
    max_grade: Grade | None = None
    display_metrics: list[str] = []
    product: ProductJudgement | None = None
    peg_safety: PegSafety | None = None
    weight_rules: list[WeightRule] = []
    own_history: dict[str, float] | None = None
    # Metrics compared with their own history even when the template compares assets with each other
    # (macro series that are the same for every asset in the group, such as the dollar index).
    own_history_metrics: list[str] = []
    excluded_metrics: list[str] = []
    show_btc_relative: bool = False
    show_underlying_timing: bool = False
    mirror_pairs: bool = False
    flag_macro_price_divergence: bool = False
    # Calibrated lower bounds per letter for this template (phase 8); absent: the global letter_scale.
    letter_scale: dict[Literal["A", "B", "C", "D", "F"], float] | None = None

    @field_validator("letter_scale")
    @classmethod
    def scale_descends(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        return None if v is None else check_letter_scale(v)
    safety_params: dict[str, float] = {}

    @model_validator(mode="after")
    def check_grading(self) -> "Template":
        if self.grading == "weighted":
            if not self.pillars:
                raise ValueError(f"{self.id}: weighted template needs pillars")
            total = sum(p.weight for p in self.pillars)
            if abs(total - 100) > 1e-9:
                raise ValueError(f"{self.id}: pillar weights sum to {total}, expected 100")
            if all(p.timing for p in self.pillars):
                raise ValueError(f"{self.id}: needs at least one non-timing pillar for Kwaliteit")
        elif self.pillars:
            raise ValueError(f"{self.id}: {self.grading} template must not have pillars")
        if self.grading == "safety_only" and self.base_grade is None:
            raise ValueError(f"{self.id}: safety_only template needs base_grade")
        if self.grading == "peg_safety" and self.peg_safety is None:
            raise ValueError(f"{self.id}: peg_safety template needs a peg_safety block")
        pillar_ids = [p.id for p in self.pillars]
        if len(pillar_ids) != len(set(pillar_ids)):
            raise ValueError(f"{self.id}: duplicate pillar id")
        for rule in self.weight_rules:
            if rule.scale_pillar.pillar not in pillar_ids:
                raise ValueError(f"{self.id}: weight rule {rule.id} names unknown pillar")
        gate_ids = [g.id for g in self.gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError(f"{self.id}: duplicate gate id")
        return self

    def metric_ids(self) -> set[str]:
        """Every metric id this template references, for catalog checks."""
        ids = {m.id for p in self.pillars for m in p.metrics}
        gates = list(self.gates) + (list(self.product.gates) if self.product else [])
        ids |= {g.metric for g in gates if isinstance(g, MetricThresholdGate)}
        ids |= set(self.display_metrics)
        ids |= set(self.product.metrics) if self.product else set()
        ids |= set(self.peg_safety.factors) if self.peg_safety else set()
        ids |= {r.when.metric for r in self.weight_rules}
        return ids


class ScoringSettings(Strict):
    winsorize: tuple[float, float]
    # True from model 0.6.0: the clipping bounds come from the comparison group alone. Before, the asset's own
    # value was added once more (it is already in the group), which shifted the bounds slightly.
    winsor_excludes_self: bool = False
    valuation_mix: dict[Literal["peer", "own_history"], float]

    @field_validator("valuation_mix")
    @classmethod
    def sums_to_one(cls, v: dict[str, float]) -> dict[str, float]:
        if abs(sum(v.values()) - 1) > 1e-9:
            raise ValueError("valuation_mix must sum to 1")
        return v


class CoverageSettings(Strict):
    provisional_below: float = Field(gt=0, lt=1)
    hidden_below: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def ordered(self) -> "CoverageSettings":
        if self.hidden_below >= self.provisional_below:
            raise ValueError("hidden_below must be lower than provisional_below")
        return self


class PeerSettings(Strict):
    min_group_size: int = Field(ge=2)
    broaden: dict[str, str]
    groups: dict[str, list[str]]
    own_history_years: float = Field(gt=0)

    @model_validator(mode="after")
    def broaden_targets_exist(self) -> "PeerSettings":
        for target in self.broaden.values():
            if target not in self.groups:
                raise ValueError(f"peers.broaden points to unknown group {target}")
        return self


class StabilitySettings(Strict):
    hysteresis_points: float = Field(ge=0)
    hysteresis_days: int = Field(ge=0)
    band_weight_shift: float = Field(ge=0, lt=1)


class RegimeVote(Strict):
    series: str
    calm_below_pct: float
    stress_above_pct: float
    lookback_years: float | None = None
    min_history_years: float | None = None


class RegimeSettings(Strict):
    states: list[str]
    world_index: dict[str, Any]
    high_yield_spread: RegimeVote
    vix: RegimeVote
    risk_on_at: int
    risk_off_at: int
    min_inputs: int
    scores: dict[str, float]
    grade_shift: dict[str, int]
    max_grade_shift_steps: int


class EtfSettings(Strict):
    tracking_years: list[int]
    max_plausible_tracking_difference: float
    replication_scores: dict[str, float]
    lending_scores: dict[str, float]
    min_peers: int


class BondSettings(Strict):
    expected_loss_pct: dict[str, float]
    rating_points: dict[str, float]
    stale_days: int


class ModelSettings(Strict):
    version: str
    description: str | None = None
    default_horizon_months: list[int]
    letter_scale: dict[Literal["A", "B", "C", "D", "F"], float]
    plus_minus: Literal["thirds"]
    scoring: ScoringSettings
    coverage: CoverageSettings
    peers: PeerSettings
    stability: StabilitySettings
    regime: RegimeSettings | dict[str, Any]     # a plain dict in model versions before 0.4.0
    etf: EtfSettings | None = None
    bond: BondSettings | None = None
    etf_tax: dict[str, Any]
    forbidden_words_nl: list[str]

    @field_validator("version")
    @classmethod
    def semver(cls, v: str) -> str:
        if not re.fullmatch(r"\d+\.\d+\.\d+", v):
            raise ValueError("version must look like 1.2.3")
        return v

    @field_validator("letter_scale")
    @classmethod
    def descending(cls, v: dict[str, float]) -> dict[str, float]:
        return check_letter_scale(v)


class TechnicalBlock(Strict):
    id: str
    weight: float = Field(gt=0)
    tests: list[str] | None = None
    measures: list[str] | None = None


class TechnicalParams(Strict):
    sma_short: int
    sma_long: int
    sma_long_rising_lag: int
    months_for_10m_average: int
    momentum_long: int
    momentum_skip: int
    momentum_short: int
    high_window: int
    relative_windows: list[int]
    volatility_window: int
    volatility_history: int
    min_block_coverage: float = Field(gt=0, le=1)
    benchmark: str
    days_per_year: int = 365


class TechnicalConfig(Strict):
    blocks: list[TechnicalBlock]
    params: dict[str, TechnicalParams]
    rules: dict[str, Any]
    chart_sets: dict[str, dict[Literal["score", "context"], list[str]]]

    @model_validator(mode="after")
    def weights(self) -> "TechnicalConfig":
        total = sum(b.weight for b in self.blocks)
        if abs(total - 100) > 1e-9:
            raise ValueError(f"technical blocks sum to {total}, expected 100")
        return self


class CategoryRule(Strict):
    template: str
    any_category: list[str]


class TagRule(Strict):
    any_category: list[str] | None = None
    alias_kind: str | None = None


class CryptoAssignment(Strict):
    overrides: dict[str, str]
    rules: list[CategoryRule]
    default: str
    tags: dict[str, TagRule]


class SicRule(Strict):
    template: str
    sic: list[tuple[int, int]]
    tag: str | None = None


class SectorRule(Strict):
    sector: str
    sic: list[tuple[int, int]]


class StockOverride(Strict):
    template: str | None = None
    tag: str | None = None
    sector: str | None = None


class StockAssignment(Strict):
    rules: list[SicRule]
    default: str
    sectors: list[SectorRule]
    default_sector: str
    overrides: dict[str, StockOverride]


class AssignmentConfig(Strict):
    crypto: CryptoAssignment
    stocks: StockAssignment | None = None   # absent in model versions before 0.3.0
