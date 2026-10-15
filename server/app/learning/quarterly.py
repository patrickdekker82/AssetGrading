"""The quarterly round (chapter 8): a weight proposal per template from the measured pillar rank correlations.

Every weight proposal, from this formula, from the language model or from anyone else, enters through
`store_weight_proposal`, which applies the fixed guardrail check: a proposal that breaks a guardrail is
stored as refused, with the reasons, and can never be approved.
"""

import json
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.evaluation.outcomes import EvaluationSettings, measurement_frame, to_json
from app.ingest.report import Report
from app.learning.promotion import latest_run
from app.learning.registry import baseline, weights_of
from app.learning.weights import DataCoverage, Guardrails, check_weights, propose_weights, quarterly_ic
from app.modelconfig import ModelConfig


def coverage_for(session: Session, template_id: str, champion_id: int,
                 horizon: int) -> tuple[DataCoverage, pd.DataFrame]:
    """Backtest months, assets per month and live months for one template, plus the combined frame."""
    frames = []
    run = latest_run(session, champion_id)
    bt = measurement_frame(session, "backtest", run, champion_id, horizon) if run else pd.DataFrame()
    bt = bt[bt["template_id"] == template_id] if not bt.empty else bt
    live = measurement_frame(session, "live", None, champion_id, horizon)
    live = live[live["template_id"] == template_id] if not live.empty else live
    if not bt.empty and not live.empty:
        # The backtest runs up to today: a month-end that also has live grades counts once, with the live ones.
        live_months_set = set(live.dropna(subset=["excess"])["as_of"])
        bt_for_ic = bt[~bt["as_of"].isin(live_months_set)]
    else:
        bt_for_ic = bt
    for f in (bt_for_ic, live):
        if not f.empty:
            frames.append(f)
    bt_months = int(bt["as_of"].nunique()) if not bt.empty else 0
    apm = float(bt.groupby("as_of")["asset_id"].nunique().mean()) if not bt.empty else 0.0
    live_months = int(live.dropna(subset=["excess"])["as_of"].nunique()) if not live.empty else 0
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return DataCoverage(bt_months, apm, live_months), combined


def store_weight_proposal(session: Session, template_id: str, weights: dict, w0: dict, current: dict,
                          g: Guardrails, cov: DataCoverage | None, source: str, summary_nl: str,
                          evidence: dict, model_version_id: int) -> tuple[int, list[str]]:
    """The single entry for a weight proposal. Returns (id, violations); with violations it is refused."""
    problems = check_weights(w0, current, weights, g, cov)
    status = "refused" if problems else "open"
    pid = session.execute(text(
        """INSERT INTO model_proposal (kind, model_version_id, summary_nl, payload, evidence, status, source,
                                       refusal, decided_at)
           VALUES ('weights', :v, :s, :p, :e, :st, :src, :r, :decided)
           RETURNING id"""),
        {"v": model_version_id, "s": summary_nl, "p": json.dumps({template_id: weights}),
         "e": json.dumps(to_json({"current": current, "start": w0, **evidence})), "st": status, "src": source,
         "r": json.dumps(problems, ensure_ascii=False) if problems else None,
         "decided": datetime.now(UTC) if problems else None}).scalar()
    session.commit()
    return pid, problems


def quarterly_round(session: Session, settings: EvaluationSettings, champion: ModelConfig, champion_id: int,
                    report: Report) -> list[int]:
    """Steps 1 to 6 for every weighted template; returns the ids of the stored proposals."""
    cfg = settings.raw["learning"]
    g = Guardrails.from_settings(settings.raw)
    h = int(cfg["quarterly_horizon_months"])
    base, _ = baseline(session)
    ids = []
    for tid, template in champion.templates.items():
        if not template.pillars:
            continue
        cov, df = coverage_for(session, tid, champion_id, h)
        pillars = [p.id for p in template.pillars]
        ic = quarterly_ic(df, pillars, int(settings.raw.get("min_assets_per_month", 5))) if not df.empty else {}
        quarters = max((len(s) for s in ic.values()), default=0)
        w0, current = weights_of(base, tid), weights_of(champion, tid)
        res = propose_weights(w0, current, ic, 3 * quarters, g, cov, cfg["shrink_months"], cfg["max_lambda"])
        if res.weights is None:
            report.notes.append(f"{template.name_nl}: {res.reason_nl}")
            continue
        changes = ", ".join(f"{p} {current[p]:g} -> {res.weights[p]:g}" for p in pillars
                            if abs(res.weights[p] - current[p]) >= 0.05)
        pid, problems = store_weight_proposal(
            session, tid, res.weights, w0, current, g, cov, "model",
            f"{template.name_nl}: gewichten bijstellen op de gemeten rangcorrelatie per pijler ({changes}).",
            {"coverage": cov.__dict__, **res.evidence}, champion_id)
        ids.append(pid)
        report.add("weight_proposals" if not problems else "weight_proposals_refused")
    return ids
