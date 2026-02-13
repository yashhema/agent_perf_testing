"""Unit tests for ExecutionStateMachine."""

import pytest

from app.models.enums import ExecutionStatus
from app.services.state_machine import ExecutionStateMachine, TransitionResult


class TestExecutionStateMachine:
    """Unit tests for ExecutionStateMachine."""

    # ============================================================
    # Valid Transition Tests
    # ============================================================

    def test_valid_transition_notstarted_to_calibrating(self) -> None:
        """Test valid transition from notstarted to calibrating."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.CALIBRATING,
        )

    def test_valid_transition_calibrating_to_ready(self) -> None:
        """Test valid transition from calibrating to ready."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.READY,
        )

    def test_valid_transition_calibrating_to_ended_error(self) -> None:
        """Test valid transition from calibrating to ended_error."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.ENDED_ERROR,
        )

    def test_valid_transition_ready_to_executing(self) -> None:
        """Test valid transition from ready to executing."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.READY,
            ExecutionStatus.EXECUTING,
        )

    def test_valid_transition_executing_to_paused(self) -> None:
        """Test valid transition from executing to paused."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.EXECUTING,
            ExecutionStatus.PAUSED,
        )

    def test_valid_transition_executing_to_ended(self) -> None:
        """Test valid transition from executing to ended."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.EXECUTING,
            ExecutionStatus.ENDED,
        )

    def test_valid_transition_executing_to_ended_error(self) -> None:
        """Test valid transition from executing to ended_error."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.EXECUTING,
            ExecutionStatus.ENDED_ERROR,
        )

    def test_valid_transition_paused_to_executing(self) -> None:
        """Test valid transition from paused to executing."""
        assert ExecutionStateMachine.can_transition(
            ExecutionStatus.PAUSED,
            ExecutionStatus.EXECUTING,
        )

    # ============================================================
    # Invalid Transition Tests
    # ============================================================

    def test_invalid_transition_notstarted_to_executing(self) -> None:
        """Test invalid direct transition from notstarted to executing."""
        assert not ExecutionStateMachine.can_transition(
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.EXECUTING,
        )

    def test_invalid_transition_notstarted_to_ready(self) -> None:
        """Test invalid transition from notstarted to ready."""
        assert not ExecutionStateMachine.can_transition(
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.READY,
        )

    def test_invalid_transition_calibrating_to_executing(self) -> None:
        """Test invalid transition from calibrating to executing."""
        assert not ExecutionStateMachine.can_transition(
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.EXECUTING,
        )

    def test_invalid_transition_paused_to_ended(self) -> None:
        """Test invalid transition from paused to ended."""
        assert not ExecutionStateMachine.can_transition(
            ExecutionStatus.PAUSED,
            ExecutionStatus.ENDED,
        )

    def test_invalid_transition_ended_to_any(self) -> None:
        """Test that ended state has no outgoing transitions."""
        for target_state in ExecutionStatus:
            if target_state != ExecutionStatus.ENDED:
                assert not ExecutionStateMachine.can_transition(
                    ExecutionStatus.ENDED,
                    target_state,
                )

    # ============================================================
    # Terminal State Tests
    # ============================================================

    def test_terminal_states_have_no_transitions(self) -> None:
        """Test that terminal states have no outgoing transitions."""
        terminal_states = [
            ExecutionStatus.ENDED,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        ]

        for state in terminal_states:
            assert ExecutionStateMachine.is_terminal(state)
            transitions = ExecutionStateMachine.get_valid_transitions(state)
            assert len(transitions) == 0

    def test_non_terminal_states(self) -> None:
        """Test that non-terminal states are identified correctly."""
        non_terminal_states = [
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.READY,
            ExecutionStatus.EXECUTING,
            ExecutionStatus.PAUSED,
        ]

        for state in non_terminal_states:
            assert not ExecutionStateMachine.is_terminal(state)

    # ============================================================
    # Action Tests
    # ============================================================

    def test_continue_action_from_notstarted(self) -> None:
        """Test continue action from notstarted starts calibration."""
        target = ExecutionStateMachine.get_action_target_state(
            ExecutionStatus.NOT_STARTED,
            "continue",
        )
        assert target == ExecutionStatus.CALIBRATING

    def test_continue_action_from_ready(self) -> None:
        """Test continue action from ready starts executing."""
        target = ExecutionStateMachine.get_action_target_state(
            ExecutionStatus.READY,
            "continue",
        )
        assert target == ExecutionStatus.EXECUTING

    def test_continue_action_from_paused(self) -> None:
        """Test continue action from paused resumes executing."""
        target = ExecutionStateMachine.get_action_target_state(
            ExecutionStatus.PAUSED,
            "continue",
        )
        assert target == ExecutionStatus.EXECUTING

    def test_pause_action_from_executing(self) -> None:
        """Test pause action from executing."""
        target = ExecutionStateMachine.get_action_target_state(
            ExecutionStatus.EXECUTING,
            "pause",
        )
        assert target == ExecutionStatus.PAUSED

    def test_abandon_action_from_any_non_terminal(self) -> None:
        """Test abandon action is valid from any non-terminal state."""
        non_terminal = [
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.READY,
            ExecutionStatus.EXECUTING,
            ExecutionStatus.PAUSED,
        ]

        for state in non_terminal:
            target = ExecutionStateMachine.get_action_target_state(state, "abandon")
            assert target == ExecutionStatus.ABANDONED

    def test_status_action_returns_current_state(self) -> None:
        """Test status action returns the current state."""
        for state in ExecutionStatus:
            target = ExecutionStateMachine.get_action_target_state(state, "status")
            assert target == state

    def test_invalid_action_returns_none(self) -> None:
        """Test invalid action returns None."""
        target = ExecutionStateMachine.get_action_target_state(
            ExecutionStatus.NOT_STARTED,
            "invalid_action",
        )
        assert target is None

    def test_pause_from_non_executing_returns_none(self) -> None:
        """Test pause action from non-executing state returns None."""
        for state in [
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.READY,
            ExecutionStatus.PAUSED,
        ]:
            target = ExecutionStateMachine.get_action_target_state(state, "pause")
            assert target is None

    # ============================================================
    # Valid Actions Tests
    # ============================================================

    def test_get_valid_actions_notstarted(self) -> None:
        """Test valid actions for notstarted state."""
        actions = ExecutionStateMachine.get_valid_actions(ExecutionStatus.NOT_STARTED)
        assert "status" in actions
        assert "abandon" in actions
        assert "continue" in actions
        assert "pause" not in actions

    def test_get_valid_actions_executing(self) -> None:
        """Test valid actions for executing state."""
        actions = ExecutionStateMachine.get_valid_actions(ExecutionStatus.EXECUTING)
        assert "status" in actions
        assert "abandon" in actions
        assert "pause" in actions
        assert "continue" not in actions

    def test_get_valid_actions_paused(self) -> None:
        """Test valid actions for paused state."""
        actions = ExecutionStateMachine.get_valid_actions(ExecutionStatus.PAUSED)
        assert "status" in actions
        assert "abandon" in actions
        assert "continue" in actions
        assert "pause" not in actions

    def test_get_valid_actions_terminal(self) -> None:
        """Test valid actions for terminal states."""
        for state in [
            ExecutionStatus.ENDED,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        ]:
            actions = ExecutionStateMachine.get_valid_actions(state)
            assert actions == ["status"]

    # ============================================================
    # Validate Transition Tests
    # ============================================================

    def test_validate_transition_success(self) -> None:
        """Test successful transition validation."""
        result = ExecutionStateMachine.validate_transition(
            ExecutionStatus.NOT_STARTED,
            "continue",
        )
        assert result.success
        assert result.new_status == ExecutionStatus.CALIBRATING
        assert "Transitioning" in result.message

    def test_validate_transition_status_action(self) -> None:
        """Test status action validation."""
        result = ExecutionStateMachine.validate_transition(
            ExecutionStatus.EXECUTING,
            "status",
        )
        assert result.success
        assert result.new_status == ExecutionStatus.EXECUTING
        assert "Current status" in result.message

    def test_validate_transition_invalid_action(self) -> None:
        """Test invalid action validation."""
        result = ExecutionStateMachine.validate_transition(
            ExecutionStatus.NOT_STARTED,
            "pause",
        )
        assert not result.success
        assert result.new_status is None
        assert "Invalid action" in result.message

    def test_validate_transition_terminal_state(self) -> None:
        """Test action on terminal state."""
        result = ExecutionStateMachine.validate_transition(
            ExecutionStatus.ENDED,
            "continue",
        )
        assert not result.success
        assert result.new_status is None
        assert "terminal state" in result.message

    def test_validate_transition_abandon(self) -> None:
        """Test abandon action validation."""
        result = ExecutionStateMachine.validate_transition(
            ExecutionStatus.EXECUTING,
            "abandon",
        )
        assert result.success
        assert result.new_status == ExecutionStatus.ABANDONED

    # ============================================================
    # Helper Method Tests
    # ============================================================

    def test_get_completion_states(self) -> None:
        """Test getting completion states."""
        completion_states = ExecutionStateMachine.get_completion_states()
        assert ExecutionStatus.ENDED in completion_states
        assert len(completion_states) == 1

    def test_get_error_states(self) -> None:
        """Test getting error states."""
        error_states = ExecutionStateMachine.get_error_states()
        assert ExecutionStatus.ENDED_ERROR in error_states
        assert ExecutionStatus.ABANDONED in error_states
        assert len(error_states) == 2

    def test_is_active(self) -> None:
        """Test is_active method."""
        active_states = [
            ExecutionStatus.NOT_STARTED,
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.READY,
            ExecutionStatus.EXECUTING,
            ExecutionStatus.PAUSED,
        ]

        for state in active_states:
            assert ExecutionStateMachine.is_active(state)

        inactive_states = [
            ExecutionStatus.ENDED,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        ]

        for state in inactive_states:
            assert not ExecutionStateMachine.is_active(state)

    def test_requires_calibration(self) -> None:
        """Test requires_calibration method."""
        assert ExecutionStateMachine.requires_calibration(ExecutionStatus.NOT_STARTED)
        assert ExecutionStateMachine.requires_calibration(ExecutionStatus.CALIBRATING)
        assert not ExecutionStateMachine.requires_calibration(ExecutionStatus.READY)
        assert not ExecutionStateMachine.requires_calibration(ExecutionStatus.EXECUTING)

    def test_is_runnable(self) -> None:
        """Test is_runnable method."""
        assert ExecutionStateMachine.is_runnable(ExecutionStatus.READY)
        assert ExecutionStateMachine.is_runnable(ExecutionStatus.PAUSED)
        assert not ExecutionStateMachine.is_runnable(ExecutionStatus.NOT_STARTED)
        assert not ExecutionStateMachine.is_runnable(ExecutionStatus.EXECUTING)
        assert not ExecutionStateMachine.is_runnable(ExecutionStatus.ENDED)
