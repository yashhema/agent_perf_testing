"""API router for Lab operations."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.repositories.lab_repository import LabRepository
from app.services.lab_service import LabService
from app.api.models.requests import CreateLabRequest, UpdateLabRequest
from app.api.models.responses import (
    LabResponse,
    LabListResponse,
    DeleteResponse,
)

router = APIRouter(prefix="/labs")


def get_lab_service(session: AsyncSession = Depends(get_session)) -> LabService:
    """Get LabService instance."""
    return LabService(LabRepository(session))


@router.post("/", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
async def create_lab(
    request: CreateLabRequest,
    service: LabService = Depends(get_lab_service),
):
    """Create a new lab."""
    try:
        lab = await service.create_lab(
            name=request.name,
            lab_type=request.lab_type,
            description=request.description,
        )
        return LabResponse(
            id=lab.id,
            name=lab.name,
            lab_type=lab.lab_type,
            description=lab.description,
            created_at=lab.created_at,
            updated_at=lab.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=LabListResponse)
async def list_labs(
    service: LabService = Depends(get_lab_service),
):
    """List all labs."""
    labs = await service.list_labs()
    return LabListResponse(
        labs=[
            LabResponse(
                id=lab.id,
                name=lab.name,
                lab_type=lab.lab_type,
                description=lab.description,
                created_at=lab.created_at,
                updated_at=lab.updated_at,
            )
            for lab in labs
        ],
        total=len(labs),
    )


@router.get("/{lab_id}", response_model=LabResponse)
async def get_lab(
    lab_id: int,
    service: LabService = Depends(get_lab_service),
):
    """Get a lab by ID."""
    lab = await service.get_lab(lab_id)
    if lab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lab with ID {lab_id} not found",
        )
    return LabResponse(
        id=lab.id,
        name=lab.name,
        lab_type=lab.lab_type,
        description=lab.description,
        created_at=lab.created_at,
        updated_at=lab.updated_at,
    )


@router.patch("/{lab_id}", response_model=LabResponse)
async def update_lab(
    lab_id: int,
    request: UpdateLabRequest,
    service: LabService = Depends(get_lab_service),
):
    """Update a lab."""
    try:
        lab = await service.update_lab(
            lab_id=lab_id,
            name=request.name,
            lab_type=request.lab_type,
            description=request.description,
        )
        if lab is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lab with ID {lab_id} not found",
            )
        return LabResponse(
            id=lab.id,
            name=lab.name,
            lab_type=lab.lab_type,
            description=lab.description,
            created_at=lab.created_at,
            updated_at=lab.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{lab_id}", response_model=DeleteResponse)
async def delete_lab(
    lab_id: int,
    service: LabService = Depends(get_lab_service),
):
    """Delete a lab."""
    deleted = await service.delete_lab(lab_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lab with ID {lab_id} not found",
        )
    return DeleteResponse(success=True, message=f"Lab {lab_id} deleted successfully")
