"""Analysis of big misses (chapter 9): an A or B grade that then lagged the benchmark by more than 30%.

The language model gets the grade as it was and its outcome, explains what may have been missed and may name
one existing metric and a direction as a candidate gate. It never supplies a threshold: the code tries every
decile of that metric over the whole backtest and counts, per threshold, the misses it would have caught and
the false alarms (A and B grades it would have capped that did not miss). The result is a proposal for the
owner; turning it into a gate is a model change (new version) like any other.
Only live misses are analysed: a model knows how old events ended, so it is not shown backtest history.
"""

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.calls import call
from app.ai.config import AiConfig
from app.evaluation.outcomes import EvaluationSettings, grade_source_sql, to_json
from app.ingest.report import Report
from app.learning.promotion import latest_run
from app.modelconfig import ModelConfig

SYSTEM = """\
Je analyseert een misser van Graadmeter, een privé-app die beleggingsassets rangschikt: een asset kreeg een A \
of B en bleef daarna ruim achter bij de benchmark. Je krijgt de grade zoals die toen was, met alle maatstaven en \
pijlers, en de uitkomst. Er is geen nieuwsbron gekoppeld; zeg het als de verklaring vooral in nieuws zou liggen.

Leg in gewone taal uit wat het model gemist kan hebben. Noem hoogstens één bestaande maatstaf uit "maatstaven" \
die een harde regel had kunnen zijn, met de richting: "laag" als een lage waarde het risico was, "hoog" als een \
hoge waarde het risico was, of "geen" als geen maatstaf past. Noem geen drempel en geen getallen die niet in de \
invoer staan; de app toetst zelf welke drempel over de hele terugtest werkt. Gebruik geen woorden als kopen, \
verkopen of koersdoel."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verklaring": {"type": "string"},
        "vooral_nieuws": {"type": "boolean"},
        "maatstaf": {"type": "string"},
        "richting": {"type": "string", "enum": ["laag", "hoog", "geen"]},
        "reden": {"type": "string"},
    },
    "required": ["verklaring", "vooral_nieuws", "maatstaf", "richting", "reden"],
    "additionalProperties": False,
}


def live_misses(session: Session, model_version_id: int, horizon: int, below: float) -> list[dict]:
    """Live A/B month-end grades that lagged by more than `below`, not analysed before."""
    rows = session.execute(text(
        f"""
        SELECT g.asset_id, a.name, g.as_of, g.template_id, g.letter, g.score, g.result, g.inputs,
               o.excess_return, o.total_return, o.max_drawdown, o.benchmark
        FROM ({grade_source_sql('live')}) g
        JOIN asset a ON a.id = g.asset_id
        JOIN outcome o ON o.source = 'live' AND o.asset_id = g.asset_id AND o.as_of = g.as_of
             AND o.model_version_id = :v AND o.horizon_months = :h
        WHERE left(g.letter, 1) IN ('A', 'B') AND o.excess_return < :below
          AND NOT EXISTS (SELECT 1 FROM llm_call c WHERE c.component = 'miss_analysis' AND c.asset_id = g.asset_id
                          AND c.snapshot_as_of = g.as_of)
        ORDER BY g.as_of DESC
        """), {"run": None, "v": model_version_id, "h": horizon, "below": below}).mappings().all()
    return [dict(r) for r in rows]


def miss_input(m: dict, horizon: int) -> dict:
    metrics = []
    for p in m["result"].get("pillars", []):
        for x in p.get("metrics", []):
            metrics.append({"id": x["id"], "pijler": p["name_nl"], "waarde": x.get("value"), "score": x.get("score")})
    return to_json({"asset": m["name"], "datum": m["as_of"], "sjabloon": m["template_id"], "grade": m["letter"],
                    "score": m["score"], "pijlers": [{"naam": p["name_nl"], "score": p.get("score")}
                                                    for p in m["result"].get("pillars", [])],
                    "harde_regels": m["result"].get("gates", []), "maatstaven": metrics,
                    "uitkomst": {"horizon_maanden": horizon, "rendement": m["total_return"],
                                 "boven_benchmark": m["excess_return"], "benchmark": m["benchmark"],
                                 "grootste_daling": m["max_drawdown"]}})


def evaluate_gate(session: Session, run_id: int, model_version_id: int, template_id: str, metric: str,
                  direction: str, horizon: int, below: float) -> dict:
    """Every decile of the metric as threshold over the backtest: misses caught and false alarms."""
    rows = session.execute(text(
        f"""
        SELECT (g.inputs->'grade_input'->'metrics'->:m->>'value')::float8 AS value, g.letter,
               o.excess_return AS excess
        FROM ({grade_source_sql('backtest')}) g
        JOIN outcome o ON o.run_id = g.run_id AND o.asset_id = g.asset_id AND o.as_of = g.as_of
             AND o.horizon_months = :h
        WHERE g.template_id = :t AND left(g.letter, 1) IN ('A', 'B')
        """), {"run": run_id, "v": model_version_id, "m": metric, "h": horizon, "t": template_id}).all()
    df = pd.DataFrame(rows, columns=["value", "letter", "excess"]).dropna()
    if df.empty:
        return {"observations": 0, "misses": 0, "thresholds": [], "best": None}
    miss = df["excess"] < below
    table = []
    for q in range(10, 100, 10):
        t = float(np.percentile(df["value"], q))
        flagged = df["value"] <= t if direction == "laag" else df["value"] >= t
        caught, false = int((flagged & miss).sum()), int((flagged & ~miss).sum())
        table.append({"percentile": q, "threshold": t, "flagged": int(flagged.sum()), "misses_caught": caught,
                      "false_alarms": false,
                      "youden": (caught / max(int(miss.sum()), 1)) - (false / max(int((~miss).sum()), 1))})
    best = max(table, key=lambda r: r["youden"]) if table else None
    return {"observations": int(len(df)), "misses": int(miss.sum()), "thresholds": table, "best": best}


def analyse_misses(session: Session, ai: AiConfig, client, settings: EvaluationSettings, champion: ModelConfig,
                   champion_id: int, report: Report, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(UTC)
    cfg = settings.raw["learning"]["miss_analysis"]
    h, below = int(cfg["horizon_months"]), float(cfg["excess_below"])
    misses = live_misses(session, champion_id, h, below)[: int(cfg["max_per_quarter"])]
    if not misses:
        report.notes.append("Geen nieuwe live missers om te analyseren.")
        return []
    run = latest_run(session, champion_id)
    ids = []
    for m in misses:
        payload = miss_input(m, h)
        res = call(session, ai, client, "miss_analysis", SYSTEM, payload, SCHEMA, now, asset_id=m["asset_id"],
                   model_version_id=champion_id, snapshot_as_of=m["as_of"])
        if res.data is None:
            report.notes.append(f"Misser {m['name']} niet geanalyseerd: " + "; ".join(res.problems))
            continue
        known = {x["id"] for x in payload["maatstaven"]}
        metric, direction = res.data.get("maatstaf"), res.data.get("richting")
        evidence = {"misser": payload, "verklaring": res.data.get("verklaring"),
                    "vooral_nieuws": res.data.get("vooral_nieuws"), "reden": res.data.get("reden"),
                    "llm_call_id": res.call_id}
        if direction == "geen" or metric not in known:
            evidence["toets"] = None
            summary = f"Misser {m['name']} ({m['letter']}, {m['as_of']}): geen kandidaat voor een harde regel."
        else:
            evidence["toets"] = evaluate_gate(session, run, champion_id, m["template_id"], metric, direction, h,
                                              below) if run else None
            summary = (f"Kandidaat-gate na misser {m['name']} ({m['letter']}, {m['as_of']}): {metric} "
                       f"{'laag' if direction == 'laag' else 'hoog'} als risico, getoetst over de terugtest.")
        ids.append(session.execute(text(
            """INSERT INTO model_proposal (kind, model_version_id, run_id, summary_nl, payload, evidence, source)
               VALUES ('gate_candidate', :v, :r, :s, :p, :e, 'taalmodel') RETURNING id"""),
            {"v": champion_id, "r": run, "s": summary,
             "p": json.dumps({"template": m["template_id"], "metric": metric, "direction": direction}),
             "e": json.dumps(to_json(evidence))}).scalar())
        session.commit()
        report.add("gate_candidates")
    return ids
