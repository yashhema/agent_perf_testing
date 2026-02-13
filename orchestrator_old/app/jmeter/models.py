"""JMeter models for load test execution."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JMeterStatus(str, Enum):
    """JMeter execution status."""

    PENDING = "pending"
    STARTING = "starting"
    WARMUP = "warmup"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class JMeterConfig:
    """Configuration for JMeter execution."""

    # Test plan
    jmx_file_path: str
    result_file_path: str = "/tmp/jmeter_results.jtl"
    log_file_path: str = "/tmp/jmeter.log"

    # Target endpoint
    target_host: str = "localhost"
    target_port: int = 8080

    # Load configuration
    thread_count: int = 10
    ramp_up_sec: int = 30
    warmup_sec: int = 300
    measured_sec: int = 600
    total_duration_sec: int = 900  # warmup + measured

    # JMeter properties
    jmeter_home: str = "/opt/jmeter"
    jvm_args: str = "-Xms512m -Xmx2g"

    # Additional properties to pass to JMeter
    properties: dict = field(default_factory=dict)

    def build_command(self) -> str:
        """Build JMeter command line."""
        cmd_parts = [
            f"{self.jmeter_home}/bin/jmeter",
            "-n",  # Non-GUI mode
            f"-t {self.jmx_file_path}",
            f"-l {self.result_file_path}",
            f"-j {self.log_file_path}",
            f"-Jthreads={self.thread_count}",
            f"-Jrampup={self.ramp_up_sec}",
            f"-Jduration={self.total_duration_sec}",
            f"-Jhost={self.target_host}",
            f"-Jport={self.target_port}",
        ]

        # Add custom properties
        for key, value in self.properties.items():
            cmd_parts.append(f"-J{key}={value}")

        return " ".join(cmd_parts)


@dataclass
class JMeterExecutionResult:
    """Result of JMeter execution."""

    status: JMeterStatus
    config: JMeterConfig

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: Optional[float] = None

    # Command execution
    command_used: Optional[str] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None

    # Result file
    result_file_path: Optional[str] = None
    result_file_exists: bool = False
    result_file_size_bytes: int = 0

    # Error info
    error_message: Optional[str] = None
    error_type: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.status == JMeterStatus.COMPLETED and self.exit_code == 0


@dataclass
class JMeterProgress:
    """Progress of JMeter execution."""

    status: JMeterStatus
    elapsed_sec: float = 0
    total_sec: float = 0
    progress_percent: float = 0

    # Metrics (if available during execution)
    requests_completed: int = 0
    requests_per_second: float = 0
    error_count: int = 0
    avg_response_time_ms: float = 0

    @property
    def is_in_warmup(self) -> bool:
        """Check if still in warmup period."""
        return self.status == JMeterStatus.WARMUP

    @property
    def is_running(self) -> bool:
        """Check if actively running (warmup or running)."""
        return self.status in (JMeterStatus.WARMUP, JMeterStatus.RUNNING)
