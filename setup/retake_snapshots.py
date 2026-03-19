#!/usr/bin/env python3
"""Retake dirty snapshots for a baseline test run.

Given a test name (case-insensitive), finds all target snapshots,
reverts each to its parent, cleans the VM, deletes the old snapshot
on the hypervisor, takes a fresh one, and updates the existing DB
record in-place (same ID, same group — no new records).

Usage:
    python retake_snapshots.py "Win2022 CrowdStrike v7.18 baseline"
    python retake_snapshots.py --test-id 42
    python retake_snapshots.py "my test" --dry-run
    python retake_snapshots.py "my test" --targets srv1,srv2   # only specific targets
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


def main():
    parser = argparse.ArgumentParser(
        description="Retake dirty snapshots for a baseline test run",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("name", nargs="?", default=None,
                       help="Test run name (case-insensitive search)")
    group.add_argument("--test-id", type=int, default=None,
                       help="Test run ID (exact)")
    parser.add_argument("--targets", default=None,
                        help="Comma-separated hostnames to retake (default: all targets)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="Skip the cleanup step (VM already clean)")
    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal
    from orchestrator.models.orm import (
        BaselineTestRunORM, BaselineTestRunTargetORM,
        LabORM, ServerORM, SnapshotORM,
    )
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider
    from orchestrator.infra.remote_executor import create_executor
    from orchestrator.core.baseline_execution import wait_for_ssh

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
        # Case-insensitive name search
        from sqlalchemy import func
        results = session.query(BaselineTestRunORM).filter(
            func.lower(BaselineTestRunORM.name) == args.name.lower(),
        ).all()
        if not results:
            # Try partial match
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

    # Filter targets if --targets specified
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

    # --- Phase 1: Clean loadgens ---
    print(f"\n{'='*60}")
    print(f"  PHASE 1: Loadgen Cleanup")
    print(f"{'='*60}")

    seen_loadgens = set()
    for t_orm in target_orms:
        loadgen = session.get(ServerORM, t_orm.loadgenerator_id)
        if not loadgen or loadgen.id in seen_loadgens:
            continue
        seen_loadgens.add(loadgen.id)

        print(f"\n  Loadgen: {loadgen.hostname} ({loadgen.ip_address})")

        if args.dry_run:
            print(f"  [DRY RUN] Would: kill JMeter, clean stale run dirs")
            continue

        try:
            lg_cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            lg_exec = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=lg_cred.username,
                password=lg_cred.password,
            )
            try:
                # Kill all JMeter processes
                result = lg_exec.execute("pkill -f jmeter || true")
                print(f"    [OK] JMeter processes killed")

                # Clean stale run dirs from previous tests (keep nothing)
                result = lg_exec.execute("sudo rm -rf /opt/jmeter/runs/baseline_*")
                print(f"    [OK] Stale run dirs cleaned")

                # Kill emulator if running on loadgen
                result = lg_exec.execute("sudo pkill -f emulator || true")
                print(f"    [OK] Emulator processes killed")
            finally:
                lg_exec.close()
        except Exception as e:
            print(f"    [ERROR] {e}")

    # --- Phase 2: Retake target snapshots ---
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

        if not snapshot.parent_id:
            print(f"  SKIP: No parent snapshot — this is a root snapshot, cannot retake")
            skip_count += 1
            continue

        parent = session.get(SnapshotORM, snapshot.parent_id)
        if not parent:
            print(f"  SKIP: Parent snapshot ID={snapshot.parent_id} not found in DB")
            skip_count += 1
            continue
        if parent.is_archived:
            print(f"  SKIP: Parent snapshot '{parent.name}' is archived")
            skip_count += 1
            continue

        print(f"  Parent: '{parent.name}' (ID={parent.id}, provider={parent.provider_snapshot_id})")

        if args.dry_run:
            print(f"  [DRY RUN] Would: revert to parent → cleanup → delete old → take new → update DB")
            success_count += 1
            continue

        try:
            # Step 1: Revert to parent
            print(f"  [1/6] Reverting to parent snapshot '{parent.name}'...")
            new_ip = provider.restore_snapshot(server.server_infra_ref, parent.provider_ref)
            provider.wait_for_vm_ready(server.server_infra_ref)
            actual_ip = server.ip_address
            if new_ip and new_ip != server.ip_address:
                actual_ip = new_ip
                server.ip_address = new_ip
                session.commit()
                print(f"         IP changed: {server.ip_address} -> {new_ip}")

            # Step 2: Wait for SSH/WinRM
            print(f"  [2/6] Waiting for {'WinRM' if server.os_family.value == 'windows' else 'SSH'}...")
            wait_for_ssh(actual_ip, os_family=server.os_family.value, timeout_sec=120)
            print(f"         Connected")

            # Step 3: Cleanup
            if args.skip_cleanup:
                print(f"  [3/6] Cleanup SKIPPED (--skip-cleanup)")
            else:
                print(f"  [3/6] Running cleanup on {server.hostname}...")
                target_cred = credentials.get_server_credential(server.id, server.os_family.value)
                executor = create_executor(
                    os_family=server.os_family.value,
                    host=actual_ip,
                    username=target_cred.username,
                    password=target_cred.password,
                )
                try:
                    if server.os_family.value == "windows":
                        executor.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
                        executor.execute(
                            'powershell -Command "'
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                            '"'
                        )
                    else:
                        executor.execute("sudo pkill -f emulator || true")
                        executor.execute("sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/*")
                    print(f"         Cleanup done")
                finally:
                    executor.close()

            # Step 4: Delete old snapshot on hypervisor
            print(f"  [4/6] Deleting old snapshot '{snapshot.name}' from hypervisor...")
            try:
                provider.delete_snapshot(server.server_infra_ref, snapshot.provider_ref)
                print(f"         Deleted")
            except Exception as e:
                print(f"         Delete failed (non-fatal, may already be gone): {e}")

            # Step 5: Take new snapshot
            print(f"  [5/6] Taking new snapshot '{snapshot.name}'...")
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
            print(f"  [6/6] Updating DB record (ID={snapshot.id})...")
            old_provider_id = snapshot.provider_snapshot_id
            snapshot.provider_snapshot_id = new_provider_id
            snapshot.provider_ref = result
            snapshot.snapshot_tree = [
                s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)
            ]
            session.commit()
            print(f"         Updated: provider_id {old_provider_id} -> {new_provider_id}")
            print(f"         DB record ID={snapshot.id} preserved (group, baseline refs unchanged)")

            success_count += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            fail_count += 1
            try:
                session.rollback()
            except Exception:
                pass

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  Loadgens cleaned: {len(seen_loadgens)}")
    print(f"  Targets retaken:  {success_count} ok, {fail_count} failed, {skip_count} skipped")
    if fail_count == 0 and success_count > 0:
        print(f"\n  All clean. Run sanity check from the UI to confirm, then start/retry the test.")
    elif fail_count > 0:
        print(f"\n  {fail_count} target(s) failed. Check errors above and fix manually.")
    print(f"{'='*60}")

    session.close()


if __name__ == "__main__":
    main()
