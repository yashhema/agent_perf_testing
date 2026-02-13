"""Mock vSphere client for E2E testing."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List


class VMPowerState(str, Enum):
    """VM power states."""
    POWERED_ON = "poweredOn"
    POWERED_OFF = "poweredOff"
    SUSPENDED = "suspended"


@dataclass
class MockSnapshot:
    """Mock VM snapshot."""
    name: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    description: str = ""


@dataclass
class MockVM:
    """Mock virtual machine."""
    name: str
    power_state: VMPowerState = VMPowerState.POWERED_OFF
    ip_address: Optional[str] = None
    cpu_count: int = 4
    memory_mb: int = 8192
    snapshots: List[MockSnapshot] = field(default_factory=list)
    current_snapshot: Optional[str] = None


class VSphereSimulator:
    """
    Simulates vSphere behavior for testing.

    Tracks VM state and simulates operations with configurable delays.
    """

    def __init__(
        self,
        operation_delay_sec: float = 0.1,
        failure_rate: float = 0.0,
    ):
        self._vms: Dict[str, MockVM] = {}
        self._operation_delay = operation_delay_sec
        self._failure_rate = failure_rate
        self._operation_count = 0
        self._operations_log: List[Dict] = []

    def add_vm(
        self,
        name: str,
        ip_address: str = "192.168.1.100",
        snapshots: Optional[List[str]] = None,
    ) -> MockVM:
        """Add a VM to the simulator."""
        vm = MockVM(
            name=name,
            ip_address=ip_address,
            snapshots=[
                MockSnapshot(name=s) for s in (snapshots or ["baseline"])
            ],
        )
        self._vms[name] = vm
        return vm

    def get_vm(self, name: str) -> Optional[MockVM]:
        """Get VM by name."""
        return self._vms.get(name)

    def get_operations_log(self) -> List[Dict]:
        """Get log of all operations performed."""
        return list(self._operations_log)

    def _log_operation(self, operation: str, vm_name: str, **kwargs) -> None:
        """Log an operation."""
        self._operations_log.append({
            "operation": operation,
            "vm_name": vm_name,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs,
        })

    async def _simulate_delay(self) -> None:
        """Simulate operation delay."""
        if self._operation_delay > 0:
            await asyncio.sleep(self._operation_delay)

    def _should_fail(self) -> bool:
        """Determine if operation should fail based on failure rate."""
        import random
        return random.random() < self._failure_rate


class MockVSphereClient:
    """
    Mock vSphere client for E2E testing.

    Provides the same interface as the real vSphere client but
    uses the VSphereSimulator for state management.
    """

    def __init__(self, simulator: VSphereSimulator):
        self._simulator = simulator
        self._connected = False

    async def connect(self, host: str, username: str, password: str) -> bool:
        """Simulate connection to vCenter."""
        await self._simulator._simulate_delay()

        if self._simulator._should_fail():
            raise ConnectionError("Failed to connect to vCenter")

        self._connected = True
        return True

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False

    async def get_vm(self, vm_name: str) -> Optional[Dict]:
        """Get VM information."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()
        vm = self._simulator.get_vm(vm_name)

        if vm is None:
            return None

        return {
            "name": vm.name,
            "power_state": vm.power_state.value,
            "ip_address": vm.ip_address,
            "cpu_count": vm.cpu_count,
            "memory_mb": vm.memory_mb,
            "snapshots": [s.name for s in vm.snapshots],
            "current_snapshot": vm.current_snapshot,
        }

    async def revert_to_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
    ) -> bool:
        """Revert VM to snapshot."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()

        if self._simulator._should_fail():
            raise RuntimeError(f"Failed to revert {vm_name} to {snapshot_name}")

        vm = self._simulator.get_vm(vm_name)
        if vm is None:
            raise ValueError(f"VM {vm_name} not found")

        # Check snapshot exists
        snapshot_names = [s.name for s in vm.snapshots]
        if snapshot_name not in snapshot_names:
            raise ValueError(f"Snapshot {snapshot_name} not found")

        vm.current_snapshot = snapshot_name
        vm.power_state = VMPowerState.POWERED_OFF

        self._simulator._log_operation(
            "revert_to_snapshot",
            vm_name,
            snapshot_name=snapshot_name,
        )

        return True

    async def power_on(self, vm_name: str) -> bool:
        """Power on VM."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()

        if self._simulator._should_fail():
            raise RuntimeError(f"Failed to power on {vm_name}")

        vm = self._simulator.get_vm(vm_name)
        if vm is None:
            raise ValueError(f"VM {vm_name} not found")

        vm.power_state = VMPowerState.POWERED_ON

        self._simulator._log_operation("power_on", vm_name)

        return True

    async def power_off(self, vm_name: str) -> bool:
        """Power off VM."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()

        vm = self._simulator.get_vm(vm_name)
        if vm is None:
            raise ValueError(f"VM {vm_name} not found")

        vm.power_state = VMPowerState.POWERED_OFF

        self._simulator._log_operation("power_off", vm_name)

        return True

    async def wait_for_ip(
        self,
        vm_name: str,
        timeout_sec: int = 120,
    ) -> Optional[str]:
        """Wait for VM to get an IP address."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()

        vm = self._simulator.get_vm(vm_name)
        if vm is None:
            raise ValueError(f"VM {vm_name} not found")

        if vm.power_state != VMPowerState.POWERED_ON:
            return None

        return vm.ip_address

    async def create_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        description: str = "",
    ) -> bool:
        """Create a new snapshot."""
        if not self._connected:
            raise RuntimeError("Not connected to vCenter")

        await self._simulator._simulate_delay()

        vm = self._simulator.get_vm(vm_name)
        if vm is None:
            raise ValueError(f"VM {vm_name} not found")

        vm.snapshots.append(MockSnapshot(
            name=snapshot_name,
            description=description,
        ))

        self._simulator._log_operation(
            "create_snapshot",
            vm_name,
            snapshot_name=snapshot_name,
        )

        return True
