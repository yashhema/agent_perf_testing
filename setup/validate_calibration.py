#!/usr/bin/env python3
"""Validate calibration setup for a test run — SSHs into machines, checks everything.

Connects to the actual loadgen and target for a test run and validates:
  1. JMX file on loadgen: SwitchController, think_ms, ignoreFirstLine, cpu_ms default
  2. CSV on loadgen: header, row count, op_type distribution
  3. Emulator on target: health, config (output_folders, partner, pool)
  4. JMeter on loadgen: binary, running processes, recent JTL/logs
  5. Emulator stats: is collecting, sample count, recent CPU values
  6. CalibrationResult in DB: status, thread_count, phase, message
  7. JMeter command reconstruction: what -J params would be sent

Usage:
    python validate_calibration.py "test name"
    python validate_calibration.py --test-id 8
    python validate_calibration.py "test name" --check-running   # also check live JMeter processes
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def ok(msg):
    print(f"    [OK] {msg}")

def fail(msg):
    print(f"    [FAIL] {msg}")

def warn(msg):
    print(f"    [WARN] {msg}")

def info(msg):
    print(f"    {msg}")

def section(title):
    print(f"\n  === {title} ===")

def run_cmd(executor, cmd, timeout_sec=30):
    result = executor.execute(cmd, timeout_sec=timeout_sec)
    return result

def http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def find_test_run(session, test_name=None, test_id=None):
    from orchestrator.models.orm import BaselineTestRunORM
    if test_id:
        return session.get(BaselineTestRunORM, test_id)
    if test_name:
        return session.query(BaselineTestRunORM).filter(
            BaselineTestRunORM.name == test_name
        ).order_by(BaselineTestRunORM.id.desc()).first()
    return None


def load_context(session, test_run):
    from orchestrator.models.orm import (
        LabORM, ScenarioORM, BaselineTestRunTargetORM, ServerORM,
        SnapshotORM, LoadProfileORM, BaselineTestRunLoadProfileORM,
        CalibrationResultORM,
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

    # Calibration results
    cal_results = session.query(CalibrationResultORM).filter(
        CalibrationResultORM.baseline_test_run_id == test_run.id
    ).all()

    return lab, scenario, targets, load_profiles, cal_results


def validate_jmx_on_loadgen(executor, run_dir):
    """Check JMX file content on the loadgen."""
    section("JMX on loadgen")

    jmx_path = f"{run_dir}/test.jmx"
    r = run_cmd(executor, f"test -f {jmx_path} && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status != "EXISTS":
        fail(f"JMX not found: {jmx_path}")
        return

    ok(f"JMX exists: {jmx_path}")

    # Check SwitchController
    r = run_cmd(executor, f"grep -c 'SwitchController' {jmx_path}")
    count = r.stdout.strip()
    if count and int(count) > 0:
        ok(f"SwitchController present ({count} refs)")
    else:
        fail("SwitchController MISSING — old JMX!")

    # Check think_ms property
    r = run_cmd(executor, f"grep 'think_ms' {jmx_path}")
    if "think_ms" in r.stdout:
        if "think_ms,100" in r.stdout:
            ok("think_ms default = 100ms")
        elif "think_ms,500" in r.stdout:
            fail("think_ms default = 500ms — OLD JMX! Should be 100ms")
        else:
            info(f"think_ms line: {r.stdout.strip()}")
    else:
        fail("think_ms NOT a property — hardcoded 500ms think time")

    # Check ignoreFirstLine
    r = run_cmd(executor, f"grep 'ignoreFirstLine' {jmx_path}")
    if "true" in r.stdout.lower():
        ok("ignoreFirstLine = true")
    else:
        warn("ignoreFirstLine = false — CSV header read as data")

    # Check cpu_ms default
    r = run_cmd(executor, f"grep 'cpu_ms' {jmx_path}")
    if "cpu_ms,200" in r.stdout:
        ok("cpu_ms default = 200")
    elif "cpu_ms,10" in r.stdout:
        fail("cpu_ms default = 10 — OLD JMX!")
    else:
        info(f"cpu_ms line: {r.stdout.strip()}")

    # Check touch_mb default
    r = run_cmd(executor, f"grep 'touch_mb' {jmx_path}")
    if "touch_mb,1.0" in r.stdout:
        ok("touch_mb default = 1.0")
    elif "touch_mb,0.2" in r.stdout:
        warn("touch_mb default = 0.2 — should be 1.0")
    else:
        info(f"touch_mb line: {r.stdout.strip()}")


def validate_csv_on_loadgen(executor, run_dir):
    """Check calibration CSV content on the loadgen."""
    section("Calibration CSV on loadgen")

    csv_path = f"{run_dir}/calibration_ops.csv"
    r = run_cmd(executor, f"test -f {csv_path} && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status != "EXISTS":
        fail(f"CSV not found: {csv_path}")
        return

    # Row count
    r = run_cmd(executor, f"wc -l < {csv_path}")
    rows = r.stdout.strip()
    ok(f"CSV exists: {rows} lines")

    # Header
    r = run_cmd(executor, f"head -1 {csv_path}")
    header = r.stdout.strip()
    expected = "seq_id,op_type,size_bracket,target_size_kb,output_format,output_folder_idx,is_confidential,make_zip,source_file_ids"
    if header == expected:
        ok("Header matches (9 columns)")
    else:
        fail(f"Header mismatch!")
        info(f"Expected: {expected}")
        info(f"Got:      {header}")

    # Op distribution (first 1000 rows)
    r = run_cmd(executor, f"tail -n +2 {csv_path} | head -1000 | cut -d',' -f2 | sort | uniq -c | sort -rn")
    if r.stdout.strip():
        info("Op distribution (first 1000):")
        for line in r.stdout.strip().splitlines():
            info(f"  {line.strip()}")

    # First 3 data rows
    r = run_cmd(executor, f"head -4 {csv_path} | tail -3")
    info("First 3 rows:")
    for line in r.stdout.strip().splitlines():
        info(f"  {line[:100]}")


def validate_jmeter_on_loadgen(executor, loadgen_hostname, target_ip, check_running=False):
    """Check JMeter binary and running processes."""
    section(f"JMeter on loadgen ({loadgen_hostname})")

    # Binary
    r = run_cmd(executor, "test -x /data/jmeter/bin/jmeter && echo EXISTS || echo MISSING")
    status = r.stdout.strip().split('\n')[-1].strip()
    if status == "EXISTS":
        ok("JMeter binary exists")
    else:
        fail("JMeter binary NOT FOUND at /data/jmeter/bin/jmeter")
        return

    if check_running:
        # Running processes
        r = run_cmd(executor, "ps aux | grep '[j]meter' | grep -v grep")
        if r.stdout.strip():
            warn("JMeter processes currently running:")
            for line in r.stdout.strip().splitlines():
                info(f"  {line[:150]}")

            # Extract -J params from running command
            r2 = run_cmd(executor, "ps aux | grep '[j]meter' | grep -oP '\\-J\\w+=[^ ]+' | sort")
            if r2.stdout.strip():
                info("Active -J parameters:")
                for line in r2.stdout.strip().splitlines():
                    param = line.strip()
                    if "cpu_ms=10" in param:
                        fail(f"  {param} — STILL USING OLD cpu_ms=10!")
                    elif "think_ms=500" in param:
                        warn(f"  {param} — using old think_ms=500")
                    else:
                        info(f"  {param}")
        else:
            ok("No JMeter processes running")

        # Check for orphan java processes
        r = run_cmd(executor, f"ps aux | grep '[A]pacheJMeter' | grep '{target_ip}'")
        if r.stdout.strip():
            warn(f"Orphan JMeter targeting {target_ip}:")
            for line in r.stdout.strip().splitlines():
                info(f"  {line[:150]}")


def validate_emulator_on_target(target_ip, emulator_port=8080):
    """Check emulator health, config, stats on target."""
    section(f"Emulator on target ({target_ip})")

    base_url = f"http://{target_ip}:{emulator_port}"

    # Health
    try:
        resp = http_get(f"{base_url}/health")
        ok(f"Healthy: {resp.get('status')}, uptime={resp.get('uptime_sec')}s")
    except Exception as e:
        fail(f"Health check failed: {e}")
        return

    # Config
    try:
        config = http_get(f"{base_url}/api/v1/config")
        configured = config.get("is_configured", False)
        folders = config.get("output_folders", [])
        partner_fqdn = config.get("partner", {}).get("fqdn")
        partner_port = config.get("partner", {}).get("port")

        if configured:
            ok(f"Configured: folders={len(folders)}, partner={partner_fqdn}:{partner_port}")
        else:
            fail("NOT configured — networkclient and file ops will return 400!")

        if not folders:
            fail("No output_folders — file ops will return 400!")
        if not partner_fqdn:
            fail("No partner fqdn — networkclient ops will return 400!")

    except Exception as e:
        warn(f"Config check failed: {e}")

    # Pool
    try:
        pool = http_get(f"{base_url}/api/v1/config/pool")
        if pool.get("allocated"):
            size_mb = pool.get("size_bytes", 0) / 1024 / 1024
            ok(f"Pool allocated: {size_mb:.0f} MB")
        else:
            fail("Pool NOT allocated — /work ops will return 400!")
    except Exception as e:
        warn(f"Pool check failed: {e}")

    # Stats — is it collecting?
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count=10")
        collecting = stats.get("is_collecting", False)
        total = stats.get("total_samples", 0)
        returned = stats.get("returned_samples", 0)
        samples = stats.get("samples", [])

        if collecting:
            ok(f"Stats collecting: {total} total, returned {returned}")
        else:
            info(f"Stats NOT collecting (idle): {total} samples in buffer")

        if samples:
            cpus = [s.get("cpu_percent", 0) for s in samples]
            info(f"Recent CPU: {[round(v,1) for v in cpus]}")
            avg = sum(cpus) / len(cpus)
            info(f"Avg CPU: {avg:.1f}%")
        else:
            info("No samples available")

    except Exception as e:
        warn(f"Stats check failed: {e}")

    # Active test
    try:
        test_status = http_get(f"{base_url}/api/v1/tests/current")
        if test_status:
            info(f"Active test: {json.dumps(test_status)[:200]}")
    except Exception:
        pass


def validate_db_calibration(cal_results, load_profiles):
    """Check calibration results in DB."""
    section("Calibration results in DB")

    if not cal_results:
        info("No calibration results found")
        return

    lp_map = {lp.id: lp.name for lp in load_profiles}

    for cal in cal_results:
        lp_name = lp_map.get(cal.load_profile_id, f"LP#{cal.load_profile_id}")
        status = cal.status or "?"
        thread_count = cal.thread_count
        phase = cal.phase or "-"
        message = (cal.message or "")[:100]
        error = (cal.error_message or "")[:100]
        cpu = getattr(cal, 'last_observed_cpu', None)
        iteration = getattr(cal, 'current_iteration', None)
        current_t = getattr(cal, 'current_thread_count', None)

        marker = ""
        if status == "completed":
            marker = " [OK]"
        elif status == "failed":
            marker = " [FAIL]"
        elif status == "in_progress":
            marker = " [RUNNING]"

        info(f"Server {cal.server_id} / {lp_name}:{marker}")
        info(f"  status={status}  thread_count={thread_count}  phase={phase}")
        if current_t:
            info(f"  current_thread_count={current_t}  iteration={iteration}")
        if cpu:
            info(f"  last_observed_cpu={cpu}%")
        if message:
            info(f"  message: {message}")
        if error:
            fail(f"  error: {error}")


def validate_recent_jtl(executor, run_dir):
    """Check recent JTL files for errors."""
    section("Recent JTL/logs on loadgen")

    r = run_cmd(executor, f"find {run_dir} -name '*.jtl' -mmin -60 2>/dev/null | head -5")
    jtl_files = [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]

    if not jtl_files:
        info("No recent JTL files (last 60 min)")
        return

    for jtl in jtl_files:
        info(f"\nJTL: {jtl}")
        r = run_cmd(executor, f"wc -l < {jtl}")
        lines = r.stdout.strip()
        info(f"  Lines: {lines}")

        if int(lines) > 1:
            # Error rate
            r = run_cmd(executor, f"tail -n +2 {jtl} | cut -d',' -f8 | sort | uniq -c")
            if r.stdout.strip():
                info(f"  Success/fail: {r.stdout.strip()}")

            # Response codes
            r = run_cmd(executor, f"tail -n +2 {jtl} | cut -d',' -f4 | sort | uniq -c | sort -rn | head -5")
            if r.stdout.strip():
                info(f"  Response codes: {r.stdout.strip()}")

            # Request distribution
            r = run_cmd(executor, f"tail -n +2 {jtl} | cut -d',' -f3 | sort | uniq -c | sort -rn")
            if r.stdout.strip():
                info(f"  Labels:")
                for line in r.stdout.strip().splitlines():
                    info(f"    {line.strip()}")

    # Recent JMeter logs
    r = run_cmd(executor, f"find {run_dir} -name '*.log' -mmin -60 2>/dev/null | head -3")
    log_files = [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]
    for lf in log_files:
        info(f"\nJMeter log: {lf}")
        r = run_cmd(executor, f"grep -iE 'ERROR|FATAL' {lf} | tail -5")
        if r.stdout.strip():
            fail("Errors in JMeter log:")
            for line in r.stdout.strip().splitlines():
                info(f"  {line[:150]}")
        else:
            ok("No errors in JMeter log")

        # Show last Summariser line
        r = run_cmd(executor, f"grep 'Summariser' {lf} | tail -2")
        if r.stdout.strip():
            info("Last summariser:")
            for line in r.stdout.strip().splitlines():
                info(f"  {line[:150]}")


def main():
    parser = argparse.ArgumentParser(description="Validate calibration setup for a test run")
    parser.add_argument("test_name", nargs="?", help="Test run name")
    parser.add_argument("--test-id", type=int, help="Test run ID")
    parser.add_argument("--check-running", action="store_true",
                        help="Also check running JMeter processes and their -J params")
    parser.add_argument("--config", default=None, help="Path to orchestrator.yaml")
    args = parser.parse_args()

    if not args.test_name and not args.test_id:
        parser.error("Provide test name or --test-id")

    # Load config
    config_path = args.config or os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    from orchestrator.config.settings import load_config
    config = load_config(config_path)

    from orchestrator.models.database import SessionLocal, init_db
    init_db(config.database.url)
    session = SessionLocal()

    cred_path = os.path.join(REPO_ROOT, "orchestrator", config.credentials_path)
    from orchestrator.config.credentials import CredentialsStore
    credentials = CredentialsStore(cred_path)

    # Find test run
    test_run = find_test_run(session, test_name=args.test_name, test_id=args.test_id)
    if not test_run:
        print(f"Test run not found: {args.test_name or args.test_id}")
        sys.exit(1)

    lab, scenario, targets, load_profiles, cal_results = load_context(session, test_run)

    print(f"{'='*70}")
    print(f"  CALIBRATION VALIDATION: {test_run.name} (ID={test_run.id})")
    print(f"  State: {test_run.state.value}")
    print(f"  Type: {test_run.test_type.value}")
    print(f"  Template: {scenario.template_type.value}")
    print(f"  Current LP: {test_run.current_load_profile_id}")
    print(f"  Targets: {len(targets)}")
    print(f"  Profiles: {', '.join(f'{lp.name} ({lp.target_cpu_range_min}-{lp.target_cpu_range_max}%)' for lp in load_profiles)}")
    print(f"{'='*70}")

    from orchestrator.infra.remote_executor import create_executor

    seen_loadgens = set()
    for target_orm, server, loadgen, test_snap in targets:
        run_dir = f"/data/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

        # --- Loadgen checks ---
        if loadgen.id not in seen_loadgens:
            seen_loadgens.add(loadgen.id)

            print(f"\n{'='*70}")
            print(f"  LOADGEN: {loadgen.hostname} ({loadgen.ip_address})")
            print(f"{'='*70}")

            cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            try:
                lg_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
            except Exception as e:
                fail(f"Cannot connect to loadgen: {e}")
                continue

            try:
                validate_jmeter_on_loadgen(lg_exec, loadgen.hostname, server.ip_address,
                                           check_running=args.check_running)
                validate_jmx_on_loadgen(lg_exec, run_dir)
                validate_csv_on_loadgen(lg_exec, run_dir)
                validate_recent_jtl(lg_exec, run_dir)
            finally:
                lg_exec.close()

        # --- Target checks ---
        print(f"\n{'='*70}")
        print(f"  TARGET: {server.hostname} ({server.ip_address})")
        print(f"  Run dir: {run_dir}")
        print(f"{'='*70}")

        validate_emulator_on_target(server.ip_address, config.emulator.emulator_api_port)

    # --- DB checks ---
    print(f"\n{'='*70}")
    print(f"  DATABASE")
    print(f"{'='*70}")

    validate_db_calibration(cal_results, load_profiles)

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f"  VALIDATION COMPLETE")
    print(f"{'='*70}")

    session.close()


if __name__ == "__main__":
    main()
