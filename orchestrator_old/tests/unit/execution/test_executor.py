"""Unit tests for test executor."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.execution.models import (
    ExecutionConfig,
    ExecutionPhase,
    ExecutionRequest,
    ExecutionStatus,
    TargetInfo,
)
from app.execution.executor import (
    ExecutorError,
    PhaseExecutor,
    TestExecutor,
)
from app.execution.state_machine import ExecutionStateMachine


class TestPhaseExecutor:
    """Tests for PhaseExecutor."""

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
            vm_name="vm-test",
            vcenter_host="vcenter.example.com",
            snapshot_name="baseline",
        )

    @pytest.fixture
    def config(self):
        """Create execution config."""
        return ExecutionConfig(
            test_duration_sec=60,
            warmup_sec=10,
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
    async def test_execute_vm_preparation_no_vcenter(self, config):
        """Test VM preparation when no vCenter config."""
        from app.execution.models import ExecutionState

        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=1,
            baseline_id=100,
        )
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        executor = PhaseExecutor(sm, config)

        success = await executor.execute_vm_preparation(
            vm_name=None,
            vcenter_host=None,
            snapshot_name=None,
        )

        assert success is True
        assert len(sm.state.phase_results) == 1
        assert sm.state.phase_results[0].phase == ExecutionPhase.VM_PREPARATION

    @pytest.mark.asyncio
    async def test_execute_vm_preparation_with_vcenter(self, config):
        """Test VM preparation with vCenter config."""
        from app.execution.models import ExecutionState

        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=1,
            baseline_id=100,
        )
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        events = []

        async def event_callback(event):
            events.append(event)

        executor = PhaseExecutor(sm, config, event_callback)

        success = await executor.execute_vm_preparation(
            vm_name="vm-test",
            vcenter_host="vcenter.example.com",
            snapshot_name="baseline",
        )

        assert success is True
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_execute_emulator_deployment_success(self, config):
        """Test successful emulator deployment."""
        from app.execution.models import ExecutionState

        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=1,
            baseline_id=100,
        )
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        executor = PhaseExecutor(sm, config)

        deployment = await executor.execute_emulator_deployment(
            target_host="192.168.1.100",
            target_port=8080,
            os_type="linux",
        )

        assert deployment is not None
        assert deployment.host == "192.168.1.100"
        assert deployment.port == 8080
        assert sm.state.emulator_deployment is not None

    @pytest.mark.asyncio
    async def test_execute_calibration_success(self, config):
        """Test successful calibration."""
        from app.execution.models import ExecutionState
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=1,
            baseline_id=100,
        )
        sm = ExecutionStateMachine(state)
        # Go through proper status transitions to reach DEPLOYING
        sm.transition_to(ExecutionStatus.INITIALIZING)
        sm.transition_to(ExecutionStatus.DEPLOYING, ExecutionPhase.EMULATOR_DEPLOYMENT)

        executor = PhaseExecutor(sm, config)

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

            result = await executor.execute_calibration(
                emulator_host="192.168.1.100",
                emulator_port=8080,
                load_profile="medium",
                cpu_count=8,
                memory_gb=16.0,
            )

            assert result is not None
            thread_count, achieved_cpu = result
            assert thread_count == 15
            assert achieved_cpu == 49.5
            assert sm.state.calibration_thread_count == 15


class TestTestExecutor:
    """Tests for TestExecutor."""

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
            test_duration_sec=10,
            warmup_sec=2,
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

    def test_init(self, exec_request):
        """Test executor initialization."""
        executor = TestExecutor(exec_request)

        assert executor.execution_id is not None
        assert executor.state is not None
        assert executor.state.status == ExecutionStatus.PENDING

    def test_execution_id_unique(self, exec_request):
        """Test execution IDs are unique."""
        executor1 = TestExecutor(exec_request)
        executor2 = TestExecutor(exec_request)

        assert executor1.execution_id != executor2.execution_id

    @pytest.mark.asyncio
    async def test_execute_success(self, exec_request):
        """Test successful execution."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        executor = TestExecutor(exec_request)

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

            result = await executor.execute()

            assert result.status == ExecutionStatus.COMPLETED
            assert result.thread_count == 15
            assert result.metrics is not None

    @pytest.mark.asyncio
    async def test_execute_with_progress_callback(self, exec_request):
        """Test execution with progress callback."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        progress_updates = []

        async def progress_callback(progress):
            progress_updates.append(progress)

        executor = TestExecutor(exec_request, progress_callback=progress_callback)

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

            await executor.execute()

            assert len(progress_updates) > 0

    @pytest.mark.asyncio
    async def test_execute_with_event_callback(self, exec_request):
        """Test execution with event callback."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

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

            await executor.execute()

            assert len(events) > 0

    @pytest.mark.asyncio
    async def test_cancel(self, exec_request):
        """Test execution cancellation."""
        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

        await executor.cancel()

        assert executor.state.status == ExecutionStatus.CANCELLED
        assert len(events) > 0
        assert any(e.event_type == "execution_cancelled" for e in events)


class TestExecutorFailureHandling:
    """Tests for executor failure handling."""

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
            test_duration_sec=10,
            warmup_sec=2,
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
    async def test_execute_calibration_failure(self, exec_request):
        """Test execution with calibration failure."""
        from app.calibration.models import CalibrationResult, CalibrationStatus, LoadProfile

        executor = TestExecutor(exec_request)

        mock_result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.FAILED,
            thread_count=0,
            cpu_target_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Emulator not reachable",
        )

        with patch(
            "app.execution.executor.CalibrationService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.calibrate_target = AsyncMock(return_value=mock_result)
            mock_service_class.return_value = mock_service

            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_execute_exception_handling(self, exec_request):
        """Test execution handles unexpected exceptions."""
        executor = TestExecutor(exec_request)

        with patch(
            "app.execution.executor.PhaseExecutor.execute_vm_preparation",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected error"),
        ):
            result = await executor.execute()

            assert result.status == ExecutionStatus.FAILED
            assert "Unexpected error" in result.error_message
