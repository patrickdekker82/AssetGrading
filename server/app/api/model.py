"""The Model page (chapter 8): the live track record, the backtest (always labelled as such) and proposals."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.evaluation.proposals import decide

router = APIRouter(prefix="/api/model")


def _latest_report(session, source: str, model_version_id: int):
    run_filter = ("AND e.run_id = (SELECT max(id) FROM backtest_run WHERE status = 'ok' AND model_version_id = :v)"
                  if source == "backtest" else "")
    return session.execute(text(
        f"""
        SELECT e.id, e.run_id, e.computed_at, e.report FROM evaluation e
        WHERE e.source = :s AND e.model_version_id = :v {run_filter}
        ORDER BY e.computed_at DESC, e.id DESC LIMIT 1
        """), {"s": source, "v": model_version_id}).mappings().first()


@router.get("/performance")
def performance(request: Request) -> dict:
    jobs = request.app.state.jobs
    ev = jobs.evaluation
    min_months = int(ev.raw["live"]["min_months"]) if ev else 12
    with jobs.sf() as session:
        live = _latest_report(session, "live", jobs.model_version_id)
        backtest = _latest_report(session, "backtest", jobs.model_version_id)
        live_months = session.execute(text(
            """SELECT count(DISTINCT as_of) FROM outcome
               WHERE source = 'live' AND model_version_id = :v AND horizon_months = 1"""),
            {"v": jobs.model_version_id}).scalar()
        first_live = session.execute(text("SELECT min(as_of) FROM grade_snapshot WHERE model_version_id = :v"),
                                     {"v": jobs.model_version_id}).scalar()
        run = None
        if backtest:
            run = session.execute(text(
                "SELECT id, params, started_at, finished_at, summary->'counts' AS counts FROM backtest_run "
                "WHERE id = :i"), {"i": backtest["run_id"]}).mappings().first()
        running = session.execute(text(
            "SELECT id, started_at, params FROM backtest_run WHERE status = 'running' ORDER BY id DESC LIMIT 1")
        ).mappings().first()
    return {
        "model_version": jobs.model.version,
        "live": {
            "insufficient": live_months < min_months,
            "months_with_outcomes": live_months,
            "min_months": min_months,
            "first_grade": first_live,
            "computed_at": live["computed_at"] if live else None,
            "report": live["report"] if live else None,
        },
        "backtest": {
            "label": "Terugtest: herberekend met alleen de data die toen bekend was. Geen behaald resultaat.",
            "run": dict(run) if run else None,
            "running": dict(running) if running else None,
            "computed_at": backtest["computed_at"] if backtest else None,
            "report": backtest["report"] if backtest else None,
        },
    }


@router.get("/proposals")
def proposals(request: Request) -> list[dict]:
    with request.app.state.jobs.sf() as session:
        rows = session.execute(text(
            """SELECT id, kind, status, created_at, decided_at, applied_version, run_id, summary_nl, payload, evidence,
                      source, refusal
               FROM model_proposal ORDER BY (status = 'open') DESC, id DESC LIMIT 30""")).mappings().all()
    return [dict(r) for r in rows]


def _decide(request: Request, proposal_id: int, approve: bool) -> dict:
    with request.app.state.jobs.sf() as session:
        try:
            return decide(session, proposal_id, approve)
        except KeyError:
            raise HTTPException(404, "Voorstel niet gevonden") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: int, request: Request) -> dict:
    with request.app.state.jobs.sf() as session:
        kind = session.execute(text("SELECT kind FROM model_proposal WHERE id = :i"), {"i": proposal_id}).scalar()
    if kind == "weights":
        # An approved weight proposal starts as a challenger in the shadow; it does not become active.
        from app.api.learning import start_challenger

        return start_challenger(proposal_id, request)
    return _decide(request, proposal_id, True)


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: int, request: Request) -> dict:
    return _decide(request, proposal_id, False)
