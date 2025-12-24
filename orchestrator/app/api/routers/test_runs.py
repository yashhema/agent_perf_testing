"""API router for TestRun operations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository
from app.repositories.baseline_repository import BaselineRepository
from app.services.test_run_service import TestRunService
from app.api.models.requests import (
    CreateTestRunRequest,
    UpdateTestRunRequest,
    CreateTestRunTargetRequest,
)
from app.api.models.responses import (
    TestRunResponse,
    TestRunListResponse,
    TestRunTargetResponse,
    DeleteResponse,
)

router = APIRouter(prefix="/test-runs")


def get_test_run_service(
    session: AsyncSession = Depends(get_session),
) -> TestRunService:
    """Get TestRunService instance."""
    return TestRunService(
        repository=TestRunRepository(session),
        target_repository=TestRunTargetRepository(session),
        lab_repository=LabRepository(session),
        server_repository=ServerRepository(session),
        baseline_repository=BaselineRepository(session),
    )


@router.post("/", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
async def create_test_run(
    request: CreateTestRunRequest,
    service: TestRunService = Depends(get_test_run_service),
):
    """Create a new test run."""
    try:
        test_run = await service.create_test_run(
            name=request.name,
            lab_id=request.lab_id,
            req_loadprofile=request.req_loadprofile,
            loadgenerator_package_grpid_lst=request.loadgenerator_package_grpid_lst,
            description=request.description,
            warmup_sec=request.warmup_sec,
            measured_sec=request.measured_sec,
            analysis_trim_sec=request.analysis_trim_sec,
            repetitions=request.repetitions,
        )
        return TestRunResponse(
            id=test_run.id,
            name=test_run.name,
            description=test_run.description,
            lab_id=test_run.lab_id,
            req_loadprofile=test_run.req_loadprofile,
            warmup_sec=test_run.warmup_sec,
            measured_sec=test_run.measured_sec,
            analysis_trim_sec=test_run.analysis_trim_sec,
            repetitions=test_run.repetitions,
            loadgenerator_package_grpid_lst=test_run.loadgenerator_package_grpid_lst,
            created_at=test_run.created_at,
            updated_at=test_run.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=TestRunListResponse)
async def list_test_runs(
    lab_id: int = Query(..., description="Lab ID to filter test runs"),
    service: TestRunService = Depends(get_test_run_service),
):
    """List test runs in a lab."""
    test_runs = await service.list_test_runs(lab_id)
    return TestRunListResponse(
        test_runs=[
            TestRunResponse(
                id=tr.id,
                name=tr.name,
                description=tr.description,
                lab_id=tr.lab_id,
                req_loadprofile=tr.req_loadprofile,
                warmup_sec=tr.warmup_sec,
                measured_sec=tr.measured_sec,
                analysis_trim_sec=tr.analysis_trim_sec,
                repetitions=tr.repetitions,
                loadgenerator_package_grpid_lst=tr.loadgenerator_package_grpid_lst,
                created_at=tr.created_at,
                updated_at=tr.updated_at,
            )
            for tr in test_runs
        ],
        total=len(test_runs),
    )


@router.get("/{test_run_id}", response_model=TestRunResponse)
async def get_test_run(
    test_run_id: int,
    service: TestRunService = Depends(get_test_run_service),
):
    """Get a test run by ID."""
    test_run = await service.get_test_run(test_run_id)
    if test_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test run with ID {test_run_id} not found",
        )
    return TestRunResponse(
        id=test_run.id,
        name=test_run.name,
        description=test_run.description,
        lab_id=test_run.lab_id,
        req_loadprofile=test_run.req_loadprofile,
        warmup_sec=test_run.warmup_sec,
        measured_sec=test_run.measured_sec,
        analysis_trim_sec=test_run.analysis_trim_sec,
        repetitions=test_run.repetitions,
        loadgenerator_package_grpid_lst=test_run.loadgenerator_package_grpid_lst,
        created_at=test_run.created_at,
        updated_at=test_run.updated_at,
    )


@router.patch("/{test_run_id}", response_model=TestRunResponse)
async def update_test_run(
    test_run_id: int,
    request: UpdateTestRunRequest,
    service: TestRunService = Depends(get_test_run_service),
):
    """Update a test run."""
    test_run = await service.update_test_run(
        test_run_id=test_run_id,
        name=request.name,
        description=request.description,
        req_loadprofile=request.req_loadprofile,
        warmup_sec=request.warmup_sec,
        measured_sec=request.measured_sec,
        analysis_trim_sec=request.analysis_trim_sec,
        repetitions=request.repetitions,
    )
    if test_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test run with ID {test_run_id} not found",
        )
    return TestRunResponse(
        id=test_run.id,
        name=test_run.name,
        description=test_run.description,
        lab_id=test_run.lab_id,
        req_loadprofile=test_run.req_loadprofile,
        warmup_sec=test_run.warmup_sec,
        measured_sec=test_run.measured_sec,
        analysis_trim_sec=test_run.analysis_trim_sec,
        repetitions=test_run.repetitions,
        loadgenerator_package_grpid_lst=test_run.loadgenerator_package_grpid_lst,
        created_at=test_run.created_at,
        updated_at=test_run.updated_at,
    )


@router.delete("/{test_run_id}", response_model=DeleteResponse)
async def delete_test_run(
    test_run_id: int,
    service: TestRunService = Depends(get_test_run_service),
):
    """Delete a test run and all its targets."""
    deleted = await service.delete_test_run(test_run_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test run with ID {test_run_id} not found",
        )
    return DeleteResponse(
        success=True,
        message=f"Test run {test_run_id} deleted successfully",
    )


# ============================================================
# Target Operations
# ============================================================


@router.post(
    "/{test_run_id}/targets",
    response_model=TestRunTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_target(
    test_run_id: int,
    request: CreateTestRunTargetRequest,
    service: TestRunService = Depends(get_test_run_service),
):
    """Add a target to a test run."""
    try:
        target = await service.add_target(
            test_run_id=test_run_id,
            target_id=request.target_id,
            loadgenerator_id=request.loadgenerator_id,
            jmeter_port=request.jmeter_port,
            jmx_file_path=request.jmx_file_path,
            base_baseline_id=request.base_baseline_id,
            initial_baseline_id=request.initial_baseline_id,
            upgrade_baseline_id=request.upgrade_baseline_id,
        )
        return TestRunTargetResponse(
            id=target.id,
            test_run_id=target.test_run_id,
            target_id=target.target_id,
            loadgenerator_id=target.loadgenerator_id,
            jmeter_port=target.jmeter_port,
            jmx_file_path=target.jmx_file_path,
            base_baseline_id=target.base_baseline_id,
            initial_baseline_id=target.initial_baseline_id,
            upgrade_baseline_id=target.upgrade_baseline_id,
            created_at=target.created_at,
            updated_at=target.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{test_run_id}/targets", response_model=list[TestRunTargetResponse])
async def list_targets(
    test_run_id: int,
    service: TestRunService = Depends(get_test_run_service),
):
    """List all targets for a test run."""
    targets = await service.get_targets(test_run_id)
    return [
        TestRunTargetResponse(
            id=t.id,
            test_run_id=t.test_run_id,
            target_id=t.target_id,
            loadgenerator_id=t.loadgenerator_id,
            jmeter_port=t.jmeter_port,
            jmx_file_path=t.jmx_file_path,
            base_baseline_id=t.base_baseline_id,
            initial_baseline_id=t.initial_baseline_id,
            upgrade_baseline_id=t.upgrade_baseline_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in targets
    ]


@router.delete("/{test_run_id}/targets/{target_id}", response_model=DeleteResponse)
async def remove_target(
    test_run_id: int,
    target_id: int,
    service: TestRunService = Depends(get_test_run_service),
):
    """Remove a target from a test run."""
    deleted = await service.remove_target(target_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target with ID {target_id} not found",
        )
    return DeleteResponse(
        success=True,
        message=f"Target {target_id} removed from test run {test_run_id}",
    )
