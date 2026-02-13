"""Models for runner protocol.

Runner is a lightweight agent installed on EUC devices that:
1. Wakes up (after restart or on schedule)
2. Asks orchestrator "what's my current state?"
3. Performs actions based on state
4. Reports results back to orchestrator
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class RunnerState(str, Enum):
    """Current state the runner should be in."""

    IDLE = "idle"  # Nothing to do
    AWAITING_PACKAGE_INSTALL = "awaiting_package_install"  # MDM install pending
    REPORT_PACKAGE_MEASUREMENT = "report_package_measurement"  # Report installed versions
    EXECUTE_LOAD = "execute_load"  # Run load test
    EXECUTE_FUNCTIONAL = "execute_functional"  # Run functional tests
    COLLECT_STATS = "collect_stats"  # Collect stats/logs
    COMPLETE = "complete"  # Phase complete


class RunnerAction(str, Enum):
    """Action runner should take."""

    WAIT = "wait"  # Wait and check back later
    MEASURE_PACKAGES = "measure_packages"  # Check installed package versions
    RUN_LOAD_TEST = "run_load_test"  # Execute load test
    RUN_FUNCTIONAL_TEST = "run_functional_test"  # Execute functional test
    COLLECT_STATS = "collect_stats"  # Collect performance stats
    COLLECT_LOGS = "collect_logs"  # Collect logs
    SHUTDOWN = "shutdown"  # Shutdown/complete


@dataclass
class RunnerStateQuery:
    """
    Query from runner asking for its current state.

    Runner identifies itself by IP or FQDN.
    """

    # Device identification (at least one required)
    device_ip: Optional[str] = None
    device_fqdn: Optional[str] = None
    device_hostname: Optional[str] = None

    # Runner metadata
    runner_version: Optional[str] = None
    os_info: Optional[str] = None
    uptime_sec: Optional[int] = None

    # Timestamp
    query_timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RunnerStateResponse:
    """
    Response to runner with its current state and action.

    Tells runner what to do next.
    """

    # Identification
    device_id: Optional[str] = None
    execution_id: Optional[str] = None
    workflow_state_id: Optional[int] = None

    # Current state
    state: RunnerState = RunnerState.IDLE
    action: RunnerAction = RunnerAction.WAIT

    # Phase context
    current_phase: Optional[str] = None  # "base", "initial", "upgrade"
    loadprofile: Optional[str] = None  # "low", "medium", "high"

    # What to measure/execute
    packages_to_measure: Optional[list[dict]] = None  # From *_package_lst
    load_test_config: Optional[dict] = None  # Thread count, duration, etc.
    functional_test_config: Optional[dict] = None  # Test scripts to run

    # Timing
    check_back_after_sec: int = 60  # How long to wait before next query

    # Message
    message: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "device_id": self.device_id,
            "execution_id": self.execution_id,
            "workflow_state_id": self.workflow_state_id,
            "state": self.state.value,
            "action": self.action.value,
            "current_phase": self.current_phase,
            "loadprofile": self.loadprofile,
            "packages_to_measure": self.packages_to_measure,
            "load_test_config": self.load_test_config,
            "functional_test_config": self.functional_test_config,
            "check_back_after_sec": self.check_back_after_sec,
            "message": self.message,
        }


@dataclass
class PackageMeasurement:
    """Single package measurement from runner."""

    package_id: int
    package_name: str
    expected_version: str

    # Measurement result
    is_installed: bool = False
    measured_version: Optional[str] = None
    version_matched: bool = False

    # Verification details
    version_check_command: Optional[str] = None
    version_check_output: Optional[str] = None
    version_check_exit_code: Optional[int] = None

    # Error info
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "package_id": self.package_id,
            "package_name": self.package_name,
            "expected_version": self.expected_version,
            "is_installed": self.is_installed,
            "measured_version": self.measured_version,
            "version_matched": self.version_matched,
            "version_check_command": self.version_check_command,
            "version_check_output": self.version_check_output,
            "version_check_exit_code": self.version_check_exit_code,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PackageMeasurement":
        return cls(
            package_id=data["package_id"],
            package_name=data["package_name"],
            expected_version=data["expected_version"],
            is_installed=data.get("is_installed", False),
            measured_version=data.get("measured_version"),
            version_matched=data.get("version_matched", False),
            version_check_command=data.get("version_check_command"),
            version_check_output=data.get("version_check_output"),
            version_check_exit_code=data.get("version_check_exit_code"),
            error_message=data.get("error_message"),
        )


@dataclass
class RunnerMeasurementReport:
    """
    Package measurement report from runner.

    Runner reports what packages are installed and their versions.
    """

    # Device identification
    device_ip: Optional[str] = None
    device_fqdn: Optional[str] = None
    workflow_state_id: Optional[int] = None

    # Measurement results
    measurements: list[PackageMeasurement] = field(default_factory=list)
    all_matched: bool = False

    # Timing
    measured_at: datetime = field(default_factory=datetime.utcnow)
    measurement_duration_sec: Optional[float] = None

    # System info at measurement time
    system_uptime_sec: Optional[int] = None
    pending_reboot: bool = False

    def to_dict(self) -> dict:
        return {
            "device_ip": self.device_ip,
            "device_fqdn": self.device_fqdn,
            "workflow_state_id": self.workflow_state_id,
            "measurements": [m.to_dict() for m in self.measurements],
            "all_matched": self.all_matched,
            "measured_at": self.measured_at.isoformat(),
            "measurement_duration_sec": self.measurement_duration_sec,
            "system_uptime_sec": self.system_uptime_sec,
            "pending_reboot": self.pending_reboot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunnerMeasurementReport":
        return cls(
            device_ip=data.get("device_ip"),
            device_fqdn=data.get("device_fqdn"),
            workflow_state_id=data.get("workflow_state_id"),
            measurements=[
                PackageMeasurement.from_dict(m)
                for m in data.get("measurements", [])
            ],
            all_matched=data.get("all_matched", False),
            measured_at=datetime.fromisoformat(data["measured_at"])
            if data.get("measured_at")
            else datetime.utcnow(),
            measurement_duration_sec=data.get("measurement_duration_sec"),
            system_uptime_sec=data.get("system_uptime_sec"),
            pending_reboot=data.get("pending_reboot", False),
        )


@dataclass
class RunnerLoadResult:
    """
    Load test result from runner.

    Runner reports results after executing load test.
    """

    # Device identification
    device_ip: Optional[str] = None
    device_fqdn: Optional[str] = None
    workflow_state_id: Optional[int] = None

    # Test identification
    phase: str = ""  # "base", "initial", "upgrade"
    loadprofile: str = ""  # "low", "medium", "high"

    # Execution status
    success: bool = False
    error_message: Optional[str] = None

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    warmup_sec: Optional[int] = None
    measured_sec: Optional[int] = None

    # Load test results
    thread_count: Optional[int] = None
    total_iterations: Optional[int] = None
    successful_iterations: Optional[int] = None
    failed_iterations: Optional[int] = None

    # Performance metrics
    avg_iteration_time_ms: Optional[float] = None
    min_iteration_time_ms: Optional[float] = None
    max_iteration_time_ms: Optional[float] = None
    p50_iteration_time_ms: Optional[float] = None
    p90_iteration_time_ms: Optional[float] = None
    p99_iteration_time_ms: Optional[float] = None
    stddev_iteration_time_ms: Optional[float] = None

    # Resource metrics during test
    avg_cpu_percent: Optional[float] = None
    max_cpu_percent: Optional[float] = None
    avg_memory_percent: Optional[float] = None
    max_memory_percent: Optional[float] = None

    # Raw data paths (if collected)
    result_file_path: Optional[str] = None
    stats_file_path: Optional[str] = None
    logs_file_path: Optional[str] = None

    # Raw data (if small enough to include)
    result_data: Optional[dict] = None
    stats_data: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "device_ip": self.device_ip,
            "device_fqdn": self.device_fqdn,
            "workflow_state_id": self.workflow_state_id,
            "phase": self.phase,
            "loadprofile": self.loadprofile,
            "success": self.success,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_sec": self.duration_sec,
            "warmup_sec": self.warmup_sec,
            "measured_sec": self.measured_sec,
            "thread_count": self.thread_count,
            "total_iterations": self.total_iterations,
            "successful_iterations": self.successful_iterations,
            "failed_iterations": self.failed_iterations,
            "avg_iteration_time_ms": self.avg_iteration_time_ms,
            "min_iteration_time_ms": self.min_iteration_time_ms,
            "max_iteration_time_ms": self.max_iteration_time_ms,
            "p50_iteration_time_ms": self.p50_iteration_time_ms,
            "p90_iteration_time_ms": self.p90_iteration_time_ms,
            "p99_iteration_time_ms": self.p99_iteration_time_ms,
            "stddev_iteration_time_ms": self.stddev_iteration_time_ms,
            "avg_cpu_percent": self.avg_cpu_percent,
            "max_cpu_percent": self.max_cpu_percent,
            "avg_memory_percent": self.avg_memory_percent,
            "max_memory_percent": self.max_memory_percent,
            "result_file_path": self.result_file_path,
            "stats_file_path": self.stats_file_path,
            "logs_file_path": self.logs_file_path,
            "result_data": self.result_data,
            "stats_data": self.stats_data,
        }


@dataclass
class RunnerFunctionalResult:
    """
    Functional test result from runner.

    Runner reports results after executing functional/policy tests.
    """

    # Device identification
    device_ip: Optional[str] = None
    device_fqdn: Optional[str] = None
    workflow_state_id: Optional[int] = None

    # Test identification
    phase: str = ""
    package_group_id: int = 0
    package_group_name: Optional[str] = None
    test_name: Optional[str] = None

    # Execution status
    success: bool = False
    error_message: Optional[str] = None

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: Optional[float] = None

    # Test results
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    # Detailed results
    test_results: Optional[list[dict]] = None  # Individual test outcomes
    result_file_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "device_ip": self.device_ip,
            "device_fqdn": self.device_fqdn,
            "workflow_state_id": self.workflow_state_id,
            "phase": self.phase,
            "package_group_id": self.package_group_id,
            "package_group_name": self.package_group_name,
            "test_name": self.test_name,
            "success": self.success,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_sec": self.duration_sec,
            "tests_total": self.tests_total,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_skipped": self.tests_skipped,
            "test_results": self.test_results,
            "result_file_path": self.result_file_path,
        }
