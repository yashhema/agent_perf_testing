"""Baseline Test Run API endpoints.

Create, list, get, start baseline-compare test runs.
Also provides snapshot management endpoints for servers.
"""

import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from orchestrator.api.schemas import (
    BaselineTestRunCreate,
    BaselineTestRunCreateV2,
    BaselineTestRunResponse,
    BaselineTestRunUpdate,
    ComparisonResultResponse,
    DeleteSnapshotRequest,
    SnapshotBaselineCreate,
    SnapshotBaselineResponse,
    SnapshotGroupCreate,
    SnapshotGroupResponse,
    SnapshotProfileDataResponse,
    SnapshotResponse,
    SnapshotTreeNode,
    TakeSnapshotRequest,
    ValidateSnapshotResponse,
)
from orchestrator.models.database import SessionLocal, get_session
from orchestrator.models.enums import BaselineTestState, BaselineTestType, ExecutionMode
from orchestrator.models.orm import (
    BaselineTestRunLoadProfileORM,
    BaselineTestRunORM,
    BaselineTestRunTargetORM,
    CalibrationResultORM,
    ComparisonResultORM,
    LabORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    SnapshotBaselineORM,
    SnapshotGroupORM,
    SnapshotORM,
    SnapshotProfileDataORM,
    UserORM,
)
from orchestrator.services.auth import get_current_user

router = APIRouter(
    prefix="/api/baseline-tests",
    tags=["baseline-tests"],
    dependencies=[Depends(get_current_user)],
)

snapshot_router = APIRouter(
    prefix="/api/servers",
    tags=["snapshots"],
    dependencies=[Depends(get_current_user)],
)


# ===========================================================================
# Baseline Test Run Endpoints
# ===========================================================================

@router.post("", response_model=BaselineTestRunResponse, status_code=status.HTTP_201_CREATED)
def create_baseline_test_run(
    data: BaselineTestRunCreate,
    session: Session = Depends(get_session),
):
    """Create a new baseline-compare test run with one or more targets."""
    # Validate all targets and resolve defaults
    target_orms = []
    lab = None
    for entry in data.targets:
        server = session.get(ServerORM, entry.server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Server {entry.server_id} not found")

        if lab is None:
            lab = session.get(LabORM, server.lab_id)
            if lab.execution_mode != ExecutionMode.baseline_compare:
                raise HTTPException(
                    status_code=400,
                    detail=f"Lab '{lab.name}' is in '{lab.execution_mode.value}' mode, "
                           f"not baseline_compare",
                )
        elif server.lab_id != lab.id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id} belongs to a different lab",
            )

        loadgen_id = entry.loadgenerator_id or server.default_loadgen_id
        if not loadgen_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id}: no loadgenerator_id and no default_loadgen_id",
            )
        partner_id = entry.partner_id or server.default_partner_id
        monitor_patterns = entry.service_monitor_patterns or server.service_monitor_patterns

        # Validate test_type + compare_snapshot_id consistency
        if data.test_type == BaselineTestType.new_baseline and entry.compare_snapshot_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id}: new_baseline should not have compare_snapshot_id",
            )
        if data.test_type != BaselineTestType.new_baseline and not entry.compare_snapshot_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id}: {data.test_type.value} requires compare_snapshot_id",
            )

        target_orms.append(BaselineTestRunTargetORM(
            target_id=entry.server_id,
            loadgenerator_id=loadgen_id,
            partner_id=partner_id,
            test_snapshot_id=entry.test_snapshot_id,
            compare_snapshot_id=entry.compare_snapshot_id,
            service_monitor_patterns=monitor_patterns,
        ))

    test_run = BaselineTestRunORM(
        lab_id=lab.id,
        scenario_id=data.scenario_id,
        test_type=data.test_type,
        cycle_count=data.cycle_count,
    )
    session.add(test_run)
    session.flush()

    for target_orm in target_orms:
        target_orm.baseline_test_run_id = test_run.id
        session.add(target_orm)

    for lp_id in data.load_profile_ids:
        session.add(BaselineTestRunLoadProfileORM(
            baseline_test_run_id=test_run.id,
            load_profile_id=lp_id,
        ))

    session.commit()
    session.refresh(test_run)
    return test_run


@router.get("", response_model=List[BaselineTestRunResponse])
def list_baseline_test_runs(
    server_id: Optional[int] = None,
    state: Optional[BaselineTestState] = None,
    session: Session = Depends(get_session),
):
    """List baseline test runs with optional filters."""
    q = session.query(BaselineTestRunORM)
    if server_id is not None:
        q = q.join(BaselineTestRunTargetORM).filter(
            BaselineTestRunTargetORM.target_id == server_id,
        )
    if state is not None:
        q = q.filter(BaselineTestRunORM.state == state)
    return q.order_by(BaselineTestRunORM.created_at.desc()).all()


@router.get("/{run_id}", response_model=BaselineTestRunResponse)
def get_baseline_test_run(run_id: int, session: Session = Depends(get_session)):
    obj = session.get(BaselineTestRunORM, run_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Baseline test run not found")
    return obj


@router.post("/{run_id}/start")
def start_baseline_test_run(run_id: int, session: Session = Depends(get_session)):
    """Start executing a baseline test run in background."""
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")
    if test_run.state != BaselineTestState.created:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start: current state is '{test_run.state.value}'",
        )

    def _run_in_background(test_run_id: int):
        from orchestrator.app import app_config, credentials
        from orchestrator.core.baseline_orchestrator import BaselineOrchestrator

        db_session = SessionLocal()
        try:
            orchestrator = BaselineOrchestrator(app_config, credentials)
            orchestrator.run(db_session, test_run_id)
        finally:
            db_session.close()

    thread = threading.Thread(
        target=_run_in_background,
        args=(run_id,),
        daemon=True,
    )
    thread.start()

    return {"message": f"Baseline test run {run_id} started", "state": test_run.state.value}


@router.post("/{run_id}/retry")
def retry_baseline_test_run(run_id: int, session: Session = Depends(get_session)):
    """Retry a failed baseline test run using per-cycle clean slate retry.

    Uses RETRY_RESUME_STATE mapping to determine where to resume.
    Resets ALL targets to pending (not just failed ones).
    Preserves current_load_profile_id and current_cycle.
    """
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")
    if test_run.state != BaselineTestState.failed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry: current state is '{test_run.state.value}' (must be 'failed')",
        )

    from orchestrator.core.baseline_state_machine import RETRY_RESUME_STATE
    from orchestrator.models.enums import BaselineTargetState

    # Determine resume state from failed_at_state
    if not test_run.failed_at_state:
        raise HTTPException(
            status_code=400,
            detail="Cannot retry: failed_at_state not recorded (test may have failed before state machine redesign)",
        )

    try:
        failed_at = BaselineTestState(test_run.failed_at_state)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry: unrecognized failed_at_state '{test_run.failed_at_state}'",
        )

    resume_state = RETRY_RESUME_STATE.get(failed_at)
    if resume_state is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry: no resume mapping for failed_at_state '{test_run.failed_at_state}'",
        )

    # Reset ALL targets to pending (clean slate for the cycle)
    targets = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
    ).all()
    for t in targets:
        t.state = BaselineTargetState.pending
        t.error_message = None

    # Set test to resume state (LP + cycle preserved)
    test_run.state = resume_state
    test_run.error_message = None
    test_run.failed_at_state = None
    session.commit()

    # Get current LP name for message
    current_lp_name = "unknown"
    if test_run.current_load_profile_id:
        lp = session.get(LoadProfileORM, test_run.current_load_profile_id)
        if lp:
            current_lp_name = lp.name

    # Start in background
    def _run_in_background(test_run_id: int):
        from orchestrator.app import app_config, credentials
        from orchestrator.core.baseline_orchestrator import BaselineOrchestrator
        db_session = SessionLocal()
        try:
            orchestrator = BaselineOrchestrator(app_config, credentials)
            orchestrator.run(db_session, test_run_id)
        finally:
            db_session.close()

    thread = threading.Thread(
        target=_run_in_background,
        args=(run_id,),
        daemon=True,
    )
    thread.start()

    return {
        "message": f"Retrying from {resume_state.value} [LP={current_lp_name}, cycle={test_run.current_cycle}]",
        "resume_state": resume_state.value,
        "current_lp": current_lp_name,
        "current_cycle": test_run.current_cycle,
    }


@router.get("/{run_id}/calibration-progress")
def get_calibration_progress(run_id: int, session: Session = Depends(get_session)):
    """Get live calibration progress for all targets in a baseline test run."""
    results = session.query(CalibrationResultORM).filter(
        CalibrationResultORM.baseline_test_run_id == run_id,
    ).all()
    out = []
    for r in results:
        server = session.get(ServerORM, r.server_id)
        lp = session.get(LoadProfileORM, r.load_profile_id)
        out.append({
            "id": r.id,
            "server_id": r.server_id,
            "server_hostname": server.hostname if server else "unknown",
            "load_profile": lp.name if lp else "unknown",
            "status": r.status,
            "phase": r.phase,
            "thread_count": r.thread_count,
            "current_thread_count": r.current_thread_count,
            "current_iteration": r.current_iteration,
            "last_observed_cpu": r.last_observed_cpu,
            "target_cpu_min": r.target_cpu_min,
            "target_cpu_max": r.target_cpu_max,
            "stability_check_num": r.stability_check_num,
            "stability_checks_total": r.stability_checks_total,
            "stability_pct_in_range": r.stability_pct_in_range,
            "stability_attempt": r.stability_attempt,
            "message": r.message,
            "error_message": r.error_message,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


@router.post("/{run_id}/sanity-check")
def sanity_check_baseline_test_run(run_id: int, session: Session = Depends(get_session)):
    """Run pre-flight, connectivity, and dirty-state checks without starting the test.

    Returns a report of all checks with pass/fail/warn status.
    Can be run in any non-terminal state.
    """
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")

    terminal = {BaselineTestState.completed, BaselineTestState.cancelled}
    if test_run.state in terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot run sanity check: test is in terminal state '{test_run.state.value}'",
        )

    from orchestrator.app import app_config, credentials
    from orchestrator.core.baseline_orchestrator import BaselineOrchestrator

    orchestrator = BaselineOrchestrator(app_config, credentials)
    result = orchestrator.sanity_check(session, run_id)

    return result


@router.post("/{run_id}/cancel")
def cancel_baseline_test_run(run_id: int, session: Session = Depends(get_session)):
    """Cancel a running baseline test run."""
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")

    terminal = {BaselineTestState.completed, BaselineTestState.failed, BaselineTestState.cancelled}
    if test_run.state in terminal:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel: already in terminal state '{test_run.state.value}'",
        )

    from orchestrator.core import baseline_state_machine as sm
    sm.transition(session, test_run, BaselineTestState.cancelled)
    return {"message": f"Baseline test run {run_id} cancelled"}


@router.get("/{run_id}/comparison-results", response_model=List[ComparisonResultResponse])
def get_baseline_comparison_results(run_id: int, session: Session = Depends(get_session)):
    results = session.query(ComparisonResultORM).filter(
        ComparisonResultORM.baseline_test_run_id == run_id,
    ).all()
    return results


# ===========================================================================
# V2 Endpoints — Test Run = Test Case (auto-creates scenario)
# ===========================================================================

@router.post("/v2", response_model=BaselineTestRunResponse, status_code=status.HTTP_201_CREATED)
def create_baseline_test_run_v2(
    data: BaselineTestRunCreateV2,
    session: Session = Depends(get_session),
):
    """Create a baseline test run with inline configuration.

    Auto-creates a ScenarioORM behind the scenes so the execution engine
    (which uses scenario.template_type in ~12 places) keeps working unchanged.

    For compare modes (parent_run_id set): copies scenario_id and load profiles
    from parent, auto-fills compare_snapshot_id from parent's test_snapshot_id.
    """
    from datetime import datetime as dt

    # --- Validate targets and resolve lab ---
    target_orms = []
    lab = None
    for entry in data.targets:
        server = session.get(ServerORM, entry.server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Server {entry.server_id} not found")

        if lab is None:
            lab = session.get(LabORM, server.lab_id)
            if lab.execution_mode != ExecutionMode.baseline_compare:
                raise HTTPException(
                    status_code=400,
                    detail=f"Lab '{lab.name}' is not in baseline_compare mode",
                )
        elif server.lab_id != lab.id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id} belongs to a different lab",
            )

        loadgen_id = entry.loadgenerator_id or server.default_loadgen_id
        if not loadgen_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {entry.server_id}: no loadgenerator_id and no default_loadgen_id",
            )
        # Simplification: partner = loadgen
        partner_id = loadgen_id
        monitor_patterns = entry.service_monitor_patterns or server.service_monitor_patterns

        target_orms.append(BaselineTestRunTargetORM(
            target_id=entry.server_id,
            loadgenerator_id=loadgen_id,
            partner_id=partner_id,
            test_snapshot_id=entry.test_snapshot_id,
            compare_snapshot_id=entry.compare_snapshot_id,
            service_monitor_patterns=monitor_patterns,
        ))

    # --- Compare mode: validate parent and inherit config ---
    scenario_id = None
    lp_entries = data.load_profiles

    if data.parent_run_id is not None:
        parent = session.get(BaselineTestRunORM, data.parent_run_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Parent run {data.parent_run_id} not found")
        if parent.state != BaselineTestState.completed:
            raise HTTPException(
                status_code=400,
                detail=f"Parent run {data.parent_run_id} is not completed (state={parent.state.value})",
            )

        # Reuse scenario from parent (don't recreate)
        scenario_id = parent.scenario_id

        # Copy load profiles + duration overrides from parent (locked)
        parent_lp_links = session.query(BaselineTestRunLoadProfileORM).filter(
            BaselineTestRunLoadProfileORM.baseline_test_run_id == parent.id,
        ).all()
        lp_entries = []
        from orchestrator.api.schemas import BaselineTestRunLoadProfileEntry
        for plpl in parent_lp_links:
            lp_entries.append(BaselineTestRunLoadProfileEntry(
                load_profile_id=plpl.load_profile_id,
                duration_sec=plpl.duration_sec,
                ramp_up_sec=plpl.ramp_up_sec,
            ))

        # Auto-fill compare_snapshot_id from parent's test_snapshot_id per target
        parent_targets = session.query(BaselineTestRunTargetORM).filter(
            BaselineTestRunTargetORM.baseline_test_run_id == parent.id,
        ).all()
        parent_target_map = {pt.target_id: pt for pt in parent_targets}

        for t_orm in target_orms:
            parent_target = parent_target_map.get(t_orm.target_id)
            if parent_target:
                t_orm.compare_snapshot_id = parent_target.test_snapshot_id

    # --- Auto-create scenario if not inherited from parent ---
    if scenario_id is None:
        timestamp = dt.utcnow().strftime("%Y%m%d_%H%M%S")
        auto_scenario = ScenarioORM(
            name=f"auto_{data.name}_{timestamp}",
            lab_id=lab.id,
            template_type=data.template_type,
            has_base_phase=True,
            has_initial_phase=False,
            has_dbtest=(data.template_type.value == "db-load"),
            load_generator_package_grp_id=lab.jmeter_package_grpid,
            stress_test_enabled=data.stress_test_enabled,
            network_degradation_enabled=data.network_degradation_enabled,
        )
        session.add(auto_scenario)
        session.flush()
        scenario_id = auto_scenario.id

    # --- Validate test_type + compare_snapshot_id consistency ---
    for t_orm in target_orms:
        if data.test_type == BaselineTestType.new_baseline and t_orm.compare_snapshot_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {t_orm.target_id}: new_baseline should not have compare_snapshot_id",
            )
        if data.test_type != BaselineTestType.new_baseline and not t_orm.compare_snapshot_id:
            raise HTTPException(
                status_code=400,
                detail=f"Server {t_orm.target_id}: {data.test_type.value} requires compare_snapshot_id",
            )

    # --- Create the test run ---
    test_run = BaselineTestRunORM(
        name=data.name,
        description=data.description,
        lab_id=lab.id,
        scenario_id=scenario_id,
        test_type=data.test_type,
        parent_run_id=data.parent_run_id,
        cycle_count=data.cycle_count,
    )
    session.add(test_run)
    session.flush()

    for t_orm in target_orms:
        t_orm.baseline_test_run_id = test_run.id
        session.add(t_orm)

    for lp_entry in lp_entries:
        session.add(BaselineTestRunLoadProfileORM(
            baseline_test_run_id=test_run.id,
            load_profile_id=lp_entry.load_profile_id,
            duration_sec=lp_entry.duration_sec,
            ramp_up_sec=lp_entry.ramp_up_sec,
        ))

    session.commit()
    session.refresh(test_run)
    return test_run


@router.put("/{run_id}", response_model=BaselineTestRunResponse)
def update_baseline_test_run(
    run_id: int,
    data: BaselineTestRunUpdate,
    session: Session = Depends(get_session),
):
    """Update a baseline test run (name/description only, state=created only)."""
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")
    if test_run.state != BaselineTestState.created:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit: current state is '{test_run.state.value}' (must be 'created')",
        )

    if data.name is not None:
        test_run.name = data.name
    if data.description is not None:
        test_run.description = data.description

    session.commit()
    session.refresh(test_run)
    return test_run


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_baseline_test_run(
    run_id: int,
    session: Session = Depends(get_session),
):
    """Delete a baseline test run (state=created only). Cascades to targets + load profiles."""
    test_run = session.get(BaselineTestRunORM, run_id)
    if not test_run:
        raise HTTPException(status_code=404, detail="Baseline test run not found")
    if test_run.state != BaselineTestState.created:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: current state is '{test_run.state.value}' (must be 'created')",
        )

    session.delete(test_run)
    session.commit()


# ===========================================================================
# Snapshot Management Endpoints
# ===========================================================================

@snapshot_router.get("/{server_id}/snapshots", response_model=List[SnapshotResponse])
def list_snapshots(server_id: int, session: Session = Depends(get_session)):
    """List all snapshots for a server."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server_id,
    ).order_by(SnapshotORM.created_at).all()


@snapshot_router.get("/{server_id}/snapshots/tree")
def get_snapshot_tree(server_id: int, session: Session = Depends(get_session)):
    """Get the snapshot tree for a server as a nested structure."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    snapshots = session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server_id,
    ).all()

    # Build tree
    by_id = {s.id: s for s in snapshots}
    children_map = {}
    roots = []
    for s in snapshots:
        children_map.setdefault(s.id, [])
        if s.parent_id is None or s.parent_id not in by_id:
            roots.append(s)
        else:
            children_map.setdefault(s.parent_id, []).append(s)

    def build_node(snap: SnapshotORM) -> dict:
        has_data = len(snap.profile_data) > 0 if snap.profile_data else False
        return {
            "id": snap.id,
            "name": snap.name,
            "description": snap.description,
            "is_baseline": snap.is_baseline,
            "is_archived": snap.is_archived,
            "has_data": has_data,
            "group_id": snap.group_id,
            "group_name": snap.group.name if snap.group else None,
            "children": [build_node(c) for c in children_map.get(snap.id, [])],
        }

    return [build_node(r) for r in roots]


@snapshot_router.post("/{server_id}/snapshots/sync", response_model=List[SnapshotResponse])
def sync_snapshot_tree(server_id: int, session: Session = Depends(get_session)):
    """Sync snapshot tree from hypervisor to DB."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    try:
        return mgr.sync_tree(session, server, lab)
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Sync conflict (possible concurrent sync): {e}",
        )


@snapshot_router.post("/{server_id}/snapshots/take", response_model=SnapshotResponse)
def take_snapshot(
    server_id: int,
    data: TakeSnapshotRequest,
    session: Session = Depends(get_session),
):
    """Take a new snapshot on the hypervisor and register in DB."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    lab = session.get(LabORM, server.lab_id)

    # Validate group_id if provided
    if data.group_id is not None:
        group = session.get(SnapshotGroupORM, data.group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Snapshot group not found")
        # Validate the group belongs to this server's baseline
        baseline = session.get(SnapshotBaselineORM, group.baseline_id)
        if not baseline or baseline.server_id != server_id:
            raise HTTPException(
                status_code=400,
                detail="Snapshot group does not belong to this server",
            )

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    snap = mgr.take_snapshot(
        session, server, lab, name=data.name, description=data.description or "",
    )
    if not snap:
        raise HTTPException(status_code=500, detail="Failed to create snapshot")

    # Set group_id if provided
    if data.group_id is not None:
        snap.group_id = data.group_id

    # Capture snapshot tree at time of creation
    provider = mgr._get_provider(lab)
    snap.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]

    session.commit()
    session.refresh(snap)
    return snap


@snapshot_router.post("/{server_id}/snapshots/delete")
def delete_snapshot(
    server_id: int,
    data: DeleteSnapshotRequest,
    session: Session = Depends(get_session),
):
    """Delete a snapshot from hypervisor (archives in DB)."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    snapshot = session.get(SnapshotORM, data.snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")
    if snapshot.is_archived:
        raise HTTPException(status_code=400, detail="Snapshot already archived")

    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    mgr.delete_snapshot(session, server, lab, snapshot)
    return {"message": f"Snapshot '{snapshot.name}' deleted and archived"}


@snapshot_router.post("/{server_id}/snapshots/{snapshot_id}/revert")
def revert_to_snapshot(
    server_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    """Revert VM to a specific snapshot."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    snapshot = session.get(SnapshotORM, snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")
    if snapshot.is_archived:
        raise HTTPException(status_code=400, detail="Cannot revert to archived snapshot")

    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    new_ip = mgr.revert_snapshot(server, lab, snapshot)
    if new_ip and new_ip != server.ip_address:
        server.ip_address = new_ip
        session.commit()

    return {"message": f"VM reverted to snapshot '{snapshot.name}'"}


@snapshot_router.post("/{server_id}/snapshots/{snapshot_id}/retake")
def retake_snapshot(
    server_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    """Retake a dirty snapshot: revert to parent, cleanup, delete old, take new.

    Updates the EXISTING snapshot record in-place (same ID, same group, same
    test run references). Only provider_ref and provider_snapshot_id change.

    Flow:
    1. Revert VM to the snapshot's parent (the clean base)
    2. Wait for VM ready
    3. Run cleanup commands on the VM (kill emulator, clean dirs)
    4. Delete the old snapshot on the hypervisor
    5. Take a new snapshot with the same name
    6. Update the existing DB record with new provider_ref/provider_snapshot_id
    """
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    snapshot = session.get(SnapshotORM, snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")
    if snapshot.is_archived:
        raise HTTPException(status_code=400, detail="Cannot retake an archived snapshot")

    # Must have a parent to revert to
    if not snapshot.parent_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot retake: snapshot has no parent to revert to. "
                   "This is a root snapshot — take a new one manually.",
        )
    parent = session.get(SnapshotORM, snapshot.parent_id)
    if not parent or parent.is_archived:
        raise HTTPException(status_code=400, detail="Parent snapshot is missing or archived")

    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    provider = mgr._get_provider(lab)

    # Step 1: Revert to parent (the clean base)
    new_ip = provider.restore_snapshot(server.server_infra_ref, parent.provider_ref)
    provider.wait_for_vm_ready(server.server_infra_ref)
    if new_ip and new_ip != server.ip_address:
        server.ip_address = new_ip
        session.commit()

    # Step 2: Wait for SSH/WinRM
    from orchestrator.core.baseline_execution import wait_for_ssh
    wait_for_ssh(server.ip_address, os_family=server.os_family.value, timeout_sec=120)

    # Step 3: Cleanup on the VM
    from orchestrator.infra.remote_executor import create_executor
    target_cred = credentials.get_server_credential(server.id, server.os_family.value)
    executor = create_executor(
        os_family=server.os_family.value,
        host=server.ip_address,
        username=target_cred.username,
        password=target_cred.password,
    )
    try:
        if server.os_family.value == "windows":
            executor.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
            executor.execute(
                'powershell -Command "'
                "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                '"'
            )
        else:
            executor.execute("sudo pkill -f emulator || true")
            executor.execute("sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/*")
    finally:
        executor.close()

    # Step 4: Delete old snapshot on hypervisor
    try:
        provider.delete_snapshot(server.server_infra_ref, snapshot.provider_ref)
    except Exception as e:
        # Non-fatal — old snapshot may already be gone
        pass

    # Step 5: Take new snapshot with same name
    result = provider.create_snapshot(
        server.server_infra_ref,
        snapshot_name=snapshot.name,
        description=snapshot.description or "",
    )
    # result: {"snapshot_moref_id": ...} for vSphere, {"snapshot_id": ...} for Vultr, etc.
    new_provider_snapshot_id = (
        result.get("snapshot_moref_id")
        or result.get("snapshot_id")
        or result.get("snapshot_name")
    )

    # Step 6: Update existing DB record in-place (no new record, no sync)
    snapshot.provider_snapshot_id = new_provider_snapshot_id
    snapshot.provider_ref = result
    snapshot.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
    # Preserve: id, name, description, server_id, parent_id, group_id, is_baseline, is_archived
    session.commit()
    session.refresh(snapshot)

    return {
        "message": f"Snapshot '{snapshot.name}' retaken successfully. "
                   f"Old provider_ref replaced. DB record ID {snapshot.id} preserved.",
        "snapshot_id": snapshot.id,
        "new_provider_snapshot_id": snapshot.provider_snapshot_id,
    }


@snapshot_router.get(
    "/{server_id}/snapshots/{snapshot_id}/profile-data",
    response_model=List[SnapshotProfileDataResponse],
)
def get_snapshot_profile_data(
    server_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    """Get stored profile data for a snapshot."""
    snapshot = session.get(SnapshotORM, snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")
    return session.query(SnapshotProfileDataORM).filter(
        SnapshotProfileDataORM.snapshot_id == snapshot_id,
    ).all()


@snapshot_router.post(
    "/{server_id}/snapshots/{snapshot_id}/validate",
    response_model=ValidateSnapshotResponse,
)
def validate_snapshot(
    server_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    """Validate that a snapshot still exists on the hypervisor."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    snapshot = session.get(SnapshotORM, snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")

    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    provider = mgr._get_provider(lab)
    exists = provider.snapshot_exists(server.server_infra_ref, snapshot.provider_ref)

    return ValidateSnapshotResponse(
        snapshot_id=snapshot.id,
        provider_snapshot_id=snapshot.provider_snapshot_id,
        exists_on_hypervisor=exists,
    )


# ===========================================================================
# Hypervisor Snapshot List (for pick-from-list UI)
# ===========================================================================

@snapshot_router.get("/{server_id}/hypervisor-snapshots")
def list_hypervisor_snapshots(
    server_id: int,
    parent_of: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """List snapshots currently on the hypervisor for this server.

    Args:
        parent_of: If provided, only return snapshots that are descendants of
                   this snapshot name (for hierarchy-validated subgroup picking).
    """
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    provider = mgr._get_provider(lab)
    hypervisor_snaps = provider.list_snapshots(server.server_infra_ref)

    # Convert HypervisorSnapshot dataclasses to dicts for response
    snap_dicts = [hs.to_dict() for hs in hypervisor_snaps]

    # If parent_of is set, filter to only descendants of that snapshot
    if parent_of:
        # Build parent->children map and find all descendants
        children_map = {}
        for sd in snap_dicts:
            p = sd.get("parent")
            if p:
                children_map.setdefault(p, []).append(sd["id"])

        def get_descendants(snap_id):
            result = set()
            for child in children_map.get(snap_id, []):
                result.add(child)
                result.update(get_descendants(child))
            return result

        valid_ids = get_descendants(parent_of)
        snap_dicts = [sd for sd in snap_dicts if sd["id"] in valid_ids]

    # Annotate each with whether it's already linked in DB
    db_snaps = session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server_id,
        SnapshotORM.is_archived == False,
    ).all()
    db_provider_ids = {s.provider_snapshot_id for s in db_snaps}
    db_provider_map = {s.provider_snapshot_id: s.id for s in db_snaps}

    for sd in snap_dicts:
        prov_id = sd["id"]
        sd["linked_in_db"] = prov_id in db_provider_ids
        sd["db_snapshot_id"] = db_provider_map.get(prov_id)

    return snap_dicts


# ===========================================================================
# Snapshot Group Endpoints (UI: "Group")
# ===========================================================================

@snapshot_router.get(
    "/{server_id}/snapshot-baselines",
    response_model=List[SnapshotBaselineResponse],
)
def list_snapshot_baselines(server_id: int, session: Session = Depends(get_session)):
    """List all baselines for a server."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return session.query(SnapshotBaselineORM).filter(
        SnapshotBaselineORM.server_id == server_id,
    ).order_by(SnapshotBaselineORM.created_at).all()


@snapshot_router.post(
    "/{server_id}/snapshot-baselines",
    response_model=SnapshotBaselineResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot_baseline(
    server_id: int,
    data: SnapshotBaselineCreate,
    session: Session = Depends(get_session),
):
    """Create a group: either takes a new snapshot or links an existing one,
    then auto-creates a default subgroup with the same snapshot linked."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)
    provider = mgr._get_provider(lab)

    if data.existing_snapshot_id:
        # Link to existing snapshot
        snap = session.get(SnapshotORM, data.existing_snapshot_id)
        if not snap or snap.server_id != server_id:
            raise HTTPException(status_code=404, detail="Snapshot not found for this server")
        snap.is_baseline = True
        snap.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
        session.flush()
    else:
        # Take new snapshot on hypervisor
        if not data.snapshot_name:
            raise HTTPException(status_code=400, detail="snapshot_name required when not using existing snapshot")
        snap = mgr.take_snapshot(
            session, server, lab,
            name=data.snapshot_name,
            description=data.description or "",
        )
        if not snap:
            raise HTTPException(status_code=500, detail="Failed to create group snapshot")
        snap.is_baseline = True
        snap.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
        session.flush()

    # Create group record (DB table: snapshot_baselines)
    baseline = SnapshotBaselineORM(
        server_id=server_id,
        snapshot_id=snap.id,
        name=data.name,
        description=data.description,
    )
    session.add(baseline)
    session.flush()

    # Auto-create default subgroup linked to the same snapshot
    default_subgroup = SnapshotGroupORM(
        baseline_id=baseline.id,
        snapshot_id=snap.id,
        name=f"{data.name}_default",
        description=f"Default subgroup for {data.name}",
    )
    session.add(default_subgroup)
    session.flush()  # Ensure default_subgroup.id is assigned before referencing it

    # Link the snapshot to the default subgroup
    snap.group_id = default_subgroup.id

    session.commit()
    session.refresh(baseline)
    return baseline


@snapshot_router.post(
    "/{server_id}/snapshot-baselines/{baseline_id}/revert",
)
def revert_to_baseline(
    server_id: int,
    baseline_id: int,
    session: Session = Depends(get_session),
):
    """Revert VM to a baseline snapshot."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    baseline = session.get(SnapshotBaselineORM, baseline_id)
    if not baseline or baseline.server_id != server_id:
        raise HTTPException(status_code=404, detail="Baseline not found for this server")

    snapshot = session.get(SnapshotORM, baseline.snapshot_id)
    if not snapshot or snapshot.is_archived:
        raise HTTPException(status_code=400, detail="Baseline snapshot is archived or missing")

    lab = session.get(LabORM, server.lab_id)

    from orchestrator.app import credentials
    from orchestrator.services.snapshot_manager import SnapshotManager

    mgr = SnapshotManager(credentials)

    # Validate snapshot exists on hypervisor before reverting
    provider = mgr._get_provider(lab)
    if not provider.snapshot_exists(server.server_infra_ref, snapshot.provider_ref):
        raise HTTPException(
            status_code=400,
            detail="Baseline snapshot no longer exists on hypervisor",
        )

    new_ip = mgr.revert_snapshot(server, lab, snapshot)
    if new_ip and new_ip != server.ip_address:
        server.ip_address = new_ip
        session.commit()

    return {"message": f"VM reverted to baseline '{baseline.name}'"}


@snapshot_router.delete(
    "/{server_id}/snapshot-baselines/{baseline_id}",
)
def delete_snapshot_baseline(
    server_id: int,
    baseline_id: int,
    session: Session = Depends(get_session),
):
    """Delete a group and all its subgroups. Snapshots are unlinked, not deleted."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    baseline = session.get(SnapshotBaselineORM, baseline_id)
    if not baseline or baseline.server_id != server_id:
        raise HTTPException(status_code=404, detail="Group not found for this server")

    # Unlink all snapshots from subgroups under this group
    subgroups = session.query(SnapshotGroupORM).filter(
        SnapshotGroupORM.baseline_id == baseline_id,
    ).all()
    for sg in subgroups:
        session.query(SnapshotORM).filter(
            SnapshotORM.group_id == sg.id,
        ).update({"group_id": None})
        session.delete(sg)

    session.delete(baseline)
    session.commit()
    return {"message": f"Group '{baseline.name}' deleted"}


# ===========================================================================
# Snapshot Group Endpoints
# ===========================================================================

@snapshot_router.get(
    "/{server_id}/snapshot-groups",
    response_model=List[SnapshotGroupResponse],
)
def list_snapshot_groups(
    server_id: int,
    baseline_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """List snapshot groups, optionally filtered by baseline."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    q = session.query(SnapshotGroupORM).join(SnapshotBaselineORM).filter(
        SnapshotBaselineORM.server_id == server_id,
    )
    if baseline_id is not None:
        q = q.filter(SnapshotGroupORM.baseline_id == baseline_id)
    return q.order_by(SnapshotGroupORM.created_at).all()


@snapshot_router.post(
    "/{server_id}/snapshot-groups",
    response_model=SnapshotGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot_group(
    server_id: int,
    data: SnapshotGroupCreate,
    session: Session = Depends(get_session),
):
    """Create a subgroup under a group.

    If existing_snapshot_id is provided, links to that snapshot.
    Otherwise takes a new snapshot on the hypervisor.
    """
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    baseline = session.get(SnapshotBaselineORM, data.baseline_id)
    if not baseline or baseline.server_id != server_id:
        raise HTTPException(status_code=404, detail="Group not found for this server")

    snapshot_id = None

    if data.existing_snapshot_id:
        # Link to an existing snapshot — validate it belongs to this server
        existing_snap = session.get(SnapshotORM, data.existing_snapshot_id)
        if not existing_snap or existing_snap.server_id != server_id:
            raise HTTPException(status_code=404, detail="Snapshot not found for this server")
        snapshot_id = existing_snap.id
    else:
        # Take a new snapshot on the hypervisor
        lab = session.get(LabORM, server.lab_id)

        from orchestrator.app import credentials
        from orchestrator.services.snapshot_manager import SnapshotManager

        mgr = SnapshotManager(credentials)

        snap_name = data.snapshot_name or f"{baseline.name}_{data.name}_snapshot"
        snap = mgr.take_snapshot(
            session, server, lab,
            name=snap_name,
            description=data.description or f"Subgroup snapshot for {data.name}",
        )
        if not snap:
            raise HTTPException(status_code=500, detail="Failed to create subgroup snapshot")

        # Capture snapshot tree
        provider = mgr._get_provider(lab)
        snap.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
        session.flush()
        snapshot_id = snap.id

    group = SnapshotGroupORM(
        baseline_id=data.baseline_id,
        snapshot_id=snapshot_id,
        name=data.name,
        description=data.description,
    )
    session.add(group)
    session.flush()

    # Link the snapshot to this subgroup
    if snapshot_id:
        snap_obj = session.get(SnapshotORM, snapshot_id)
        if snap_obj and not snap_obj.group_id:
            snap_obj.group_id = group.id

    session.commit()
    session.refresh(group)
    return group


@snapshot_router.delete(
    "/{server_id}/snapshot-groups/{group_id}",
)
def delete_snapshot_group(
    server_id: int,
    group_id: int,
    session: Session = Depends(get_session),
):
    """Delete a subgroup. Snapshots in the subgroup become unassigned."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    group = session.get(SnapshotGroupORM, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Snapshot group not found")
    # Verify it belongs to this server
    baseline = session.get(SnapshotBaselineORM, group.baseline_id)
    if not baseline or baseline.server_id != server_id:
        raise HTTPException(status_code=404, detail="Group not found for this server")

    # Unlink snapshots
    session.query(SnapshotORM).filter(
        SnapshotORM.group_id == group_id,
    ).update({"group_id": None})

    session.delete(group)
    session.commit()
    return {"message": f"Subgroup '{group.name}' deleted"}


@snapshot_router.get(
    "/{server_id}/snapshot-groups/{group_id}/snapshots",
    response_model=List[SnapshotResponse],
)
def list_group_snapshots(
    server_id: int,
    group_id: int,
    session: Session = Depends(get_session),
):
    """List all snapshots within a group."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    group = session.get(SnapshotGroupORM, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Snapshot group not found")

    return session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server_id,
        SnapshotORM.group_id == group_id,
    ).order_by(SnapshotORM.created_at).all()


@snapshot_router.post(
    "/{server_id}/snapshot-groups/{group_id}/link-snapshot/{snapshot_id}",
)
def link_snapshot_to_subgroup(
    server_id: int,
    group_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    """Link an existing snapshot to a subgroup."""
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    group = session.get(SnapshotGroupORM, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Subgroup not found")
    snapshot = session.get(SnapshotORM, snapshot_id)
    if not snapshot or snapshot.server_id != server_id:
        raise HTTPException(status_code=404, detail="Snapshot not found for this server")

    snapshot.group_id = group_id
    session.commit()
    return {"message": f"Snapshot #{snapshot_id} linked to subgroup '{group.name}'"}
