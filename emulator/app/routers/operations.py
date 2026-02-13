"""Operations router for individual operation execution."""

from fastapi import APIRouter, HTTPException

from ..config import get_config
from ..models.requests import (
    CPUOperationRequest,
    MEMOperationRequest,
    DISKOperationRequest,
    NETOperationRequest,
    FileOperationRequest,
)
from ..models.responses import OperationResult, FileOperationResult
from ..operations.cpu import CPUOperation, CPUOperationParams
from ..operations.memory import MEMOperation, MEMOperationParams
from ..operations.disk import DISKOperation, DISKOperationParams
from ..operations.network import NETOperation, NETOperationParams
from ..operations.file import FileOperation, FileOperationParams


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
    """Execute a network I/O operation.

    If target_host and target_port are not provided, uses configured partner.
    """
    try:
        # Use configured partner if not provided in request
        config = get_config()
        target_host = request.target_host or config.partner.fqdn
        target_port = request.target_port or config.partner.port

        if not target_host:
            raise HTTPException(
                status_code=400,
                detail="target_host not provided and no partner configured"
            )

        params = NETOperationParams(
            duration_ms=request.duration_ms,
            target_host=target_host,
            target_port=target_port,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file", response_model=FileOperationResult)
async def execute_file_operation(request: FileOperationRequest) -> FileOperationResult:
    """Execute a file operation.

    Creates a file in one of the configured output folders.

    Deterministic mode (when optional fields provided):
    - Uses specified size_bracket, target_size_kb, output_format,
      output_folder_idx, and source_file_ids from the request.
    - Values come from the operation sequence CSV for reproducible tests.

    Random mode (when optional fields omitted):
    - Randomly selects size bracket, format, folder, and source files.
    - For standalone/manual use.
    """
    try:
        config = get_config()

        if not config.output_folders:
            raise HTTPException(
                status_code=400,
                detail="No output folders configured. Call POST /api/v1/config first."
            )

        params = FileOperationParams(
            is_confidential=request.is_confidential,
            make_zip=request.make_zip,
            size_bracket=request.size_bracket,
            target_size_kb=request.target_size_kb,
            output_format=request.output_format,
            output_folder_idx=request.output_folder_idx,
            source_file_ids=request.source_file_ids,
        )
        result = await FileOperation.execute(params)

        return FileOperationResult(
            operation=result.operation,
            status=result.status,
            duration_ms=result.duration_ms,
            size_bracket=result.size_bracket,
            actual_size_bytes=result.actual_size_bytes,
            output_format=result.output_format,
            output_folder=result.output_folder,
            output_file=result.output_file,
            is_confidential=result.is_confidential,
            is_zipped=result.is_zipped,
            source_files_used=result.source_files_used,
            error_message=result.error_message,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
