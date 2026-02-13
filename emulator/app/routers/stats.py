"""Stats router for system statistics."""

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models.responses import (
    StatsResponse,
    IterationTimingResponse,
    RecentStatsResponse,
    StatsSampleResponse,
    AllStatsResponse,
    StatsMetadataResponse,
)
from ..stats.collector import get_stats_collector


router = APIRouter(prefix="/stats")


@router.get("/system", response_model=StatsResponse)
async def get_system_stats() -> StatsResponse:
    """Get current system statistics (single snapshot)."""
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


@router.get("/recent", response_model=RecentStatsResponse)
async def get_recent_stats(
    count: int = Query(default=100, ge=1, le=1000, description="Number of samples to return")
) -> RecentStatsResponse:
    """Get the most recent N stats samples from the running test.

    This endpoint returns samples from the in-memory buffer during an active test.
    Use this for real-time monitoring dashboards.
    """
    collector = get_stats_collector()
    status = collector.get_collection_status()
    samples = collector.get_recent_samples(count)

    return RecentStatsResponse(
        test_id=status.get("test_id"),
        test_run_id=status.get("test_run_id"),
        is_collecting=status.get("is_collecting", False),
        total_samples=status.get("samples_collected", 0),
        returned_samples=len(samples),
        samples=[
            StatsSampleResponse(
                timestamp=s.timestamp,
                elapsed_sec=s.elapsed_sec,
                cpu_percent=s.cpu_percent,
                memory_percent=s.memory_percent,
                memory_used_mb=s.memory_used_mb,
                memory_available_mb=s.memory_available_mb,
                disk_read_bytes=s.disk_read_bytes,
                disk_write_bytes=s.disk_write_bytes,
                disk_read_rate_mbps=s.disk_read_rate_mbps,
                disk_write_rate_mbps=s.disk_write_rate_mbps,
                network_sent_bytes=s.network_sent_bytes,
                network_recv_bytes=s.network_recv_bytes,
                network_sent_rate_mbps=s.network_sent_rate_mbps,
                network_recv_rate_mbps=s.network_recv_rate_mbps,
            )
            for s in samples
        ],
    )


@router.get("/all", response_model=AllStatsResponse)
async def get_all_stats(
    test_run_id: str = Query(..., description="Test run ID to retrieve stats for"),
    scenario_id: Optional[str] = Query(default=None, description="Optional scenario filter"),
) -> AllStatsResponse:
    """Retrieve all stats from a completed test's stats file.

    This endpoint loads stats from the JSON file saved when a test was stopped.
    Use this for post-test analysis and reporting.
    """
    collector = get_stats_collector()

    # Check if test is still running
    status = collector.get_collection_status()
    if status.get("is_collecting") and status.get("test_run_id") == test_run_id:
        raise HTTPException(
            status_code=400,
            detail="Test is still running. Stop the test first to access all stats."
        )

    # Load stats from file
    data = collector.load_stats_file(test_run_id, scenario_id)

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Stats file not found for test_run_id: {test_run_id}"
        )

    # Convert to response model
    metadata = data.get("metadata", {})
    samples = data.get("samples", [])
    summary = data.get("summary", {})

    return AllStatsResponse(
        metadata=StatsMetadataResponse(
            test_id=metadata.get("test_id", ""),
            test_run_id=metadata.get("test_run_id", ""),
            scenario_id=metadata.get("scenario_id", ""),
            mode=metadata.get("mode", ""),
            started_at=metadata.get("started_at", ""),
            ended_at=metadata.get("ended_at", ""),
            duration_sec=metadata.get("duration_sec", 0.0),
            collect_interval_sec=metadata.get("collect_interval_sec", 1.0),
            total_samples=metadata.get("total_samples", 0),
        ),
        samples=[
            StatsSampleResponse(
                timestamp=s.get("timestamp", ""),
                elapsed_sec=s.get("elapsed_sec", 0.0),
                cpu_percent=s.get("cpu_percent", 0.0),
                memory_percent=s.get("memory_percent", 0.0),
                memory_used_mb=s.get("memory_used_mb", 0.0),
                memory_available_mb=s.get("memory_available_mb", 0.0),
                disk_read_bytes=s.get("disk_read_bytes", 0),
                disk_write_bytes=s.get("disk_write_bytes", 0),
                disk_read_rate_mbps=s.get("disk_read_rate_mbps", 0.0),
                disk_write_rate_mbps=s.get("disk_write_rate_mbps", 0.0),
                network_sent_bytes=s.get("network_sent_bytes", 0),
                network_recv_bytes=s.get("network_recv_bytes", 0),
                network_sent_rate_mbps=s.get("network_sent_rate_mbps", 0.0),
                network_recv_rate_mbps=s.get("network_recv_rate_mbps", 0.0),
            )
            for s in samples
        ],
        summary=summary,
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
