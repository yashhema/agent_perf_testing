#!/usr/bin/env python3
"""Manage VM snapshots and sync them to the orchestrator DB.

Commands:
    python manage_snapshots.py list <hostname>                     # List vSphere snapshots for a server
    python manage_snapshots.py list-all                            # List vSphere snapshots for all servers
    python manage_snapshots.py create <hostname> <snapshot_name>   # Create snapshot in vSphere + register in DB
    python manage_snapshots.py delete <hostname> <snapshot_name>   # Delete snapshot from vSphere + DB
    python manage_snapshots.py sync <hostname>                     # Sync all vSphere snapshots to DB for a server
    python manage_snapshots.py sync-all                            # Sync all vSphere snapshots to DB for all servers
    python manage_snapshots.py db-list                             # Show all snapshots in DB

Also seeds default scenarios if they don't exist.

Reads setup_config.yaml for vSphere + DB connection details.
"""

import argparse
import json
import logging
import os
import ssl
import sys

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SETUP_DIR)

from tasks.common import (
    load_config, load_servers, load_credentials, SetupConfig,
)

logger = logging.getLogger("snapshots")

CONFIG_FILE = os.path.join(SETUP_DIR, "setup_config.yaml")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db_session(config: SetupConfig):
    src_path = os.path.join(config.repo_path, "orchestrator", "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    db_url = (f"postgresql://{config.postgres_user}:{config.postgres_password}"
              f"@{config.postgres_host}:{config.postgres_port}/{config.postgres_db}")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _get_server_by_hostname(session, hostname: str):
    from orchestrator.models.orm import ServerORM
    srv = session.query(ServerORM).filter_by(hostname=hostname).first()
    if not srv:
        # Try case-insensitive
        all_servers = session.query(ServerORM).all()
        for s in all_servers:
            if s.hostname.lower() == hostname.lower():
                return s
        available = [s.hostname for s in all_servers]
        print(f"Server '{hostname}' not found in DB. Available: {', '.join(available)}")
        sys.exit(1)
    return srv


# ---------------------------------------------------------------------------
# vSphere connection
# ---------------------------------------------------------------------------

def _connect_vsphere(config: SetupConfig, creds):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    si = SmartConnect(
        host=config.vsphere_host,
        user=creds.vsphere_user,
        pwd=creds.vsphere_pass,
        port=config.vsphere_port,
        sslContext=context,
    )
    return si


def _find_vm(content, hostname: str, ip: str = None):
    """Find VM by hostname or IP in vSphere."""
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    try:
        for vm in container.view:
            if vm.name and vm.name.lower() == hostname.lower():
                return vm
            if vm.guest and vm.guest.hostName:
                if vm.guest.hostName.lower() == hostname.lower():
                    return vm
            if ip and vm.guest and vm.guest.net:
                for nic in vm.guest.net:
                    if nic.ipAddress and ip in nic.ipAddress:
                        return vm
    finally:
        container.Destroy()
    return None


def _get_snapshot_list(snapshot_tree, parent_path=""):
    """Recursively collect snapshots from VM snapshot tree."""
    snapshots = []
    if not snapshot_tree:
        return snapshots
    for snap in snapshot_tree:
        path = f"{parent_path}/{snap.name}" if parent_path else snap.name
        snapshots.append({
            "name": snap.name,
            "path": path,
            "id": snap.id,
            "description": snap.description or "",
            "create_time": str(snap.createTime),
            "state": str(snap.state),
            "moref": str(snap.snapshot._moId),
            "snapshot_obj": snap.snapshot,
        })
        if snap.childSnapshotList:
            snapshots.extend(_get_snapshot_list(snap.childSnapshotList, path))
    return snapshots


def _find_snapshot_by_name(vm, name: str):
    """Find a specific snapshot by name in the VM's snapshot tree."""
    if not vm.snapshot:
        return None
    snaps = _get_snapshot_list(vm.snapshot.rootSnapshotList)
    for s in snaps:
        if s["name"] == name:
            return s
    return None


def _wait_for_task(task, action=""):
    """Wait for a vSphere task to complete."""
    while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
        import time
        time.sleep(2)
    if task.info.state == vim.TaskInfo.State.success:
        print(f"  vSphere {action} completed successfully")
        return True
    else:
        print(f"  vSphere {action} failed: {task.info.error}")
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(config, hostname):
    """List vSphere snapshots for a server."""
    creds = load_credentials(config.credentials_file)
    servers = load_servers(config.servers_file)
    server = next((s for s in servers if s.hostname.lower() == hostname.lower()), None)
    if not server:
        print(f"Server '{hostname}' not in servers.csv")
        sys.exit(1)

    si = _connect_vsphere(config, creds)
    try:
        content = si.RetrieveContent()
        vm = _find_vm(content, server.hostname, server.ip)
        if not vm:
            print(f"VM not found in vSphere for {server.hostname}")
            return

        if not vm.snapshot:
            print(f"No snapshots for {server.hostname}")
            return

        snaps = _get_snapshot_list(vm.snapshot.rootSnapshotList)
        print(f"\nSnapshots for {server.hostname} ({vm.name}):")
        print(f"{'Name':30s} {'ID':6s} {'Created':25s} {'Description'}")
        print("-" * 90)
        for s in snaps:
            print(f"{s['name']:30s} {s['id']:<6d} {s['create_time'][:25]:25s} {s['description'][:30]}")
    finally:
        Disconnect(si)


def cmd_list_all(config):
    """List vSphere snapshots for all servers."""
    servers = load_servers(config.servers_file)
    for server in servers:
        cmd_list(config, server.hostname)
        print()


def cmd_create(config, hostname, snapshot_name, description=""):
    """Create a VM snapshot in vSphere and register it in DB."""
    creds = load_credentials(config.credentials_file)
    servers = load_servers(config.servers_file)
    server = next((s for s in servers if s.hostname.lower() == hostname.lower()), None)
    if not server:
        print(f"Server '{hostname}' not in servers.csv")
        sys.exit(1)

    # Create in vSphere
    si = _connect_vsphere(config, creds)
    try:
        content = si.RetrieveContent()
        vm = _find_vm(content, server.hostname, server.ip)
        if not vm:
            print(f"VM not found in vSphere for {server.hostname}")
            sys.exit(1)

        print(f"Creating snapshot '{snapshot_name}' on {server.hostname} ...")
        task = vm.CreateSnapshot_Task(
            name=snapshot_name,
            description=description or f"Created by setup tool",
            memory=False,
            quiesce=True,
        )
        if not _wait_for_task(task, "create snapshot"):
            sys.exit(1)

        # Get the snapshot details
        snap = _find_snapshot_by_name(vm, snapshot_name)
        if not snap:
            print("  Warning: snapshot created but couldn't find it in tree")
            snap = {"moref": "unknown", "id": 0}

    finally:
        Disconnect(si)

    # Register in DB
    _register_snapshot_in_db(config, server.hostname, snapshot_name, snap, description)


def cmd_delete(config, hostname, snapshot_name):
    """Delete a VM snapshot from vSphere and DB."""
    creds = load_credentials(config.credentials_file)
    servers = load_servers(config.servers_file)
    server = next((s for s in servers if s.hostname.lower() == hostname.lower()), None)
    if not server:
        print(f"Server '{hostname}' not in servers.csv")
        sys.exit(1)

    # Delete from vSphere
    si = _connect_vsphere(config, creds)
    try:
        content = si.RetrieveContent()
        vm = _find_vm(content, server.hostname, server.ip)
        if not vm:
            print(f"VM not found in vSphere for {server.hostname}")
            sys.exit(1)

        snap = _find_snapshot_by_name(vm, snapshot_name)
        if not snap:
            print(f"Snapshot '{snapshot_name}' not found on {server.hostname}")
            # Still try to remove from DB
        else:
            print(f"Deleting snapshot '{snapshot_name}' from {server.hostname} ...")
            task = snap["snapshot_obj"].RemoveSnapshot_Task(removeChildren=False)
            _wait_for_task(task, "delete snapshot")

    finally:
        Disconnect(si)

    # Remove from DB
    _remove_snapshot_from_db(config, server.hostname, snapshot_name)


def cmd_sync(config, hostname):
    """Sync all vSphere snapshots to DB for a server."""
    creds = load_credentials(config.credentials_file)
    servers = load_servers(config.servers_file)
    server = next((s for s in servers if s.hostname.lower() == hostname.lower()), None)
    if not server:
        print(f"Server '{hostname}' not in servers.csv")
        sys.exit(1)

    si = _connect_vsphere(config, creds)
    try:
        content = si.RetrieveContent()
        vm = _find_vm(content, server.hostname, server.ip)
        if not vm:
            print(f"VM not found in vSphere for {server.hostname}")
            return

        if not vm.snapshot:
            print(f"No snapshots for {server.hostname}")
            return

        snaps = _get_snapshot_list(vm.snapshot.rootSnapshotList)
        print(f"Syncing {len(snaps)} snapshots for {server.hostname} ...")

        for snap in snaps:
            _register_snapshot_in_db(config, server.hostname, snap["name"], snap,
                                     snap.get("description", ""))

    finally:
        Disconnect(si)


def cmd_sync_all(config):
    """Sync all vSphere snapshots to DB for all servers."""
    servers = load_servers(config.servers_file)
    for server in servers:
        cmd_sync(config, server.hostname)


def cmd_db_list(config):
    """Show all snapshots in DB."""
    session, engine = _get_db_session(config)
    try:
        from orchestrator.models.orm import SnapshotORM, ServerORM
        snaps = (
            session.query(SnapshotORM, ServerORM.hostname)
            .join(ServerORM, SnapshotORM.server_id == ServerORM.id)
            .order_by(ServerORM.hostname, SnapshotORM.name)
            .all()
        )

        if not snaps:
            print("No snapshots in DB")
            return

        print(f"\n{'Server':25s} {'Snapshot':25s} {'ID':5s} {'Provider ID':15s} {'Baseline':8s} {'Created'}")
        print("-" * 110)
        for snap, hostname in snaps:
            print(f"{hostname:25s} {snap.name:25s} {snap.id:<5d} {snap.provider_snapshot_id:15s} "
                  f"{'Yes' if snap.is_baseline else 'No':8s} {str(snap.created_at)[:19]}")

    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def _register_snapshot_in_db(config, hostname, snapshot_name, snap_info, description=""):
    """Register or update a snapshot in the DB."""
    session, engine = _get_db_session(config)
    try:
        from orchestrator.models.orm import SnapshotORM
        srv = _get_server_by_hostname(session, hostname)

        provider_id = str(snap_info.get("moref", snap_info.get("id", "unknown")))

        existing = (
            session.query(SnapshotORM)
            .filter_by(server_id=srv.id, name=snapshot_name)
            .first()
        )

        if existing:
            existing.provider_snapshot_id = provider_id
            existing.provider_ref = {
                "moref": snap_info.get("moref", ""),
                "vsphere_id": snap_info.get("id", 0),
                "create_time": snap_info.get("create_time", ""),
            }
            session.commit()
            print(f"  DB updated: {hostname}/{snapshot_name} (id={existing.id})")
        else:
            new_snap = SnapshotORM(
                name=snapshot_name,
                description=description,
                server_id=srv.id,
                provider_snapshot_id=provider_id,
                provider_ref={
                    "moref": snap_info.get("moref", ""),
                    "vsphere_id": snap_info.get("id", 0),
                    "create_time": snap_info.get("create_time", ""),
                },
                is_baseline=True,
            )
            session.add(new_snap)
            session.commit()
            print(f"  DB registered: {hostname}/{snapshot_name} (id={new_snap.id})")

    finally:
        session.close()
        engine.dispose()


def _remove_snapshot_from_db(config, hostname, snapshot_name):
    """Remove a snapshot from the DB."""
    session, engine = _get_db_session(config)
    try:
        from orchestrator.models.orm import SnapshotORM
        srv = _get_server_by_hostname(session, hostname)

        snap = (
            session.query(SnapshotORM)
            .filter_by(server_id=srv.id, name=snapshot_name)
            .first()
        )
        if snap:
            session.delete(snap)
            session.commit()
            print(f"  DB removed: {hostname}/{snapshot_name} (id={snap.id})")
        else:
            print(f"  Not in DB: {hostname}/{snapshot_name}")

    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Scenario seeding
# ---------------------------------------------------------------------------

def ensure_scenarios(config):
    """Create default scenarios if they don't exist."""
    session, engine = _get_db_session(config)
    try:
        from orchestrator.models.orm import ScenarioORM, LabORM, PackageGroupORM
        from orchestrator.models.enums import TemplateType

        lab = session.query(LabORM).filter_by(name=config.lab_name).first()
        if not lab:
            print(f"Lab '{config.lab_name}' not found — run task3 first")
            return

        jmeter_pg = session.query(PackageGroupORM).filter_by(name="jmeter-default").first()
        if not jmeter_pg:
            print("Package group 'jmeter-default' not found — run task3 first")
            return

        templates = [
            ("Baseline Steady", TemplateType.server_steady, "Steady CPU load via /work endpoint"),
            ("Baseline Normal", TemplateType.server_normal, "Mixed workload: CPU, network, file, memory"),
            ("Baseline File Heavy", TemplateType.server_file_heavy, "File-heavy workload with confidential data"),
            ("Baseline DB Load", TemplateType.db_load, "Database query workload"),
        ]

        for name, template, desc in templates:
            existing = session.query(ScenarioORM).filter_by(
                lab_id=lab.id, template_type=template
            ).first()
            if not existing:
                scenario = ScenarioORM(
                    name=name,
                    description=desc,
                    lab_id=lab.id,
                    template_type=template,
                    has_base_phase=True,
                    has_initial_phase=False,
                    has_dbtest=(template == TemplateType.db_load),
                    load_generator_package_grp_id=jmeter_pg.id,
                )
                session.add(scenario)
                session.flush()
                print(f"  Created scenario: {name} (template={template.value}, id={scenario.id})")
            else:
                print(f"  Scenario exists: {name} (id={existing.id})")

        session.commit()
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage VM snapshots (vSphere + DB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p = sub.add_parser("list", help="List vSphere snapshots for a server")
    p.add_argument("hostname")

    # list-all
    sub.add_parser("list-all", help="List vSphere snapshots for all servers")

    # create
    p = sub.add_parser("create", help="Create snapshot in vSphere + register in DB")
    p.add_argument("hostname")
    p.add_argument("snapshot_name")
    p.add_argument("--description", "-d", default="", help="Snapshot description")

    # delete
    p = sub.add_parser("delete", help="Delete snapshot from vSphere + DB")
    p.add_argument("hostname")
    p.add_argument("snapshot_name")

    # sync
    p = sub.add_parser("sync", help="Sync vSphere snapshots to DB for a server")
    p.add_argument("hostname")

    # sync-all
    sub.add_parser("sync-all", help="Sync vSphere snapshots to DB for all servers")

    # db-list
    sub.add_parser("db-list", help="Show all snapshots in DB")

    # init-scenarios
    sub.add_parser("init-scenarios", help="Create default scenarios in DB")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5s] %(message)s")
    config = load_config(CONFIG_FILE)

    if args.command == "list":
        cmd_list(config, args.hostname)
    elif args.command == "list-all":
        cmd_list_all(config)
    elif args.command == "create":
        cmd_create(config, args.hostname, args.snapshot_name, args.description)
    elif args.command == "delete":
        cmd_delete(config, args.hostname, args.snapshot_name)
    elif args.command == "sync":
        cmd_sync(config, args.hostname)
    elif args.command == "sync-all":
        cmd_sync_all(config)
    elif args.command == "db-list":
        cmd_db_list(config)
    elif args.command == "init-scenarios":
        ensure_scenarios(config)


if __name__ == "__main__":
    main()
