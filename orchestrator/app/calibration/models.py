"""Models for calibration service."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class LoadProfile(str, Enum):
    """Load profile levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CalibrationStatus(str, Enum):
    """Calibration status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class CalibrationConfig:
    """Configuration for calibration."""

    # Target CPU percentages for each profile
    cpu_target_low: float = 30.0
    cpu_target_medium: float = 50.0
    cpu_target_high: float = 70.0

    # Tolerance for accepting calibration result
    tolerance: float = 5.0  # ±5%

    # Thread count bounds
    min_threads: int = 1
    max_threads: int = 100

    # Calibration test duration
    calibration_duration_sec: int = 60

    # Maximum binary search iterations
    max_iterations: int = 10

    # Warmup before measuring
    warmup_sec: int = 10

    # Iteration timing sample size
    iteration_sample_count: int = 100


@dataclass(frozen=True)
class IterationStats:
    """Statistics for iteration timing."""

    sample_count: int
    avg_ms: float
    stddev_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p90_ms: float
    p99_ms: float


@dataclass(frozen=True)
class CalibrationRun:
    """Single calibration run result."""

    thread_count: int
    target_cpu_percent: float
    achieved_cpu_percent: float
    duration_sec: int
    within_tolerance: bool
    iteration_stats: Optional[IterationStats] = None


@dataclass(frozen=True)
class CalibrationResult:
    """Final calibration result for a target/profile combination."""

    target_id: int
    baseline_id: int
    loadprofile: LoadProfile
    status: CalibrationStatus

    # Final calibrated values
    thread_count: int
    cpu_target_percent: float
    achieved_cpu_percent: float

    # Iteration timing (for HIGH profile)
    avg_iteration_time_ms: Optional[int] = None
    stddev_iteration_time_ms: Optional[int] = None
    min_iteration_time_ms: Optional[int] = None
    max_iteration_time_ms: Optional[int] = None
    iteration_sample_count: Optional[int] = None

    # Metadata
    calibrated_at: Optional[datetime] = None
    calibration_runs: List[CalibrationRun] = field(default_factory=list)
    error_message: Optional[str] = None

    # Hardware info at calibration time
    cpu_count: Optional[int] = None
    memory_gb: Optional[float] = None
