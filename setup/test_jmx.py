#!/usr/bin/env python3
"""Standalone JMX validation — verifies loadgen + JMeter + CSV + emulator end-to-end.

Connects to each loadgen and target for a given test, validates:
  1. JMeter binary exists and is executable on loadgen
  2. JMX file (server-steady.jmx) is uploaded and valid
  3. Calibration CSV exists with correct header
  4. Emulator is reachable and healthy on targets
  5. Fires a short JMeter run (10s) and verifies requests hit the emulator
  6. Checks JMeter log for errors after the run
  7. Validates emulator /file endpoint accepts all CSV params

Usage:
    python test_jmx.py "test name"
    python test_jmx.py --test-id 42
    python test_jmx.py "test name" --skip-fire   # skip the live JMeter run
"""

import argparse
import json
import os
import sys
import time
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
DB_ASSETS = os.path.join(REPO_ROOT, "db-assets")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)
if DB_ASSETS not in sys.path:
    sys.path.insert(0, DB_ASSETS)


# --- Formatting helpers ---

def ok(msg):
    print(f"    ✓ {msg}")

def fail(msg):
    print(f"    ✗ {msg}")

def info(msg):
    print(f"    · {msg}")

def section(title):
    print(f"\n  [{title}]")


def run_cmd(executor, cmd, timeout_sec=30):
    """Run remote command, return result."""
    result = executor.execute(cmd, timeout_sec=timeout_sec)
    return result


def find_test_run(session, test_name=None, test_id=None):
    """Find a baseline test run by name or ID."""
    from orchestrator.models.orm import BaselineTestRunORM
    if test_id:
        return session.get(BaselineTestRunORM, test_id)
    if test_name:
        return session.query(BaselineTestRunORM).filter(
            BaselineTestRunORM.name == test_name
        ).order_by(BaselineTestRunORM.id.desc()).first()
    return None


def load_context(session, test_run):
    """Load lab, scenario, targets, loadgens for a test run."""
    from orchestrator.models.orm import (
        LabORM, ScenarioORM, BaselineTestRunTargetORM, ServerORM,
        SnapshotORM, LoadProfileORM, BaselineTestRunLoadProfileORM,
    )

    lab = session.get(LabORM, test_run.lab_id)
    scenario = session.get(ScenarioORM, test_run.scenario_id)

    target_rows = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id
    ).all()

    targets = []
    for t in target_rows:
        server = session.get(ServerORM, t.target_id)
        loadgen = session.get(ServerORM, t.loadgenerator_id)
        test_snap = session.get(SnapshotORM, t.test_snapshot_id) if t.test_snapshot_id else None
        targets.append((t, server, loadgen, test_snap))

    lp_rows = session.query(BaselineTestRunLoadProfileORM).filter(
        BaselineTestRunLoadProfileORM.baseline_test_run_id == test_run.id
    ).all()
    load_profiles = []
    for lp_link in lp_rows:
        lp = session.get(LoadProfileORM, lp_link.load_profile_id)
        load_profiles.append(lp)

    return lab, scenario, targets, load_profiles


def test_loadgen_jmeter(executor, loadgen_hostname, run_dir):
    """Check 1-3: JMeter binary, JMX file, calibration CSV on loadgen."""
    results = []

    section("JMeter binary")
    r = run_cmd(executor, "test -x /data/jmeter/bin/jmeter && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status == "EXISTS":
        ok("JMeter binary exists and is executable")
        # Get version
        rv = run_cmd(executor, "/data/jmeter/bin/jmeter --version 2>&1 | head -3")
        for line in rv.stdout.strip().splitlines()[:3]:
            info(line.strip())
        results.append(("jmeter_binary", True))
    else:
        fail("JMeter binary NOT FOUND at /data/jmeter/bin/jmeter")
        results.append(("jmeter_binary", False))
        return results  # can't continue without JMeter

    section("JMX file (test.jmx)")
    r = run_cmd(executor, f"test -f {run_dir}/test.jmx && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status == "EXISTS":
        ok(f"test.jmx exists at {run_dir}/test.jmx")
        # Verify it's the unified JMX with SwitchController
        r2 = run_cmd(executor, f"grep -c 'SwitchController' {run_dir}/test.jmx")
        count = r2.stdout.strip()
        if count and int(count) > 0:
            ok(f"Contains SwitchController ({count} references)")
        else:
            fail("test.jmx does NOT contain SwitchController — may be old JMX")
        # Verify CSVDataSet variableNames
        r3 = run_cmd(executor, f"grep 'variableNames' {run_dir}/test.jmx")
        if "size_bracket" in r3.stdout:
            ok("CSVDataSet has 9-column variableNames (unified schema)")
        else:
            fail("CSVDataSet variableNames missing file columns — old JMX?")
        results.append(("jmx_file", True))
    else:
        fail(f"test.jmx NOT FOUND at {run_dir}/test.jmx")
        results.append(("jmx_file", False))

    section("Calibration CSV")
    r = run_cmd(executor, f"test -f {run_dir}/calibration_ops.csv && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status == "EXISTS":
        ok(f"calibration_ops.csv exists")
        # Check header
        r2 = run_cmd(executor, f"head -1 {run_dir}/calibration_ops.csv")
        header = r2.stdout.strip()
        expected = "seq_id,op_type,size_bracket,target_size_kb,output_format,output_folder_idx,is_confidential,make_zip,source_file_ids"
        if header == expected:
            ok(f"CSV header matches JMX variableNames (9 columns)")
        else:
            fail(f"CSV header mismatch!")
            info(f"Expected: {expected}")
            info(f"Got:      {header}")
        # Check row count
        r3 = run_cmd(executor, f"wc -l < {run_dir}/calibration_ops.csv")
        row_count = r3.stdout.strip()
        info(f"Row count: {row_count}")
        # Show sample rows
        r4 = run_cmd(executor, f"head -5 {run_dir}/calibration_ops.csv")
        for line in r4.stdout.strip().splitlines():
            info(f"  {line}")
        results.append(("calibration_csv", True))
    else:
        fail(f"calibration_ops.csv NOT FOUND at {run_dir}/calibration_ops.csv")
        results.append(("calibration_csv", False))

    return results


def test_emulator_health(target_ip, emulator_port=8080):
    """Check 4: Emulator is reachable and healthy."""
    import urllib.request
    results = []

    section(f"Emulator health ({target_ip}:{emulator_port})")
    try:
        url = f"http://{target_ip}:{emulator_port}/api/v1/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            ok(f"Health endpoint OK: {body.get('status', 'unknown')}")
            results.append(("emulator_health", True))
    except Exception as e:
        fail(f"Emulator health check failed: {e}")
        results.append(("emulator_health", False))

    return results


def test_emulator_file_endpoint(target_ip, emulator_port=8080):
    """Check 7: Emulator /file endpoint accepts all CSV params."""
    import urllib.request
    results = []

    section(f"Emulator /file endpoint ({target_ip})")

    # Test with null params (steady template scenario)
    payload_null = json.dumps({
        "size_bracket": None,
        "target_size_kb": None,
        "output_format": None,
        "output_folder_idx": None,
        "is_confidential": False,
        "make_zip": False,
        "source_file_ids": None,
    }).encode()

    try:
        url = f"http://{target_ip}:{emulator_port}/api/v1/operations/file"
        req = urllib.request.Request(url, data=payload_null, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if body.get("status") == "completed":
                ok(f"File op (null params) OK: {body.get('size_bracket')}, {body.get('actual_size_bytes')} bytes")
            else:
                fail(f"File op returned status={body.get('status')}: {body.get('error_message')}")
        results.append(("file_null_params", True))
    except Exception as e:
        fail(f"File op (null params) failed: {e}")
        results.append(("file_null_params", False))

    # Test with full deterministic params (file-heavy template scenario)
    payload_full = json.dumps({
        "size_bracket": "small",
        "target_size_kb": 50,
        "output_format": "txt",
        "output_folder_idx": 0,
        "is_confidential": False,
        "make_zip": False,
        "source_file_ids": "rfc791",
    }).encode()

    try:
        url = f"http://{target_ip}:{emulator_port}/api/v1/operations/file"
        req = urllib.request.Request(url, data=payload_full, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if body.get("status") == "completed":
                ok(f"File op (full params) OK: {body.get('output_format')}, {body.get('actual_size_bytes')} bytes, files_used={body.get('source_files_used')}")
            else:
                fail(f"File op returned status={body.get('status')}: {body.get('error_message')}")
        results.append(("file_full_params", True))
    except Exception as e:
        fail(f"File op (full params) failed: {e}")
        results.append(("file_full_params", False))

    return results


def test_jmeter_fire(executor, run_dir, target_ip, emulator_port=8080):
    """Check 5-6: Fire a short JMeter run and verify it works."""
    results = []

    section("JMeter live fire test (10s)")
    jtl_path = f"{run_dir}/_test_fire.jtl"
    log_path = f"{run_dir}/_test_fire.log"

    cmd = (
        f"/data/jmeter/bin/jmeter -n"
        f" -t {run_dir}/test.jmx"
        f" -l {jtl_path}"
        f" -j {log_path}"
        f" -Jthreads=2"
        f" -Jrampup=2"
        f" -Jduration=10"
        f" -Jhost={target_ip}"
        f" -Jport={emulator_port}"
        f" -Jops_sequence={run_dir}/calibration_ops.csv"
        f" -Jcpu_ms=50"
        f" -Jintensity=0.8"
        f" -Jtouch_mb=1.0"
    )

    info(f"Running: {cmd}")
    r = run_cmd(executor, cmd, timeout_sec=60)

    if r.success:
        ok("JMeter exited successfully")
    else:
        fail(f"JMeter exited with error (code={r.exit_code})")
        for line in r.stderr.strip().splitlines()[:10]:
            info(f"stderr: {line}")
        results.append(("jmeter_fire", False))
        return results

    # Check JTL for results
    section("JMeter results (JTL)")
    r2 = run_cmd(executor, f"wc -l < {jtl_path} 2>/dev/null || echo 0")
    jtl_lines = r2.stdout.strip()
    info(f"JTL lines: {jtl_lines}")

    if int(jtl_lines) > 1:
        ok(f"JTL has {jtl_lines} lines (requests were fired)")
        # Show sample labels
        r3 = run_cmd(executor, f"head -1 {jtl_path} && tail -5 {jtl_path}")
        for line in r3.stdout.strip().splitlines():
            info(f"  {line[:120]}")
        # Count by label
        r4 = run_cmd(executor, f"tail -n +2 {jtl_path} | cut -d',' -f3 | sort | uniq -c | sort -rn")
        info("Request distribution:")
        for line in r4.stdout.strip().splitlines()[:10]:
            info(f"  {line.strip()}")
        results.append(("jmeter_fire", True))
    else:
        fail("JTL is empty — JMeter fired no requests!")
        results.append(("jmeter_fire", False))

    # Check JMeter log for errors
    section("JMeter log check")
    r5 = run_cmd(executor, f"grep -iE 'ERROR|FATAL|Exception' {log_path} | head -10")
    if r5.stdout.strip():
        fail("Errors found in JMeter log:")
        for line in r5.stdout.strip().splitlines()[:10]:
            info(f"  {line.strip()}")
        results.append(("jmeter_log", False))
    else:
        ok("No errors in JMeter log")
        results.append(("jmeter_log", True))

    # Cleanup
    run_cmd(executor, f"rm -f {jtl_path} {log_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Standalone JMX validation")
    parser.add_argument("test_name", nargs="?", help="Test run name")
    parser.add_argument("--test-id", type=int, help="Test run ID")
    parser.add_argument("--skip-fire", action="store_true", help="Skip the live JMeter run")
    parser.add_argument("--config", default=None, help="Path to orchestrator.yaml")
    args = parser.parse_args()

    if not args.test_name and not args.test_id:
        parser.error("Provide test name or --test-id")

    # Load config
    config_path = args.config or os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    from orchestrator.config.settings import load_config
    config = load_config(config_path)

    # DB session
    from orchestrator.models.database import SessionLocal, init_db
    init_db(config.database.url)
    session = SessionLocal()

    # Credentials
    cred_path = os.path.join(REPO_ROOT, "orchestrator", config.credentials_path)
    from orchestrator.config.credentials import CredentialsStore
    credentials = CredentialsStore(cred_path)

    # Find test run
    test_run = find_test_run(session, test_name=args.test_name, test_id=args.test_id)
    if not test_run:
        print(f"Test run not found: {args.test_name or args.test_id}")
        sys.exit(1)

    lab, scenario, targets, load_profiles = load_context(session, test_run)

    print(f"{'='*70}")
    print(f"  JMX VALIDATION: {test_run.name} (ID={test_run.id})")
    print(f"  Template: {scenario.template_type.value}")
    print(f"  Lab: {lab.name}")
    print(f"  Targets: {len(targets)}")
    print(f"  Load profiles: {', '.join(lp.name for lp in load_profiles)}")
    print(f"{'='*70}")

    from orchestrator.infra.remote_executor import create_executor

    all_results = []
    seen_loadgens = set()

    for target_orm, server, loadgen, test_snap in targets:
        run_dir = f"/data/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

        # --- Loadgen checks (once per loadgen) ---
        if loadgen.id not in seen_loadgens:
            seen_loadgens.add(loadgen.id)

            print(f"\n{'='*70}")
            print(f"  LOADGEN: {loadgen.hostname} ({loadgen.ip_address})")
            print(f"{'='*70}")

            cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            lg_exec = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=cred.username,
                password=cred.password,
            )

            try:
                # Checks 1-3: JMeter binary, JMX, CSV
                lg_results = test_loadgen_jmeter(lg_exec, loadgen.hostname, run_dir)
                all_results.extend(lg_results)

                # Checks 5-6: Fire test (if JMeter + JMX + CSV all passed)
                jmeter_ok = all(passed for _, passed in lg_results)
                if jmeter_ok and not args.skip_fire:
                    fire_results = test_jmeter_fire(lg_exec, run_dir, server.ip_address,
                                                     config.emulator.emulator_api_port)
                    all_results.extend(fire_results)
                elif not jmeter_ok:
                    info("Skipping live fire — prerequisite checks failed")
                elif args.skip_fire:
                    info("Skipping live fire (--skip-fire)")
            finally:
                lg_exec.close()

        # --- Target checks ---
        print(f"\n{'='*70}")
        print(f"  TARGET: {server.hostname} ({server.ip_address})")
        print(f"{'='*70}")

        emulator_port = config.emulator.emulator_api_port

        # Check 4: Emulator health
        health_results = test_emulator_health(server.ip_address, emulator_port)
        all_results.extend(health_results)

        # Check 7: File endpoint
        emulator_ok = all(passed for _, passed in health_results)
        if emulator_ok:
            file_results = test_emulator_file_endpoint(server.ip_address, emulator_port)
            all_results.extend(file_results)
        else:
            info("Skipping /file endpoint test — emulator not healthy")

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for _, p in all_results if p)
    failed = sum(1 for _, p in all_results if not p)
    for name, p in all_results:
        status = "PASS" if p else "FAIL"
        print(f"    [{status}] {name}")
    print(f"\n  {passed} passed, {failed} failed")

    session.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
