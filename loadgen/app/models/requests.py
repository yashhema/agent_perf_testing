"""Pydantic request models for load generator service."""

from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class StartJMeterRequest(BaseModel):
    """Request to start JMeter test."""

    target_id: int = Field(..., description="Target server ID")
    test_run_id: str = Field(..., description="Test run identifier")
    jmx_file: str = Field(..., description="Path to JMX test plan file")
    thread_count: int = Field(..., gt=0, description="Number of threads")
    ramp_up_sec: int = Field(default=60, ge=0, description="Ramp-up time in seconds")
    loop_count: int = Field(default=-1, description="Loop count (-1 for infinite)")
    duration_sec: Optional[int] = Field(None, description="Duration in seconds")
    emulator_host: str = Field(..., description="Emulator service host")
    emulator_port: int = Field(default=8080, description="Emulator service port")
    jmeter_port: Optional[int] = Field(None, description="JMeter port (auto-assigned if None)")
    additional_props: Dict[str, str] = Field(
        default_factory=dict, description="Additional JMeter properties"
    )


class StopJMeterRequest(BaseModel):
    """Request to stop JMeter test."""

    target_id: int = Field(..., description="Target server ID")
    force: bool = Field(default=False, description="Force stop immediately")


class GetResultsRequest(BaseModel):
    """Request to get JMeter results."""

    target_id: int = Field(..., description="Target server ID")
    include_raw: bool = Field(default=False, description="Include raw JTL data")


class UpdateThreadsRequest(BaseModel):
    """Request to update thread count on running test."""

    target_id: int = Field(..., description="Target server ID")
    thread_count: int = Field(..., gt=0, description="New thread count")
