"""Test Run API endpoints (user-facing).

Create, list, get, add targets, start, pause, resume, cancel test runs.
Requires authenticated user (not necessarily admin).
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from orchestrator.api.schemas import (
    CalibrationResultResponse,
    ComparisonResultResponse,
    PhaseExecutionResultResponse,
    TestRunCreate,
    TestRunResponse,
    TestRunTargetCreate,
    TestRunTargetResponse,
)
from orchestrator.models.database import get_session
from orchestrator.models.enums import TestRunState
from orchestrator.models.orm import (
    CalibrationResultORM,
    ComparisonResultORM,
    PhaseExecutionResultORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
    UserORM,
)
from orchestrator.services.auth import get_current_user

router = APIRouter(prefix="/api/test-runs", tags=["test-runs"], dependencies=[Depends(get_current_user)])


@router.post("", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
def create_test_run(data: TestRunCreate, session: Session = Depends(get_session)):
    """Create a new test run with selected load profiles."""
    test_run = TestRunORM(
        scenario_id=data.scenario_id,
        lab_id=data.lab_id,
        cycles_per_profile=data.cycles_per_profile,
        run_mode=data.run_mode,
    )
    session.add(test_run)
    session.flush()  # get test_run.id

    for lp_id in data.load_profile_ids:
        session.add(TestRunLoadProfileORM(
            test_run_id=test_run.id,
            load_profile_id=lp_id,
        ))

    session.commit()
    session.refresh(test_run)
    return test_run


@router.get("", response_model=List[TestRunResponse])
def list_test_runs(
    scenario_id: int = None,
    state: TestRunState = None,
    session: Session = Depends(get_session),
):
    """List test runs with optional filters."""
    q = session.query(TestRunORM)
    if scenario_id is not None:
        q = q.filter(TestRunORM.scenario_id == scenario_id)
    if state is not None:
        q = q.filter(TestRunORM.state == state)
    return q.order_by(TestRunORM.created_at.desc()).all()


@router.get("/{run_id}", response_model=TestRunResponse)
def get_test_run(run_id: int, session: Session = Depends(get_session)):
    obj = session.get(TestRunORM, run_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Test run not found")
    return obj


# ---- Targets ----

@router.post("/{run_id}/targets", response_model=TestRunTargetResponse, status_code=status.HTTP_201_CREATED)
def add_target(run_id: int, data: TestRunTargetCreate, session: Session = Depends(get_session)):
    """Add a target server to a test run."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")
    if test_run.state != TestRunState.created:
        raise HTTPException(status_code=400, detail="Can only add targets to test runs in 'created' state")

    target = TestRunTargetORM(
        test_run_id=run_id,
        **data.model_dump(),
    )
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


@router.get("/{run_id}/targets", response_model=List[TestRunTargetResponse])
def list_targets(run_id: int, session: Session = Depends(get_session)):
    return session.query(TestRunTargetORM).filter(
        TestRunTargetORM.test_run_id == run_id
    ).all()


@router.delete("/{run_id}/targets/{target_config_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_target(run_id: int, target_config_id: int, session: Session = Depends(get_session)):
    """Remove a target from a test run (only in 'created' state)."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")
    if test_run.state != TestRunState.created:
        raise HTTPException(status_code=400, detail="Can only remove targets from test runs in 'created' state")

    obj = session.get(TestRunTargetORM, target_config_id)
    if not obj or obj.test_run_id != run_id:
        raise HTTPException(status_code=404, detail="Target not found in this test run")
    session.delete(obj)
    session.commit()


# ---- Actions ----

@router.post("/{run_id}/start", response_model=TestRunResponse)
def start_test_run(run_id: int, session: Session = Depends(get_session)):
    """Start a test run (transitions from 'created' to 'validating')."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")
    if test_run.state != TestRunState.created:
        raise HTTPException(status_code=400, detail=f"Cannot start test run in state '{test_run.state.value}'")

    # Verify at least one target and one load profile
    targets = session.query(TestRunTargetORM).filter(TestRunTargetORM.test_run_id == run_id).count()
    profiles = session.query(TestRunLoadProfileORM).filter(TestRunLoadProfileORM.test_run_id == run_id).count()
    if targets == 0:
        raise HTTPException(status_code=400, detail="No targets configured for this test run")
    if profiles == 0:
        raise HTTPException(status_code=400, detail="No load profiles selected for this test run")

    test_run.state = TestRunState.validating
    session.commit()
    session.refresh(test_run)
    return test_run


@router.post("/{run_id}/pause", response_model=TestRunResponse)
def pause_test_run(run_id: int, session: Session = Depends(get_session)):
    """Pause a running test run (takes effect at next state/substate boundary)."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")

    non_pausable = {TestRunState.created, TestRunState.completed, TestRunState.cancelled, TestRunState.failed, TestRunState.paused}
    if test_run.state in non_pausable:
        raise HTTPException(status_code=400, detail=f"Cannot pause test run in state '{test_run.state.value}'")

    test_run.state = TestRunState.paused
    session.commit()
    session.refresh(test_run)
    return test_run


@router.post("/{run_id}/resume", response_model=TestRunResponse)
def resume_test_run(run_id: int, session: Session = Depends(get_session)):
    """Resume a paused test run."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")
    if test_run.state != TestRunState.paused:
        raise HTTPException(status_code=400, detail="Test run is not paused")

    # Resume to executing state (orchestrator engine will determine exact substate)
    test_run.state = TestRunState.executing
    session.commit()
    session.refresh(test_run)
    return test_run


@router.post("/{run_id}/cancel", response_model=TestRunResponse)
def cancel_test_run(run_id: int, session: Session = Depends(get_session)):
    """Cancel a test run immediately."""
    test_run = session.get(TestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Test run not found")

    terminal = {TestRunState.completed, TestRunState.cancelled, TestRunState.failed}
    if test_run.state in terminal:
        raise HTTPException(status_code=400, detail=f"Cannot cancel test run in state '{test_run.state.value}'")

    test_run.state = TestRunState.cancelled
    session.commit()
    session.refresh(test_run)
    return test_run


# ---- Results (read-only) ----

@router.get("/{run_id}/calibration-results", response_model=List[CalibrationResultResponse])
def list_calibration_results(run_id: int, session: Session = Depends(get_session)):
    return session.query(CalibrationResultORM).filter(
        CalibrationResultORM.test_run_id == run_id
    ).all()


@router.get("/{run_id}/phase-results", response_model=List[PhaseExecutionResultResponse])
def list_phase_results(run_id: int, session: Session = Depends(get_session)):
    return session.query(PhaseExecutionResultORM).filter(
        PhaseExecutionResultORM.test_run_id == run_id
    ).all()


@router.get("/{run_id}/comparison-results", response_model=List[ComparisonResultResponse])
def list_comparison_results(run_id: int, session: Session = Depends(get_session)):
    return session.query(ComparisonResultORM).filter(
        ComparisonResultORM.test_run_id == run_id
    ).all()
