"""Stats router for system statistics."""

from fastapi import APIRouter

from ..models.responses import StatsResponse, IterationTimingResponse
from ..stats.collector import get_stats_collector


router = APIRouter(prefix="/stats")


@router.get("/system", response_model=StatsResponse)
async def get_system_stats() -> StatsResponse:
    """Get current system statistics."""
    collector = get_stats_collector()
    stats = await collector.get_system_stats()

    return StatsResponse(
        timestamp=stats.timestamp,
        cpu_percent=stats.cpu_percent,
        memory_percent=stats.memory_percent,
        memory_used_mb=stats.memory_used_mb,
        memory_available_mb=stats.memory_available_mb,
        disk_read_bytes=stats.disk_read_bytes,
        disk_write_bytes=stats.disk_write_bytes,
        network_sent_bytes=stats.network_sent_bytes,
        network_recv_bytes=stats.network_recv_bytes,
    )


@router.get("/iterations", response_model=IterationTimingResponse)
async def get_iteration_stats() -> IterationTimingResponse:
    """Get iteration timing statistics."""
    collector = get_stats_collector()
    timing = collector.get_iteration_timing()

    if not timing:
        return IterationTimingResponse(
            sample_count=0,
            avg_ms=0.0,
            stddev_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            p50_ms=0.0,
            p90_ms=0.0,
            p99_ms=0.0,
        )

    return IterationTimingResponse(
        sample_count=timing.sample_count,
        avg_ms=timing.avg_ms,
        stddev_ms=timing.stddev_ms,
        min_ms=timing.min_ms,
        max_ms=timing.max_ms,
        p50_ms=timing.p50_ms,
        p90_ms=timing.p90_ms,
        p99_ms=timing.p99_ms,
    )


@router.post("/iterations/clear")
async def clear_iteration_stats() -> dict:
    """Clear iteration timing statistics."""
    collector = get_stats_collector()
    collector.clear_iteration_times()
    return {"success": True, "message": "Iteration stats cleared"}
