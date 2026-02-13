"""Enumeration types for the application.

All enums are defined here to maintain consistency between
ORM models, Application models, and API schemas.
"""

from enum import Enum


class OSFamily(str, Enum):
    """Operating system family."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    AIX = "aix"
    OTHER = "other"


class LabType(str, Enum):
    """Type of lab environment."""

    ONPREM_VSPHERE = "onprem_vsphere"
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    ENDPOINT_MDM = "endpoint_mdm"
    HYBRID = "hybrid"


class SecretManagement(str, Enum):
    """Secret management method for a lab."""

    KEYPASS = "keypass"
    SECRETMANAGER = "secretmanager"
    PKWAREMANAGEDFILE = "pkwaremanagedfile"


class ConnectionType(str, Enum):
    """Connection/delivery method types."""

    MFOO = "mfoo"
    TANIUM = "tanium"
    NFS = "nfs"
    AGENTCONSOLE = "agentconsole"
    GITLABREPO = "gitlabrepo"
    NESSUSREPO = "nessusrepo"
    OS_FAMILY = "os_family"
    SSM = "ssm"
    INTUNE = "intune"
    JAMF = "jamf"
    SCRIPT = "script"
    VSPHERE = "vsphere"


class TargetType(str, Enum):
    """Type of target device."""

    SERVER = "server"
    ENDPOINT = "endpoint"
    K8S_CLUSTER = "k8s_cluster"
    VM = "vm"
    OTHER = "other"


class DiskType(str, Enum):
    """Type of disk storage."""

    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"
    UNKNOWN = "unknown"


class TraceStatus(str, Enum):
    """Status of a trace."""

    ACTIVE = "active"
    CLOSED = "closed"


class PackageGroupType(str, Enum):
    """Type of package group."""

    LOAD_RUNNER_EUC = "load_runner_euc"
    EMULATOR = "emulator"
    FUNCTIONAL = "functional"
    POLICY = "policy"
    AGENT = "agent"


class BaselineScope(str, Enum):
    """Scope of baseline - EUC or Server."""

    EUC = "euc"
    SERVER = "server"


class WorkflowState(str, Enum):
    """Workflow state for execution tracking."""

    NO_RUN = "norun"
    CONFIGURATION_CHECK = "configuration_check"
    CONFIGURATION_CHECK_EXECUTING = "configuration_check_executing"
    CONFIGURATION_CHECK_COMPLETE = "configuration_check_complete"
    RESTART = "restart"
    PRE_RUN_EXECUTING = "pre_run_executing"
    PRE_RUN_COMPLETE = "pre_run_complete"
    AGENT_UPGRADE = "agent_upgrade"
    AGENT_UPGRADE_EXECUTING = "agent_upgrade_executing"
    AGENT_UPGRADE_COMPLETE = "agent_upgrade_complete"
    POST_RUN_EXECUTING = "post_run_executing"
    POST_RUN_COMPLETE = "post_run_complete"
    COMPLETE = "complete"
    ERROR = "error"


class ServerRole(str, Enum):
    """Role/purpose of server in the infrastructure."""

    APP_SERVER = "app_server"
    DB_SERVER = "db_server"
    LOAD_GENERATOR = "load_generator"


class ServerInfraType(str, Enum):
    """Infrastructure type - how the server is hosted/managed."""

    DOCKER = "docker"          # Docker container
    EC2 = "ec2"                # AWS EC2 instance
    VSPHERE_VM = "vsphere_vm"  # VMware vSphere VM
    AZURE_VM = "azure_vm"      # Azure VM
    GCP_VM = "gcp_vm"          # Google Cloud VM
    PHYSICAL = "physical"      # Physical/bare-metal server


class DatabaseType(str, Enum):
    """Database type for DB servers."""

    POSTGRES = "postgres"      # PostgreSQL
    MYSQL = "mysql"            # MySQL/MariaDB
    ORACLE = "oracle"          # Oracle DB
    MSSQL = "mssql"            # Microsoft SQL Server


class DeploymentType(str, Enum):
    """How to deploy packages to a server."""

    SSH = "ssh"                # SSH for Linux/Unix (default for redhat, ubuntu, aix, oracle)
    WINRM = "winrm"            # WinRM for Windows (default for microsoft)
    DOCKER_EXEC = "docker_exec"  # Docker exec for containers
    SSM = "ssm"                # AWS Systems Manager
    INTUNE = "intune"          # Microsoft Intune for endpoints
    JAMF = "jamf"              # JAMF for macOS


class LoadProfile(str, Enum):
    """Load profile levels for testing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RunMode(str, Enum):
    """Execution run mode."""

    CONTINUOUS = "continuous"  # Run all steps without stopping
    STEP = "step"  # Pause between major steps


class ExecutionStatus(str, Enum):
    """Status of a test run execution."""

    NOT_STARTED = "notstarted"
    CALIBRATING = "calibrating"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    ENDED = "ended"
    ENDED_ERROR = "ended_error"
    ABANDONED = "abandoned"

    def is_terminal(self) -> bool:
        """Check if this status is a terminal state."""
        return self in {
            ExecutionStatus.ENDED,
            ExecutionStatus.ENDED_ERROR,
            ExecutionStatus.ABANDONED,
        }

    def is_active(self) -> bool:
        """Check if this status represents an active execution."""
        return not self.is_terminal()


class BaselineType(str, Enum):
    """Type of baseline - how to restore the baseline state."""

    DOCKER = "docker"          # Docker image - pull/recreate container
    VSPHERE = "vsphere"        # vSphere snapshot - revert to snapshot
    AWS = "aws"                # AWS AMI/EBS snapshot - create from AMI
    AZURE = "azure"            # Azure snapshot/image
    GCP = "gcp"                # GCP snapshot/image
    INTUNE = "intune"          # Intune policy - re-apply policy
    JAMF = "jamf"              # JAMF policy - re-apply policy


class CalibrationStatus(str, Enum):
    """Status of calibration for a target."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionPhase(str, Enum):
    """Phase of test execution."""

    CALIBRATION = "calibration"
    BASE = "base"
    INITIAL = "initial"
    UPGRADE = "upgrade"


class ScenarioExecutionStatus(str, Enum):
    """Status of scenario execution per loadprofile."""

    PENDING = "pending"
    CALIBRATING = "calibrating"
    CALIBRATED = "calibrated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

    def is_terminal(self) -> bool:
        """Check if this status is a terminal state."""
        return self in {
            ScenarioExecutionStatus.COMPLETED,
            ScenarioExecutionStatus.FAILED,
            ScenarioExecutionStatus.SKIPPED,
        }


class FailureType(str, Enum):
    """Types of failures that can occur during execution."""

    # Connection failures
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_TIMEOUT = "connection_timeout"
    CONNECTION_LOST = "connection_lost"

    # Package failures
    PACKAGE_DOWNLOAD_FAILED = "package_download_failed"
    PACKAGE_INSTALL_FAILED = "package_install_failed"
    PACKAGE_INSTALL_TIMEOUT = "package_install_timeout"
    PACKAGE_UPGRADE_FAILED = "package_upgrade_failed"
    VERSION_MISMATCH = "version_mismatch"
    CONFIG_MISMATCH = "config_mismatch"

    # Calibration failures
    CALIBRATION_FAILED = "calibration_failed"
    CALIBRATION_TIMEOUT = "calibration_timeout"
    CPU_TARGET_NOT_REACHED = "cpu_target_not_reached"

    # Load test failures
    LOADTEST_START_FAILED = "loadtest_start_failed"
    LOADTEST_CRASHED = "loadtest_crashed"
    LOADTEST_TIMEOUT = "loadtest_timeout"
    TARGET_CRASHED = "target_crashed"

    # Infrastructure failures
    SNAPSHOT_NOT_FOUND = "snapshot_not_found"
    SNAPSHOT_REVERT_FAILED = "snapshot_revert_failed"
    POWER_ON_FAILED = "power_on_failed"
    GUEST_TOOLS_NOT_READY = "guest_tools_not_ready"

    # Data collection failures
    STATS_COLLECTION_FAILED = "stats_collection_failed"
    LOGS_COLLECTION_FAILED = "logs_collection_failed"


class FailureAction(str, Enum):
    """Action to take on failure."""

    RETRY = "retry"
    FAIL = "fail"
    SKIP = "skip"
    CONTINUE = "continue"  # Soft fail, continue to next step
    ABORT = "abort"  # Stop entire execution


class PhaseState(str, Enum):
    """State within an execution phase."""

    NOT_STARTED = "not_started"
    REVERTING_SNAPSHOT = "reverting_snapshot"
    POWERING_ON = "powering_on"
    WAITING_FOR_READY = "waiting_for_ready"
    INSTALLING_AGENT = "installing_agent"
    AGENT_INSTALLED = "agent_installed"
    WARMUP = "warmup"
    LOAD_TEST_RUNNING = "load_test_running"
    LOAD_TEST_COMPLETED = "load_test_completed"
    COLLECTING_STATS = "collecting_stats"
    COMPLETED = "completed"
    ERROR = "error"
