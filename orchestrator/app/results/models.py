"""Models for result data structures.

Defines the structure of data stored in the compressed blobs:
- DeviceResultData: Test results (JMeter, functional, policy)
- DeviceStatsData: Stats collected during execution
- DeviceExecutionData: Execution status (command success/failure)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any


@dataclass
class JMeterResult:
    """JMeter load test results."""

    success: bool
    error_message: Optional[str] = None

    # Timing
    started_at: Optional[str] = None  # ISO format
    completed_at: Optional[str] = None
    duration_sec: Optional[float] = None
    warmup_sec: Optional[int] = None
    measured_sec: Optional[int] = None

    # Load configuration
    thread_count: Optional[int] = None
    ramp_up_sec: Optional[int] = None

    # Request counts
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Response time metrics (milliseconds)
    avg_response_time_ms: Optional[float] = None
    min_response_time_ms: Optional[float] = None
    max_response_time_ms: Optional[float] = None
    p50_response_time_ms: Optional[float] = None
    p90_response_time_ms: Optional[float] = None
    p95_response_time_ms: Optional[float] = None
    p99_response_time_ms: Optional[float] = None
    stddev_response_time_ms: Optional[float] = None

    # Throughput
    throughput_rps: Optional[float] = None
    bytes_sent: Optional[int] = None
    bytes_received: Optional[int] = None

    # Error breakdown
    error_counts: Optional[dict] = None  # {error_type: count}

    # Raw data (can be large - JTL content)
    raw_jtl: Optional[str] = None
    jtl_file_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": self.duration_sec,
            "warmup_sec": self.warmup_sec,
            "measured_sec": self.measured_sec,
            "thread_count": self.thread_count,
            "ramp_up_sec": self.ramp_up_sec,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "avg_response_time_ms": self.avg_response_time_ms,
            "min_response_time_ms": self.min_response_time_ms,
            "max_response_time_ms": self.max_response_time_ms,
            "p50_response_time_ms": self.p50_response_time_ms,
            "p90_response_time_ms": self.p90_response_time_ms,
            "p95_response_time_ms": self.p95_response_time_ms,
            "p99_response_time_ms": self.p99_response_time_ms,
            "stddev_response_time_ms": self.stddev_response_time_ms,
            "throughput_rps": self.throughput_rps,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "error_counts": self.error_counts,
            "raw_jtl": self.raw_jtl,
            "jtl_file_path": self.jtl_file_path,
        }


@dataclass
class FunctionalTestResult:
    """Functional/policy test results for a package."""

    package_id: int
    package_name: str
    package_type: str  # "functional", "policy"

    success: bool
    error_message: Optional[str] = None

    # Timing
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_sec: Optional[float] = None

    # Test counts
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0

    # Individual test results
    test_results: Optional[list[dict]] = None
    # Each: {name, status, duration_ms, error_message}

    # Raw output
    raw_output: Optional[str] = None
    result_file_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "package_id": self.package_id,
            "package_name": self.package_name,
            "package_type": self.package_type,
            "success": self.success,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": self.duration_sec,
            "tests_total": self.tests_total,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_skipped": self.tests_skipped,
            "test_results": self.test_results,
            "raw_output": self.raw_output,
            "result_file_path": self.result_file_path,
        }


@dataclass
class DeviceResultData:
    """
    Test results for a device phase (functional/policy tests only).

    Stored in *_device_result_blob as compressed dict.
    JMeter results are stored separately in jmeter_device_result_blob.

    Structure:
    {
        "pkg_<id>": FunctionalTestResult,
        ...
    }
    """

    functional_results: dict[int, FunctionalTestResult] = field(default_factory=dict)

    # Metadata
    phase: Optional[str] = None
    loadprofile: Optional[str] = None
    collected_at: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "phase": self.phase,
            "loadprofile": self.loadprofile,
            "collected_at": self.collected_at,
        }

        for pkg_id, func_result in self.functional_results.items():
            result[f"pkg_{pkg_id}"] = func_result.to_dict()

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceResultData":
        instance = cls(
            phase=data.get("phase"),
            loadprofile=data.get("loadprofile"),
            collected_at=data.get("collected_at"),
        )

        for key, value in data.items():
            if key.startswith("pkg_") and isinstance(value, dict):
                pkg_id = int(key.replace("pkg_", ""))
                instance.functional_results[pkg_id] = FunctionalTestResult(**value)

        return instance


@dataclass
class JMeterResultData:
    """
    JMeter load test results.

    Stored in jmeter_device_result_blob as compressed dict.
    Separate from phase device results since JMeter runs on load generator machine.

    Structure:
    {
        "jmeter": JMeterResult,
        "package_id": <jmeter_package_id>
    }
    """

    jmeter: Optional[JMeterResult] = None
    package_id: Optional[int] = None  # JMeter package ID from lab.jmeter_package_grpid

    # Metadata
    phase: Optional[str] = None
    loadprofile: Optional[str] = None
    collected_at: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "phase": self.phase,
            "loadprofile": self.loadprofile,
            "collected_at": self.collected_at,
            "package_id": self.package_id,
        }

        if self.jmeter:
            result["jmeter"] = self.jmeter.to_dict()

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "JMeterResultData":
        instance = cls(
            phase=data.get("phase"),
            loadprofile=data.get("loadprofile"),
            collected_at=data.get("collected_at"),
            package_id=data.get("package_id"),
        )

        if "jmeter" in data:
            instance.jmeter = JMeterResult(**data["jmeter"])

        return instance


@dataclass
class SystemStats:
    """System-level stats during test execution."""

    # Time series data (list of samples)
    # Each sample: {timestamp, cpu_percent, memory_percent, ...}
    samples: list[dict] = field(default_factory=list)

    # Aggregated metrics
    avg_cpu_percent: Optional[float] = None
    max_cpu_percent: Optional[float] = None
    min_cpu_percent: Optional[float] = None
    avg_memory_percent: Optional[float] = None
    max_memory_percent: Optional[float] = None
    avg_disk_io_read_mbps: Optional[float] = None
    avg_disk_io_write_mbps: Optional[float] = None
    avg_network_rx_mbps: Optional[float] = None
    avg_network_tx_mbps: Optional[float] = None

    # Collection info
    sample_interval_sec: int = 1
    total_samples: int = 0

    def to_dict(self) -> dict:
        return {
            "samples": self.samples,
            "avg_cpu_percent": self.avg_cpu_percent,
            "max_cpu_percent": self.max_cpu_percent,
            "min_cpu_percent": self.min_cpu_percent,
            "avg_memory_percent": self.avg_memory_percent,
            "max_memory_percent": self.max_memory_percent,
            "avg_disk_io_read_mbps": self.avg_disk_io_read_mbps,
            "avg_disk_io_write_mbps": self.avg_disk_io_write_mbps,
            "avg_network_rx_mbps": self.avg_network_rx_mbps,
            "avg_network_tx_mbps": self.avg_network_tx_mbps,
            "sample_interval_sec": self.sample_interval_sec,
            "total_samples": self.total_samples,
        }


@dataclass
class EmulatorStats:
    """CPU emulator stats during load test."""

    # Iteration metrics
    total_iterations: int = 0
    avg_iteration_time_ms: Optional[float] = None
    min_iteration_time_ms: Optional[float] = None
    max_iteration_time_ms: Optional[float] = None
    stddev_iteration_time_ms: Optional[float] = None
    p50_iteration_time_ms: Optional[float] = None
    p90_iteration_time_ms: Optional[float] = None
    p99_iteration_time_ms: Optional[float] = None

    # CPU target tracking
    target_cpu_percent: Optional[float] = None
    achieved_cpu_percent: Optional[float] = None

    # Time series (if collected)
    iteration_samples: Optional[list[dict]] = None

    def to_dict(self) -> dict:
        return {
            "total_iterations": self.total_iterations,
            "avg_iteration_time_ms": self.avg_iteration_time_ms,
            "min_iteration_time_ms": self.min_iteration_time_ms,
            "max_iteration_time_ms": self.max_iteration_time_ms,
            "stddev_iteration_time_ms": self.stddev_iteration_time_ms,
            "p50_iteration_time_ms": self.p50_iteration_time_ms,
            "p90_iteration_time_ms": self.p90_iteration_time_ms,
            "p99_iteration_time_ms": self.p99_iteration_time_ms,
            "target_cpu_percent": self.target_cpu_percent,
            "achieved_cpu_percent": self.achieved_cpu_percent,
            "iteration_samples": self.iteration_samples,
        }


@dataclass
class DeviceStatsData:
    """
    All stats collected during phase execution.

    Stored in *_device_stats_blob as compressed dict.

    Structure:
    {
        "system": SystemStats,
        "emulator": EmulatorStats,
        "pkg_<id>": {package-specific stats}
    }
    """

    system: Optional[SystemStats] = None
    emulator: Optional[EmulatorStats] = None
    package_stats: dict[int, dict] = field(default_factory=dict)

    # Metadata
    phase: Optional[str] = None
    loadprofile: Optional[str] = None
    collected_at: Optional[str] = None
    collection_duration_sec: Optional[float] = None

    def to_dict(self) -> dict:
        result = {
            "phase": self.phase,
            "loadprofile": self.loadprofile,
            "collected_at": self.collected_at,
            "collection_duration_sec": self.collection_duration_sec,
        }

        if self.system:
            result["system"] = self.system.to_dict()

        if self.emulator:
            result["emulator"] = self.emulator.to_dict()

        for pkg_id, stats in self.package_stats.items():
            result[f"pkg_{pkg_id}"] = stats

        return result


@dataclass
class ExecutionCommand:
    """Result of executing a single command."""

    command: str
    success: bool
    exit_code: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_sec: Optional[float] = None

    stdout: Optional[str] = None
    stderr: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "success": self.success,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": self.duration_sec,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_message": self.error_message,
        }


@dataclass
class DeviceExecutionData:
    """
    Execution results for all commands in a phase.

    Stored in *_device_execution_blob as compressed dict.
    Meaningful only if execution succeeded - indicates whether
    result and stats blobs contain valid data.

    Structure:
    {
        "jmeter": ExecutionCommand,
        "pkg_<id>": ExecutionCommand,
        "overall_success": bool
    }
    """

    jmeter_execution: Optional[ExecutionCommand] = None
    package_executions: dict[int, ExecutionCommand] = field(default_factory=dict)

    overall_success: bool = False
    phase: Optional[str] = None
    loadprofile: Optional[str] = None
    executed_at: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "overall_success": self.overall_success,
            "phase": self.phase,
            "loadprofile": self.loadprofile,
            "executed_at": self.executed_at,
        }

        if self.jmeter_execution:
            result["jmeter"] = self.jmeter_execution.to_dict()

        for pkg_id, exec_result in self.package_executions.items():
            result[f"pkg_{pkg_id}"] = exec_result.to_dict()

        return result


@dataclass
class PhaseResults:
    """
    Complete results for a phase, ready to store in DB.

    Combines all blob types for a phase.
    Note: JMeter results are stored separately in jmeter_* blobs.
    """

    phase: str  # "base", "initial", "upgrade"
    loadprofile: str

    # Data to be compressed and stored (target device)
    result_data: Optional[DeviceResultData] = None
    stats_data: Optional[DeviceStatsData] = None
    execution_data: Optional[DeviceExecutionData] = None
    logs_data: Optional[dict] = None  # Raw logs if error occurred

    # JMeter data (load generator machine) - stored in jmeter_* blobs
    jmeter_result_data: Optional[JMeterResultData] = None
    jmeter_stats_data: Optional[DeviceStatsData] = None  # Load gen machine stats
    jmeter_execution_data: Optional[DeviceExecutionData] = None
    jmeter_logs_data: Optional[dict] = None

    # Compressed blobs - target device (populated by compress())
    result_blob: Optional[bytes] = None
    stats_blob: Optional[bytes] = None
    execution_blob: Optional[bytes] = None
    logs_blob: Optional[bytes] = None

    # Compressed blobs - JMeter/load generator (populated by compress())
    jmeter_result_blob: Optional[bytes] = None
    jmeter_stats_blob: Optional[bytes] = None
    jmeter_execution_blob: Optional[bytes] = None
    jmeter_logs_blob: Optional[bytes] = None

    def compress(self) -> None:
        """Compress all data to blobs."""
        from app.results.compression import compress_dict

        # Target device blobs
        if self.result_data:
            self.result_blob = compress_dict(self.result_data.to_dict())

        if self.stats_data:
            self.stats_blob = compress_dict(self.stats_data.to_dict())

        if self.execution_data:
            self.execution_blob = compress_dict(self.execution_data.to_dict())

        if self.logs_data:
            self.logs_blob = compress_dict(self.logs_data)

        # JMeter/load generator blobs
        if self.jmeter_result_data:
            self.jmeter_result_blob = compress_dict(self.jmeter_result_data.to_dict())

        if self.jmeter_stats_data:
            self.jmeter_stats_blob = compress_dict(self.jmeter_stats_data.to_dict())

        if self.jmeter_execution_data:
            self.jmeter_execution_blob = compress_dict(self.jmeter_execution_data.to_dict())

        if self.jmeter_logs_data:
            self.jmeter_logs_blob = compress_dict(self.jmeter_logs_data)

    def get_blob_field_name(self, blob_type: str) -> str:
        """Get ORM field name for a blob type."""
        return f"{self.phase}_device_{blob_type}_blob"

    def get_jmeter_blob_field_name(self, blob_type: str) -> str:
        """Get ORM field name for a JMeter blob type."""
        return f"jmeter_device_{blob_type}_blob"
