"""Models for package installation and measurement."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class InstallStatus(str, Enum):
    """Status of package installation."""

    PENDING = "pending"
    INSTALLING = "installing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class VerifyStatus(str, Enum):
    """Status of version verification."""

    PENDING = "pending"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PackageInfo:
    """
    Package information from *_package_lst.

    This represents a package to be installed during a phase.
    """

    package_id: int
    package_name: str
    package_version: str
    package_type: str
    package_group_id: int
    package_group_member_id: int
    con_type: str
    is_measured: bool = False

    # Optional fields
    delivery_config: Optional[dict] = None
    requires_restart: bool = False
    restart_timeout_sec: Optional[int] = None
    version_check_command: Optional[str] = None
    expected_version_regex: Optional[str] = None

    # Agent-specific fields (only for agent packages)
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "PackageInfo":
        """Create PackageInfo from dictionary."""
        return cls(
            package_id=data["package_id"],
            package_name=data["package_name"],
            package_version=data["package_version"],
            package_type=data["package_type"],
            package_group_id=data["package_group_id"],
            package_group_member_id=data["package_group_member_id"],
            con_type=data["con_type"],
            is_measured=data.get("is_measured", False),
            delivery_config=data.get("delivery_config"),
            requires_restart=data.get("requires_restart", False),
            restart_timeout_sec=data.get("restart_timeout_sec"),
            version_check_command=data.get("version_check_command"),
            expected_version_regex=data.get("expected_version_regex"),
            agent_id=data.get("agent_id"),
            agent_name=data.get("agent_name"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        result = {
            "package_id": self.package_id,
            "package_name": self.package_name,
            "package_version": self.package_version,
            "package_type": self.package_type,
            "package_group_id": self.package_group_id,
            "package_group_member_id": self.package_group_member_id,
            "con_type": self.con_type,
            "is_measured": self.is_measured,
            "requires_restart": self.requires_restart,
        }

        if self.delivery_config:
            result["delivery_config"] = self.delivery_config
        if self.restart_timeout_sec is not None:
            result["restart_timeout_sec"] = self.restart_timeout_sec
        if self.version_check_command:
            result["version_check_command"] = self.version_check_command
        if self.expected_version_regex:
            result["expected_version_regex"] = self.expected_version_regex
        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
            result["agent_name"] = self.agent_name

        return result


@dataclass
class PackageInstallResult:
    """
    Result of installing a single package.

    Returned by the package installer after attempting installation.
    """

    package_id: int
    package_name: str
    install_status: InstallStatus
    install_started_at: datetime
    install_completed_at: Optional[datetime] = None

    # Installation details
    install_command_used: Optional[str] = None
    install_exit_code: Optional[int] = None
    install_stdout: Optional[str] = None
    install_stderr: Optional[str] = None

    # Restart handling
    restart_performed: bool = False
    restart_started_at: Optional[datetime] = None
    restart_completed_at: Optional[datetime] = None
    restart_duration_sec: Optional[float] = None

    # Error info
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    retry_count: int = 0

    @property
    def install_duration_sec(self) -> Optional[float]:
        """Calculate installation duration in seconds."""
        if self.install_completed_at and self.install_started_at:
            delta = self.install_completed_at - self.install_started_at
            return delta.total_seconds()
        return None


@dataclass
class PackageVerifyResult:
    """
    Result of verifying a package installation.

    Returned after running version check command.
    """

    package_id: int
    verify_status: VerifyStatus
    verified_at: datetime

    # Version info
    expected_version: str
    measured_version: Optional[str] = None
    version_matched: bool = False

    # Command details
    version_check_command: Optional[str] = None
    version_check_exit_code: Optional[int] = None
    version_check_stdout: Optional[str] = None
    version_check_stderr: Optional[str] = None

    # Regex matching
    expected_version_regex: Optional[str] = None
    regex_match_result: Optional[str] = None

    # Error info
    error_message: Optional[str] = None


@dataclass
class PackageMeasuredRecord:
    """
    Complete measured record for a package.

    This is what gets stored in *_package_lst_measured.
    Combines installation result and verification result.
    """

    # Package identification
    package_id: int
    package_name: str
    package_type: str
    is_measured: bool

    # Expected vs actual
    expected_version: str
    measured_version: Optional[str] = None
    version_matched: bool = False

    # Installation result
    install_status: str = "pending"  # InstallStatus value
    install_timestamp: Optional[str] = None  # ISO format
    install_duration_sec: Optional[float] = None

    # Restart info (if required)
    restart_required: bool = False
    restart_performed: bool = False
    restart_duration_sec: Optional[float] = None

    # Verification result
    verify_status: str = "pending"  # VerifyStatus value
    verify_timestamp: Optional[str] = None  # ISO format

    # Error tracking
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    retry_count: int = 0

    # Agent info (if agent package)
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        result = {
            "package_id": self.package_id,
            "package_name": self.package_name,
            "package_type": self.package_type,
            "is_measured": self.is_measured,
            "expected_version": self.expected_version,
            "measured_version": self.measured_version,
            "version_matched": self.version_matched,
            "install_status": self.install_status,
            "install_timestamp": self.install_timestamp,
            "install_duration_sec": self.install_duration_sec,
            "restart_required": self.restart_required,
            "restart_performed": self.restart_performed,
            "restart_duration_sec": self.restart_duration_sec,
            "verify_status": self.verify_status,
            "verify_timestamp": self.verify_timestamp,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
        }

        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
            result["agent_name"] = self.agent_name

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "PackageMeasuredRecord":
        """Create from dictionary."""
        return cls(
            package_id=data["package_id"],
            package_name=data["package_name"],
            package_type=data["package_type"],
            is_measured=data.get("is_measured", False),
            expected_version=data["expected_version"],
            measured_version=data.get("measured_version"),
            version_matched=data.get("version_matched", False),
            install_status=data.get("install_status", "pending"),
            install_timestamp=data.get("install_timestamp"),
            install_duration_sec=data.get("install_duration_sec"),
            restart_required=data.get("restart_required", False),
            restart_performed=data.get("restart_performed", False),
            restart_duration_sec=data.get("restart_duration_sec"),
            verify_status=data.get("verify_status", "pending"),
            verify_timestamp=data.get("verify_timestamp"),
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            retry_count=data.get("retry_count", 0),
            agent_id=data.get("agent_id"),
            agent_name=data.get("agent_name"),
        )

    @property
    def is_success(self) -> bool:
        """Check if installation and verification succeeded."""
        return (
            self.install_status == InstallStatus.SUCCESS.value
            and self.verify_status == VerifyStatus.MATCHED.value
        )

    @property
    def is_failed(self) -> bool:
        """Check if installation or verification failed."""
        return (
            self.install_status in (InstallStatus.FAILED.value, InstallStatus.TIMEOUT.value)
            or self.verify_status == VerifyStatus.FAILED.value
        )


@dataclass
class PhasePackageResult:
    """
    Aggregate result of all package installations for a phase.

    Used to determine if a phase can proceed.
    """

    phase: str  # "base", "initial", "upgrade"
    total_packages: int
    installed_count: int
    failed_count: int
    skipped_count: int
    all_matched: bool

    # Detailed results
    measured_records: list[PackageMeasuredRecord] = field(default_factory=list)

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def is_success(self) -> bool:
        """Check if all packages installed successfully."""
        return self.failed_count == 0 and self.installed_count == self.total_packages

    @property
    def duration_sec(self) -> Optional[float]:
        """Calculate total duration in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
