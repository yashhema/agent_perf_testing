"""Tests router for managing load tests."""

from typing import List

from fastapi import APIRouter, HTTPException

from ..models.requests import StartTestRequest, StopTestRequest
from ..models.responses import TestStatusResponse
from ..operations.cpu import CPUOperationParams
from ..operations.memory import MEMOperationParams
from ..operations.disk import DISKOperationParams
from ..operations.network import NETOperationParams
from ..services.test_manager import TestConfig, TestStatus, get_test_manager


router = APIRouter(prefix="/tests")


@router.post("/", response_model=TestStatusResponse)
async def start_test(request: StartTestRequest) -> TestStatusResponse:
    """Start a new load test."""
    manager = get_test_manager()

    # Build operation params
    cpu_params = None
    mem_params = None
    disk_params = None
    net_params = None

    if request.operation.cpu:
        cpu_params = CPUOperationParams(
            duration_ms=request.operation.cpu.duration_ms,
            intensity=request.operation.cpu.intensity,
        )

    if request.operation.mem:
        mem_params = MEMOperationParams(
            duration_ms=request.operation.mem.duration_ms,
            size_mb=request.operation.mem.size_mb,
            pattern=request.operation.mem.pattern,
        )

    if request.operation.disk:
        disk_params = DISKOperationParams(
            duration_ms=request.operation.disk.duration_ms,
            mode=request.operation.disk.mode,
            size_mb=request.operation.disk.size_mb,
            block_size_kb=request.operation.disk.block_size_kb,
        )

    if request.operation.net:
        net_params = NETOperationParams(
            duration_ms=request.operation.net.duration_ms,
            target_host=request.operation.net.target_host,
            target_port=request.operation.net.target_port,
            packet_size_bytes=request.operation.net.packet_size_bytes,
            mode=request.operation.net.mode,
        )

    config = TestConfig(
        thread_count=request.thread_count,
        duration_sec=request.duration_sec,
        loop_count=request.loop_count,
        cpu_params=cpu_params,
        mem_params=mem_params,
        disk_params=disk_params,
        net_params=net_params,
        parallel=request.operation.parallel,
    )

    test_id = await manager.start_test(config)
    state = manager.get_test_status(test_id)

    return TestStatusResponse(
        test_id=test_id,
        status=state.status.value,
        thread_count=config.thread_count,
        iterations_completed=state.iterations_completed,
        started_at=state.started_at,
        elapsed_sec=0.0,
        error_count=state.error_count,
    )


@router.get("/", response_model=List[TestStatusResponse])
async def list_tests() -> List[TestStatusResponse]:
    """List all tests."""
    manager = get_test_manager()
    tests = manager.get_all_tests()

    return [
        TestStatusResponse(
            test_id=state.test_id,
            status=state.status.value,
            thread_count=state.config.thread_count,
            iterations_completed=state.iterations_completed,
            started_at=state.started_at,
            elapsed_sec=_calculate_elapsed(state),
            error_count=state.error_count,
        )
        for state in tests
    ]


@router.get("/{test_id}", response_model=TestStatusResponse)
async def get_test(test_id: str) -> TestStatusResponse:
    """Get test status by ID."""
    manager = get_test_manager()
    state = manager.get_test_status(test_id)

    if not state:
        raise HTTPException(status_code=404, detail="Test not found")

    return TestStatusResponse(
        test_id=state.test_id,
        status=state.status.value,
        thread_count=state.config.thread_count,
        iterations_completed=state.iterations_completed,
        started_at=state.started_at,
        elapsed_sec=_calculate_elapsed(state),
        error_count=state.error_count,
    )


@router.post("/{test_id}/stop")
async def stop_test(test_id: str, request: StopTestRequest) -> dict:
    """Stop a running test."""
    manager = get_test_manager()

    if not manager.get_test_status(test_id):
        raise HTTPException(status_code=404, detail="Test not found")

    success = await manager.stop_test(test_id, force=request.force)

    if not success:
        raise HTTPException(status_code=400, detail="Test is not running")

    return {"success": True, "message": "Test stopped"}


def _calculate_elapsed(state) -> float:
    """Calculate elapsed time for a test."""
    if not state.started_at:
        return 0.0

    from datetime import datetime

    end_time = state.completed_at or datetime.utcnow()
    return (end_time - state.started_at).total_seconds()
