"""The evaluation report per template and horizon (chapter 8), and the calibration of the letter bounds."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.evaluation import metrics
from app.evaluation.outcomes import EvaluationSettings, grade_source_sql, measurement_frame, to_json
from app.grading.letters import letter_for
from app.modelconfig import ModelConfig


def build_report(session: Session, settings: EvaluationSettings, model: ModelConfig, source: str,
                 run_id: int | None, model_version_id: int) -> dict:
    frames = {h: measurement_frame(session, source, run_id, model_version_id, h) for h in settings.horizons}
    templates: dict[str, dict] = {}
    for tid, template in model.templates.items():
        entry = {"name_nl": template.name_nl, "tab": template.tab, "horizons": {}}
        for h, frame in frames.items():
            df = frame[frame["template_id"] == tid] if not frame.empty else frame
            if df.empty:
                continue
            entry["horizons"][str(h)] = metrics.measure(df, h, settings.raw)
        any_frame = next(iter(frames.values()))
        entry["coverage"] = metrics.coverage(any_frame[any_frame["template_id"] == tid]) \
            if not any_frame.empty else metrics.coverage(any_frame)
        if entry["coverage"]["months"]:
            templates[tid] = entry
    return to_json({
        "source": source, "run_id": run_id, "model_version": model.version,
        "computed_at": datetime.now(UTC), "horizons": settings.horizons, "templates": templates,
        "label": "terugtest: herberekend, geen behaald resultaat" if source == "backtest" else "live",
    })


def store_report(session: Session, report: dict, source: str, run_id: int | None, model_version_id: int) -> int:
    import json

    return session.execute(text(
        "INSERT INTO evaluation (source, run_id, model_version_id, report) VALUES (:s, :r, :v, :rep) RETURNING id"),
        {"s": source, "r": run_id, "v": model_version_id, "rep": json.dumps(report)}).scalar()


# --- calibration ----------------------------------------------------------------------------------


def calibrate_scale(scores: pd.Series, target: dict[str, float], round_to: float) -> dict[str, float]:
    """Lower bounds so that the target shares of A, B, C, D and F come out of these scores."""
    cum, bounds = 0.0, {}
    for letter in ("A", "B", "C", "D"):
        cum += target[letter]
        q = float(np.quantile(scores, 1 - cum))
        bounds[letter] = round(q / round_to) * round_to
    bounds["F"] = 0.0
    # Keep them strictly descending and above zero even for clumped scores.
    floor = round_to
    for letter in ("D", "C", "B", "A"):
        bounds[letter] = max(bounds[letter], floor)
        floor = bounds[letter] + round_to
    return bounds


def distribution(scores: pd.Series, scale: dict[str, float]) -> dict[str, float]:
    letters = scores.map(lambda s: letter_for(float(s), scale)[0])
    return {b: round(float((letters == b).mean()), 3) for b in metrics.BASE_ORDER}


def calibration(session: Session, settings: EvaluationSettings, model: ModelConfig, run_id: int,
                model_version_id: int) -> dict:
    """Per template: proposed bounds from the backtest scores, or why the provisional bounds stay."""
    cfg = settings.raw["calibration"]
    rows = session.execute(text(
        f"""SELECT template_id, as_of, score FROM ({grade_source_sql('backtest')}) g
            WHERE status IN ('graded', 'provisional') AND score IS NOT NULL"""),
        {"run": run_id, "v": model_version_id}).all()
    df = pd.DataFrame(rows, columns=["template_id", "as_of", "score"])
    out = {}
    for tid in model.templates:
        g = df[df["template_id"] == tid] if not df.empty else df
        months, n = (int(g["as_of"].nunique()), int(len(g))) if not g.empty else (0, 0)
        current = model.letter_scale_for(tid)
        entry = {"name_nl": model.templates[tid].name_nl, "months": months, "observations": n, "current": current}
        if months < cfg["min_months"] or n < cfg["min_observations"]:
            entry["proposed"] = None
            entry["reason_nl"] = (f"Te weinig terugtestdata ({months} maanden, {n} waarnemingen; nodig "
                                  f"{cfg['min_months']} maanden en {cfg['min_observations']}). De voorlopige "
                                  "grenzen blijven.")
        else:
            proposed = calibrate_scale(g["score"], cfg["target"], cfg["round_to"])
            entry["proposed"] = proposed
            entry["distribution_current"] = distribution(g["score"], current)
            entry["distribution_proposed"] = distribution(g["score"], proposed)
        out[tid] = entry
    return out


def propose_calibration(session: Session, settings: EvaluationSettings, model: ModelConfig, run_id: int,
                        model_version_id: int) -> int | None:
    """Store an open proposal with new letter bounds for the templates that have enough backtest data."""
    import json

    cal = calibration(session, settings, model, run_id, model_version_id)
    payload = {tid: e["proposed"] for tid, e in cal.items() if e["proposed"]}
    if not payload:
        return None
    names = ", ".join(model.templates[t].name_nl for t in payload)
    summary = (f"Lettergrenzen per sjabloon ijken op de doelverdeling (10% A, 20% B, 40% C, 20% D, 10% F) in "
               f"terugtest {run_id}: {names}. Sjablonen met te weinig data houden de voorlopige grenzen.")
    return session.execute(text(
        """
        INSERT INTO model_proposal (kind, model_version_id, run_id, summary_nl, payload, evidence)
        VALUES ('letter_scale', :v, :r, :s, :p, :e) RETURNING id
        """), {"v": model_version_id, "r": run_id, "s": summary, "p": json.dumps(payload),
               "e": json.dumps(to_json(cal))}).scalar()
