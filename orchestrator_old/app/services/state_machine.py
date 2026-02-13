"""Execution state machine for managing test run execution states.

This module defines the valid state transitions and actions for test run executions.

State Diagram:
    notstarted -> calibrating (action: continue with immediate_run)
    calibrating -> ready (on calibration success)
    calibrating -> ended_error (on calibration failure)
    ready -> executing (action: continue)
    executing -> paused (action: pause)
    executing -> ended (on completion)
    executing -> ended_error (on failure)
    paused -> executing (action: continue)
    any non-terminal -> abandoned (action: abandon)

Terminal States: ended, ended_error, abandoned
"""

from dataclasses import dataclass
from typing import Optional, Set, FrozenSet

from app.models.enums import ExecutionStatus


@dataclass(frozen=True)
class TransitionResult:
    """Result of a state transition attempt."""

    success: bool
    message: str
    new_status: Optional[ExecutionStatus] = None


class ExecutionStateMachine:
    """
    State machine for test run execution.

    Manages valid state transitions and determines target states for actions.
    """

    # Define valid transitions as frozensets for immutability
    _TRANSITIONS: dict[ExecutionStatus, FrozenSet[ExecutionStatus]] = {
        ExecutionStatus.NOT_STARTED: frozenset({
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.ABANDONED,
        }),
        ExecutionStatus.CALIBRATING: frozenset({
            ExecutionStatus.READY,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        }),
        ExecutionStatus.READY: frozenset({
            ExecutionStatus.EXECUTING,
            ExecutionStatus.ABANDONED,
        }),
        ExecutionStatus.EXECUTING: frozenset({
            ExecutionStatus.PAUSED,
            ExecutionStatus.ENDED,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        }),
        ExecutionStatus.PAUSED: frozenset({
            ExecutionStatus.EXECUTING,
            ExecutionStatus.ABANDONED,
        }),
        # Terminal states have no outgoing transitions
        ExecutionStatus.ENDED: frozenset(),
        ExecutionStatus.ENDED_ERROR: frozenset(),
        ExecutionStatus.ABANDONED: frozenset(),
    }

    # Terminal states
    _TERMINAL_STATES: FrozenSet[ExecutionStatus] = frozenset({
        ExecutionStatus.ENDED,
        ExecutionStatus.ENDED_ERROR,
        ExecutionStatus.ABANDONED,
    })

    # Action to target state mapping
    _ACTION_MAP: dict[ExecutionStatus, dict[str, ExecutionStatus]] = {
        ExecutionStatus.NOT_STARTED: {
            "continue": ExecutionStatus.CALIBRATING,
        },
        ExecutionStatus.READY: {
            "continue": ExecutionStatus.EXECUTING,
        },
        ExecutionStatus.EXECUTING: {
            "pause": ExecutionStatus.PAUSED,
        },
        ExecutionStatus.PAUSED: {
            "continue": ExecutionStatus.EXECUTING,
        },
    }

    @classmethod
    def can_transition(
        cls,
        from_state: ExecutionStatus,
        to_state: ExecutionStatus,
    ) -> bool:
        """
        Check if a transition from one state to another is valid.

        Args:
            from_state: The current state.
            to_state: The target state.

        Returns:
            True if the transition is valid, False otherwise.
        """
        valid_targets = cls._TRANSITIONS.get(from_state, frozenset())
        return to_state in valid_targets

    @classmethod
    def get_valid_transitions(
        cls,
        current_state: ExecutionStatus,
    ) -> FrozenSet[ExecutionStatus]:
        """
        Get all valid target states from the current state.

        Args:
            current_state: The current execution state.

        Returns:
            Set of valid target states.
        """
        return cls._TRANSITIONS.get(current_state, frozenset())

    @classmethod
    def is_terminal(cls, state: ExecutionStatus) -> bool:
        """
        Check if a state is terminal (no further transitions possible).

        Args:
            state: The state to check.

        Returns:
            True if the state is terminal, False otherwise.
        """
        return state in cls._TERMINAL_STATES

    @classmethod
    def get_action_target_state(
        cls,
        current_state: ExecutionStatus,
        action: str,
    ) -> Optional[ExecutionStatus]:
        """
        Get the target state for an action from the current state.

        Args:
            current_state: The current execution state.
            action: The action to perform (continue, pause, abandon, status).

        Returns:
            The target state if the action is valid, None otherwise.
        """
        # Status action doesn't change state
        if action == "status":
            return current_state

        # Abandon is always valid for non-terminal states
        if action == "abandon" and not cls.is_terminal(current_state):
            return ExecutionStatus.ABANDONED

        # Look up action in the map
        state_actions = cls._ACTION_MAP.get(current_state, {})
        return state_actions.get(action)

    @classmethod
    def get_valid_actions(cls, current_state: ExecutionStatus) -> list[str]:
        """
        Get all valid actions for the current state.

        Args:
            current_state: The current execution state.

        Returns:
            List of valid action names.
        """
        actions = ["status"]  # Status is always valid

        if cls.is_terminal(current_state):
            return actions

        # Abandon is valid for all non-terminal states
        actions.append("abandon")

        # Add state-specific actions
        state_actions = cls._ACTION_MAP.get(current_state, {})
        actions.extend(state_actions.keys())

        return actions

    @classmethod
    def validate_transition(
        cls,
        current_state: ExecutionStatus,
        action: str,
    ) -> TransitionResult:
        """
        Validate an action and return the transition result.

        Args:
            current_state: The current execution state.
            action: The action to perform.

        Returns:
            TransitionResult with success status and target state.
        """
        # Status action doesn't change state
        if action == "status":
            return TransitionResult(
                success=True,
                message=f"Current status: {current_state.value}",
                new_status=current_state,
            )

        # Check if state is terminal
        if cls.is_terminal(current_state):
            return TransitionResult(
                success=False,
                message=f"Cannot perform action '{action}' on terminal state '{current_state.value}'",
                new_status=None,
            )

        # Get target state for the action
        target_state = cls.get_action_target_state(current_state, action)

        if target_state is None:
            valid_actions = cls.get_valid_actions(current_state)
            return TransitionResult(
                success=False,
                message=f"Invalid action '{action}' for state '{current_state.value}'. "
                        f"Valid actions: {', '.join(valid_actions)}",
                new_status=None,
            )

        return TransitionResult(
            success=True,
            message=f"Transitioning from '{current_state.value}' to '{target_state.value}'",
            new_status=target_state,
        )

    @classmethod
    def get_completion_states(cls) -> FrozenSet[ExecutionStatus]:
        """Get the set of successful completion states."""
        return frozenset({ExecutionStatus.ENDED})

    @classmethod
    def get_error_states(cls) -> FrozenSet[ExecutionStatus]:
        """Get the set of error/failure states."""
        return frozenset({ExecutionStatus.ENDED_ERROR, ExecutionStatus.ABANDONED})

    @classmethod
    def is_active(cls, state: ExecutionStatus) -> bool:
        """Check if an execution is in an active (non-terminal) state."""
        return not cls.is_terminal(state)

    @classmethod
    def requires_calibration(cls, state: ExecutionStatus) -> bool:
        """Check if the state indicates calibration is needed or in progress."""
        return state in {ExecutionStatus.NOT_STARTED, ExecutionStatus.CALIBRATING}

    @classmethod
    def is_runnable(cls, state: ExecutionStatus) -> bool:
        """Check if execution can be started or resumed."""
        return state in {ExecutionStatus.READY, ExecutionStatus.PAUSED}
