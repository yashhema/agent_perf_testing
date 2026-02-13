"""Tests router for managing load tests with stats collection."""

from typing import List

from fastapi import APIRouter, HTTPException

from ..models.requests import StartTestRequest, StopTestRequest
from ..models.responses import TestStatusResponse, StopTestResponse, StatsCollectionInfo
from ..operations.cpu import CPUOperationParams
from ..operations.memory import MEMOperationParams
from ..operations.disk import DISKOperationParams
from ..operations.network import NETOperationParams
from ..services.test_manager import TestConfig, get_test_manager
from ..stats.collector import get_stats_collector


router = APIRouter(prefix="/tests")


# Store test metadata for correlation
_test_metadata = {}


@router.post("/start", response_model=TestStatusResponse)
async def start_test(request: StartTestRequest) -> TestStatusResponse:
    """Start a new load test with stats collection.

    Two modes:
    1. Full mode (operation provided): Starts internal operation loop + stats collection
    2. Stats-only mode (operation=None): Only starts stats collection.
       JMeter drives operations externally via /api/v1/operations/* endpoints.
    """
    manager = get_test_manager()
    collector = get_stats_collector()

    import uuid
    test_id = str(uuid.uuid4())

    if request.operation is not None:
        # Full mode: start internal operation loop
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
        status = state.status.value
        iterations = state.iterations_completed
        started_at = state.started_at
        error_count = state.error_count
    else:
        # Stats-only mode: no internal operation loop
        status = "running"
        iterations = 0
        started_at = None
        error_count = 0

    # Store metadata for this test
    _test_metadata[test_id] = {
        "test_run_id": request.test_run_id,
        "scenario_id": request.scenario_id,
        "mode": request.mode,
        "collect_interval_sec": request.collect_interval_sec,
        "stats_only": request.operation is None,
    }

    # Start stats collection (always)
    await collector.start_collection(
        test_id=test_id,
        test_run_id=request.test_run_id,
        scenario_id=request.scenario_id,
        mode=request.mode,
        interval_sec=request.collect_interval_sec,
    )

    return TestStatusResponse(
        test_id=test_id,
        test_run_id=request.test_run_id,
        scenario_id=request.scenario_id,
        mode=request.mode,
        status=status,
        thread_count=request.thread_count,
        iterations_completed=iterations,
        started_at=started_at,
        elapsed_sec=0.0,
        error_count=error_count,
        stats_collection=StatsCollectionInfo(
            enabled=True,
            interval_sec=request.collect_interval_sec,
            samples_collected=0,
        ),
    )


@router.post("/", response_model=TestStatusResponse)
async def start_test_legacy(request: StartTestRequest) -> TestStatusResponse:
    """Start a new load test (legacy endpoint, redirects to /start)."""
    return await start_test(request)


@router.get("/", response_model=List[TestStatusResponse])
async def list_tests() -> List[TestStatusResponse]:
    """List all tests."""
    manager = get_test_manager()
    collector = get_stats_collector()
    tests = manager.get_all_tests()

    results = []
    for state in tests:
        metadata = _test_metadata.get(state.test_id, {})
        collection_status = collector.get_collection_status()

        stats_info = None
        if collection_status.get("test_id") == state.test_id:
            stats_info = StatsCollectionInfo(
                enabled=collection_status.get("is_collecting", False),
                interval_sec=collection_status.get("interval_sec", 1.0),
                samples_collected=collection_status.get("samples_collected", 0),
            )

        results.append(TestStatusResponse(
            test_id=state.test_id,
            test_run_id=metadata.get("test_run_id"),
            scenario_id=metadata.get("scenario_id"),
            mode=metadata.get("mode"),
            status=state.status.value,
            thread_count=state.config.thread_count,
            iterations_completed=state.iterations_completed,
            started_at=state.started_at,
            elapsed_sec=_calculate_elapsed(state),
            error_count=state.error_count,
            stats_collection=stats_info,
        ))

    return results


@router.get("/{test_id}", response_model=TestStatusResponse)
async def get_test(test_id: str) -> TestStatusResponse:
    """Get test status by ID."""
    manager = get_test_manager()
    collector = get_stats_collector()
    metadata = _test_metadata.get(test_id, {})
    is_stats_only = metadata.get("stats_only", False)

    collection_status = collector.get_collection_status()
    stats_info = None
    if collection_status.get("test_id") == test_id:
        stats_info = StatsCollectionInfo(
            enabled=collection_status.get("is_collecting", False),
            interval_sec=collection_status.get("interval_sec", 1.0),
            samples_collected=collection_status.get("samples_collected", 0),
        )

    if is_stats_only:
        # Stats-only test: no test manager state
        if not metadata:
            raise HTTPException(status_code=404, detail="Test not found")
        is_collecting = collection_status.get("is_collecting", False)
        return TestStatusResponse(
            test_id=test_id,
            test_run_id=metadata.get("test_run_id"),
            scenario_id=metadata.get("scenario_id"),
            mode=metadata.get("mode"),
            status="running" if is_collecting else "stopped",
            thread_count=0,
            iterations_completed=0,
            started_at=None,
            elapsed_sec=0.0,
            error_count=0,
            stats_collection=stats_info,
        )

    # Full mode test
    state = manager.get_test_status(test_id)
    if not state:
        raise HTTPException(status_code=404, detail="Test not found")

    return TestStatusResponse(
        test_id=state.test_id,
        test_run_id=metadata.get("test_run_id"),
        scenario_id=metadata.get("scenario_id"),
        mode=metadata.get("mode"),
        status=state.status.value,
        thread_count=state.config.thread_count,
        iterations_completed=state.iterations_completed,
        started_at=state.started_at,
        elapsed_sec=_calculate_elapsed(state),
        error_count=state.error_count,
        stats_collection=stats_info,
    )


@router.post("/{test_id}/stop", response_model=StopTestResponse)
async def stop_test(test_id: str, request: StopTestRequest) -> StopTestResponse:
    """Stop a running test and save stats to file.

    Handles both full-mode tests (with operation loop) and stats-only tests.
    1. Stops the load test workers (if any)
    2. Stops stats collection
    3. Saves all collected stats to a JSON file
    4. Returns the file path and sample count
    """
    manager = get_test_manager()
    collector = get_stats_collector()

    metadata = _test_metadata.get(test_id)
    is_stats_only = metadata.get("stats_only", False) if metadata else False

    if is_stats_only:
        # Stats-only mode: just stop collection, no test manager state
        pass
    else:
        # Full mode: stop the operation loop
        if not manager.get_test_status(test_id):
            raise HTTPException(status_code=404, detail="Test not found")

        success = await manager.stop_test(test_id, force=request.force)
        if not success:
            raise HTTPException(status_code=400, detail="Test is not running")

    # Stop stats collection and save to file
    stats_file = await collector.stop_collection()
    collection_status = collector.get_collection_status()

    # Clean up metadata
    _test_metadata.pop(test_id, None)

    return StopTestResponse(
        success=True,
        message="Test stopped and stats saved",
        stats_file=stats_file,
        total_samples=collection_status.get("samples_collected", 0),
    )


def _calculate_elapsed(state) -> float:
    """Calculate elapsed time for a test."""
    if not state.started_at:
        return 0.0

    from datetime import datetime

    end_time = state.completed_at or datetime.utcnow()
    return (end_time - state.started_at).total_seconds()
