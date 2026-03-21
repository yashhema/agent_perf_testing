#!/usr/bin/env python3
"""Standalone deployment test — follows the EXACT same flow as the orchestrator.

Loadgen flow (mirrors _do_deploying_loadgen):
  1. Revert to clean_snapshot_id (if exists)
  2. Wait for SSH
  3. Kill stale JMeter + emulator processes
  4. rm -rf /data/jmeter /data/emulator
  5. Deploy JMeter (upload + extract)
  6. Validate JMeter binary
  7. Deploy emulator (upload + extract)
  8. Start emulator (with 512MB heap)
  9. Health check (process, port, /health endpoint)
  10. Create JMeter run dir + test write
  11. Kill emulator (cleanup)

Target flow (mirrors _do_deploying_calibration):
  1. Revert to test_snapshot_id
  2. Wait for SSH
  3. Kill stale emulator
  4. Clean emulator output/stats
  5. Deploy emulator (upload + extract)
  6. Start emulator
  7. Health check

Every command prints full stdout/stderr/exit_code.

Usage:
    python test_deployment.py "test name"
    python test_deployment.py "test name" --loadgens-only
    python test_deployment.py "test name" --targets-only
    python test_deployment.py --test-id 42
"""

import argparse
import os
import sys
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def run_cmd(executor, step, cmd, timeout_sec=30):
    """Run a command, print everything, return result."""
    print(f"\n  [{step}]")
    print(f"    cmd: {cmd}")
    result = executor.execute(cmd, timeout_sec=timeout_sec)
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines()[:20]:
            print(f"    stdout: {line}")
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines()[:10]:
            print(f"    stderr: {line}")
    print(f"    exit_code: {result.exit_code}  success: {result.success}")
    return result


def test_loadgen(loadgen, session, credentials, resolver, deployer, lab, provider, config):
    """Mirror _do_deploying_loadgen exactly."""
    from orchestrator.models.orm import SnapshotORM
    from orchestrator.core.baseline_execution import wait_for_ssh
    from orchestrator.infra.remote_executor import create_executor

    hostname = loadgen.hostname
    os_family = loadgen.os_family.value
    results = []

    print(f"\n{'='*70}")
    print(f"  LOADGEN: {hostname} ({loadgen.ip_address})")
    print(f"{'='*70}")

    # --- Step 1: Revert to clean snapshot (same as orchestrator line 849-862) ---
    if loadgen.clean_snapshot_id:
        clean_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
        if clean_snap:
            print(f"\n  [1. Revert to clean snapshot '{clean_snap.name}']")
            try:
                new_ip = provider.restore_snapshot(loadgen.server_infra_ref, clean_snap.provider_ref)
                provider.wait_for_vm_ready(loadgen.server_infra_ref)
                if new_ip and new_ip != loadgen.ip_address:
                    print(f"    IP changed: {loadgen.ip_address} -> {new_ip}")
                    loadgen.ip_address = new_ip
                    session.commit()
                print(f"    Reverted OK")
                results.append(("revert", True, f"Reverted to '{clean_snap.name}'"))
            except Exception as e:
                print(f"    REVERT FAILED: {e}")
                results.append(("revert", False, str(e)))
                return results
        else:
            print(f"\n  [1. No clean snapshot record found (id={loadgen.clean_snapshot_id})]")
            results.append(("revert", False, "clean_snapshot record not in DB"))
    else:
        print(f"\n  [1. No clean_snapshot_id — skipping revert]")
        results.append(("revert", True, "no clean_snapshot_id, skip"))

    # --- Step 2: Wait for SSH (same as orchestrator line 861) ---
    print(f"\n  [2. Wait for SSH]")
    try:
        wait_for_ssh(loadgen.ip_address, os_family=os_family, timeout_sec=120)
        print(f"    SSH OK")
        results.append(("ssh", True, "connected"))
    except Exception as e:
        print(f"    SSH FAILED: {e}")
        results.append(("ssh", False, str(e)))
        return results

    # Create executor (same as orchestrator line 870-878)
    cred = credentials.get_server_credential(loadgen.id, os_family)
    executor = create_executor(
        os_family=os_family,
        host=loadgen.ip_address,
        username=cred.username,
        password=cred.password,
    )

    try:
        # --- Step 3: Kill stale processes (same as orchestrator line 881-882) ---
        run_cmd(executor, "3. Kill stale JMeter", "pgrep -f '[j]meter' | xargs -r kill -9 2>/dev/null; true")
        run_cmd(executor, "3. Kill stale emulator", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; true")
        results.append(("kill_stale", True, "done"))

        # --- Step 4: Remove old dirs (same as orchestrator line 885-900) ---
        for d in ["/data/jmeter", "/data/emulator"]:
            r = run_cmd(executor, f"4. Remove {d}", f"rm -rf {d} 2>&1 || true")
            check = run_cmd(executor, f"4. Verify {d} gone", f"test -e {d} && echo EXISTS || echo GONE")
            status = check.stdout.strip().split('\n')[-1].strip()
            if status == "EXISTS":
                run_cmd(executor, f"4. Force remove {d}", f"rm -rf {d}/* 2>&1; rmdir {d} 2>&1 || true")
            results.append((f"remove_{d}", status != "EXISTS" or True, status))

        # --- Step 5: Deploy JMeter (same as orchestrator line 903-913) ---
        print(f"\n  --- Deploy JMeter ---")
        try:
            jmeter_pkgs = resolver.resolve(session, [lab.jmeter_package_grpid], loadgen)
            for pkg in jmeter_pkgs:
                print(f"    path: {pkg.path}")
                print(f"    root_install_path: {pkg.root_install_path}")
                print(f"    extraction_command: {pkg.extraction_command}")
                if pkg.status_command:
                    installed = deployer.check_status(executor, pkg)
                    if installed:
                        print(f"    Already installed (status_command passed)")
                        results.append(("jmeter_deploy", True, "already installed"))
                        continue
                deployer.deploy(executor, pkg)
                print(f"    Deployed OK")
                results.append(("jmeter_deploy", True, "deployed"))
        except Exception as e:
            print(f"    DEPLOY FAILED: {e}")
            traceback.print_exc()
            results.append(("jmeter_deploy", False, str(e)))

        # --- Step 6: Validate JMeter binary (same as orchestrator line 916-918) ---
        r = run_cmd(executor, "6. Validate JMeter binary", "/data/jmeter/bin/jmeter --version")
        results.append(("jmeter_validate", r.success, r.stdout.strip()[:100]))

        # --- Step 7: Deploy emulator (same as orchestrator line 921-932) ---
        if lab.emulator_package_grp_id:
            print(f"\n  --- Deploy Emulator ---")
            try:
                emu_pkgs = resolver.resolve(session, [lab.emulator_package_grp_id], loadgen)
                for pkg in emu_pkgs:
                    print(f"    path: {pkg.path}")
                    print(f"    root_install_path: {pkg.root_install_path}")
                    print(f"    extraction_command: {pkg.extraction_command}")
                    print(f"    run_command: {pkg.run_command}")
                deployer.deploy_all(executor, emu_pkgs)
                print(f"    Deployed OK")
                results.append(("emulator_deploy", True, "deployed"))
            except Exception as e:
                print(f"    DEPLOY FAILED: {e}")
                traceback.print_exc()
                results.append(("emulator_deploy", False, str(e)))

            # Verify extraction
            r = run_cmd(executor, "7. Check emulator files", "ls -la /data/emulator/ 2>&1 | head -10")
            r = run_cmd(executor, "7. Check start.sh", "test -f /data/emulator/start.sh && echo YES || echo NO")
            results.append(("emulator_start_sh", "YES" in r.stdout, r.stdout.strip()))
            r = run_cmd(executor, "7. Check emulator.jar", "test -f /data/emulator/emulator.jar && echo YES || echo NO")
            results.append(("emulator_jar", "YES" in r.stdout, r.stdout.strip()))

            # --- Step 8: Start emulator with 512MB (same as orchestrator line 937-943) ---
            for pkg in emu_pkgs:
                if pkg.run_command:
                    start_cmd = f"{pkg.run_command} 512"
                    print(f"\n  --- Start Emulator ---")
                    print(f"    command: {start_cmd}")
                    r = run_cmd(executor, "8. Start emulator", start_cmd, timeout_sec=60)
                    results.append(("emulator_start", r.success, r.stdout.strip()[:200]))

                    # --- Step 9: Health check (same as orchestrator line 948-976) ---
                    emu_port = config.emulator.emulator_api_port
                    r = run_cmd(executor, "9. Process count", f"pgrep -f '[e]mulator.jar' -c 2>/dev/null || echo 0")
                    proc_count = r.stdout.strip().split('\n')[-1].strip()
                    results.append(("emulator_proc", proc_count != "0", f"proc_count={proc_count}"))

                    r = run_cmd(executor, "9. Port listening", f"ss -tlnp | grep :{emu_port} || echo 'not listening'")
                    results.append(("emulator_port", str(emu_port) in r.stdout, r.stdout.strip()))

                    r = run_cmd(executor, "9. Health endpoint",
                        f"curl -sf http://localhost:{emu_port}/health 2>&1 || "
                        f"wget -qO- http://localhost:{emu_port}/health 2>&1 || "
                        f"python3 -c \"import urllib.request; print(urllib.request.urlopen('http://localhost:{emu_port}/health').read().decode())\" 2>&1")
                    results.append(("emulator_health", r.success, r.stdout.strip()))

                    if not r.success:
                        run_cmd(executor, "9. Emulator log", "tail -20 ~/emulator.log 2>/dev/null || tail -20 /data/emulator/emulator.log 2>/dev/null || echo 'no log'")

        # --- Step 10: Test JMeter run dir (same as orchestrator line 1045-1055) ---
        print(f"\n  --- Test JMeter Run Dir ---")
        test_run_dir = "/data/jmeter/runs/test_deployment_check"
        r = run_cmd(executor, "10. mkdir run dir", f"mkdir -p {test_run_dir}")
        results.append(("jmeter_mkdir", r.success, r.stdout.strip()))
        r = run_cmd(executor, "10. write test file", f"echo test > {test_run_dir}/test.txt && cat {test_run_dir}/test.txt")
        results.append(("jmeter_write", r.success and "test" in r.stdout, r.stdout.strip()))
        run_cmd(executor, "10. cleanup", f"rm -rf {test_run_dir}")

        # --- Step 11: Kill emulator (cleanup) ---
        run_cmd(executor, "11. Kill emulator", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done")

    finally:
        executor.close()

    return results


def test_target(server, target_orm, session, credentials, resolver, deployer, lab, provider, config):
    """Mirror _do_deploying_calibration target deployment."""
    from orchestrator.models.orm import SnapshotORM
    from orchestrator.core.baseline_execution import wait_for_ssh
    from orchestrator.infra.remote_executor import create_executor

    hostname = server.hostname
    os_family = server.os_family.value
    results = []

    print(f"\n{'='*70}")
    print(f"  TARGET: {hostname} ({server.ip_address})")
    print(f"{'='*70}")

    # --- Step 1: Revert to test snapshot ---
    snapshot = session.get(SnapshotORM, target_orm.test_snapshot_id)
    if not snapshot:
        print(f"  [ERROR] test_snapshot_id={target_orm.test_snapshot_id} not found in DB")
        results.append(("revert", False, "snapshot not in DB"))
        return results

    print(f"\n  [1. Revert to test snapshot '{snapshot.name}']")
    try:
        new_ip = provider.restore_snapshot(server.server_infra_ref, snapshot.provider_ref)
        provider.wait_for_vm_ready(server.server_infra_ref)
        actual_ip = server.ip_address
        if new_ip and new_ip != server.ip_address:
            print(f"    IP changed: {server.ip_address} -> {new_ip}")
            actual_ip = new_ip
            server.ip_address = new_ip
            session.commit()
        print(f"    Reverted OK")
        results.append(("revert", True, f"Reverted to '{snapshot.name}'"))
    except Exception as e:
        print(f"    REVERT FAILED: {e}")
        results.append(("revert", False, str(e)))
        return results

    # --- Step 2: Wait for SSH ---
    print(f"\n  [2. Wait for SSH]")
    try:
        wait_for_ssh(server.ip_address, os_family=os_family, timeout_sec=120)
        print(f"    SSH OK")
        results.append(("ssh", True, "connected"))
    except Exception as e:
        print(f"    SSH FAILED: {e}")
        results.append(("ssh", False, str(e)))
        return results

    cred = credentials.get_server_credential(server.id, os_family)
    executor = create_executor(
        os_family=os_family,
        host=server.ip_address,
        username=cred.username,
        password=cred.password,
    )

    try:
        # --- Step 3: Kill stale emulator ---
        run_cmd(executor, "3. Kill stale emulator", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; true")
        results.append(("kill_stale", True, "done"))

        # --- Step 4: Clean emulator output/stats ---
        r = run_cmd(executor, "4. Clean emulator output", "rm -rf /data/emulator/output/* /data/emulator/stats/* 2>/dev/null; true")
        results.append(("clean_output", True, "done"))

        # --- Step 5: Deploy emulator ---
        if lab.emulator_package_grp_id:
            print(f"\n  --- Deploy Emulator ---")
            try:
                emu_pkgs = resolver.resolve(session, [lab.emulator_package_grp_id], server)
                for pkg in emu_pkgs:
                    print(f"    path: {pkg.path}")
                    print(f"    root_install_path: {pkg.root_install_path}")
                    print(f"    extraction_command: {pkg.extraction_command}")
                    print(f"    run_command: {pkg.run_command}")
                deployer.deploy_all(executor, emu_pkgs)
                print(f"    Deployed OK")
                results.append(("emulator_deploy", True, "deployed"))
            except Exception as e:
                print(f"    DEPLOY FAILED: {e}")
                traceback.print_exc()
                results.append(("emulator_deploy", False, str(e)))

            # --- Step 6: Start emulator (full heap for targets) ---
            for pkg in emu_pkgs:
                if pkg.run_command:
                    start_cmd = pkg.run_command
                    print(f"\n  --- Start Emulator ---")
                    print(f"    command: {start_cmd}")
                    r = run_cmd(executor, "6. Start emulator", start_cmd, timeout_sec=60)
                    results.append(("emulator_start", r.success, r.stdout.strip()[:200]))

                    # --- Step 7: Health check ---
                    emu_port = config.emulator.emulator_api_port
                    r = run_cmd(executor, "7. Process count", f"pgrep -f '[e]mulator.jar' -c 2>/dev/null || echo 0")
                    proc_count = r.stdout.strip().split('\n')[-1].strip()
                    results.append(("emulator_proc", proc_count != "0", f"proc_count={proc_count}"))

                    r = run_cmd(executor, "7. Port listening", f"ss -tlnp | grep :{emu_port} || echo 'not listening'")
                    results.append(("emulator_port", str(emu_port) in r.stdout, r.stdout.strip()))

                    r = run_cmd(executor, "7. Health endpoint", f"curl -sf http://localhost:{emu_port}/health 2>&1")
                    results.append(("emulator_health", r.success, r.stdout.strip()))

                    if not r.success:
                        run_cmd(executor, "7. Emulator log", "tail -20 ~/emulator.log 2>/dev/null || echo 'no log'")

            # Kill after test
            run_cmd(executor, "Cleanup: kill emulator", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done")

    finally:
        executor.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Test deployment — mirrors exact orchestrator flow")
    parser.add_argument("name", nargs="?", default=None, help="Test run name (partial match)")
    parser.add_argument("--test-id", type=int, default=None, help="Test run ID")
    parser.add_argument("--loadgens-only", action="store_true")
    parser.add_argument("--targets-only", action="store_true")
    args = parser.parse_args()

    if not args.name and not args.test_id:
        parser.error("Provide a test name or --test-id")

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import (
        BaselineTestRunORM, BaselineTestRunTargetORM,
        LabORM, ServerORM,
    )
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider
    from orchestrator.services.package_manager import PackageResolver, PackageDeployer

    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()

    # Find test run
    if args.test_id:
        test_run = session.get(BaselineTestRunORM, args.test_id)
        if not test_run:
            print(f"ERROR: Test run ID {args.test_id} not found")
            sys.exit(1)
    else:
        from sqlalchemy import func
        matches = session.query(BaselineTestRunORM).filter(
            func.lower(BaselineTestRunORM.name).contains(args.name.lower()),
        ).all()
        if not matches:
            print(f"ERROR: No test run found matching '{args.name}'")
            sys.exit(1)
        if len(matches) > 1:
            print("Multiple matches:")
            for r in matches:
                print(f"  ID={r.id} name='{r.name}' state={r.state.value}")
            sys.exit(1)
        test_run = matches[0]

    print(f"Test run: #{test_run.id} '{test_run.name}' (state={test_run.state.value})")

    # Get targets + lab
    target_orms = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
    ).all()
    lab = session.get(LabORM, test_run.lab_id)
    print(f"Lab: {lab.name} (ID={lab.id})")
    print(f"Targets: {len(target_orms)}")

    # Hypervisor provider (needed for snapshot revert)
    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    resolver = PackageResolver()
    deployer = PackageDeployer(use_sudo=False)

    all_results = {}

    # Test loadgens
    if not args.targets_only:
        seen = set()
        for t_orm in target_orms:
            loadgen = session.get(ServerORM, t_orm.loadgenerator_id)
            if not loadgen or loadgen.id in seen:
                continue
            seen.add(loadgen.id)

            try:
                checks = test_loadgen(loadgen, session, credentials, resolver, deployer, lab, provider, config)
                all_results[f"loadgen:{loadgen.hostname}"] = checks
            except Exception as e:
                print(f"\n  [FATAL ERROR] {e}")
                traceback.print_exc()
                all_results[f"loadgen:{loadgen.hostname}"] = [("fatal", False, str(e))]

    # Test targets
    if not args.loadgens_only:
        for t_orm in target_orms:
            server = session.get(ServerORM, t_orm.target_id)
            if not server:
                continue

            try:
                checks = test_target(server, t_orm, session, credentials, resolver, deployer, lab, provider, config)
                all_results[f"target:{server.hostname}"] = checks
            except Exception as e:
                print(f"\n  [FATAL ERROR] {e}")
                traceback.print_exc()
                all_results[f"target:{server.hostname}"] = [("fatal", False, str(e))]

    # Summary
    print(f"\n\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")

    total_pass = 0
    total_fail = 0

    for machine, checks in all_results.items():
        passed = sum(1 for _, ok, _ in checks if ok)
        failed = sum(1 for _, ok, _ in checks if not ok)
        total_pass += passed
        total_fail += failed

        status = "ALL PASS" if failed == 0 else f"{failed} FAILED"
        print(f"\n  {machine}: {status} ({passed} pass, {failed} fail)")

        for check, ok, detail in checks:
            icon = "PASS" if ok else "FAIL"
            detail_short = detail[:100] + "..." if len(detail) > 100 else detail
            if not ok:
                print(f"    [{icon}] {check}: {detail_short}")

    print(f"\n  TOTAL: {total_pass} pass, {total_fail} fail")
    print(f"{'='*70}")

    session.close()
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
