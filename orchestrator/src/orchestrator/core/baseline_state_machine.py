"""Baseline-compare test run state machine.

Manages state transitions for BaselineTestRunORM. Separate from the
live-compare state machine to avoid coupling.

State flows per test type:
  new_baseline:       created -> validating -> deploying_loadgen -> deploying_calibration
                      -> calibrating -> generating -> deploying_testing -> executing
                      -> storing -> completed
  compare:            created -> validating -> deploying_loadgen -> deploying_testing
                      -> executing -> comparing -> storing -> completed
  compare_with_new_calibration:
                      created -> validating -> deploying_loadgen -> deploying_calibration
                      -> calibrating -> generating -> deploying_testing -> executing
                      -> comparing -> storing -> completed
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from orchestrator.models.enums import BaselineTestState
from orchestrator.models.orm import BaselineTestRunORM

logger = logging.getLogger(__name__)

# Valid state transitions — union of all test type paths + cycle loops
BASELINE_TRANSITIONS = {
    BaselineTestState.created: [
        BaselineTestState.validating,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.validating: [
        BaselineTestState.deploying_loadgen,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.deploying_loadgen: [
        BaselineTestState.deploying_calibration,  # new_baseline / compare_with_new_cal
        BaselineTestState.deploying_testing,      # compare (skip calibration)
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.deploying_calibration: [
        BaselineTestState.calibrating,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.calibrating: [
        BaselineTestState.generating,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.generating: [
        BaselineTestState.deploying_calibration,  # next calibration LP
        BaselineTestState.deploying_testing,      # all cal LPs done -> first test LP
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.deploying_testing: [
        BaselineTestState.executing,
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.executing: [
        BaselineTestState.deploying_testing,  # next cycle or next LP
        BaselineTestState.storing,            # new_baseline: all done
        BaselineTestState.comparing,          # compare types: all done
        BaselineTestState.failed,
        BaselineTestState.cancelled,
    ],
    BaselineTestState.comparing: [
        BaselineTestState.storing,
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


# Retry resume mapping: failed_at_state -> resume_state.
# Work states resume at their deploy state (machine is dirty).
# Deploy/non-machine states resume at themselves.
RETRY_RESUME_STATE = {
    # Initial -> resume at itself (can't normally fail here, but defensive)
    BaselineTestState.created:                BaselineTestState.created,

    # Pre-flight -> resume at itself
    BaselineTestState.validating:             BaselineTestState.validating,

    # Deploy states -> resume at themselves
    BaselineTestState.deploying_loadgen:      BaselineTestState.deploying_loadgen,
    BaselineTestState.deploying_calibration:  BaselineTestState.deploying_loadgen,
    BaselineTestState.deploying_testing:      BaselineTestState.deploying_testing,

    # Calibration failure -> restart from loadgen deploy (JMeter may be missing)
    BaselineTestState.calibrating:            BaselineTestState.deploying_loadgen,
    BaselineTestState.executing:              BaselineTestState.deploying_testing,

    # Non-machine states -> resume at themselves
    BaselineTestState.generating:             BaselineTestState.generating,
    BaselineTestState.comparing:              BaselineTestState.comparing,
    BaselineTestState.storing:                BaselineTestState.storing,
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
    """Transition to failed state with error message.

    Records failed_at_state before transitioning so retry knows where to resume.
    Also marks any in-progress calibration records as failed.
    """
    from orchestrator.models.orm import CalibrationResultORM

    # Save the current state before transitioning to failed
    failed_at = test_run.state
    # Must set error_message after transition() calls session.refresh(),
    # otherwise refresh wipes the uncommitted in-memory change.
    transition(session, test_run, BaselineTestState.failed)
    test_run.failed_at_state = failed_at.value if hasattr(failed_at, 'value') else str(failed_at)
    test_run.error_message = error_message

    # Clean up any in-progress calibration records
    stale_cals = session.query(CalibrationResultORM).filter(
        CalibrationResultORM.baseline_test_run_id == test_run.id,
        CalibrationResultORM.status == "in_progress",
    ).all()
    for cal in stale_cals:
        cal.status = "failed"
        cal.error_message = f"Test run failed: {error_message}"
    session.commit()


def update_current_profile(
    session: Session,
    test_run: BaselineTestRunORM,
    load_profile_id: int,
) -> None:
    """Update the current load profile being processed."""
    test_run.current_load_profile_id = load_profile_id
    session.commit()


def update_current_cycle(
    session: Session,
    test_run: BaselineTestRunORM,
    cycle: int,
) -> None:
    """Update the current cycle number."""
    test_run.current_cycle = cycle
    session.commit()
