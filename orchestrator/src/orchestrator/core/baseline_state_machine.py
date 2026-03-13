"""Baseline-compare test run state machine.

Manages state transitions for BaselineTestRunORM. Separate from the
live-compare state machine to avoid coupling.

State flows per test type:
  new_baseline:       created -> validating -> setting_up -> calibrating -> generating
                      -> executing -> storing -> completed
  compare:            created -> validating -> setting_up -> executing -> comparing
                      -> storing -> completed
  compare_with_new_calibration:
                      created -> validating -> setting_up -> calibrating -> generating
                      -> executing -> comparing -> storing -> completed
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from orchestrator.models.enums import BaselineTestState
from orchestrator.models.orm import BaselineTestRunORM

logger = logging.getLogger(__name__)

# Valid state transitions — union of all test type paths
BASELINE_TRANSITIONS = {
    BaselineTestState.created: [
        BaselineTestState.validating,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.validating: [
        BaselineTestState.setting_up,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.setting_up: [
        BaselineTestState.calibrating,   # new_baseline / compare_with_new_calibration
        BaselineTestState.executing,     # compare (skip calibration)
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.calibrating: [
        BaselineTestState.generating,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.generating: [
        BaselineTestState.executing,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.executing: [
        BaselineTestState.storing,       # new_baseline (no comparison)
        BaselineTestState.comparing,     # compare / compare_with_new_calibration
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.comparing: [
        BaselineTestState.storing,       # compare_with_new_calibration stores after comparing
        BaselineTestState.completed,     # compare finishes after comparing
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.storing: [
        BaselineTestState.completed,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.completed: [],
    BaselineTestState.failed: [],
    BaselineTestState.cancelled: [],
}


def transition(
    session: Session,
    test_run: BaselineTestRunORM,
    target_state: BaselineTestState,
) -> None:
    """Transition a baseline test run to a new state.

    Args:
        session: DB session
        test_run: BaselineTestRunORM instance
        target_state: desired state

    Raises:
        ValueError: if transition is invalid
    """
    session.refresh(test_run)
    current = test_run.state
    allowed = BASELINE_TRANSITIONS.get(current, [])

    if current == target_state:
        return

    if target_state not in allowed:
        raise ValueError(
            f"Invalid baseline transition: {current.value} -> {target_state.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )

    logger.info(
        "BaselineTestRun %d: %s -> %s",
        test_run.id, current.value, target_state.value,
    )
    test_run.state = target_state

    if target_state == BaselineTestState.validating and test_run.started_at is None:
        test_run.started_at = datetime.utcnow()

    if target_state in (
        BaselineTestState.completed,
        BaselineTestState.cancelled,
        BaselineTestState.failed,
    ):
        test_run.completed_at = datetime.utcnow()

    session.commit()


def fail(
    session: Session,
    test_run: BaselineTestRunORM,
    error_message: str,
) -> None:
    """Transition to failed state with error message."""
    # Must set error_message after transition() calls session.refresh(),
    # otherwise refresh wipes the uncommitted in-memory change.
    transition(session, test_run, BaselineTestState.failed)
    test_run.error_message = error_message
    session.commit()


def update_current_profile(
    session: Session,
    test_run: BaselineTestRunORM,
    load_profile_id: int,
) -> None:
    """Update the current load profile being processed."""
    test_run.current_load_profile_id = load_profile_id
    session.commit()
