"""vSphere helper for VM operations."""

import atexit
import time
from dataclasses import dataclass
from typing import Optional, List, Any

from .models import (
    VMInfo,
    SnapshotInfo,
    VMHardwareConfig,
    VMPowerState,
    TaskResult,
)


@dataclass(frozen=True)
class VSphereConfig:
    """Configuration for vSphere connection."""

    host: str
    username: str
    password: str
    datacenter: str
    port: int = 443
    disable_ssl_verification: bool = True
    timeout: int = 30


class VSphereHelper:
    """Helper class for vSphere VM operations."""

    def __init__(self, config: VSphereConfig):
        self._config = config
        self._si = None  # ServiceInstance
        self._content = None
        self._datacenter = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to vSphere."""
        return self._si is not None

    def connect(self) -> None:
        """Establish connection to vSphere."""
        try:
            from pyVim import connect
            from pyVmomi import vim
            import ssl

            # Handle SSL
            ssl_context = None
            if self._config.disable_ssl_verification:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            self._si = connect.SmartConnect(
                host=self._config.host,
                user=self._config.username,
                pwd=self._config.password,
                port=self._config.port,
                sslContext=ssl_context,
            )

            # Register cleanup
            atexit.register(connect.Disconnect, self._si)

            self._content = self._si.RetrieveContent()
            self._datacenter = self._get_datacenter(self._config.datacenter)

            if not self._datacenter:
                raise ValueError(f"Datacenter '{self._config.datacenter}' not found")

        except ImportError:
            raise ImportError("pyvmomi is required for vSphere operations")
        except Exception as e:
            self._si = None
            raise ConnectionError(f"Failed to connect to vSphere: {e}")

    def disconnect(self) -> None:
        """Disconnect from vSphere."""
        if self._si:
            try:
                from pyVim import connect
                connect.Disconnect(self._si)
            except Exception:
                pass
            self._si = None
            self._content = None
            self._datacenter = None

    def _get_datacenter(self, name: str) -> Any:
        """Get datacenter by name."""
        from pyVmomi import vim

        for dc in self._content.rootFolder.childEntity:
            if isinstance(dc, vim.Datacenter) and dc.name == name:
                return dc
        return None

    def _get_vm(self, vm_name: str) -> Any:
        """Get VM by name."""
        from pyVmomi import vim

        container = self._content.viewManager.CreateContainerView(
            self._datacenter, [vim.VirtualMachine], True
        )

        try:
            for vm in container.view:
                if vm.name == vm_name:
                    return vm
        finally:
            container.Destroy()

        return None

    def _wait_for_task(self, task: Any, timeout: int = 300) -> TaskResult:
        """Wait for vSphere task to complete."""
        from pyVmomi import vim

        start_time = time.time()
        task_name = task.info.descriptionId or "Unknown"

        while task.info.state not in [
            vim.TaskInfo.State.success,
            vim.TaskInfo.State.error,
        ]:
            if time.time() - start_time > timeout:
                return TaskResult(
                    success=False,
                    task_name=task_name,
                    message="Task timed out",
                    duration_sec=time.time() - start_time,
                    error_message="Timeout waiting for task",
                )
            time.sleep(1)

        duration = time.time() - start_time

        if task.info.state == vim.TaskInfo.State.success:
            return TaskResult(
                success=True,
                task_name=task_name,
                message="Task completed successfully",
                duration_sec=duration,
            )
        else:
            error_msg = str(task.info.error) if task.info.error else "Unknown error"
            return TaskResult(
                success=False,
                task_name=task_name,
                message="Task failed",
                duration_sec=duration,
                error_message=error_msg,
            )

    # ========================================
    # VM Information
    # ========================================

    def get_vm_info(self, vm_name: str) -> Optional[VMInfo]:
        """Get detailed VM information."""
        vm = self._get_vm(vm_name)
        if not vm:
            return None

        return self._build_vm_info(vm)

    def _build_vm_info(self, vm: Any) -> VMInfo:
        """Build VMInfo from VM object."""
        from pyVmomi import vim

        # Get hardware config
        hardware = VMHardwareConfig(
            cpu_count=vm.config.hardware.numCPU,
            cpu_cores_per_socket=vm.config.hardware.numCoresPerSocket,
            memory_mb=vm.config.hardware.memoryMB,
            num_ethernet_cards=len([
                d for d in vm.config.hardware.device
                if isinstance(d, vim.vm.device.VirtualEthernetCard)
            ]),
            num_virtual_disks=len([
                d for d in vm.config.hardware.device
                if isinstance(d, vim.vm.device.VirtualDisk)
            ]),
            guest_os_id=vm.config.guestId,
            guest_os_full_name=vm.config.guestFullName,
        )

        # Get power state
        power_state = self._map_power_state(vm.runtime.powerState)

        # Get guest info
        guest_hostname = None
        guest_ip = None
        if vm.guest:
            guest_hostname = vm.guest.hostName
            guest_ip = vm.guest.ipAddress

        # Get location info
        host = vm.runtime.host.name if vm.runtime.host else "Unknown"
        cluster = None
        if vm.runtime.host and vm.runtime.host.parent:
            if hasattr(vm.runtime.host.parent, "name"):
                cluster = vm.runtime.host.parent.name

        resource_pool = None
        if vm.resourcePool:
            resource_pool = vm.resourcePool.name

        folder = vm.parent.name if vm.parent else "Unknown"

        # Get snapshots
        snapshots = self._get_snapshot_tree(vm)

        return VMInfo(
            name=vm.name,
            uuid=vm.config.uuid,
            power_state=power_state,
            guest_hostname=guest_hostname,
            guest_ip_address=guest_ip,
            hardware=hardware,
            datacenter=self._config.datacenter,
            cluster=cluster,
            host=host,
            resource_pool=resource_pool,
            folder=folder,
            annotation=vm.config.annotation,
            snapshots=snapshots,
        )

    def _map_power_state(self, state: Any) -> VMPowerState:
        """Map vSphere power state to enum."""
        from pyVmomi import vim

        state_map = {
            vim.VirtualMachinePowerState.poweredOn: VMPowerState.POWERED_ON,
            vim.VirtualMachinePowerState.poweredOff: VMPowerState.POWERED_OFF,
            vim.VirtualMachinePowerState.suspended: VMPowerState.SUSPENDED,
        }
        return state_map.get(state, VMPowerState.UNKNOWN)

    def list_vms(self, folder: Optional[str] = None) -> List[str]:
        """List all VMs in datacenter or folder."""
        from pyVmomi import vim

        container = self._content.viewManager.CreateContainerView(
            self._datacenter, [vim.VirtualMachine], True
        )

        try:
            vms = []
            for vm in container.view:
                if folder is None or (vm.parent and vm.parent.name == folder):
                    vms.append(vm.name)
            return sorted(vms)
        finally:
            container.Destroy()

    # ========================================
    # Power Operations
    # ========================================

    def power_on(self, vm_name: str, wait: bool = True) -> TaskResult:
        """Power on a VM."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="PowerOn",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        # Check if already powered on
        if vm.runtime.powerState == "poweredOn":
            return TaskResult(
                success=True,
                task_name="PowerOn",
                message="VM is already powered on",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = vm.PowerOnVM_Task()
            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="PowerOn",
                    message=result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="PowerOn",
                message="Power on task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="PowerOn",
                message="Failed to power on VM",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def power_off(self, vm_name: str, force: bool = False, wait: bool = True) -> TaskResult:
        """Power off a VM."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="PowerOff",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        # Check if already powered off
        if vm.runtime.powerState == "poweredOff":
            return TaskResult(
                success=True,
                task_name="PowerOff",
                message="VM is already powered off",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            if force:
                task = vm.PowerOffVM_Task()
            else:
                # Try graceful shutdown first
                vm.ShutdownGuest()
                # Wait for power off
                start = time.time()
                while vm.runtime.powerState != "poweredOff" and time.time() - start < 120:
                    time.sleep(5)
                    vm = self._get_vm(vm_name)

                if vm.runtime.powerState == "poweredOff":
                    return TaskResult(
                        success=True,
                        task_name="PowerOff",
                        message="VM shut down gracefully",
                        duration_sec=time.time() - start,
                        vm_name=vm_name,
                    )
                # Force power off if graceful failed
                task = vm.PowerOffVM_Task()

            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="PowerOff",
                    message=result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="PowerOff",
                message="Power off task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="PowerOff",
                message="Failed to power off VM",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def reset(self, vm_name: str, wait: bool = True) -> TaskResult:
        """Reset (hard reboot) a VM."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="Reset",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = vm.ResetVM_Task()
            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="Reset",
                    message=result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="Reset",
                message="Reset task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="Reset",
                message="Failed to reset VM",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def suspend(self, vm_name: str, wait: bool = True) -> TaskResult:
        """Suspend a VM."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="Suspend",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = vm.SuspendVM_Task()
            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="Suspend",
                    message=result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="Suspend",
                message="Suspend task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="Suspend",
                message="Failed to suspend VM",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    # ========================================
    # Snapshot Operations
    # ========================================

    def _get_snapshot_tree(self, vm: Any) -> List[SnapshotInfo]:
        """Get snapshot tree for a VM."""
        if not vm.snapshot or not vm.snapshot.rootSnapshotList:
            return []

        current_snapshot = vm.snapshot.currentSnapshot if vm.snapshot else None
        return self._build_snapshot_list(vm.snapshot.rootSnapshotList, current_snapshot)

    def _build_snapshot_list(
        self, snapshot_list: List[Any], current_snapshot: Any
    ) -> List[SnapshotInfo]:
        """Recursively build snapshot info list."""
        snapshots = []
        for snap in snapshot_list:
            is_current = current_snapshot and snap.snapshot == current_snapshot

            children = []
            if snap.childSnapshotList:
                children = self._build_snapshot_list(snap.childSnapshotList, current_snapshot)

            snapshots.append(SnapshotInfo(
                name=snap.name,
                description=snap.description or "",
                create_time=snap.createTime,
                snapshot_id=str(snap.id),
                power_state=self._map_power_state(snap.state),
                is_current=is_current,
                children=children,
            ))

        return snapshots

    def _find_snapshot(self, vm: Any, snapshot_name: str) -> Any:
        """Find snapshot by name."""
        if not vm.snapshot:
            return None

        def search_tree(snapshot_list):
            for snap in snapshot_list:
                if snap.name == snapshot_name:
                    return snap.snapshot
                if snap.childSnapshotList:
                    found = search_tree(snap.childSnapshotList)
                    if found:
                        return found
            return None

        return search_tree(vm.snapshot.rootSnapshotList)

    def create_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        description: str = "",
        include_memory: bool = False,
        quiesce: bool = True,
        wait: bool = True,
    ) -> TaskResult:
        """Create a VM snapshot."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="CreateSnapshot",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = vm.CreateSnapshot_Task(
                name=snapshot_name,
                description=description,
                memory=include_memory,
                quiesce=quiesce,
            )

            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="CreateSnapshot",
                    message=f"Snapshot '{snapshot_name}' created" if result.success else result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="CreateSnapshot",
                message="Snapshot creation started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="CreateSnapshot",
                message="Failed to create snapshot",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def revert_to_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        wait: bool = True,
    ) -> TaskResult:
        """Revert VM to a snapshot."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="RevertToSnapshot",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        snapshot = self._find_snapshot(vm, snapshot_name)
        if not snapshot:
            return TaskResult(
                success=False,
                task_name="RevertToSnapshot",
                message=f"Snapshot '{snapshot_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = snapshot.RevertToSnapshot_Task()

            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="RevertToSnapshot",
                    message=f"Reverted to snapshot '{snapshot_name}'" if result.success else result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="RevertToSnapshot",
                message="Revert task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="RevertToSnapshot",
                message="Failed to revert to snapshot",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def delete_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        remove_children: bool = False,
        wait: bool = True,
    ) -> TaskResult:
        """Delete a VM snapshot."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="DeleteSnapshot",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        snapshot = self._find_snapshot(vm, snapshot_name)
        if not snapshot:
            return TaskResult(
                success=False,
                task_name="DeleteSnapshot",
                message=f"Snapshot '{snapshot_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = snapshot.RemoveSnapshot_Task(removeChildren=remove_children)

            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="DeleteSnapshot",
                    message=f"Snapshot '{snapshot_name}' deleted" if result.success else result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="DeleteSnapshot",
                message="Delete task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="DeleteSnapshot",
                message="Failed to delete snapshot",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    def delete_all_snapshots(self, vm_name: str, wait: bool = True) -> TaskResult:
        """Delete all snapshots for a VM."""
        vm = self._get_vm(vm_name)
        if not vm:
            return TaskResult(
                success=False,
                task_name="DeleteAllSnapshots",
                message=f"VM '{vm_name}' not found",
                duration_sec=0,
                vm_name=vm_name,
            )

        if not vm.snapshot:
            return TaskResult(
                success=True,
                task_name="DeleteAllSnapshots",
                message="No snapshots to delete",
                duration_sec=0,
                vm_name=vm_name,
            )

        try:
            task = vm.RemoveAllSnapshots_Task()

            if wait:
                result = self._wait_for_task(task)
                return TaskResult(
                    success=result.success,
                    task_name="DeleteAllSnapshots",
                    message="All snapshots deleted" if result.success else result.message,
                    duration_sec=result.duration_sec,
                    vm_name=vm_name,
                    error_message=result.error_message,
                )
            return TaskResult(
                success=True,
                task_name="DeleteAllSnapshots",
                message="Delete all snapshots task started",
                duration_sec=0,
                vm_name=vm_name,
            )
        except Exception as e:
            return TaskResult(
                success=False,
                task_name="DeleteAllSnapshots",
                message="Failed to delete snapshots",
                duration_sec=0,
                vm_name=vm_name,
                error_message=str(e),
            )

    # ========================================
    # Hardware Configuration
    # ========================================

    def get_hardware_config(self, vm_name: str) -> Optional[VMHardwareConfig]:
        """Get VM hardware configuration."""
        vm = self._get_vm(vm_name)
        if not vm:
            return None

        from pyVmomi import vim

        return VMHardwareConfig(
            cpu_count=vm.config.hardware.numCPU,
            cpu_cores_per_socket=vm.config.hardware.numCoresPerSocket,
            memory_mb=vm.config.hardware.memoryMB,
            num_ethernet_cards=len([
                d for d in vm.config.hardware.device
                if isinstance(d, vim.vm.device.VirtualEthernetCard)
            ]),
            num_virtual_disks=len([
                d for d in vm.config.hardware.device
                if isinstance(d, vim.vm.device.VirtualDisk)
            ]),
            guest_os_id=vm.config.guestId,
            guest_os_full_name=vm.config.guestFullName,
        )

    def wait_for_guest_tools(
        self,
        vm_name: str,
        timeout: int = 300,
    ) -> bool:
        """Wait for VMware Tools to become available."""
        vm = self._get_vm(vm_name)
        if not vm:
            return False

        start = time.time()
        while time.time() - start < timeout:
            vm = self._get_vm(vm_name)
            if vm and vm.guest and vm.guest.toolsRunningStatus == "guestToolsRunning":
                return True
            time.sleep(5)

        return False

    def wait_for_ip_address(
        self,
        vm_name: str,
        timeout: int = 300,
    ) -> Optional[str]:
        """Wait for VM to get an IP address."""
        vm = self._get_vm(vm_name)
        if not vm:
            return None

        start = time.time()
        while time.time() - start < timeout:
            vm = self._get_vm(vm_name)
            if vm and vm.guest and vm.guest.ipAddress:
                return vm.guest.ipAddress
            time.sleep(5)

        return None

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
