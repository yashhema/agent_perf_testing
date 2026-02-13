"""Error classification for orchestrator operations.

Classifies errors as retryable vs non-retryable, and provides
user-facing error messages for common failure modes.
"""

import logging

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""
    retryable: bool = False
    user_message: str = "An unexpected error occurred"

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


class InfrastructureError(OrchestratorError):
    """Infrastructure-related errors (VMs, hypervisors, network)."""
    retryable = True
    user_message = "Infrastructure operation failed"


class SnapshotRestoreError(InfrastructureError):
    """Snapshot restore timed out or failed."""
    user_message = "VM snapshot restore failed — the VM may be unresponsive"


class SSHConnectionError(InfrastructureError):
    """SSH/WinRM connection to target failed."""
    user_message = "Could not connect to target server"


class HypervisorError(InfrastructureError):
    """Hypervisor API call failed."""
    user_message = "Hypervisor API returned an error"


class PackageDeployError(OrchestratorError):
    """Package deployment failed."""
    retryable = True
    user_message = "Package deployment failed on target server"


class CalibrationError(OrchestratorError):
    """Calibration did not converge."""
    retryable = False
    user_message = "Calibration failed to find a stable thread count"


class ValidationError(OrchestratorError):
    """Pre-flight validation failed."""
    retryable = False
    user_message = "Pre-flight validation found errors"


class EmulatorError(OrchestratorError):
    """Emulator API call failed."""
    retryable = True
    user_message = "Emulator API returned an error"


class JMeterError(OrchestratorError):
    """JMeter start/stop/monitoring failed."""
    retryable = True
    user_message = "JMeter operation failed on load generator"


class ConfigurationError(OrchestratorError):
    """Invalid configuration."""
    retryable = False
    user_message = "Configuration error — please check settings"


def is_retryable(error: Exception) -> bool:
    """Check if an error is retryable."""
    if isinstance(error, OrchestratorError):
        return error.retryable
    # Network/timeout errors are generally retryable
    error_type = type(error).__name__
    retryable_types = {"ConnectionError", "TimeoutError", "OSError", "IOError"}
    return error_type in retryable_types


def get_user_message(error: Exception) -> str:
    """Get a user-facing error message."""
    if isinstance(error, OrchestratorError):
        return f"{error.user_message}: {error}"
    return f"Unexpected error: {type(error).__name__}: {error}"
