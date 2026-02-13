"""Pydantic response models for API endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import (
    OSFamily,
    ServerRole,
    BaselineType,
    LoadProfile,
    RunMode,
    ExecutionStatus,
    ExecutionPhase,
    PhaseState,
    CalibrationStatus,
)


# ============================================================
# Lab Responses
# ============================================================


class LabResponse(BaseModel):
    """Response model for a lab."""

    id: int
    name: str
    lab_type: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LabListResponse(BaseModel):
    """Response model for a list of labs."""

    labs: list[LabResponse]
    total: int


# ============================================================
# Server Responses
# ============================================================


class ServerResponse(BaseModel):
    """Response model for a server."""

    id: int
    hostname: str
    ip_address: str
    os_family: OSFamily
    server_type: ServerRole
    lab_id: int
    ssh_username: Optional[str]
    ssh_key_path: Optional[str]
    winrm_username: Optional[str]
    emulator_port: int
    loadgen_service_port: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServerListResponse(BaseModel):
    """Response model for a list of servers."""

    servers: list[ServerResponse]
    total: int


# ============================================================
# Baseline Responses
# ============================================================


class BaselineConfigResponse(BaseModel):
    """Response model for baseline configuration."""

    vcenter_host: Optional[str] = None
    datacenter: Optional[str] = None
    snapshot_name: Optional[str] = None
    ami_id: Optional[str] = None
    instance_type: Optional[str] = None
    region: Optional[str] = None
    policy_id: Optional[str] = None
    group_id: Optional[str] = None

    model_config = {"from_attributes": True}


class BaselineResponse(BaseModel):
    """Response model for a baseline."""

    id: int
    name: str
    description: Optional[str]
    baseline_type: BaselineType
    baseline_conf: BaselineConfigResponse
    lab_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BaselineListResponse(BaseModel):
    """Response model for a list of baselines."""

    baselines: list[BaselineResponse]
    total: int


# ============================================================
# Test Run Responses
# ============================================================


class TestRunTargetResponse(BaseModel):
    """Response model for a test run target."""

    id: int
    test_run_id: int
    target_id: int
    loadgenerator_id: int
    jmeter_port: Optional[int]
    jmx_file_path: Optional[str]
    base_baseline_id: Optional[int]
    initial_baseline_id: Optional[int]
    upgrade_baseline_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestRunResponse(BaseModel):
    """Response model for a test run."""

    id: int
    name: str
    description: Optional[str]
    lab_id: int
    req_loadprofile: list[LoadProfile]
    warmup_sec: int
    measured_sec: int
    analysis_trim_sec: int
    repetitions: int
    loadgenerator_package_grpid_lst: list[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestRunDetailResponse(BaseModel):
    """Response model for a test run with targets."""

    id: int
    name: str
    description: Optional[str]
    lab_id: int
    req_loadprofile: list[LoadProfile]
    warmup_sec: int
    measured_sec: int
    analysis_trim_sec: int
    repetitions: int
    loadgenerator_package_grpid_lst: list[int]
    targets: list[TestRunTargetResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestRunListResponse(BaseModel):
    """Response model for a list of test runs."""

    test_runs: list[TestRunResponse]
    total: int


# ============================================================
# Execution Responses
# ============================================================


class ExecutionResponse(BaseModel):
    """Response model for a test run execution."""

    id: UUID
    test_run_id: int
    run_mode: RunMode
    status: ExecutionStatus
    current_loadprofile: Optional[LoadProfile]
    current_repetition: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExecutionCreateResponse(BaseModel):
    """Response model for execution creation."""

    id: UUID
    message: str
    calibration_started: bool = False


class ExecutionListResponse(BaseModel):
    """Response model for a list of executions."""

    executions: list[ExecutionResponse]
    total: int


class ActionResultResponse(BaseModel):
    """Response model for execution action result."""

    success: bool
    message: str
    new_status: Optional[ExecutionStatus] = None


class ErrorRecordResponse(BaseModel):
    """Response model for an error record."""

    timestamp: datetime
    phase: ExecutionPhase
    state: PhaseState
    error_message: str
    retry_count: int


class WorkflowStateResponse(BaseModel):
    """Response model for execution workflow state."""

    id: int
    test_run_execution_id: UUID
    target_id: int
    loadprofile: LoadProfile
    runcount: int
    base_baseline_id: Optional[int]
    initial_baseline_id: Optional[int]
    upgrade_baseline_id: Optional[int]
    current_phase: ExecutionPhase
    phase_state: PhaseState
    retry_count: int
    max_retries: int
    error_history: list[ErrorRecordResponse]
    phase_started_at: Optional[datetime]
    phase_completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExecutionDetailResponse(BaseModel):
    """Response model for execution with workflow states."""

    id: UUID
    test_run_id: int
    run_mode: RunMode
    status: ExecutionStatus
    current_loadprofile: Optional[LoadProfile]
    current_repetition: int
    error_message: Optional[str]
    workflow_states: list[WorkflowStateResponse]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# Calibration Responses
# ============================================================


class IterationTimingResponse(BaseModel):
    """Response model for iteration timing statistics."""

    avg_iteration_time_ms: int
    stddev_iteration_time_ms: int
    min_iteration_time_ms: int
    max_iteration_time_ms: int
    iteration_sample_count: int

    model_config = {"from_attributes": True}


class CalibrationResultResponse(BaseModel):
    """Response model for a calibration result."""

    id: int
    target_id: int
    baseline_id: int
    loadprofile: LoadProfile
    thread_count: int
    cpu_count: int
    memory_gb: Decimal
    cpu_target_percent: Optional[Decimal]
    achieved_cpu_percent: Optional[Decimal]
    iteration_timing: Optional[IterationTimingResponse]
    calibration_run_id: Optional[UUID]
    calibration_status: CalibrationStatus
    calibrated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# Generic Responses
# ============================================================


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class DeleteResponse(BaseModel):
    """Response model for delete operations."""

    success: bool
    message: str
