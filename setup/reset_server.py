#!/usr/bin/env python3
"""Reset servers: delete ALL snapshots, clean DB, prepare OS, take root snapshot.

This script is for initial setup / full reset. After running:
  - All hypervisor snapshots are deleted
  - All DB snapshot records are archived, groups/subgroups deleted
  - Server is prepared (sudo, firewall, java 17, /data disk)
  - Root snapshot is taken and set as root_snapshot_id + first group

Flow:
  1. Delete ALL snapshots from hypervisor for each server
  2. Clean DB records (archive snapshots, delete groups/subgroups)
  3. Wait for SSH
  4. Fix passwordless sudo
  5. Open firewall port 8080
  6. Install prerequisites (Java 17, Python3)
  7. Setup data disk (/dev/sdc -> /data, output folders, chown)
  8. Take root snapshot, create DB records (SnapshotORM + Group + root_snapshot_id)

Usage:
    python reset_server.py --all --sudo-user svc_account
    python reset_server.py --hostname srv-rocky1,srv-rocky2 --sudo-user svc_account
    python reset_server.py --all --sudo-user svc_account --group-name "Jan2026 Patches"
    python reset_server.py --all --sudo-user svc_account --dry-run
    python reset_server.py --hostname srv-rocky1 --sudo-user svc_account --skip-prepare
"""

import argparse
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)

# Reuse all helper functions from retake_snapshots
from retake_snapshots import (
    fix_sudo,
    open_firewall,
    install_prerequisites,
    setup_data_disk,
    FIREWALL_PORT,
)


def delete_all_snapshots(provider, server, dry_run=False):
    """Delete ALL snapshots from hypervisor for a server.

    Deletes leaf nodes first (bottom-up) so each delete is a simple
    removal, not a merge into parent.
    """
    all_snaps = provider.list_snapshots(server.server_infra_ref)
    if not all_snaps:
        print("    No snapshots on hypervisor — nothing to delete")
        return True

    print(f"    Found {len(all_snaps)} snapshots on hypervisor")

    # Build parent -> children map
    children_of = {}
    for s in all_snaps:
        parent = s.parent if s.parent else None
        children_of.setdefault(parent, []).append(s)

    # Delete leaves first (bottom-up)
    ordered = []
    remaining = {s.id for s in all_snaps}
    snap_by_id = {s.id: s for s in all_snaps}

    max_iterations = len(all_snaps) + 1
    for _ in range(max_iterations):
        if not remaining:
            break
        leaves = []
        for sid in remaining:
            snap_children = [c for c in children_of.get(sid, []) if c.id in remaining]
            if not snap_children:
                leaves.append(sid)
        if not leaves:
            print(f"    [WARN] Could not determine leaf order for {len(remaining)} remaining — deleting in arbitrary order")
            ordered.extend(remaining)
            break
        ordered.extend(leaves)
        remaining -= set(leaves)

    all_ok = True
    for snap_id in ordered:
        snap = snap_by_id.get(snap_id)
        if not snap:
            continue
        if dry_run:
            print(f"    [DRY RUN] Would delete: {snap.name} (id={snap.id})")
            continue
        try:
            print(f"    Deleting: {snap.name} (id={snap.id})...")
            provider_ref = _build_provider_ref(snap, server)
            provider.delete_snapshot(server.server_infra_ref, provider_ref)
            print(f"      [OK] Deleted")
            time.sleep(1)  # Brief pause between deletes
        except Exception as e:
            print(f"      [WARN] Failed: {e}")
            all_ok = False

    return all_ok


def _build_provider_ref(hypervisor_snap, server):
    """Build provider_ref dict from a HypervisorSnapshot for deletion."""
    infra_type = server.server_infra_type.value
    if infra_type == "vsphere_vm":
        return {
            "snapshot_name": hypervisor_snap.name,
            "snapshot_moref_id": hypervisor_snap.id,
        }
    elif infra_type == "proxmox_vm":
        return {"snapshot_name": hypervisor_snap.id}
    elif infra_type == "vultr_instance":
        return {"snapshot_id": hypervisor_snap.id, "snapshot_name": hypervisor_snap.name}
    else:
        return {"snapshot_name": hypervisor_snap.name}


def clean_db_records(session, server):
    """Archive all DB snapshot records and delete groups/subgroups for this server."""
    from orchestrator.models.orm import SnapshotORM, SnapshotBaselineORM

    # Archive all snapshots
    snaps = session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server.id,
        SnapshotORM.is_archived == False,
    ).all()
    for s in snaps:
        s.is_archived = True
        s.group_id = None

    # Delete all groups (cascade deletes subgroups)
    groups = session.query(SnapshotBaselineORM).filter(
        SnapshotBaselineORM.server_id == server.id,
    ).all()
    for g in groups:
        session.delete(g)

    # Clear root_snapshot_id and clean_snapshot_id
    server.root_snapshot_id = None
    server.clean_snapshot_id = None

    session.commit()
    print(f"    [DB] {len(snaps)} snapshots archived, {len(groups)} groups deleted, root/clean snapshot refs cleared")


def take_root_snapshot_and_create_group(provider, server, session, group_name):
    """Take snapshot on hypervisor and create DB records:
    SnapshotORM + SnapshotBaselineORM (group) + set server.root_snapshot_id.
    """
    from datetime import datetime
    from orchestrator.models.orm import SnapshotORM, SnapshotBaselineORM, SnapshotGroupORM

    snap_name = f"root-{server.hostname}"
    description = f"Root snapshot — clean OS prepared ({datetime.utcnow().strftime('%Y-%m-%d')})"

    # Take snapshot on hypervisor
    print(f"    Taking snapshot '{snap_name}' on hypervisor...")
    result = provider.create_snapshot(
        server.server_infra_ref,
        snapshot_name=snap_name,
        description=description,
    )
    new_provider_id = (
        result.get("snapshot_moref_id")
        or result.get("snapshot_id")
        or result.get("snapshot_name")
    )
    print(f"    [OK] Created: provider_id={new_provider_id}")

    # Get snapshot tree
    snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]

    # Create SnapshotORM
    snap_orm = SnapshotORM(
        name=snap_name,
        description=description,
        server_id=server.id,
        parent_id=None,
        group_id=None,
        provider_snapshot_id=str(new_provider_id),
        provider_ref=result,
        snapshot_tree=snapshot_tree,
        is_baseline=True,
        is_archived=False,
    )
    session.add(snap_orm)
    session.flush()
    print(f"    [DB] Snapshot record created: ID={snap_orm.id}")

    # Set as root_snapshot_id on server
    server.root_snapshot_id = snap_orm.id
    # Also set as clean_snapshot_id (loadgens use this)
    server.clean_snapshot_id = snap_orm.id
    print(f"    [DB] Set root_snapshot_id={snap_orm.id}, clean_snapshot_id={snap_orm.id}")

    # Create group (SnapshotBaselineORM)
    group_orm = SnapshotBaselineORM(
        server_id=server.id,
        snapshot_id=snap_orm.id,
        name=group_name,
        description=description,
    )
    session.add(group_orm)
    session.flush()
    print(f"    [DB] Group created: '{group_name}' (ID={group_orm.id})")

    # Create default subgroup
    default_sg = SnapshotGroupORM(
        baseline_id=group_orm.id,
        snapshot_id=snap_orm.id,
        name="Default",
        description="Auto-created default subgroup",
    )
    session.add(default_sg)

    # Link snapshot to default subgroup
    snap_orm.group_id = default_sg.id

    session.commit()
    print(f"    [DB] Default subgroup created, snapshot linked")

    return snap_orm, group_orm


def reset_one_server(
    *,
    server,
    provider,
    credentials,
    session,
    sudo_user,
    group_name,
    dry_run=False,
    skip_prepare=False,
    wait_for_ssh_fn=None,
):
    """Reset a single server."""
    os_family = server.os_family.value
    hostname = server.hostname
    ip = server.ip_address
    TOTAL = 8

    print(f"\n{'='*60}")
    print(f"  Server: {hostname} ({ip}) [role={server.role.value}]")
    print(f"  OS: {os_family}")
    print(f"{'='*60}")

    # --- Step 1: Delete all snapshots from hypervisor ---
    print(f"\n  [1/{TOTAL}] Deleting ALL snapshots from hypervisor...")
    try:
        if not delete_all_snapshots(provider, server, dry_run):
            print(f"    [WARN] Some deletions failed — continuing")
    except Exception as e:
        print(f"    [ERROR] {e}")
        return False

    # --- Step 2: Clean DB records ---
    print(f"\n  [2/{TOTAL}] Cleaning DB records...")
    if not dry_run:
        clean_db_records(session, server)
    else:
        print(f"    [DRY RUN] Would archive all snapshots and delete groups")

    if skip_prepare:
        print(f"\n  [DONE] Snapshots cleaned. Skipping preparation (--skip-prepare)")
        return True

    # --- Step 3: Wait for SSH ---
    print(f"\n  [3/{TOTAL}] Waiting for SSH on {ip}...")
    if not dry_run:
        try:
            wait_for_ssh_fn(ip, os_family=os_family, timeout_sec=120)
            print(f"    [OK] Connected")
        except Exception as e:
            print(f"  [ERROR] SSH failed: {e}")
            return False
    else:
        print(f"    [DRY RUN] Would wait for SSH")

    if dry_run:
        print(f"\n  [4/{TOTAL}] [DRY RUN] Would fix passwordless sudo for '{sudo_user}'")
        print(f"  [5/{TOTAL}] [DRY RUN] Would open firewall port {FIREWALL_PORT}")
        print(f"  [6/{TOTAL}] [DRY RUN] Would install prerequisites (Java 17)")
        print(f"  [7/{TOTAL}] [DRY RUN] Would setup data disk /dev/sdc -> /data")
        print(f"  [8/{TOTAL}] [DRY RUN] Would take root snapshot and create group '{group_name}'")
        print(f"\n  [DONE] Dry run complete")
        return True

    cred = credentials.get_server_credential(server.id, os_family)
    from orchestrator.infra.remote_executor import create_executor
    executor = create_executor(
        os_family=os_family,
        host=ip,
        username=cred.username,
        password=cred.password,
    )

    try:
        # --- Step 4: Fix sudo ---
        print(f"\n  [4/{TOTAL}] Fixing passwordless sudo for '{sudo_user}'...")
        if not fix_sudo(executor, cred.password, sudo_user, os_family):
            print(f"  [ERROR] Sudo fix failed")
            return False

        # --- Step 5: Open firewall ---
        print(f"\n  [5/{TOTAL}] Opening firewall port {FIREWALL_PORT}...")
        open_firewall(executor, os_family, FIREWALL_PORT)

        # --- Step 6: Install prerequisites ---
        print(f"\n  [6/{TOTAL}] Installing prerequisites (Java 17)...")
        if not install_prerequisites(executor, os_family):
            print(f"  [WARN] Some prerequisites may have failed — continuing")

        # --- Step 7: Setup data disk ---
        print(f"\n  [7/{TOTAL}] Setting up data disk...")
        if not setup_data_disk(executor, os_family, cred.username):
            print(f"  [ERROR] Data disk setup failed")
            return False

    finally:
        executor.close()

    # --- Step 8: Take root snapshot and create group ---
    print(f"\n  [8/{TOTAL}] Taking root snapshot and creating group '{group_name}'...")
    try:
        snap, group = take_root_snapshot_and_create_group(
            provider, server, session, group_name,
        )
        print(f"    [OK] Root snapshot: '{snap.name}' (ID={snap.id})")
        print(f"    [OK] Group: '{group.name}' (ID={group.id})")
    except Exception as e:
        print(f"  [ERROR] Failed to take snapshot: {e}")
        import traceback
        traceback.print_exc()
        return False

    print(f"\n  {'='*60}")
    print(f"  [DONE] {hostname} — reset, prepared, root snapshot taken")
    print(f"  {'='*60}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Reset target servers: delete all snapshots, clean DB, prepare OS",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hostname", default=None,
                       help="Comma-separated hostnames to reset")
    group.add_argument("--all", action="store_true",
                       help="Reset ALL servers (targets and loadgens)")
    parser.add_argument("--sudo-user", required=True,
                        help="Username to configure passwordless sudo for")
    parser.add_argument("--group-name", default=None,
                        help="Name for the root group (default: 'Clean OS <hostname>')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--skip-prepare", action="store_true",
                        help="Only delete snapshots and clean DB — skip SSH/sudo/java/disk/snapshot")

    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import ServerORM
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider
    from orchestrator.core.baseline_execution import wait_for_ssh

    # Initialize DB
    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()

    # Find servers
    if args.all:
        servers = session.query(ServerORM).all()
        if not servers:
            print("No servers found in database")
            sys.exit(1)
        print(f"Found {len(servers)} servers")
    else:
        hostnames = {h.strip().lower() for h in args.hostname.split(",")}
        servers = session.query(ServerORM).all()
        servers = [s for s in servers if s.hostname.lower() in hostnames]
        if not servers:
            print(f"No servers found matching: {args.hostname}")
            sys.exit(1)
        missing = hostnames - {s.hostname.lower() for s in servers}
        if missing:
            print(f"[WARN] Not found: {', '.join(missing)}")

    # Get hypervisor provider
    from orchestrator.models.orm import LabORM
    lab = session.get(LabORM, servers[0].lab_id)
    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    print(f"\nLab: {lab.name} ({lab.hypervisor_type.value})")
    for s in servers:
        print(f"  - {s.hostname} ({s.ip_address}) [role={s.role.value}]")
    if not args.dry_run:
        print(f"\n*** WARNING: This will DELETE ALL snapshots from the hypervisor ***")
        confirm = input("Type 'yes' to continue: ")
        if confirm.strip().lower() != 'yes':
            print("Aborted.")
            sys.exit(0)

    # Process each server
    success = 0
    failed = 0
    for server in servers:
        try:
            gname = args.group_name or f"Clean OS {server.hostname}"
            ok = reset_one_server(
                server=server,
                provider=provider,
                credentials=credentials,
                session=session,
                sudo_user=args.sudo_user,
                group_name=gname,
                dry_run=args.dry_run,
                skip_prepare=args.skip_prepare,
                wait_for_ssh_fn=wait_for_ssh,
            )
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n  [ERROR] {server.hostname}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            try:
                session.rollback()
            except Exception:
                pass

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {success} ok, {failed} failed")
    print(f"{'='*60}")

    session.close()
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
