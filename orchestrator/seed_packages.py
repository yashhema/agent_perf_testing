#!/usr/bin/env python3
"""Seed package group members for JMeter and Emulator.

Adds OS-specific package members so PackageResolver can match servers.
Safe to re-run — skips if members already exist for that OS regex.

Also shows current server OS info so you can verify/fix missing fields.

Usage:
    cd orchestrator
    python seed_packages.py [--config config/orchestrator.yaml]
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from orchestrator.config.settings import load_config
from orchestrator.models.database import init_db, SessionLocal
from orchestrator.models.orm import (
    PackageGroupORM,
    PackageGroupMemberORM,
    ServerORM,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Package files (relative to artifacts dir, served at /packages/...) ──
# These paths match what's in orchestrator/artifacts/packages/
JMETER_LINUX_PKG = "/packages/jmeter-5.6.3-linux.tar.gz"
EMULATOR_LINUX_PKG = "/packages/emulator-linux.tar.gz"
EMULATOR_WINDOWS_PKG = "/packages/emulator-windows.tar.gz"

# ── Members to seed ──
MEMBERS = {
    "jmeter-default": [
        {
            "os_match_regex": "rhel/.*",
            "path": JMETER_LINUX_PKG,
            "root_install_path": "/opt/jmeter",
            "extraction_command": "mkdir -p /opt/jmeter && tar xzf {file} -C /opt/jmeter --strip-components=1",
            "install_command": None,
            "run_command": None,  # JMeter is started by orchestrator via JMeterController
            "output_path": None,
            "uninstall_command": "rm -rf /opt/jmeter",
            "status_command": "test -f /opt/jmeter/bin/jmeter && echo OK",
            "prereq_script": None,
        },
    ],
    "emulator-default": [
        {
            "os_match_regex": "rhel/.*",
            "path": EMULATOR_LINUX_PKG,
            "root_install_path": "/opt/emulator",
            "extraction_command": "mkdir -p /opt/emulator && tar xzf {file} -C /opt/emulator",
            "install_command": None,
            "run_command": "cd /opt/emulator && nohup ./start.sh > /opt/emulator/emulator.log 2>&1 &",
            "output_path": "/opt/emulator/output",
            "uninstall_command": "rm -rf /opt/emulator",
            "status_command": "curl -sf http://localhost:8080/api/v1/health",
            "prereq_script": None,
        },
        {
            "os_match_regex": "windows_server/.*",
            "path": EMULATOR_WINDOWS_PKG,
            "root_install_path": "C:\\emulator",
            "extraction_command": "powershell -Command \"Expand-Archive -Path '{file}' -DestinationPath 'C:\\emulator' -Force\"",
            "install_command": None,
            "run_command": "powershell -Command \"Start-Process -FilePath 'C:\\emulator\\start.bat' -WindowStyle Hidden\"",
            "output_path": "C:\\emulator\\output",
            "uninstall_command": "powershell -Command \"Remove-Item -Recurse -Force 'C:\\emulator'\"",
            "status_command": "powershell -Command \"(Invoke-WebRequest -Uri http://localhost:8080/api/v1/health -UseBasicParsing).StatusCode\"",
            "prereq_script": None,
        },
    ],
}


def show_servers(session):
    """Show all servers with their OS info for verification."""
    servers = session.query(ServerORM).order_by(ServerORM.id).all()
    print("\n" + "=" * 80)
    print("CURRENT SERVERS — check os_vendor_family and os_major_ver are set")
    print("=" * 80)
    print(f"  {'ID':<4} {'Hostname':<25} {'os_family':<10} {'os_vendor_family':<18} {'os_major_ver':<12} {'os_minor_ver':<12}")
    print("  " + "-" * 78)

    needs_fix = []
    for s in servers:
        vendor = s.os_vendor_family or "NULL"
        major = s.os_major_ver or "NULL"
        minor = s.os_minor_ver or ""
        flag = " <-- NEEDS FIX" if not s.os_vendor_family or not s.os_major_ver else ""
        print(f"  {s.id:<4} {s.hostname:<25} {s.os_family.value:<10} {vendor:<18} {major:<12} {minor:<12}{flag}")
        if not s.os_vendor_family or not s.os_major_ver:
            needs_fix.append(s)

    if needs_fix:
        print(f"\n  WARNING: {len(needs_fix)} server(s) have NULL os_vendor_family/os_major_ver.")
        print("  Package resolution will FAIL for these servers.")
        print("  Fix via Admin UI > Servers > Edit, or run:")
        print()
        for s in needs_fix:
            if s.os_family.value == "linux":
                print(f"    -- Server '{s.hostname}' (id={s.id}): set os_vendor_family and os_major_ver")
                print(f"    UPDATE servers SET os_vendor_family='rhel', os_major_ver='8' WHERE id={s.id};")
            else:
                print(f"    -- Server '{s.hostname}' (id={s.id}): set os_vendor_family and os_major_ver")
                print(f"    UPDATE servers SET os_vendor_family='windows_server', os_major_ver='2019' WHERE id={s.id};")
        print()
    else:
        print("\n  All servers have os_vendor_family and os_major_ver set.\n")

    return needs_fix


def seed_members(session):
    """Seed package group members. Skips existing (by os_match_regex)."""
    print("=" * 80)
    print("SEEDING PACKAGE GROUP MEMBERS")
    print("=" * 80)

    for group_name, members in MEMBERS.items():
        group = session.query(PackageGroupORM).filter_by(name=group_name).first()
        if not group:
            logger.warning("  Package group '%s' not found — skipping. Create it in Admin > Packages first.", group_name)
            continue

        print(f"\n  Package group: '{group_name}' (id={group.id})")

        # Show existing members
        existing = session.query(PackageGroupMemberORM).filter_by(
            package_group_id=group.id,
        ).all()
        if existing:
            print(f"    Existing members: {len(existing)}")
            for m in existing:
                print(f"      id={m.id}  os_match_regex='{m.os_match_regex}'  path='{m.path}'")

        for member_data in members:
            regex = member_data["os_match_regex"]

            # Check if already exists
            exists = session.query(PackageGroupMemberORM).filter_by(
                package_group_id=group.id,
                os_match_regex=regex,
            ).first()

            if exists:
                print(f"    SKIP: os_match_regex='{regex}' already exists (id={exists.id})")
                continue

            m = PackageGroupMemberORM(
                package_group_id=group.id,
                os_match_regex=member_data["os_match_regex"],
                path=member_data["path"],
                root_install_path=member_data["root_install_path"],
                extraction_command=member_data.get("extraction_command"),
                install_command=member_data.get("install_command"),
                run_command=member_data.get("run_command"),
                output_path=member_data.get("output_path"),
                uninstall_command=member_data.get("uninstall_command"),
                status_command=member_data.get("status_command"),
                prereq_script=member_data.get("prereq_script"),
            )
            session.add(m)
            session.flush()
            print(f"    ADDED: os_match_regex='{regex}', path='{member_data['path']}' (id={m.id})")

    session.commit()
    print()


def verify_resolution(session):
    """Test package resolution for each server."""
    from orchestrator.services.package_manager import PackageResolver
    from orchestrator.models.orm import LabORM

    print("=" * 80)
    print("VERIFYING PACKAGE RESOLUTION")
    print("=" * 80)

    resolver = PackageResolver()
    servers = session.query(ServerORM).order_by(ServerORM.id).all()
    labs = {lab.id: lab for lab in session.query(LabORM).all()}

    for s in servers:
        lab = labs.get(s.lab_id)
        if not lab:
            print(f"  {s.hostname}: lab_id={s.lab_id} not found — SKIP")
            continue

        if not s.os_vendor_family or not s.os_major_ver:
            print(f"  {s.hostname}: os_vendor_family/os_major_ver is NULL — SKIP (fix first)")
            continue

        os_string = resolver._build_os_string(s)

        # Try JMeter (loadgen package)
        try:
            jmeter = resolver.resolve(session, [lab.jmeter_package_grpid], s)
            print(f"  {s.hostname} ({os_string}): JMeter OK -> '{jmeter[0].path}'")
        except ValueError as e:
            print(f"  {s.hostname} ({os_string}): JMeter FAIL -> {e}")

        # Try emulator (if configured)
        if lab.emulator_package_grp_id:
            try:
                emu = resolver.resolve(session, [lab.emulator_package_grp_id], s)
                print(f"  {s.hostname} ({os_string}): Emulator OK -> '{emu[0].path}'")
            except ValueError as e:
                print(f"  {s.hostname} ({os_string}): Emulator FAIL -> {e}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Seed package group members")
    parser.add_argument("--config", default="config/orchestrator.yaml")
    parser.add_argument("--verify-only", action="store_true", help="Only show server info and verify resolution, don't seed")
    args = parser.parse_args()

    config = load_config(args.config)
    init_db(config.database.url, echo=False)
    session = SessionLocal()

    try:
        needs_fix = show_servers(session)

        if not args.verify_only:
            seed_members(session)

        verify_resolution(session)

        if needs_fix:
            print("ACTION REQUIRED: Fix the server(s) marked above, then re-run:")
            print("  python seed_packages.py --verify-only")
    finally:
        session.close()


if __name__ == "__main__":
    main()
