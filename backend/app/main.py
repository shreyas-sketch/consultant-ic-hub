"""The web application: one FastAPI app for the consultant app, client pages, admin and MCP.

Layering (each layer only imports the ones below it):

    api/routes   HTTP adapters: parse requests, call the domain, shape responses
    auth         login, OTP, sessions
    domain       business actions (one registry, four doors: screens, automations, agents, MCP)
    agents, automations
    integrations vendor adapters (WhatsApp, email, calendar, storage, AI), services (PDF, uploads)
    db, core     database access, tenant scoping, settings, events, limits, utils

Start:  uvicorn app.main:app      (web, RUN_JOBS=false)
        python -m app.workers     (worker, RUN_JOBS=true)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from app import __version__, domain
from app.api import errors
from app.api.middleware import RequestContextMiddleware
from app.core import settings
from app.core.logging import setup_logging

log = logging.getLogger("app")


async def startup():
    """Shared by web and worker: settings check, indexes, migrations, QA seed."""
    setup_logging()
    for p in settings.validate():
        log.warning("unsafe setting allowed by ALLOW_UNSAFE_CONFIG: %s", p)
    domain.load()
    from app.db import ensure_indexes
    from app.db.migrations import migrate
    if settings.ENSURE_INDEXES_ON_START or settings.QA_MODE:
        await ensure_indexes()
    await migrate()
    if settings.QA_MODE and settings._b("QA_SEED", "true"):
        from app.qa.seed import seed
        await seed()


def _init_sentry():
    if not settings.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT, release=__version__,
                        traces_sample_rate=0.05, send_default_pii=False)
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk isn't installed. Errors will only be logged.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    sched = None
    if settings.RUN_JOBS:
        from app.workers.jobs import start_scheduler
        sched = start_scheduler()
    log.info("web started", extra={"fields": {"version": __version__, "env": settings.ENVIRONMENT,
                                              "qa": settings.QA_MODE, "jobs": settings.RUN_JOBS}})
    yield
    if sched:
        sched.shutdown(wait=False)
    from app.db import close
    close()


def create_app() -> FastAPI:
    setup_logging()
    _init_sentry()
    domain.load()
    app = FastAPI(title=settings.BRAND_NAME, version=__version__, lifespan=lifespan,
                  docs_url="/api/docs" if settings.QA_MODE else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if settings.QA_MODE else None)

    # Outermost first: request id + access log wraps everything, gzip inside it.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestContextMiddleware, https=settings.APP_URL.startswith("https://"))
    errors.install(app)

    from app.api.routes import (actions, admin, auth, connections, files, frontend, mcp, oauth, public, system)
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(actions.router)
    app.include_router(files.router)
    app.include_router(connections.router)
    app.include_router(public.router)
    app.include_router(public.hooks)
    app.include_router(admin.router)
    app.include_router(mcp.router)
    app.include_router(oauth.router)
    if settings.QA_MODE:
        from app.api.routes import qa
        app.include_router(qa.router)
    app.include_router(frontend.router)   # catch-all: must stay last
    return app


app = create_app()
