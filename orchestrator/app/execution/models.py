"""Models for test execution."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class ExecutionStatus(str, Enum):
    """Status of test execution."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    CALIBRATING = "calibrating"
    DEPLOYING = "deploying"
    RUNNING = "running"
    COLLECTING = "collecting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionPhase(str, Enum):
    """Current phase of execution."""

    INIT = "init"
    VM_PREPARATION = "vm_preparation"
    EMULATOR_DEPLOYMENT = "emulator_deployment"
    CALIBRATION = "calibration"
    LOAD_TEST = "load_test"
    RESULT_COLLECTION = "result_collection"
    CLEANUP = "cleanup"
    DONE = "done"


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for test execution."""

    # Test parameters
    test_duration_sec: int = 300
    warmup_sec: int = 30
    cooldown_sec: int = 30

    # Retry settings
    max_retries: int = 3
    retry_delay_sec: int = 60

    # Timeouts
    vm_operation_timeout_sec: int = 300
    deployment_timeout_sec: int = 600
    calibration_timeout_sec: int = 900
    test_timeout_sec: int = 3600

    # Cleanup behavior
    cleanup_on_failure: bool = True
    revert_snapshot_on_failure: bool = True

    # Parallel execution
    max_parallel_targets: int = 5


@dataclass(frozen=True)
class TargetInfo:
    """Information about a test target."""

    target_id: int
    hostname: str
    ip_address: str
    os_type: str  # "linux" or "windows"
    cpu_count: int
    memory_gb: float
    vm_name: Optional[str] = None
    vcenter_host: Optional[str] = None
    snapshot_name: Optional[str] = None


@dataclass(frozen=True)
class EmulatorDeployment:
    """Emulator deployment information."""

    target_id: int
    host: str
    port: int
    deployed_at: datetime
    version: Optional[str] = None
    pid: Optional[int] = None


@dataclass(frozen=True)
class PhaseResult:
    """Result of an execution phase."""

    phase: ExecutionPhase
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    error_message: Optional[str] = None
    details: Optional[str] = None


@dataclass(frozen=True)
class ExecutionMetrics:
    """Metrics collected during execution."""

    # Timing metrics
    total_duration_sec: float
    calibration_duration_sec: Optional[float] = None
    deployment_duration_sec: Optional[float] = None
    test_duration_sec: Optional[float] = None

    # Test metrics
    total_requests: Optional[int] = None
    successful_requests: Optional[int] = None
    failed_requests: Optional[int] = None
    avg_response_time_ms: Optional[float] = None
    p50_response_time_ms: Optional[float] = None
    p90_response_time_ms: Optional[float] = None
    p99_response_time_ms: Optional[float] = None
    throughput_rps: Optional[float] = None

    # Resource metrics
    avg_cpu_percent: Optional[float] = None
    max_cpu_percent: Optional[float] = None
    avg_memory_percent: Optional[float] = None
    max_memory_percent: Optional[float] = None


@dataclass
class ExecutionState:
    """Mutable state of test execution."""

    execution_id: str
    test_run_id: int
    target_id: int
    baseline_id: int

    # Current state
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_phase: ExecutionPhase = ExecutionPhase.INIT
    retry_count: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Phase tracking
    phase_results: List[PhaseResult] = field(default_factory=list)

    # Deployment info
    emulator_deployment: Optional[EmulatorDeployment] = None

    # Calibration results
    calibration_thread_count: Optional[int] = None
    calibration_achieved_cpu: Optional[float] = None

    # Test results
    jmeter_test_id: Optional[str] = None
    metrics: Optional[ExecutionMetrics] = None

    # Error tracking
    last_error: Optional[str] = None
    error_phase: Optional[ExecutionPhase] = None


@dataclass(frozen=True)
class ExecutionRequest:
    """Request to execute a test."""

    test_run_id: int
    target_id: int
    baseline_id: int
    target_info: TargetInfo
    load_profile: str  # "low", "medium", "high"
    config: ExecutionConfig = field(default_factory=ExecutionConfig)


@dataclass(frozen=True)
class ExecutionResult:
    """Final result of test execution."""

    execution_id: str
    test_run_id: int
    target_id: int
    baseline_id: int

    # Status
    status: ExecutionStatus
    load_profile: str

    # Timing
    started_at: datetime
    completed_at: datetime
    total_duration_sec: float

    # Calibration
    thread_count: int
    target_cpu_percent: float
    achieved_cpu_percent: float

    # Test metrics
    metrics: Optional[ExecutionMetrics] = None

    # Phase history
    phase_results: List[PhaseResult] = field(default_factory=list)

    # Error info
    error_message: Optional[str] = None
    error_phase: Optional[ExecutionPhase] = None


@dataclass(frozen=True)
class ExecutionProgress:
    """Progress update for execution."""

    execution_id: str
    status: ExecutionStatus
    current_phase: ExecutionPhase
    phase_progress_percent: float
    overall_progress_percent: float
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class ExecutionEvent:
    """Event during execution."""

    execution_id: str
    event_type: str
    phase: ExecutionPhase
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Optional[str] = None
    is_error: bool = False
