"""Point-in-time backtest (chapter 8): the live grading code, applied month by month, with only the data that
was known at the end of each month-end day.

Nothing is special-cased for the backtest: every grader already reads facts and macro values by
`available_at <= knowledge`, prices up to `as_of` and its own earlier grades through the snapshot sink. The
backtest only changes three things: `knowledge` is the end of the month-end day instead of now, grades go to
backtest_snapshot of one run, and the market regime is recomputed from the data known that day (the stored
daily regime history was computed with today's data).
"""

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.evaluation.outcomes import EvaluationSettings, month_ends, update_outcomes
from app.evaluation.report import build_report, propose_calibration, store_report
from app.grading.crypto import SnapshotSink
from app.ingest.report import Report
from app.modelconfig import ModelConfig
from app.modelconfig.schema import RegimeSettings

log = logging.getLogger("graadmeter.backtest")


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59), tzinfo=UTC)


def regime_at(session: Session, config: ModelConfig, day: date, knowledge: datetime) -> str | None:
    from app.grading.regime import compute_regime, load_inputs

    cfg = config.settings.regime
    if not isinstance(cfg, RegimeSettings):
        return None
    world, hy, vix = load_inputs(session, cfg, knowledge)
    world = world.loc[:day]
    return compute_regime(day, world, hy, vix, cfg).state


@dataclass
class Backtest:
    """Everything the four graders need, as in the nightly jobs."""

    sf: sessionmaker[Session]
    model: ModelConfig
    model_version_id: int
    settings: EvaluationSettings
    crypto_history_start: date | None = None
    stocks: object | None = None
    markets: object | None = None
    commodities: object | None = None
    progress: list[str] = field(default_factory=list)

    def grade_month(self, run_id: int, day: date, classes: list[str], report: Report) -> None:
        from app.grading.commodities import grade_commodities
        from app.grading.crypto import grade_crypto
        from app.grading.markets import grade_markets
        from app.grading.stocks import grade_stocks

        knowledge = end_of_day(day)
        with self.sf() as session:
            sink = SnapshotSink(run_id=run_id, regime=regime_at(session, self.model, day, knowledge))
        mv = self.model_version_id
        steps = {
            "crypto": lambda: grade_crypto(self.sf, self.model, mv, day, self.crypto_history_start, knowledge, sink),
            "stocks": lambda: grade_stocks(self.sf, self.model, mv, self.stocks, day, knowledge, sink),
            "markets": lambda: grade_markets(self.sf, self.model, mv, self.markets, day, knowledge, sink),
            "commodities": lambda: grade_commodities(self.sf, self.model, mv, self.commodities, day, knowledge, sink),
        }
        for cls in classes:
            try:
                r = steps[cls]()
            except Exception as exc:  # noqa: BLE001 - one class failing one month does not stop the run
                log.exception("backtest %s %s failed", cls, day)
                report.error(f"{day} {cls}: {type(exc).__name__}: {exc}")
                continue
            for k, v in r.counts.items():
                report.add(k, v)
            report.errors += [f"{day} {cls}: {e}" for e in r.errors[:5]]

    def run(self, start: date, end: date, classes: list[str], today: date | None = None) -> tuple[int, Report]:
        today = today or datetime.now(UTC).date()
        days = month_ends(start, min(end, today))
        with self.sf() as session:
            run_id = session.execute(text(
                "INSERT INTO backtest_run (model_version_id, params, status) VALUES (:v, :p, 'running') RETURNING id"),
                {"v": self.model_version_id, "p": json.dumps({"start": str(start), "end": str(min(end, today)),
                                                              "classes": classes, "months": len(days)})}).scalar()
            session.commit()
        return run_id, self._continue(run_id, days, classes, today)

    def resume(self, run_id: int, today: date | None = None) -> Report:
        """Continue a run that stopped (process ended): grade the months not stored yet, then finish it."""
        today = today or datetime.now(UTC).date()
        with self.sf() as session:
            row = session.execute(text("SELECT params, model_version_id FROM backtest_run WHERE id = :i"),
                                  {"i": run_id}).first()
            if row is None or row.model_version_id != self.model_version_id:
                raise ValueError(f"Terugtest {run_id} bestaat niet voor deze modelversie.")
            done = session.execute(text("SELECT max(as_of) FROM backtest_snapshot WHERE run_id = :i"),
                                   {"i": run_id}).scalar()
            session.execute(text("UPDATE backtest_run SET status = 'running', error = NULL WHERE id = :i"),
                            {"i": run_id})
            session.commit()
        params = row.params
        days = month_ends(date.fromisoformat(params["start"]), date.fromisoformat(params["end"]))
        # The last stored month may be incomplete (one class missing): grade it again; stored rows are kept.
        days = [d for d in days if done is None or d >= done]
        return self._continue(run_id, days, list(params["classes"]), today)

    def _continue(self, run_id: int, days: list[date], classes: list[str], today: date) -> Report:
        report = Report()
        try:
            for i, day in enumerate(days, 1):
                self.grade_month(run_id, day, classes, report)
                if i % 12 == 0 or i == len(days):
                    log.info("backtest %s: %s/%s months (%s)", run_id, i, len(days), day)
            with self.sf() as session:
                report.add("outcomes_added", update_outcomes(session, self.settings, "backtest", run_id,
                                                              self.model_version_id, today))
                session.commit()
                rep = build_report(session, self.settings, self.model, "backtest", run_id, self.model_version_id)
                store_report(session, rep, "backtest", run_id, self.model_version_id)
                proposal = propose_calibration(session, self.settings, self.model, run_id, self.model_version_id)
                if proposal:
                    report.notes.append(f"Voorstel {proposal}: lettergrenzen ijken (wacht op akkoord).")
                session.commit()
            status, error = "ok", None
        except Exception as exc:  # noqa: BLE001 - recorded on the run
            log.exception("backtest %s failed", run_id)
            status, error = "failed", "".join(traceback.format_exception(exc))[-4000:]
        with self.sf() as session:
            session.execute(text(
                "UPDATE backtest_run SET status = :s, finished_at = now(), summary = :sum, error = :e WHERE id = :i"),
                {"s": status, "sum": json.dumps(report.as_dict()), "e": error, "i": run_id})
            session.commit()
        return report


def evaluate_live(sf: sessionmaker[Session], settings: EvaluationSettings, model: ModelConfig,
                  model_version_id: int, today: date | None = None) -> Report:
    """The monthly measurement on live grades: new outcomes, then a stored report."""
    today = today or datetime.now(UTC).date()
    report = Report()
    with sf() as session:
        report.add("outcomes_added", update_outcomes(session, settings, "live", None, model_version_id, today))
        rep = build_report(session, settings, model, "live", None, model_version_id)
        store_report(session, rep, "live", None, model_version_id)
        session.commit()
    report.add("templates_measured", len(rep["templates"]))
    return report
