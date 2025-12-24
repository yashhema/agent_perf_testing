"""Dependency injection for FastAPI."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.repositories import (
    LabRepository,
    ServerRepository,
    BaselineRepository,
    TestRunRepository,
    TestRunTargetRepository,
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
    CalibrationRepository,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_lab_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[LabRepository, None]:
    """Get LabRepository instance."""
    async for sess in get_session():
        yield LabRepository(sess)


async def get_server_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[ServerRepository, None]:
    """Get ServerRepository instance."""
    async for sess in get_session():
        yield ServerRepository(sess)


async def get_baseline_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[BaselineRepository, None]:
    """Get BaselineRepository instance."""
    async for sess in get_session():
        yield BaselineRepository(sess)


async def get_test_run_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[TestRunRepository, None]:
    """Get TestRunRepository instance."""
    async for sess in get_session():
        yield TestRunRepository(sess)


async def get_test_run_target_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[TestRunTargetRepository, None]:
    """Get TestRunTargetRepository instance."""
    async for sess in get_session():
        yield TestRunTargetRepository(sess)


async def get_execution_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[TestRunExecutionRepository, None]:
    """Get TestRunExecutionRepository instance."""
    async for sess in get_session():
        yield TestRunExecutionRepository(sess)


async def get_workflow_state_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[ExecutionWorkflowStateRepository, None]:
    """Get ExecutionWorkflowStateRepository instance."""
    async for sess in get_session():
        yield ExecutionWorkflowStateRepository(sess)


async def get_calibration_repository(
    session: AsyncSession = None,
) -> AsyncGenerator[CalibrationRepository, None]:
    """Get CalibrationRepository instance."""
    async for sess in get_session():
        yield CalibrationRepository(sess)
