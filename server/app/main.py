import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.api.routes import router
from app.db import get_engine
from app.glossary import load_glossary
from app.modelconfig import load_model_config
from app.registry import register_model_version
from app.scheduler import create_scheduler
from app.settings import get_settings
from app.universes import load_universes

log = logging.getLogger("graadmeter")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Configuration errors stop start-up: grading on an unversioned model is not allowed.
    config = load_model_config(settings.config_dir / "model")
    app.state.model_config = config
    app.state.glossary = load_glossary(settings.config_dir / "glossary.nl.yaml")
    app.state.universes = load_universes(settings.config_dir / "universes.yaml")

    with sessionmaker(bind=get_engine())() as session:
        register_model_version(session, config)
    log.info("model version %s (%s) active", config.version, config.config_hash[:12])

    app.state.scheduler = None
    if settings.scheduler_enabled:
        app.state.scheduler = create_scheduler()
        app.state.scheduler.start()
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Graadmeter", lifespan=lifespan)
app.include_router(router)
