"""vSphere integration module for VM operations."""

from .helper import VSphereHelper, VSphereConfig
from .models import (
    VMInfo,
    SnapshotInfo,
    VMHardwareConfig,
    VMPowerState,
    TaskResult,
)

__all__ = [
    "VSphereHelper",
    "VSphereConfig",
    "VMInfo",
    "SnapshotInfo",
    "VMHardwareConfig",
    "VMPowerState",
    "TaskResult",
]
