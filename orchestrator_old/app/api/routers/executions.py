"""API router for Execution operations."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.repositories.execution_repository import (
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
)
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository
from app.services.execution_service import ExecutionService
from app.api.models.requests import CreateExecutionRequest, ExecutionActionRequest
from app.api.models.responses import (
    ExecutionResponse,
    ExecutionCreateResponse,
    ExecutionListResponse,
    ActionResultResponse,
    WorkflowStateResponse,
    ErrorRecordResponse,
)

router = APIRouter(prefix="/executions")


def get_execution_service(
    session: AsyncSession = Depends(get_session),
) -> ExecutionService:
    """Get ExecutionService instance."""
    return ExecutionService(
        execution_repository=TestRunExecutionRepository(session),
        workflow_state_repository=ExecutionWorkflowStateRepository(session),
        test_run_repository=TestRunRepository(session),
        test_run_target_repository=TestRunTargetRepository(session),
    )


@router.post(
    "/",
    response_model=ExecutionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution(
    request: CreateExecutionRequest,
    service: ExecutionService = Depends(get_execution_service),
):
    """Create a new test run execution."""
    result = await service.create_execution(
        test_run_id=request.test_run_id,
        run_mode=request.run_mode,
        immediate_run=request.immediate_run,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return ExecutionCreateResponse(
        id=result.execution_id,
        message=result.message,
        calibration_started=result.calibration_started,
    )


@router.get("/", response_model=ExecutionListResponse)
async def list_active_executions(
    service: ExecutionService = Depends(get_execution_service),
):
    """List all active test run executions."""
    executions = await service.list_active_executions()
    return ExecutionListResponse(
        executions=[
            ExecutionResponse(
                id=e.id,
                test_run_id=e.test_run_id,
                run_mode=e.run_mode,
                status=e.status,
                current_loadprofile=e.current_loadprofile,
                current_repetition=e.current_repetition,
                error_message=e.error_message,
                started_at=e.started_at,
                completed_at=e.completed_at,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
            for e in executions
        ],
        total=len(executions),
    )


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: UUID,
    service: ExecutionService = Depends(get_execution_service),
):
    """Get execution details."""
    execution = await service.get_execution(execution_id)

    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution with ID {execution_id} not found",
        )

    return ExecutionResponse(
        id=execution.id,
        test_run_id=execution.test_run_id,
        run_mode=execution.run_mode,
        status=execution.status,
        current_loadprofile=execution.current_loadprofile,
        current_repetition=execution.current_repetition,
        error_message=execution.error_message,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )


@router.get("/{execution_id}/workflow-states", response_model=list[WorkflowStateResponse])
async def get_workflow_states(
    execution_id: UUID,
    service: ExecutionService = Depends(get_execution_service),
):
    """Get workflow states for an execution."""
    # Verify execution exists
    execution = await service.get_execution(execution_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution with ID {execution_id} not found",
        )

    states = await service.get_workflow_states(execution_id)
    return [
        WorkflowStateResponse(
            id=s.id,
            test_run_execution_id=s.test_run_execution_id,
            target_id=s.target_id,
            loadprofile=s.loadprofile,
            runcount=s.runcount,
            base_baseline_id=s.base_baseline_id,
            initial_baseline_id=s.initial_baseline_id,
            upgrade_baseline_id=s.upgrade_baseline_id,
            current_phase=s.current_phase,
            phase_state=s.phase_state,
            retry_count=s.retry_count,
            max_retries=s.max_retries,
            error_history=[
                ErrorRecordResponse(
                    timestamp=e.timestamp,
                    phase=e.phase,
                    state=e.state,
                    error_message=e.error_message,
                    retry_count=e.retry_count,
                )
                for e in s.error_history
            ],
            phase_started_at=s.phase_started_at,
            phase_completed_at=s.phase_completed_at,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in states
    ]


@router.post("/{execution_id}/action", response_model=ActionResultResponse)
async def execute_action(
    execution_id: UUID,
    request: ExecutionActionRequest,
    service: ExecutionService = Depends(get_execution_service),
):
    """Execute action on a test run (continue, pause, abandon, status)."""
    result = await service.execute_action(
        execution_id=execution_id,
        action=request.action,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return ActionResultResponse(
        success=result.success,
        message=result.message,
        new_status=result.new_status,
    )


@router.post("/{execution_id}/continue", response_model=ActionResultResponse)
async def continue_execution(
    execution_id: UUID,
    service: ExecutionService = Depends(get_execution_service),
):
    """Continue a paused or ready execution."""
    result = await service.execute_action(
        execution_id=execution_id,
        action="continue",
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return ActionResultResponse(
        success=result.success,
        message=result.message,
        new_status=result.new_status,
    )


@router.post("/{execution_id}/pause", response_model=ActionResultResponse)
async def pause_execution(
    execution_id: UUID,
    service: ExecutionService = Depends(get_execution_service),
):
    """Pause a running execution."""
    result = await service.execute_action(
        execution_id=execution_id,
        action="pause",
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return ActionResultResponse(
        success=result.success,
        message=result.message,
        new_status=result.new_status,
    )


@router.post("/{execution_id}/abandon", response_model=ActionResultResponse)
async def abandon_execution(
    execution_id: UUID,
    service: ExecutionService = Depends(get_execution_service),
):
    """Abandon an execution."""
    result = await service.execute_action(
        execution_id=execution_id,
        action="abandon",
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    return ActionResultResponse(
        success=result.success,
        message=result.message,
        new_status=result.new_status,
    )
