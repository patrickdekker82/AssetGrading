import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.api.data import router as data_router
from app.api.routes import router
from app.db import get_engine
from app.glossary import load_glossary
from app.jobs import JobContext, fail_orphaned_runs, schedule_jobs
from app.modelconfig import load_model_config
from app.providers.config import load_providers_config
from app.providers.recorder import DbRecorder
from app.providers.registry import Providers
from app.registry import register_model_version
from app.scheduler import create_scheduler
from app.settings import get_settings
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
        register_model_version(session, config)
    fail_orphaned_runs(engine, sf)
    log.info("model version %s (%s) active", config.version, config.config_hash[:12])

    providers = Providers(providers_config, DbRecorder(sf))
    app.state.jobs = JobContext(engine, sf, providers, providers_config, app.state.universes)

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
app.include_router(router)
app.include_router(data_router)
