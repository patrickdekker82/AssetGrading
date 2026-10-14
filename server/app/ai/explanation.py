"""Explanations written by a language model (chapter 9), with a number check and the template as fallback.

The model gets a JSON with the computed grade of one asset and returns Dutch text plus the metrics it used.
Every number in the text is checked against that JSON; on a mismatch there is one new attempt, after that
the fixed template text stays. Every call is logged with model, prompt version, input hash and output.
Explanations run nightly through the batch API and are only rewritten when the grade changes or a pillar
moves more than the configured number of points. Without an API key nothing is called.
"""

import hashlib
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import LlmResult
from app.ai.config import AiConfig
from app.ai.numbers import check_text
from app.grading.explain import change_thresholds, explain
from app.ingest.report import Report
from app.modelconfig import ModelConfig

log = logging.getLogger("graadmeter.ai")

COMPONENT = "explanation"

STATUS_NL = {
    "graded": "beoordeeld", "provisional": "voorlopig (te weinig vergelijkbare assets of data)",
    "speculative": "speculatief (alleen veiligheidscontrole)", "peg_safety": "stablecoin (pegveiligheid)",
    "no_grade": "geen grade",
}

# The fixed instruction. Changing it means a new prompt_version in config/ai.yaml.
SYSTEM_PROMPT = """\
Je schrijft de toelichting bij de grade van één asset in Graadmeter, een privé-app voor onderzoek die \
beleggingsassets rangschikt met een letter van A+ tot F en een score van 0 tot 100. De grade is al \
berekend door een vast model. Jij rekent niets uit en beoordeelt niets opnieuw: je legt in gewone, \
zakelijke Nederlandse taal uit wat de berekening laat zien.

Je krijgt één JSON-object met de uitkomst. Schrijf een lopende tekst van 120 tot 200 woorden die:
1. noemt welke grade en score de asset heeft en binnen welk sjabloon;
2. uitlegt hoe Kwaliteit en Timing zich tot elkaar verhouden, als beide in de invoer staan;
3. de drie sterkste en de drie zwakste punten noemt uit "sterkste_punten" en "zwakste_punten";
4. de geraakte harde regels noemt met hun gevolg, als die er zijn;
5. zegt wat de grade zou veranderen, met de drempels uit "wat_de_grade_verandert";
6. de notities uit "notities" verwerkt als ze er zijn, zoals een marktregime of een tegenspraak tussen \
macro en koers;
7. de datadekking noemt als die onder 100 procent ligt.

Strikte regels:
- Gebruik uitsluitend getallen die letterlijk in de invoer staan, precies zoals ze daar staan. Rond niet \
af, reken niets uit, tel niets op, maak geen verschillen of percentages.
- Schrijf getallen altijd in cijfers, nooit in woorden. Schrijf dus niet "drie" maar laat het aantal weg \
of gebruik een cijfer uit de invoer.
- Gebruik alleen grades (lettercombinaties zoals B+ of C-) die in de invoer staan.
- Geef geen advies, geen voorspelling en geen koersverwachting. Gebruik nooit de woorden kopen, \
verkopen of koersdoel. Een grade is een rangorde binnen een groep vergelijkbare assets, geen oordeel \
over wat iemand moet doen.
- Scores van maatstaven en pijlers lopen van 0 tot 100 en zijn percentielen ten opzichte van vergelijkbare \
assets; noem ze zo als dat de tekst duidelijker maakt.
- Is de status "geen grade", leg dan uit waarom niet en wat er wel beschikbaar is.
- Is het een stablecoin, leg dan de pegveiligheid uit in plaats van een grade.
- Schrijf in de derde persoon over de asset, zonder kopjes, opsommingstekens of opmaak.

Geef het antwoord als JSON met "tekst" (de toelichting) en "gebruikte_maatstaven" (de id's uit \
"maatstaven" waarop de tekst steunt)."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tekst": {"type": "string"},
        "gebruikte_maatstaven": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tekst", "gebruikte_maatstaven"],
    "additionalProperties": False,
}


def _int(v: float | None) -> int | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else int(f"{v:.0f}")


def build_input(name: str, as_of: date, result: dict, config: ModelConfig, labels: dict[str, str]) -> dict:
    """Everything the text may say, already rounded the way it may be written."""
    template = config.templates[result["template_id"]]
    metrics = []
    for p in result.get("pillars", []):
        for m in p.get("metrics", []):
            if m.get("score") is not None:
                metrics.append({"id": m["id"], "naam": labels.get(m["id"], m["id"]), "pijler": p["name_nl"],
                                "score": _int(m["score"])})
    by_score = sorted(metrics, key=lambda m: (-m["score"], m["id"]))
    payload: dict = {
        "asset": name,
        "datum": as_of.isoformat(),
        "sjabloon": template.name_nl,
        "status": STATUS_NL.get(result["status"], result["status"]),
        "grade": result.get("letter"),
        "score": _int(result.get("score")),
        "kwaliteit": _int(result.get("quality")),
        "timing": _int(result.get("timing")),
        "schaal": "scores lopen van 0 tot 100",
        "pijlers": [{"naam": p["name_nl"], "score": _int(p.get("score")),
                     "gewicht_pct": _int(p.get("effective_weight"))}
                    for p in result.get("pillars", []) if p.get("score") is not None],
        "pijlers_zonder_data": [p["name_nl"] for p in result.get("pillars", []) if p.get("score") is None],
        "maatstaven": metrics,
        "sterkste_punten": by_score[:3] if len(metrics) >= 2 else [],
        "zwakste_punten": sorted(metrics, key=lambda m: (m["score"], m["id"]))[:3] if len(metrics) >= 2 else [],
        "harde_regels_geraakt": [{"reden": g["reason_nl"], "hoogst_mogelijke_grade": g.get("cap")}
                                 for g in result.get("gates", []) if g["status"] == "hit"],
        "harde_regels_niet_te_controleren": sum(1 for g in result.get("gates", []) if g["status"] == "unknown"),
        "datadekking_pct": int(result["coverage"] * 100) if result.get("coverage") is not None else None,
        "notities": list(result.get("notes", [])),
        "labels": list(result.get("labels", [])),
    }
    if result.get("letter_low") and result.get("letter_high") and result["letter_low"] != result["letter_high"]:
        payload["bandbreedte"] = {"laagste_grade": result["letter_low"], "hoogste_grade": result["letter_high"],
                                  "gewichten_hoger_of_lager_pct": _int(
                                      config.settings.stability.band_weight_shift * 100)}
    if result["status"] in ("graded", "provisional") and result.get("score") is not None:
        t = change_thresholds(result, config)
        if t:
            payload["wat_de_grade_verandert"] = {
                "omhoog": {"boven_score": int(t["up"]["above"]), "wordt": t["up"]["grade"]} if "up" in t else None,
                "omlaag": {"onder_score": int(t["down"]["below"]), "wordt": t["down"]["grade"]}
                if "down" in t else None,
                "marge_punten": t["margin"],
                "harde_regel_houdt_grade_lager": t["capped"],
            }
    if result["status"] == "peg_safety":
        payload["pegveiligheid"] = result.get("peg_safety")
        payload["schaal_pegveiligheid"] = "1 (sterk) tot 5 (zwak)"
    if result["status"] == "speculative":
        payload["hoogst_mogelijke_grade_voor_dit_sjabloon"] = template.max_grade
    if result["status"] == "no_grade":
        payload["reden_geen_grade"] = result.get("reason_nl")
    if template.note_nl:
        payload["sjabloon_notitie"] = template.note_nl.strip()
    return payload


def canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_hash(payload: dict, settings) -> str:
    return hashlib.sha256(f"{settings.model}|{settings.prompt_version}|{canonical(payload)}".encode()).hexdigest()


def request_params(ai: AiConfig, payload: dict, problems: list[str] | None = None) -> dict:
    s = ai.explanation
    user = "Invoer:\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    if problems:
        user += ("\n\nEen eerdere tekst voor deze invoer werd afgekeurd door de controle: " + "; ".join(problems)
                 + ". Schrijf een nieuwe tekst die zich strikt aan de regels houdt.")
    return {
        "model": s.model,
        "max_tokens": s.max_tokens,
        # The fixed instruction is cached; only the asset's JSON changes between requests.
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": s.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


@dataclass
class Checked:
    passed: bool
    text: str | None
    used: list[str]
    problems: list[str]


def check_result(res: LlmResult, payload: dict, ai: AiConfig) -> Checked:
    """Stop reason, JSON schema, numbers, grades, length and forbidden words."""
    if res.error:
        return Checked(False, None, [], [f"fout: {res.error}"])
    if res.stop_reason != "end_turn":
        # max_tokens can cut the JSON in half; refusal has no usable text at all.
        return Checked(False, None, [], [f"stopreden {res.stop_reason}"])
    try:
        data = json.loads(res.text)
        body, used = data["tekst"], data["gebruikte_maatstaven"]
        if not isinstance(body, str) or not isinstance(used, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return Checked(False, None, [], ["antwoord volgt het schema niet"])
    body = " ".join(body.split())
    problems = check_text(body, payload, ai.explanation.min_words, ai.explanation.max_words)
    known = {m["id"] for m in payload["maatstaven"]}
    unknown = sorted(str(u) for u in used if u not in known)
    if unknown:
        problems.append("onbekende maatstaven: " + ", ".join(unknown))
    return Checked(not problems, body, [str(u) for u in used], problems)


# --- persistence -----------------------------------------------------------------------------------


@dataclass
class Snapshot:
    asset_id: int
    name: str
    as_of: date
    model_version_id: int
    result: dict
    status: str
    letter: str | None
    score: float | None
    peg_safety: int | None

    @property
    def custom_id(self) -> str:
        return f"a{self.asset_id}-{self.as_of:%Y%m%d}"

    def pillars(self) -> dict[str, float | None]:
        return {p["id"]: p.get("score") for p in self.result.get("pillars", [])}


SNAPSHOT_SQL = """
    SELECT g.asset_id, a.name, g.as_of, g.model_version_id, g.result, g.status, g.letter, g.score, g.peg_safety
    FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id
"""


def _snapshot(row) -> Snapshot:
    return Snapshot(row.asset_id, row.name, row.as_of, row.model_version_id, row.result, row.status, row.letter,
                    row.score, row.peg_safety)


def latest_snapshots(session: Session, model_version_id: int, asset_ids: list[int] | None = None) -> list[Snapshot]:
    where = "AND g.asset_id = ANY(:ids)" if asset_ids is not None else ""
    rows = session.execute(text(
        f"""
        SELECT DISTINCT ON (g.asset_id) g.asset_id, a.name, g.as_of, g.model_version_id, g.result, g.status,
               g.letter, g.score, g.peg_safety
        FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id
        WHERE g.model_version_id = :v {where}
        ORDER BY g.asset_id, g.as_of DESC
        """), {"v": model_version_id, "ids": asset_ids}).all()
    return [_snapshot(r) for r in rows]


def snapshot_on(session: Session, model_version_id: int, asset_id: int, as_of: date) -> Snapshot | None:
    row = session.execute(text(SNAPSHOT_SQL + " WHERE g.model_version_id = :v AND g.asset_id = :a AND g.as_of = :d"),
                          {"v": model_version_id, "a": asset_id, "d": as_of}).first()
    return _snapshot(row) if row else None


def latest_explanation(session: Session, model_version_id: int, asset_id: int):
    return session.execute(text(
        """
        SELECT * FROM explanation WHERE asset_id = :a AND model_version_id = :v
        ORDER BY created_at DESC, id DESC LIMIT 1
        """), {"a": asset_id, "v": model_version_id}).mappings().first()


def needs_new(prev, snap: Snapshot, shift: float) -> bool:
    """Rewrite only when the grade changes or a pillar (or the score) moves more than `shift` points."""
    if prev is None:
        return True
    if prev["status"] != snap.status or prev["letter"] != snap.letter or prev["peg_safety"] != snap.peg_safety:
        return True

    def moved(a, b) -> bool:
        if a is None or b is None:
            return (a is None) != (b is None)
        return abs(a - b) > shift

    if moved(prev["score"], snap.score):
        return True
    old, new = prev["pillars"] or {}, snap.pillars()
    return any(moved(old.get(k), new.get(k)) for k in set(old) | set(new))


def log_call(session: Session, ai: AiConfig, snap: Snapshot, payload: dict, res: LlmResult, checked: Checked,
             mode: str, attempt: int, batch_id: str | None) -> int:
    s = ai.explanation
    cost = ai.cost_usd(res.model or s.model, res.usage, batch=mode == "batch") if res.usage else 0.0
    return session.execute(text(
        """
        INSERT INTO llm_call (component, model, prompt_version, input_hash, asset_id, model_version_id,
                              snapshot_as_of, mode, batch_id, attempt, stop_reason, output, passed, problems,
                              usage, cost_usd, request_id, error)
        VALUES (:c, :m, :pv, :h, :a, :v, :d, :mode, :b, :att, :sr, :out, :ok, :p, :u, :cost, :rid, :err)
        RETURNING id
        """), {
        "c": COMPONENT, "m": res.model or s.model, "pv": s.prompt_version, "h": input_hash(payload, s),
        "a": snap.asset_id, "v": snap.model_version_id, "d": snap.as_of, "mode": mode, "b": batch_id,
        "att": attempt, "sr": res.stop_reason, "out": res.text or None, "ok": checked.passed,
        "p": json.dumps(checked.problems, ensure_ascii=False), "u": json.dumps(res.usage), "cost": cost,
        "rid": res.request_id, "err": res.error,
    }).scalar()


def store_explanation(session: Session, ai: AiConfig, snap: Snapshot, source: str, body: str,
                      used: list[str] | None, call_id: int | None) -> None:
    session.execute(text(
        """
        INSERT INTO explanation (asset_id, model_version_id, snapshot_as_of, source, text, used_metrics,
                                 llm_call_id, prompt_version, status, letter, score, peg_safety, pillars)
        VALUES (:a, :v, :d, :src, :t, :u, :c, :pv, :st, :l, :s, :peg, :p)
        """), {
        "a": snap.asset_id, "v": snap.model_version_id, "d": snap.as_of, "src": source, "t": body,
        "u": json.dumps(used) if used is not None else None, "c": call_id, "pv": ai.explanation.prompt_version,
        "st": snap.status, "l": snap.letter, "s": snap.score, "peg": snap.peg_safety,
        "p": json.dumps(snap.pillars()),
    })


# --- budget ----------------------------------------------------------------------------------------


def month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def spent_usd(session: Session, now: datetime) -> float:
    """Cost logged this month plus the reservation of batches still running."""
    used = session.execute(text("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_call WHERE created_at >= :s"),
                           {"s": month_start(now)}).scalar()
    reserved = session.execute(text(
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM llm_batch WHERE status = 'submitted'")).scalar()
    return float(used) + float(reserved)


def estimate_usd(ai: AiConfig, params: dict, batch: bool) -> float:
    """Upper bound for one request: about 3 characters per token in, the full max_tokens out."""
    chars = len(SYSTEM_PROMPT) + sum(len(m["content"]) for m in params["messages"])
    usage = {"input_tokens": chars // 3 + 50, "output_tokens": params["max_tokens"]}
    return ai.cost_usd(params["model"], usage, batch)


# --- running ---------------------------------------------------------------------------------------


@dataclass
class Explainer:
    sf: sessionmaker[Session]
    ai: AiConfig
    model: ModelConfig
    model_version_id: int
    labels: dict[str, str]
    client: object | None            # AnthropicClient or a test double; None without an API key
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def payload(self, snap: Snapshot) -> dict:
        return build_input(snap.name, snap.as_of, snap.result, self.model, self.labels)

    def _budget_left(self, session: Session) -> float:
        return self.ai.monthly_budget_usd - spent_usd(session, self.now())

    def _finish(self, session: Session, snap: Snapshot, payload: dict, res: LlmResult, mode: str,
                batch_id: str | None, report: Report) -> None:
        """Check an answer; one direct retry on failure, then the template text."""
        checked = check_result(res, payload, self.ai)
        call_id = log_call(session, self.ai, snap, payload, res, checked, mode, 1, batch_id)
        if not checked.passed:
            report.add("explanations_rejected", 1)
            params = request_params(self.ai, payload, checked.problems)
            if self._budget_left(session) >= estimate_usd(self.ai, params, batch=False):
                retry = self.client.create(params)
                checked = check_result(retry, payload, self.ai)
                call_id = log_call(session, self.ai, snap, payload, retry, checked, "direct", 2, None)
            else:
                report.note_once("Maandbudget taalmodel bereikt; geen nieuwe poging.")
        if checked.passed:
            store_explanation(session, self.ai, snap, "model", checked.text, checked.used, call_id)
            report.add("explanations_written", 1)
        else:
            body = explain(snap.name, snap.result, self.model, self.labels)
            store_explanation(session, self.ai, snap, "template", body, None, call_id)
            report.add("explanations_template", 1)
            report.error(f"toelichting {snap.name}: " + "; ".join(checked.problems)[:300])
        session.commit()

    def explain_now(self, asset_id: int, report: Report | None = None) -> Report:
        """One asset, directly (not through the batch API), for the command line."""
        report = report or Report()
        if self.client is None:
            report.error("Geen API-sleutel voor het taalmodel (ANTHROPIC_API_KEY).")
            return report
        with self.sf() as session:
            snaps = latest_snapshots(session, self.model_version_id, [asset_id])
            if not snaps:
                report.error("Geen grade voor deze asset.")
                return report
            snap, payload = snaps[0], self.payload(snaps[0])
            params = request_params(self.ai, payload)
            if self._budget_left(session) < estimate_usd(self.ai, params, batch=False):
                report.error("Maandbudget taalmodel bereikt.")
                return report
            self._finish(session, snap, payload, self.client.create(params), "direct", None, report)
        return report

    def collect(self, report: Report) -> None:
        """Process every batch that has ended; give up on batches older than the poll window."""
        with self.sf() as session:
            pending = session.execute(text(
                "SELECT id, batch_id, model_version_id, submitted_at FROM llm_batch WHERE status = 'submitted' "
                "AND component = :c ORDER BY id"), {"c": COMPONENT}).all()
        for row in pending:
            try:
                status = self.client.batch_status(row.batch_id)
            except Exception as exc:  # noqa: BLE001 - try again next run
                report.error(f"batch {row.batch_id}: {type(exc).__name__}")
                continue
            if status != "ended":
                if self.now() - row.submitted_at > timedelta(hours=self.ai.explanation.batch_poll_hours):
                    try:
                        self.client.cancel_batch(row.batch_id)
                    except Exception:  # noqa: BLE001 - it is given up either way
                        pass
                    self._mark(row.id, "expired")
                    report.error(f"batch {row.batch_id} niet op tijd klaar; opgegeven")
                continue
            for custom_id, res in self.client.batch_results(row.batch_id):
                asset_id, day = custom_id[1:].split("-")
                with self.sf() as session:
                    snap = snapshot_on(session, row.model_version_id, int(asset_id),
                                       datetime.strptime(day, "%Y%m%d").date())
                    if snap is None:
                        continue
                    self._finish(session, snap, self.payload(snap), res, "batch", row.batch_id, report)
            self._mark(row.id, "ended")
            report.add("batches_collected", 1)

    def _mark(self, row_id: int, status: str) -> None:
        with self.sf() as session:
            session.execute(text("UPDATE llm_batch SET status = :s, ended_at = now() WHERE id = :i"),
                            {"s": status, "i": row_id})
            session.commit()

    def candidates(self, session: Session) -> list[Snapshot]:
        """Latest snapshots whose explanation is missing or out of date, watchlist first."""
        in_flight = set()
        for (ids,) in session.execute(text(
                "SELECT custom_ids FROM llm_batch WHERE status = 'submitted' AND component = :c"), {"c": COMPONENT}):
            in_flight |= set(ids)
        watched = set(session.execute(text("SELECT asset_id FROM watchlist_item")).scalars())
        shift = self.ai.explanation.regenerate_shift_points
        out = []
        for snap in latest_snapshots(session, self.model_version_id):
            if snap.custom_id in in_flight:
                continue
            if needs_new(latest_explanation(session, self.model_version_id, snap.asset_id), snap, shift):
                out.append(snap)
        return sorted(out, key=lambda s: (s.asset_id not in watched, s.asset_id))

    def submit(self, report: Report) -> None:
        with self.sf() as session:
            todo = self.candidates(session)
            if not todo:
                report.notes.append("Alle toelichtingen zijn actueel.")
                return
            left = self._budget_left(session)
        requests, reserved = [], 0.0
        for snap in todo:
            params = request_params(self.ai, self.payload(snap))
            cost = estimate_usd(self.ai, params, batch=True)
            if reserved + cost > left:
                report.notes.append(f"Maandbudget taalmodel bereikt: {len(todo) - len(requests)} toelichtingen "
                                    "wachten op de volgende maand en tonen de sjabloontekst.")
                break
            requests.append((snap.custom_id, params))
            reserved += cost
        if not requests:
            return
        batch_id = self.client.submit_batch(requests)
        with self.sf() as session:
            session.execute(text(
                """
                INSERT INTO llm_batch (batch_id, component, model, prompt_version, model_version_id, custom_ids,
                                       estimated_cost_usd, status)
                VALUES (:b, :c, :m, :pv, :v, :ids, :est, 'submitted')
                """), {"b": batch_id, "c": COMPONENT, "m": self.ai.explanation.model,
                       "pv": self.ai.explanation.prompt_version, "v": self.model_version_id,
                       "ids": json.dumps([cid for cid, _ in requests]), "est": reserved})
            session.commit()
        report.add("explanations_submitted", len(requests))

    def run(self) -> Report:
        """The nightly job: collect finished batches, then submit what is missing or out of date."""
        report = Report()
        if self.client is None:
            report.notes.append("Geen API-sleutel voor het taalmodel; de app toont de sjabloontekst.")
            return report
        self.collect(report)
        self.submit(report)
        return report


# --- what the asset page shows ---------------------------------------------------------------------


def shown_explanation(session: Session, ai: AiConfig, model: ModelConfig, snap: Snapshot,
                      labels: dict[str, str]) -> dict:
    """The model text when it is still current for this grade, otherwise the template text."""
    prev = latest_explanation(session, snap.model_version_id, snap.asset_id)
    current = prev is not None and not needs_new(prev, snap, ai.explanation.regenerate_shift_points)
    if current and prev["source"] == "model":
        return {"text": prev["text"], "source": "taalmodel", "written_for": prev["snapshot_as_of"],
                "used_metrics": prev["used_metrics"] or []}
    return {"text": explain(snap.name, snap.result, model, labels), "source": "sjabloon",
            "written_for": snap.as_of, "used_metrics": [],
            "rejected": bool(current and prev["source"] == "template")}
