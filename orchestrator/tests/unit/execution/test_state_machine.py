"""Unit tests for execution state machine."""

import pytest
from datetime import datetime

from app.execution.models import (
    ExecutionPhase,
    ExecutionState,
    ExecutionStatus,
)
from app.execution.state_machine import (
    ExecutionStateMachine,
    InvalidTransitionError,
    Transition,
)


class TestTransition:
    """Tests for Transition dataclass."""

    def test_create_transition(self):
        """Test creating a transition."""
        transition = Transition(
            from_status=ExecutionStatus.PENDING,
            to_status=ExecutionStatus.INITIALIZING,
            from_phase=ExecutionPhase.INIT,
            to_phase=ExecutionPhase.VM_PREPARATION,
        )

        assert transition.from_status == ExecutionStatus.PENDING
        assert transition.to_status == ExecutionStatus.INITIALIZING
        assert transition.from_phase == ExecutionPhase.INIT
        assert transition.to_phase == ExecutionPhase.VM_PREPARATION


class TestInvalidTransitionError:
    """Tests for InvalidTransitionError."""

    def test_error_message(self):
        """Test error message formatting."""
        error = InvalidTransitionError(
            from_status=ExecutionStatus.PENDING,
            to_status=ExecutionStatus.COMPLETED,
            from_phase=ExecutionPhase.INIT,
            to_phase=ExecutionPhase.DONE,
        )

        assert "pending" in str(error)
        assert "completed" in str(error)
        assert "init" in str(error)
        assert "done" in str(error)


class TestExecutionStateMachine:
    """Tests for ExecutionStateMachine."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    @pytest.fixture
    def sm(self, state):
        """Create state machine instance."""
        return ExecutionStateMachine(state)

    def test_initial_state(self, sm):
        """Test initial state machine state."""
        assert sm.current_status == ExecutionStatus.PENDING
        assert sm.current_phase == ExecutionPhase.INIT
        assert sm.is_terminal() is False

    def test_state_property(self, sm, state):
        """Test state property returns the state."""
        assert sm.state == state

    def test_can_transition_to_valid_status(self, sm):
        """Test can_transition_to returns True for valid transitions."""
        assert sm.can_transition_to(ExecutionStatus.INITIALIZING) is True
        assert sm.can_transition_to(ExecutionStatus.CANCELLED) is True

    def test_can_transition_to_invalid_status(self, sm):
        """Test can_transition_to returns False for invalid transitions."""
        assert sm.can_transition_to(ExecutionStatus.COMPLETED) is False
        assert sm.can_transition_to(ExecutionStatus.RUNNING) is False

    def test_can_transition_to_with_phase(self, sm):
        """Test can_transition_to with phase validation."""
        assert sm.can_transition_to(
            ExecutionStatus.INITIALIZING,
            ExecutionPhase.VM_PREPARATION,
        ) is True

        assert sm.can_transition_to(
            ExecutionStatus.INITIALIZING,
            ExecutionPhase.LOAD_TEST,  # Invalid phase transition
        ) is False

    def test_transition_to_valid(self, sm):
        """Test valid transition."""
        sm.transition_to(
            ExecutionStatus.INITIALIZING,
            ExecutionPhase.VM_PREPARATION,
        )

        assert sm.current_status == ExecutionStatus.INITIALIZING
        assert sm.current_phase == ExecutionPhase.VM_PREPARATION
        assert sm.state.started_at is not None

    def test_transition_to_invalid(self, sm):
        """Test invalid transition raises error."""
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(ExecutionStatus.COMPLETED)

    def test_transition_sets_started_at(self, sm):
        """Test transition sets started_at timestamp."""
        assert sm.state.started_at is None

        sm.transition_to(ExecutionStatus.INITIALIZING)

        assert sm.state.started_at is not None

    def test_transition_to_terminal_sets_completed_at(self, sm):
        """Test transition to terminal state sets completed_at."""
        sm.transition_to(ExecutionStatus.CANCELLED)

        assert sm.state.completed_at is not None
        assert sm.is_terminal() is True

    def test_transition_with_error_message(self, sm):
        """Test transition with error message."""
        sm.transition_to(
            ExecutionStatus.CANCELLED,
            error_message="User cancelled",
        )

        assert sm.state.last_error == "User cancelled"

    def test_is_terminal_completed(self, state):
        """Test is_terminal for COMPLETED status."""
        state.status = ExecutionStatus.COMPLETED
        sm = ExecutionStateMachine(state)

        assert sm.is_terminal() is True

    def test_is_terminal_failed(self, state):
        """Test is_terminal for FAILED status."""
        state.status = ExecutionStatus.FAILED
        sm = ExecutionStateMachine(state)

        assert sm.is_terminal() is True

    def test_is_terminal_cancelled(self, state):
        """Test is_terminal for CANCELLED status."""
        state.status = ExecutionStatus.CANCELLED
        sm = ExecutionStateMachine(state)

        assert sm.is_terminal() is True


class TestPhaseManagement:
    """Tests for phase management methods."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    @pytest.fixture
    def sm(self, state):
        """Create state machine instance."""
        return ExecutionStateMachine(state)

    def test_start_phase(self, sm):
        """Test starting a phase."""
        sm.start_phase(ExecutionPhase.VM_PREPARATION)

        assert sm.current_phase == ExecutionPhase.VM_PREPARATION
        assert len(sm.state.phase_results) == 1
        assert sm.state.phase_results[0].phase == ExecutionPhase.VM_PREPARATION
        assert sm.state.phase_results[0].completed_at is None

    def test_complete_phase_success(self, sm):
        """Test completing a phase successfully."""
        sm.start_phase(ExecutionPhase.VM_PREPARATION)
        sm.complete_phase(
            ExecutionPhase.VM_PREPARATION,
            success=True,
            details="VM prepared",
        )

        assert len(sm.state.phase_results) == 1
        result = sm.state.phase_results[0]
        assert result.status == ExecutionStatus.COMPLETED
        assert result.completed_at is not None
        assert result.duration_sec is not None
        assert result.details == "VM prepared"

    def test_complete_phase_failure(self, sm):
        """Test completing a phase with failure."""
        # First transition to INITIALIZING to allow starting EMULATOR_DEPLOYMENT phase
        sm.transition_to(ExecutionStatus.INITIALIZING)
        sm.start_phase(ExecutionPhase.EMULATOR_DEPLOYMENT)
        sm.complete_phase(
            ExecutionPhase.EMULATOR_DEPLOYMENT,
            success=False,
            error_message="Connection refused",
        )

        result = sm.state.phase_results[0]
        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Connection refused"
        assert sm.state.last_error == "Connection refused"
        assert sm.state.error_phase == ExecutionPhase.EMULATOR_DEPLOYMENT

    def test_fail_marks_execution_failed(self, sm):
        """Test fail method marks execution as failed."""
        sm.transition_to(ExecutionStatus.INITIALIZING)
        sm.start_phase(ExecutionPhase.VM_PREPARATION)

        sm.fail("Critical error occurred")

        assert sm.current_status == ExecutionStatus.FAILED
        assert sm.state.last_error == "Critical error occurred"
        assert sm.is_terminal() is True

    def test_cancel_marks_execution_cancelled(self, sm):
        """Test cancel method marks execution as cancelled."""
        sm.transition_to(ExecutionStatus.INITIALIZING)
        sm.start_phase(ExecutionPhase.VM_PREPARATION)

        sm.cancel("User requested cancellation")

        assert sm.current_status == ExecutionStatus.CANCELLED
        assert "User requested cancellation" in sm.state.last_error
        assert sm.is_terminal() is True

    def test_complete_marks_execution_completed(self, sm):
        """Test complete method marks execution as completed."""
        # Go through required transitions (DEPLOYING -> CALIBRATING -> RUNNING)
        sm.transition_to(ExecutionStatus.INITIALIZING)
        sm.transition_to(ExecutionStatus.DEPLOYING, ExecutionPhase.EMULATOR_DEPLOYMENT)
        sm.transition_to(ExecutionStatus.CALIBRATING, ExecutionPhase.CALIBRATION)
        sm.transition_to(ExecutionStatus.RUNNING, ExecutionPhase.LOAD_TEST)
        sm.transition_to(ExecutionStatus.COLLECTING, ExecutionPhase.RESULT_COLLECTION)
        sm.start_phase(ExecutionPhase.DONE)

        sm.complete()

        assert sm.current_status == ExecutionStatus.COMPLETED
        assert sm.current_phase == ExecutionPhase.DONE
        assert sm.is_terminal() is True


class TestPhaseTracking:
    """Tests for phase duration tracking."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    @pytest.fixture
    def sm(self, state):
        """Create state machine instance."""
        return ExecutionStateMachine(state)

    def test_get_phase_duration(self, sm):
        """Test getting phase duration."""
        sm.start_phase(ExecutionPhase.VM_PREPARATION)
        sm.complete_phase(ExecutionPhase.VM_PREPARATION, success=True)

        duration = sm.get_phase_duration(ExecutionPhase.VM_PREPARATION)

        assert duration is not None
        assert duration >= 0

    def test_get_phase_duration_not_completed(self, sm):
        """Test getting duration of uncompleted phase."""
        sm.start_phase(ExecutionPhase.VM_PREPARATION)

        duration = sm.get_phase_duration(ExecutionPhase.VM_PREPARATION)

        assert duration is None

    def test_get_phase_duration_not_started(self, sm):
        """Test getting duration of unstarted phase."""
        duration = sm.get_phase_duration(ExecutionPhase.CALIBRATION)

        assert duration is None

    def test_get_total_duration(self, sm):
        """Test getting total execution duration."""
        sm.transition_to(ExecutionStatus.INITIALIZING)

        duration = sm.get_total_duration()

        assert duration is not None
        assert duration >= 0

    def test_get_total_duration_not_started(self, sm):
        """Test getting total duration when not started."""
        duration = sm.get_total_duration()

        assert duration is None

    def test_get_phase_results(self, sm):
        """Test getting all phase results."""
        sm.start_phase(ExecutionPhase.VM_PREPARATION)
        sm.complete_phase(ExecutionPhase.VM_PREPARATION, success=True)
        sm.start_phase(ExecutionPhase.EMULATOR_DEPLOYMENT)

        results = sm.get_phase_results()

        assert len(results) == 2
        assert results[0].phase == ExecutionPhase.VM_PREPARATION
        assert results[1].phase == ExecutionPhase.EMULATOR_DEPLOYMENT


class TestRetryTracking:
    """Tests for retry count tracking."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    @pytest.fixture
    def sm(self, state):
        """Create state machine instance."""
        return ExecutionStateMachine(state)

    def test_increment_retry(self, sm):
        """Test incrementing retry count."""
        assert sm.state.retry_count == 0

        count = sm.increment_retry()

        assert count == 1
        assert sm.state.retry_count == 1

    def test_multiple_retries(self, sm):
        """Test multiple retry increments."""
        sm.increment_retry()
        sm.increment_retry()
        count = sm.increment_retry()

        assert count == 3
        assert sm.state.retry_count == 3


class TestStateListeners:
    """Tests for state change listeners."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    @pytest.fixture
    def sm(self, state):
        """Create state machine instance."""
        return ExecutionStateMachine(state)

    def test_add_listener(self, sm):
        """Test adding a listener."""
        events = []

        def listener(state, transition):
            events.append((state.status, transition))

        sm.add_listener(listener)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        assert len(events) == 1
        assert events[0][0] == ExecutionStatus.INITIALIZING

    def test_remove_listener(self, sm):
        """Test removing a listener."""
        events = []

        def listener(state, transition):
            events.append(state.status)

        sm.add_listener(listener)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        sm.remove_listener(listener)
        sm.transition_to(ExecutionStatus.CANCELLED)

        assert len(events) == 1

    def test_multiple_listeners(self, sm):
        """Test multiple listeners."""
        events1 = []
        events2 = []

        def listener1(state, transition):
            events1.append(state.status)

        def listener2(state, transition):
            events2.append(state.status)

        sm.add_listener(listener1)
        sm.add_listener(listener2)
        sm.transition_to(ExecutionStatus.INITIALIZING)

        assert len(events1) == 1
        assert len(events2) == 1


class TestValidTransitions:
    """Tests to verify all valid state transitions."""

    @pytest.fixture
    def state(self):
        """Create initial execution state."""
        return ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

    def test_pending_to_initializing(self, state):
        """Test PENDING -> INITIALIZING."""
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.INITIALIZING)
        assert sm.current_status == ExecutionStatus.INITIALIZING

    def test_pending_to_cancelled(self, state):
        """Test PENDING -> CANCELLED."""
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.CANCELLED)
        assert sm.current_status == ExecutionStatus.CANCELLED

    def test_initializing_to_deploying(self, state):
        """Test INITIALIZING -> DEPLOYING."""
        state.status = ExecutionStatus.INITIALIZING
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.DEPLOYING)
        assert sm.current_status == ExecutionStatus.DEPLOYING

    def test_deploying_to_calibrating(self, state):
        """Test DEPLOYING -> CALIBRATING."""
        state.status = ExecutionStatus.DEPLOYING
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.CALIBRATING)
        assert sm.current_status == ExecutionStatus.CALIBRATING

    def test_calibrating_to_running(self, state):
        """Test CALIBRATING -> RUNNING."""
        state.status = ExecutionStatus.CALIBRATING
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.RUNNING)
        assert sm.current_status == ExecutionStatus.RUNNING

    def test_running_to_collecting(self, state):
        """Test RUNNING -> COLLECTING."""
        state.status = ExecutionStatus.RUNNING
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.COLLECTING)
        assert sm.current_status == ExecutionStatus.COLLECTING

    def test_collecting_to_completed(self, state):
        """Test COLLECTING -> COMPLETED."""
        state.status = ExecutionStatus.COLLECTING
        sm = ExecutionStateMachine(state)
        sm.transition_to(ExecutionStatus.COMPLETED)
        assert sm.current_status == ExecutionStatus.COMPLETED

    def test_any_to_failed(self, state):
        """Test any active status can transition to FAILED."""
        for status in [
            ExecutionStatus.INITIALIZING,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.DEPLOYING,
            ExecutionStatus.RUNNING,
            ExecutionStatus.COLLECTING,
        ]:
            state.status = status
            sm = ExecutionStateMachine(state)
            sm.transition_to(ExecutionStatus.FAILED)
            assert sm.current_status == ExecutionStatus.FAILED
            state.status = status  # Reset for next iteration

    def test_any_to_cancelled(self, state):
        """Test any active status can transition to CANCELLED."""
        for status in [
            ExecutionStatus.PENDING,
            ExecutionStatus.INITIALIZING,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.DEPLOYING,
            ExecutionStatus.RUNNING,
            ExecutionStatus.COLLECTING,
        ]:
            state.status = status
            sm = ExecutionStateMachine(state)
            sm.transition_to(ExecutionStatus.CANCELLED)
            assert sm.current_status == ExecutionStatus.CANCELLED
            state.status = status  # Reset for next iteration
