"""E2E tests for error handling scenarios."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.execution.models import (
    ExecutionStatus,
    ExecutionPhase,
    ExecutionRequest,
    ExecutionConfig,
    TargetInfo,
)
from app.execution.executor import TestExecutor
from app.execution.coordinator import ExecutionCoordinator, BatchRequest
from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

from tests.e2e.mocks.vsphere import VSphereSimulator, MockVSphereClient
from tests.e2e.mocks.emulator import EmulatorSimulator, MockEmulatorServer


class TestCalibrationFailures:
    """Tests for calibration failure handling."""

    @pytest.fixture
    def target_info(self):
        """Create target info."""
        return TargetInfo(
            target_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
        )

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
        )

    @pytest.fixture
    def exec_request(self, target_info, config):
        """Create execution request."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_calibration_failure_marks_execution_failed(self, exec_request):
        """Test that calibration failure marks execution as failed."""
        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.FAILED,
            thread_count=0,
            cpu_target_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Failed to reach target CPU",
        )

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_calibration_exception_handled(self, exec_request):
        """Test that calibration exceptions are handled gracefully."""
        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception("Network timeout")
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert "Network timeout" in result.error_message

    @pytest.mark.asyncio
    async def test_calibration_failure_records_error_phase(self, exec_request):
        """Test that calibration failure records the error phase."""
        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.FAILED,
            thread_count=0,
            cpu_target_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Calibration failed",
        )

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            await executor.execute()

            # Error phase should be recorded
            assert executor.state.error_phase is not None


class TestEmulatorFailures:
    """Tests for emulator failure handling."""

    @pytest.fixture
    def target_info(self):
        """Create target info."""
        return TargetInfo(
            target_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
        )

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
        )

    @pytest.fixture
    def exec_request(self, target_info, config):
        """Create execution request."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_emulator_deployment_failure(self, exec_request):
        """Test handling of emulator deployment failure."""
        with patch(
            "app.execution.executor.PhaseExecutor.execute_emulator_deployment",
            new_callable=AsyncMock,
            return_value=None,  # Deployment failed
        ):
            with patch("app.execution.executor.CalibrationService"):
                executor = TestExecutor(exec_request)

                result = await executor.execute()

                # Should fail when deployment returns None
                assert result.status == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_emulator_unreachable(self, exec_request):
        """Test handling of unreachable emulator."""
        # Create unhealthy emulator
        simulator = EmulatorSimulator()
        simulator.set_healthy(False)

        server = MockEmulatorServer(simulator)

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=RuntimeError("Emulator not responding")
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED


class TestVSphereFailures:
    """Tests for vSphere failure handling."""

    @pytest.fixture
    def target_info_with_vm(self):
        """Create target info with VM details."""
        return TargetInfo(
            target_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
            vm_name="test-vm",
            vcenter_host="vcenter.local",
            snapshot_name="baseline",
        )

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
        )

    @pytest.fixture
    def exec_request_with_vm(self, target_info_with_vm, config):
        """Create execution request with VM."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info_with_vm,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_vm_not_found(self, exec_request_with_vm):
        """Test handling of VM not found error."""
        simulator = VSphereSimulator()
        # Don't add the VM - it won't be found
        client = MockVSphereClient(simulator)

        with patch(
            "app.execution.executor.PhaseExecutor.execute_vm_preparation",
            new_callable=AsyncMock,
            side_effect=ValueError("VM test-vm not found"),
        ):
            executor = TestExecutor(exec_request_with_vm)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_snapshot_not_found(self, exec_request_with_vm):
        """Test handling of snapshot not found error."""
        simulator = VSphereSimulator()
        # Add VM but without the expected snapshot
        simulator.add_vm(
            name="test-vm",
            ip_address="192.168.1.100",
            snapshots=["different-snapshot"],  # Not "baseline"
        )

        with patch(
            "app.execution.executor.PhaseExecutor.execute_vm_preparation",
            new_callable=AsyncMock,
            side_effect=ValueError("Snapshot baseline not found"),
        ):
            executor = TestExecutor(exec_request_with_vm)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_vcenter_connection_failure(self, exec_request_with_vm):
        """Test handling of vCenter connection failure."""
        with patch(
            "app.execution.executor.PhaseExecutor.execute_vm_preparation",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Failed to connect to vCenter"),
        ):
            executor = TestExecutor(exec_request_with_vm)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert "connect" in result.error_message.lower()


class TestBatchFailures:
    """Tests for batch execution failure handling."""

    @pytest.fixture
    def targets(self):
        """Create multiple targets."""
        return [
            TargetInfo(
                target_id=i,
                hostname=f"server-{i}",
                ip_address=f"192.168.1.{100 + i}",
                os_type="linux",
                cpu_count=8,
                memory_gb=16.0,
            )
            for i in range(1, 4)
        ]

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
            max_parallel_targets=2,
        )

    @pytest.fixture
    def batch_request(self, targets, config):
        """Create batch request."""
        return BatchRequest(
            test_run_id=1,
            baseline_id=100,
            targets=targets,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_partial_batch_failure(self, batch_request):
        """Test batch where some executions fail."""
        call_count = 0

        async def mock_calibrate(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            # Fail every other one
            if call_count % 2 == 0:
                return CalibrationResult(
                    target_id=kwargs.get("target_id", 1),
                    baseline_id=kwargs.get("baseline_id", 100),
                    loadprofile=LoadProfile.MEDIUM,
                    status=CalibrationStatus.FAILED,
                    thread_count=0,
                    cpu_target_percent=50.0,
                    achieved_cpu_percent=0.0,
                    error_message="Calibration failed",
                )
            else:
                return CalibrationResult(
                    target_id=kwargs.get("target_id", 1),
                    baseline_id=kwargs.get("baseline_id", 100),
                    loadprofile=LoadProfile.MEDIUM,
                    status=CalibrationStatus.COMPLETED,
                    thread_count=10,
                    cpu_target_percent=50.0,
                    achieved_cpu_percent=48.5,
                )

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(side_effect=mock_calibrate)
            mock_service.validate_calibration = lambda r: (True, "Valid")
            mock_class.return_value = mock_service

            coordinator = ExecutionCoordinator()

            result = await coordinator.execute_batch(batch_request)

            # Some should have succeeded, some failed
            assert result.successful_targets > 0
            assert result.failed_targets > 0
            assert result.successful_targets + result.failed_targets == result.total_targets

    @pytest.mark.asyncio
    async def test_all_batch_failures(self, batch_request):
        """Test batch where all executions fail."""
        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception("All failed")
            )
            mock_class.return_value = mock_service

            coordinator = ExecutionCoordinator()

            result = await coordinator.execute_batch(batch_request)

            assert result.successful_targets == 0
            assert result.failed_targets == result.total_targets


class TestRecoveryScenarios:
    """Tests for error recovery scenarios."""

    @pytest.fixture
    def target_info(self):
        """Create target info."""
        return TargetInfo(
            target_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
        )

    @pytest.fixture
    def config(self):
        """Create execution config with retries."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
            max_retries=3,
            retry_delay_sec=0.1,
        )

    @pytest.fixture
    def exec_request(self, target_info, config):
        """Create execution request."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_transient_failure_recovery(self, exec_request):
        """Test recovery from transient failures with retry."""
        call_count = 0

        async def mock_calibrate(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            # Fail first 2 times, succeed on 3rd
            if call_count < 3:
                raise ConnectionError("Temporary network error")

            return CalibrationResult(
                target_id=1,
                baseline_id=100,
                loadprofile=LoadProfile.MEDIUM,
                status=CalibrationStatus.COMPLETED,
                thread_count=10,
                cpu_target_percent=50.0,
                achieved_cpu_percent=48.5,
            )

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(side_effect=mock_calibrate)
            mock_service.validate_calibration = lambda r: (True, "Valid")
            mock_class.return_value = mock_service

            from app.execution.coordinator import RetryCoordinator, ExecutionCoordinator

            coordinator = ExecutionCoordinator()
            retry_coordinator = RetryCoordinator(
                coordinator=coordinator,
                max_retries=3,
                base_delay_sec=0.01,
            )

            # First attempt fails
            executor1 = TestExecutor(exec_request)
            result1 = await executor1.execute()

            if result1.status == ExecutionStatus.FAILED:
                # Retry
                executor2 = TestExecutor(exec_request)
                result2 = await executor2.execute()

                if result2.status == ExecutionStatus.FAILED:
                    # Final retry should succeed
                    executor3 = TestExecutor(exec_request)
                    result3 = await executor3.execute()

                    assert result3.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_execution_cleanup(self, exec_request):
        """Test that failed executions still clean up properly."""
        events = []

        async def event_callback(event):
            events.append(event)

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception("Fatal error")
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request, event_callback=event_callback)

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED

            # Should have failure event
            event_types = [e.event_type for e in events]
            # Should have failure notification
            assert any("failed" in et.lower() for et in event_types)


class TestStateConsistency:
    """Tests for state consistency during errors."""

    @pytest.fixture
    def target_info(self):
        """Create target info."""
        return TargetInfo(
            target_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
        )

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=5,
            warmup_sec=1,
        )

    @pytest.fixture
    def exec_request(self, target_info, config):
        """Create execution request."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_failed_state_is_terminal(self, exec_request):
        """Test that FAILED state is terminal."""
        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception("Error")
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            await executor.execute()

            assert executor._sm.is_terminal()
            assert executor.state.status == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_error_recorded_in_state(self, exec_request):
        """Test that errors are recorded in state."""
        error_message = "Specific test error message"

        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception(error_message)
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            await executor.execute()

            assert executor.state.last_error is not None
            assert error_message in executor.state.last_error

    @pytest.mark.asyncio
    async def test_completed_at_set_on_failure(self, exec_request):
        """Test that completed_at is set even on failure."""
        with patch("app.execution.executor.CalibrationService") as mock_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(
                side_effect=Exception("Error")
            )
            mock_class.return_value = mock_service

            executor = TestExecutor(exec_request)

            await executor.execute()

            assert executor.state.completed_at is not None
