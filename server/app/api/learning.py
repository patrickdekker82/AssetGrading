"""The learning loop on the Model page (chapter 8): challengers, promotion, rollback, and qualitative features.

Every route here only records what the owner decided. A weight changes only through `promote` (all checks
passed) or `rollback` (undo the last promotion), both explicit owner actions.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text

from app.evaluation.proposals import decide
from app.learning import registry
from app.learning.promotion import run_checks
from app.learning.qualitative import assess, latest_for
from app.learning.weights import Guardrails
from app.models import Asset

router = APIRouter(prefix="/api")


def _jobs(request: Request):
    return request.app.state.jobs


def activate_in_process(request: Request, version_id: int) -> None:
    """Grade with the newly active model from now on, without a restart."""
    jobs = _jobs(request)
    with jobs.sf() as session:
        config = registry.config_of(session, version_id)
    jobs.model, jobs.model_version_id = config, version_id
    request.app.state.model_config = config
    from app.api.assets import clear_chart_cache

    clear_chart_cache()


@router.get("/model/learning")
def learning(request: Request) -> dict:
    jobs = _jobs(request)
    with jobs.sf() as session:
        base, base_id = registry.baseline(session)
        rows = session.execute(text(
            """SELECT c.*, v.version, cv.version AS champion_version FROM challenger c
               JOIN model_version v ON v.id = c.model_version_id
               JOIN model_version cv ON cv.id = c.champion_version_id
               ORDER BY (c.status = 'shadow') DESC, c.id DESC LIMIT 10""")).mappings().all()
        challengers = []
        for r in rows:
            cfg = registry.config_of(session, r["model_version_id"])
            champ = registry.config_of(session, r["champion_version_id"])
            changes = {t: {"from": registry.weights_of(champ, t), "to": registry.weights_of(cfg, t),
                           "name_nl": cfg.templates[t].name_nl}
                       for t in cfg.templates if cfg.templates[t].pillars
                       and registry.weights_of(cfg, t) != registry.weights_of(champ, t)}
            challengers.append({**{k: r[k] for k in ("id", "status", "started_at", "ended_at", "checks", "checked_at",
                                                      "proposal_id", "version", "champion_version")},
                                "changes": changes})
        hist = registry.history(session)
        last = registry.last_switch(session)
    return {
        "active": {"version": jobs.model.version, "id": jobs.model_version_id},
        "baseline": {"version": base.version, "id": base_id},
        "rollback_available": bool(hist) and hist[0]["kind"] == "promote",
        "last_switch": last,
        "history": hist,
        "challengers": challengers,
    }


@router.post("/model/proposals/{proposal_id}/start")
def start_challenger(proposal_id: int, request: Request) -> dict:
    """Approving a weight proposal starts it as a challenger in the shadow; nothing becomes active."""
    jobs = _jobs(request)
    g = Guardrails.from_settings(jobs.evaluation.raw)
    with jobs.sf() as session:
        kind = session.execute(text("SELECT kind FROM model_proposal WHERE id = :i"), {"i": proposal_id}).scalar()
        if kind is None:
            raise HTTPException(404, "Voorstel niet gevonden")
        try:
            decide(session, proposal_id, True)
            cid = registry.create_challenger(session, proposal_id, jobs.model, jobs.model_version_id, g)
        except (ValueError, registry.LearningError) as exc:
            raise HTTPException(409, str(exc)) from None
    return {"proposal": proposal_id, "challenger": cid, "status": "shadow"}


@router.post("/model/challengers/{challenger_id}/check")
def check(challenger_id: int, request: Request) -> list[dict]:
    jobs = _jobs(request)
    with jobs.sf() as session:
        return run_checks(session, jobs.evaluation, challenger_id)


@router.post("/model/challengers/{challenger_id}/promote")
def promote(challenger_id: int, request: Request) -> dict:
    jobs = _jobs(request)
    cfg = jobs.evaluation.raw["learning"]["promotion"]
    with jobs.sf() as session:
        checks = run_checks(session, jobs.evaluation, challenger_id)
        try:
            vid = registry.promote(session, challenger_id, checks, int(cfg["min_months_between_switches"]))
        except registry.LearningError as exc:
            raise HTTPException(409, str(exc)) from None
    activate_in_process(request, vid)
    return {"active": _jobs(request).model.version}


@router.post("/model/challengers/{challenger_id}/retire")
def retire(challenger_id: int, request: Request) -> dict:
    with _jobs(request).sf() as session:
        n = session.execute(text(
            "UPDATE challenger SET status = 'retired', ended_at = now() WHERE id = :i AND status = 'shadow'"),
            {"i": challenger_id}).rowcount
        session.commit()
    if not n:
        raise HTTPException(409, "Deze uitdager draait niet in de schaduw.")
    return {"challenger": challenger_id, "status": "retired"}


@router.post("/model/rollback")
def rollback(request: Request) -> dict:
    with _jobs(request).sf() as session:
        try:
            vid = registry.rollback(session)
        except registry.LearningError as exc:
            raise HTTPException(409, str(exc)) from None
    activate_in_process(request, vid)
    return {"active": _jobs(request).model.version}


class Document(BaseModel):
    source_name: str
    text: str


@router.get("/assets/{key}/qualitative")
def qualitative(key: str, request: Request) -> list[dict]:
    with _jobs(request).sf() as session:
        asset = session.scalar(select(Asset).where(Asset.slug == key))
        if asset is None:
            raise HTTPException(404, "Asset niet gevonden")
        return latest_for(session, asset.id)


@router.post("/assets/{key}/qualitative")
def qualitative_new(key: str, doc: Document, request: Request) -> dict:
    jobs = _jobs(request)
    if jobs.llm_client is None or jobs.ai is None:
        raise HTTPException(503, "Geen API-sleutel voor het taalmodel; kwalitatieve kenmerken zijn niet beschikbaar.")
    with jobs.sf() as session:
        asset = session.scalar(select(Asset).where(Asset.slug == key))
        if asset is None:
            raise HTTPException(404, "Asset niet gevonden")
        try:
            return assess(session, jobs.ai, jobs.llm_client, asset.id, doc.source_name, doc.text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
