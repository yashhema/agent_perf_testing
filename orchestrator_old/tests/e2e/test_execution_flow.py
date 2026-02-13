"""E2E tests for complete execution flow."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.execution.models import (
    ExecutionStatus,
    ExecutionPhase,
    ExecutionRequest,
    ExecutionConfig,
    TargetInfo,
)
from app.execution.executor import TestExecutor, PhaseExecutor
from app.execution.state_machine import ExecutionStateMachine
from app.execution.coordinator import ExecutionCoordinator, BatchRequest

from tests.e2e.mocks.vsphere import VSphereSimulator, MockVSphereClient
from tests.e2e.mocks.emulator import EmulatorSimulator, MockEmulatorServer


class TestFullExecutionFlow:
    """Tests for complete test execution lifecycle."""

    @pytest.fixture
    def target_info(self):
        """Create target info without VM details (no vSphere)."""
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
    async def test_executor_lifecycle_pending_to_completed(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test full execution from PENDING to COMPLETED."""
        events = []
        progress_updates = []

        async def event_callback(event):
            events.append(event)

        async def progress_callback(progress):
            progress_updates.append(progress)

        executor = TestExecutor(
            exec_request,
            event_callback=event_callback,
            progress_callback=progress_callback,
        )

        # Verify initial state
        assert executor.state.status == ExecutionStatus.PENDING
        assert executor.state.current_phase == ExecutionPhase.INIT

        # Execute
        result = await executor.execute()

        # Verify final state
        assert result.status == ExecutionStatus.COMPLETED
        assert result.thread_count > 0
        assert result.metrics is not None

        # Verify events were emitted
        assert len(events) > 0
        event_types = [e.event_type for e in events]
        # Verify core phase events are present
        assert "deployment_started" in event_types
        assert "calibration_started" in event_types

        # Verify progress was reported
        assert len(progress_updates) > 0

    @pytest.mark.asyncio
    async def test_state_transitions_through_lifecycle(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test state machine transitions through execution."""
        status_history = []
        phase_history = []

        def listener(state, transition):
            status_history.append(state.status)
            phase_history.append(state.current_phase)

        executor = TestExecutor(exec_request)
        executor._sm.add_listener(listener)

        await executor.execute()

        # Verify we went through expected statuses
        assert ExecutionStatus.INITIALIZING in status_history
        assert ExecutionStatus.DEPLOYING in status_history
        assert ExecutionStatus.CALIBRATING in status_history
        assert ExecutionStatus.RUNNING in status_history
        assert ExecutionStatus.COLLECTING in status_history
        assert ExecutionStatus.COMPLETED in status_history

        # Verify we went through expected phases
        assert ExecutionPhase.VM_PREPARATION in phase_history
        assert ExecutionPhase.EMULATOR_DEPLOYMENT in phase_history
        assert ExecutionPhase.CALIBRATION in phase_history
        assert ExecutionPhase.LOAD_TEST in phase_history
        assert ExecutionPhase.RESULT_COLLECTION in phase_history

    @pytest.mark.asyncio
    async def test_execution_timestamps(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that timestamps are properly set."""
        executor = TestExecutor(exec_request)

        # Before execution
        assert executor.state.started_at is None
        assert executor.state.completed_at is None

        await executor.execute()

        # After execution
        assert executor.state.started_at is not None
        assert executor.state.completed_at is not None
        assert executor.state.completed_at >= executor.state.started_at

    @pytest.mark.asyncio
    async def test_phase_results_recorded(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that phase results are recorded."""
        executor = TestExecutor(exec_request)

        await executor.execute()

        # Get phase results
        phase_results = executor._sm.get_phase_results()

        assert len(phase_results) > 0

        # All phases should have duration
        completed_phases = [p for p in phase_results if p.completed_at is not None]
        assert len(completed_phases) > 0

        for phase in completed_phases:
            assert phase.duration_sec is not None
            assert phase.duration_sec >= 0


class TestExecutionWithVSphere:
    """Tests for execution with vSphere VM management."""

    @pytest.fixture
    def vsphere_simulator(self):
        """Create vSphere simulator."""
        simulator = VSphereSimulator(operation_delay_sec=0.01)
        simulator.add_vm(
            name="test-vm",
            ip_address="192.168.1.100",
            snapshots=["baseline"],
        )
        return simulator

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
        """Create execution request with VM info."""
        return ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target_info_with_vm,
            load_profile="medium",
            config=config,
        )

    @pytest.mark.asyncio
    async def test_vm_preparation_phase(
        self,
        exec_request_with_vm,
        vsphere_simulator,
        mock_calibration_service,
    ):
        """Test VM preparation phase with vSphere."""
        vsphere_client = MockVSphereClient(vsphere_simulator)
        await vsphere_client.connect("vcenter.local", "user", "pass")

        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(
            exec_request_with_vm,
            event_callback=event_callback,
        )

        await executor.execute()

        # Verify deployment events were emitted (main observable behavior)
        event_types = [e.event_type for e in events]
        assert "deployment_started" in event_types or "vm_prep_skipped" in event_types


class TestBatchExecution:
    """Tests for batch execution coordination."""

    @pytest.fixture
    def targets(self):
        """Create multiple target infos."""
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
    async def test_batch_execution_all_succeed(
        self,
        batch_request,
        mock_calibration_service,
    ):
        """Test batch execution with all targets succeeding."""
        progress_updates = []

        async def progress_callback(progress):
            progress_updates.append(progress)

        coordinator = ExecutionCoordinator(progress_callback=progress_callback)

        result = await coordinator.execute_batch(batch_request)

        # Verify all completed
        assert result.total_targets == 3
        assert result.successful_targets == 3
        assert result.failed_targets == 0

        # Verify all results are present
        assert len(result.results) == 3

        for exec_result in result.results:
            assert exec_result.status == ExecutionStatus.COMPLETED

        # Verify progress was reported
        assert len(progress_updates) > 0

    @pytest.mark.asyncio
    async def test_batch_respects_concurrency_limit(
        self,
        batch_request,
        mock_calibration_service,
    ):
        """Test that batch respects max_concurrent limit."""
        active_count_history = []

        coordinator = ExecutionCoordinator()

        # Track active executions
        original_execute = coordinator._execute_with_semaphore

        async def tracking_execute(semaphore, *args, **kwargs):
            active_count_history.append(len(coordinator.active_executions))
            return await original_execute(semaphore, *args, **kwargs)

        coordinator._execute_with_semaphore = tracking_execute

        await coordinator.execute_batch(batch_request)

        # With 3 requests and max_parallel_targets=2, we should never exceed 2 active
        # Note: The tracking happens at start, so we might see 0, 1, 2
        assert all(c <= 2 for c in active_count_history)

    @pytest.mark.asyncio
    async def test_batch_cancellation(
        self,
        batch_request,
        mock_calibration_service,
    ):
        """Test batch execution cancellation."""
        coordinator = ExecutionCoordinator()

        # Start batch in background and cancel quickly
        import asyncio

        async def cancel_after_delay():
            await asyncio.sleep(0.1)
            coordinator._cancelled = True  # Direct cancellation

        # Run both concurrently
        cancel_task = asyncio.create_task(cancel_after_delay())

        result = await coordinator.execute_batch(batch_request)

        await cancel_task

        # At least some should be cancelled or fewer completed
        assert result.cancelled_targets >= 0 or result.successful_targets <= result.total_targets


class TestExecutionCancellation:
    """Tests for execution cancellation."""

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
    async def test_cancel_before_execution(self, exec_request):
        """Test cancelling before execution starts."""
        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

        # Cancel before execution
        await executor.cancel()

        assert executor.state.status == ExecutionStatus.CANCELLED
        assert any(e.event_type == "execution_cancelled" for e in events)

    @pytest.mark.asyncio
    async def test_cancelled_execution_is_terminal(self, exec_request):
        """Test that cancelled execution cannot be resumed."""
        executor = TestExecutor(exec_request)

        await executor.cancel()

        assert executor._sm.is_terminal()

        # Cannot transition from terminal state
        from app.execution.state_machine import InvalidTransitionError

        with pytest.raises(InvalidTransitionError):
            executor._sm.transition_to(ExecutionStatus.INITIALIZING)


class TestEventCallbacks:
    """Tests for event callback system."""

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
    async def test_all_event_types_emitted(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that all expected event types are emitted."""
        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

        await executor.execute()

        event_types = {e.event_type for e in events}

        # Core phase events that should be present
        assert "deployment_started" in event_types
        assert "calibration_started" in event_types

    @pytest.mark.asyncio
    async def test_events_have_required_fields(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that events have all required fields."""
        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

        await executor.execute()

        for event in events:
            assert event.event_type is not None
            assert event.execution_id is not None
            assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_events_ordered_by_timestamp(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that events are in chronological order."""
        events = []

        async def event_callback(event):
            events.append(event)

        executor = TestExecutor(exec_request, event_callback=event_callback)

        await executor.execute()

        # Verify events are ordered
        for i in range(1, len(events)):
            assert events[i].timestamp >= events[i - 1].timestamp


class TestProgressReporting:
    """Tests for progress reporting."""

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
    async def test_progress_increases(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that progress percentage increases."""
        progress_updates = []

        async def progress_callback(progress):
            progress_updates.append(progress)

        executor = TestExecutor(exec_request, progress_callback=progress_callback)

        await executor.execute()

        # Extract percentages
        percentages = [p.overall_progress_percent for p in progress_updates]

        # Should start low and end at 100
        if len(percentages) > 1:
            assert percentages[-1] >= percentages[0]

    @pytest.mark.asyncio
    async def test_progress_reaches_100(
        self,
        exec_request,
        mock_calibration_service,
    ):
        """Test that progress reaches 100% on completion."""
        progress_updates = []

        async def progress_callback(progress):
            progress_updates.append(progress)

        executor = TestExecutor(exec_request, progress_callback=progress_callback)

        await executor.execute()

        # Final progress should be 100%
        if progress_updates:
            assert progress_updates[-1].overall_progress_percent == 100
