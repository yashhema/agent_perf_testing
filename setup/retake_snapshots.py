#!/usr/bin/env python3
"""Retake snapshots for a baseline test run — targets AND loadgens.

Loadgens:  Kill all processes, rm -rf JMeter + emulator, verify clean,
           take a fresh "clean" hypervisor snapshot, store as clean_snapshot_id.
Targets:   Revert to root (parent) snapshot, delete old test snapshot on
           hypervisor, clean the VM, take a fresh snapshot, update DB in-place.

Usage:
    python retake_snapshots.py "Win2022 CrowdStrike v7.18 baseline"
    python retake_snapshots.py --test-id 42
    python retake_snapshots.py "my test" --dry-run
    python retake_snapshots.py "my test" --targets srv1,srv2
    python retake_snapshots.py "my test" --loadgens-only
    python retake_snapshots.py "my test" --targets-only
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


# ---------------------------------------------------------------------------
# Loadgen cleanup + snapshot
# ---------------------------------------------------------------------------
LOADGEN_CLEANUP_COMMANDS_LINUX = [
    # Kill processes (use kill via pgrep to avoid sudo issues with pkill)
    ("Kill JMeter processes", "pgrep -f '[j]meter' | xargs -r kill -9 2>/dev/null; echo done"),
    ("Kill emulator processes", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done"),
    # Remove all installed artifacts (no sudo — use the SSH user's permissions)
    ("Remove JMeter", "rm -rf /opt/jmeter 2>&1 || echo 'trying sudo'; sudo rm -rf /opt/jmeter 2>&1; echo done"),
    ("Remove emulator", "rm -rf /opt/emulator 2>&1 || echo 'trying sudo'; sudo rm -rf /opt/emulator 2>&1; echo done"),
    # Remove stale run/output dirs
    ("Remove stale run dirs", "rm -rf /tmp/jmeter* /tmp/emulator* 2>&1; echo done"),
]

LOADGEN_VERIFY_COMMANDS_LINUX = [
    ("No JMeter processes", "pgrep -f '[j]meter' -c 2>/dev/null || echo 0", "0"),
    ("No emulator processes", "pgrep -f '[e]mulator' -c 2>/dev/null || echo 0", "0"),
    ("JMeter dir gone", "test -d /opt/jmeter && echo EXISTS || echo GONE", "GONE"),
    ("Emulator dir gone", "test -d /opt/emulator && echo EXISTS || echo GONE", "GONE"),
]

TARGET_CLEANUP_COMMANDS = {
    "linux": [
        ("Kill emulator", "sudo pkill -9 -f emulator || true"),
        ("Clean emulator output", "sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/*"),
    ],
    "windows": [
        ("Kill emulator", 'powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"'),
        ("Clean emulator output",
         'powershell -Command "'
         "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
         "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
         '"'),
    ],
}


def clean_loadgen(executor, hostname, dry_run=False):
    """Kill all processes and rm -rf JMeter + emulator from a loadgen. Returns True if clean."""
    print(f"\n  --- Cleaning loadgen: {hostname} ---")

    if dry_run:
        for desc, _ in LOADGEN_CLEANUP_COMMANDS_LINUX:
            print(f"    [DRY RUN] {desc}")
        return True

    # Execute cleanup
    for desc, cmd in LOADGEN_CLEANUP_COMMANDS_LINUX:
        print(f"    {desc}...")
        print(f"      cmd: {cmd}")
        result = executor.execute(cmd)
        if result.stdout.strip():
            print(f"      stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            print(f"      stderr: {result.stderr.strip()}")
        if not result.success:
            print(f"    [WARN] {desc}: exit_code={result.exit_code}")
        else:
            print(f"    [OK] {desc}")

    # Small pause for process cleanup to propagate
    time.sleep(2)

    # Verify (always read stdout — some commands return non-zero exit codes legitimately)
    all_clean = True
    print(f"    --- Verifying ---")
    for desc, cmd, expected in LOADGEN_VERIFY_COMMANDS_LINUX:
        result = executor.execute(cmd)
        # Take only the last non-empty line, strip all whitespace including \r
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        actual = lines[-1] if lines else ""
        if actual == expected:
            print(f"    [PASS] {desc}: {actual}")
        else:
            print(f"    [FAIL] {desc}: expected={expected!r}, got={actual!r} (raw={result.stdout!r})")
            all_clean = False

    return all_clean


def clean_target(executor, hostname, os_family, dry_run=False):
    """Clean a target VM after reverting to parent snapshot."""
    commands = TARGET_CLEANUP_COMMANDS.get(os_family, TARGET_CLEANUP_COMMANDS["linux"])

    if dry_run:
        for desc, _ in commands:
            print(f"    [DRY RUN] {desc}")
        return

    for desc, cmd in commands:
        print(f"    {desc}...")
        result = executor.execute(cmd)
        if not result.success:
            print(f"    [WARN] {desc}: {result.stderr}")
        else:
            print(f"    [OK] {desc}")


def main():
    parser = argparse.ArgumentParser(
        description="Retake snapshots for a baseline test run (loadgens + targets)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("name", nargs="?", default=None,
                       help="Test run name (case-insensitive search)")
    group.add_argument("--test-id", type=int, default=None,
                       help="Test run ID (exact)")
    parser.add_argument("--targets", default=None,
                        help="Comma-separated hostnames to retake (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--loadgens-only", action="store_true",
                        help="Only clean and snapshot loadgens")
    parser.add_argument("--targets-only", action="store_true",
                        help="Only retake target snapshots")

    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import (
        BaselineTestRunORM, BaselineTestRunTargetORM,
        LabORM, ServerORM, SnapshotORM,
    )
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider
    from orchestrator.infra.remote_executor import create_executor
    from orchestrator.core.baseline_execution import wait_for_ssh

    # Initialize DB engine (standalone scripts must do this explicitly)
    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()

    # --- Find test run ---
    if args.test_id:
        test_run = session.get(BaselineTestRunORM, args.test_id)
        if not test_run:
            print(f"ERROR: Test run ID {args.test_id} not found")
            sys.exit(1)
    else:
        from sqlalchemy import func
        results = session.query(BaselineTestRunORM).filter(
            func.lower(BaselineTestRunORM.name) == args.name.lower(),
        ).all()
        if not results:
            results = session.query(BaselineTestRunORM).filter(
                func.lower(BaselineTestRunORM.name).contains(args.name.lower()),
            ).all()
        if not results:
            print(f"ERROR: No test run found matching '{args.name}'")
            sys.exit(1)
        if len(results) > 1:
            print(f"Multiple test runs match '{args.name}':")
            for r in results:
                print(f"  ID={r.id}  name='{r.name}'  state={r.state.value}  created={r.created_at}")
            print("\nUse --test-id to specify exactly which one.")
            sys.exit(1)
        test_run = results[0]

    print(f"Test run: #{test_run.id} '{test_run.name}' (state={test_run.state.value})")

    # --- Get targets ---
    target_orms = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
    ).all()

    if not target_orms:
        print("ERROR: No targets found for this test run")
        sys.exit(1)

    target_filter = None
    if args.targets:
        target_filter = {h.strip().lower() for h in args.targets.split(",")}

    # --- Get lab + hypervisor ---
    lab = session.get(LabORM, test_run.lab_id)
    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    # ===================================================================
    # PHASE 1: Loadgen cleanup + snapshot
    # ===================================================================
    if not args.targets_only:
        print(f"\n{'='*60}")
        print(f"  PHASE 1: Loadgen Cleanup + Snapshot")
        print(f"{'='*60}")

        seen_loadgens = set()
        loadgen_ok = 0
        loadgen_fail = 0

        for t_orm in target_orms:
            loadgen = session.get(ServerORM, t_orm.loadgenerator_id)
            if not loadgen or loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)

            print(f"\n  Loadgen: {loadgen.hostname} ({loadgen.ip_address})")

            if args.dry_run:
                print(f"  [DRY RUN] Would: kill all, rm -rf JMeter+emulator, verify, take snapshot")
                has_snap = loadgen.clean_snapshot_id is not None
                print(f"  [DRY RUN] Current clean_snapshot_id: {loadgen.clean_snapshot_id or 'None (will create new)'}")
                loadgen_ok += 1
                continue

            # Check if clean snapshot already exists and is valid
            if loadgen.clean_snapshot_id:
                old_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                if old_snap:
                    try:
                        exists = provider.snapshot_exists(loadgen.server_infra_ref, old_snap.provider_ref)
                        if exists:
                            print(f"  [SKIP] Clean snapshot already exists: '{old_snap.name}' (ID={old_snap.id})")
                            loadgen_ok += 1
                            continue
                    except Exception:
                        pass  # snapshot check failed, proceed to recreate

            try:
                lg_cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                lg_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=lg_cred.username,
                    password=lg_cred.password,
                )
                try:
                    # Step 1: Clean everything
                    is_clean = clean_loadgen(lg_exec, loadgen.hostname)
                    if not is_clean:
                        print(f"  [ERROR] Loadgen {loadgen.hostname} not clean after cleanup — skipping snapshot")
                        loadgen_fail += 1
                        continue

                    # Step 2: Delete old clean snapshot on hypervisor (if exists)
                    if loadgen.clean_snapshot_id:
                        old_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                        if old_snap:
                            print(f"  [2] Deleting old clean snapshot '{old_snap.name}' from hypervisor...")
                            try:
                                provider.delete_snapshot(loadgen.server_infra_ref, old_snap.provider_ref)
                                print(f"      Deleted")
                            except Exception as e:
                                print(f"      Delete failed (non-fatal): {e}")

                    # Step 3: Take new clean snapshot
                    snap_name = f"clean-{loadgen.hostname}"
                    print(f"  [3] Taking snapshot '{snap_name}'...")
                    result = provider.create_snapshot(
                        loadgen.server_infra_ref,
                        snapshot_name=snap_name,
                        description=f"Clean loadgen state (no JMeter/emulator) — auto-created by retake_snapshots.py",
                    )
                    new_provider_id = (
                        result.get("snapshot_moref_id")
                        or result.get("snapshot_id")
                        or result.get("snapshot_name")
                    )
                    print(f"      Created: provider_id={new_provider_id}")

                    # Step 4: Upsert SnapshotORM record
                    if loadgen.clean_snapshot_id:
                        snap_orm = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                        if snap_orm:
                            print(f"  [4] Updating existing DB snapshot record (ID={snap_orm.id})...")
                            snap_orm.provider_snapshot_id = str(new_provider_id)
                            snap_orm.provider_ref = result
                            snap_orm.snapshot_tree = [
                                s.to_dict() for s in provider.list_snapshots(loadgen.server_infra_ref)
                            ]
                        else:
                            snap_orm = None
                    else:
                        snap_orm = None

                    if snap_orm is None:
                        print(f"  [4] Creating new DB snapshot record...")
                        snap_orm = SnapshotORM(
                            name=snap_name,
                            description=f"Clean loadgen snapshot for {loadgen.hostname}",
                            server_id=loadgen.id,
                            parent_id=None,
                            group_id=None,
                            provider_snapshot_id=str(new_provider_id),
                            provider_ref=result,
                            snapshot_tree=[
                                s.to_dict() for s in provider.list_snapshots(loadgen.server_infra_ref)
                            ],
                            is_baseline=False,
                            is_archived=False,
                        )
                        session.add(snap_orm)
                        session.flush()

                    # Step 5: Link to server
                    loadgen.clean_snapshot_id = snap_orm.id
                    session.commit()
                    print(f"      DB record ID={snap_orm.id}, linked to server.clean_snapshot_id")

                    # Step 6: Verify snapshot exists on hypervisor
                    exists = provider.snapshot_exists(loadgen.server_infra_ref, result)
                    if exists:
                        print(f"  [VERIFIED] Snapshot exists on hypervisor")
                    else:
                        print(f"  [WARN] Snapshot not found on hypervisor after creation!")

                    loadgen_ok += 1

                finally:
                    lg_exec.close()
            except Exception as e:
                print(f"  [ERROR] {e}")
                loadgen_fail += 1
                try:
                    session.rollback()
                except Exception:
                    pass

        print(f"\n  Loadgens: {loadgen_ok} ok, {loadgen_fail} failed")

    # ===================================================================
    # PHASE 2: Target snapshot retake
    # ===================================================================
    if not args.loadgens_only:
        print(f"\n{'='*60}")
        print(f"  PHASE 2: Target Snapshot Retake")
        print(f"{'='*60}")

        success_count = 0
        fail_count = 0
        skip_count = 0

        for t_orm in target_orms:
            server = session.get(ServerORM, t_orm.target_id)
            snapshot = session.get(SnapshotORM, t_orm.test_snapshot_id)

            if not server or not snapshot:
                print(f"\n  SKIP: target_id={t_orm.target_id} — server or snapshot not found")
                skip_count += 1
                continue

            if target_filter and server.hostname.lower() not in target_filter:
                continue

            print(f"\n{'='*60}")
            print(f"  Target: {server.hostname} ({server.ip_address})")
            print(f"  Snapshot: '{snapshot.name}' (ID={snapshot.id}, provider={snapshot.provider_snapshot_id})")

            has_parent = snapshot.parent_id is not None
            parent = None
            if has_parent:
                parent = session.get(SnapshotORM, snapshot.parent_id)
                if parent:
                    print(f"  Parent: '{parent.name}' (ID={parent.id})")
                else:
                    print(f"  Parent ID={snapshot.parent_id} not found in DB — treating as root")
                    has_parent = False

            if args.dry_run:
                if has_parent:
                    print(f"  [DRY RUN] Would: revert to parent -> cleanup -> delete old -> take new -> update DB")
                else:
                    print(f"  [DRY RUN] Would: revert to snapshot -> cleanup in-place -> delete old -> take new -> update DB")
                success_count += 1
                continue

            try:
                # Step 1: Revert
                if has_parent:
                    # Has parent: revert to parent (clean base)
                    print(f"  [1/7] Reverting to parent snapshot '{parent.name}'...")
                    new_ip = provider.restore_snapshot(server.server_infra_ref, parent.provider_ref)
                else:
                    # Root snapshot: revert to itself, then clean in-place
                    print(f"  [1/7] Reverting to snapshot '{snapshot.name}' (root — will clean in-place)...")
                    new_ip = provider.restore_snapshot(server.server_infra_ref, snapshot.provider_ref)

                provider.wait_for_vm_ready(server.server_infra_ref)
                actual_ip = server.ip_address
                if new_ip and new_ip != server.ip_address:
                    actual_ip = new_ip
                    server.ip_address = new_ip
                    session.commit()
                    print(f"         IP changed: {server.ip_address} -> {new_ip}")

                # Step 2: Wait for SSH/WinRM
                print(f"  [2/7] Waiting for {'WinRM' if server.os_family.value == 'windows' else 'SSH'}...")
                wait_for_ssh(actual_ip, os_family=server.os_family.value, timeout_sec=120)
                print(f"         Connected")

                # Step 3: Cleanup
                print(f"  [3/7] Running cleanup on {server.hostname}...")
                target_cred = credentials.get_server_credential(server.id, server.os_family.value)
                executor = create_executor(
                    os_family=server.os_family.value,
                    host=actual_ip,
                    username=target_cred.username,
                    password=target_cred.password,
                )
                try:
                    clean_target(executor, server.hostname, server.os_family.value)
                finally:
                    executor.close()

                # Step 4: Delete old snapshot on hypervisor
                print(f"  [4/7] Deleting old snapshot '{snapshot.name}' from hypervisor...")
                try:
                    provider.delete_snapshot(server.server_infra_ref, snapshot.provider_ref)
                    print(f"         Deleted")
                except Exception as e:
                    print(f"         Delete failed (non-fatal, may already be gone): {e}")

                # Step 5: Take new snapshot
                print(f"  [5/7] Taking new snapshot '{snapshot.name}'...")
                result = provider.create_snapshot(
                    server.server_infra_ref,
                    snapshot_name=snapshot.name,
                    description=snapshot.description or "",
                )
                new_provider_id = (
                    result.get("snapshot_moref_id")
                    or result.get("snapshot_id")
                    or result.get("snapshot_name")
                )
                print(f"         Created: provider_id={new_provider_id}")

                # Step 6: Update DB record in-place
                print(f"  [6/7] Updating DB record (ID={snapshot.id})...")
                old_provider_id = snapshot.provider_snapshot_id
                snapshot.provider_snapshot_id = str(new_provider_id)
                snapshot.provider_ref = result
                snapshot.snapshot_tree = [
                    s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)
                ]
                session.commit()
                print(f"         Updated: provider_id {old_provider_id} -> {new_provider_id}")
                print(f"         DB record ID={snapshot.id} preserved (group, baseline refs unchanged)")

                # Step 7: Verify snapshot exists on hypervisor
                exists = provider.snapshot_exists(server.server_infra_ref, result)
                if exists:
                    print(f"  [7/7] [VERIFIED] Snapshot exists on hypervisor")
                else:
                    print(f"  [7/7] [WARN] Snapshot not found on hypervisor after creation!")

                success_count += 1

            except Exception as e:
                print(f"  ERROR: {e}")
                fail_count += 1
                try:
                    session.rollback()
                except Exception:
                    pass

        print(f"\n  Targets: {success_count} ok, {fail_count} failed, {skip_count} skipped")

    # ===================================================================
    # Summary
    # ===================================================================
    print(f"\n{'='*60}")
    print(f"  DONE")
    if not args.targets_only:
        print(f"  Run sanity check from the UI to confirm all green.")
    print(f"{'='*60}")

    session.close()


if __name__ == "__main__":
    main()
