"""Main FastAPI application for load generator service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import health, jmeter, results


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    print("Load Generator Service starting...")
    yield
    print("Load Generator Service shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Performance Testing Load Generator",
        description="Load generator service managing JMeter processes",
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
    app.include_router(jmeter.router, prefix="/api/v1", tags=["JMeter"])
    app.include_router(results.router, prefix="/api/v1", tags=["Results"])

    return app


app = create_app()
