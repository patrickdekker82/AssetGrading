"""One direct, logged call for the language-model components of chapter 9 other than the explanation:
budget check first, JSON by schema, stop reason checked, every call stored in llm_call (model, prompt version,
input hash, raw output). Without a client (no API key) nothing is called.
"""

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.client import LlmResult
from app.ai.config import AiConfig
from app.ai.explanation import budget_usd, spent_usd


@dataclass
class CallResult:
    data: dict | None
    problems: list[str] = field(default_factory=list)
    call_id: int | None = None


def params_for(ai: AiConfig, component: str, system: str, payload: dict, schema: dict) -> dict:
    c = ai.components[component]
    return {
        "model": c.model,
        "max_tokens": c.max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Invoer:\n" + json.dumps(payload, ensure_ascii=False, indent=1)}],
        "output_config": {"effort": c.effort, "format": {"type": "json_schema", "schema": schema}},
    }


def call(session: Session, ai: AiConfig, client, component: str, system: str, payload: dict, schema: dict,
         now, asset_id: int | None = None, model_version_id: int | None = None, snapshot_as_of=None) -> CallResult:
    if client is None:
        return CallResult(None, ["geen API-sleutel voor het taalmodel"])
    c = ai.components[component]
    params = params_for(ai, component, system, payload, schema)
    chars = len(system) + len(params["messages"][0]["content"])
    estimate = ai.cost_usd(c.model, {"input_tokens": chars // 3 + 50, "output_tokens": c.max_tokens}, batch=False)
    if spent_usd(session, now) + estimate > budget_usd(session, ai):
        return CallResult(None, ["maandbudget taalmodel bereikt"])
    res: LlmResult = client.create(params)
    problems, data = [], None
    if res.error:
        problems.append(f"fout: {res.error}")
    elif res.stop_reason != "end_turn":
        problems.append(f"stopreden {res.stop_reason}")
    else:
        try:
            data = json.loads(res.text)
        except ValueError:
            problems.append("antwoord volgt het schema niet")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cost = ai.cost_usd(res.model or c.model, res.usage, batch=False) if res.usage else 0.0
    call_id = session.execute(text(
        """
        INSERT INTO llm_call (component, model, prompt_version, input_hash, asset_id, model_version_id,
                              snapshot_as_of, mode, attempt, stop_reason, output, passed, problems, usage, cost_usd,
                              request_id, error)
        VALUES (:c, :m, :pv, :h, :a, :v, :d, 'direct', 1, :sr, :out, :ok, :p, :u, :cost, :rid, :err) RETURNING id
        """), {
        "c": component, "m": res.model or c.model, "pv": c.prompt_version,
        "h": hashlib.sha256(f"{c.model}|{c.prompt_version}|{canonical}".encode()).hexdigest(), "a": asset_id,
        "v": model_version_id, "d": snapshot_as_of, "sr": res.stop_reason, "out": res.text or None,
        "ok": data is not None,
        "p": json.dumps(problems, ensure_ascii=False), "u": json.dumps(res.usage), "cost": cost,
        "rid": res.request_id, "err": res.error}).scalar()
    session.commit()
    return CallResult(data, problems, call_id)
