"""Usage, job and data-coverage endpoints for the Verbruik page."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.jobs import JOB_LABELS_NL, JOBS, run_job

router = APIRouter(prefix="/api")


@router.get("/usage")
def usage(request: Request) -> dict:
    cfg = request.app.state.providers_config
    sf = request.app.state.jobs.sf
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    with sf() as session:
        rows = session.execute(
            text(
                """
                SELECT provider,
                       COALESCE(SUM(cost), 0) AS cost,
                       COUNT(*) AS calls,
                       COUNT(*) FILTER (WHERE NOT ok) AS errors,
                       MAX(started_at) FILTER (WHERE ok) AS last_ok,
                       MAX(started_at) FILTER (WHERE NOT ok) AS last_error_at,
                       ROUND(AVG(duration_ms)) AS avg_ms
                FROM provider_call_log WHERE started_at >= :start GROUP BY provider
                """
            ),
            {"start": month_start},
        ).mappings().all()
        last_errors = dict(session.execute(text(
            """
            SELECT DISTINCT ON (provider) provider, error FROM provider_call_log
            WHERE NOT ok AND started_at >= :start ORDER BY provider, started_at DESC
            """
        ), {"start": month_start}).all())
    stats = {r["provider"]: r for r in rows}
    providers = []
    for name, entry in cfg.providers.items():
        r = stats.get(name)
        providers.append({
            "provider": name,
            "calls": int(r["calls"]) if r else 0,
            "cost": int(r["cost"]) if r else 0,
            "errors": int(r["errors"]) if r else 0,
            "budget": entry.monthly_budget,
            "rate_limit": entry.rate_limit,
            "last_ok": r["last_ok"] if r else None,
            "last_error_at": r["last_error_at"] if r else None,
            "last_error": last_errors.get(name),
            "avg_ms": int(r["avg_ms"]) if r and r["avg_ms"] is not None else None,
            "attribution": entry.attribution,
        })
    return {"month": month_start.strftime("%Y-%m"), "providers": providers}


@router.get("/jobs")
def jobs(request: Request) -> dict:
    sf = request.app.state.jobs.sf
    with sf() as session:
        runs = session.execute(text(
            """
            SELECT id, job, trigger, status, started_at, finished_at, summary, error
            FROM job_run ORDER BY started_at DESC LIMIT 30
            """
        )).mappings().all()
    scheduler = request.app.state.scheduler
    next_runs = {}
    if scheduler is not None:
        for job in scheduler.get_jobs():
            if job.id.startswith("nightly-") and job.next_run_time:
                next_runs[job.id.removeprefix("nightly-")] = job.next_run_time
    return {
        "jobs": [{"name": n, "label_nl": JOB_LABELS_NL.get(n, n), "next_run": next_runs.get(n)} for n in JOBS],
        "runs": [dict(r) for r in runs],
    }


@router.post("/jobs/{name}/run", status_code=202)
def start_job(name: str, request: Request) -> dict:
    if name not in JOBS:
        raise HTTPException(404, "Onbekende taak")
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(503, "Planner staat uit")
    scheduler.add_job(run_job, args=[request.app.state.jobs, name, "manual"], id=f"manual-{name}",
                      replace_existing=True)
    return {"started": name}


@router.get("/data/coverage")
def coverage(request: Request) -> dict:
    """How much data each asset class has; used to check the phase 1 acceptance criteria."""
    sf = request.app.state.jobs.sf
    with sf() as session:
        crypto = session.execute(text(
            """
            WITH latest AS (
                SELECT max(as_of) AS as_of FROM universe_membership WHERE universe = 'crypto_top'
            ), list AS (
                SELECT m.asset_id FROM universe_membership m, latest
                WHERE m.universe = 'crypto_top' AND m.as_of = latest.as_of AND m.included
            ), eur AS (
                SELECT asset_id, min(ts) AS first_day, max(ts) AS last_day, count(DISTINCT ts) AS days
                FROM price_daily_eur GROUP BY asset_id
            )
            SELECT (SELECT as_of FROM latest) AS list_date,
                   count(*) AS list_size,
                   count(*) FILTER (WHERE eur.days >= 365) AS with_year_eur,
                   min(eur.days) AS min_days,
                   max(eur.last_day) AS last_day
            FROM list LEFT JOIN eur USING (asset_id)
            """
        )).mappings().one()
        missing = session.execute(text(
            """
            WITH latest AS (SELECT max(as_of) AS as_of FROM universe_membership WHERE universe = 'crypto_top')
            SELECT a.name, a.symbol, a.price_sources,
                   (SELECT count(*) FROM price_daily_eur e WHERE e.asset_id = a.id) AS days,
                   (SELECT min(ts) FROM price_daily_eur e WHERE e.asset_id = a.id) AS first_day
            FROM universe_membership m JOIN latest ON m.as_of = latest.as_of JOIN asset a ON a.id = m.asset_id
            WHERE m.universe = 'crypto_top' AND m.included
            ORDER BY m.rank
            """
        )).mappings().all()
        counts = session.execute(text(
            """
            SELECT (SELECT count(*) FROM asset WHERE tracked) AS tracked_assets,
                   (SELECT count(*) FROM price_bar) AS price_bars,
                   (SELECT count(*) FROM fundamental_fact) AS facts,
                   (SELECT count(*) FROM fx_rate) AS fx_rates,
                   (SELECT count(*) FROM macro_observation) AS macro_observations
            """
        )).mappings().one()
    return {
        "crypto": dict(crypto),
        "crypto_assets": [dict(r) for r in missing],
        "totals": dict(counts),
    }


@router.get("/ai/usage")
def ai_usage(request: Request) -> dict:
    """Language-model use this month against the hard budget (chapter 9), for the settings page."""
    from app.ai.explanation import month_start

    ai = request.app.state.ai_config
    jobs = request.app.state.jobs
    start = month_start(datetime.now(UTC))
    with jobs.sf() as session:
        calls = session.execute(text(
            """
            SELECT component, model, COUNT(*) AS calls, COUNT(*) FILTER (WHERE passed) AS passed,
                   COUNT(*) FILTER (WHERE mode = 'batch') AS batch, COALESCE(SUM(cost_usd), 0) AS cost,
                   COALESCE(SUM((usage->>'input_tokens')::bigint), 0) AS input_tokens,
                   COALESCE(SUM((usage->>'output_tokens')::bigint), 0) AS output_tokens,
                   COALESCE(SUM((usage->>'cache_read_input_tokens')::bigint), 0) AS cache_read_tokens
            FROM llm_call WHERE created_at >= :s GROUP BY component, model ORDER BY component, model
            """), {"s": start}).mappings().all()
        reserved = session.execute(text(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0), COUNT(*) FROM llm_batch WHERE status = 'submitted'")).one()
        shown = session.execute(text(
            """
            SELECT COUNT(*) FILTER (WHERE source = 'model') AS model, COUNT(*) FILTER (WHERE source = 'template')
                   AS template
            FROM (SELECT DISTINCT ON (asset_id) source FROM explanation WHERE model_version_id = :v
                  ORDER BY asset_id, created_at DESC, id DESC) e
            """), {"v": jobs.model_version_id}).mappings().one()
    spent = sum(float(c["cost"]) for c in calls)
    return {
        "month": start.strftime("%Y-%m"),
        "key_configured": jobs.llm_client is not None,
        "budget_usd": ai.monthly_budget_usd,
        "spent_usd": round(spent, 4),
        "reserved_usd": round(float(reserved[0]), 4),
        "pending_batches": int(reserved[1]),
        "components": [{"component": "explanation", "label_nl": "Toelichting", "model": ai.explanation.model,
                        "prompt_version": ai.explanation.prompt_version, "batch": True,
                        "regenerate_shift_points": ai.explanation.regenerate_shift_points}],
        "calls": [{**dict(c), "cost": round(float(c["cost"]), 4)} for c in calls],
        "explanations": {"model": int(shown["model"] or 0), "template_after_check": int(shown["template"] or 0)},
    }


@router.get("/sources")
def sources(request: Request) -> list[dict]:
    import yaml

    from app.settings import get_settings

    path = get_settings().config_dir / "sources.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
