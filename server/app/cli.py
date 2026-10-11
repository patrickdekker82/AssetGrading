"""Maintenance commands.

    python -m app.cli check-config        validate configuration
    python -m app.cli lock-model          register a new model version
    python -m app.cli run <job>           run a job now (crypto, fx_macro, prune_raw)
    python -m app.cli grade [YYYY-MM-DD]  grade crypto for a day (default: yesterday)
    python -m app.cli verify [N]          recompute the latest N snapshots (default: all) and compare
    python -m app.cli set-fact <coingecko_id> <field> <value>
                                          enter a fact no free source provides, e.g. unlock_90d 0.04 or
                                          flag_unresolved_exploit 1 (stored with source 'manual')
"""

import sys

from app.glossary import load_glossary
from app.modelconfig import ModelConfigError, load_model_config
from app.modelconfig.loader import write_lock
from app.settings import get_settings


def main(argv: list[str]) -> int:
    settings = get_settings()
    model_dir = settings.config_dir / "model"
    command = argv[0] if argv else "check-config"
    try:
        if command == "check-config":
            config = load_model_config(model_dir)
            load_glossary(settings.config_dir / "glossary.nl.yaml")
            print(f"OK: model {config.version}, {len(config.templates)} templates, hash {config.config_hash[:12]}")
        elif command == "lock-model":
            config = load_model_config(model_dir, check_lock=False)
            write_lock(config, model_dir)
            print(f"Locked model {config.version} -> {config.config_hash[:12]}")
        elif command == "run":
            return _run_job(argv[1] if len(argv) > 1 else "")
        elif command == "grade":
            return _grade(argv[1] if len(argv) > 1 else None)
        elif command == "verify":
            return _verify(int(argv[1]) if len(argv) > 1 else None)
        elif command == "set-fact":
            return _set_fact(*argv[1:4])
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except ModelConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_job(name: str) -> int:
    import json
    import logging

    from sqlalchemy.orm import sessionmaker

    from app.db import get_engine
    from app.jobs import JOBS, JobContext, run_job
    from app.providers.config import load_providers_config
    from app.providers.recorder import DbRecorder
    from app.providers.registry import Providers
    from app.universes import load_universes

    if name not in JOBS:
        print(f"choose a job: {', '.join(JOBS)}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO)
    # httpx logs full URLs at INFO; FRED puts its API key in the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    engine = get_engine()
    sf = sessionmaker(bind=engine)
    cfg = load_providers_config(settings.config_dir / "providers.yaml")
    universes = load_universes(settings.config_dir / "universes.yaml")
    model = load_model_config(settings.config_dir / "model")
    from app.registry import register_model_version

    with sf() as session:
        version_id = register_model_version(session, model).id
    ctx = JobContext(engine, sf, Providers(cfg, DbRecorder(sf)), cfg, universes, model, version_id)
    run = run_job(ctx, name, trigger="cli")
    print(json.dumps({"status": run.status, "summary": run.summary, "error": run.error}, indent=2, default=str))
    return 0 if run.status in ("ok", "partial", "skipped") else 1


def _context():
    from sqlalchemy.orm import sessionmaker

    from app.db import get_engine
    from app.registry import register_model_version

    settings = get_settings()
    engine = get_engine()
    sf = sessionmaker(bind=engine)
    config = load_model_config(settings.config_dir / "model")
    with sf() as session:
        version_id = register_model_version(session, config).id
    return settings, sf, config, version_id


def _grade(day: str | None) -> int:
    import json
    from datetime import UTC, date, datetime, timedelta

    from app.grading.crypto import grade_crypto
    from app.providers.config import load_providers_config

    settings, sf, config, version_id = _context()
    cfg = load_providers_config(settings.config_dir / "providers.yaml")
    as_of = date.fromisoformat(day) if day else datetime.now(UTC).date() - timedelta(days=1)
    report = grade_crypto(sf, config, version_id, as_of, date.fromisoformat(cfg.crypto.history_start))
    print(json.dumps(report.as_dict(), indent=2))
    return 0


def _verify(limit: int | None) -> int:
    from app.grading.recompute import verify_all

    _, sf, _, _ = _context()
    with sf() as session:
        checks = verify_all(session, limit)
    bad = [c for c in checks if not c.ok]
    print(f"{len(checks)} snapshots herberekend, {len(checks) - len(bad)} exact gelijk, {len(bad)} afwijkend")
    for c in bad[:20]:
        print(f"  snapshot {c.snapshot_id}: " + "; ".join(c.differences[:5]))
    return 1 if bad else 0


def _set_fact(coingecko_id: str, field: str, value: str) -> int:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.ingest.store import insert_facts
    from app.models import Asset
    from app.providers import Fact

    _, sf, _, _ = _context()
    now = datetime.now(UTC)
    with sf() as session:
        asset = session.scalar(select(Asset).where(Asset.coingecko_id == coingecko_id))
        if asset is None:
            print(f"onbekende asset: {coingecko_id}", file=sys.stderr)
            return 1
        unit = "flag" if field.startswith("flag_") else "manual"
        fact = Fact(field, (now - timedelta(days=1)).date(), Decimal(value), unit)
        insert_facts(session, asset.id, "manual", [fact], now)
        session.commit()
    print(f"{coingecko_id}: {field} = {value} (handmatig, bekend vanaf {now:%Y-%m-%d %H:%M} UTC)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
