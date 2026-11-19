from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import health_router, jobs_router, leads_router
from app.config import Settings, get_settings
from app.db.repositories import JobRepository
from app.db.session import (
    create_db_engine,
    create_session_factory,
    init_db,
    session_scope,
)
from app.logging_config import configure_logging
from app.services.collector import CollectorService
from app.services.job_runner import Executor, JobRunner
from app.services.scheduler import build_scheduler
from app.sources import LeadSource, build_source

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    source_factory: Callable[[], LeadSource] | None = None,
    executor: Executor | None = None,
) -> FastAPI:
    """Application factory. The keyword arguments exist for dependency injection (tests, alt. sources)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if session_factory is None:
        engine = create_db_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    else:
        engine = session_factory.kw["bind"]
    source_factory = source_factory or (lambda: build_source(settings))
    runner = JobRunner(CollectorService(session_factory, source_factory), session_factory, executor=executor)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        with session_scope(session_factory) as s:
            stale = JobRepository(s).fail_stale()
        if stale:
            logger.warning("stale_jobs_marked_failed", extra={"count": stale})
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = build_scheduler(settings, runner)
            scheduler.start()
            logger.info("scheduler_started", extra={"cron": settings.scheduler_cron})
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)
            runner.shutdown()
            engine.dispose()

    app = FastAPI(
        title="LinkedIn Job Lead Collector",
        version="1.0.0",
        description="Collects publicly visible job-post contact details for a job seeker's own review. Never sends messages.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.runner = runner
    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(leads_router)
    return app


app = create_app()
