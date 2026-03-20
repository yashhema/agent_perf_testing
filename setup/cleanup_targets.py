#!/usr/bin/env python3
"""Standalone cleanup script for target servers and loadgens.

Kills emulator/JMeter processes and cleans artifact directories.
Used to remediate dirty snapshots or clean up after failed test runs.

Usage:
    python cleanup_targets.py --lab <lab_name>
    python cleanup_targets.py --lab <lab_name> --servers srv1,srv2
    python cleanup_targets.py --lab <lab_name> --loadgens lg1,lg2
    python cleanup_targets.py --lab <lab_name> --full
"""

import argparse
import os
import sys

# Add orchestrator src to path for DB access
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def get_session_and_credentials():
    """Initialize DB session and credentials."""
    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore

    # Initialize DB engine (standalone scripts must do this explicitly)
    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()
    return session, credentials


def clean_target(server, credentials, full=False):
    """Clean a target server: stop emulator, clean dirs."""
    from orchestrator.infra.remote_executor import create_executor

    cred = credentials.get_server_credential(server.id, server.os_family.value)
    executor = create_executor(
        os_family=server.os_family.value,
        host=server.ip_address,
        username=cred.username,
        password=cred.password,
    )

    print(f"\nCleaning target: {server.hostname} ({server.ip_address})")

    try:
        # Stop emulator
        if server.os_family.value == "windows":
            result = executor.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
        else:
            result = executor.execute("sudo pkill -f emulator || true")
        print(f"  [OK] Emulator stopped")

        # Clean dirs
        if server.os_family.value == "windows":
            if full:
                executor.execute('powershell -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue C:\\emulator"')
                print(f"  [OK] C:\\emulator removed (full)")
            else:
                executor.execute(
                    'powershell -Command "'
                    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                    '"'
                )
                print(f"  [OK] C:\\emulator\\output\\ cleaned")
                print(f"  [OK] C:\\emulator\\stats\\ cleaned")
        else:
            if full:
                executor.execute("sudo rm -rf /opt/emulator/")
                print(f"  [OK] /opt/emulator/ removed (full)")
            else:
                executor.execute("sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/*")
                print(f"  [OK] /opt/emulator/output/ cleaned")
                print(f"  [OK] /opt/emulator/stats/ cleaned")
    except Exception as e:
        print(f"  [ERROR] {e}")
    finally:
        executor.close()


def clean_loadgen(server, credentials, full=False):
    """Clean a loadgen server: kill JMeter, clean runs dir."""
    from orchestrator.infra.remote_executor import create_executor

    cred = credentials.get_server_credential(server.id, server.os_family.value)
    executor = create_executor(
        os_family=server.os_family.value,
        host=server.ip_address,
        username=cred.username,
        password=cred.password,
    )

    print(f"\nCleaning loadgen: {server.hostname} ({server.ip_address})")

    try:
        # Kill JMeter
        result = executor.execute("pkill -f jmeter || true")
        # Count killed processes
        count_result = executor.execute("pgrep -c -f jmeter || echo 0")
        print(f"  [OK] JMeter killed")

        # Clean runs
        if full:
            executor.execute("sudo rm -rf /opt/jmeter/")
            print(f"  [OK] /opt/jmeter/ removed (full)")
        else:
            executor.execute("sudo rm -rf /opt/jmeter/runs/")
            print(f"  [OK] /opt/jmeter/runs/ removed")
    except Exception as e:
        print(f"  [ERROR] {e}")
    finally:
        executor.close()


def main():
    parser = argparse.ArgumentParser(description="Clean up target servers and loadgens")
    parser.add_argument("--lab", required=True, help="Lab name")
    parser.add_argument("--servers", default=None, help="Comma-separated server hostnames (default: all in lab)")
    parser.add_argument("--loadgens", default=None, help="Comma-separated loadgen hostnames (default: all in lab)")
    parser.add_argument("--full", action="store_true", help="Full cleanup: remove entire install dirs")
    args = parser.parse_args()

    session, credentials = get_session_and_credentials()

    from orchestrator.models.orm import LabORM, ServerORM

    # Find lab
    lab = session.query(LabORM).filter(LabORM.name == args.lab).first()
    if not lab:
        print(f"Lab '{args.lab}' not found")
        sys.exit(1)

    # Get all servers in lab
    servers = session.query(ServerORM).filter(ServerORM.lab_id == lab.id).all()

    # Filter target servers
    target_filter = set(args.servers.split(",")) if args.servers else None
    loadgen_filter = set(args.loadgens.split(",")) if args.loadgens else None

    # Identify unique loadgens from server defaults
    loadgen_ids = set()
    for s in servers:
        if s.default_loadgen_id:
            loadgen_ids.add(s.default_loadgen_id)

    # Clean targets
    for s in servers:
        if s.id in loadgen_ids:
            continue  # Skip loadgens in target pass
        if target_filter and s.hostname not in target_filter:
            continue
        clean_target(s, credentials, full=args.full)

    # Clean loadgens
    for lg_id in loadgen_ids:
        lg = session.get(ServerORM, lg_id)
        if not lg:
            continue
        if loadgen_filter and lg.hostname not in loadgen_filter:
            continue
        clean_loadgen(lg, credentials, full=args.full)

    print("\nDone. Take fresh snapshots in vSphere/Proxmox now.")
    session.close()


if __name__ == "__main__":
    main()
