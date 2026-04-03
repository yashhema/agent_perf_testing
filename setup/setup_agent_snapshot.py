#!/usr/bin/env python3
"""Helper script for end users to set up agent snapshots.

Two modes:
  --revert   Revert server to OS Level (root snapshot) or a specific snapshot
  --snapshot Take snapshot after agents are installed

Workflow:
  1. python setup_agent_snapshot.py --revert --hostname srv-rocky1
     → Reverts to OS Level. SSH into server and install agents.
  2. python setup_agent_snapshot.py --snapshot --hostname srv-rocky1 --name "CS+Tanium-v1"
     → Takes snapshot of current state.

For multi-agent setups (building on CS+Tanium base):
  1. python setup_agent_snapshot.py --revert --hostname srv-rocky1
  2. Install CrowdStrike + Tanium on the server
  3. python setup_agent_snapshot.py --snapshot --hostname srv-rocky1 --name "CS+Tanium-base"
  4. (Later, for adding PkWare on top:)
  5. python setup_agent_snapshot.py --revert --hostname srv-rocky1 --snapshot-name "CS+Tanium-base"
  6. Install PkWare on the server
  7. python setup_agent_snapshot.py --snapshot --hostname srv-rocky1 --name "CS+Tanium+PkWare"

Usage:
    python setup_agent_snapshot.py --revert --hostname srv-rocky1
    python setup_agent_snapshot.py --revert --hostname srv-rocky1 --snapshot-name "CS+Tanium-base"
    python setup_agent_snapshot.py --snapshot --hostname srv-rocky1 --name "CrowdStrike-v7.19"
    python setup_agent_snapshot.py --list --hostname srv-rocky1
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def get_provider_and_server(session, hostname):
    from orchestrator.models.orm import LabORM, ServerORM
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider

    server = session.query(ServerORM).filter(ServerORM.hostname == hostname).first()
    if not server:
        print(f"ERROR: Server '{hostname}' not found in database")
        sys.exit(1)

    lab = session.get(LabORM, server.lab_id)
    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    cred_path = os.path.join(os.path.dirname(config_path), "credentials.json")
    credentials = CredentialsStore(cred_path)

    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    return provider, server, lab, credentials


def do_list(session, hostname):
    """List all snapshots for a server."""
    from orchestrator.models.orm import SnapshotORM
    provider, server, lab, _ = get_provider_and_server(session, hostname)

    print(f"\nServer: {server.hostname} ({server.ip_address})")
    print(f"OS: {server.os_vendor_family} {server.os_major_ver}")
    print(f"Root snapshot ID: {server.root_snapshot_id or 'not set'}")

    # DB snapshots
    db_snaps = session.query(SnapshotORM).filter(
        SnapshotORM.server_id == server.id,
        SnapshotORM.is_archived == False,
    ).order_by(SnapshotORM.created_at.desc()).all()

    print(f"\nDB Snapshots ({len(db_snaps)}):")
    for s in db_snaps:
        root_marker = " [ROOT]" if s.id == server.root_snapshot_id else ""
        print(f"  ID={s.id} | {s.name} | provider={s.provider_snapshot_id}{root_marker}")

    # Hypervisor snapshots
    print(f"\nHypervisor Snapshots:")
    try:
        hyp_snaps = provider.list_snapshots(server.server_infra_ref)
        for s in hyp_snaps:
            print(f"  {s.name} (id={s.id}, parent={s.parent or 'root'})")
    except Exception as e:
        print(f"  ERROR: {e}")


def do_revert(session, hostname, snapshot_name=None):
    """Revert server to OS Level or a named snapshot."""
    from orchestrator.models.orm import SnapshotORM
    from orchestrator.core.baseline_execution import wait_for_ssh

    provider, server, lab, credentials = get_provider_and_server(session, hostname)

    if snapshot_name:
        # Find named snapshot
        snap = session.query(SnapshotORM).filter(
            SnapshotORM.server_id == server.id,
            SnapshotORM.name == snapshot_name,
            SnapshotORM.is_archived == False,
        ).first()
        if not snap:
            print(f"ERROR: Snapshot '{snapshot_name}' not found for {hostname}")
            print("Available snapshots:")
            do_list(session, hostname)
            sys.exit(1)
        snap_ref = snap.provider_ref
        print(f"Reverting to snapshot: {snap.name} (ID={snap.id})")
    else:
        # Revert to root
        if not server.root_snapshot_id:
            print(f"ERROR: No root snapshot set for {hostname}. Run Prepare & Snapshot first.")
            sys.exit(1)
        snap = session.get(SnapshotORM, server.root_snapshot_id)
        if not snap:
            print(f"ERROR: Root snapshot record not found (ID={server.root_snapshot_id})")
            sys.exit(1)
        snap_ref = snap.provider_ref
        print(f"Reverting to OS Level (root): {snap.name} (ID={snap.id})")

    # Revert
    print("Reverting snapshot...")
    new_ip = provider.restore_snapshot(server.server_infra_ref, snap_ref)
    print("Waiting for VM to be ready...")
    provider.wait_for_vm_ready(server.server_infra_ref, timeout_sec=300)

    actual_ip = server.ip_address
    if new_ip and new_ip != server.ip_address:
        actual_ip = new_ip
        server.ip_address = new_ip
        session.commit()
        print(f"IP changed: {actual_ip}")

    print("Waiting for SSH...")
    wait_for_ssh(actual_ip, os_family=server.os_family.value, timeout_sec=180)

    print(f"\n{'='*60}")
    print(f"Server reverted successfully!")
    print(f"")
    print(f"  SSH: ssh user@{actual_ip}")
    print(f"")
    print(f"  Install your agents now, then run:")
    print(f"  python setup_agent_snapshot.py --snapshot --hostname {hostname} --name \"YourSnapshotName\"")
    print(f"{'='*60}")


def do_snapshot(session, hostname, name, description=None):
    """Take a snapshot of the current server state."""
    from orchestrator.models.orm import SnapshotORM
    from orchestrator.services.snapshot_manager import SnapshotManager

    provider, server, lab, credentials = get_provider_and_server(session, hostname)

    print(f"Taking snapshot '{name}' on {hostname}...")
    mgr = SnapshotManager(credentials)
    snap = mgr.take_snapshot(
        session, server, lab,
        name=name,
        description=description or f"Agent snapshot for {hostname}",
    )
    if not snap:
        print("ERROR: Failed to take snapshot")
        sys.exit(1)

    # Capture snapshot tree
    snap.snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
    session.commit()

    print(f"\n{'='*60}")
    print(f"Snapshot taken successfully!")
    print(f"  Name: {snap.name}")
    print(f"  DB ID: {snap.id}")
    print(f"  Provider ID: {snap.provider_snapshot_id}")
    print(f"")
    print(f"  Use this snapshot in the Orchestrator UI when creating an Agent Set Test.")
    print(f"  Select it from the snapshot dropdown for {hostname}.")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Helper script for setting up agent snapshots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Revert to OS Level (clean OS):
    python setup_agent_snapshot.py --revert --hostname srv-rocky1

  Revert to a specific snapshot (e.g., CS+Tanium base):
    python setup_agent_snapshot.py --revert --hostname srv-rocky1 --snapshot-name "CS+Tanium-base"

  Take snapshot after installing agents:
    python setup_agent_snapshot.py --snapshot --hostname srv-rocky1 --name "CS+Tanium-v1"

  List all snapshots for a server:
    python setup_agent_snapshot.py --list --hostname srv-rocky1
""",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--revert", action="store_true", help="Revert server to OS Level or named snapshot")
    action.add_argument("--snapshot", action="store_true", help="Take snapshot of current state")
    action.add_argument("--list", action="store_true", help="List all snapshots for the server")

    parser.add_argument("--hostname", required=True, help="Server hostname")
    parser.add_argument("--snapshot-name", default=None, help="(revert) Specific snapshot to revert to (default: OS Level)")
    parser.add_argument("--name", default=None, help="(snapshot) Name for the new snapshot")
    parser.add_argument("--description", default=None, help="(snapshot) Description")

    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.config.settings import load_config

    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)
    session = SessionLocal()

    try:
        if args.list:
            do_list(session, args.hostname)
        elif args.revert:
            do_revert(session, args.hostname, args.snapshot_name)
        elif args.snapshot:
            if not args.name:
                print("ERROR: --name is required when taking a snapshot")
                sys.exit(1)
            do_snapshot(session, args.hostname, args.name, args.description)
    finally:
        session.close()


if __name__ == "__main__":
    main()
