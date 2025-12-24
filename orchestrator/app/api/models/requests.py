"""Pydantic request models for API endpoints."""

from typing import Optional
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    OSFamily,
    ServerType,
    BaselineType,
    LoadProfile,
    RunMode,
)


# ============================================================
# Lab Requests
# ============================================================


class CreateLabRequest(BaseModel):
    """Request model for creating a lab."""

    name: str = Field(..., min_length=1, max_length=255)
    lab_type: str = Field(..., pattern="^(server|euc)$")
    description: Optional[str] = Field(None, max_length=2000)


class UpdateLabRequest(BaseModel):
    """Request model for updating a lab."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    lab_type: Optional[str] = Field(None, pattern="^(server|euc)$")
    description: Optional[str] = Field(None, max_length=2000)


# ============================================================
# Server Requests
# ============================================================


class CreateServerRequest(BaseModel):
    """Request model for creating a server."""

    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=7, max_length=45)
    os_family: OSFamily
    server_type: ServerType
    lab_id: int = Field(..., gt=0)
    ssh_username: Optional[str] = Field(None, max_length=100)
    ssh_key_path: Optional[str] = Field(None, max_length=500)
    winrm_username: Optional[str] = Field(None, max_length=100)
    emulator_port: int = Field(8080, ge=1, le=65535)
    loadgen_service_port: int = Field(8090, ge=1, le=65535)
    is_active: bool = True


class UpdateServerRequest(BaseModel):
    """Request model for updating a server."""

    hostname: Optional[str] = Field(None, min_length=1, max_length=255)
    ip_address: Optional[str] = Field(None, min_length=7, max_length=45)
    os_family: Optional[OSFamily] = None
    server_type: Optional[ServerType] = None
    ssh_username: Optional[str] = Field(None, max_length=100)
    ssh_key_path: Optional[str] = Field(None, max_length=500)
    winrm_username: Optional[str] = Field(None, max_length=100)
    emulator_port: Optional[int] = Field(None, ge=1, le=65535)
    loadgen_service_port: Optional[int] = Field(None, ge=1, le=65535)
    is_active: Optional[bool] = None


# ============================================================
# Baseline Requests
# ============================================================


class BaselineConfigRequest(BaseModel):
    """Request model for baseline configuration."""

    # vSphere specific
    vcenter_host: Optional[str] = Field(None, max_length=255)
    datacenter: Optional[str] = Field(None, max_length=255)
    snapshot_name: Optional[str] = Field(None, max_length=255)

    # AWS specific
    ami_id: Optional[str] = Field(None, max_length=255)
    instance_type: Optional[str] = Field(None, max_length=50)
    region: Optional[str] = Field(None, max_length=50)

    # Intune/Jamf specific
    policy_id: Optional[str] = Field(None, max_length=255)
    group_id: Optional[str] = Field(None, max_length=255)


class CreateBaselineRequest(BaseModel):
    """Request model for creating a baseline."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    baseline_type: BaselineType
    baseline_conf: BaselineConfigRequest
    lab_id: int = Field(..., gt=0)


class UpdateBaselineRequest(BaseModel):
    """Request model for updating a baseline."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    baseline_conf: Optional[BaselineConfigRequest] = None


# ============================================================
# Test Run Requests
# ============================================================


class CreateTestRunRequest(BaseModel):
    """Request model for creating a test run."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    lab_id: int = Field(..., gt=0)
    req_loadprofile: list[LoadProfile] = Field(..., min_length=1)
    warmup_sec: int = Field(300, ge=0)
    measured_sec: int = Field(10800, ge=60)
    analysis_trim_sec: int = Field(300, ge=0)
    repetitions: int = Field(1, ge=1, le=100)
    loadgenerator_package_grpid_lst: list[int] = Field(..., min_length=1)

    @field_validator("req_loadprofile")
    @classmethod
    def validate_loadprofile_not_empty(cls, v: list[LoadProfile]) -> list[LoadProfile]:
        """Ensure load profile list is not empty."""
        if not v:
            raise ValueError("req_loadprofile must contain at least one profile")
        return v


class UpdateTestRunRequest(BaseModel):
    """Request model for updating a test run."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    req_loadprofile: Optional[list[LoadProfile]] = Field(None, min_length=1)
    warmup_sec: Optional[int] = Field(None, ge=0)
    measured_sec: Optional[int] = Field(None, ge=60)
    analysis_trim_sec: Optional[int] = Field(None, ge=0)
    repetitions: Optional[int] = Field(None, ge=1, le=100)


class CreateTestRunTargetRequest(BaseModel):
    """Request model for creating a test run target association."""

    target_id: int = Field(..., gt=0)
    loadgenerator_id: int = Field(..., gt=0)
    jmeter_port: Optional[int] = Field(None, ge=1024, le=65535)
    jmx_file_path: Optional[str] = Field(None, max_length=500)
    base_baseline_id: Optional[int] = Field(None, gt=0)
    initial_baseline_id: Optional[int] = Field(None, gt=0)
    upgrade_baseline_id: Optional[int] = Field(None, gt=0)


# ============================================================
# Execution Requests
# ============================================================


class CreateExecutionRequest(BaseModel):
    """Request model for creating a test run execution."""

    test_run_id: int = Field(..., gt=0)
    run_mode: RunMode = RunMode.CONTINUOUS
    immediate_run: bool = False


class ExecutionActionRequest(BaseModel):
    """Request model for execution actions."""

    action: str = Field(..., pattern="^(continue|pause|abandon|status)$")
