"""The quarterly review by a language model (chapter 9): the evaluation report in, change proposals with evidence,
expected effect and risks out. The model has no write access: each proposal goes through the same fixed
guardrail check as any other (store_weight_proposal) and is refused when it breaks one.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.calls import call
from app.ai.config import AiConfig
from app.evaluation.outcomes import EvaluationSettings, to_json
from app.ingest.report import Report
from app.learning.quarterly import coverage_for, store_weight_proposal
from app.learning.registry import baseline, weights_of
from app.learning.weights import Guardrails, bounds
from app.modelconfig import ModelConfig

SYSTEM = """\
Je beoordeelt elk kwartaal het gradingmodel van Graadmeter, een privé-app die beleggingsassets rangschikt. Je \
krijgt per sjabloon de huidige gewichten van de pijlers, de startgewichten, de grenzen die de vangrails toelaten, \
de datadekking en de gemeten rangcorrelaties uit de terugtest en de live meting.

Doe alleen een voorstel als de gemeten data het dragen. Een voorstel bevat per sjabloon de volledige set \
gewichten in procenten (som 100), het bewijs uit de invoer, het verwachte effect en de risico's. Houd je aan de \
grenzen uit "toegestaan": elk voorstel daarbuiten wordt automatisch geweigerd. Geen voorstel doen is een geldig \
en vaak het beste antwoord, zeker bij te weinig data of rangcorrelaties dicht bij nul. Je wijzigt zelf niets; \
de eigenaar beslist. Gebruik geen woorden als kopen, verkopen of koersdoel."""

SCHEMA = {
    "type": "object",
    "properties": {
        "samenvatting": {"type": "string"},
        "voorstellen": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "sjabloon": {"type": "string"},
                "gewichten": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"pijler": {"type": "string"}, "gewicht": {"type": "number"}},
                    "required": ["pijler", "gewicht"], "additionalProperties": False}},
                "bewijs": {"type": "string"},
                "verwacht_effect": {"type": "string"},
                "risicos": {"type": "string"},
            },
            "required": ["sjabloon", "gewichten", "bewijs", "verwacht_effect", "risicos"],
            "additionalProperties": False}},
    },
    "required": ["samenvatting", "voorstellen"],
    "additionalProperties": False,
}


def review_input(session: Session, settings: EvaluationSettings, champion: ModelConfig, champion_id: int) -> dict:
    g = Guardrails.from_settings(settings.raw)
    base, _ = baseline(session)
    latest = session.execute(text(
        """SELECT DISTINCT ON (source) source, report FROM evaluation WHERE model_version_id = :v
           ORDER BY source, computed_at DESC"""), {"v": champion_id}).mappings().all()
    reports = {r["source"]: r["report"] for r in latest}
    templates = {}
    for tid, t in champion.templates.items():
        if not t.pillars:
            continue
        cov, _ = coverage_for(session, tid, champion_id, int(settings.raw["learning"]["quarterly_horizon_months"]))
        current, w0 = weights_of(champion, tid), weights_of(base, tid)
        entry = {"naam": t.name_nl, "huidig": current, "start": w0,
                 "toegestaan": {p: {"min": lo, "max": hi} for p, (lo, hi) in bounds(w0, current, g).items()},
                 "dekking": cov.__dict__}
        for source, rep in reports.items():
            tr = (rep or {}).get("templates", {}).get(tid)
            if tr:
                entry[source] = {h: {"rangcorrelatie": m["ic"].get("mean"), "t": m["ic"].get("t_newey_west"),
                                     "maanden": m["ic"].get("months"),
                                     "pijlers": m["pillars"]["ic"]} for h, m in tr["horizons"].items()}
        templates[tid] = entry
    return to_json({"modelversie": champion.version, "minimale_data": {
        "terugtest_maanden": g.min_backtest_months, "assets_per_maand": g.min_assets_per_month,
        "live_maanden": g.min_live_months}, "sjablonen": templates})


def quarterly_review(session: Session, ai: AiConfig, client, settings: EvaluationSettings, champion: ModelConfig,
                     champion_id: int, report: Report, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(UTC)
    payload = review_input(session, settings, champion, champion_id)
    res = call(session, ai, client, "quarterly_review", SYSTEM, payload, SCHEMA, now,
               model_version_id=champion_id)
    if res.data is None:
        report.notes.append("Kwartaalbeoordeling door het taalmodel overgeslagen: " + "; ".join(res.problems))
        return []
    g = Guardrails.from_settings(settings.raw)
    base, _ = baseline(session)
    report.notes.append("Kwartaalbeoordeling: " + str(res.data.get("samenvatting", ""))[:500])
    ids = []
    for v in res.data.get("voorstellen", []):
        tid = v.get("sjabloon")
        if tid not in champion.templates or not champion.templates[tid].pillars:
            report.error(f"kwartaalbeoordeling: onbekend sjabloon {tid}")
            continue
        weights = {w["pijler"]: float(w["gewicht"]) for w in v.get("gewichten", [])}
        cov, _ = coverage_for(session, tid, champion_id, int(settings.raw["learning"]["quarterly_horizon_months"]))
        pid, problems = store_weight_proposal(
            session, tid, weights, weights_of(base, tid), weights_of(champion, tid), g, cov, "taalmodel",
            f"{champion.templates[tid].name_nl}: voorstel uit de kwartaalbeoordeling door het taalmodel.",
            {"bewijs": v.get("bewijs"), "verwacht_effect": v.get("verwacht_effect"), "risicos": v.get("risicos"),
             "llm_call_id": res.call_id, "coverage": cov.__dict__}, champion_id)
        ids.append(pid)
        report.add("review_proposals_refused" if problems else "review_proposals")
    return ids
