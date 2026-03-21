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

# Suppress noisy library logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
# Suppress uvicorn access logs (GET /api/... every few seconds from UI polling)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Global app state — populated during lifespan
app_config: AppConfig = AppConfig()
credentials: CredentialsStore = CredentialsStore.__new__(CredentialsStore)


def _cleanup_orphaned_runs():
    """Mark any test runs left in active states as failed.

    When the orchestrator is restarted (crash, Ctrl+C, deploy), test runs
    that were mid-execution are left in active DB states with no process
    driving them. This detects and fails them on startup so the UI shows
    the correct state and the user can retry.
    """
    from orchestrator.models.database import SessionLocal
    from orchestrator.models.orm import BaselineTestRunORM, CalibrationResultORM
    from orchestrator.models.enums import BaselineTestState

    active_states = {
        BaselineTestState.validating,
        BaselineTestState.deploying_loadgen,
        BaselineTestState.deploying_calibration,
        BaselineTestState.calibrating,
        BaselineTestState.generating,
        BaselineTestState.deploying_testing,
        BaselineTestState.executing,
        BaselineTestState.storing,
        BaselineTestState.comparing,
    }

    session = SessionLocal()
    try:
        orphans = session.query(BaselineTestRunORM).filter(
            BaselineTestRunORM.state.in_(active_states),
        ).all()

        for run in orphans:
            logger.warning(
                "Orphaned test run #%d '%s' found in state '%s' — marking as failed",
                run.id, run.name, run.state.value,
            )
            run.failed_at_state = run.state.value
            run.state = BaselineTestState.failed
            run.error_message = (
                f"Orchestrator restarted while test was in '{run.failed_at_state}' state. "
                f"The test was interrupted and must be retried."
            )

            # Clean up in-progress calibration records
            stale_cals = session.query(CalibrationResultORM).filter(
                CalibrationResultORM.baseline_test_run_id == run.id,
                CalibrationResultORM.status == "in_progress",
            ).all()
            for cal in stale_cals:
                cal.status = "failed"
                cal.error_message = "Orchestrator restarted — calibration interrupted"

        if orphans:
            session.commit()
            logger.info("Cleaned up %d orphaned test run(s)", len(orphans))
        else:
            logger.info("No orphaned test runs found")
    except Exception as e:
        logger.error("Failed to clean up orphaned runs: %s", e)
        session.rollback()
    finally:
        session.close()


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

    # Detect orphaned test runs from previous orchestrator instance
    _cleanup_orphaned_runs()

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
