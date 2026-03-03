"""Pydantic request models for emulator service."""

from typing import Optional, List, Literal

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
    target_host: Optional[str] = Field(
        default=None, description="Target host (uses configured partner if not provided)"
    )
    target_port: Optional[int] = Field(
        default=None, gt=0, le=65535, description="Target port (uses configured partner if not provided)"
    )
    packet_size_bytes: int = Field(
        default=1024, gt=0, description="Packet size in bytes"
    )
    mode: Literal["send", "receive", "both"] = Field(
        default="both", description="Network operation mode"
    )


class FileOperationRequest(BaseModel):
    """Request model for file operation.

    When optional fields are provided, the emulator uses them directly
    (deterministic mode — values come from the operation sequence CSV).
    When omitted, the emulator selects randomly (legacy/standalone mode).
    """

    is_confidential: bool = Field(
        default=False, description="Include confidential data in file"
    )
    make_zip: bool = Field(
        default=False, description="Compress output file"
    )
    # Deterministic fields — all optional for backward compatibility
    size_bracket: Optional[Literal["small", "medium", "large", "xlarge"]] = Field(
        default=None, description="Size category (if None, random)"
    )
    target_size_kb: Optional[int] = Field(
        default=None, gt=0, description="Exact target file size in KB (if None, random within bracket)"
    )
    output_format: Optional[Literal["txt", "csv", "doc", "xls", "pdf"]] = Field(
        default=None, description="Output format (if None, random)"
    )
    output_folder_idx: Optional[int] = Field(
        default=None, ge=0, description="Index into output_folders list (if None, random)"
    )
    source_file_ids: Optional[str] = Field(
        default=None, description="Semicolon-separated source file IDs (if None, auto-select)"
    )


class SuspiciousOperationRequest(BaseModel):
    """Request model for suspicious system-level activity.

    Performs OS-level activities that security agents (EDR/AV) would flag.
    Used as end-test to observe agent response to suspicious behavior.
    """

    activity_type: str = Field(
        ..., description="Type of suspicious activity (e.g., 'crontab_write', 'registry_write')"
    )
    duration_ms: int = Field(
        default=500, gt=0, description="How long to keep artifact alive before cleanup (ms)"
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

    # Test identification (for stats collection)
    test_run_id: str = Field(
        ..., description="External test run ID from orchestrator"
    )
    scenario_id: str = Field(
        ..., description="Scenario identifier (e.g., 'file-heavy', 'calibration')"
    )
    mode: Literal["calibration", "normal"] = Field(
        default="normal", description="Test mode: calibration (baseline) or normal"
    )

    # Stats collection settings
    collect_interval_sec: float = Field(
        default=1.0, gt=0, description="Stats collection interval in seconds"
    )

    # Existing fields
    thread_count: int = Field(..., gt=0, description="Number of threads")
    duration_sec: Optional[int] = Field(
        default=None, gt=0, description="Duration in seconds (optional if loop_count set)"
    )
    loop_count: Optional[int] = Field(
        default=None, description="Number of iterations (None for infinite)"
    )
    operation: Optional[CompositeOperationRequest] = Field(
        default=None,
        description="Operations to execute. If None, stats-only mode: "
                    "stats collection runs but no internal operation loop."
    )


class StopTestRequest(BaseModel):
    """Request model for stopping a test."""

    force: bool = Field(default=False, description="Force stop immediately")
