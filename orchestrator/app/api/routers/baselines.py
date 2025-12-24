"""API router for Baseline operations."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.repositories.baseline_repository import BaselineRepository
from app.repositories.lab_repository import LabRepository
from app.services.baseline_service import BaselineService
from app.models.application import BaselineConfig
from app.models.enums import BaselineType
from app.api.models.requests import CreateBaselineRequest, UpdateBaselineRequest
from app.api.models.responses import (
    BaselineResponse,
    BaselineConfigResponse,
    BaselineListResponse,
    DeleteResponse,
)

router = APIRouter(prefix="/baselines")


def get_baseline_service(
    session: AsyncSession = Depends(get_session),
) -> BaselineService:
    """Get BaselineService instance."""
    return BaselineService(
        BaselineRepository(session),
        LabRepository(session),
    )


def _to_baseline_config(request) -> BaselineConfig:
    """Convert request baseline config to application model."""
    return BaselineConfig(
        vcenter_host=request.vcenter_host,
        datacenter=request.datacenter,
        snapshot_name=request.snapshot_name,
        ami_id=request.ami_id,
        instance_type=request.instance_type,
        region=request.region,
        policy_id=request.policy_id,
        group_id=request.group_id,
    )


def _to_config_response(config: BaselineConfig) -> BaselineConfigResponse:
    """Convert baseline config to response model."""
    return BaselineConfigResponse(
        vcenter_host=config.vcenter_host,
        datacenter=config.datacenter,
        snapshot_name=config.snapshot_name,
        ami_id=config.ami_id,
        instance_type=config.instance_type,
        region=config.region,
        policy_id=config.policy_id,
        group_id=config.group_id,
    )


@router.post("/", response_model=BaselineResponse, status_code=status.HTTP_201_CREATED)
async def create_baseline(
    request: CreateBaselineRequest,
    service: BaselineService = Depends(get_baseline_service),
):
    """Create a new baseline."""
    try:
        baseline = await service.create_baseline(
            name=request.name,
            baseline_type=request.baseline_type,
            baseline_conf=_to_baseline_config(request.baseline_conf),
            lab_id=request.lab_id,
            description=request.description,
        )
        return BaselineResponse(
            id=baseline.id,
            name=baseline.name,
            description=baseline.description,
            baseline_type=baseline.baseline_type,
            baseline_conf=_to_config_response(baseline.baseline_conf),
            lab_id=baseline.lab_id,
            created_at=baseline.created_at,
            updated_at=baseline.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=BaselineListResponse)
async def list_baselines(
    lab_id: int = Query(..., description="Lab ID to filter baselines"),
    baseline_type: Optional[BaselineType] = Query(
        None, description="Filter by baseline type"
    ),
    service: BaselineService = Depends(get_baseline_service),
):
    """List baselines in a lab, optionally filtered by type."""
    if baseline_type is not None:
        baselines = await service.list_baselines_by_type(lab_id, baseline_type)
    else:
        baselines = await service.list_baselines(lab_id)

    return BaselineListResponse(
        baselines=[
            BaselineResponse(
                id=b.id,
                name=b.name,
                description=b.description,
                baseline_type=b.baseline_type,
                baseline_conf=_to_config_response(b.baseline_conf),
                lab_id=b.lab_id,
                created_at=b.created_at,
                updated_at=b.updated_at,
            )
            for b in baselines
        ],
        total=len(baselines),
    )


@router.get("/{baseline_id}", response_model=BaselineResponse)
async def get_baseline(
    baseline_id: int,
    service: BaselineService = Depends(get_baseline_service),
):
    """Get a baseline by ID."""
    baseline = await service.get_baseline(baseline_id)
    if baseline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline with ID {baseline_id} not found",
        )
    return BaselineResponse(
        id=baseline.id,
        name=baseline.name,
        description=baseline.description,
        baseline_type=baseline.baseline_type,
        baseline_conf=_to_config_response(baseline.baseline_conf),
        lab_id=baseline.lab_id,
        created_at=baseline.created_at,
        updated_at=baseline.updated_at,
    )


@router.patch("/{baseline_id}", response_model=BaselineResponse)
async def update_baseline(
    baseline_id: int,
    request: UpdateBaselineRequest,
    service: BaselineService = Depends(get_baseline_service),
):
    """Update a baseline."""
    try:
        baseline_conf = None
        if request.baseline_conf is not None:
            baseline_conf = _to_baseline_config(request.baseline_conf)

        baseline = await service.update_baseline(
            baseline_id=baseline_id,
            name=request.name,
            description=request.description,
            baseline_conf=baseline_conf,
        )
        if baseline is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Baseline with ID {baseline_id} not found",
            )
        return BaselineResponse(
            id=baseline.id,
            name=baseline.name,
            description=baseline.description,
            baseline_type=baseline.baseline_type,
            baseline_conf=_to_config_response(baseline.baseline_conf),
            lab_id=baseline.lab_id,
            created_at=baseline.created_at,
            updated_at=baseline.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{baseline_id}", response_model=DeleteResponse)
async def delete_baseline(
    baseline_id: int,
    service: BaselineService = Depends(get_baseline_service),
):
    """Delete a baseline."""
    deleted = await service.delete_baseline(baseline_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline with ID {baseline_id} not found",
        )
    return DeleteResponse(
        success=True,
        message=f"Baseline {baseline_id} deleted successfully",
    )
