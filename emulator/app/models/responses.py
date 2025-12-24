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


class TestStatusResponse(BaseModel):
    """Status of a running or completed test."""

    test_id: str = Field(..., description="Test identifier")
    status: str = Field(..., description="Test status")
    thread_count: int = Field(..., description="Number of threads")
    iterations_completed: int = Field(..., description="Number of completed iterations")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    elapsed_sec: float = Field(..., description="Elapsed time in seconds")
    error_count: int = Field(default=0, description="Number of errors")


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


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error detail")
    code: Optional[str] = Field(None, description="Error code")
