"""Application models using dataclasses.

These are the domain models used throughout the application layer.
They are separate from ORM models to maintain clean architecture.

STRICT RULES:
- NO dictionaries for storing fields
- All fields must be properly typed
- Use Optional[] for nullable fields
- Use List[] for array fields
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.models.enums import (
    OSFamily,
    ServerType,
    LoadProfile,
    RunMode,
    ExecutionStatus,
    BaselineType,
    CalibrationStatus,
    ExecutionPhase,
    PhaseState,
)


@dataclass(frozen=True)
class Lab:
    """Laboratory/environment for testing.

    Represents a logical grouping of servers and configurations.
    """

    id: int
    name: str
    lab_type: str  # 'server' or 'euc'
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Server:
    """Server in the test infrastructure.

    Can be an app server, db server, or load generator.
    """

    id: int
    hostname: str
    ip_address: str
    os_family: OSFamily
    server_type: ServerType
    lab_id: int

    # Connection credentials
    ssh_username: Optional[str]
    ssh_key_path: Optional[str]
    winrm_username: Optional[str]

    # Service ports
    emulator_port: int
    loadgen_service_port: int

    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BaselineConfig:
    """Configuration for a baseline environment.

    Type-specific configuration stored as structured data.
    """

    # vSphere specific
    vcenter_host: Optional[str] = None
    datacenter: Optional[str] = None
    snapshot_name: Optional[str] = None

    # AWS specific
    ami_id: Optional[str] = None
    instance_type: Optional[str] = None
    region: Optional[str] = None

    # Intune/Jamf specific
    policy_id: Optional[str] = None
    group_id: Optional[str] = None


@dataclass(frozen=True)
class Baseline:
    """Baseline environment configuration.

    Represents a specific environment state (e.g., VM snapshot, AMI).
    """

    id: int
    name: str
    description: Optional[str]
    baseline_type: BaselineType
    baseline_conf: BaselineConfig
    lab_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TestRun:
    """Test run configuration.

    Defines the parameters for a performance test.
    """

    id: int
    name: str
    description: Optional[str]
    lab_id: int

    # Load profile configuration
    req_loadprofile: list[LoadProfile]
    warmup_sec: int
    measured_sec: int
    analysis_trim_sec: int
    repetitions: int

    # Load generator packages
    loadgenerator_package_grpid_lst: list[int]

    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TestRunTarget:
    """Association between test run, target server, and load generator.

    Defines which load generator will test which target server.
    """

    id: int
    test_run_id: int
    target_id: int
    loadgenerator_id: int

    # JMeter configuration
    jmeter_port: Optional[int]
    jmx_file_path: Optional[str]

    # Baseline overrides (optional, can inherit from test_run)
    base_baseline_id: Optional[int]
    initial_baseline_id: Optional[int]
    upgrade_baseline_id: Optional[int]

    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TestRunExecution:
    """Instance of a test run execution.

    Tracks the state of an active or completed test run.
    """

    id: UUID
    test_run_id: int
    run_mode: RunMode
    status: ExecutionStatus

    # Progress tracking
    current_loadprofile: Optional[LoadProfile]
    current_repetition: int

    # Error handling
    error_message: Optional[str]

    # Timestamps
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IterationTimingStats:
    """Statistics for iteration timing measurement.

    Used to calculate loop count for JMeter tests.
    """

    avg_iteration_time_ms: int
    stddev_iteration_time_ms: int
    min_iteration_time_ms: int
    max_iteration_time_ms: int
    iteration_sample_count: int


@dataclass(frozen=True)
class CalibrationResult:
    """Result of calibration for a specific target and load profile.

    Stores the optimal thread count and related metrics.
    """

    id: int
    target_id: int
    baseline_id: int
    loadprofile: LoadProfile

    # Calibration output
    thread_count: int
    cpu_count: int
    memory_gb: Decimal
    cpu_target_percent: Optional[Decimal]
    achieved_cpu_percent: Optional[Decimal]

    # Iteration timing (HIGH load profile only)
    iteration_timing: Optional[IterationTimingStats]

    calibration_run_id: Optional[UUID]
    calibration_status: CalibrationStatus
    calibrated_at: Optional[datetime]

    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorRecord:
    """Record of an error that occurred during execution."""

    timestamp: datetime
    phase: ExecutionPhase
    state: PhaseState
    error_message: str
    retry_count: int


@dataclass(frozen=True)
class ExecutionWorkflowState:
    """State of execution workflow for a specific target.

    Tracks the current phase and state of execution.
    """

    id: int
    test_run_execution_id: UUID
    target_id: int

    # Execution context
    loadprofile: LoadProfile
    runcount: int

    # Baseline references
    base_baseline_id: Optional[int]
    initial_baseline_id: Optional[int]
    upgrade_baseline_id: Optional[int]

    # Phase tracking
    current_phase: ExecutionPhase
    phase_state: PhaseState

    # Error tracking
    retry_count: int
    max_retries: int
    error_history: list[ErrorRecord]

    # Timestamps
    phase_started_at: Optional[datetime]
    phase_completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ============================================================
# Result types for service layer
# ============================================================


@dataclass(frozen=True)
class CreateExecutionResult:
    """Result of creating a test run execution."""

    success: bool
    execution_id: Optional[UUID]
    message: str
    calibration_started: bool = False


@dataclass(frozen=True)
class ActionResult:
    """Result of executing an action on a test run."""

    success: bool
    message: str
    new_status: Optional[ExecutionStatus] = None


@dataclass(frozen=True)
class ActiveExecutionInfo:
    """Summary information for an active test run execution."""

    execution_id: UUID
    test_run_id: int
    test_run_name: str
    status: ExecutionStatus
    run_mode: RunMode
    current_loadprofile: Optional[LoadProfile]
    current_repetition: int
    started_at: Optional[datetime]
