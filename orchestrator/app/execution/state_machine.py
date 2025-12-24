"""State machine for test execution lifecycle."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Dict, Callable, List

from .models import (
    ExecutionStatus,
    ExecutionPhase,
    ExecutionState,
    PhaseResult,
)


@dataclass(frozen=True)
class Transition:
    """Represents a valid state transition."""

    from_status: ExecutionStatus
    to_status: ExecutionStatus
    from_phase: Optional[ExecutionPhase] = None
    to_phase: Optional[ExecutionPhase] = None


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: ExecutionStatus,
        to_status: ExecutionStatus,
        from_phase: Optional[ExecutionPhase] = None,
        to_phase: Optional[ExecutionPhase] = None,
    ):
        self.from_status = from_status
        self.to_status = to_status
        self.from_phase = from_phase
        self.to_phase = to_phase
        super().__init__(
            f"Invalid transition from {from_status.value}"
            f"/{from_phase.value if from_phase else 'None'} to "
            f"{to_status.value}/{to_phase.value if to_phase else 'None'}"
        )


class ExecutionStateMachine:
    """
    State machine for managing execution lifecycle.

    Enforces valid state transitions and tracks phase history.
    """

    # Valid status transitions
    # Order: PENDING -> INITIALIZING -> DEPLOYING -> CALIBRATING -> RUNNING -> COLLECTING -> COMPLETED
    VALID_STATUS_TRANSITIONS: Dict[ExecutionStatus, Set[ExecutionStatus]] = {
        ExecutionStatus.PENDING: {
            ExecutionStatus.INITIALIZING,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.INITIALIZING: {
            ExecutionStatus.DEPLOYING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.DEPLOYING: {
            ExecutionStatus.CALIBRATING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.CALIBRATING: {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.RUNNING: {
            ExecutionStatus.COLLECTING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.COLLECTING: {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        },
        ExecutionStatus.COMPLETED: set(),  # Terminal state
        ExecutionStatus.FAILED: set(),  # Terminal state
        ExecutionStatus.CANCELLED: set(),  # Terminal state
    }

    # Valid phase transitions
    VALID_PHASE_TRANSITIONS: Dict[ExecutionPhase, Set[ExecutionPhase]] = {
        ExecutionPhase.INIT: {
            ExecutionPhase.VM_PREPARATION,
            ExecutionPhase.EMULATOR_DEPLOYMENT,
            ExecutionPhase.DONE,  # For cancelled
        },
        ExecutionPhase.VM_PREPARATION: {
            ExecutionPhase.EMULATOR_DEPLOYMENT,
            ExecutionPhase.CLEANUP,
            ExecutionPhase.DONE,
        },
        ExecutionPhase.EMULATOR_DEPLOYMENT: {
            ExecutionPhase.CALIBRATION,
            ExecutionPhase.CLEANUP,
            ExecutionPhase.DONE,
        },
        ExecutionPhase.CALIBRATION: {
            ExecutionPhase.LOAD_TEST,
            ExecutionPhase.CLEANUP,
            ExecutionPhase.DONE,
        },
        ExecutionPhase.LOAD_TEST: {
            ExecutionPhase.RESULT_COLLECTION,
            ExecutionPhase.CLEANUP,
            ExecutionPhase.DONE,
        },
        ExecutionPhase.RESULT_COLLECTION: {
            ExecutionPhase.CLEANUP,
            ExecutionPhase.DONE,
        },
        ExecutionPhase.CLEANUP: {
            ExecutionPhase.DONE,
        },
        ExecutionPhase.DONE: set(),  # Terminal phase
    }

    # Phase to status mapping
    PHASE_STATUS_MAP: Dict[ExecutionPhase, ExecutionStatus] = {
        ExecutionPhase.INIT: ExecutionStatus.INITIALIZING,
        ExecutionPhase.VM_PREPARATION: ExecutionStatus.INITIALIZING,
        ExecutionPhase.EMULATOR_DEPLOYMENT: ExecutionStatus.DEPLOYING,
        ExecutionPhase.CALIBRATION: ExecutionStatus.CALIBRATING,
        ExecutionPhase.LOAD_TEST: ExecutionStatus.RUNNING,
        ExecutionPhase.RESULT_COLLECTION: ExecutionStatus.COLLECTING,
        ExecutionPhase.CLEANUP: ExecutionStatus.COLLECTING,
        ExecutionPhase.DONE: ExecutionStatus.COMPLETED,
    }

    def __init__(self, state: ExecutionState):
        self._state = state
        self._listeners: List[Callable[[ExecutionState, Transition], None]] = []

    @property
    def state(self) -> ExecutionState:
        """Get current state."""
        return self._state

    @property
    def current_status(self) -> ExecutionStatus:
        """Get current status."""
        return self._state.status

    @property
    def current_phase(self) -> ExecutionPhase:
        """Get current phase."""
        return self._state.current_phase

    def is_terminal(self) -> bool:
        """Check if execution is in a terminal state."""
        return self._state.status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }

    def can_transition_to(
        self,
        status: ExecutionStatus,
        phase: Optional[ExecutionPhase] = None,
    ) -> bool:
        """Check if transition to given status/phase is valid."""
        # Allow staying at same status (for phase-only changes)
        if status != self._state.status:
            valid_statuses = self.VALID_STATUS_TRANSITIONS.get(self._state.status, set())
            if status not in valid_statuses:
                return False

        # Check phase transition if specified and different from current
        if phase is not None and phase != self._state.current_phase:
            valid_phases = self.VALID_PHASE_TRANSITIONS.get(
                self._state.current_phase, set()
            )
            if phase not in valid_phases:
                return False

        return True

    def transition_to(
        self,
        status: ExecutionStatus,
        phase: Optional[ExecutionPhase] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Transition to a new status/phase.

        Args:
            status: Target status
            phase: Target phase (optional)
            error_message: Error message if transitioning to FAILED

        Raises:
            InvalidTransitionError: If transition is not valid
        """
        if not self.can_transition_to(status, phase):
            raise InvalidTransitionError(
                from_status=self._state.status,
                to_status=status,
                from_phase=self._state.current_phase,
                to_phase=phase,
            )

        transition = Transition(
            from_status=self._state.status,
            to_status=status,
            from_phase=self._state.current_phase,
            to_phase=phase,
        )

        # Update state
        now = datetime.utcnow()

        if self._state.started_at is None and status != ExecutionStatus.PENDING:
            self._state.started_at = now

        self._state.status = status

        if phase is not None:
            self._state.current_phase = phase

        if status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }:
            self._state.completed_at = now

        if error_message:
            self._state.last_error = error_message
            self._state.error_phase = self._state.current_phase

        # Notify listeners
        for listener in self._listeners:
            listener(self._state, transition)

    def start_phase(self, phase: ExecutionPhase) -> None:
        """
        Start a new phase.

        Records phase start time and updates status accordingly.
        """
        # Determine appropriate status for phase
        status = self.PHASE_STATUS_MAP.get(phase, self._state.status)

        # Create phase result
        phase_result = PhaseResult(
            phase=phase,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.utcnow(),
        )

        # Add to phase results
        self._state.phase_results.append(phase_result)

        # Transition
        self.transition_to(status=status, phase=phase)

    def complete_phase(
        self,
        phase: ExecutionPhase,
        success: bool = True,
        error_message: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        """
        Complete a phase.

        Records phase completion and duration.
        """
        now = datetime.utcnow()

        # Find and update phase result
        for i, result in enumerate(self._state.phase_results):
            if result.phase == phase and result.completed_at is None:
                duration = (now - result.started_at).total_seconds()
                updated_result = PhaseResult(
                    phase=result.phase,
                    status=(
                        ExecutionStatus.COMPLETED if success else ExecutionStatus.FAILED
                    ),
                    started_at=result.started_at,
                    completed_at=now,
                    duration_sec=duration,
                    error_message=error_message,
                    details=details,
                )
                self._state.phase_results[i] = updated_result
                break

        if not success and error_message:
            self._state.last_error = error_message
            self._state.error_phase = phase

    def fail(self, error_message: str, phase: Optional[ExecutionPhase] = None) -> None:
        """
        Mark execution as failed.

        Args:
            error_message: Description of the failure
            phase: Phase where failure occurred (defaults to current)
        """
        failure_phase = phase or self._state.current_phase

        # Complete current phase as failed
        self.complete_phase(
            phase=failure_phase,
            success=False,
            error_message=error_message,
        )

        # Transition to failed status
        self.transition_to(
            status=ExecutionStatus.FAILED,
            error_message=error_message,
        )

    def cancel(self, reason: Optional[str] = None) -> None:
        """
        Cancel execution.

        Args:
            reason: Reason for cancellation
        """
        message = reason or "Execution cancelled by user"

        # Complete current phase as cancelled
        self.complete_phase(
            phase=self._state.current_phase,
            success=False,
            error_message=message,
        )

        # Transition to cancelled status
        self.transition_to(
            status=ExecutionStatus.CANCELLED,
            error_message=message,
        )

    def complete(self) -> None:
        """Mark execution as successfully completed."""
        # Complete done phase
        self.complete_phase(
            phase=ExecutionPhase.DONE,
            success=True,
        )

        # Transition to completed status
        self.transition_to(
            status=ExecutionStatus.COMPLETED,
            phase=ExecutionPhase.DONE,
        )

    def add_listener(
        self, listener: Callable[[ExecutionState, Transition], None]
    ) -> None:
        """Add a state change listener."""
        self._listeners.append(listener)

    def remove_listener(
        self, listener: Callable[[ExecutionState, Transition], None]
    ) -> None:
        """Remove a state change listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def get_phase_duration(self, phase: ExecutionPhase) -> Optional[float]:
        """Get duration of a completed phase."""
        for result in self._state.phase_results:
            if result.phase == phase and result.duration_sec is not None:
                return result.duration_sec
        return None

    def get_total_duration(self) -> Optional[float]:
        """Get total execution duration."""
        if self._state.started_at is None:
            return None

        end_time = self._state.completed_at or datetime.utcnow()
        return (end_time - self._state.started_at).total_seconds()

    def get_phase_results(self) -> List[PhaseResult]:
        """Get all phase results."""
        return list(self._state.phase_results)

    def increment_retry(self) -> int:
        """Increment retry count and return new value."""
        self._state.retry_count += 1
        return self._state.retry_count
