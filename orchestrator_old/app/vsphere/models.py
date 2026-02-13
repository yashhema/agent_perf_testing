"""Models for vSphere operations."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class VMPowerState(str, Enum):
    """VM power state."""

    POWERED_ON = "poweredOn"
    POWERED_OFF = "poweredOff"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VMHardwareConfig:
    """VM hardware configuration."""

    cpu_count: int
    cpu_cores_per_socket: int
    memory_mb: int
    num_ethernet_cards: int
    num_virtual_disks: int
    guest_os_id: str
    guest_os_full_name: Optional[str] = None


@dataclass(frozen=True)
class SnapshotInfo:
    """Snapshot information."""

    name: str
    description: str
    create_time: datetime
    snapshot_id: str
    power_state: VMPowerState
    is_current: bool = False
    children: List["SnapshotInfo"] = field(default_factory=list)


@dataclass(frozen=True)
class VMInfo:
    """Virtual machine information."""

    name: str
    uuid: str
    power_state: VMPowerState
    guest_hostname: Optional[str]
    guest_ip_address: Optional[str]
    hardware: VMHardwareConfig
    datacenter: str
    cluster: Optional[str]
    host: str
    resource_pool: Optional[str]
    folder: str
    annotation: Optional[str] = None
    snapshots: List[SnapshotInfo] = field(default_factory=list)


@dataclass(frozen=True)
class TaskResult:
    """Result of a vSphere task."""

    success: bool
    task_name: str
    message: str
    duration_sec: float
    vm_name: Optional[str] = None
    error_message: Optional[str] = None
