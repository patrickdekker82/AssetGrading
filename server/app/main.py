import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import sessionmaker

from app.ai import load_ai_config, make_client
from app.api.assets import router as assets_router
from app.api.data import router as data_router
from app.api.grades import router as grades_router
from app.api.model import router as model_router
from app.api.routes import router
from app.commodities_config import load_commodities_config
from app.db import get_engine
from app.evaluation.outcomes import EvaluationSettings
from app.glossary import load_glossary
from app.jobs import JobContext, fail_orphaned_runs, schedule_jobs
from app.markets_config import load_markets_config
from app.modelconfig import load_model_config
from app.providers.config import load_providers_config
from app.providers.recorder import DbRecorder
from app.providers.registry import Providers
from app.registry import register_model_version
from app.scheduler import create_scheduler
from app.settings import get_settings
from app.stocks_config import load_stocks_config
from app.universes import load_universes

log = logging.getLogger("graadmeter")
# httpx logs full URLs at INFO; FRED puts its API key in the URL.
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Configuration errors stop start-up: grading on an unversioned model is not allowed.
    config = load_model_config(settings.config_dir / "model")
    app.state.model_config = config
    app.state.glossary = load_glossary(settings.config_dir / "glossary.nl.yaml")
    app.state.universes = load_universes(settings.config_dir / "universes.yaml")

    providers_config = load_providers_config(settings.config_dir / "providers.yaml")
    app.state.providers_config = providers_config

    engine = get_engine()
    sf = sessionmaker(bind=engine)
    with sf() as session:
        model_version_id = register_model_version(session, config).id
    fail_orphaned_runs(engine, sf)
    log.info("model version %s (%s) active", config.version, config.config_hash[:12])

    providers = Providers(providers_config, DbRecorder(sf))
    stocks = load_stocks_config(settings.config_dir / "stocks.yaml")
    markets = load_markets_config(settings.config_dir)
    ai = load_ai_config(settings.config_dir / "ai.yaml")
    app.state.ai_config = ai
    labels = {k: v.label for k, v in app.state.glossary.metrics.items()}
    app.state.jobs = JobContext(engine, sf, providers, providers_config, app.state.universes, config, model_version_id,
                                stocks=stocks, markets=markets,
                                commodities=load_commodities_config(settings.config_dir),
                                ai=ai, labels=labels, llm_client=make_client(ai),
                                evaluation=EvaluationSettings.load(settings.config_dir / "evaluation.yaml"))

    app.state.scheduler = None
    if settings.scheduler_enabled:
        app.state.scheduler = create_scheduler()
        schedule_jobs(app.state.scheduler, app.state.jobs)
        app.state.scheduler.start()
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Graadmeter", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(router)
app.include_router(data_router)
app.include_router(assets_router)
app.include_router(grades_router)
app.include_router(model_router)
