"""Notifications when a nightly run fails (phase 10): a webhook (ntfy, Synology Chat, Home Assistant, ...) and/or
e-mail over SMTP, both configured only in .env. Every attempt is logged in `notification`. Messages never contain
secrets: anything that looks like a key in a URL is masked before sending.
"""

import json
import logging
import re
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ops.config import OpsConfig

log = logging.getLogger("graadmeter.notify")

SECRET = re.compile(r"((?:api_key|apikey|token|api_token|x_cg_demo_api_key|key|password)=)[^&\s\"']+", re.I)


def mask(s: str) -> str:
    return SECRET.sub(r"\1***", s)


def _webhook(url: str, subject: str, body: str) -> None:
    # ntfy uses the Title header; other services simply receive the text.
    r = httpx.post(url, content=f"{subject}\n\n{body}".encode(), headers={"Title": subject}, timeout=15)
    r.raise_for_status()


def _email(smtp: dict, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, smtp["sender"], smtp["to"]
    msg.set_content(body)
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=20) as s:
        if smtp["starttls"]:
            s.starttls()
        if smtp["user"]:
            s.login(smtp["user"], smtp["password"] or "")
        s.send_message(msg)


def channels(ops: OpsConfig) -> list[str]:
    return [name for name, on in (("webhook", ops.webhook_url), ("e-mail", ops.smtp)) if on]


def send(session: Session, ops: OpsConfig, subject: str, body: str, kind: str, senders: dict | None = None) -> int:
    """Send to every configured channel and log each attempt. Returns the number delivered."""
    subject, body = mask(f"{ops.subject_prefix} {subject}"), mask(body)
    senders = senders or {"webhook": lambda s, b: _webhook(ops.webhook_url, s, b),
                          "e-mail": lambda s, b: _email(ops.smtp, s, b)}
    names = channels(ops)
    if not names:
        session.execute(text(
            "INSERT INTO notification (kind, channel, subject, body, ok, error) "
            "VALUES (:k, 'geen', :s, :b, false, :e)"),
            {"k": kind, "s": subject, "b": body[:4000], "e": "geen meldkanaal ingesteld"})
        session.commit()
        return 0
    delivered = 0
    for name in names:
        error = None
        try:
            senders[name](subject, body)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 - a failing channel is logged, never raised
            error = mask(f"{type(exc).__name__}: {exc}")[:500]
            log.warning("notification via %s failed: %s", name, error)
        session.execute(text(
            "INSERT INTO notification (kind, channel, subject, body, ok, error) VALUES (:k, :c, :s, :b, :ok, :e)"),
            {"k": kind, "c": name, "s": subject, "b": body[:4000], "ok": error is None, "e": error})
    session.commit()
    return delivered


def job_message(job: str, label: str, status: str, summary: dict | None, error: str | None) -> tuple[str, str]:
    counts = (summary or {}).get("counts") or {}
    errors = (summary or {}).get("errors") or []
    lines = [f"Taak: {label} ({job})", f"Status: {status}"]
    if error:
        lines += ["", "Fout:", error.strip().splitlines()[-1][:500]]
    if errors:
        lines += ["", f"{(summary or {}).get('error_count', len(errors))} meldingen, de eerste:"]
        lines += [f"- {e[:300]}" for e in errors[:10]]
    if counts:
        lines += ["", "Tellingen: " + json.dumps(counts, ensure_ascii=False)[:800]]
    lines += ["", "Zie Instellingen en verbruik in Graadmeter voor details."]
    return f"{label}: {'mislukt' if status == 'failed' else 'met fouten'}", "\n".join(lines)


def should_notify(ops: OpsConfig, status: str, summary: dict | None) -> bool:
    if status == "failed":
        return ops.notify_on_failed
    if status == "partial":
        return int((summary or {}).get("error_count") or 0) >= ops.partial_min_errors
    return False
