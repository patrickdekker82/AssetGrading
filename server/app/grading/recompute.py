"""Recompute a stored grade from its snapshot alone (acceptance criterion: exactly reproducible).

The snapshot holds the engine input (metric values, percentiles, flags, hysteresis state) and the peer
values behind every percentile. Recomputing uses the model configuration stored with the snapshot's
model version, so later model changes never alter how an old grade is reproduced.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.grading.engine import GradeInput, grade
from app.grading.percentiles import percentile_of
from app.modelconfig import ModelConfig
from app.modelconfig.loader import config_from_raw, fingerprint
from app.models import GradeSnapshot, ModelVersion

COMPARED = ["status", "score", "quality", "timing", "coverage", "raw_letter", "hysteresis_letter", "letter",
            "letter_low", "letter_high", "score_low", "score_high", "peg_safety", "labels"]


@dataclass
class Check:
    snapshot_id: int
    ok: bool
    differences: list[str]


@lru_cache(maxsize=16)
def _config_for(config_hash: str, raw_json: str) -> ModelConfig:
    return config_from_raw(json.loads(raw_json))


def model_config_for(session: Session, model_version_id: int) -> ModelConfig:
    mv = session.get(ModelVersion, model_version_id)
    if fingerprint(mv.config) != mv.config_hash:
        raise ValueError(f"model_version {mv.version}: stored configuration does not match its fingerprint")
    return _config_for(mv.config_hash, json.dumps(mv.config, sort_keys=True))


def recompute(snapshot: GradeSnapshot, config: ModelConfig) -> Check:
    diffs: list[str] = []
    inp = GradeInput.from_dict(snapshot.inputs["grade_input"])
    winsor = tuple(config.settings.scoring.winsorize)
    for metric_id, peers in (snapshot.inputs.get("peers") or {}).items():
        values = peers.get("values")
        mi = inp.metrics.get(metric_id)
        if values is None or mi is None or mi.value is None:
            continue
        expected = None
        if len(values) >= 3:
            higher = config.metrics[metric_id].direction == "higher"
            expected = percentile_of(mi.value, values, higher_is_better=higher, winsor=winsor)
        if expected != mi.peer_pct:
            diffs.append(f"percentile {metric_id}: stored {mi.peer_pct}, recomputed {expected}")
    result = grade(inp, config).to_dict()
    stored: dict[str, Any] = snapshot.result
    for key in COMPARED:
        if result.get(key) != stored.get(key):
            diffs.append(f"{key}: stored {stored.get(key)!r}, recomputed {result.get(key)!r}")
    if [g["status"] for g in result["gates"]] != [g["status"] for g in stored["gates"]]:
        diffs.append("gate outcomes differ")
    return Check(snapshot.id, not diffs, diffs)


def verify_all(session: Session, limit: int | None = None) -> list[Check]:
    stmt = select(GradeSnapshot).order_by(GradeSnapshot.id.desc())
    if limit:
        stmt = stmt.limit(limit)
    checks = []
    for snap in session.scalars(stmt):
        checks.append(recompute(snap, model_config_for(session, snap.model_version_id)))
    return checks
