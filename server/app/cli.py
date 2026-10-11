"""Maintenance commands.

    python -m app.cli check-config        validate configuration
    python -m app.cli lock-model          register a new model version
    python -m app.cli run <job>           run a job now (crypto, fx_macro, prune_raw)
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
    ctx = JobContext(engine, sf, Providers(cfg, DbRecorder(sf)), cfg, universes)
    run = run_job(ctx, name, trigger="cli")
    print(json.dumps({"status": run.status, "summary": run.summary, "error": run.error}, indent=2, default=str))
    return 0 if run.status in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
