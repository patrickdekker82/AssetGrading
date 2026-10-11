from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session
from app.system import compute_smoke_test, cpu_flags, library_versions, numpy_simd

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health(request: Request, session: SessionDep) -> dict:
    state = request.app.state
    try:
        session.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:  # noqa: BLE001 - report any database failure as unhealthy
        db = f"error: {type(exc).__name__}"
    scheduler = state.scheduler.running if state.scheduler is not None else False
    return {
        "status": "ok" if db == "ok" else "degraded",
        "database": db,
        "model_version": state.model_config.version,
        "config_hash": state.model_config.config_hash,
        "scheduler_running": scheduler,
        "compute_ok": compute_smoke_test(),
        "cpu": cpu_flags(),
        "numpy_simd": numpy_simd(),
        "versions": library_versions(),
    }


@router.get("/glossary")
def glossary(request: Request) -> dict:
    return request.app.state.glossary.model_dump()


@router.get("/tabs")
def tabs(request: Request) -> list[dict]:
    universes = request.app.state.universes
    config = request.app.state.model_config
    out = []
    for tab in universes.tabs:
        item = tab.model_dump()
        item["template_names"] = [config.templates[t].name_nl for t in tab.templates]
        out.append(item)
    return out


@router.get("/model")
def model_summary(request: Request) -> dict:
    config = request.app.state.model_config
    return {
        "version": config.version,
        "config_hash": config.config_hash,
        "description": config.settings.description,
        "letter_scale": config.settings.letter_scale,
        "templates": [
            {
                "id": t.id,
                "name_nl": t.name_nl,
                "tab": t.tab,
                "grading": t.grading,
                "pillars": [{"id": p.id, "name_nl": p.name_nl, "weight": p.weight} for p in t.pillars],
                "gates": [g.id for g in t.gates],
            }
            for t in config.templates.values()
        ],
    }
