"""Pydantic response models for load generator service."""

from typing import Optional, List, Dict
from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    service: str = Field(default="loadgen", description="Service name")
    version: str = Field(..., description="Service version")
    jmeter_available: bool = Field(..., description="Whether JMeter is available")
    jmeter_version: Optional[str] = Field(None, description="JMeter version")


class JMeterStatusResponse(BaseModel):
    """Status of a JMeter process."""

    target_id: int = Field(..., description="Target server ID")
    test_run_id: str = Field(..., description="Test run identifier")
    status: str = Field(..., description="Process status")
    jmeter_port: int = Field(..., description="JMeter port")
    thread_count: int = Field(..., description="Configured thread count")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    elapsed_sec: float = Field(..., description="Elapsed time in seconds")
    pid: Optional[int] = Field(None, description="Process ID")


class OperationStatsResponse(BaseModel):
    """Statistics for a single operation type."""

    operation: str = Field(..., description="Operation name/label")
    count: int = Field(..., description="Number of samples")
    success_count: int = Field(..., description="Number of successful samples")
    failure_count: int = Field(..., description="Number of failed samples")
    error_rate: float = Field(..., description="Error rate percentage")
    avg_response_time_ms: float = Field(..., description="Average response time in ms")
    min_response_time_ms: float = Field(..., description="Minimum response time in ms")
    max_response_time_ms: float = Field(..., description="Maximum response time in ms")
    p50_ms: float = Field(..., description="50th percentile in ms")
    p90_ms: float = Field(..., description="90th percentile in ms")
    p99_ms: float = Field(..., description="99th percentile in ms")
    throughput: float = Field(..., description="Requests per second")


class JTLSummaryResponse(BaseModel):
    """Summary of JTL results."""

    target_id: int = Field(..., description="Target server ID")
    test_run_id: str = Field(..., description="Test run identifier")
    total_samples: int = Field(..., description="Total number of samples")
    success_count: int = Field(..., description="Number of successful samples")
    failure_count: int = Field(..., description="Number of failed samples")
    error_rate: float = Field(..., description="Overall error rate percentage")
    avg_response_time_ms: float = Field(..., description="Overall average response time")
    duration_sec: float = Field(..., description="Test duration in seconds")
    throughput: float = Field(..., description="Overall requests per second")
    per_operation: List[OperationStatsResponse] = Field(
        default_factory=list, description="Per-operation statistics"
    )


class StartJMeterResponse(BaseModel):
    """Response for starting JMeter."""

    success: bool = Field(..., description="Whether start was successful")
    message: str = Field(..., description="Status message")
    target_id: int = Field(..., description="Target server ID")
    jmeter_port: int = Field(..., description="Assigned JMeter port")
    pid: Optional[int] = Field(None, description="Process ID")


class StopJMeterResponse(BaseModel):
    """Response for stopping JMeter."""

    success: bool = Field(..., description="Whether stop was successful")
    message: str = Field(..., description="Status message")
    target_id: int = Field(..., description="Target server ID")


class ListProcessesResponse(BaseModel):
    """Response listing all JMeter processes."""

    processes: List[JMeterStatusResponse] = Field(
        default_factory=list, description="List of JMeter processes"
    )


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error detail")
