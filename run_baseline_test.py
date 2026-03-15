"""
End-to-end baseline test runner.

Starts the orchestrator, creates a baseline test via the API, monitors progress
by polling state + checking DB, and reports results.

Supports three test types:
  - new_baseline:  Establish baseline performance metrics for one or more servers.
                   Runs: validating -> setting_up -> calibrating -> generating
                         -> executing -> storing -> completed
                   The "storing" phase saves calibrated thread counts, stats, JTL,
                   and ops-sequence CSV into snapshot_profile_data for each target's
                   snapshot. These stored results become the reference for future
                   compare runs.

  - compare:       Re-run load test using the SAME thread count and ops-sequence
                   from a previous baseline, then compare metrics to detect
                   performance regressions (e.g. after installing a security agent).
                   Runs: validating -> setting_up -> executing -> comparing
                         -> storing -> completed
                   Skips calibration/generation — reuses stored data from
                   compare_snapshot_id.

  - compare_with_new_calibration:
                   Like compare, but re-calibrates thread counts first (useful when
                   the agent changes CPU baseline). Still compares against the
                   original baseline's stats.
                   Runs: validating -> setting_up -> calibrating -> generating
                         -> executing -> comparing -> storing -> completed

Multi-server support:
  Use --target both to run Linux and Windows servers in a single test run.
  All phases (setup, calibration, generation, execution) run in PARALLEL across
  targets, with barriers between phases (all targets must complete phase N before
  phase N+1 begins). Errors are tracked per-target per-state for easy debugging.

  Each target has its own snapshot (test_snapshot_id) and optionally its own
  compare snapshot (baseline_snapshot_id in TARGETS dict). The TARGETS dict below
  defines the mapping — add new servers there.

How to run a baseline + compare cycle:
  1. Create baseline:
       python run_baseline_test.py --target both --profile low --skip-build
     This calibrates, runs, and stores results into each target's snapshot.

  2. Install security agent on the target VMs (manual step or via orchestrator).

  3. Run compare against the baseline:
       python run_baseline_test.py --target both --profile low --test-type compare --skip-build
     Each target automatically uses its own baseline_snapshot_id from the TARGETS
     dict. The orchestrator loads stored thread counts + ops CSVs from those
     snapshots, re-runs the exact same load, and compares stats.

  4. (Optional) Override compare snapshot for all targets:
       python run_baseline_test.py --target linux --test-type compare --compare-snapshot-id 5

Usage examples:
    python run_baseline_test.py                          # Linux only, low profile, new baseline
    python run_baseline_test.py --target both            # Both servers, new baseline
    python run_baseline_test.py --target both --profile low,medium  # Multiple profiles
    python run_baseline_test.py --target both --test-type compare --skip-build  # Compare run
    python run_baseline_test.py --skip-orchestrator      # Don't start/stop orchestrator
    python run_baseline_test.py --skip-build             # Skip Maven emulator build
"""

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from datetime import datetime

import requests

# ── Constants ──────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.join(SCRIPT_DIR, "orchestrator")
EMULATOR_JAVA_DIR = os.path.join(SCRIPT_DIR, "emulator_java")
EMULATOR_DATA_DIR = os.path.join(SCRIPT_DIR, "emulator", "data")
ARTIFACTS_DIR = os.path.join(ORCH_DIR, "artifacts", "packages")
JDK17_HOME = r"C:\jdk-17.0.18.8-hotspot"
ORCH_LOG_FILE = os.path.join(ORCH_DIR, "logs", "orchestrator_run.log")
ORCH_BIND = "0.0.0.0"       # uvicorn listens on all interfaces (WinRM targets need it)
ORCH_HOST = "127.0.0.1"    # local API calls use localhost
ORCH_PORT = 8000
ORCH_BASE = f"http://{ORCH_HOST}:{ORCH_PORT}"
API = f"{ORCH_BASE}/api"

# Credentials (from seed data)
USERNAME = "admin"
PASSWORD = "admin"

# DB IDs (from setup_proxmox_lab.py output)
# To add a new server: add an entry here with the correct DB IDs, then use
# --target <name> or --target both. The orchestrator will include it in
# parallel execution alongside other targets.
#
# Fields:
#   server_id           - servers.id in DB (from setup_proxmox_lab.py)
#   snapshot_id          - snapshots.id used as test_snapshot (VM reverted to this before each run)
#   baseline_snapshot_id - snapshots.id holding stored baseline profile data (thread counts,
#                          stats, JTL, ops CSV). Used as compare_snapshot_id in compare runs.
#                          After a new_baseline run, the storing phase writes profile data
#                          into this snapshot's snapshot_profile_data rows.
#   hostname / ip        - for pre-flight health checks only (actual values come from DB)
TARGETS = {
    "linux": {
        "server_id": 8,
        "snapshot_id": 3,              # clean-rocky-baseline (Proxmox snapshot)
        "baseline_snapshot_id": 3,     # same snapshot — stores baseline profile data
        "hostname": "target-rky-01",
        "ip": "10.0.0.92",
    },
    "windows": {
        "server_id": 9,
        "snapshot_id": 4,              # clean-win-baseline (Proxmox snapshot)
        "baseline_snapshot_id": 4,     # same snapshot — stores baseline profile data
        "hostname": "TARGET-WIN-01",
        "ip": "10.0.0.91",
    },
}

# Scenario determines which JMX template is used (server-steady, server-normal, etc.)
SCENARIO_ID = 1004  # Proxmox Baseline Steady (server-steady: /work endpoint)
LAB_ID = 4

# Available load profile names — resolved to DB IDs at runtime via load_profiles table
PROFILE_NAMES = ["low", "medium", "high"]

# Poll interval
POLL_SEC = 15
MAX_WAIT_SEC = 21600  # 6 hours max (supports 4-hour load tests + calibration overhead)


# ── Helpers ────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")


def banner(msg):
    print(f"\n{'=' * 70}")
    print(f"  {ts()}  {msg}")
    print(f"{'=' * 70}")


def info(msg):
    print(f"  {ts()}  {msg}")


def ok(msg):
    print(f"  {ts()}  [OK] {msg}")


def fail(msg):
    print(f"  {ts()}  [FAIL] {msg}")


def build_emulator_packages():
    """Build Java emulator jar and create deployment tar.gz packages."""
    banner("Building Java emulator packages")

    # Step 1: Maven build (using JDK 17 for Spring Boot 3.x)
    build_env = os.environ.copy()
    build_env["JAVA_HOME"] = JDK17_HOME
    build_env["PATH"] = os.path.join(JDK17_HOME, "bin") + os.pathsep + build_env["PATH"]
    info(f"Using JAVA_HOME={JDK17_HOME}")
    info("Running mvn package...")
    result = subprocess.run(
        ["mvn", "package", "-DskipTests", "-q"],
        cwd=EMULATOR_JAVA_DIR,
        capture_output=True, text=True, timeout=120,
        env=build_env,
        shell=True,  # Windows needs shell=True to resolve mvn.cmd
    )
    if result.returncode != 0:
        fail(f"Maven build failed:\n{result.stdout}\n{result.stderr}")
        sys.exit(1)

    jar_path = os.path.join(EMULATOR_JAVA_DIR, "target", "emulator.jar")
    if not os.path.isfile(jar_path):
        fail(f"emulator.jar not found at {jar_path}")
        sys.exit(1)
    jar_size_mb = os.path.getsize(jar_path) / (1024 * 1024)
    ok(f"Built emulator.jar ({jar_size_mb:.1f} MB)")

    # Step 2: Create tar.gz packages directly (no staging dir needed)
    # Uses Python tarfile to avoid Windows MAX_PATH and shell tar issues
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    for platform, start_script in [("linux", "start.sh"), ("windows", "start.ps1")]:
        pkg_name = f"emulator-java-{platform}"
        tar_path = os.path.join(ARTIFACTS_DIR, f"{pkg_name}.tar.gz")
        skipped = 0

        with tarfile.open(tar_path, "w:gz") as tar:
            # Add emulator.jar
            tar.add(jar_path, arcname=f"{pkg_name}/emulator.jar")
            # Add start script
            tar.add(
                os.path.join(EMULATOR_JAVA_DIR, start_script),
                arcname=f"{pkg_name}/{start_script}",
            )
            # Add data dir (DLP test files, normal files)
            if os.path.isdir(EMULATOR_DATA_DIR):
                for root, dirs, files in os.walk(EMULATOR_DATA_DIR):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, EMULATOR_DATA_DIR)
                        arcname = f"{pkg_name}/data/{rel_path}".replace("\\", "/")
                        try:
                            tar.add(full_path, arcname=arcname)
                        except (OSError, FileNotFoundError):
                            skipped += 1

        tar_size_mb = os.path.getsize(tar_path) / (1024 * 1024)
        msg = f"Created {pkg_name}.tar.gz ({tar_size_mb:.1f} MB)"
        if skipped:
            msg += f" ({skipped} files skipped due to long paths)"
        ok(msg)

    ok("Emulator packages built successfully")


def login():
    """Authenticate and return Bearer token."""
    resp = requests.post(
        f"{API}/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        fail(f"Login failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    token = resp.json()["access_token"]
    ok(f"Logged in as '{USERNAME}'")
    return {"Authorization": f"Bearer {token}"}


def api_get(path, headers, label=None):
    try:
        resp = requests.get(f"{API}{path}", headers=headers, timeout=30)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        fail(f"GET {path} timeout/connection error: {e}")
        return None
    if resp.status_code != 200:
        fail(f"GET {path} failed: {resp.status_code} {resp.text}")
        return None
    return resp.json()


def api_post(path, headers, json_data=None, label=None):
    try:
        resp = requests.post(f"{API}{path}", headers=headers, json=json_data, timeout=30)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        fail(f"POST {path} timeout/connection error: {e}")
        return None
    if resp.status_code not in (200, 201):
        fail(f"POST {path} failed: {resp.status_code} {resp.text}")
        return None
    return resp.json()


def resolve_profile_ids(headers, profile_names):
    """Fetch load profiles from API and map names to IDs."""
    # Query DB directly since there's no /api/load-profiles endpoint
    sys.path.insert(0, os.path.join(ORCH_DIR, "src"))
    from orchestrator.models.database import init_db, SessionLocal
    from orchestrator.models.orm import LoadProfileORM
    from orchestrator.config.settings import load_config

    config = load_config(os.path.join(ORCH_DIR, "config", "orchestrator.yaml"))
    init_db(config.database.url, echo=False)
    session = SessionLocal()
    profiles = session.query(LoadProfileORM).all()
    name_to_id = {p.name: p.id for p in profiles}
    session.close()

    ids = []
    for name in profile_names:
        if name not in name_to_id:
            fail(f"Load profile '{name}' not found. Available: {list(name_to_id.keys())}")
            sys.exit(1)
        ids.append(name_to_id[name])
    return ids


def check_db_state(test_run_id):
    """Query DB directly for detailed state info (calibration results, etc.)."""
    try:
        sys.path.insert(0, os.path.join(ORCH_DIR, "src"))
        from orchestrator.models.database import SessionLocal
        from orchestrator.models.orm import (
            BaselineTestRunORM, CalibrationResultORM, ComparisonResultORM,
        )

        session = SessionLocal()
        test_run = session.get(BaselineTestRunORM, test_run_id)
        if not test_run:
            return {}

        result = {
            "state": test_run.state.value,
            "current_profile": test_run.current_load_profile_id,
            "error": test_run.error_message,
            "verdict": test_run.verdict.value if test_run.verdict else None,
        }

        # Calibration results
        cal_results = session.query(CalibrationResultORM).filter_by(
            baseline_test_run_id=test_run_id
        ).all()
        if cal_results:
            result["calibration"] = []
            for cr in cal_results:
                result["calibration"].append({
                    "server_id": cr.server_id,
                    "profile_id": cr.load_profile_id,
                    "threads": getattr(cr, 'current_thread_count', cr.thread_count),
                    "status": cr.status,
                    "cpu": cr.last_observed_cpu,
                    "iteration": cr.current_iteration,
                    "phase": getattr(cr, 'phase', None),
                    "message": getattr(cr, 'message', None),
                })

        # Comparison results
        cmp_results = session.query(ComparisonResultORM).filter_by(
            baseline_test_run_id=test_run_id
        ).all()
        if cmp_results:
            result["comparisons"] = []
            for cr in cmp_results:
                result["comparisons"].append({
                    "target_id": cr.target_id,
                    "profile_id": cr.load_profile_id,
                    "verdict": cr.verdict.value if cr.verdict else None,
                    "violations": cr.violation_count,
                })

        session.close()
        return result
    except Exception as e:
        return {"db_error": str(e)}


def check_emulator_health(targets_config):
    """Check emulator health on all targets."""
    for name, cfg in targets_config.items():
        try:
            resp = requests.get(f"http://{cfg['ip']}:8080/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                info(f"  {name} ({cfg['ip']}): healthy, uptime={data.get('uptime_sec', '?')}s")
            else:
                fail(f"  {name} ({cfg['ip']}): HTTP {resp.status_code}")
        except Exception as e:
            fail(f"  {name} ({cfg['ip']}): unreachable ({e})")


def kill_existing_orchestrator():
    """Kill any existing orchestrator process listening on ORCH_PORT."""
    try:
        # Find and kill process on the orchestrator port
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if f":{ORCH_PORT}" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                info(f"Killing existing orchestrator process (PID {pid}) on port {ORCH_PORT}")
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
                time.sleep(2)
                break
    except Exception as e:
        info(f"  (Could not check for existing process: {e})")


def start_orchestrator():
    """Kill any existing orchestrator, then start a fresh one."""
    banner("Starting orchestrator server")
    kill_existing_orchestrator()
    env = os.environ.copy()
    # orchestrator.app expects CWD = orchestrator/ (for config/orchestrator.yaml)
    # but the Python package is under orchestrator/src/, so add src/ to PYTHONPATH
    src_dir = os.path.join(ORCH_DIR, "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    # Log to file instead of piping (piping causes buffer fill -> orchestrator blocks)
    os.makedirs(os.path.dirname(ORCH_LOG_FILE), exist_ok=True)
    orch_log_fh = open(ORCH_LOG_FILE, "w", encoding="utf-8")
    info(f"Orchestrator logs: {ORCH_LOG_FILE}")
    # Set Python logging to output all orchestrator module logs
    env["LOG_LEVEL"] = "INFO"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orchestrator.app:app",
         "--host", ORCH_BIND, "--port", str(ORCH_PORT),
         "--log-level", "info"],
        cwd=ORCH_DIR,
        env=env,
        stdout=orch_log_fh,
        stderr=subprocess.STDOUT,
    )
    info(f"Orchestrator PID: {proc.pid}")

    # Wait for it to be ready
    for i in range(30):
        try:
            resp = requests.get(f"{ORCH_BASE}/docs", timeout=2)
            if resp.status_code == 200:
                ok(f"Orchestrator ready at {ORCH_BASE} (took {i+1}s)")
                return proc
        except Exception:
            pass
        time.sleep(1)

    fail("Orchestrator failed to start within 30s")
    proc.terminate()
    sys.exit(1)


def stop_orchestrator(proc):
    """Stop the orchestrator subprocess."""
    if proc and proc.poll() is None:
        info("Stopping orchestrator...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        ok("Orchestrator stopped")


# ── State Display ──────────────────────────────────────────────────────────

STATE_DESCRIPTIONS = {
    "created": "Test created, waiting to start",
    "validating": "Pre-flight validation (checking targets, snapshots, connectivity)",
    "setting_up": "Infrastructure setup (reverting VMs, deploying packages, starting emulators)",
    "calibrating": "Calibrating thread counts (binary search for target CPU range)",
    "generating": "Generating deterministic operation sequences",
    "executing": "Running load test (JMeter driving emulators)",
    "comparing": "Comparing results against baseline",
    "storing": "Storing results to snapshot data",
    "completed": "Test completed successfully",
    "failed": "Test failed",
    "cancelled": "Test cancelled",
}

TERMINAL_STATES = {"completed", "failed", "cancelled"}


def print_state_update(state, db_info, prev_state):
    """Print state change or progress update."""
    if state != prev_state:
        desc = STATE_DESCRIPTIONS.get(state, "")
        banner(f"STATE: {state.upper()} -- {desc}")

    # Print calibration progress
    if "calibration" in db_info:
        for cal in db_info["calibration"]:
            info(f"  Calibration: server={cal['server_id']} profile={cal['profile_id']} "
                 f"threads={cal['threads']} cpu={cal['cpu']}% "
                 f"status={cal['status']} iter={cal['iteration']} "
                 f"phase={cal.get('phase')}")
            if cal.get("message"):
                info(f"    {cal['message']}")

    # Print comparison results
    if "comparisons" in db_info:
        for cmp in db_info["comparisons"]:
            info(f"  Comparison: target={cmp['target_id']} profile={cmp['profile_id']} "
                 f"verdict={cmp['verdict']} violations={cmp['violations']}")

    if db_info.get("current_profile"):
        info(f"  Current load profile ID: {db_info['current_profile']}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="End-to-end baseline test runner")
    parser.add_argument("--target", choices=["linux", "windows", "both"], default="linux",
                        help="Target server(s) to test (default: linux)")
    parser.add_argument("--profile", default="low",
                        help="Comma-separated load profile names (default: low)")
    parser.add_argument("--test-type", default="new_baseline",
                        choices=["new_baseline", "compare", "compare_with_new_calibration"],
                        help="Test type (default: new_baseline)")
    parser.add_argument("--skip-orchestrator", action="store_true",
                        help="Don't start/stop orchestrator (assumes already running)")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip emulator Maven build and package creation")
    parser.add_argument("--compare-snapshot-id", type=int, default=None,
                        help="Snapshot ID to compare against (required for compare test types)")
    args = parser.parse_args()

    # Determine targets
    if args.target == "both":
        active_targets = dict(TARGETS)
    else:
        active_targets = {args.target: TARGETS[args.target]}

    profile_names = [p.strip() for p in args.profile.split(",")]

    banner("END-TO-END BASELINE TEST")
    info(f"Targets: {', '.join(active_targets.keys())}")
    info(f"Profiles: {', '.join(profile_names)}")
    info(f"Test type: {args.test_type}")
    info(f"Scenario ID: {SCENARIO_ID}")

    # Build emulator packages
    if not args.skip_build:
        build_emulator_packages()
    else:
        info("Skipping emulator build (--skip-build)")

    # Start orchestrator if needed
    orch_proc = None
    if not args.skip_orchestrator:
        orch_proc = start_orchestrator()
    else:
        # Verify it's running
        try:
            requests.get(f"{ORCH_BASE}/docs", timeout=5)
            ok(f"Orchestrator already running at {ORCH_BASE}")
        except Exception:
            fail(f"Orchestrator not reachable at {ORCH_BASE}. Start it or remove --skip-orchestrator")
            sys.exit(1)

    try:
        # Login
        banner("Authentication")
        headers = login()

        # Resolve load profile IDs
        banner("Resolving load profiles")
        profile_ids = resolve_profile_ids(headers, profile_names)
        for name, pid in zip(profile_names, profile_ids):
            info(f"  {name} -> id={pid}")

        # Check emulator health on targets
        banner("Pre-flight: emulator health check")
        check_emulator_health(active_targets)

        # Build create payload
        targets_payload = []
        for name, cfg in active_targets.items():
            target_entry = {
                "server_id": cfg["server_id"],
                "test_snapshot_id": cfg["snapshot_id"],
            }
            if args.test_type != "new_baseline":
                # Use per-target baseline_snapshot_id, falling back to --compare-snapshot-id
                compare_snap = args.compare_snapshot_id or cfg.get("baseline_snapshot_id")
                if not compare_snap:
                    fail(f"No compare snapshot for {name}: set baseline_snapshot_id in TARGETS or use --compare-snapshot-id")
                    sys.exit(1)
                target_entry["compare_snapshot_id"] = compare_snap
            targets_payload.append(target_entry)

        create_payload = {
            "scenario_id": SCENARIO_ID,
            "test_type": args.test_type,
            "load_profile_ids": profile_ids,
            "targets": targets_payload,
        }

        # Create baseline test
        banner("Creating baseline test run")
        info(f"Payload: {json.dumps(create_payload, indent=2)}")
        result = api_post("/baseline-tests", headers, create_payload)
        if not result:
            sys.exit(1)

        test_run_id = result["id"]
        ok(f"Created test run id={test_run_id}, state={result['state']}")

        # Start the test
        banner("Starting test run")
        start_result = api_post(f"/baseline-tests/{test_run_id}/start", headers)
        if not start_result:
            sys.exit(1)
        ok(f"Test run {test_run_id} started: {start_result['message']}")

        # Poll for completion
        banner("Monitoring test progress")
        info(f"Polling every {POLL_SEC}s (max {MAX_WAIT_SEC}s)")
        info(f"Cancel with Ctrl+C")

        start_time = time.time()
        prev_state = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > MAX_WAIT_SEC:
                fail(f"Timeout after {MAX_WAIT_SEC}s")
                break

            # Poll API
            status_data = api_get(f"/baseline-tests/{test_run_id}", headers)
            if not status_data:
                info("  (API unreachable, retrying...)")
                time.sleep(POLL_SEC)
                continue

            state = status_data["state"]

            # Poll DB for detailed info
            db_info = check_db_state(test_run_id)

            # Display
            print_state_update(state, db_info, prev_state)

            if state in TERMINAL_STATES:
                break

            prev_state = state
            time.sleep(POLL_SEC)

        # Final report
        elapsed_total = time.time() - start_time
        minutes = int(elapsed_total // 60)
        seconds = int(elapsed_total % 60)

        banner("FINAL REPORT")
        info(f"Test run ID: {test_run_id}")
        info(f"Duration: {minutes}m {seconds}s")
        info(f"Final state: {state}")

        if state == "completed":
            info(f"Verdict: {status_data.get('verdict', 'N/A')}")
            ok("BASELINE TEST COMPLETED SUCCESSFULLY")

            # Print comparison results if available
            comparisons = api_get(f"/baseline-tests/{test_run_id}/comparison-results", headers)
            if comparisons:
                info("\nComparison Results:")
                for cr in comparisons:
                    info(f"  Target {cr['target_id']}, Profile {cr['load_profile_id']}: "
                         f"verdict={cr['verdict']}, violations={cr['violation_count']}")

        elif state == "failed":
            fail(f"ERROR: {status_data.get('error_message', 'Unknown error')}")
            # Show last DB state for debugging
            db_final = check_db_state(test_run_id)
            if db_final.get("error"):
                info(f"  DB error: {db_final['error']}")

        elif state == "cancelled":
            info("Test was cancelled")

        else:
            fail(f"Test ended in unexpected state: {state}")

        return 0 if state == "completed" else 1

    except KeyboardInterrupt:
        print(f"\n\n  {ts()}  Interrupted by user")
        info(f"Cancelling test run {test_run_id}...")
        try:
            api_post(f"/baseline-tests/{test_run_id}/cancel", headers)
            ok("Test run cancelled")
        except Exception:
            pass
        return 1

    finally:
        if orch_proc:
            stop_orchestrator(orch_proc)


if __name__ == "__main__":
    sys.exit(main())
