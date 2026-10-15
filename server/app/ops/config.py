"""config/operations.yaml and the notification settings from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class OpsConfig:
    backup_dir: Path
    keep_daily: int
    keep_monthly: int
    restore_database: str
    notify_on_failed: bool
    partial_min_errors: int
    subject_prefix: str
    watchdog_hours: dict[str, float]
    env: Mapping[str, str] = field(default_factory=dict)

    # Notification channels, all optional, all from .env.
    @property
    def webhook_url(self) -> str | None:
        return (self.env.get("NOTIFY_WEBHOOK_URL") or "").strip() or None

    @property
    def smtp(self) -> dict | None:
        host, to = (self.env.get("SMTP_HOST") or "").strip(), (self.env.get("NOTIFY_EMAIL_TO") or "").strip()
        if not host or not to:
            return None
        return {"host": host, "port": int(self.env.get("SMTP_PORT") or 587),
                "user": (self.env.get("SMTP_USER") or "").strip() or None,
                "password": self.env.get("SMTP_PASSWORD") or None,
                "starttls": (self.env.get("SMTP_STARTTLS") or "true").lower() != "false",
                "sender": (self.env.get("NOTIFY_EMAIL_FROM") or "").strip() or to, "to": to}


def load_ops_config(path: Path, env: Mapping[str, str] | None = None) -> OpsConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    env = env if env is not None else os.environ
    return OpsConfig(
        backup_dir=Path(env.get("BACKUP_DIR") or raw["backup"]["dir"]),
        keep_daily=int(raw["backup"]["keep_daily"]), keep_monthly=int(raw["backup"]["keep_monthly"]),
        restore_database=raw["restore_test"]["database"],
        notify_on_failed=bool(raw["notify"]["on_failed"]),
        partial_min_errors=int(raw["notify"]["partial_min_errors"]),
        subject_prefix=raw["notify"]["subject_prefix"],
        watchdog_hours={k: float(v) for k, v in raw["watchdog"].items()},
        # Only what the notification channels need; nothing else from the environment is kept.
        env={k: v for k, v in env.items() if k.startswith(("NOTIFY_", "SMTP_"))},
    )
