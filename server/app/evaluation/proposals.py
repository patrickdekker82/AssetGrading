"""Model proposals (chapter 8): open -> approved or rejected by the owner -> written into a new model version.

The server never changes the model on its own: it only records the owner's decision. Writing an approved
proposal into config/model and locking the new version is a separate command run by the owner (the
configuration is mounted read-only into the containers).
"""

import json
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.modelconfig import ModelConfig, load_model_config
from app.modelconfig.loader import write_lock


def decide(session: Session, proposal_id: int, approve: bool) -> dict:
    row = session.execute(text("SELECT id, status FROM model_proposal WHERE id = :i"), {"i": proposal_id}).first()
    if row is None:
        raise KeyError(proposal_id)
    if row.status != "open":
        raise ValueError(f"Voorstel {proposal_id} is al {row.status}.")
    status = "approved" if approve else "rejected"
    session.execute(text("UPDATE model_proposal SET status = :s, decided_at = now() WHERE id = :i"),
                    {"s": status, "i": proposal_id})
    session.commit()
    return {"id": proposal_id, "status": status}


def next_version(version: str) -> str:
    major, minor, _ = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


SCALE_BLOCK = re.compile(r"\n# Calibrated letter bounds.*?\nletter_scale: \{[^}]*\}\n", re.DOTALL)


def write_letter_scale(template_file: Path, scale: dict[str, float], note: str) -> None:
    body = SCALE_BLOCK.sub("\n", template_file.read_text(encoding="utf-8")).rstrip("\n") + "\n"
    flow = ", ".join(f"{k}: {scale[k]:g}" for k in ("A", "B", "C", "D", "F"))
    template_file.write_text(body + f"\n# Calibrated letter bounds ({note})\nletter_scale: {{{flow}}}\n",
                             encoding="utf-8")


def apply_proposal(sf: sessionmaker[Session], model_dir: Path, config: ModelConfig, proposal_id: int) -> str:
    """Write an approved letter-scale proposal into the templates, bump the version and lock it."""
    with sf() as session:
        p = session.execute(text("SELECT * FROM model_proposal WHERE id = :i"), {"i": proposal_id}).mappings().first()
    if p is None:
        raise ValueError(f"Voorstel {proposal_id} bestaat niet.")
    if p["status"] != "approved":
        raise ValueError(f"Voorstel {proposal_id} is niet goedgekeurd (status {p['status']}).")
    if p["applied_version"]:
        raise ValueError(f"Voorstel {proposal_id} zit al in modelversie {p['applied_version']}.")
    if p["kind"] != "letter_scale":
        raise ValueError(f"Voorstellen van het soort {p['kind']} worden in fase 9 toegepast.")
    payload = p["payload"] if isinstance(p["payload"], dict) else json.loads(p["payload"])
    version = next_version(config.version)
    note = f"backtest run {p['run_id']}, proposal {proposal_id}, model {version}"
    for template_id, scale in payload.items():
        write_letter_scale(model_dir / "templates" / f"{template_id}.yaml", scale, note)
    model_file = model_dir / "model.yaml"
    body = model_file.read_text(encoding="utf-8")
    body = re.sub(r'^version: "[^"]+"', f'version: "{version}"', body, count=1, flags=re.MULTILINE)
    body = re.sub(r"^description: .*$", f"description: Startgewichten uit de bouwprompt (hoofdstuk 5 en 6); "
                  f"lettergrenzen per sjabloon geijkt op terugtest {p['run_id']} (voorstel {proposal_id}).",
                  body, count=1, flags=re.MULTILINE)
    model_file.write_text(body, encoding="utf-8")
    new = load_model_config(model_dir, check_lock=False)
    write_lock(new, model_dir)
    with sf() as session:
        session.execute(text("UPDATE model_proposal SET applied_version = :v WHERE id = :i"),
                        {"v": version, "i": proposal_id})
        session.commit()
    return version
