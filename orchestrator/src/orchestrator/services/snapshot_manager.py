"""Snapshot tree management for baseline-compare mode.

Provides:
  - sync_tree: Sync hypervisor snapshot tree to DB, archive orphaned snapshots
  - take_snapshot: Create snapshot via hypervisor API and add to DB
  - delete_snapshot: Delete snapshot via hypervisor API and archive in DB
  - revert_snapshot: Revert VM to a snapshot via hypervisor API
  - is_descendant: Check if snapshot A is a descendant of snapshot B
"""

import logging
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.infra.hypervisor import HypervisorProvider, HypervisorSnapshot, create_hypervisor_provider
from orchestrator.models.orm import LabORM, ServerORM, SnapshotORM

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Manages the snapshot tree for servers in baseline-compare mode."""

    def __init__(self, credentials: CredentialsStore):
        self._credentials = credentials

    def _get_provider(self, lab: LabORM) -> HypervisorProvider:
        """Create a hypervisor provider for the given lab."""
        hyp_cred = self._credentials.get_hypervisor_credential(
            lab.hypervisor_type.value,
        )
        return create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

    def sync_tree(
        self, session: Session, server: ServerORM, lab: LabORM,
    ) -> List[SnapshotORM]:
        """Sync the hypervisor snapshot tree to the DB for a server.

        - New hypervisor snapshots get added to DB
        - Snapshots removed from hypervisor get marked is_archived=True
        - Existing snapshots are updated (parent linkage, name)
        - Stored profile data on archived snapshots is PRESERVED
        - Matching is by provider_snapshot_id (MoRef for vSphere, name for Proxmox,
          UUID for Vultr) — never by display name, which can be duplicated.

        Returns:
            List of all SnapshotORM records after sync
        """
        provider = self._get_provider(lab)
        hyp_snapshots = provider.list_snapshots(server.server_infra_ref)

        # Build provider_id -> hypervisor snapshot mapping
        # "id" is the unique provider identifier (MoRef ID, Proxmox name, Vultr UUID)
        hyp_by_pid: Dict[str, HypervisorSnapshot] = {s.id: s for s in hyp_snapshots}
        hyp_pids: Set[str] = set(hyp_by_pid.keys())

        # Get existing DB snapshots for this server
        db_snapshots = session.query(SnapshotORM).filter(
            SnapshotORM.server_id == server.id,
        ).all()
        db_by_pid: Dict[str, SnapshotORM] = {
            s.provider_snapshot_id: s for s in db_snapshots
            if s.provider_snapshot_id
        }

        # Archive snapshots no longer on hypervisor
        for snap in db_snapshots:
            if snap.provider_snapshot_id not in hyp_pids and not snap.is_archived:
                logger.info(
                    "Archiving snapshot '%s' (pid=%s, id=%d) — no longer on hypervisor",
                    snap.name, snap.provider_snapshot_id, snap.id,
                )
                snap.is_archived = True

        # Un-archive snapshots that reappeared on hypervisor
        for snap in db_snapshots:
            if snap.provider_snapshot_id in hyp_pids and snap.is_archived:
                logger.info(
                    "Un-archiving snapshot '%s' (pid=%s, id=%d) — found on hypervisor again",
                    snap.name, snap.provider_snapshot_id, snap.id,
                )
                snap.is_archived = False

        # Add new snapshots (present on hypervisor but not in DB)
        # Do two passes: first create all without parent_id, then set parent_id
        new_snapshots: Dict[str, SnapshotORM] = {}
        for pid, hyp_snap in hyp_by_pid.items():
            if pid not in db_by_pid:
                snap = SnapshotORM(
                    name=hyp_snap.name,
                    description=hyp_snap.description or "",
                    server_id=server.id,
                    provider_snapshot_id=pid,
                    provider_ref={
                        "snapshot_name": hyp_snap.name,
                        "snapshot_moref_id": pid,
                    },
                    is_baseline=False,
                    is_archived=False,
                )
                session.add(snap)
                new_snapshots[pid] = snap
                logger.info(
                    "Adding new snapshot '%s' (pid=%s) for server %s",
                    hyp_snap.name, pid, server.hostname,
                )

        session.flush()  # Get IDs for new snapshots

        # Merge DB lookups by provider ID
        all_by_pid: Dict[str, SnapshotORM] = {**db_by_pid, **new_snapshots}

        # Build the full tree as list of dicts (point-in-time capture for new snapshots)
        tree_snapshot = [hs.to_dict() for hs in hyp_snapshots]

        # Update parent linkage and metadata for all live snapshots
        for pid, hyp_snap in hyp_by_pid.items():
            snap = all_by_pid.get(pid)
            if not snap:
                continue
            # Update name if it changed on hypervisor
            snap.name = hyp_snap.name
            # Set parent by provider ID
            parent_pid = hyp_snap.parent
            if parent_pid and parent_pid in all_by_pid:
                snap.parent_id = all_by_pid[parent_pid].id
            else:
                snap.parent_id = None
            # Update provider_ref with full data
            snap.provider_ref = {
                "snapshot_name": hyp_snap.name,
                "snapshot_moref_id": pid,
            }
            # Capture snapshot tree only on first discovery (not every sync)
            if snap.snapshot_tree is None:
                snap.snapshot_tree = tree_snapshot

        session.commit()

        return session.query(SnapshotORM).filter(
            SnapshotORM.server_id == server.id,
        ).all()

    def take_snapshot(
        self,
        session: Session,
        server: ServerORM,
        lab: LabORM,
        name: str,
        description: str = "",
    ) -> SnapshotORM:
        """Create a new snapshot on the hypervisor and register in DB.

        The snapshot captures the VM's current state. Its parent is determined
        by the hypervisor (whatever snapshot is currently active).
        After creation, we sync the tree to pick up correct parentage.

        Returns the SnapshotORM for the newly created snapshot.
        """
        provider = self._get_provider(lab)
        result = provider.create_snapshot(
            server.server_infra_ref,
            snapshot_name=name,
            description=description,
        )
        # result contains {"snapshot_name": ..., "snapshot_moref_id": ...} for vSphere
        # or {"snapshot_name": ...} for Proxmox, {"snapshot_id": ..., "snapshot_name": ...} for Vultr
        provider_snapshot_id = (
            result.get("snapshot_moref_id")
            or result.get("snapshot_id")
            or result.get("snapshot_name")
        )
        logger.info(
            "Created snapshot '%s' (pid=%s) on hypervisor for %s",
            name, provider_snapshot_id, server.hostname,
        )

        # Sync to pick up the new snapshot with correct parent
        self.sync_tree(session, server, lab)

        # Find by provider_snapshot_id (unique, safe even with duplicate names)
        snap = session.query(SnapshotORM).filter(
            SnapshotORM.server_id == server.id,
            SnapshotORM.provider_snapshot_id == provider_snapshot_id,
        ).first()
        return snap

    def delete_snapshot(
        self,
        session: Session,
        server: ServerORM,
        lab: LabORM,
        snapshot: SnapshotORM,
    ) -> None:
        """Delete a snapshot from the hypervisor. Archives it in DB (data preserved)."""
        provider = self._get_provider(lab)
        provider.delete_snapshot(server.server_infra_ref, snapshot.provider_ref)
        snapshot.is_archived = True
        session.commit()
        logger.info(
            "Deleted snapshot '%s' from hypervisor, archived in DB (id=%d)",
            snapshot.name, snapshot.id,
        )

    def revert_snapshot(
        self,
        server: ServerORM,
        lab: LabORM,
        snapshot: SnapshotORM,
    ) -> Optional[str]:
        """Revert VM to a snapshot and wait for it to be ready.

        Returns:
            New IP address if changed (Vultr), else None
        """
        provider = self._get_provider(lab)
        new_ip = provider.restore_snapshot(
            server.server_infra_ref, snapshot.provider_ref,
        )
        provider.wait_for_vm_ready(server.server_infra_ref)
        return new_ip

    @staticmethod
    def is_descendant(
        session: Session,
        candidate_id: int,
        ancestor_id: int,
    ) -> bool:
        """Check if candidate snapshot is a descendant of ancestor snapshot.

        Walks up the parent chain from candidate. Returns True if ancestor
        is found in the chain.
        """
        visited: Set[int] = set()
        current_id = candidate_id

        while current_id is not None:
            if current_id == ancestor_id:
                return True
            if current_id in visited:
                return False  # Cycle protection
            visited.add(current_id)
            snap = session.get(SnapshotORM, current_id)
            if snap is None:
                return False
            current_id = snap.parent_id

        return False
