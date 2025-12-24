"""Unit tests for vSphere models."""

import pytest
from datetime import datetime

from app.vsphere.models import (
    VMInfo,
    SnapshotInfo,
    VMHardwareConfig,
    VMPowerState,
    TaskResult,
)


class TestVMHardwareConfig:
    """Unit tests for VMHardwareConfig."""

    def test_create_config(self) -> None:
        """Test creating hardware config."""
        config = VMHardwareConfig(
            cpu_count=4,
            cpu_cores_per_socket=2,
            memory_mb=8192,
            num_ethernet_cards=1,
            num_virtual_disks=2,
            guest_os_id="windows9Server64Guest",
            guest_os_full_name="Microsoft Windows Server 2019",
        )

        assert config.cpu_count == 4
        assert config.cpu_cores_per_socket == 2
        assert config.memory_mb == 8192
        assert config.num_ethernet_cards == 1
        assert config.num_virtual_disks == 2

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = VMHardwareConfig(
            cpu_count=4,
            cpu_cores_per_socket=2,
            memory_mb=8192,
            num_ethernet_cards=1,
            num_virtual_disks=1,
            guest_os_id="rhel7_64Guest",
        )

        with pytest.raises(AttributeError):
            config.cpu_count = 8


class TestSnapshotInfo:
    """Unit tests for SnapshotInfo."""

    def test_create_snapshot_info(self) -> None:
        """Test creating snapshot info."""
        now = datetime.utcnow()

        snapshot = SnapshotInfo(
            name="base",
            description="Base snapshot",
            create_time=now,
            snapshot_id="snapshot-1",
            power_state=VMPowerState.POWERED_OFF,
            is_current=True,
        )

        assert snapshot.name == "base"
        assert snapshot.is_current is True
        assert snapshot.power_state == VMPowerState.POWERED_OFF

    def test_snapshot_with_children(self) -> None:
        """Test snapshot with child snapshots."""
        now = datetime.utcnow()

        child = SnapshotInfo(
            name="child",
            description="Child snapshot",
            create_time=now,
            snapshot_id="snapshot-2",
            power_state=VMPowerState.POWERED_ON,
        )

        parent = SnapshotInfo(
            name="parent",
            description="Parent snapshot",
            create_time=now,
            snapshot_id="snapshot-1",
            power_state=VMPowerState.POWERED_OFF,
            children=[child],
        )

        assert len(parent.children) == 1
        assert parent.children[0].name == "child"


class TestVMInfo:
    """Unit tests for VMInfo."""

    def test_create_vm_info(self) -> None:
        """Test creating VM info."""
        hardware = VMHardwareConfig(
            cpu_count=4,
            cpu_cores_per_socket=2,
            memory_mb=8192,
            num_ethernet_cards=1,
            num_virtual_disks=1,
            guest_os_id="rhel7_64Guest",
        )

        vm_info = VMInfo(
            name="test-vm",
            uuid="12345678-1234-1234-1234-123456789012",
            power_state=VMPowerState.POWERED_ON,
            guest_hostname="test-vm.example.com",
            guest_ip_address="192.168.1.100",
            hardware=hardware,
            datacenter="DC1",
            cluster="Cluster1",
            host="esxi-01.example.com",
            resource_pool="Resources",
            folder="VMs",
        )

        assert vm_info.name == "test-vm"
        assert vm_info.power_state == VMPowerState.POWERED_ON
        assert vm_info.hardware.cpu_count == 4
        assert vm_info.guest_ip_address == "192.168.1.100"

    def test_vm_info_with_snapshots(self) -> None:
        """Test VM info with snapshots."""
        hardware = VMHardwareConfig(
            cpu_count=2,
            cpu_cores_per_socket=1,
            memory_mb=4096,
            num_ethernet_cards=1,
            num_virtual_disks=1,
            guest_os_id="ubuntu64Guest",
        )

        snapshot = SnapshotInfo(
            name="base",
            description="Base snapshot",
            create_time=datetime.utcnow(),
            snapshot_id="snap-1",
            power_state=VMPowerState.POWERED_OFF,
            is_current=True,
        )

        vm_info = VMInfo(
            name="test-vm",
            uuid="uuid-1234",
            power_state=VMPowerState.POWERED_OFF,
            guest_hostname=None,
            guest_ip_address=None,
            hardware=hardware,
            datacenter="DC1",
            cluster=None,
            host="esxi-01",
            resource_pool=None,
            folder="VMs",
            snapshots=[snapshot],
        )

        assert len(vm_info.snapshots) == 1
        assert vm_info.snapshots[0].name == "base"

    def test_vm_info_is_frozen(self) -> None:
        """Test that VM info is immutable."""
        hardware = VMHardwareConfig(
            cpu_count=2,
            cpu_cores_per_socket=1,
            memory_mb=4096,
            num_ethernet_cards=1,
            num_virtual_disks=1,
            guest_os_id="ubuntu64Guest",
        )

        vm_info = VMInfo(
            name="test-vm",
            uuid="uuid-1234",
            power_state=VMPowerState.POWERED_ON,
            guest_hostname=None,
            guest_ip_address=None,
            hardware=hardware,
            datacenter="DC1",
            cluster=None,
            host="esxi-01",
            resource_pool=None,
            folder="VMs",
        )

        with pytest.raises(AttributeError):
            vm_info.name = "new-name"
