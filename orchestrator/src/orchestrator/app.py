"""FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig, load_config
from orchestrator.models.database import init_db

# Configure root logger so all orchestrator.* module logs go to stderr (captured by uvicorn)
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

# Global app state — populated during lifespan
app_config: AppConfig = AppConfig()
credentials: CredentialsStore = CredentialsStore.__new__(CredentialsStore)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    global app_config, credentials

    config_path = "config/orchestrator.yaml"
    logger.info("Loading configuration from %s", config_path)
    app_config = load_config(config_path)

    logger.info("Initializing database: %s", app_config.database.url)
    init_db(app_config.database.url, echo=app_config.database.echo)

    logger.info("Loading credentials from %s", app_config.credentials_path)
    credentials = CredentialsStore(app_config.credentials_path)

    logger.info("Orchestrator startup complete")
    yield
    logger.info("Orchestrator shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Orchestrator",
        description="Agent Performance Testing Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount static files
    static_dir = Path(__file__).resolve().parent / "static"
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve package artifacts so remote targets can download via HTTP
    artifacts_dir = Path(__file__).resolve().parents[2] / "artifacts" / "packages"
    if artifacts_dir.exists():
        application.mount("/packages", StaticFiles(directory=str(artifacts_dir)), name="packages")
        logger.info("Serving packages from %s", artifacts_dir)

    # Serve prerequisite scripts so remote targets can download via HTTP
    prereq_dir = Path(__file__).resolve().parents[2] / "prerequisites"
    if prereq_dir.exists():
        application.mount("/prerequisites", StaticFiles(directory=str(prereq_dir)), name="prerequisites")
        logger.info("Serving prerequisites from %s", prereq_dir)

    # Register API routers
    from orchestrator.api.auth import router as auth_router
    from orchestrator.api.admin import router as admin_router
    from orchestrator.api.test_runs import router as test_runs_router
    from orchestrator.api.trending import router as trending_router
    from orchestrator.api.baseline_test_runs import router as baseline_router
    from orchestrator.api.baseline_test_runs import snapshot_router
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(test_runs_router)
    application.include_router(trending_router)
    application.include_router(baseline_router)
    application.include_router(snapshot_router)

    # Register web UI routes
    from orchestrator.web.views import router as web_router
    application.include_router(web_router)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    return application


app = create_app()
