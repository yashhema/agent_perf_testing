"""Pytest configuration and fixtures for orchestrator tests."""

import asyncio
from typing import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)

from app.models.orm import Base
from app.models.enums import (
    OSFamily,
    ServerType,
    BaselineType,
    LoadProfile,
    RunMode,
    ExecutionStatus,
    CalibrationStatus,
    ExecutionPhase,
    PhaseState,
)


# Use in-memory SQLite for unit tests (fast, no external dependencies)
# For integration tests, use PostgreSQL via Docker
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


# ============================================================
# Sample data fixtures
# ============================================================


@pytest.fixture
def sample_lab_data() -> dict:
    """Sample data for creating a lab."""
    return {
        "name": "Test Lab",
        "lab_type": "server",
        "description": "A test laboratory",
    }


@pytest.fixture
def sample_server_data() -> dict:
    """Sample data for creating a server."""
    return {
        "hostname": "test-server-01",
        "ip_address": "192.168.1.100",
        "os_family": OSFamily.WINDOWS,
        "server_type": ServerType.APP_SERVER,
        "ssh_username": None,
        "ssh_key_path": None,
        "winrm_username": "admin",
        "emulator_port": 8080,
        "loadgen_service_port": 8090,
        "is_active": True,
    }


@pytest.fixture
def sample_loadgen_data() -> dict:
    """Sample data for creating a load generator server."""
    return {
        "hostname": "loadgen-01",
        "ip_address": "192.168.1.200",
        "os_family": OSFamily.LINUX,
        "server_type": ServerType.LOAD_GENERATOR,
        "ssh_username": "ubuntu",
        "ssh_key_path": "/path/to/key",
        "winrm_username": None,
        "emulator_port": 8080,
        "loadgen_service_port": 8090,
        "is_active": True,
    }


@pytest.fixture
def sample_baseline_data() -> dict:
    """Sample data for creating a baseline."""
    return {
        "name": "Windows Base",
        "description": "Base Windows snapshot",
        "baseline_type": BaselineType.VSPHERE,
    }


@pytest.fixture
def sample_baseline_config() -> dict:
    """Sample baseline config data."""
    return {
        "vcenter_host": "vcenter.example.com",
        "datacenter": "DC1",
        "snapshot_name": "clean-snapshot",
    }


@pytest.fixture
def sample_test_run_data() -> dict:
    """Sample data for creating a test run."""
    return {
        "name": "Performance Test Run 1",
        "description": "Initial performance test",
        "req_loadprofile": [LoadProfile.LOW, LoadProfile.MEDIUM, LoadProfile.HIGH],
        "warmup_sec": 300,
        "measured_sec": 3600,
        "analysis_trim_sec": 300,
        "repetitions": 3,
        "loadgenerator_package_grpid_lst": [1, 2, 3],
    }


@pytest.fixture
def sample_calibration_data() -> dict:
    """Sample data for creating a calibration result."""
    return {
        "loadprofile": LoadProfile.MEDIUM,
        "thread_count": 10,
        "cpu_count": 4,
        "memory_gb": Decimal("8.00"),
        "cpu_target_percent": Decimal("70.00"),
        "achieved_cpu_percent": None,
        "calibration_status": CalibrationStatus.PENDING,
    }


@pytest.fixture
def sample_execution_data() -> dict:
    """Sample data for creating a test run execution."""
    return {
        "run_mode": RunMode.CONTINUOUS,
    }


@pytest.fixture
def sample_workflow_state_data() -> dict:
    """Sample data for creating an execution workflow state."""
    return {
        "loadprofile": LoadProfile.LOW,
        "runcount": 1,
        "current_phase": ExecutionPhase.RESET,
        "phase_state": PhaseState.PENDING,
        "max_retries": 3,
    }
