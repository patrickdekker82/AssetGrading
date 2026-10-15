"""Job runner: records each run in job_run and prevents two runs of the same job at once."""

import logging
import traceback
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.ai.config import AiConfig
from app.commodities_config import CommoditiesConfig
from app.grading.commodities import grade_commodities
from app.grading.crypto import grade_crypto
from app.grading.markets import grade_markets
from app.grading.regime import update_regime
from app.grading.stocks import grade_stocks
from app.ingest.commodities import run_commodities
from app.ingest.crypto import run_crypto
from app.ingest.fx_macro import run_fx_macro
from app.ingest.markets import run_markets
from app.ingest.prune import run_prune
from app.ingest.report import Report
from app.ingest.stocks import run_stocks
from app.markets_config import MarketsConfig
from app.modelconfig import ModelConfig
from app.models import JobRun
from app.providers.config import ProvidersConfig
from app.providers.recorder import current_job_run
from app.providers.registry import Providers
from app.stocks_config import StocksConfig
from app.universes import Universes

log = logging.getLogger("graadmeter.jobs")


@dataclass
class JobContext:
    engine: Engine
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    universes: Universes
    model: ModelConfig | None = None
    model_version_id: int | None = None
    stocks: StocksConfig | None = None
    markets: MarketsConfig | None = None
    commodities: CommoditiesConfig | None = None
    ai: AiConfig | None = None
    labels: dict[str, str] | None = None     # metric labels from the glossary, for explanations
    llm_client: object | None = None         # None without an API key: template text only
    evaluation: object | None = None         # EvaluationSettings (config/evaluation.yaml)
    ops: object | None = None                # OpsConfig (config/operations.yaml): back-up and notifications


def run_crypto_and_grade(c: JobContext) -> Report:
    """Nightly crypto: ingest, then grade the last completed day."""
    report = run_crypto(c.sf, c.providers, c.cfg, c.universes, model=c.model)
    if c.model is None or c.model_version_id is None:
        report.notes.append("Geen modelconfiguratie geladen; grading overgeslagen.")
        return report
    as_of = datetime.now(UTC).date() - timedelta(days=1)
    start = date.fromisoformat(c.cfg.crypto.history_start)
    try:
        graded = grade_crypto(c.sf, c.model, c.model_version_id, as_of, start)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("crypto grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    grade_shadows(c, report, lambda cfg, vid, sink: grade_crypto(c.sf, cfg, vid, as_of, start, None, sink))
    return report


def grade_shadows(c: JobContext, report: Report, grade_fn) -> None:
    """Grade every challenger in the shadow with the same data (chapter 8). Never shown; never active."""
    from app.grading.crypto import SnapshotSink
    from app.learning.registry import shadow_challengers

    try:
        with c.sf() as session:
            shadows = shadow_challengers(session)
    except Exception as exc:  # noqa: BLE001 - shadow grading never blocks the champion
        report.error(f"schaduw: {type(exc).__name__}: {exc}")
        return
    for config, vid, _ in shadows:
        try:
            r = grade_fn(config, vid, SnapshotSink(regime_version_id=c.model_version_id))
            report.add("shadow_snapshots_added", r.counts.get("snapshots_added", 0))
        except Exception as exc:  # noqa: BLE001
            log.exception("shadow grading %s failed", config.version)
            report.error(f"schaduw {config.version}: {type(exc).__name__}: {exc}")


def run_stocks_and_grade(c: JobContext) -> Report:
    """Weekday stock run: ingest, then grade today's close (the run starts after the US close)."""
    if c.model is None or c.model_version_id is None or c.stocks is None:
        report = Report()
        report.error("Geen model- of aandelenconfiguratie geladen.")
        return report
    report = run_stocks(c.sf, c.providers, c.cfg, c.stocks, c.universes, c.model)
    as_of = last_trading_day(datetime.now(UTC))
    try:
        graded = grade_stocks(c.sf, c.model, c.model_version_id, c.stocks, as_of)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("stock grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    grade_shadows(c, report, lambda cfg, vid, sink: grade_stocks(c.sf, cfg, vid, c.stocks, as_of, None, sink))
    return report


REGIME_START = date(2010, 1, 1)


def run_markets_and_grade(c: JobContext) -> Report:
    """Weekday markets run: indices, ETFs and bond ETFs, the market regime, then their grades."""
    if c.model is None or c.model_version_id is None or c.markets is None:
        report = Report()
        report.error("Geen model- of marktconfiguratie geladen.")
        return report
    report = run_markets(c.sf, c.providers, c.cfg, c.markets)
    as_of = last_trading_day(datetime.now(UTC))
    try:
        update_regime(c.sf, c.model, c.model_version_id, datetime.now(UTC).date(), REGIME_START, report)
        graded = grade_markets(c.sf, c.model, c.model_version_id, c.markets, as_of)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("markets grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    grade_shadows(c, report, lambda cfg, vid, sink: grade_markets(c.sf, cfg, vid, c.markets, as_of, None, sink))
    return report


def run_commodities_and_grade(c: JobContext) -> Report:
    """Weekday commodities and currencies run, then their grades (commodity, product, currency pair)."""
    if c.model is None or c.model_version_id is None or c.commodities is None:
        report = Report()
        report.error("Geen model- of grondstoffenconfiguratie geladen.")
        return report
    report = run_commodities(c.sf, c.providers, c.cfg, c.commodities)
    as_of = last_trading_day(datetime.now(UTC))
    try:
        graded = grade_commodities(c.sf, c.model, c.model_version_id, c.commodities, as_of)
    except Exception as exc:  # noqa: BLE001 - keep the ingest result; report the grading failure
        log.exception("commodities grading failed")
        report.error(f"grading: {type(exc).__name__}: {exc}")
        return report
    for key, value in graded.counts.items():
        report.add(key, value)
    from app.api.assets import clear_chart_cache

    clear_chart_cache()
    report.errors += graded.errors
    grade_shadows(c, report, lambda cfg, vid, sink: grade_commodities(c.sf, cfg, vid, c.commodities, as_of, None,
                                                                       sink))
    return report


def run_explanations(c: JobContext) -> Report:
    """Collect finished explanation batches and submit new ones (chapter 9)."""
    if c.model is None or c.model_version_id is None or c.ai is None:
        report = Report()
        report.error("Geen model- of AI-configuratie geladen.")
        return report
    from app.ai.explanation import Explainer

    return Explainer(c.sf, c.ai, c.model, c.model_version_id, c.labels or {}, c.llm_client).run()


def run_evaluation(c: JobContext) -> Report:
    """Monthly measurement on live grades: outcomes that became known, then a new report (chapter 8)."""
    if c.model is None or c.model_version_id is None or c.evaluation is None:
        report = Report()
        report.error("Geen model- of evaluatieconfiguratie geladen.")
        return report
    from app.evaluation.backtest import evaluate_live
    from app.learning.promotion import run_checks
    from app.learning.registry import shadow_challengers

    report = evaluate_live(c.sf, c.evaluation, c.model, c.model_version_id)
    with c.sf() as session:
        shadows = shadow_challengers(session)
    for config, vid, cid in shadows:
        r = evaluate_live(c.sf, c.evaluation, config, vid)
        report.add("shadow_outcomes_added", r.counts.get("outcomes_added", 0))
        with c.sf() as session:
            checks = run_checks(session, c.evaluation, cid)
        passed = sum(ch["passed"] for ch in checks)
        report.notes.append(f"Uitdager {config.version}: {passed} van {len(checks)} toetsen gehaald.")
    return report


def run_quarterly(c: JobContext) -> Report:
    """The quarterly round: weight proposals from the measurements, the review by the language model and the
    analysis of misses. Only proposals come out of it (chapter 8 and 9)."""
    report = Report()
    if c.model is None or c.model_version_id is None or c.evaluation is None:
        report.error("Geen model- of evaluatieconfiguratie geladen.")
        return report
    from app.learning.misses import analyse_misses
    from app.learning.quarterly import quarterly_round
    from app.learning.review import quarterly_review

    with c.sf() as session:
        quarterly_round(session, c.evaluation, c.model, c.model_version_id, report)
        if c.ai is not None:
            quarterly_review(session, c.ai, c.llm_client, c.evaluation, c.model, c.model_version_id, report)
            analyse_misses(session, c.ai, c.llm_client, c.evaluation, c.model, c.model_version_id, report)
    return report


def run_challenger_backtests(c: JobContext) -> Report:
    """Backtest the champion and every shadow challenger that has no finished backtest yet."""
    report = Report()
    if c.model is None or c.model_version_id is None or c.evaluation is None:
        report.error("Geen model- of evaluatieconfiguratie geladen.")
        return report
    from app.evaluation.backtest import Backtest
    from app.learning.promotion import latest_run
    from app.learning.registry import shadow_challengers

    with c.sf() as session:
        todo = [(c.model, c.model_version_id)] + [(cfg, vid) for cfg, vid, _ in shadow_challengers(session)]
        todo = [(cfg, vid) for cfg, vid in todo if latest_run(session, vid) is None]
    bt_cfg = c.evaluation.raw["backtest"]
    for config, vid in todo:
        bt = Backtest(c.sf, config, vid, c.evaluation, date.fromisoformat(c.cfg.crypto.history_start), c.stocks,
                      c.markets, c.commodities)
        run_id, r = bt.run(date.fromisoformat(bt_cfg["start"] + "-01"), datetime.now(UTC).date(),
                           list(bt_cfg["classes"]))
        report.notes.append(f"Terugtest {run_id} voor modelversie {config.version}")
        report.errors += r.errors[:20]
    if not todo:
        report.notes.append("Elke modelversie heeft al een terugtest.")
    return report


def run_backtest(c: JobContext) -> Report:
    """The full point-in-time backtest with the settings of config/evaluation.yaml (takes hours)."""
    if c.model is None or c.model_version_id is None or c.evaluation is None:
        report = Report()
        report.error("Geen model- of evaluatieconfiguratie geladen.")
        return report
    from app.evaluation.backtest import Backtest

    bt_cfg = c.evaluation.raw["backtest"]
    start = date.fromisoformat(bt_cfg["start"] + "-01")
    bt = Backtest(c.sf, c.model, c.model_version_id, c.evaluation, date.fromisoformat(c.cfg.crypto.history_start),
                  c.stocks, c.markets, c.commodities)
    run_id, report = bt.run(start, datetime.now(UTC).date(), list(bt_cfg["classes"]))
    report.notes.insert(0, f"Terugtest {run_id}")
    return report


def run_backup(c: JobContext) -> Report:
    """Nightly pg_dump to the back-up folder outside the containers (phase 10)."""
    from app.ops.backup import backup
    from app.settings import get_settings

    if c.ops is None:
        report = Report()
        report.error("Geen beheerconfiguratie geladen.")
        return report
    _, report = backup(get_settings().database_url, c.ops.backup_dir, c.ops.keep_daily, c.ops.keep_monthly)
    return report


def run_restore_test(c: JobContext) -> Report:
    """Weekly: restore the newest back-up into an empty database and recompute every grade (phase 10)."""
    from app.ops.backup import restore_test
    from app.settings import get_settings

    if c.ops is None:
        report = Report()
        report.error("Geen beheerconfiguratie geladen.")
        return report
    return restore_test(get_settings().database_url, c.ops.backup_dir, c.ops.restore_database)


def run_watchdog(ctx: JobContext) -> None:
    """Hourly, not recorded as a run: report scheduled jobs that should have run but did not."""
    from app.ops.watchdog import run_watchdog as check

    if ctx.ops is None:
        return
    try:
        with ctx.sf() as session:
            check(session, ctx.ops, set(ctx.cfg.schedule), JOB_LABELS_NL)
    except Exception:  # noqa: BLE001
        log.exception("watchdog failed")


def last_trading_day(now: datetime) -> date:
    """The last weekday whose US session has closed (21:00 UTC covers both summer and winter time)."""
    day = now.date() if now.hour >= 21 else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


JOBS: dict[str, Callable[[JobContext], Report]] = {
    "crypto": run_crypto_and_grade,
    "stocks": run_stocks_and_grade,
    "markets": run_markets_and_grade,
    "commodities": run_commodities_and_grade,
    "fx_macro": lambda c: run_fx_macro(c.sf, c.providers, c.cfg),
    "explanations": run_explanations,
    "evaluation": run_evaluation,
    "backtest": run_backtest,
    "quarterly": run_quarterly,
    "challenger_backtests": run_challenger_backtests,
    "backup": run_backup,
    "restore_test": run_restore_test,
    "prune_raw": lambda c: run_prune(c.sf, c.cfg),
}

JOB_LABELS_NL = {
    "crypto": "Crypto (koersen, lijst, fundamentals)",
    "stocks": "Aandelen (koersen, SEC-cijfers, lijst)",
    "markets": "Indices, ETF's, obligaties en marktregime",
    "commodities": "Grondstoffen, ETC's en valuta",
    "fx_macro": "Wisselkoersen en macro",
    "explanations": "Toelichtingen (taalmodel, batch)",
    "evaluation": "Maandelijkse meting (live uitkomsten)",
    "backtest": "Terugtest (alle klassen, duurt uren)",
    "quarterly": "Kwartaalronde (voorstellen, beoordeling, missers)",
    "challenger_backtests": "Terugtest van uitdagers",
    "backup": "Back-up van de database",
    "restore_test": "Hersteltest van de back-up",
    "prune_raw": "Opruimen ruwe antwoorden",
}


def lock_key(name: str) -> int:
    return zlib.crc32(f"graadmeter-job-{name}".encode())


def fail_orphaned_runs(engine: Engine, sf: sessionmaker[Session]) -> int:
    """Mark runs as failed that say 'running' but whose job lock nobody holds (process stopped).

    A run started from the command line holds its lock in another process and is left alone.
    """
    failed = 0
    with sf() as session, engine.connect() as conn:
        for run in session.query(JobRun).filter(JobRun.status == "running"):
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key(run.job)}).scalar():
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key(run.job)})
                run.status, run.error, run.finished_at = "failed", "proces gestopt tijdens run", datetime.now(UTC)
                failed += 1
        conn.commit()
        session.commit()
    return failed


def run_job(ctx: JobContext, name: str, trigger: str = "manual") -> JobRun:
    if name not in JOBS:
        raise KeyError(name)
    key = lock_key(name)
    with ctx.engine.connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            return _record_skip(ctx, name, trigger)
        try:
            return _execute(ctx, name, trigger)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            lock_conn.commit()


def _record_skip(ctx: JobContext, name: str, trigger: str) -> JobRun:
    now = datetime.now(UTC)
    with ctx.sf() as session:
        run = JobRun(job=name, trigger=trigger, status="skipped", started_at=now, finished_at=now,
                     summary={"notes": ["De vorige run van deze taak liep nog."]})
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def _execute(ctx: JobContext, name: str, trigger: str) -> JobRun:
    with ctx.sf() as session:
        run = JobRun(job=name, trigger=trigger, status="running", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        run_id = run.id
    token = current_job_run.set(run_id)
    status, summary, error = "ok", None, None
    from app.ops.resources import ResourceMeter

    meter = ResourceMeter()
    try:
        with meter:
            report = JOBS[name](ctx)
        summary = report.as_dict()
        status = "partial" if report.errors else "ok"
    except Exception as exc:  # noqa: BLE001 - a failed run is recorded, never crashes the server
        status, error = "failed", "".join(traceback.format_exception(exc))[-4000:]
        log.exception("job %s failed", name)
    finally:
        current_job_run.reset(token)
    summary = {**(summary or {}), "resources": getattr(meter, "result", None)}
    with ctx.sf() as session:
        run = session.get(JobRun, run_id)
        run.status, run.summary, run.error, run.finished_at = status, summary, error, datetime.now(UTC)
        session.commit()
        session.refresh(run)
        log.info("job %s finished: %s", name, status)
    if trigger == "schedule" and ctx.ops is not None:
        _notify_failure(ctx, name, status, summary, error)
    return run


def _notify_failure(ctx: JobContext, name: str, status: str, summary: dict, error: str | None) -> None:
    from app.ops.notify import job_message, send, should_notify

    if not should_notify(ctx.ops, status, summary):
        return
    subject, body = job_message(name, JOB_LABELS_NL.get(name, name), status, summary, error)
    try:
        with ctx.sf() as session:
            send(session, ctx.ops, subject, body, "job")
    except Exception:  # noqa: BLE001 - a notification never breaks the run record
        log.exception("notification for %s failed", name)


def schedule_jobs(scheduler: BaseScheduler, ctx: JobContext) -> None:
    mapping = {"crypto": ["crypto"], "stocks": ["stocks"], "markets": ["markets"], "commodities": ["commodities"],
               "fx_macro": ["fx_macro"], "explanations": ["explanations"], "prune_raw": ["prune_raw"],
               "evaluation": ["evaluation"], "quarterly": ["quarterly"],
               "challenger_backtests": ["challenger_backtests"], "backup": ["backup"],
               "restore_test": ["restore_test"]}
    for key, expr in ctx.cfg.schedule.items():
        for job in mapping.get(key, []):
            scheduler.add_job(
                run_job, CronTrigger.from_crontab(expr, timezone="UTC"), args=[ctx, job, "schedule"],
                id=f"nightly-{job}", replace_existing=True, misfire_grace_time=3600,
            )
    if "watchdog" in ctx.cfg.schedule:
        scheduler.add_job(run_watchdog, CronTrigger.from_crontab(ctx.cfg.schedule["watchdog"], timezone="UTC"),
                          args=[ctx], id="watchdog", replace_existing=True, misfire_grace_time=3600)
