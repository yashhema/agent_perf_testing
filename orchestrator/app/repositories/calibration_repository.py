"""Repository for CalibrationResult entity."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import CalibrationResult, IterationTimingStats
from app.models.enums import LoadProfile, CalibrationStatus
from app.models.orm import CalibrationResultORM


class CalibrationRepository:
    """Repository for CalibrationResult CRUD operations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _orm_to_model(self, orm: CalibrationResultORM) -> CalibrationResult:
        """Convert CalibrationResultORM to CalibrationResult application model."""
        # Build iteration timing stats if all fields present
        iteration_timing: Optional[IterationTimingStats] = None
        if (
            orm.avg_iteration_time_ms is not None
            and orm.stddev_iteration_time_ms is not None
            and orm.min_iteration_time_ms is not None
            and orm.max_iteration_time_ms is not None
            and orm.iteration_sample_count is not None
        ):
            iteration_timing = IterationTimingStats(
                avg_iteration_time_ms=orm.avg_iteration_time_ms,
                stddev_iteration_time_ms=orm.stddev_iteration_time_ms,
                min_iteration_time_ms=orm.min_iteration_time_ms,
                max_iteration_time_ms=orm.max_iteration_time_ms,
                iteration_sample_count=orm.iteration_sample_count,
            )

        return CalibrationResult(
            id=orm.id,
            target_id=orm.target_id,
            baseline_id=orm.baseline_id,
            loadprofile=LoadProfile(orm.loadprofile),
            thread_count=orm.thread_count,
            cpu_count=orm.cpu_count,
            memory_gb=orm.memory_gb,
            cpu_target_percent=orm.cpu_target_percent,
            achieved_cpu_percent=orm.achieved_cpu_percent,
            iteration_timing=iteration_timing,
            calibration_run_id=orm.calibration_run_id,
            calibration_status=CalibrationStatus(orm.calibration_status),
            calibrated_at=orm.calibrated_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        target_id: int,
        baseline_id: int,
        loadprofile: LoadProfile,
        thread_count: int,
        cpu_count: int,
        memory_gb: Decimal,
        cpu_target_percent: Optional[Decimal] = None,
        achieved_cpu_percent: Optional[Decimal] = None,
        iteration_timing: Optional[IterationTimingStats] = None,
        calibration_run_id: Optional[UUID] = None,
        calibration_status: CalibrationStatus = CalibrationStatus.PENDING,
    ) -> CalibrationResult:
        """Create a new calibration result."""
        orm = CalibrationResultORM(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=loadprofile.value,
            thread_count=thread_count,
            cpu_count=cpu_count,
            memory_gb=memory_gb,
            cpu_target_percent=cpu_target_percent,
            achieved_cpu_percent=achieved_cpu_percent,
            calibration_run_id=calibration_run_id,
            calibration_status=calibration_status.value,
        )

        # Set iteration timing if provided
        if iteration_timing is not None:
            orm.avg_iteration_time_ms = iteration_timing.avg_iteration_time_ms
            orm.stddev_iteration_time_ms = iteration_timing.stddev_iteration_time_ms
            orm.min_iteration_time_ms = iteration_timing.min_iteration_time_ms
            orm.max_iteration_time_ms = iteration_timing.max_iteration_time_ms
            orm.iteration_sample_count = iteration_timing.iteration_sample_count

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_id(self, calibration_id: int) -> Optional[CalibrationResult]:
        """Get calibration result by ID."""
        stmt = select(CalibrationResultORM).where(
            CalibrationResultORM.id == calibration_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_for_target(
        self,
        target_id: int,
        baseline_id: int,
        loadprofile: LoadProfile,
    ) -> Optional[CalibrationResult]:
        """Get calibration result for a specific target/baseline/loadprofile combo."""
        stmt = select(CalibrationResultORM).where(
            and_(
                CalibrationResultORM.target_id == target_id,
                CalibrationResultORM.baseline_id == baseline_id,
                CalibrationResultORM.loadprofile == loadprofile.value,
            )
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_by_target_id(self, target_id: int) -> list[CalibrationResult]:
        """Get all calibration results for a target."""
        stmt = (
            select(CalibrationResultORM)
            .where(CalibrationResultORM.target_id == target_id)
            .order_by(
                CalibrationResultORM.baseline_id,
                CalibrationResultORM.loadprofile,
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_baseline_id(self, baseline_id: int) -> list[CalibrationResult]:
        """Get all calibration results for a baseline."""
        stmt = (
            select(CalibrationResultORM)
            .where(CalibrationResultORM.baseline_id == baseline_id)
            .order_by(
                CalibrationResultORM.target_id,
                CalibrationResultORM.loadprofile,
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_status(
        self,
        status: CalibrationStatus,
    ) -> list[CalibrationResult]:
        """Get all calibration results with a specific status."""
        stmt = (
            select(CalibrationResultORM)
            .where(CalibrationResultORM.calibration_status == status.value)
            .order_by(CalibrationResultORM.created_at)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_pending_for_targets(
        self,
        target_ids: list[int],
    ) -> list[CalibrationResult]:
        """Get pending calibration results for multiple targets."""
        stmt = (
            select(CalibrationResultORM)
            .where(
                and_(
                    CalibrationResultORM.target_id.in_(target_ids),
                    CalibrationResultORM.calibration_status
                    == CalibrationStatus.PENDING.value,
                )
            )
            .order_by(
                CalibrationResultORM.target_id,
                CalibrationResultORM.loadprofile,
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def update_calibration(
        self,
        calibration_id: int,
        thread_count: Optional[int] = None,
        cpu_target_percent: Optional[Decimal] = None,
        achieved_cpu_percent: Optional[Decimal] = None,
        iteration_timing: Optional[IterationTimingStats] = None,
        calibration_run_id: Optional[UUID] = None,
        calibration_status: Optional[CalibrationStatus] = None,
    ) -> Optional[CalibrationResult]:
        """Update calibration result."""
        stmt = select(CalibrationResultORM).where(
            CalibrationResultORM.id == calibration_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if thread_count is not None:
            orm.thread_count = thread_count
        if cpu_target_percent is not None:
            orm.cpu_target_percent = cpu_target_percent
        if achieved_cpu_percent is not None:
            orm.achieved_cpu_percent = achieved_cpu_percent
        if calibration_run_id is not None:
            orm.calibration_run_id = calibration_run_id
        if calibration_status is not None:
            orm.calibration_status = calibration_status.value
            if calibration_status == CalibrationStatus.COMPLETED:
                orm.calibrated_at = datetime.utcnow()

        # Update iteration timing if provided
        if iteration_timing is not None:
            orm.avg_iteration_time_ms = iteration_timing.avg_iteration_time_ms
            orm.stddev_iteration_time_ms = iteration_timing.stddev_iteration_time_ms
            orm.min_iteration_time_ms = iteration_timing.min_iteration_time_ms
            orm.max_iteration_time_ms = iteration_timing.max_iteration_time_ms
            orm.iteration_sample_count = iteration_timing.iteration_sample_count

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def mark_completed(
        self,
        calibration_id: int,
        thread_count: int,
        achieved_cpu_percent: Decimal,
        iteration_timing: Optional[IterationTimingStats] = None,
    ) -> Optional[CalibrationResult]:
        """Mark calibration as completed with results."""
        return await self.update_calibration(
            calibration_id=calibration_id,
            thread_count=thread_count,
            achieved_cpu_percent=achieved_cpu_percent,
            iteration_timing=iteration_timing,
            calibration_status=CalibrationStatus.COMPLETED,
        )

    async def mark_failed(
        self,
        calibration_id: int,
    ) -> Optional[CalibrationResult]:
        """Mark calibration as failed."""
        return await self.update_calibration(
            calibration_id=calibration_id,
            calibration_status=CalibrationStatus.FAILED,
        )

    async def delete_by_id(self, calibration_id: int) -> bool:
        """Delete calibration result by ID. Returns True if deleted."""
        stmt = select(CalibrationResultORM).where(
            CalibrationResultORM.id == calibration_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return False

        await self._session.delete(orm)
        await self._session.flush()
        return True

    async def delete_by_target_id(self, target_id: int) -> int:
        """Delete all calibration results for a target. Returns count deleted."""
        stmt = select(CalibrationResultORM).where(
            CalibrationResultORM.target_id == target_id
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        count = len(orms)
        for orm in orms:
            await self._session.delete(orm)

        await self._session.flush()
        return count

    async def upsert(
        self,
        target_id: int,
        baseline_id: int,
        loadprofile: LoadProfile,
        thread_count: int,
        cpu_count: int,
        memory_gb: Decimal,
        cpu_target_percent: Optional[Decimal] = None,
        achieved_cpu_percent: Optional[Decimal] = None,
        iteration_timing: Optional[IterationTimingStats] = None,
        calibration_run_id: Optional[UUID] = None,
        calibration_status: CalibrationStatus = CalibrationStatus.PENDING,
    ) -> CalibrationResult:
        """Create or update a calibration result."""
        existing = await self.get_for_target(target_id, baseline_id, loadprofile)

        if existing is None:
            return await self.create(
                target_id=target_id,
                baseline_id=baseline_id,
                loadprofile=loadprofile,
                thread_count=thread_count,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
                cpu_target_percent=cpu_target_percent,
                achieved_cpu_percent=achieved_cpu_percent,
                iteration_timing=iteration_timing,
                calibration_run_id=calibration_run_id,
                calibration_status=calibration_status,
            )

        # Update existing record
        stmt = select(CalibrationResultORM).where(
            CalibrationResultORM.id == existing.id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one()

        orm.thread_count = thread_count
        orm.cpu_count = cpu_count
        orm.memory_gb = memory_gb
        orm.cpu_target_percent = cpu_target_percent
        orm.achieved_cpu_percent = achieved_cpu_percent
        orm.calibration_run_id = calibration_run_id
        orm.calibration_status = calibration_status.value

        if calibration_status == CalibrationStatus.COMPLETED:
            orm.calibrated_at = datetime.utcnow()

        if iteration_timing is not None:
            orm.avg_iteration_time_ms = iteration_timing.avg_iteration_time_ms
            orm.stddev_iteration_time_ms = iteration_timing.stddev_iteration_time_ms
            orm.min_iteration_time_ms = iteration_timing.min_iteration_time_ms
            orm.max_iteration_time_ms = iteration_timing.max_iteration_time_ms
            orm.iteration_sample_count = iteration_timing.iteration_sample_count

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)
