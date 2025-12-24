"""Operations router for individual operation execution."""

from fastapi import APIRouter, HTTPException

from ..models.requests import (
    CPUOperationRequest,
    MEMOperationRequest,
    DISKOperationRequest,
    NETOperationRequest,
)
from ..models.responses import OperationResult
from ..operations.cpu import CPUOperation, CPUOperationParams
from ..operations.memory import MEMOperation, MEMOperationParams
from ..operations.disk import DISKOperation, DISKOperationParams
from ..operations.network import NETOperation, NETOperationParams


router = APIRouter(prefix="/operations")


@router.post("/cpu", response_model=OperationResult)
async def execute_cpu_operation(request: CPUOperationRequest) -> OperationResult:
    """Execute a CPU load operation."""
    try:
        params = CPUOperationParams(
            duration_ms=request.duration_ms,
            intensity=request.intensity,
        )
        result = await CPUOperation.execute(params)

        return OperationResult(
            operation=result.operation,
            status=result.status,
            duration_ms=result.actual_duration_ms,
            details={
                "requested_duration_ms": result.duration_ms,
                "intensity": result.intensity,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mem", response_model=OperationResult)
async def execute_memory_operation(request: MEMOperationRequest) -> OperationResult:
    """Execute a memory operation."""
    try:
        params = MEMOperationParams(
            duration_ms=request.duration_ms,
            size_mb=request.size_mb,
            pattern=request.pattern,
        )
        result = await MEMOperation.execute(params)

        return OperationResult(
            operation=result.operation,
            status=result.status,
            duration_ms=result.actual_duration_ms,
            details={
                "requested_duration_ms": result.duration_ms,
                "size_mb": result.size_mb,
                "pattern": result.pattern,
                "access_count": result.access_count,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disk", response_model=OperationResult)
async def execute_disk_operation(request: DISKOperationRequest) -> OperationResult:
    """Execute a disk I/O operation."""
    try:
        params = DISKOperationParams(
            duration_ms=request.duration_ms,
            mode=request.mode,
            size_mb=request.size_mb,
            block_size_kb=request.block_size_kb,
        )
        result = await DISKOperation.execute(params)

        return OperationResult(
            operation=result.operation,
            status=result.status,
            duration_ms=result.actual_duration_ms,
            details={
                "requested_duration_ms": result.duration_ms,
                "mode": result.mode,
                "size_mb": result.size_mb,
                "block_size_kb": result.block_size_kb,
                "bytes_written": result.bytes_written,
                "bytes_read": result.bytes_read,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/net", response_model=OperationResult)
async def execute_network_operation(request: NETOperationRequest) -> OperationResult:
    """Execute a network I/O operation."""
    try:
        params = NETOperationParams(
            duration_ms=request.duration_ms,
            target_host=request.target_host,
            target_port=request.target_port,
            packet_size_bytes=request.packet_size_bytes,
            mode=request.mode,
        )
        result = await NETOperation.execute(params)

        return OperationResult(
            operation=result.operation,
            status=result.status,
            duration_ms=result.actual_duration_ms,
            details={
                "requested_duration_ms": result.duration_ms,
                "target_host": result.target_host,
                "target_port": result.target_port,
                "mode": result.mode,
                "bytes_sent": result.bytes_sent,
                "bytes_received": result.bytes_received,
                "connection_established": result.connection_established,
                "error_message": result.error_message,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
