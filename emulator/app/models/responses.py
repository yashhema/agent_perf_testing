"""Pydantic response models for emulator service."""

from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field


class OperationResult(BaseModel):
    """Result of an operation execution."""

    operation: str = Field(..., description="Operation type")
    status: str = Field(..., description="Operation status")
    duration_ms: int = Field(..., description="Actual duration in milliseconds")
    details: dict = Field(default_factory=dict, description="Additional details")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    service: str = Field(default="emulator", description="Service name")
    version: str = Field(..., description="Service version")
    uptime_sec: float = Field(..., description="Uptime in seconds")


class StatsCollectionInfo(BaseModel):
    """Stats collection status info."""

    enabled: bool = Field(..., description="Whether stats collection is enabled")
    interval_sec: float = Field(..., description="Collection interval in seconds")
    samples_collected: int = Field(..., description="Number of samples collected")


class TestStatusResponse(BaseModel):
    """Status of a running or completed test."""

    test_id: str = Field(..., description="Internal test identifier")
    test_run_id: Optional[str] = Field(None, description="External test run ID")
    scenario_id: Optional[str] = Field(None, description="Scenario identifier")
    mode: Optional[str] = Field(None, description="Test mode (calibration/normal)")
    status: str = Field(..., description="Test status")
    thread_count: int = Field(..., description="Number of threads")
    iterations_completed: int = Field(..., description="Number of completed iterations")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    elapsed_sec: float = Field(..., description="Elapsed time in seconds")
    error_count: int = Field(default=0, description="Number of errors")
    stats_collection: Optional[StatsCollectionInfo] = Field(
        None, description="Stats collection status"
    )


class StopTestResponse(BaseModel):
    """Response when stopping a test."""

    success: bool = Field(..., description="Whether stop was successful")
    message: str = Field(..., description="Status message")
    stats_file: Optional[str] = Field(None, description="Path to saved stats file")
    total_samples: int = Field(default=0, description="Total stats samples collected")


class StatsResponse(BaseModel):
    """System statistics response."""

    timestamp: datetime = Field(..., description="Stats timestamp")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    memory_percent: float = Field(..., description="Memory usage percentage")
    memory_used_mb: float = Field(..., description="Memory used in MB")
    memory_available_mb: float = Field(..., description="Memory available in MB")
    disk_read_bytes: int = Field(..., description="Disk bytes read")
    disk_write_bytes: int = Field(..., description="Disk bytes written")
    network_sent_bytes: int = Field(..., description="Network bytes sent")
    network_recv_bytes: int = Field(..., description="Network bytes received")


class IterationTimingResponse(BaseModel):
    """Iteration timing statistics."""

    sample_count: int = Field(..., description="Number of samples")
    avg_ms: float = Field(..., description="Average iteration time in ms")
    stddev_ms: float = Field(..., description="Standard deviation in ms")
    min_ms: float = Field(..., description="Minimum iteration time in ms")
    max_ms: float = Field(..., description="Maximum iteration time in ms")
    p50_ms: float = Field(..., description="50th percentile in ms")
    p90_ms: float = Field(..., description="90th percentile in ms")
    p99_ms: float = Field(..., description="99th percentile in ms")


class AgentInfoResponse(BaseModel):
    """Agent information response."""

    agent_type: str = Field(..., description="Agent type")
    installed: bool = Field(..., description="Whether agent is installed")
    version: Optional[str] = Field(None, description="Agent version if installed")
    service_status: Optional[str] = Field(None, description="Service status")
    install_path: Optional[str] = Field(None, description="Installation path")


class FileOperationResult(BaseModel):
    """Result of a file operation."""

    operation: str = Field(default="FILE", description="Operation type")
    status: str = Field(..., description="Operation status")
    duration_ms: int = Field(..., description="Duration in milliseconds")
    size_bracket: str = Field(..., description="Size bracket (e.g., '50-100KB')")
    actual_size_bytes: int = Field(..., description="Actual file size in bytes")
    output_format: str = Field(..., description="Output format (txt, csv, doc, xls, pdf)")
    output_folder: str = Field(..., description="Output folder path")
    output_file: str = Field(..., description="Full output file path")
    is_confidential: bool = Field(..., description="Whether file contains confidential data")
    is_zipped: bool = Field(..., description="Whether file is zipped")
    source_files_used: int = Field(..., description="Number of source files used")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class ProcessStatsResponse(BaseModel):
    """Per-process resource usage."""

    name: str = Field(..., description="Process name")
    pid: int = Field(..., description="Process ID")
    cpu_percent: float = Field(..., description="Process CPU usage percentage")
    memory_percent: float = Field(..., description="Process memory usage percentage")
    memory_rss_mb: float = Field(..., description="Process resident set size in MB")


class StatsSampleResponse(BaseModel):
    """A single stats sample."""

    timestamp: str = Field(..., description="Sample timestamp (ISO format)")
    elapsed_sec: float = Field(..., description="Elapsed seconds since test start")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    memory_percent: float = Field(..., description="Memory usage percentage")
    memory_used_mb: float = Field(..., description="Memory used in MB")
    memory_available_mb: float = Field(..., description="Memory available in MB")
    disk_read_bytes: int = Field(..., description="Total disk bytes read")
    disk_write_bytes: int = Field(..., description="Total disk bytes written")
    disk_read_rate_mbps: float = Field(..., description="Disk read rate in MB/s")
    disk_write_rate_mbps: float = Field(..., description="Disk write rate in MB/s")
    network_sent_bytes: int = Field(..., description="Total network bytes sent")
    network_recv_bytes: int = Field(..., description="Total network bytes received")
    network_sent_rate_mbps: float = Field(..., description="Network send rate in MB/s")
    network_recv_rate_mbps: float = Field(..., description="Network receive rate in MB/s")
    process_stats: List[ProcessStatsResponse] = Field(
        default_factory=list, description="Per-process stats for monitored services"
    )


class RecentStatsResponse(BaseModel):
    """Response for recent stats samples."""

    test_id: Optional[str] = Field(None, description="Current test ID")
    test_run_id: Optional[str] = Field(None, description="Current test run ID")
    is_collecting: bool = Field(..., description="Whether stats collection is active")
    total_samples: int = Field(..., description="Total samples in buffer")
    returned_samples: int = Field(..., description="Number of samples returned")
    samples: List[StatsSampleResponse] = Field(
        default_factory=list, description="Stats samples"
    )


class MetricSummary(BaseModel):
    """Summary statistics for a single metric."""

    avg: float = Field(..., description="Average value")
    min: float = Field(..., description="Minimum value")
    max: float = Field(..., description="Maximum value")
    p50: float = Field(..., description="50th percentile")
    p90: float = Field(..., description="90th percentile")
    p95: float = Field(..., description="95th percentile")
    p99: float = Field(..., description="99th percentile")


class StatsMetadataResponse(BaseModel):
    """Metadata for a stats file."""

    test_id: str = Field(..., description="Internal test ID")
    test_run_id: str = Field(..., description="External test run ID")
    scenario_id: str = Field(..., description="Scenario identifier")
    mode: str = Field(..., description="Test mode")
    started_at: str = Field(..., description="Start timestamp")
    ended_at: str = Field(..., description="End timestamp")
    duration_sec: float = Field(..., description="Test duration in seconds")
    collect_interval_sec: float = Field(..., description="Collection interval")
    total_samples: int = Field(..., description="Total samples collected")


class AllStatsResponse(BaseModel):
    """Response for all stats from a file."""

    metadata: StatsMetadataResponse = Field(..., description="Test metadata")
    samples: List[StatsSampleResponse] = Field(
        default_factory=list, description="All stats samples"
    )
    summary: dict = Field(default_factory=dict, description="Summary statistics")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error detail")
    code: Optional[str] = Field(None, description="Error code")
