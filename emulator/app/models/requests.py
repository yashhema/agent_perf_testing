"""Pydantic request models for emulator service."""

from typing import Optional, Literal

from pydantic import BaseModel, Field


class CPUOperationRequest(BaseModel):
    """Request model for CPU operation."""

    duration_ms: int = Field(..., gt=0, description="Duration in milliseconds")
    intensity: float = Field(
        default=1.0, ge=0.0, le=1.0, description="CPU intensity (0.0 to 1.0)"
    )


class MEMOperationRequest(BaseModel):
    """Request model for memory operation."""

    duration_ms: int = Field(..., gt=0, description="Duration in milliseconds")
    size_mb: int = Field(..., gt=0, description="Memory size in MB")
    pattern: Literal["sequential", "random"] = Field(
        default="sequential", description="Memory access pattern"
    )


class DISKOperationRequest(BaseModel):
    """Request model for disk operation."""

    duration_ms: int = Field(..., gt=0, description="Duration in milliseconds")
    mode: Literal["read", "write", "mixed"] = Field(
        ..., description="Disk operation mode"
    )
    size_mb: int = Field(default=100, gt=0, description="File size in MB")
    block_size_kb: int = Field(default=64, gt=0, description="Block size in KB")


class NETOperationRequest(BaseModel):
    """Request model for network operation."""

    duration_ms: int = Field(..., gt=0, description="Duration in milliseconds")
    target_host: str = Field(..., description="Target host for network operation")
    target_port: int = Field(..., gt=0, le=65535, description="Target port")
    packet_size_bytes: int = Field(
        default=1024, gt=0, description="Packet size in bytes"
    )
    mode: Literal["send", "receive", "both"] = Field(
        default="both", description="Network operation mode"
    )


class CompositeOperationRequest(BaseModel):
    """Request model for composite operation (multiple operations)."""

    cpu: Optional[CPUOperationRequest] = None
    mem: Optional[MEMOperationRequest] = None
    disk: Optional[DISKOperationRequest] = None
    net: Optional[NETOperationRequest] = None
    parallel: bool = Field(
        default=True, description="Run operations in parallel if True"
    )


class StartTestRequest(BaseModel):
    """Request model for starting a load test."""

    thread_count: int = Field(..., gt=0, description="Number of threads")
    duration_sec: int = Field(..., gt=0, description="Duration in seconds")
    operation: CompositeOperationRequest = Field(
        ..., description="Operations to execute"
    )
    loop_count: Optional[int] = Field(
        default=None, description="Number of iterations (None for infinite)"
    )


class StopTestRequest(BaseModel):
    """Request model for stopping a test."""

    force: bool = Field(default=False, description="Force stop immediately")
