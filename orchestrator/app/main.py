"""FastAPI application for Agent Performance Testing Orchestrator."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import health, labs, servers, baselines, test_runs, executions
from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print("Orchestrator Service starting...")
    yield
    # Shutdown
    print("Orchestrator Service shutting down...")
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Performance Testing Orchestrator",
        description="Orchestrator service for managing agent performance tests",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(labs.router, prefix="/api/v1", tags=["Labs"])
    app.include_router(servers.router, prefix="/api/v1", tags=["Servers"])
    app.include_router(baselines.router, prefix="/api/v1", tags=["Baselines"])
    app.include_router(test_runs.router, prefix="/api/v1", tags=["Test Runs"])
    app.include_router(executions.router, prefix="/api/v1", tags=["Executions"])

    return app


app = create_app()
