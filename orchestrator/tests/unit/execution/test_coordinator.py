"""Unit tests for execution coordinator."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.execution.models import (
    ExecutionConfig,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    TargetInfo,
)
from app.execution.coordinator import (
    BatchProgress,
    BatchRequest,
    BatchResult,
    ExecutionCoordinator,
    RetryCoordinator,
)


class TestBatchRequest:
    """Tests for BatchRequest dataclass."""

    def test_create_request(self):
        """Test creating batch request."""
        targets = [
            TargetInfo(
                target_id=1,
                hostname="server-1",
                ip_address="192.168.1.101",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            ),
            TargetInfo(
                target_id=2,
                hostname="server-2",
                ip_address="192.168.1.102",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            ),
        ]

        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
        )

        assert request.test_run_id == 1
        assert request.baseline_id == 100
        assert len(request.targets) == 2
        assert request.load_profile == "medium"
        assert isinstance(request.config, ExecutionConfig)


class TestBatchProgress:
    """Tests for BatchProgress dataclass."""

    def test_create_progress(self):
        """Test creating batch progress."""
        progress = BatchProgress(
            test_run_id=1,
            total_targets=10,
            completed_targets=5,
            failed_targets=1,
            in_progress_targets=2,
            pending_targets=2,
            overall_progress_percent=50.0,
            executions=[],
        )

        assert progress.total_targets == 10
        assert progress.completed_targets == 5
        assert progress.failed_targets == 1
        assert progress.in_progress_targets == 2
        assert progress.pending_targets == 2
        assert progress.overall_progress_percent == 50.0


class TestBatchResult:
    """Tests for BatchResult dataclass."""

    def test_create_result(self):
        """Test creating batch result."""
        now = datetime.utcnow()
        result = BatchResult(
            test_run_id=1,
            baseline_id=100,
            load_profile="high",
            started_at=now,
            completed_at=now,
            total_duration_sec=600.0,
            total_targets=10,
            successful_targets=8,
            failed_targets=2,
            cancelled_targets=0,
            results=[],
        )

        assert result.test_run_id == 1
        assert result.total_targets == 10
        assert result.successful_targets == 8
        assert result.failed_targets == 2


class TestExecutionCoordinator:
    """Tests for ExecutionCoordinator."""

    @pytest.fixture
    def coordinator(self):
        """Create coordinator instance."""
        return ExecutionCoordinator()

    @pytest.fixture
    def targets(self):
        """Create test targets."""
        return [
            TargetInfo(
                target_id=1,
                hostname="server-1",
                ip_address="192.168.1.101",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            ),
            TargetInfo(
                target_id=2,
                hostname="server-2",
                ip_address="192.168.1.102",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            ),
        ]

    def test_init(self, coordinator):
        """Test coordinator initialization."""
        assert coordinator.active_executions == set()

    def test_get_execution_state_not_found(self, coordinator):
        """Test getting state of non-existent execution."""
        state = coordinator.get_execution_state("non-existent")
        assert state is None

    def test_get_execution_result_not_found(self, coordinator):
        """Test getting result of non-existent execution."""
        result = coordinator.get_execution_result("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_single(self, coordinator):
        """Test single target execution."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        target = TargetInfo(
            target_id=1,
            hostname="server-1",
            ip_address="192.168.1.101",
            os_type="linux",
            cpu_count=4,
            memory_gb=8.0,
        )

        request = ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=5,
                warmup_sec=1,
            ),
        )

        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        with patch(
            "app.execution.executor.CalibrationService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_service.validate_calibration = MagicMock(return_value=(True, "Valid"))
            mock_service_class.return_value = mock_service

            result = await coordinator.execute_single(request)

            assert result is not None
            assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_batch(self, coordinator, targets):
        """Test batch execution."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=5,
                warmup_sec=1,
                max_parallel_targets=2,
            ),
        )

        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        with patch(
            "app.execution.executor.CalibrationService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_service.validate_calibration = MagicMock(return_value=(True, "Valid"))
            mock_service_class.return_value = mock_service

            result = await coordinator.execute_batch(request)

            assert isinstance(result, BatchResult)
            assert result.total_targets == 2
            assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_execute_batch_concurrent_limit(self, coordinator):
        """Test batch respects concurrent execution limit."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        # Create many targets
        targets = [
            TargetInfo(
                target_id=i,
                hostname=f"server-{i}",
                ip_address=f"192.168.1.{100 + i}",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            )
            for i in range(5)
        ]

        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=5,
                warmup_sec=1,
                max_parallel_targets=2,  # Only 2 at a time
            ),
        )

        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        with patch(
            "app.execution.executor.CalibrationService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_service.validate_calibration = MagicMock(return_value=(True, "Valid"))
            mock_service_class.return_value = mock_service

            result = await coordinator.execute_batch(request)

            assert result.total_targets == 5
            assert len(result.results) == 5

    @pytest.mark.asyncio
    async def test_execute_batch_with_progress_callback(self, coordinator, targets):
        """Test batch execution with progress callback."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        progress_updates = []

        async def progress_callback(progress):
            progress_updates.append(progress)

        coordinator = ExecutionCoordinator(progress_callback=progress_callback)

        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=5,
                warmup_sec=1,
            ),
        )

        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        with patch(
            "app.execution.executor.CalibrationService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_service.validate_calibration = MagicMock(return_value=(True, "Valid"))
            mock_service_class.return_value = mock_service

            await coordinator.execute_batch(request)

            assert len(progress_updates) > 0

    @pytest.mark.asyncio
    async def test_cancel_batch(self, coordinator, targets):
        """Test batch cancellation."""
        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=60,  # Long duration
                warmup_sec=30,
            ),
        )

        # Start batch in background
        batch_task = asyncio.create_task(coordinator.execute_batch(request))

        # Wait a bit then cancel
        await asyncio.sleep(0.1)
        await coordinator.cancel_batch()

        # Wait for batch to complete
        result = await batch_task

        # Should have some cancelled results
        assert result is not None

    def test_get_batch_status_no_active(self, coordinator):
        """Test getting batch status when no batch is active."""
        status = coordinator.get_batch_status()
        assert status is None


class TestRetryCoordinator:
    """Tests for RetryCoordinator."""

    @pytest.fixture
    def coordinator(self):
        """Create execution coordinator."""
        return ExecutionCoordinator()

    @pytest.fixture
    def retry_coordinator(self, coordinator):
        """Create retry coordinator."""
        return RetryCoordinator(
            coordinator=coordinator,
            max_retries=3,
            base_delay_sec=1,
            max_delay_sec=10,
        )

    def test_get_retry_delay_exponential(self, retry_coordinator):
        """Test exponential backoff for retry delay."""
        delay0 = retry_coordinator.get_retry_delay(0)
        delay1 = retry_coordinator.get_retry_delay(1)
        delay2 = retry_coordinator.get_retry_delay(2)

        assert delay0 == 1  # base_delay * 2^0
        assert delay1 == 2  # base_delay * 2^1
        assert delay2 == 4  # base_delay * 2^2

    def test_get_retry_delay_max_cap(self, retry_coordinator):
        """Test retry delay is capped at max."""
        delay = retry_coordinator.get_retry_delay(10)  # Would be 1024 without cap

        assert delay == 10  # Capped at max_delay_sec

    def test_should_retry_under_limit(self, retry_coordinator):
        """Test should_retry when under limit."""
        assert retry_coordinator.should_retry(1) is True

    def test_should_retry_at_limit(self, retry_coordinator):
        """Test should_retry when at limit."""
        retry_coordinator._retry_counts[1] = 3

        assert retry_coordinator.should_retry(1) is False

    def test_record_retry(self, retry_coordinator):
        """Test recording retry attempts."""
        count1 = retry_coordinator.record_retry(1)
        count2 = retry_coordinator.record_retry(1)
        count3 = retry_coordinator.record_retry(1)

        assert count1 == 1
        assert count2 == 2
        assert count3 == 3

    def test_reset_retries(self, retry_coordinator):
        """Test resetting retry count."""
        retry_coordinator.record_retry(1)
        retry_coordinator.record_retry(1)

        retry_coordinator.reset_retries(1)

        assert retry_coordinator.should_retry(1) is True
        assert retry_coordinator._retry_counts.get(1) is None

    @pytest.mark.asyncio
    async def test_retry_failed_empty(self, retry_coordinator):
        """Test retry with no failed results."""
        batch_result = BatchResult(
            test_run_id=1,
            baseline_id=100,
            load_profile="medium",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            total_duration_sec=60.0,
            total_targets=2,
            successful_targets=2,
            failed_targets=0,
            cancelled_targets=0,
            results=[],
        )

        retry_results = await retry_coordinator.retry_failed(batch_result)

        assert retry_results == []

    @pytest.mark.asyncio
    async def test_retry_failed_exceeded_max(self, retry_coordinator):
        """Test retry when max retries exceeded."""
        from app.execution.models import ExecutionPhase

        # Set up target as already at max retries
        retry_coordinator._retry_counts[1] = 3

        failed_result = ExecutionResult(
            execution_id="exec-1",
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            status=ExecutionStatus.FAILED,
            load_profile="medium",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            total_duration_sec=60.0,
            thread_count=0,
            target_cpu_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Failed",
        )

        batch_result = BatchResult(
            test_run_id=1,
            baseline_id=100,
            load_profile="medium",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            total_duration_sec=60.0,
            total_targets=1,
            successful_targets=0,
            failed_targets=1,
            cancelled_targets=0,
            results=[failed_result],
        )

        retry_results = await retry_coordinator.retry_failed(batch_result)

        assert retry_results == []


class TestCoordinatorConcurrency:
    """Tests for coordinator concurrency handling."""

    @pytest.mark.asyncio
    async def test_prevent_concurrent_batches(self):
        """Test that concurrent batches are prevented."""
        coordinator = ExecutionCoordinator()

        targets = [
            TargetInfo(
                target_id=1,
                hostname="server-1",
                ip_address="192.168.1.101",
                os_type="linux",
                cpu_count=4,
                memory_gb=8.0,
            ),
        ]

        request = BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=ExecutionConfig(
                test_duration_sec=60,
                warmup_sec=30,
            ),
        )

        # Manually set active batch
        coordinator._active_batch = 1

        with pytest.raises(RuntimeError, match="already running"):
            await coordinator.execute_batch(request)

    @pytest.mark.asyncio
    async def test_cancel_execution(self):
        """Test cancelling specific execution."""
        coordinator = ExecutionCoordinator()

        # Try to cancel non-existent execution
        result = await coordinator.cancel_execution("non-existent")

        assert result is False
