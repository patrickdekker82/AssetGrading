"""Maintenance commands.

    python -m app.cli check-config        validate configuration
    python -m app.cli lock-model          register a new model version
    python -m app.cli run <job>           run a job now (crypto, stocks, markets, commodities, fx_macro,
                                          prune_raw)
    python -m app.cli grade [YYYY-MM-DD] [crypto|stocks|markets|commodities]
                                          grade a day (default: yesterday, both classes)
    python -m app.cli regime              store the market regime for every day not stored yet
    python -m app.cli verify [N]          recompute the latest N snapshots (default: all) and compare
    python -m app.cli set-fact <asset> <field> <value>
                                          enter a fact no free source provides, e.g. unlock_90d 0.04,
                                          flag_unresolved_exploit 1 or, for a stock whose share count SEC
                                          does not give, shares_outstanding 1950000000 (source 'manual')
    python -m app.cli explain <asset>     write the explanation of one asset now (direct call, needs
                                          ANTHROPIC_API_KEY); the nightly job uses the batch API
    python -m app.cli check-explanations  check every stored explanation against its input again
    python -m app.cli backtest [YYYY-MM] [YYYY-MM] [classes]
                                          point-in-time backtest (default: config/evaluation.yaml),
                                          classes comma-separated: crypto,stocks,markets,commodities
    python -m app.cli backtest resume <run>
                                          continue a backtest that stopped
    python -m app.cli evaluate            monthly measurement on live grades now
    python -m app.cli proposals           list model proposals
    python -m app.cli apply-proposal <id> write an approved proposal into a new model version
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
            from app.ai import load_ai_config

            load_ai_config(settings.config_dir / "ai.yaml")
            print(f"OK: model {config.version}, {len(config.templates)} templates, hash {config.config_hash[:12]}")
        elif command == "lock-model":
            config = load_model_config(model_dir, check_lock=False)
            write_lock(config, model_dir)
            print(f"Locked model {config.version} -> {config.config_hash[:12]}")
        elif command == "run":
            return _run_job(argv[1] if len(argv) > 1 else "")
        elif command == "grade":
            return _grade(argv[1] if len(argv) > 1 else None, argv[2] if len(argv) > 2 else None)
        elif command == "regime":
            return _regime()
        elif command == "verify":
            return _verify(int(argv[1]) if len(argv) > 1 else None)
        elif command == "set-fact":
            return _set_fact(*argv[1:4])
        elif command == "explain":
            return _explain(argv[1] if len(argv) > 1 else "")
        elif command == "check-explanations":
            return _check_explanations()
        elif command == "backtest":
            return _backtest(*argv[1:4])
        elif command == "evaluate":
            return _run_job("evaluation")
        elif command == "proposals":
            return _proposals()
        elif command == "apply-proposal":
            return _apply_proposal(int(argv[1]))
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
    from app.commodities_config import load_commodities_config
    from app.markets_config import load_markets_config
    from app.stocks_config import load_stocks_config

    stocks = load_stocks_config(settings.config_dir / "stocks.yaml")
    from app.ai import load_ai_config, make_client
    from app.evaluation.outcomes import EvaluationSettings

    ai = load_ai_config(settings.config_dir / "ai.yaml")
    labels = {k: v.label for k, v in load_glossary(settings.config_dir / "glossary.nl.yaml").metrics.items()}
    ctx = JobContext(engine, sf, Providers(cfg, DbRecorder(sf)), cfg, universes, model, version_id, stocks=stocks,
                     markets=load_markets_config(settings.config_dir),
                     commodities=load_commodities_config(settings.config_dir),
                     ai=ai, labels=labels, llm_client=make_client(ai),
                     evaluation=EvaluationSettings.load(settings.config_dir / "evaluation.yaml"))
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


def _grade(day: str | None, asset_class: str | None) -> int:
    import json
    from datetime import UTC, date, datetime, timedelta

    from app.grading.crypto import grade_crypto
    from app.grading.stocks import grade_stocks
    from app.providers.config import load_providers_config
    from app.stocks_config import load_stocks_config

    settings, sf, config, version_id = _context()
    cfg = load_providers_config(settings.config_dir / "providers.yaml")
    as_of = date.fromisoformat(day) if day else datetime.now(UTC).date() - timedelta(days=1)
    if asset_class in (None, "crypto"):
        report = grade_crypto(sf, config, version_id, as_of, date.fromisoformat(cfg.crypto.history_start))
        print(json.dumps({"crypto": report.as_dict()}, indent=2))
    if asset_class in (None, "stocks"):
        stocks = load_stocks_config(settings.config_dir / "stocks.yaml")
        report = grade_stocks(sf, config, version_id, stocks, as_of)
        print(json.dumps({"stocks": report.as_dict()}, indent=2))
    if asset_class in (None, "markets"):
        from app.grading.markets import grade_markets
        from app.markets_config import load_markets_config

        report = grade_markets(sf, config, version_id, load_markets_config(settings.config_dir), as_of)
        print(json.dumps({"markets": report.as_dict()}, indent=2))
    if asset_class in (None, "commodities"):
        from app.commodities_config import load_commodities_config
        from app.grading.commodities import grade_commodities

        report = grade_commodities(sf, config, version_id, load_commodities_config(settings.config_dir), as_of)
        print(json.dumps({"commodities": report.as_dict()}, indent=2))
    return 0


def _regime() -> int:
    import json
    from datetime import UTC, datetime

    from app.grading.regime import update_regime
    from app.ingest.report import Report
    from app.jobs import REGIME_START

    _, sf, config, version_id = _context()
    report = Report()
    update_regime(sf, config, version_id, datetime.now(UTC).date(), REGIME_START, report)
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
    """`coingecko_id` is the asset key as in the URL (CoinGecko id for crypto, e.g. 'v' or 'abn-as' for stocks)."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.ingest.store import insert_facts
    from app.models import Asset
    from app.providers import Fact

    _, sf, _, _ = _context()
    now = datetime.now(UTC)
    with sf() as session:
        asset = session.scalar(select(Asset).where(Asset.slug == coingecko_id))
        if asset is None:
            print(f"onbekende asset: {coingecko_id}", file=sys.stderr)
            return 1
        unit = "flag" if field.startswith("flag_") else "manual"
        fact = Fact(field, (now - timedelta(days=1)).date(), Decimal(value), unit)
        insert_facts(session, asset.id, "manual", [fact], now)
        session.commit()
    print(f"{coingecko_id}: {field} = {value} (handmatig, bekend vanaf {now:%Y-%m-%d %H:%M} UTC)")
    return 0



def _explainer():
    from app.ai import load_ai_config, make_client
    from app.ai.explanation import Explainer

    settings, sf, config, version_id = _context()
    ai = load_ai_config(settings.config_dir / "ai.yaml")
    labels = {k: v.label for k, v in load_glossary(settings.config_dir / "glossary.nl.yaml").metrics.items()}
    return Explainer(sf, ai, config, version_id, labels, make_client(ai))


def _explain(slug: str) -> int:
    import json

    from sqlalchemy import text

    explainer = _explainer()
    with explainer.sf() as session:
        asset_id = session.execute(text("SELECT id FROM asset WHERE slug = :s"), {"s": slug}).scalar()
    if asset_id is None:
        print(f"unknown asset: {slug}", file=sys.stderr)
        return 2
    report = explainer.explain_now(asset_id)
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 1 if report.errors else 0


def _check_explanations() -> int:
    """Every stored text, model or template, against the input rebuilt from its snapshot."""
    from sqlalchemy import text

    from app.ai.explanation import snapshot_on
    from app.ai.numbers import check_text

    explainer = _explainer()
    checked = failed = 0
    with explainer.sf() as session:
        rows = session.execute(text(
            "SELECT asset_id, model_version_id, snapshot_as_of, source, text FROM explanation ORDER BY id")).all()
        for row in rows:
            snap = snapshot_on(session, row.model_version_id, row.asset_id, row.snapshot_as_of)
            problems = check_text(row.text, explainer.payload(snap))
            checked += 1
            if problems:
                failed += 1
                print(f"{snap.name} ({row.source}, {row.snapshot_as_of}): {'; '.join(problems)}")
    print(f"{checked} toelichtingen gecontroleerd, {failed} met een getal of grade buiten de invoer")
    return 1 if failed else 0


def _backtest(start: str | None = None, end: str | None = None, classes: str | None = None) -> int:
    import json
    import logging
    from datetime import UTC, date, datetime

    from app.commodities_config import load_commodities_config
    from app.evaluation.backtest import Backtest
    from app.evaluation.outcomes import EvaluationSettings, month_end
    from app.markets_config import load_markets_config
    from app.providers.config import load_providers_config
    from app.stocks_config import load_stocks_config

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings, sf, config, version_id = _context()
    ev = EvaluationSettings.load(settings.config_dir / "evaluation.yaml")
    cfg = load_providers_config(settings.config_dir / "providers.yaml")
    resume = start == "resume"
    first = date.fromisoformat((ev.raw["backtest"]["start"] if resume or not start else start) + "-01")
    last = month_end(date.fromisoformat(end + "-01")) if end and not resume else datetime.now(UTC).date()
    bt = Backtest(sf, config, version_id, ev, date.fromisoformat(cfg.crypto.history_start),
                  load_stocks_config(settings.config_dir / "stocks.yaml"), load_markets_config(settings.config_dir),
                  load_commodities_config(settings.config_dir))
    if start == "resume":
        run_id = int(end)
        report = bt.resume(run_id)
    else:
        run_id, report = bt.run(first, last, classes.split(",") if classes else list(ev.raw["backtest"]["classes"]))
    print(json.dumps({"run": run_id, **report.as_dict()}, indent=2, ensure_ascii=False)[:5000])
    return 0


def _proposals() -> int:
    from sqlalchemy import text

    _, sf, _, _ = _context()
    with sf() as session:
        rows = session.execute(text("SELECT id, kind, status, created_at, summary_nl FROM model_proposal ORDER BY id"))
        for r in rows:
            print(f"{r.id}  {r.kind}  {r.status}  {r.created_at:%Y-%m-%d}  {r.summary_nl}")
    return 0


def _apply_proposal(proposal_id: int) -> int:
    from app.evaluation.proposals import apply_proposal

    settings, sf, config, _ = _context()
    try:
        version = apply_proposal(sf, settings.config_dir / "model", config, proposal_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Modelversie {version} vastgelegd. Herstart de server om hem te gebruiken.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
