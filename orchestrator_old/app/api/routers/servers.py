"""API router for Server operations."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.repositories.server_repository import ServerRepository
from app.repositories.lab_repository import LabRepository
from app.services.server_service import ServerService
from app.models.enums import ServerRole
from app.api.models.requests import CreateServerRequest, UpdateServerRequest
from app.api.models.responses import (
    ServerResponse,
    ServerListResponse,
    DeleteResponse,
)

router = APIRouter(prefix="/servers")


def get_server_service(session: AsyncSession = Depends(get_session)) -> ServerService:
    """Get ServerService instance."""
    return ServerService(
        ServerRepository(session),
        LabRepository(session),
    )


@router.post("/", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    request: CreateServerRequest,
    service: ServerService = Depends(get_server_service),
):
    """Create a new server."""
    try:
        server = await service.create_server(
            hostname=request.hostname,
            ip_address=request.ip_address,
            os_family=request.os_family,
            server_type=request.server_type,
            lab_id=request.lab_id,
            ssh_username=request.ssh_username,
            ssh_key_path=request.ssh_key_path,
            winrm_username=request.winrm_username,
            emulator_port=request.emulator_port,
            loadgen_service_port=request.loadgen_service_port,
            is_active=request.is_active,
        )
        return ServerResponse(
            id=server.id,
            hostname=server.hostname,
            ip_address=server.ip_address,
            os_family=server.os_family,
            server_type=server.server_type,
            lab_id=server.lab_id,
            ssh_username=server.ssh_username,
            ssh_key_path=server.ssh_key_path,
            winrm_username=server.winrm_username,
            emulator_port=server.emulator_port,
            loadgen_service_port=server.loadgen_service_port,
            is_active=server.is_active,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=ServerListResponse)
async def list_servers(
    lab_id: int = Query(..., description="Lab ID to filter servers"),
    server_type: Optional[ServerRole] = Query(None, description="Filter by server type"),
    active_only: bool = Query(True, description="Only return active servers"),
    service: ServerService = Depends(get_server_service),
):
    """List servers in a lab, optionally filtered by type."""
    if server_type is not None:
        servers = await service.list_servers_by_type(lab_id, server_type, active_only)
    else:
        servers = await service.list_servers(lab_id)
        if active_only:
            servers = [s for s in servers if s.is_active]

    return ServerListResponse(
        servers=[
            ServerResponse(
                id=s.id,
                hostname=s.hostname,
                ip_address=s.ip_address,
                os_family=s.os_family,
                server_type=s.server_type,
                lab_id=s.lab_id,
                ssh_username=s.ssh_username,
                ssh_key_path=s.ssh_key_path,
                winrm_username=s.winrm_username,
                emulator_port=s.emulator_port,
                loadgen_service_port=s.loadgen_service_port,
                is_active=s.is_active,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in servers
        ],
        total=len(servers),
    )


@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(
    server_id: int,
    service: ServerService = Depends(get_server_service),
):
    """Get a server by ID."""
    server = await service.get_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with ID {server_id} not found",
        )
    return ServerResponse(
        id=server.id,
        hostname=server.hostname,
        ip_address=server.ip_address,
        os_family=server.os_family,
        server_type=server.server_type,
        lab_id=server.lab_id,
        ssh_username=server.ssh_username,
        ssh_key_path=server.ssh_key_path,
        winrm_username=server.winrm_username,
        emulator_port=server.emulator_port,
        loadgen_service_port=server.loadgen_service_port,
        is_active=server.is_active,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.patch("/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: int,
    request: UpdateServerRequest,
    service: ServerService = Depends(get_server_service),
):
    """Update a server."""
    server = await service.update_server(
        server_id=server_id,
        hostname=request.hostname,
        ip_address=request.ip_address,
        os_family=request.os_family,
        server_type=request.server_type,
        ssh_username=request.ssh_username,
        ssh_key_path=request.ssh_key_path,
        winrm_username=request.winrm_username,
        emulator_port=request.emulator_port,
        loadgen_service_port=request.loadgen_service_port,
        is_active=request.is_active,
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with ID {server_id} not found",
        )
    return ServerResponse(
        id=server.id,
        hostname=server.hostname,
        ip_address=server.ip_address,
        os_family=server.os_family,
        server_type=server.server_type,
        lab_id=server.lab_id,
        ssh_username=server.ssh_username,
        ssh_key_path=server.ssh_key_path,
        winrm_username=server.winrm_username,
        emulator_port=server.emulator_port,
        loadgen_service_port=server.loadgen_service_port,
        is_active=server.is_active,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.post("/{server_id}/deactivate", response_model=ServerResponse)
async def deactivate_server(
    server_id: int,
    service: ServerService = Depends(get_server_service),
):
    """Deactivate a server (soft delete)."""
    server = await service.deactivate_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with ID {server_id} not found",
        )
    return ServerResponse(
        id=server.id,
        hostname=server.hostname,
        ip_address=server.ip_address,
        os_family=server.os_family,
        server_type=server.server_type,
        lab_id=server.lab_id,
        ssh_username=server.ssh_username,
        ssh_key_path=server.ssh_key_path,
        winrm_username=server.winrm_username,
        emulator_port=server.emulator_port,
        loadgen_service_port=server.loadgen_service_port,
        is_active=server.is_active,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.post("/{server_id}/activate", response_model=ServerResponse)
async def activate_server(
    server_id: int,
    service: ServerService = Depends(get_server_service),
):
    """Activate a server."""
    server = await service.activate_server(server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with ID {server_id} not found",
        )
    return ServerResponse(
        id=server.id,
        hostname=server.hostname,
        ip_address=server.ip_address,
        os_family=server.os_family,
        server_type=server.server_type,
        lab_id=server.lab_id,
        ssh_username=server.ssh_username,
        ssh_key_path=server.ssh_key_path,
        winrm_username=server.winrm_username,
        emulator_port=server.emulator_port,
        loadgen_service_port=server.loadgen_service_port,
        is_active=server.is_active,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.delete("/{server_id}", response_model=DeleteResponse)
async def delete_server(
    server_id: int,
    service: ServerService = Depends(get_server_service),
):
    """Delete a server."""
    deleted = await service.delete_server(server_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with ID {server_id} not found",
        )
    return DeleteResponse(
        success=True,
        message=f"Server {server_id} deleted successfully",
    )
