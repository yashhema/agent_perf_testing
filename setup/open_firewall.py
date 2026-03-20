#!/usr/bin/env python3
"""Open emulator port (8080) on all servers in a lab.

Reads servers from DB, SSHes in, opens firewall port.
Run this BEFORE retaking snapshots so the port is baked into the snapshot.

Usage:
    python open_firewall.py --lab <lab_name>
    python open_firewall.py --lab <lab_name> --port 8080
    python open_firewall.py --lab <lab_name> --dry-run
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def main():
    parser = argparse.ArgumentParser(description="Open firewall port on all servers in a lab")
    parser.add_argument("--lab", required=True, help="Lab name")
    parser.add_argument("--port", type=int, default=8080, help="Port to open (default: 8080)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import LabORM, ServerORM
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.remote_executor import create_executor
    from sqlalchemy import func

    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()

    # Find lab
    lab = session.query(LabORM).filter(
        func.lower(LabORM.name) == args.lab.lower()
    ).first()
    if not lab:
        # Try partial match
        lab = session.query(LabORM).filter(
            func.lower(LabORM.name).contains(args.lab.lower())
        ).first()
    if not lab:
        print(f"ERROR: No lab found matching '{args.lab}'")
        sys.exit(1)

    print(f"Lab: {lab.name} (ID={lab.id})")

    # Get all servers in lab
    servers = session.query(ServerORM).filter(ServerORM.lab_id == lab.id).all()
    if not servers:
        print("ERROR: No servers found in this lab")
        sys.exit(1)

    print(f"Servers: {len(servers)}")
    print(f"Port: {args.port}")
    print()

    ok_count = 0
    fail_count = 0

    for server in servers:
        print(f"{'='*50}")
        print(f"  {server.hostname} ({server.ip_address}) — {server.os_family.value}")

        if args.dry_run:
            print(f"  [DRY RUN] Would open port {args.port}/tcp")
            ok_count += 1
            continue

        try:
            cred = credentials.get_server_credential(server.id, server.os_family.value)
            executor = create_executor(
                os_family=server.os_family.value,
                host=server.ip_address,
                username=cred.username,
                password=cred.password,
            )
            try:
                if server.os_family.value == "windows":
                    cmd = (
                        f'powershell -Command "'
                        f"New-NetFirewallRule -DisplayName 'Emulator {args.port}' "
                        f"-Direction Inbound -Port {args.port} -Protocol TCP "
                        f'-Action Allow -ErrorAction SilentlyContinue"'
                    )
                    result = executor.execute(cmd)
                    if result.success:
                        print(f"  [OK] Windows firewall rule added for port {args.port}")
                    else:
                        print(f"  [WARN] {result.stderr}")
                else:
                    # Try firewall-cmd (RHEL/CentOS)
                    result = executor.execute(
                        f"sudo firewall-cmd --permanent --add-port={args.port}/tcp 2>&1 && "
                        f"sudo firewall-cmd --reload 2>&1"
                    )
                    if result.success:
                        print(f"  [OK] firewall-cmd: port {args.port}/tcp opened")
                    else:
                        # Fallback: iptables
                        result2 = executor.execute(
                            f"sudo iptables -C INPUT -p tcp --dport {args.port} -j ACCEPT 2>/dev/null || "
                            f"sudo iptables -I INPUT -p tcp --dport {args.port} -j ACCEPT"
                        )
                        if result2.success:
                            print(f"  [OK] iptables: port {args.port}/tcp opened")
                        else:
                            print(f"  [WARN] Could not open port: {result.stdout} {result2.stderr}")

                    # Verify port is open
                    verify = executor.execute(
                        f"sudo firewall-cmd --list-ports 2>/dev/null | grep -q {args.port} && echo OPEN || "
                        f"sudo iptables -C INPUT -p tcp --dport {args.port} -j ACCEPT 2>/dev/null && echo OPEN || "
                        f"echo CLOSED"
                    )
                    status = verify.stdout.strip().split('\n')[-1].strip()
                    if "OPEN" in status:
                        print(f"  [VERIFIED] Port {args.port} is open")
                    else:
                        print(f"  [WARN] Could not verify port is open")

                ok_count += 1
            finally:
                executor.close()
        except Exception as e:
            print(f"  [ERROR] {e}")
            fail_count += 1

    print(f"\n{'='*50}")
    print(f"  Done: {ok_count} ok, {fail_count} failed")
    if fail_count == 0 and not args.dry_run:
        print(f"\n  Now retake snapshots to bake the firewall change in:")
        print(f"    python retake_snapshots.py \"<test_name>\" --force")
    print(f"{'='*50}")

    session.close()


if __name__ == "__main__":
    main()
