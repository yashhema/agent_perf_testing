#!/usr/bin/env python3
"""Standalone deployment test — uses orchestrator code to test every step.

Connects to DB, reads package configs, SSHes into each machine, and runs
every deployment step with full output. Does NOT modify snapshots or test state.

Usage:
    python test_deployment.py "test name"
    python test_deployment.py --test-id 42
    python test_deployment.py --test-id 42 --targets-only
    python test_deployment.py --test-id 42 --loadgens-only
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


def run_cmd(executor, desc, cmd):
    """Run a command, print everything, return result."""
    print(f"\n  [{desc}]")
    print(f"    cmd: {cmd}")
    result = executor.execute(cmd)
    if result.stdout.strip():
        print(f"    stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        print(f"    stderr: {result.stderr.strip()}")
    print(f"    exit_code: {result.exit_code}  success: {result.success}")
    return result


def test_one_machine(label, server, executor, session, credentials, resolver, deployer, lab, is_loadgen=False):
    """Test deployment on one machine. Returns list of (check, pass/fail, detail)."""
    results = []
    os_family = server.os_family.value
    hostname = server.hostname

    print(f"\n{'='*70}")
    print(f"  {label}: {hostname} ({server.ip_address}) — {os_family}")
    print(f"{'='*70}")

    # 1. Basic connectivity
    r = run_cmd(executor, "whoami", "whoami")
    results.append(("whoami", r.success, r.stdout.strip()))

    # 2. Passwordless sudo
    r = run_cmd(executor, "sudo check", "sudo -n whoami 2>&1")
    has_sudo = r.success and "root" in r.stdout
    results.append(("passwordless_sudo", has_sudo, r.stdout.strip()))

    # 3. Java version
    r = run_cmd(executor, "java version", "java -version 2>&1 | head -1")
    results.append(("java_version", r.success, r.stdout.strip()))

    # 4. Check /data mount
    r = run_cmd(executor, "/data mounted", "mountpoint -q /data && echo MOUNTED || echo NOTMOUNTED")
    mounted = "MOUNTED" in r.stdout
    results.append(("data_mount", mounted, r.stdout.strip()))

    # 5. Check /data ownership and permissions
    r = run_cmd(executor, "/data permissions", "ls -la /data/ 2>&1 | head -10")
    results.append(("data_permissions", r.success, r.stdout.strip()))

    # 6. Check /data disk space
    r = run_cmd(executor, "/data disk space", "df -h /data 2>&1 | tail -1")
    results.append(("data_space", r.success, r.stdout.strip()))

    # 7. Firewall port 8080
    r = run_cmd(executor, "firewall 8080",
        "sudo firewall-cmd --list-ports 2>/dev/null | grep -q 8080 && echo OPEN || "
        "sudo iptables -C INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null && echo OPEN || echo CLOSED")
    fw_open = "OPEN" in r.stdout
    results.append(("firewall_8080", fw_open, r.stdout.strip()))

    # 8. Test write to /data
    r = run_cmd(executor, "write test", "echo test > /data/_write_test && rm /data/_write_test && echo OK || echo FAIL")
    results.append(("data_writable", "OK" in r.stdout, r.stdout.strip()))

    # 9. Check output folders
    for folder in ["/data/output1", "/data/output2", "/data/output3"]:
        r = run_cmd(executor, f"folder {folder}", f"test -d {folder} && echo EXISTS || echo MISSING")
        results.append((f"folder_{folder}", "EXISTS" in r.stdout, r.stdout.strip()))

    # 10. Resolve packages from DB
    print(f"\n  --- Package Resolution ---")
    try:
        jmeter_pkgs = resolver.resolve(session, [lab.jmeter_package_grpid], server)
        for pkg in jmeter_pkgs:
            print(f"    JMeter package:")
            print(f"      path: {pkg.path}")
            print(f"      root_install_path: {pkg.root_install_path}")
            print(f"      extraction_command: {pkg.extraction_command}")
            print(f"      run_command: {pkg.run_command}")
            print(f"      status_command: {pkg.status_command}")
            print(f"      prereq_script: {pkg.prereq_script}")
        results.append(("jmeter_resolve", True, f"{len(jmeter_pkgs)} package(s)"))
    except Exception as e:
        print(f"    JMeter resolve FAILED: {e}")
        results.append(("jmeter_resolve", False, str(e)))

    if lab.emulator_package_grp_id:
        try:
            emu_pkgs = resolver.resolve(session, [lab.emulator_package_grp_id], server)
            for pkg in emu_pkgs:
                print(f"    Emulator package:")
                print(f"      path: {pkg.path}")
                print(f"      root_install_path: {pkg.root_install_path}")
                print(f"      extraction_command: {pkg.extraction_command}")
                print(f"      run_command: {pkg.run_command}")
                print(f"      status_command: {pkg.status_command}")
                print(f"      prereq_script: {pkg.prereq_script}")
            results.append(("emulator_resolve", True, f"{len(emu_pkgs)} package(s)"))
        except Exception as e:
            print(f"    Emulator resolve FAILED: {e}")
            results.append(("emulator_resolve", False, str(e)))

    # 11. Check if local package files exist on orchestrator
    print(f"\n  --- Local Package Files ---")
    artifacts_dir = os.path.join(REPO_ROOT, "orchestrator", "artifacts")
    for pkg_type, grp_ids in [("jmeter", [lab.jmeter_package_grpid]),
                               ("emulator", [lab.emulator_package_grp_id] if lab.emulator_package_grp_id else [])]:
        try:
            pkgs = resolver.resolve(session, grp_ids, server) if grp_ids else []
            for pkg in pkgs:
                local_file = os.path.join(REPO_ROOT, "orchestrator", pkg.path)
                exists = os.path.isfile(local_file)
                size = os.path.getsize(local_file) if exists else 0
                print(f"    {pkg_type}: {local_file}")
                print(f"      exists: {exists}, size: {size} bytes")
                results.append((f"{pkg_type}_local_file", exists, f"{size} bytes"))
        except Exception:
            pass

    # 12. Test deployment (upload + extract) without starting
    print(f"\n  --- Test Deploy (upload + extract) ---")
    for pkg_type, grp_ids in [("jmeter", [lab.jmeter_package_grpid]),
                               ("emulator", [lab.emulator_package_grp_id] if lab.emulator_package_grp_id else [])]:
        try:
            pkgs = resolver.resolve(session, grp_ids, server) if grp_ids else []
            for pkg in pkgs:
                print(f"\n    Deploying {pkg_type}...")
                print(f"      upload to: {pkg.root_install_path}")
                print(f"      extract: {pkg.extraction_command}")
                deployer.deploy(executor, pkg)
                print(f"    [OK] {pkg_type} deployed successfully")
                results.append((f"{pkg_type}_deploy", True, "deployed"))

                # Verify extraction result
                if pkg_type == "jmeter":
                    r = run_cmd(executor, "jmeter binary check", "ls -la /data/jmeter/bin/jmeter 2>&1")
                    results.append(("jmeter_binary", r.success, r.stdout.strip()))
                    r = run_cmd(executor, "jmeter version", "/data/jmeter/bin/jmeter --version 2>&1 | head -3")
                    results.append(("jmeter_version", r.success, r.stdout.strip()))
                elif pkg_type == "emulator":
                    r = run_cmd(executor, "emulator files", "ls -la /data/emulator/ 2>&1 | head -10")
                    results.append(("emulator_files", r.success, r.stdout.strip()))
                    r = run_cmd(executor, "start.sh exists", "test -f /data/emulator/start.sh && echo YES || echo NO")
                    results.append(("start_sh_exists", "YES" in r.stdout, r.stdout.strip()))
                    r = run_cmd(executor, "emulator.jar exists", "test -f /data/emulator/emulator.jar && echo YES || echo NO")
                    results.append(("emulator_jar_exists", "YES" in r.stdout, r.stdout.strip()))
        except Exception as e:
            print(f"    [FAIL] {pkg_type} deploy failed: {e}")
            traceback.print_exc()
            results.append((f"{pkg_type}_deploy", False, str(e)))

    # 13. Test emulator start (loadgen: 512MB, target: auto)
    if lab.emulator_package_grp_id:
        print(f"\n  --- Test Emulator Start ---")
        try:
            pkgs = resolver.resolve(session, [lab.emulator_package_grp_id], server)
            for pkg in pkgs:
                if pkg.run_command:
                    if is_loadgen:
                        start_cmd = f"{pkg.run_command} 512"
                    else:
                        start_cmd = pkg.run_command
                    print(f"    run_command: {start_cmd}")
                    r = run_cmd(executor, "start emulator", start_cmd)
                    results.append(("emulator_start", r.success, r.stdout.strip()[:200]))

                    if r.success:
                        # Health check
                        r = run_cmd(executor, "health check", "curl -sf http://localhost:8080/health 2>&1")
                        results.append(("emulator_health", r.success, r.stdout.strip()))

                        # Process check
                        r = run_cmd(executor, "process check", "pgrep -f '[e]mulator.jar' -c 2>/dev/null || echo 0")
                        results.append(("emulator_process", r.stdout.strip() != "0", r.stdout.strip()))

                        # Port check
                        r = run_cmd(executor, "port check", "ss -tlnp | grep :8080 || echo 'not listening'")
                        results.append(("emulator_port", "8080" in r.stdout, r.stdout.strip()))

                        # Log check
                        r = run_cmd(executor, "emulator log", "tail -5 ~/emulator.log 2>/dev/null || echo 'no log'")
                        results.append(("emulator_log", True, r.stdout.strip()[:200]))

                        # Kill it after test
                        run_cmd(executor, "kill emulator", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done")
        except Exception as e:
            print(f"    [FAIL] {e}")
            traceback.print_exc()
            results.append(("emulator_start", False, str(e)))

    # 14. Test JMeter run dir creation + file upload
    if is_loadgen:
        print(f"\n  --- Test JMeter Run Dir ---")
        test_dir = "/data/jmeter/runs/test_deployment_check"
        r = run_cmd(executor, "create run dir", f"mkdir -p {test_dir}")
        results.append(("jmeter_mkdir", r.success, r.stdout.strip()))
        r = run_cmd(executor, "write to run dir", f"echo test > {test_dir}/test.txt && cat {test_dir}/test.txt")
        results.append(("jmeter_write", r.success and "test" in r.stdout, r.stdout.strip()))
        run_cmd(executor, "cleanup", f"rm -rf {test_dir}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Test deployment on all machines for a test run")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("name", nargs="?", default=None, help="Test run name")
    group.add_argument("--test-id", type=int, default=None, help="Test run ID")
    parser.add_argument("--loadgens-only", action="store_true")
    parser.add_argument("--targets-only", action="store_true")
    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import (
        BaselineTestRunORM, BaselineTestRunTargetORM,
        LabORM, ServerORM,
    )
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.remote_executor import create_executor
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
        results = session.query(BaselineTestRunORM).filter(
            func.lower(BaselineTestRunORM.name).contains(args.name.lower()),
        ).all()
        if not results:
            print(f"ERROR: No test run found matching '{args.name}'")
            sys.exit(1)
        if len(results) > 1:
            print("Multiple matches:")
            for r in results:
                print(f"  ID={r.id} name='{r.name}' state={r.state.value}")
            sys.exit(1)
        test_run = results[0]

    print(f"Test run: #{test_run.id} '{test_run.name}' (state={test_run.state.value})")

    # Get targets + lab
    target_orms = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
    ).all()
    lab = session.get(LabORM, test_run.lab_id)
    print(f"Lab: {lab.name} (ID={lab.id})")
    print(f"Targets: {len(target_orms)}")

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
                cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                try:
                    checks = test_one_machine(
                        f"Loadgen", loadgen, executor, session, credentials,
                        resolver, deployer, lab, is_loadgen=True,
                    )
                    all_results[f"loadgen:{loadgen.hostname}"] = checks
                finally:
                    executor.close()
            except Exception as e:
                print(f"\n  [ERROR] Cannot connect to loadgen {loadgen.hostname}: {e}")
                all_results[f"loadgen:{loadgen.hostname}"] = [("connect", False, str(e))]

    # Test targets
    if not args.loadgens_only:
        for t_orm in target_orms:
            server = session.get(ServerORM, t_orm.target_id)
            if not server:
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
                    checks = test_one_machine(
                        f"Target", server, executor, session, credentials,
                        resolver, deployer, lab, is_loadgen=False,
                    )
                    all_results[f"target:{server.hostname}"] = checks
                finally:
                    executor.close()
            except Exception as e:
                print(f"\n  [ERROR] Cannot connect to target {server.hostname}: {e}")
                all_results[f"target:{server.hostname}"] = [("connect", False, str(e))]

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
            # Truncate long details
            detail_short = detail[:80] + "..." if len(detail) > 80 else detail
            if not ok:
                print(f"    [{icon}] {check}: {detail_short}")

    print(f"\n  TOTAL: {total_pass} pass, {total_fail} fail")
    print(f"{'='*70}")

    session.close()
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
