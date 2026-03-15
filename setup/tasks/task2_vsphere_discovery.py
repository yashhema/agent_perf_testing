"""Task 2: Discover server details from vSphere.

Connects to vCenter, finds each VM from servers.csv by hostname/IP,
extracts hardware and snapshot info, writes discovery_output.json.
"""

import json
import logging
import ssl
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

from .common import (
    SetupConfig, load_servers, load_credentials, validate_servers,
)

logger = logging.getLogger("setup.task2")


def _find_vm_by_name_or_ip(content, hostname: str, ip: str):
    """Search vSphere inventory for a VM matching hostname or IP."""
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    try:
        for vm in container.view:
            if vm.name and vm.name.lower() == hostname.lower():
                return vm
            # Check guest hostname
            if vm.guest and vm.guest.hostName:
                if vm.guest.hostName.lower() == hostname.lower():
                    return vm
            # Check IP addresses
            if vm.guest and vm.guest.net:
                for nic in vm.guest.net:
                    if nic.ipAddress:
                        for addr in nic.ipAddress:
                            if addr == ip:
                                return vm
    finally:
        container.Destroy()
    return None


def _get_snapshots(snapshot_tree, prefix=""):
    """Recursively collect snapshot info from a VM's snapshot tree."""
    snapshots = []
    if not snapshot_tree:
        return snapshots
    for snap in snapshot_tree:
        snap_info = {
            "name": snap.name,
            "description": snap.description,
            "id": snap.id,
            "create_time": str(snap.createTime),
            "state": str(snap.state),
            "snapshot_moref": str(snap.snapshot),
        }
        snapshots.append(snap_info)
        if snap.childSnapshotList:
            snapshots.extend(_get_snapshots(snap.childSnapshotList))
    return snapshots


def _extract_vm_details(vm) -> dict:
    """Extract hardware, OS, network, and snapshot details from a VM object."""
    config = vm.config
    summary = vm.summary
    guest = vm.guest
    hardware = config.hardware if config else None

    # Disk info
    disks = []
    if hardware:
        for dev in hardware.device:
            if isinstance(dev, vim.vm.device.VirtualDisk):
                disks.append({
                    "label": dev.deviceInfo.label,
                    "size_gb": round(dev.capacityInKB / (1024 * 1024), 2),
                    "thin_provisioned": getattr(dev.backing, "thinProvisioned", None),
                    "datastore": str(dev.backing.datastore.name) if hasattr(dev.backing, "datastore") and dev.backing.datastore else None,
                })

    # Network info
    nics = []
    if guest and guest.net:
        for nic in guest.net:
            nics.append({
                "network": nic.network,
                "mac_address": nic.macAddress,
                "ip_addresses": list(nic.ipAddress) if nic.ipAddress else [],
                "connected": nic.connected,
            })

    # Snapshots
    snapshots = []
    if vm.snapshot:
        snapshots = _get_snapshots(vm.snapshot.rootSnapshotList)

    # Datastore(s)
    datastores = []
    if vm.datastore:
        for ds in vm.datastore:
            datastores.append(ds.name)

    return {
        "vm_name": vm.name,
        "vm_moref": str(vm._moId),
        "power_state": str(summary.runtime.powerState),
        "guest_os_id": config.guestId if config else None,
        "guest_os_full": config.guestFullName if config else None,
        "guest_hostname": guest.hostName if guest else None,
        "guest_ip": guest.ipAddress if guest else None,
        "cpu_count": hardware.numCPU if hardware else None,
        "cpu_cores_per_socket": hardware.numCoresPerSocket if hardware else None,
        "memory_mb": hardware.memoryMB if hardware else None,
        "memory_gb": round(hardware.memoryMB / 1024, 2) if hardware and hardware.memoryMB else None,
        "disks": disks,
        "total_disk_gb": sum(d["size_gb"] for d in disks),
        "disk_type": "ssd",  # default — vSphere doesn't always expose this
        "nics": nics,
        "datastores": datastores,
        "snapshots": snapshots,
        "snapshot_count": len(snapshots),
        "resource_pool": str(vm.resourcePool.name) if vm.resourcePool else None,
        "folder": str(vm.parent.name) if vm.parent else None,
    }


def run(config: SetupConfig):
    """Run Task 2: discover server details from vSphere."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    validate_servers(servers)

    logger.info("=" * 60)
    logger.info("TASK 2: vSphere discovery for %d servers", len(servers))
    logger.info("  vCenter: %s:%d", config.vsphere_host, config.vsphere_port)
    logger.info("=" * 60)

    # Connect to vSphere
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    logger.info("Connecting to vCenter %s ...", config.vsphere_host)
    si = SmartConnect(
        host=config.vsphere_host,
        user=creds.vsphere_user,
        pwd=creds.vsphere_pass,
        port=config.vsphere_port,
        sslContext=context,
    )

    try:
        content = si.RetrieveContent()
        logger.info("Connected to vCenter: %s", content.about.fullName)

        discovery = {}
        found = 0
        missing = 0

        for server in servers:
            logger.info("Looking up VM: %s (%s) ...", server.hostname, server.ip)
            vm = _find_vm_by_name_or_ip(content, server.hostname, server.ip)

            if vm is None:
                logger.warning("  NOT FOUND in vSphere: %s", server.hostname)
                discovery[server.hostname] = {
                    "status": "not_found",
                    "server_csv": {
                        "hostname": server.hostname,
                        "ip": server.ip,
                        "os": server.os,
                        "role": server.role,
                    },
                }
                missing += 1
                continue

            details = _extract_vm_details(vm)
            details["status"] = "found"
            details["server_csv"] = {
                "hostname": server.hostname,
                "ip": server.ip,
                "os": server.os,
                "role": server.role,
            }
            discovery[server.hostname] = details
            found += 1
            logger.info("  FOUND: %s — %d CPU, %s GB RAM, %s GB disk, %d snapshots",
                        details["vm_name"], details["cpu_count"] or 0,
                        details["memory_gb"] or "?", details["total_disk_gb"],
                        details["snapshot_count"])

    finally:
        Disconnect(si)

    # Write output
    with open(config.discovery_file, "w") as f:
        json.dump(discovery, f, indent=2, default=str)

    logger.info("-" * 60)
    logger.info("Discovery complete: %d found, %d missing", found, missing)
    logger.info("Output written to: %s", config.discovery_file)

    if missing > 0:
        logger.warning("Some servers were not found. Review discovery_output.json and fix servers.csv if needed.")
        logger.warning("You can still proceed — missing servers will use defaults from servers.csv.")

    return True
