"""Champion, challengers and the activation log (chapter 8, "Kampioen en uitdager").

- The configuration files in config/model are the anchor: their version is the baseline with the starting
  weights w0. A new file version (a change the owner made and locked) becomes active as a new baseline.
- A challenger is a full model version stored in model_version (never in the files). It is created only from
  a weight proposal the owner approved and that passes the guardrails, and it runs in the shadow: graded
  every night next to the champion, never shown.
- Only `promote` (all promotion checks passed, at most one switch per 6 months, an explicit owner action) and
  `rollback` (always allowed, one click) add a row to the append-only model_activation log. Nothing else in
  the app changes which weights are used.
"""

import copy
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.evaluation.proposals import next_version
from app.learning.weights import Guardrails, check_weights
from app.modelconfig import ModelConfig
from app.modelconfig.loader import config_from_raw
from app.registry import register_model_version


class LearningError(Exception):
    """A refused action, with the reason in Dutch."""


def weights_of(config: ModelConfig, template_id: str) -> dict[str, float]:
    return {p.id: float(p.weight) for p in config.templates[template_id].pillars}


def _latest_activation(session: Session):
    return session.execute(text(
        "SELECT * FROM model_activation ORDER BY activated_at DESC, id DESC LIMIT 1")).mappings().first()


def sync_baseline(session: Session, file_config: ModelConfig) -> int:
    """Register the file configuration; a file version not yet activated as baseline becomes active."""
    file_id = register_model_version(session, file_config).id
    last_baseline = session.execute(text(
        "SELECT model_version_id FROM model_activation WHERE kind = 'baseline' ORDER BY id DESC LIMIT 1")).scalar()
    if last_baseline != file_id:
        session.execute(text(
            "INSERT INTO model_activation (model_version_id, kind, note) VALUES (:v, 'baseline', :n)"),
            {"v": file_id, "n": f"Configuratiebestanden, modelversie {file_config.version}"})
        session.commit()
    return file_id


def config_of(session: Session, model_version_id: int) -> ModelConfig:
    row = session.execute(text("SELECT version, config, config_hash FROM model_version WHERE id = :i"),
                          {"i": model_version_id}).first()
    if row is None:
        raise LearningError(f"Modelversie {model_version_id} bestaat niet.")
    config = config_from_raw(row.config if isinstance(row.config, dict) else json.loads(row.config))
    if config.config_hash != row.config_hash:
        raise LearningError(f"Opgeslagen configuratie van {row.version} klopt niet met haar vingerafdruk.")
    return config


def load_active(session: Session, file_config: ModelConfig) -> tuple[ModelConfig, int]:
    """The model the app grades with: the latest activation (the file version unless the owner switched)."""
    file_id = sync_baseline(session, file_config)
    active = _latest_activation(session)["model_version_id"]
    return (file_config, file_id) if active == file_id else (config_of(session, active), active)


def baseline(session: Session) -> tuple[ModelConfig, int]:
    """The anchor with the starting weights w0: the latest baseline activation."""
    vid = session.execute(text(
        "SELECT model_version_id FROM model_activation WHERE kind = 'baseline' ORDER BY id DESC LIMIT 1")).scalar()
    return config_of(session, vid), vid


def shadow_challengers(session: Session) -> list[tuple[ModelConfig, int, int]]:
    """(config, model_version_id, challenger id) of every challenger running in the shadow."""
    rows = session.execute(text("SELECT id, model_version_id FROM challenger WHERE status = 'shadow' ORDER BY id"))
    return [(config_of(session, r.model_version_id), r.model_version_id, r.id) for r in rows.all()]


def _next_free_version(session: Session, base: str) -> str:
    taken = set(session.execute(text("SELECT version FROM model_version")).scalars())
    v = next_version(base)
    while v in taken:
        v = next_version(v)
    return v


def create_challenger(session: Session, proposal_id: int, champion: ModelConfig, champion_id: int,
                      guardrails: Guardrails) -> int:
    """From an approved weight proposal: check the guardrails again, store the challenger model version and
    start it in the shadow. Returns the challenger id."""
    p = session.execute(text("SELECT * FROM model_proposal WHERE id = :i"), {"i": proposal_id}).mappings().first()
    if p is None or p["kind"] != "weights":
        raise LearningError(f"Voorstel {proposal_id} is geen gewichtsvoorstel.")
    if p["status"] != "approved":
        raise LearningError(f"Voorstel {proposal_id} is niet goedgekeurd (status {p['status']}).")
    if session.execute(text("SELECT 1 FROM challenger WHERE proposal_id = :i"), {"i": proposal_id}).first():
        raise LearningError(f"Voorstel {proposal_id} draait al als uitdager.")
    payload = p["payload"] if isinstance(p["payload"], dict) else json.loads(p["payload"])
    base, _ = baseline(session)
    problems = []
    for template_id, weights in payload.items():
        if template_id not in champion.templates:
            problems.append(f"{template_id}: onbekend sjabloon")
            continue
        current = weights_of(champion, template_id)
        problems += [f"{template_id}: {x}" for x in check_weights(weights_of(base, template_id), current,
                                                                 weights, guardrails, None)]
    if problems:
        raise LearningError("Vangrail geschonden: " + "; ".join(problems))
    raw = copy.deepcopy(champion.raw)
    for template_id, weights in payload.items():
        for pillar in raw["templates"][template_id]["pillars"]:
            pillar["weight"] = weights[pillar["id"]]
    top = max(session.execute(text("SELECT version FROM model_version")).scalars(),
              key=lambda v: tuple(int(x) for x in v.split(".")))
    version = _next_free_version(session, top)
    raw["model"]["version"] = version
    raw["model"]["description"] = (f"Uitdager uit voorstel {proposal_id}: gewichten van "
                                   f"{', '.join(sorted(payload))} aangepast; verder gelijk aan {champion.version}.")
    challenger = config_from_raw(raw)
    vid = register_model_version(session, challenger).id
    cid = session.execute(text(
        """INSERT INTO challenger (model_version_id, champion_version_id, proposal_id, status)
           VALUES (:v, :c, :p, 'shadow') RETURNING id"""), {"v": vid, "c": champion_id, "p": proposal_id}).scalar()
    session.commit()
    return cid


def last_switch(session: Session) -> datetime | None:
    return session.execute(text("SELECT max(activated_at) FROM model_activation WHERE kind = 'promote'")).scalar()


def promote(session: Session, challenger_id: int, checks: list[dict], min_months_between: int,
            now: datetime | None = None) -> int:
    """Make a challenger the champion. Refused unless every promotion check passed and the last switch is at
    least `min_months_between` months ago. Returns the new active model_version_id."""
    now = now or datetime.now(UTC)
    c = session.execute(text("SELECT * FROM challenger WHERE id = :i"), {"i": challenger_id}).mappings().first()
    if c is None or c["status"] != "shadow":
        raise LearningError(f"Uitdager {challenger_id} draait niet in de schaduw.")
    active = _latest_activation(session)["model_version_id"]
    if c["champion_version_id"] != active:
        raise LearningError("De kampioen is sinds de start van deze uitdager gewisseld; start een nieuwe uitdager.")
    failed = [ch["label_nl"] for ch in checks if not ch["passed"]]
    if not checks or failed:
        raise LearningError("Niet alle toetsen voor promotie zijn gehaald: " + "; ".join(failed or ["geen toetsen"]))
    previous = last_switch(session)
    if previous is not None and now - previous < timedelta(days=round(30.44 * min_months_between)):
        raise LearningError(f"Hoogstens één wissel per {min_months_between} maanden; de vorige was op "
                            f"{previous:%d-%m-%Y}.")
    session.execute(text(
        """INSERT INTO model_activation (model_version_id, kind, proposal_id, note)
           VALUES (:v, 'promote', :p, :n)"""),
        {"v": c["model_version_id"], "p": c["proposal_id"], "n": f"Uitdager {challenger_id} gepromoveerd"})
    session.execute(text("UPDATE challenger SET status = 'promoted', ended_at = now() WHERE id = :i"),
                    {"i": challenger_id})
    # Other challengers were measured against the old champion.
    session.execute(text("UPDATE challenger SET status = 'retired', ended_at = now() WHERE status = 'shadow'"))
    session.commit()
    return c["model_version_id"]


def rollback(session: Session) -> int:
    """Undo the last promotion: back to the model that was active right before it. Always allowed, but only
    directly after a promotion, so a rollback can never re-activate a model that did not pass the checks."""
    rows = session.execute(text(
        "SELECT id, kind, model_version_id FROM model_activation ORDER BY activated_at DESC, id DESC")).all()
    if not rows or rows[0].kind != "promote":
        raise LearningError("Alleen de laatste promotie kan worden teruggedraaid, en die is er niet.")
    if len(rows) < 2:
        raise LearningError("Er is geen eerder model om naar terug te gaan.")
    previous = rows[1].model_version_id
    session.execute(text(
        "INSERT INTO model_activation (model_version_id, kind, note) VALUES (:v, 'rollback', :n)"),
        {"v": previous, "n": "Promotie teruggedraaid door de eigenaar"})
    session.execute(text(
        "UPDATE challenger SET status = 'retired' WHERE model_version_id = :v AND status = 'promoted'"),
        {"v": rows[0].model_version_id})
    session.commit()
    return previous


def history(session: Session) -> list[dict]:
    return [dict(r) for r in session.execute(text(
        """SELECT a.id, a.kind, a.activated_at, a.note, a.proposal_id, v.version
           FROM model_activation a JOIN model_version v ON v.id = a.model_version_id
           ORDER BY a.activated_at DESC, a.id DESC LIMIT 20""")).mappings()]
