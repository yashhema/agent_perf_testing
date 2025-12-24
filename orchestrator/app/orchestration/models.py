"""Models for scenario orchestration."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List


class ScenarioPhase(str, Enum):
    """Phases of scenario execution."""
    PENDING = "pending"
    SETUP = "setup"
    CALIBRATION = "calibration"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class SetupStatus(str, Enum):
    """Status of server setup."""
    PENDING = "pending"
    INSTALLING = "installing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ServerSetup:
    """Server configuration for scenario."""
    server_id: int
    hostname: str
    ip_address: str
    emulator_port: int = 8080
    os_type: str = "linux"
    cpu_count: int = 4
    memory_gb: float = 8.0
    baseline_snapshot: Optional[str] = None


@dataclass(frozen=True)
class SetupResult:
    """Result of setting up a server."""
    server_id: int
    status: SetupStatus
    emulator_installed: bool = False
    emulator_version: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class CalibrationData:
    """Calibration data for a single profile."""
    server_id: int
    profile: str  # LOW, MEDIUM, HIGH
    thread_count: int
    target_cpu_percent: float
    achieved_cpu_percent: float
    calibrated_at: datetime
    duration_sec: float
    is_valid: bool
    validation_message: str


@dataclass
class ServerCalibration:
    """All calibration data for a server."""
    server_id: int
    low: Optional[CalibrationData] = None
    medium: Optional[CalibrationData] = None
    high: Optional[CalibrationData] = None

    def get_thread_count(self, profile: str) -> Optional[int]:
        """Get thread count for a profile."""
        data = getattr(self, profile.lower(), None)
        return data.thread_count if data else None

    def is_complete(self) -> bool:
        """Check if all profiles are calibrated."""
        return all([self.low, self.medium, self.high])

    def all_valid(self) -> bool:
        """Check if all calibrations are valid."""
        return all([
            self.low and self.low.is_valid,
            self.medium and self.medium.is_valid,
            self.high and self.high.is_valid,
        ])


@dataclass(frozen=True)
class PhaseResult:
    """Result of a scenario phase."""
    phase: ScenarioPhase
    success: bool
    started_at: datetime
    completed_at: datetime
    duration_sec: float
    servers_succeeded: int
    servers_failed: int
    error_message: Optional[str] = None
    details: Optional[Dict] = None


@dataclass
class ScenarioState:
    """Current state of scenario execution."""
    scenario_id: str
    phase: ScenarioPhase = ScenarioPhase.PENDING
    servers: List[ServerSetup] = field(default_factory=list)
    setup_results: Dict[int, SetupResult] = field(default_factory=dict)
    calibrations: Dict[int, ServerCalibration] = field(default_factory=dict)
    phase_results: List[PhaseResult] = field(default_factory=list)
    current_profile: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def get_calibration(self, server_id: int) -> Optional[ServerCalibration]:
        """Get calibration data for a server."""
        return self.calibrations.get(server_id)

    def set_calibration_data(
        self,
        server_id: int,
        profile: str,
        data: CalibrationData,
    ) -> None:
        """Set calibration data for a server and profile."""
        if server_id not in self.calibrations:
            self.calibrations[server_id] = ServerCalibration(server_id=server_id)

        setattr(self.calibrations[server_id], profile.lower(), data)
