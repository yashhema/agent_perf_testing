"""Hypervisor provider abstraction.

HypervisorProvider interface with implementations for Proxmox, vSphere, and Vultr.
Factory creates provider from LabORM.hypervisor_type.

Data model:
    ServerORM.server_infra_ref  — provider-specific VM identifier
        Proxmox:  {"node": "pve1", "vmid": 105}
        vSphere:  {"datacenter": "DC1", "vm_name": "target-rhel8"}
        Vultr:    {"instance_id": "uuid", "region": "ewr"}

    BaselineORM.provider_ref    — provider-specific snapshot identifier
        Proxmox:  {"snapshot_name": "clean-base"}
        vSphere:  {"snapshot_name": "clean-base", "snapshot_moref_id": "3"}
        Vultr:    {"snapshot_id": "uuid", "snapshot_name": "clean-base"}
"""

import abc
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VMStatus:
    """Status of a virtual machine."""
    name: str
    status: str  # "running", "stopped", "unknown"
    uptime_sec: Optional[float] = None


@dataclass
class HypervisorSnapshot:
    """Common snapshot structure returned by all providers.

    Every provider MUST normalize its API response into this structure.
    The UI and backend rely on these exact field names and types.
    """
    name: str                          # Human-readable snapshot name
    description: str                   # Snapshot description (empty string if none)
    id: str                            # Provider-unique ID (Proxmox=name, vSphere=moref, Vultr=uuid)
    parent: Optional[str]              # Parent snapshot ID (None if root)
    created: Optional[int]             # Unix timestamp (seconds). None if unavailable.

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "id": self.id,
            "parent": self.parent,
            "created": self.created,
        }


class HypervisorProvider(abc.ABC):
    """Abstract interface for hypervisor operations.

    All snapshot methods take two separate dicts:
        server_ref  — from ServerORM.server_infra_ref (identifies the VM)
        snapshot_ref — from BaselineORM.provider_ref (identifies the snapshot)
    """

    @abc.abstractmethod
    def restore_snapshot(self, server_ref: dict, snapshot_ref: dict) -> Optional[str]:
        """Restore a VM to a specific snapshot.

        Args:
            server_ref: Provider-specific VM reference (ServerORM.server_infra_ref).
            snapshot_ref: Provider-specific snapshot reference (BaselineORM.provider_ref).

        Returns:
            New IP address if it changed (Vultr), or None if unchanged (Proxmox/vSphere).
        """

    @abc.abstractmethod
    def get_vm_status(self, server_ref: dict) -> VMStatus:
        """Get current status of a VM.

        Args:
            server_ref: Provider-specific VM reference (ServerORM.server_infra_ref).
        """

    @abc.abstractmethod
    def create_snapshot(self, server_ref: dict, snapshot_name: str, description: str = "") -> dict:
        """Create a new snapshot of a VM.

        Args:
            server_ref: Provider-specific VM reference (ServerORM.server_infra_ref).
            snapshot_name: Logical name for the new snapshot.
            description: Optional description.

        Returns:
            snapshot_ref dict suitable for storing in BaselineORM.provider_ref.
        """

    @abc.abstractmethod
    def snapshot_exists(self, server_ref: dict, snapshot_ref: dict) -> bool:
        """Check if a snapshot exists on the hypervisor.

        Args:
            server_ref: Provider-specific VM reference (ServerORM.server_infra_ref).
            snapshot_ref: Provider-specific snapshot reference (BaselineORM.provider_ref).
        """

    @abc.abstractmethod
    def list_snapshots(self, server_ref: dict) -> List[HypervisorSnapshot]:
        """Get the full snapshot list for a VM.

        Returns:
            List of HypervisorSnapshot with common fields:
              name, description, id, parent, created (unix timestamp).
            The "id" field is the provider-specific unique identifier per VM:
              - Proxmox: snapshot name (unique per VM)
              - vSphere: MoRef integer ID (as string)
              - Vultr: snapshot UUID
        """

    @abc.abstractmethod
    def delete_snapshot(self, server_ref: dict, snapshot_ref: dict) -> None:
        """Delete a snapshot from the VM.

        Args:
            server_ref: Provider-specific VM reference.
            snapshot_ref: Provider-specific snapshot reference.
        """

    def wait_for_vm_ready(self, server_ref: dict, timeout_sec: int = 300, poll_interval_sec: int = 10) -> bool:
        """Wait until VM is running. Returns True if ready, False on timeout."""
        elapsed = 0
        while elapsed < timeout_sec:
            try:
                status = self.get_vm_status(server_ref)
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
    server_ref format:   {"node": "pve1", "vmid": 105}
    snapshot_ref format: {"snapshot_name": "clean-rhel8"}
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

    def restore_snapshot(self, server_ref: dict, snapshot_ref: dict) -> Optional[str]:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        snapshot_name = snapshot_ref["snapshot_name"]
        logger.info("Restoring snapshot '%s' on %s/qemu/%d", snapshot_name, node, vmid)
        # Rollback returns a task UPID — must wait for completion before starting VM
        upid = self._proxmox.nodes(node).qemu(vmid).snapshot(snapshot_name).rollback.post()
        if upid:
            self._wait_for_task(node, upid, timeout_sec=300)
        # Start VM after rollback completes
        try:
            self._proxmox.nodes(node).qemu(vmid).status.start.post()
        except Exception as e:
            # "already running" is OK — some snapshots restore to running state
            if "already running" not in str(e).lower():
                raise
            logger.info("VM %d already running after rollback", vmid)
        return None  # Proxmox IPs are static, no change

    def _wait_for_task(self, node: str, upid: str, timeout_sec: int = 300) -> None:
        """Wait for a Proxmox task to complete."""
        import time as _time
        elapsed = 0
        poll_sec = 3
        while elapsed < timeout_sec:
            try:
                task = self._proxmox.nodes(node).tasks(upid).status.get()
                status = task.get("status", "")
                if status == "stopped":
                    exit_status = task.get("exitstatus", "")
                    if exit_status == "OK":
                        logger.info("Task %s completed OK (waited %ds)", upid[:30], elapsed)
                        return
                    else:
                        raise RuntimeError(
                            f"Proxmox task failed: {exit_status} (upid={upid})"
                        )
            except RuntimeError:
                raise
            except Exception as e:
                logger.debug("Task status check failed: %s", e)
            _time.sleep(poll_sec)
            elapsed += poll_sec
        raise TimeoutError(f"Proxmox task {upid} did not complete within {timeout_sec}s")

    def get_vm_status(self, server_ref: dict) -> VMStatus:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        status_data = self._proxmox.nodes(node).qemu(vmid).status.current.get()
        return VMStatus(
            name=status_data.get("name", str(vmid)),
            status=status_data.get("status", "unknown"),
            uptime_sec=status_data.get("uptime", 0),
        )

    def create_snapshot(self, server_ref: dict, snapshot_name: str, description: str = "") -> dict:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        logger.info("Creating snapshot '%s' on %s/qemu/%d", snapshot_name, node, vmid)
        self._proxmox.nodes(node).qemu(vmid).snapshot.post(
            snapname=snapshot_name,
            description=description,
        )
        return {"snapshot_name": snapshot_name}

    def snapshot_exists(self, server_ref: dict, snapshot_ref: dict) -> bool:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        snapshot_name = snapshot_ref.get("snapshot_name", "")
        snapshots = self._proxmox.nodes(node).qemu(vmid).snapshot.get()
        return any(s.get("name") == snapshot_name for s in snapshots)

    def list_snapshots(self, server_ref: dict) -> List[HypervisorSnapshot]:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        snapshots = self._proxmox.nodes(node).qemu(vmid).snapshot.get()
        # Proxmox returns flat list with "parent" field; exclude "current" entry
        # Proxmox enforces unique names per VM, so id = name
        return [
            HypervisorSnapshot(
                name=s["name"],
                description=s.get("description", ""),
                id=s["name"],
                parent=s.get("parent"),
                created=s.get("snaptime"),
            )
            for s in snapshots
            if s.get("name") != "current"
        ]

    def delete_snapshot(self, server_ref: dict, snapshot_ref: dict) -> None:
        node = server_ref["node"]
        vmid = server_ref["vmid"]
        snapshot_name = snapshot_ref.get("snapshot_name", "")
        logger.info("Deleting snapshot '%s' on %s/qemu/%d", snapshot_name, node, vmid)
        self._proxmox.nodes(node).qemu(vmid).snapshot(snapshot_name).delete()


class VSphereProvider(HypervisorProvider):
    """VMware vSphere hypervisor provider.

    Uses pyvmomi library for API access.
    server_ref format:   {"datacenter": "DC1", "vm_name": "target-rhel8"}
    snapshot_ref format: {"snapshot_name": "clean-rhel8"}
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

    def _find_vm(self, server_ref: dict):
        from pyVmomi import vim
        vm_name = server_ref.get("vm_name", "")
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

    def _find_snapshot_by_moref(self, vm, moref_id: str):
        """Recursively find a snapshot by MoRef ID (unique within VM)."""
        if not vm.snapshot:
            return None
        return self._search_snapshot_tree_by_id(vm.snapshot.rootSnapshotList, int(moref_id))

    def _search_snapshot_tree(self, snapshot_list, snapshot_name):
        for snap in snapshot_list:
            if snap.name == snapshot_name:
                return snap.snapshot
            found = self._search_snapshot_tree(snap.childSnapshotList, snapshot_name)
            if found:
                return found
        return None

    def _search_snapshot_tree_by_id(self, snapshot_list, moref_id: int):
        """Search snapshot tree by MoRef integer ID."""
        for snap in snapshot_list:
            if snap.id == moref_id:
                return snap.snapshot
            found = self._search_snapshot_tree_by_id(snap.childSnapshotList, moref_id)
            if found:
                return found
        return None

    def _resolve_snapshot(self, vm, snapshot_ref: dict):
        """Find snapshot by MoRef ID (preferred) or fall back to name."""
        moref_id = snapshot_ref.get("snapshot_moref_id")
        if moref_id:
            snap = self._find_snapshot_by_moref(vm, moref_id)
            if snap:
                return snap
        snapshot_name = snapshot_ref.get("snapshot_name", "")
        return self._find_snapshot(vm, snapshot_name)

    def restore_snapshot(self, server_ref: dict, snapshot_ref: dict) -> Optional[str]:
        vm = self._find_vm(server_ref)
        snapshot = self._resolve_snapshot(vm, snapshot_ref)
        if not snapshot:
            raise ValueError(f"Snapshot not found on VM '{vm.name}': {snapshot_ref}")
        snapshot_name = snapshot_ref.get("snapshot_name", snapshot_ref.get("snapshot_moref_id"))
        logger.info("Restoring snapshot '%s' on VM '%s'", snapshot_name, vm.name)
        task = snapshot.RevertToSnapshot_Task()
        self._wait_for_task(task)
        # Power on if not already running
        from pyVmomi import vim
        if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
            task = vm.PowerOnVM_Task()
            self._wait_for_task(task)
        return None  # vSphere IPs are static, no change

    def get_vm_status(self, server_ref: dict) -> VMStatus:
        from pyVmomi import vim
        vm = self._find_vm(server_ref)
        power_state = vm.runtime.powerState
        status = "running" if power_state == vim.VirtualMachinePowerState.poweredOn else "stopped"
        return VMStatus(name=vm.name, status=status)

    def create_snapshot(self, server_ref: dict, snapshot_name: str, description: str = "") -> dict:
        vm = self._find_vm(server_ref)
        logger.info("Creating snapshot '%s' on VM '%s'", snapshot_name, vm.name)
        task = vm.CreateSnapshot_Task(
            name=snapshot_name,
            description=description,
            memory=False,
            quiesce=True,
        )
        self._wait_for_task(task)
        # Re-read VM to find the newly created snapshot's MoRef ID
        vm = self._find_vm(server_ref)
        moref_id = self._find_moref_by_name_latest(vm, snapshot_name)
        return {"snapshot_name": snapshot_name, "snapshot_moref_id": moref_id}

    def _find_moref_by_name_latest(self, vm, snapshot_name: str) -> Optional[str]:
        """Find the MoRef ID for a snapshot by name. If duplicates, return the highest ID."""
        if not vm.snapshot:
            return None
        matches = []
        self._collect_morefs_by_name(vm.snapshot.rootSnapshotList, snapshot_name, matches)
        if not matches:
            return None
        # Highest ID = most recently created
        return str(max(matches))

    def _collect_morefs_by_name(self, snapshot_list, name: str, result: list):
        for snap in snapshot_list:
            if snap.name == name:
                result.append(snap.id)
            self._collect_morefs_by_name(snap.childSnapshotList, name, result)

    def snapshot_exists(self, server_ref: dict, snapshot_ref: dict) -> bool:
        vm = self._find_vm(server_ref)
        return self._resolve_snapshot(vm, snapshot_ref) is not None

    def list_snapshots(self, server_ref: dict) -> List[HypervisorSnapshot]:
        vm = self._find_vm(server_ref)
        if not vm.snapshot:
            return []
        result: List[HypervisorSnapshot] = []
        self._collect_snapshot_tree(vm.snapshot.rootSnapshotList, parent_id=None, result=result)
        return result

    def _collect_snapshot_tree(self, snapshot_list, parent_id: Optional[str], result: List[HypervisorSnapshot]):
        """Recursively collect all snapshots into a flat list with parent references."""
        for snap in snapshot_list:
            snap_id = str(snap.id)
            # Convert vSphere datetime to unix timestamp
            created_ts = None
            try:
                created_ts = int(snap.createTime.timestamp())
            except Exception:
                pass
            result.append(HypervisorSnapshot(
                name=snap.name,
                description=snap.description or "",
                id=snap_id,
                parent=parent_id,
                created=created_ts,
            ))
            self._collect_snapshot_tree(snap.childSnapshotList, parent_id=snap_id, result=result)

    def delete_snapshot(self, server_ref: dict, snapshot_ref: dict) -> None:
        vm = self._find_vm(server_ref)
        snapshot = self._resolve_snapshot(vm, snapshot_ref)
        snapshot_name = snapshot_ref.get("snapshot_name", snapshot_ref.get("snapshot_moref_id"))
        if snapshot:
            logger.info("Deleting snapshot '%s' from VM '%s'", snapshot_name, vm.name)
            task = snapshot.RemoveSnapshot_Task(removeChildren=False)
            self._wait_for_task(task)
        else:
            logger.warning("Snapshot '%s' not found on VM '%s'", snapshot_name, vm.name)

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


class VultrProvider(HypervisorProvider):
    """Vultr cloud provider.

    Uses httpx for Vultr API v2 access.
    server_ref format:   {"instance_id": "uuid-string", "region": "ewr"}
    snapshot_ref format: {"snapshot_id": "uuid-string", "snapshot_name": "clean-base"}
    """

    VULTR_API_BASE = "https://api.vultr.com/v2"

    def __init__(self, api_key: str):
        import httpx
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=self.VULTR_API_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        logger.info("Vultr provider initialized")

    def _request(self, method: str, path: str, **kwargs):
        """Make an API request with retry on 429/5xx."""
        max_retries = 3
        resp = None
        for attempt in range(1, max_retries + 1):
            resp = self._client.request(method, path, **kwargs)
            if resp.status_code in (200, 201, 202, 204):
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = min(2 ** attempt, 30)
                logger.warning("Vultr API %d on %s, retry in %ds", resp.status_code, path, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
        if resp is not None:
            resp.raise_for_status()

    def _get_instance(self, instance_id: str) -> dict:
        """Get instance details from Vultr API."""
        resp = self._request("GET", f"/instances/{instance_id}")
        return resp.json()["instance"]

    def _get_snapshot_by_id(self, snapshot_id: str) -> Optional[dict]:
        """Get snapshot details, returns None if not found."""
        try:
            resp = self._request("GET", f"/snapshots/{snapshot_id}")
            return resp.json()["snapshot"]
        except Exception:
            return None

    def restore_snapshot(self, server_ref: dict, snapshot_ref: dict) -> Optional[str]:
        """Restore instance from a snapshot.

        Args:
            server_ref: {"instance_id": "..."} from ServerORM.server_infra_ref.
            snapshot_ref: {"snapshot_id": "..."} from BaselineORM.provider_ref.

        Returns:
            The instance's main_ip after restore (may differ from pre-restore IP).
        """
        instance_id = server_ref["instance_id"]
        snapshot_id = snapshot_ref.get("snapshot_id")
        if not snapshot_id:
            raise ValueError(
                f"snapshot_ref missing 'snapshot_id'. Got: {snapshot_ref}. "
                f"BaselineORM.provider_ref must contain {{'snapshot_id': '<vultr-uuid>'}}."
            )
        snapshot_name = snapshot_ref.get("snapshot_name", snapshot_id)
        logger.info("Restoring instance %s from snapshot %s (%s)", instance_id, snapshot_name, snapshot_id)
        self._request("POST", f"/instances/{instance_id}/restore", json={"snapshot_id": snapshot_id})

        # Wait for restore to begin — Vultr API is async so the instance
        # may still show "active/running" for a few seconds before the
        # restore process actually kicks in and transitions it.
        logger.info("Waiting for restore to begin on %s...", instance_id)
        time.sleep(15)

        # Poll until instance is active and running again
        elapsed = 15
        timeout = 600
        while elapsed < timeout:
            instance = self._get_instance(instance_id)
            status = instance.get("status")
            power = instance.get("power_status")
            logger.debug("Instance %s: status=%s, power=%s (elapsed=%ds)", instance_id, status, power, elapsed)
            if status == "active" and power == "running":
                new_ip = instance.get("main_ip")
                logger.info("Instance %s restored and running, ip=%s (took %ds)", instance_id, new_ip, elapsed)
                return new_ip
            time.sleep(15)
            elapsed += 15
        raise TimeoutError(f"Instance {instance_id} not active after restore ({timeout}s)")

    def get_vm_status(self, server_ref: dict) -> VMStatus:
        """Get current status of a Vultr instance."""
        instance_id = server_ref["instance_id"]
        instance = self._get_instance(instance_id)

        vultr_status = instance.get("status", "unknown")
        power_status = instance.get("power_status", "unknown")

        # Map Vultr statuses to our standard statuses
        if vultr_status == "active" and power_status == "running":
            status = "running"
        elif vultr_status == "active" and power_status == "stopped":
            status = "stopped"
        else:
            status = "unknown"

        return VMStatus(
            name=instance.get("label", instance_id),
            status=status,
        )

    def create_snapshot(self, server_ref: dict, snapshot_name: str, description: str = "") -> dict:
        """Create a snapshot of a Vultr instance.

        Returns:
            snapshot_ref dict: {"snapshot_id": "...", "snapshot_name": "..."}.
        """
        instance_id = server_ref["instance_id"]
        logger.info("Creating snapshot '%s' for instance %s", snapshot_name, instance_id)

        resp = self._request("POST", "/snapshots", json={
            "instance_id": instance_id,
            "description": description or f"{snapshot_name} snapshot",
        })
        snapshot = resp.json()["snapshot"]
        snapshot_id = snapshot["id"]

        # Poll until snapshot is complete
        elapsed = 0
        timeout = 900
        while elapsed < timeout:
            snap = self._get_snapshot_by_id(snapshot_id)
            if snap and snap.get("status") == "complete":
                break
            time.sleep(20)
            elapsed += 20
        else:
            raise TimeoutError(f"Snapshot {snapshot_id} not complete after {timeout}s")

        logger.info("Snapshot '%s' -> %s complete", snapshot_name, snapshot_id)
        return {"snapshot_id": snapshot_id, "snapshot_name": snapshot_name}

    def snapshot_exists(self, server_ref: dict, snapshot_ref: dict) -> bool:
        """Check if snapshot still exists on Vultr."""
        snapshot_id = snapshot_ref.get("snapshot_id")
        if not snapshot_id:
            return False
        snap = self._get_snapshot_by_id(snapshot_id)
        return snap is not None

    def list_snapshots(self, server_ref: dict) -> List[HypervisorSnapshot]:
        """List all Vultr snapshots. Vultr snapshots are flat (no hierarchy)."""
        from datetime import datetime as dt
        resp = self._request("GET", "/snapshots")
        snapshots = resp.json().get("snapshots", [])
        result = []
        for s in snapshots:
            created_ts = None
            try:
                created_ts = int(dt.fromisoformat(s["date_created"].replace("Z", "+00:00")).timestamp())
            except Exception:
                pass
            result.append(HypervisorSnapshot(
                name=s.get("description", s["id"]),
                description=s.get("description", ""),
                id=s["id"],
                parent=None,  # Vultr snapshots have no parent hierarchy
                created=created_ts,
            ))
        return result

    def delete_snapshot(self, server_ref: dict, snapshot_ref: dict) -> None:
        """Delete a Vultr snapshot."""
        snapshot_id = snapshot_ref.get("snapshot_id")
        if not snapshot_id:
            raise ValueError("snapshot_ref missing 'snapshot_id'")
        logger.info("Deleting Vultr snapshot %s", snapshot_id)
        self._request("DELETE", f"/snapshots/{snapshot_id}")


def create_hypervisor_provider(
    hypervisor_type: str,
    url: str,
    port: int,
    credential,  # ProxmoxCredential, VSphereCredential, or VultrCredential
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
    elif hypervisor_type == "vultr":
        return VultrProvider(api_key=credential.api_key)
    else:
        raise ValueError(f"Unsupported hypervisor_type: {hypervisor_type}")
