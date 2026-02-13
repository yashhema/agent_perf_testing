"""Unit tests for CalibrationRepository."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import BaselineConfig, IterationTimingStats
from app.models.enums import (
    LoadProfile,
    CalibrationStatus,
    BaselineType,
    OSFamily,
    ServerRole,
)
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository
from app.repositories.baseline_repository import BaselineRepository
from app.repositories.calibration_repository import CalibrationRepository


class TestCalibrationRepository:
    """Tests for CalibrationRepository CRUD operations."""

    @pytest.fixture
    async def lab_id(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> int:
        """Create a lab and return its ID."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)
        return lab.id

    @pytest.fixture
    async def target_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> int:
        """Create a target server and return its ID."""
        repo = ServerRepository(session)
        server = await repo.create(
            hostname="target-01",
            ip_address="192.168.1.100",
            os_family=OSFamily.WINDOWS,
            server_type=ServerRole.APP_SERVER,
            lab_id=lab_id,
        )
        return server.id

    @pytest.fixture
    async def baseline_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> int:
        """Create a baseline and return its ID."""
        repo = BaselineRepository(session)
        baseline = await repo.create(
            name="Test Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=BaselineConfig(
                vcenter_host="vcenter.example.com",
                datacenter="DC1",
                snapshot_name="clean",
            ),
            lab_id=lab_id,
        )
        return baseline.id

    @pytest.mark.asyncio
    async def test_create_calibration(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test creating a calibration result."""
        repo = CalibrationRepository(session)

        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
            cpu_target_percent=Decimal("70.00"),
        )

        assert calibration.id is not None
        assert calibration.target_id == target_id
        assert calibration.baseline_id == baseline_id
        assert calibration.loadprofile == LoadProfile.MEDIUM
        assert calibration.thread_count == 10
        assert calibration.cpu_count == 4
        assert calibration.memory_gb == Decimal("8.00")
        assert calibration.cpu_target_percent == Decimal("70.00")
        assert calibration.calibration_status == CalibrationStatus.PENDING
        assert calibration.iteration_timing is None

    @pytest.mark.asyncio
    async def test_create_calibration_with_timing(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test creating a calibration result with iteration timing."""
        repo = CalibrationRepository(session)
        timing = IterationTimingStats(
            avg_iteration_time_ms=100,
            stddev_iteration_time_ms=10,
            min_iteration_time_ms=80,
            max_iteration_time_ms=150,
            iteration_sample_count=1000,
        )

        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.HIGH,
            thread_count=20,
            cpu_count=8,
            memory_gb=Decimal("16.00"),
            iteration_timing=timing,
        )

        assert calibration.iteration_timing is not None
        assert calibration.iteration_timing.avg_iteration_time_ms == 100
        assert calibration.iteration_timing.stddev_iteration_time_ms == 10
        assert calibration.iteration_timing.iteration_sample_count == 1000

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting an existing calibration by ID."""
        repo = CalibrationRepository(session)
        created = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=2,
            memory_gb=Decimal("4.00"),
        )

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent calibration by ID."""
        repo = CalibrationRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_for_target(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting calibration for specific target/baseline/loadprofile."""
        repo = CalibrationRepository(session)
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.get_for_target(target_id, baseline_id, LoadProfile.MEDIUM)

        assert result is not None
        assert result.target_id == target_id
        assert result.baseline_id == baseline_id
        assert result.loadprofile == LoadProfile.MEDIUM

    @pytest.mark.asyncio
    async def test_get_for_target_not_found(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting non-existent calibration."""
        repo = CalibrationRepository(session)

        result = await repo.get_for_target(target_id, baseline_id, LoadProfile.HIGH)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_target_id(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting all calibrations for a target."""
        repo = CalibrationRepository(session)

        # Create calibrations for different load profiles
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.HIGH,
            thread_count=20,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.get_by_target_id(target_id)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_by_baseline_id(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting all calibrations for a baseline."""
        repo = CalibrationRepository(session)

        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.get_by_baseline_id(baseline_id)

        assert len(result) == 1
        assert result[0].baseline_id == baseline_id

    @pytest.mark.asyncio
    async def test_get_by_status(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test getting calibrations by status."""
        repo = CalibrationRepository(session)

        pending = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
            calibration_status=CalibrationStatus.PENDING,
        )
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
            calibration_status=CalibrationStatus.COMPLETED,
        )

        result = await repo.get_by_status(CalibrationStatus.PENDING)

        assert len(result) == 1
        assert result[0].id == pending.id

    @pytest.mark.asyncio
    async def test_get_pending_for_targets(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
        lab_id: int,
    ) -> None:
        """Test getting pending calibrations for multiple targets."""
        repo = CalibrationRepository(session)
        server_repo = ServerRepository(session)

        # Create another target
        target2 = await server_repo.create(
            hostname="target-02",
            ip_address="192.168.1.101",
            os_family=OSFamily.WINDOWS,
            server_type=ServerRole.APP_SERVER,
            lab_id=lab_id,
        )

        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
            calibration_status=CalibrationStatus.PENDING,
        )
        await repo.create(
            target_id=target2.id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
            calibration_status=CalibrationStatus.PENDING,
        )

        result = await repo.get_pending_for_targets([target_id, target2.id])

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_calibration(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test updating calibration result."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.update_calibration(
            calibration.id,
            thread_count=15,
            achieved_cpu_percent=Decimal("72.50"),
        )

        assert result is not None
        assert result.thread_count == 15
        assert result.achieved_cpu_percent == Decimal("72.50")

    @pytest.mark.asyncio
    async def test_update_calibration_with_timing(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test updating calibration with iteration timing."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.HIGH,
            thread_count=20,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        timing = IterationTimingStats(
            avg_iteration_time_ms=150,
            stddev_iteration_time_ms=15,
            min_iteration_time_ms=120,
            max_iteration_time_ms=200,
            iteration_sample_count=500,
        )

        result = await repo.update_calibration(
            calibration.id,
            iteration_timing=timing,
        )

        assert result is not None
        assert result.iteration_timing is not None
        assert result.iteration_timing.avg_iteration_time_ms == 150

    @pytest.mark.asyncio
    async def test_mark_completed(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test marking calibration as completed."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.mark_completed(
            calibration.id,
            thread_count=12,
            achieved_cpu_percent=Decimal("71.00"),
        )

        assert result is not None
        assert result.calibration_status == CalibrationStatus.COMPLETED
        assert result.thread_count == 12
        assert result.achieved_cpu_percent == Decimal("71.00")
        assert result.calibrated_at is not None

    @pytest.mark.asyncio
    async def test_mark_failed(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test marking calibration as failed."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.mark_failed(calibration.id)

        assert result is not None
        assert result.calibration_status == CalibrationStatus.FAILED

    @pytest.mark.asyncio
    async def test_delete_by_id(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test deleting a calibration by ID."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        result = await repo.delete_by_id(calibration.id)

        assert result is True
        assert await repo.get_by_id(calibration.id) is None

    @pytest.mark.asyncio
    async def test_delete_by_target_id(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test deleting all calibrations for a target."""
        repo = CalibrationRepository(session)

        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.LOW,
            thread_count=5,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        count = await repo.delete_by_target_id(target_id)

        assert count == 2
        assert await repo.get_by_target_id(target_id) == []

    @pytest.mark.asyncio
    async def test_upsert_create(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test upsert creates new record when none exists."""
        repo = CalibrationRepository(session)

        result = await repo.upsert(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        assert result.id is not None
        assert result.thread_count == 10

    @pytest.mark.asyncio
    async def test_upsert_update(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test upsert updates existing record."""
        repo = CalibrationRepository(session)

        # Create initial record
        await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        # Upsert should update
        result = await repo.upsert(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=15,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        assert result.thread_count == 15

        # Should still be only one record
        all_results = await repo.get_by_target_id(target_id)
        assert len(all_results) == 1

    @pytest.mark.asyncio
    async def test_calibration_model_is_frozen(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test that CalibrationResult model is immutable."""
        repo = CalibrationRepository(session)
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.MEDIUM,
            thread_count=10,
            cpu_count=4,
            memory_gb=Decimal("8.00"),
        )

        with pytest.raises(AttributeError):
            calibration.thread_count = 99  # type: ignore

    @pytest.mark.asyncio
    async def test_iteration_timing_model_is_frozen(
        self,
        session: AsyncSession,
        target_id: int,
        baseline_id: int,
    ) -> None:
        """Test that IterationTimingStats model is immutable."""
        repo = CalibrationRepository(session)
        timing = IterationTimingStats(
            avg_iteration_time_ms=100,
            stddev_iteration_time_ms=10,
            min_iteration_time_ms=80,
            max_iteration_time_ms=150,
            iteration_sample_count=1000,
        )
        calibration = await repo.create(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=LoadProfile.HIGH,
            thread_count=20,
            cpu_count=8,
            memory_gb=Decimal("16.00"),
            iteration_timing=timing,
        )

        with pytest.raises(AttributeError):
            calibration.iteration_timing.avg_iteration_time_ms = 999  # type: ignore
