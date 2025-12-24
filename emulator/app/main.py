"""Main FastAPI application for emulator service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import health, operations, tests, stats, agent
from .state import set_startup_time


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    set_startup_time()
    print("Emulator Service starting...")
    yield
    print("Emulator Service shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Performance Testing Emulator",
        description="Emulator service for generating system load (CPU, memory, disk, network)",
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
    app.include_router(operations.router, prefix="/api/v1", tags=["Operations"])
    app.include_router(tests.router, prefix="/api/v1", tags=["Tests"])
    app.include_router(stats.router, prefix="/api/v1", tags=["Stats"])
    app.include_router(agent.router, prefix="/api/v1", tags=["Agent"])

    return app


app = create_app()
