"""Operations (phase 10): back-up and proven restore, notifications, the watchdog and resource metering."""

import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.ingest.report import Report
from app.ops.backup import backup, dumps, prune, restore_test
from app.ops.config import load_ops_config
from app.ops.notify import job_message, mask, send, should_notify
from app.ops.resources import ResourceMeter
from app.ops.watchdog import run_watchdog
from tests.test_ingest import db, scalar  # noqa: F401  (shared fixtures)
from tests.test_stocks import TODAY, stock_world  # noqa: F401


@pytest.fixture
def ops(config_dir, tmp_path):
    return load_ops_config(config_dir / "operations.yaml",
                           env={"BACKUP_DIR": str(tmp_path / "backups"), "NOTIFY_WEBHOOK_URL": "https://example.org/x",
                                "FRED_API_KEY": "should-not-be-kept"})


def test_only_notification_settings_are_kept_from_the_environment(ops):
    assert set(ops.env) == {"NOTIFY_WEBHOOK_URL"} and ops.webhook_url and ops.smtp is None


def test_prune_keeps_recent_and_monthly_dumps(tmp_path):
    start = datetime(2025, 1, 1, 2, tzinfo=UTC)
    for i in range(400):
        name = f"graadmeter-{start + timedelta(days=i):%Y%m%dT%H%M%SZ}.dump"
        (tmp_path / name).write_bytes(b"x")
        (tmp_path / (name + ".sha256")).write_text("x")
    removed = prune(tmp_path, keep_daily=14, keep_monthly=12)
    kept = dumps(tmp_path)
    assert len(kept) == 400 - removed
    assert kept[-14:] == sorted(kept)[-14:] and len(kept) <= 14 + 12
    months = {p.name[11:17] for p in kept}
    assert len(months) >= 12
    assert len(list(tmp_path.glob("*.sha256"))) == len(kept)


def test_secrets_are_masked():
    s = mask("GET https://api.stlouisfed.org/fred/series?api_key=221abc&file_type=json failed; token=xyz")
    assert "221abc" not in s and "xyz" not in s and "api_key=***" in s


def test_when_to_notify(ops):
    assert should_notify(ops, "failed", None)
    assert not should_notify(ops, "ok", None)
    assert not should_notify(ops, "partial", {"error_count": 2})
    assert should_notify(ops, "partial", {"error_count": 5})
    subject, body = job_message("stocks", "Aandelen", "failed", {"errors": ["a"], "error_count": 1},
                                "Traceback\nValueError: boom")
    assert "mislukt" in subject and "ValueError: boom" in body


def test_send_logs_every_attempt(db, ops):  # noqa: F811
    engine, sf = db
    sent = []
    with sf() as session:
        n = send(session, ops, "Test", "body with api_key=secret", "test",
                 senders={"webhook": lambda s, b: sent.append((s, b))})
    assert n == 1 and "secret" not in sent[0][1] and sent[0][0].startswith("[Graadmeter]")

    def broken(s, b):
        raise ConnectionError("down")

    with sf() as session:
        assert send(session, ops, "Test", "b", "test", senders={"webhook": broken}) == 0
    assert scalar(engine, "SELECT count(*) FROM notification") == 2
    assert scalar(engine, "SELECT count(*) FROM notification WHERE NOT ok AND error LIKE '%down%'") == 1


def test_a_failed_scheduled_run_is_reported(db, ops, monkeypatch):  # noqa: F811
    from app import jobs as jobs_module
    from app.jobs import JobContext, run_job

    engine, sf = db
    sent = []
    monkeypatch.setattr("app.ops.notify._webhook", lambda url, s, b: sent.append(s))

    def boom(ctx):
        raise RuntimeError("bron onbereikbaar")

    monkeypatch.setitem(jobs_module.JOBS, "boom", boom)
    ctx = JobContext(engine, sf, None, None, None, ops=ops)
    run = run_job(ctx, "boom", trigger="schedule")
    assert run.status == "failed" and run.summary["resources"]["seconds"] >= 0
    assert len(sent) == 1 and "boom" in sent[0]
    run_job(ctx, "boom", trigger="manual")                              # a manual run is not reported
    assert len(sent) == 1


def test_watchdog_reports_a_job_that_did_not_run_once_a_day(db, ops, monkeypatch):  # noqa: F811
    engine, sf = db
    sent = []
    monkeypatch.setattr("app.ops.notify._webhook", lambda url, s, b: sent.append(s))
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO job_run (job, trigger, status, started_at, finished_at) VALUES "
                          "('crypto', 'schedule', 'ok', :old, :old), ('backup', 'schedule', 'ok', :new, :new)"),
                     {"old": now - timedelta(hours=40), "new": now - timedelta(hours=3)})
    with sf() as session:
        r = run_watchdog(session, ops, {"crypto", "backup"}, {"crypto": "Crypto"}, now)
        again = run_watchdog(session, ops, {"crypto", "backup"}, {"crypto": "Crypto"}, now + timedelta(hours=1))
    assert r.counts == {"overdue": 1, "notified": 1} and again.counts == {"overdue": 1}
    assert sent == ["[Graadmeter] Crypto: niet gedraaid"]


def test_resource_meter_measures_time_and_memory():
    with ResourceMeter(interval=0.01) as m:
        data = bytearray(30_000_000)
        sum(range(200_000))
    del data
    assert m.result["seconds"] >= 0 and m.result["peak_rss_mb"] >= m.result["start_rss_mb"]


@pytest.mark.skipif(shutil.which("pg_dump") is None, reason="pg_dump not installed")
def test_backup_and_restore_give_the_same_grades(db, stock_world, ops, test_database_url):  # noqa: F811
    """The acceptance test in small: back up, restore into an empty database, recompute every grade."""
    from app.grading.stocks import grade_stocks
    from app.ingest.stocks import run_stocks
    from app.modelconfig import load_model_config
    from app.registry import register_model_version
    from app.settings import REPO_ROOT

    engine, sf = db
    cfg, providers, stocks, universes = stock_world
    model = load_model_config(REPO_ROOT / "config" / "model")
    run_stocks(sf, providers, cfg, stocks, universes, model, today=TODAY)
    with sf() as session:
        vid = register_model_version(session, model).id
    grade_stocks(sf, model, vid, stocks, scalar(engine, "SELECT max(ts) FROM price_bar"))
    graded = scalar(engine, "SELECT count(*) FROM grade_snapshot")
    assert graded > 0

    path, rep = backup(test_database_url, ops.backup_dir, 14, 12)
    assert path.exists() and Path(str(path).replace(".dump", ".dump.sha256")).exists()
    result = restore_test(test_database_url, ops.backup_dir, "graadmeter_restoretest_ci")
    assert result.errors == [], result.errors
    assert result.counts == {"snapshots_restored": graded, "snapshots_recomputed": graded, "snapshots_exact": graded}
    # The temporary database is gone again.
    assert scalar(engine, "SELECT count(*) FROM pg_database WHERE datname = 'graadmeter_restoretest_ci'") == 0
    # A damaged dump is refused.
    path.write_bytes(path.read_bytes()[:-10] + b"0123456789")
    with pytest.raises(RuntimeError, match="beschadigd"):
        restore_test(test_database_url, ops.backup_dir, "graadmeter_restoretest_ci")
    assert isinstance(rep, Report) and date.today()
