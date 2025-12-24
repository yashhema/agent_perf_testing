"""Pytest configuration for Docker-based E2E tests.

Provides fixtures for:
- PostgreSQL database connection
- Test data seeding
- Docker container management
"""

import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)

from app.models.orm import Base
from tests.e2e.data import E2ETestDataSeeder, DockerE2EConfig


# E2E Docker database URL
E2E_DATABASE_URL = os.getenv(
    "E2E_DATABASE_URL",
    "postgresql+asyncpg://e2e_user:e2e_password@localhost:5434/agent_perf_e2e",
)

# Docker container addresses (when running outside Docker)
EMULATOR_1_HOST = os.getenv("EMULATOR_1_HOST", "localhost")
EMULATOR_1_PORT = int(os.getenv("EMULATOR_1_PORT", "8081"))
EMULATOR_2_HOST = os.getenv("EMULATOR_2_HOST", "localhost")
EMULATOR_2_PORT = int(os.getenv("EMULATOR_2_PORT", "8082"))
LOADGEN_HOST = os.getenv("LOADGEN_HOST", "localhost")
LOADGEN_PORT = int(os.getenv("LOADGEN_PORT", "8090"))

# Agent ports (running inside emulator containers)
AGENT_1_HOST = os.getenv("AGENT_1_HOST", "localhost")
AGENT_1_PORT = int(os.getenv("AGENT_1_PORT", "8085"))
AGENT_2_HOST = os.getenv("AGENT_2_HOST", "localhost")
AGENT_2_PORT = int(os.getenv("AGENT_2_PORT", "8086"))


def pytest_addoption(parser):
    """Add custom pytest options for E2E tests."""
    parser.addoption(
        "--e2e-docker",
        action="store_true",
        default=False,
        help="Run E2E tests with Docker containers",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "e2e_docker: mark test as E2E Docker test (requires Docker containers)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip E2E Docker tests if --e2e-docker not specified."""
    if config.getoption("--e2e-docker"):
        return

    skip_e2e = pytest.mark.skip(reason="need --e2e-docker option to run")
    for item in items:
        if "e2e_docker" in item.keywords:
            item.add_marker(skip_e2e)


@pytest_asyncio.fixture(scope="function")
async def e2e_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create E2E database engine connected to Docker PostgreSQL."""
    engine = create_async_engine(
        E2E_DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def e2e_session(
    e2e_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Create E2E database session."""
    async_session_maker = async_sessionmaker(
        e2e_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
def docker_e2e_config():
    """Create Docker E2E configuration with external ports."""
    from decimal import Decimal
    from dataclasses import dataclass, field
    from app.models.enums import ServerType, LoadProfile

    # Use external ports for accessing Docker containers
    return DockerE2EConfig(
        lab_name="docker-e2e-lab",
        cpu_count=4,
        memory_gb=Decimal("8.00"),
        emulator_containers=[
            {
                "hostname": "emulator-1",
                "container_name": "e2e-emulator-1",
                "ip_address": EMULATOR_1_HOST,
                "port": EMULATOR_1_PORT,
                "server_type": ServerType.APP_SERVER,
            },
            {
                "hostname": "emulator-2",
                "container_name": "e2e-emulator-2",
                "ip_address": EMULATOR_2_HOST,
                "port": EMULATOR_2_PORT,
                "server_type": ServerType.APP_SERVER,
            },
        ],
        loadgen_containers=[
            {
                "hostname": "loadgen-1",
                "container_name": "e2e-loadgen-1",
                "ip_address": LOADGEN_HOST,
                "port": LOADGEN_PORT,
                "server_type": ServerType.LOAD_GENERATOR,
            },
        ],
        calibration_thread_counts={
            LoadProfile.LOW: 4,
            LoadProfile.MEDIUM: 8,
            LoadProfile.HIGH: 12,
        },
    )


@pytest_asyncio.fixture
async def seeded_data(e2e_session: AsyncSession):
    """Seed database with E2E test data."""
    seeder = E2ETestDataSeeder(e2e_session)
    data = await seeder.seed_all()

    yield data

    # Cleanup
    await seeder.cleanup()


@pytest.fixture
def emulator_1_url():
    """Get URL for emulator 1 container."""
    return f"http://{EMULATOR_1_HOST}:{EMULATOR_1_PORT}"


@pytest.fixture
def emulator_2_url():
    """Get URL for emulator 2 container."""
    return f"http://{EMULATOR_2_HOST}:{EMULATOR_2_PORT}"


@pytest.fixture
def loadgen_url():
    """Get URL for load generator container."""
    return f"http://{LOADGEN_HOST}:{LOADGEN_PORT}"


@pytest.fixture
def agent_1_url():
    """Get URL for agent simulator on emulator 1."""
    return f"http://{AGENT_1_HOST}:{AGENT_1_PORT}"


@pytest.fixture
def agent_2_url():
    """Get URL for agent simulator on emulator 2."""
    return f"http://{AGENT_2_HOST}:{AGENT_2_PORT}"


@pytest_asyncio.fixture
async def db_session(e2e_session: AsyncSession):
    """Alias for e2e_session for cleaner test code."""
    yield e2e_session


@pytest.fixture
def docker_factory():
    """Create DockerE2EFactory for production managers."""
    from tests.e2e.docker.docker_adapters import (
        DockerE2EFactory,
        ContainerConfig,
    )

    return DockerE2EFactory(
        emulator_config=ContainerConfig(
            name="emulator-1",
            host=EMULATOR_1_HOST,
            http_port=EMULATOR_1_PORT,
            ssh_port=2222,  # SSH port mapping from docker-compose
        ),
        loadgen_config=ContainerConfig(
            name="loadgen",
            host=LOADGEN_HOST,
            http_port=LOADGEN_PORT,
            ssh_port=2223,  # SSH port mapping from docker-compose
        ),
        target_configs={
            1: ContainerConfig(
                name="emulator-1",
                host=EMULATOR_1_HOST,
                http_port=EMULATOR_1_PORT,
                ssh_port=2222,
            ),
            2: ContainerConfig(
                name="emulator-2",
                host=EMULATOR_2_HOST,
                http_port=EMULATOR_2_PORT,
                ssh_port=2224,
            ),
        },
    )
