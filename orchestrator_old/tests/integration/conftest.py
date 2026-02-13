"""Pytest configuration for integration tests."""

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


# Database URL configuration for integration tests
# Default: SQLite for fast tests
# Set TEST_DB_TYPE=mssql for SQL Server testing
# Set TEST_DB_TYPE=postgres for PostgreSQL testing
TEST_DB_TYPE = os.environ.get("TEST_DB_TYPE", "sqlite")

if TEST_DB_TYPE == "mssql":
    # SQL Server with trusted connection (Windows Authentication)
    # Requires: pip install aioodbc
    # MARS=yes enables Multiple Active Result Sets for concurrent queries
    TEST_DATABASE_URL = (
        "mssql+aioodbc://localhost/apt_test_db"
        "?driver=ODBC+Driver+17+for+SQL+Server"
        "&Trusted_Connection=yes"
        "&MARS_Connection=yes"
    )
elif TEST_DB_TYPE == "postgres":
    # PostgreSQL for integration tests
    # Requires: pip install asyncpg
    TEST_DATABASE_URL = "postgresql+asyncpg://apt:apt_password@localhost:5432/apt_test_db"
else:
    # SQLite in-memory for fast tests (default)
    # Requires: pip install aiosqlite
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
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        yield session
        await session.rollback()
