"""Credentials JSON loader.

Matches ORCHESTRATOR_DATABASE_SCHEMA.md Section 5 exactly.
Lookup cascade for server credentials (D19):
  1. Try servers.by_server_id[server.id]
  2. Fall back to servers.by_os_type[server.os_family]
Hypervisor credentials: keyed by hypervisor_type value.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ServerCredential:
    username: str
    password: str


@dataclass
class ProxmoxCredential:
    api_key: str
    verify_ssl: bool = False


@dataclass
class VSphereCredential:
    username: str
    password: str
    verify_ssl: bool = False


class CredentialsStore:
    """Loads and provides access to the credentials JSON file."""

    def __init__(self, credentials_path: str):
        self._path = Path(credentials_path)
        self._data: dict = {}
        self.reload()

    def reload(self):
        """Reload credentials from disk."""
        if self._path.exists():
            with open(self._path, "r") as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def get_server_credential(self, server_id: int, os_family: str) -> Optional[ServerCredential]:
        """Lookup server credential with cascade: by_server_id then by_os_type."""
        servers = self._data.get("servers", {})

        # Step 1: Try by_server_id
        by_id = servers.get("by_server_id", {})
        entry = by_id.get(str(server_id))
        if entry:
            return ServerCredential(username=entry["username"], password=entry["password"])

        # Step 2: Fall back to by_os_type
        by_os = servers.get("by_os_type", {})
        entry = by_os.get(os_family)
        if entry:
            return ServerCredential(username=entry["username"], password=entry["password"])

        return None

    def get_proxmox_credential(self) -> Optional[ProxmoxCredential]:
        """Get Proxmox hypervisor credentials."""
        entry = self._data.get("proxmox")
        if not entry:
            return None
        return ProxmoxCredential(
            api_key=entry["api_key"],
            verify_ssl=entry.get("verify_ssl", False),
        )

    def get_vsphere_credential(self) -> Optional[VSphereCredential]:
        """Get vSphere hypervisor credentials."""
        entry = self._data.get("vsphere")
        if not entry:
            return None
        return VSphereCredential(
            username=entry["username"],
            password=entry["password"],
            verify_ssl=entry.get("verify_ssl", False),
        )

    def get_hypervisor_credential(self, hypervisor_type: str):
        """Get hypervisor credential by type string ('proxmox' or 'vsphere')."""
        if hypervisor_type == "proxmox":
            return self.get_proxmox_credential()
        elif hypervisor_type == "vsphere":
            return self.get_vsphere_credential()
        return None

    @property
    def raw_data(self) -> dict:
        """Access raw credentials dict (for admin display with masked passwords)."""
        return self._data

    def save(self):
        """Write current credentials back to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)
