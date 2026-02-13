"""Main FastAPI application for emulator service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import health, operations, tests, stats, agent, config
from .state import set_startup_time
from .config import get_config
from .stats.collector import get_stats_collector


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    set_startup_time()

    # Configure stats collector from config
    emulator_config = get_config()
    collector = get_stats_collector()
    collector.configure(
        output_dir=emulator_config.stats.output_dir,
        max_samples=emulator_config.stats.max_memory_samples,
        default_interval_sec=emulator_config.stats.default_interval_sec,
    )

    print("Emulator Service starting...")
    yield

    # Stop any running stats collection on shutdown
    if collector._is_collecting:
        await collector.stop_collection()

    print("Emulator Service shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Performance Testing Emulator",
        description="Emulator service for generating system load (CPU, memory, disk, network, file operations)",
        version="1.1.0",
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
    app.include_router(config.router, prefix="/api/v1", tags=["Config"])
    app.include_router(operations.router, prefix="/api/v1", tags=["Operations"])
    app.include_router(tests.router, prefix="/api/v1", tags=["Tests"])
    app.include_router(stats.router, prefix="/api/v1", tags=["Stats"])
    app.include_router(agent.router, prefix="/api/v1", tags=["Agent"])

    return app


app = create_app()
