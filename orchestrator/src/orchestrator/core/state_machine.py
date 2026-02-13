"""Test run state machine.

Manages state transitions for TestRunORM per ORCHESTRATOR_DATABASE_SCHEMA.md:
  created -> validating -> setting_up -> calibrating -> generating_sequences
           -> executing -> comparing -> completed
  Any active state -> paused (at boundary)
  paused -> {resume to next state}
  Any active state -> cancelled (immediate)
  Any active state -> failed (non-recoverable)
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from orchestrator.models.enums import TestRunState
from orchestrator.models.orm import TestRunORM

logger = logging.getLogger(__name__)

# Valid state transitions
TRANSITIONS = {
    TestRunState.created: [TestRunState.validating, TestRunState.cancelled],
    TestRunState.validating: [TestRunState.setting_up, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.setting_up: [TestRunState.calibrating, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.calibrating: [TestRunState.generating_sequences, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.generating_sequences: [TestRunState.executing, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.executing: [TestRunState.comparing, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.comparing: [TestRunState.completed, TestRunState.paused, TestRunState.cancelled, TestRunState.failed],
    TestRunState.paused: [
        TestRunState.validating, TestRunState.setting_up, TestRunState.calibrating,
        TestRunState.generating_sequences, TestRunState.executing, TestRunState.comparing,
        TestRunState.cancelled,
    ],
    TestRunState.completed: [],
    TestRunState.cancelled: [],
    TestRunState.failed: [],
}

# The forward progression sequence
FORWARD_SEQUENCE = [
    TestRunState.created,
    TestRunState.validating,
    TestRunState.setting_up,
    TestRunState.calibrating,
    TestRunState.generating_sequences,
    TestRunState.executing,
    TestRunState.comparing,
    TestRunState.completed,
]


def transition(session: Session, test_run: TestRunORM, target_state: TestRunState) -> None:
    """Transition a test run to a new state.

    Args:
        session: DB session
        test_run: TestRunORM instance
        target_state: desired state

    Raises:
        ValueError: if transition is invalid
    """
    current = test_run.state
    allowed = TRANSITIONS.get(current, [])

    if target_state not in allowed:
        raise ValueError(
            f"Invalid transition: {current.value} -> {target_state.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )

    logger.info(
        "TestRun %d: %s -> %s",
        test_run.id, current.value, target_state.value,
    )
    test_run.state = target_state

    if target_state == TestRunState.validating and test_run.started_at is None:
        test_run.started_at = datetime.utcnow()

    if target_state in (TestRunState.completed, TestRunState.cancelled, TestRunState.failed):
        test_run.completed_at = datetime.utcnow()

    session.commit()


def next_forward_state(current: TestRunState) -> Optional[TestRunState]:
    """Get the next state in the forward progression sequence."""
    try:
        idx = FORWARD_SEQUENCE.index(current)
        if idx + 1 < len(FORWARD_SEQUENCE):
            return FORWARD_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None


def fail(session: Session, test_run: TestRunORM, error_message: str) -> None:
    """Transition to failed state with error message."""
    test_run.error_message = error_message
    transition(session, test_run, TestRunState.failed)


def update_substates(
    session: Session,
    test_run: TestRunORM,
    snapshot_num: Optional[int] = None,
    load_profile_id: Optional[int] = None,
    cycle_number: Optional[int] = None,
) -> None:
    """Update executing substates on the test run."""
    if snapshot_num is not None:
        test_run.current_snapshot_num = snapshot_num
    if load_profile_id is not None:
        test_run.current_load_profile_id = load_profile_id
    if cycle_number is not None:
        test_run.current_cycle_number = cycle_number
    session.commit()
