"""Hypervisor provider abstraction.

HypervisorProvider interface with implementations for Proxmox and vSphere.
Factory creates provider from LabORM.hypervisor_type.
"""

import abc
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VMStatus:
    """Status of a virtual machine."""
    name: str
    status: str  # "running", "stopped", "unknown"
    uptime_sec: Optional[float] = None


class HypervisorProvider(abc.ABC):
    """Abstract interface for hypervisor operations."""

    @abc.abstractmethod
    def restore_snapshot(self, provider_ref: dict, snapshot_name: str) -> None:
        """Restore a VM to a specific snapshot.

        Args:
            provider_ref: Provider-specific VM reference (from BaselineORM.provider_ref
                          or ServerORM.server_infra_ref)
            snapshot_name: Name of snapshot to restore
        """

    @abc.abstractmethod
    def get_vm_status(self, provider_ref: dict) -> VMStatus:
        """Get current status of a VM.

        Args:
            provider_ref: Provider-specific VM reference
        """

    @abc.abstractmethod
    def create_snapshot(self, provider_ref: dict, snapshot_name: str, description: str = "") -> dict:
        """Create a new snapshot of a VM.

        Args:
            provider_ref: Provider-specific VM reference
            snapshot_name: Name for new snapshot
            description: Optional description

        Returns:
            Updated provider_ref including the new snapshot reference
        """

    @abc.abstractmethod
    def snapshot_exists(self, provider_ref: dict, snapshot_name: str) -> bool:
        """Check if a snapshot exists on the hypervisor."""

    def wait_for_vm_ready(self, provider_ref: dict, timeout_sec: int = 300, poll_interval_sec: int = 10) -> bool:
        """Wait until VM is running. Returns True if ready, False on timeout."""
        elapsed = 0
        while elapsed < timeout_sec:
            try:
                status = self.get_vm_status(provider_ref)
                if status.status == "running":
                    logger.info("VM %s is running (waited %ds)", status.name, elapsed)
                    return True
            except Exception as e:
                logger.debug("VM status check failed (elapsed=%ds): %s", elapsed, e)
            time.sleep(poll_interval_sec)
            elapsed += poll_interval_sec
        logger.error("VM not ready after %ds", timeout_sec)
        return False


class ProxmoxProvider(HypervisorProvider):
    """Proxmox VE hypervisor provider.

    Uses proxmoxer library for API access.
    provider_ref format: {"node": "pve1", "vmid": 105, "snapshot_name": "clean-rhel8"}
    """

    def __init__(self, url: str, port: int, api_key: str, verify_ssl: bool = False):
        from proxmoxer import ProxmoxAPI
        # Parse API key format: PVEAPIToken=user@realm!tokenid=secret
        # proxmoxer expects token_name and token_value separately
        self._url = url
        self._port = port
        if api_key.startswith("PVEAPIToken="):
            token_part = api_key[len("PVEAPIToken="):]
            token_name, token_value = token_part.split("=", 1)
            self._proxmox = ProxmoxAPI(
                url, port=port,
                user=token_name.split("!")[0],
                token_name=token_name.split("!")[-1],
                token_value=token_value,
                verify_ssl=verify_ssl,
            )
        else:
            raise ValueError("Proxmox API key must start with 'PVEAPIToken='")
        logger.info("Proxmox connected to %s:%d", url, port)

    def restore_snapshot(self, provider_ref: dict, snapshot_name: str) -> None:
        node = provider_ref["node"]
        vmid = provider_ref["vmid"]
        logger.info("Restoring snapshot '%s' on %s/qemu/%d", snapshot_name, node, vmid)
        self._proxmox.nodes(node).qemu(vmid).snapshot(snapshot_name).rollback.post()
        # Start VM after restore
        self._proxmox.nodes(node).qemu(vmid).status.start.post()

    def get_vm_status(self, provider_ref: dict) -> VMStatus:
        node = provider_ref["node"]
        vmid = provider_ref["vmid"]
        status_data = self._proxmox.nodes(node).qemu(vmid).status.current.get()
        return VMStatus(
            name=status_data.get("name", str(vmid)),
            status=status_data.get("status", "unknown"),
            uptime_sec=status_data.get("uptime", 0),
        )

    def create_snapshot(self, provider_ref: dict, snapshot_name: str, description: str = "") -> dict:
        node = provider_ref["node"]
        vmid = provider_ref["vmid"]
        logger.info("Creating snapshot '%s' on %s/qemu/%d", snapshot_name, node, vmid)
        self._proxmox.nodes(node).qemu(vmid).snapshot.post(
            snapname=snapshot_name,
            description=description,
        )
        return {**provider_ref, "snapshot_name": snapshot_name}

    def snapshot_exists(self, provider_ref: dict, snapshot_name: str) -> bool:
        node = provider_ref["node"]
        vmid = provider_ref["vmid"]
        snapshots = self._proxmox.nodes(node).qemu(vmid).snapshot.get()
        return any(s.get("name") == snapshot_name for s in snapshots)


class VSphereProvider(HypervisorProvider):
    """VMware vSphere hypervisor provider.

    Uses pyvmomi library for API access.
    provider_ref format: {"datacenter": "DC1", "vm_path": "/folder/vm-name",
                          "vm_name": "target-rhel8", "snapshot_name": "clean-rhel8"}
    """

    def __init__(self, url: str, port: int, username: str, password: str, verify_ssl: bool = False):
        from pyVim.connect import SmartConnect
        import ssl
        ssl_context = None
        if not verify_ssl:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        self._si = SmartConnect(
            host=url,
            port=port,
            user=username,
            pwd=password,
            sslContext=ssl_context,
        )
        self._content = self._si.RetrieveContent()
        logger.info("vSphere connected to %s:%d", url, port)

    def _find_vm(self, provider_ref: dict):
        from pyVmomi import vim
        vm_name = provider_ref.get("vm_name", "")
        container = self._content.viewManager.CreateContainerView(
            self._content.rootFolder, [vim.VirtualMachine], True
        )
        for vm in container.view:
            if vm.name == vm_name:
                container.Destroy()
                return vm
        container.Destroy()
        raise ValueError(f"VM '{vm_name}' not found in vSphere")

    def _find_snapshot(self, vm, snapshot_name: str):
        """Recursively find a snapshot by name in the snapshot tree."""
        if not vm.snapshot:
            return None
        return self._search_snapshot_tree(vm.snapshot.rootSnapshotList, snapshot_name)

    def _search_snapshot_tree(self, snapshot_list, snapshot_name):
        for snap in snapshot_list:
            if snap.name == snapshot_name:
                return snap.snapshot
            found = self._search_snapshot_tree(snap.childSnapshotList, snapshot_name)
            if found:
                return found
        return None

    def restore_snapshot(self, provider_ref: dict, snapshot_name: str) -> None:
        vm = self._find_vm(provider_ref)
        snapshot = self._find_snapshot(vm, snapshot_name)
        if not snapshot:
            raise ValueError(f"Snapshot '{snapshot_name}' not found on VM '{vm.name}'")
        logger.info("Restoring snapshot '%s' on VM '%s'", snapshot_name, vm.name)
        task = snapshot.RevertToSnapshot_Task()
        self._wait_for_task(task)
        # Power on if not already running
        from pyVmomi import vim
        if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
            task = vm.PowerOnVM_Task()
            self._wait_for_task(task)

    def get_vm_status(self, provider_ref: dict) -> VMStatus:
        from pyVmomi import vim
        vm = self._find_vm(provider_ref)
        power_state = vm.runtime.powerState
        status = "running" if power_state == vim.VirtualMachinePowerState.poweredOn else "stopped"
        return VMStatus(name=vm.name, status=status)

    def create_snapshot(self, provider_ref: dict, snapshot_name: str, description: str = "") -> dict:
        vm = self._find_vm(provider_ref)
        logger.info("Creating snapshot '%s' on VM '%s'", snapshot_name, vm.name)
        task = vm.CreateSnapshot_Task(
            name=snapshot_name,
            description=description,
            memory=False,
            quiesce=True,
        )
        self._wait_for_task(task)
        return {**provider_ref, "snapshot_name": snapshot_name}

    def snapshot_exists(self, provider_ref: dict, snapshot_name: str) -> bool:
        vm = self._find_vm(provider_ref)
        return self._find_snapshot(vm, snapshot_name) is not None

    def _wait_for_task(self, task, timeout_sec: int = 600):
        """Wait for a vSphere task to complete."""
        from pyVmomi import vim
        elapsed = 0
        while elapsed < timeout_sec:
            if task.info.state == vim.TaskInfo.State.success:
                return
            if task.info.state == vim.TaskInfo.State.error:
                raise RuntimeError(f"vSphere task failed: {task.info.error}")
            time.sleep(5)
            elapsed += 5
        raise TimeoutError(f"vSphere task timed out after {timeout_sec}s")


def create_hypervisor_provider(
    hypervisor_type: str,
    url: str,
    port: int,
    credential,  # ProxmoxCredential or VSphereCredential
) -> HypervisorProvider:
    """Factory: create HypervisorProvider from type and credentials."""
    if hypervisor_type == "proxmox":
        return ProxmoxProvider(
            url=url,
            port=port,
            api_key=credential.api_key,
            verify_ssl=credential.verify_ssl,
        )
    elif hypervisor_type == "vsphere":
        return VSphereProvider(
            url=url,
            port=port,
            username=credential.username,
            password=credential.password,
            verify_ssl=credential.verify_ssl,
        )
    else:
        raise ValueError(f"Unsupported hypervisor_type: {hypervisor_type}")
