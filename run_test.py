#!/usr/bin/env python3
"""
Test runner — config-driven baseline test execution.

Reads a test case YAML (targets, loadgens, scenario, profiles) and runs it
as new_baseline, compare, or compare_with_new_calibration.

All server/scenario/profile references are by NAME — resolved to DB IDs at runtime.
Snapshots are auto-resolved (latest per server). Platform-aware (Linux + Windows).

Usage:
    # New baseline
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline

    # Compare against latest stored baseline (auto-detected per target)
    python run_test.py -tc test_cases/5server_steady.yaml -t compare

    # Compare against a specific prior baseline run
    python run_test.py -tc test_cases/5server_steady.yaml -t compare --baseline-run 1053

    # Override profiles at runtime
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline -p low

    # Override duration (30 min test)
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline -d 1800

    # Override template type
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline --template server-normal

    # Run only specific targets from the test case
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline --only rhel8-tgt-01,win2022-tgt-01

    # Skip orchestrator start + emulator build
    python run_test.py -tc test_cases/5server_steady.yaml -t new_baseline --skip-orchestrator --skip-build

Test case YAML format:
    name: "my-test"
    template: "server-steady"          # server-steady, server-normal, server-file-heavy, db-load
    profiles: [low, high]              # load profile names
    duration_sec: 3600                 # optional — override test duration (seconds)
    targets:
      - hostname: rhel8-tgt-01         # target server hostname (from servers table)
        loadgen: rhel8-lg-01           # loadgen server hostname (from servers table)
        snapshot: "clean-rhel8"        # VM snapshot name (from snapshots table, optional)
"""

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import tarfile
import time
from datetime import datetime

import requests
import yaml


# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.join(SCRIPT_DIR, "orchestrator")
ORCH_SRC = os.path.join(ORCH_DIR, "src")
ORCH_CONFIG = os.path.join(ORCH_DIR, "config", "orchestrator.yaml")
EMULATOR_JAVA_DIR = os.path.join(SCRIPT_DIR, "emulator_java")
EMULATOR_DATA_DIR = os.path.join(SCRIPT_DIR, "emulator", "data")
ARTIFACTS_DIR = os.path.join(ORCH_DIR, "artifacts", "packages")

ORCH_BIND = "0.0.0.0"
ORCH_HOST = "127.0.0.1"
ORCH_PORT = 8000
ORCH_BASE = f"http://{ORCH_HOST}:{ORCH_PORT}"
API = f"{ORCH_BASE}/api"

USERNAME = "admin"
PASSWORD = "admin"

POLL_SEC = 15
MAX_WAIT_SEC = 21600  # 6 hours

IS_LINUX = platform.system() != "Windows"

TERMINAL_STATES = {"completed", "failed", "cancelled"}

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


# ── Output helpers ────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def banner(msg):
    print(f"\n{'=' * 70}\n  {ts()}  {msg}\n{'=' * 70}")

def info(msg):
    print(f"  {ts()}  {msg}")

def ok(msg):
    print(f"  {ts()}  [OK] {msg}")

def fail(msg):
    print(f"  {ts()}  [FAIL] {msg}")

def die(msg):
    fail(msg)
    sys.exit(1)


# ── Test case loader ──────────────────────────────────────────────────────

def load_test_case(path: str) -> dict:
    """Load and validate a test case YAML file."""
    if not os.path.exists(path):
        die(f"Test case file not found: {path}")

    with open(path) as f:
        tc = yaml.safe_load(f)

    # Validate required fields
    for field in ("name", "template", "profiles", "targets"):
        if field not in tc:
            die(f"Test case missing required field: '{field}'")

    if not tc["targets"]:
        die("Test case has no targets")

    if not tc["profiles"]:
        die("Test case has no profiles")

    for i, t in enumerate(tc["targets"]):
        if "hostname" not in t:
            die(f"Target #{i+1} missing 'hostname'")
        if "loadgen" not in t:
            die(f"Target #{i+1} ({t['hostname']}) missing 'loadgen'")

    return tc


# ── DB resolution ─────────────────────────────────────────────────────────

def _init_db():
    """Initialize DB connection from orchestrator config."""
    if ORCH_SRC not in sys.path:
        sys.path.insert(0, ORCH_SRC)

    from orchestrator.config.settings import load_config
    from orchestrator.models.database import init_db, SessionLocal

    config = load_config(ORCH_CONFIG)
    init_db(config.database.url, echo=False)
    return SessionLocal()


def resolve_servers(session, test_case: dict, only_filter: list = None,
                    snapshot_override: str = None) -> list[dict]:
    """Resolve target hostnames, loadgen hostnames, and snapshots to DB IDs.

    Snapshot resolution priority (per target):
      1. --snapshot CLI override (applied to all targets)
      2. 'snapshot' field in test case YAML target entry
      3. Latest snapshot for the server in DB

    Returns list of dicts: {hostname, server_id, loadgen_id, loadgen_hostname,
                            snapshot_id, snapshot_name, os_family, ip}
    """
    from orchestrator.models.orm import Server as ServerORM, Snapshot as SnapshotORM

    # Build hostname -> server map
    all_servers = {s.hostname.lower(): s for s in session.query(ServerORM).all()}

    resolved = []
    for entry in test_case["targets"]:
        hostname = entry["hostname"]

        # Apply --only filter
        if only_filter and hostname not in only_filter:
            continue

        # Resolve target server
        srv = all_servers.get(hostname.lower())
        if not srv:
            die(f"Target server '{hostname}' not found in DB. "
                f"Available: {', '.join(sorted(all_servers.keys()))}")

        # Resolve loadgen server
        lg_hostname = entry["loadgen"]
        lg = all_servers.get(lg_hostname.lower())
        if not lg:
            die(f"Loadgen server '{lg_hostname}' not found in DB. "
                f"Available: {', '.join(sorted(all_servers.keys()))}")

        # Resolve snapshot: CLI override > YAML per-target > latest in DB
        snap_name = snapshot_override or entry.get("snapshot")

        if snap_name:
            # Look up by name for this server
            snapshot = (
                session.query(SnapshotORM)
                .filter_by(server_id=srv.id, name=snap_name)
                .first()
            )
            if not snapshot:
                # Show available snapshots for this server
                avail = session.query(SnapshotORM).filter_by(server_id=srv.id).all()
                avail_names = [f"'{s.name}' (id={s.id})" for s in avail]
                die(f"Snapshot '{snap_name}' not found for server '{hostname}'. "
                    f"Available: {', '.join(avail_names) or 'none'}")
        else:
            # Fallback: latest snapshot for this server
            snapshot = (
                session.query(SnapshotORM)
                .filter_by(server_id=srv.id)
                .order_by(SnapshotORM.created_at.desc())
                .first()
            )
            if not snapshot:
                die(f"No snapshot found for server '{hostname}' (id={srv.id}). "
                    f"Create a snapshot first or specify 'snapshot' in the test case.")

        resolved.append({
            "hostname": srv.hostname,
            "server_id": srv.id,
            "ip": srv.ip_address,
            "os_family": srv.os_family.value,
            "loadgen_id": lg.id,
            "loadgen_hostname": lg.hostname,
            "snapshot_id": snapshot.id,
            "snapshot_name": snapshot.name,
        })

    if not resolved:
        die("No targets resolved. Check --only filter or test case targets.")

    return resolved


def resolve_scenario(session, template_type: str) -> int:
    """Resolve template type to scenario_id.

    Looks up by template_type first, then by scenario name.
    If not found, lists available options.
    """
    from orchestrator.models.orm import Scenario as ScenarioORM

    # Try template_type match first (primary lookup)
    scenario = session.query(ScenarioORM).filter_by(template_type=template_type).first()
    if scenario:
        return scenario.id

    # Try exact name match as fallback
    scenario = session.query(ScenarioORM).filter_by(name=template_type).first()
    if scenario:
        return scenario.id

    # List available
    all_scenarios = session.query(ScenarioORM).all()
    available = [f"{s.name} (template={s.template_type}, id={s.id})" for s in all_scenarios]
    die(f"Template '{template_type}' not found.\nAvailable:\n  " + "\n  ".join(available))


def resolve_profiles(session, profile_names: list[str], duration_override: int = None) -> list[int]:
    """Resolve profile names to profile IDs.

    If duration_override is set, updates duration_sec in the DB for each profile
    before the test starts (so calibration and execution use the new duration).
    """
    from orchestrator.models.orm import LoadProfile as LoadProfileORM

    all_profiles = {p.name: p for p in session.query(LoadProfileORM).all()}
    ids = []
    for name in profile_names:
        if name not in all_profiles:
            die(f"Load profile '{name}' not found. Available: {list(all_profiles.keys())}")
        profile = all_profiles[name]

        if duration_override and profile.duration_sec != duration_override:
            old = profile.duration_sec
            profile.duration_sec = duration_override
            session.commit()
            info(f"  Profile '{name}': duration_sec {old}s -> {duration_override}s")

        ids.append(profile.id)
    return ids


def resolve_compare_snapshots(session, resolved_targets: list[dict],
                              baseline_run_id: int = None) -> dict:
    """Resolve compare_snapshot_id for each target.

    If baseline_run_id given: look up which snapshots that run stored data into.
    Otherwise: find the latest snapshot_profile_data for each target's snapshot.

    Returns: {server_id: compare_snapshot_id}
    """
    from orchestrator.models.orm import (
        SnapshotProfileData as SPD,
        BaselineTestRunTarget as BTRT,
    )

    compare_map = {}

    if baseline_run_id:
        # Look up the targets from that baseline run and use their test_snapshot_id
        targets = (
            session.query(BTRT)
            .filter_by(baseline_test_run_id=baseline_run_id)
            .all()
        )
        for t in targets:
            compare_map[t.target_id] = t.test_snapshot_id

        # Verify we have mappings for all our targets
        for rt in resolved_targets:
            if rt["server_id"] not in compare_map:
                info(f"  Warning: baseline run {baseline_run_id} has no target for "
                     f"{rt['hostname']} (id={rt['server_id']}). Using its own snapshot.")
                compare_map[rt["server_id"]] = rt["snapshot_id"]
    else:
        # Auto-detect: for each target, find the snapshot that has stored profile data
        for rt in resolved_targets:
            spd = (
                session.query(SPD)
                .filter_by(snapshot_id=rt["snapshot_id"])
                .first()
            )
            if spd:
                compare_map[rt["server_id"]] = rt["snapshot_id"]
            else:
                die(f"No baseline data found for {rt['hostname']} snapshot "
                    f"{rt['snapshot_id']} ({rt['snapshot_name']}). "
                    f"Run a new_baseline first, or specify --baseline-run.")

    return compare_map


# ── API helpers ───────────────────────────────────────────────────────────

def login():
    resp = requests.post(f"{API}/auth/login",
                         data={"username": USERNAME, "password": PASSWORD}, timeout=10)
    if resp.status_code != 200:
        die(f"Login failed: {resp.status_code} {resp.text}")
    ok(f"Logged in as '{USERNAME}'")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def api_get(path, headers):
    try:
        resp = requests.get(f"{API}{path}", headers=headers, timeout=30)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        fail(f"GET {path}: {e}")
        return None
    if resp.status_code != 200:
        fail(f"GET {path}: {resp.status_code} {resp.text}")
        return None
    return resp.json()


def api_post(path, headers, json_data=None):
    try:
        resp = requests.post(f"{API}{path}", headers=headers, json=json_data, timeout=30)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        fail(f"POST {path}: {e}")
        return None
    if resp.status_code not in (200, 201):
        fail(f"POST {path}: {resp.status_code} {resp.text}")
        return None
    return resp.json()


# ── Process management (platform-aware) ──────────────────────────────────

def kill_port(port: int):
    """Kill any process listening on the given port."""
    try:
        if IS_LINUX:
            result = subprocess.run(
                ["ss", "-tlnp", f"sport = :{port}"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "pid=" in line:
                    # Extract PID from pid=XXXX
                    for part in line.split(","):
                        if part.strip().startswith("pid="):
                            pid = int(part.strip().split("=")[1])
                            info(f"Killing existing process PID {pid} on port {port}")
                            os.kill(pid, signal.SIGTERM)
                            time.sleep(2)
        else:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.split()[-1])
                    info(f"Killing existing process PID {pid} on port {port}")
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=10)
                    time.sleep(2)
                    break
    except Exception as e:
        info(f"  (Could not check port {port}: {e})")


def start_orchestrator():
    """Start orchestrator server."""
    banner("Starting orchestrator server")
    kill_port(ORCH_PORT)

    env = os.environ.copy()
    env["PYTHONPATH"] = ORCH_SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["LOG_LEVEL"] = "INFO"

    log_dir = os.path.join(ORCH_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "orchestrator_run.log")
    log_fh = open(log_file, "w", encoding="utf-8")
    info(f"Orchestrator logs: {log_file}")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orchestrator.app:app",
         "--host", ORCH_BIND, "--port", str(ORCH_PORT), "--log-level", "info"],
        cwd=ORCH_DIR, env=env,
        stdout=log_fh, stderr=subprocess.STDOUT,
    )
    info(f"Orchestrator PID: {proc.pid}")

    for i in range(30):
        try:
            if requests.get(f"{ORCH_BASE}/docs", timeout=2).status_code == 200:
                ok(f"Orchestrator ready at {ORCH_BASE} (took {i+1}s)")
                return proc
        except Exception:
            pass
        time.sleep(1)

    die("Orchestrator failed to start within 30s")


def stop_orchestrator(proc):
    if proc and proc.poll() is None:
        info("Stopping orchestrator...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        ok("Orchestrator stopped")


# ── Emulator build ────────────────────────────────────────────────────────

def build_emulator_packages():
    """Build Java emulator jar and create deployment tar.gz packages."""
    banner("Building Java emulator packages")

    # Find Java 17
    java_home = os.environ.get("JAVA_HOME", "")
    if not java_home:
        # Try common locations
        for candidate in ["/usr/lib/jvm/java-17-openjdk", "/usr/lib/jvm/java-17",
                          r"C:\jdk-17.0.18.8-hotspot"]:
            if os.path.isdir(candidate):
                java_home = candidate
                break
    if not java_home:
        die("JAVA_HOME not set and Java 17 not found in standard locations")

    build_env = os.environ.copy()
    build_env["JAVA_HOME"] = java_home
    build_env["PATH"] = os.path.join(java_home, "bin") + os.pathsep + build_env["PATH"]
    info(f"Using JAVA_HOME={java_home}")

    mvn_cmd = "mvn" if IS_LINUX else ["mvn"]
    result = subprocess.run(
        [*([mvn_cmd] if isinstance(mvn_cmd, str) else mvn_cmd), "package", "-DskipTests", "-q"],
        cwd=EMULATOR_JAVA_DIR, capture_output=True, text=True, timeout=120,
        env=build_env, shell=(not IS_LINUX),
    )
    if result.returncode != 0:
        die(f"Maven build failed:\n{result.stdout}\n{result.stderr}")

    jar_path = os.path.join(EMULATOR_JAVA_DIR, "target", "emulator.jar")
    if not os.path.isfile(jar_path):
        die(f"emulator.jar not found at {jar_path}")

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    for plat, script in [("linux", "start.sh"), ("windows", "start.ps1")]:
        pkg_name = f"emulator-java-{plat}"
        tar_path = os.path.join(ARTIFACTS_DIR, f"{pkg_name}.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(jar_path, arcname=f"{pkg_name}/emulator.jar")
            tar.add(os.path.join(EMULATOR_JAVA_DIR, script), arcname=f"{pkg_name}/{script}")
            if os.path.isdir(EMULATOR_DATA_DIR):
                for root, dirs, files in os.walk(EMULATOR_DATA_DIR):
                    for fname in files:
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, EMULATOR_DATA_DIR)
                        try:
                            tar.add(full, arcname=f"{pkg_name}/data/{rel}".replace("\\", "/"))
                        except (OSError, FileNotFoundError):
                            pass
        tar_mb = os.path.getsize(tar_path) / (1024 * 1024)
        ok(f"Created {pkg_name}.tar.gz ({tar_mb:.1f} MB)")


# ── DB state checking ─────────────────────────────────────────────────────

def check_db_state(test_run_id: int) -> dict:
    """Query DB for calibration/comparison progress."""
    try:
        from orchestrator.models.database import SessionLocal
        from orchestrator.models.orm import (
            BaselineTestRun as BTRORM,
            CalibrationResult as CalORM,
            ComparisonResult as CmpORM,
        )
        session = SessionLocal()
        tr = session.get(BTRORM, test_run_id)
        if not tr:
            session.close()
            return {}

        result = {
            "state": tr.state.value,
            "current_profile": tr.current_load_profile_id,
            "error": tr.error_message,
            "verdict": tr.verdict.value if tr.verdict else None,
        }

        cals = session.query(CalORM).filter_by(baseline_test_run_id=test_run_id).all()
        if cals:
            result["calibration"] = [{
                "server_id": c.server_id, "profile_id": c.load_profile_id,
                "threads": getattr(c, "current_thread_count", c.thread_count),
                "status": c.status, "cpu": c.last_observed_cpu,
                "iteration": c.current_iteration,
                "phase": getattr(c, "phase", None),
                "message": getattr(c, "message", None),
            } for c in cals]

        cmps = session.query(CmpORM).filter_by(baseline_test_run_id=test_run_id).all()
        if cmps:
            result["comparisons"] = [{
                "target_id": c.target_id, "profile_id": c.load_profile_id,
                "verdict": c.verdict.value if c.verdict else None,
                "violations": c.violation_count,
            } for c in cmps]

        session.close()
        return result
    except Exception as e:
        return {"db_error": str(e)}


def print_state_update(state, db_info, prev_state):
    if state != prev_state:
        banner(f"STATE: {state.upper()} -- {STATE_DESCRIPTIONS.get(state, '')}")

    if "calibration" in db_info:
        for cal in db_info["calibration"]:
            info(f"  Calibration: server={cal['server_id']} profile={cal['profile_id']} "
                 f"threads={cal['threads']} cpu={cal['cpu']}% "
                 f"status={cal['status']} iter={cal['iteration']} "
                 f"phase={cal.get('phase')}")
            if cal.get("message"):
                info(f"    {cal['message']}")

    if "comparisons" in db_info:
        for cmp in db_info["comparisons"]:
            info(f"  Comparison: target={cmp['target_id']} profile={cmp['profile_id']} "
                 f"verdict={cmp['verdict']} violations={cmp['violations']}")

    if db_info.get("current_profile"):
        info(f"  Current load profile ID: {db_info['current_profile']}")


# ── Emulator health check ────────────────────────────────────────────────

def check_emulator_health(resolved_targets: list[dict]):
    for t in resolved_targets:
        try:
            resp = requests.get(f"http://{t['ip']}:8080/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                info(f"  {t['hostname']} ({t['ip']}): healthy, "
                     f"uptime={data.get('uptime_sec', '?')}s")
            else:
                fail(f"  {t['hostname']} ({t['ip']}): HTTP {resp.status_code}")
        except Exception as e:
            fail(f"  {t['hostname']} ({t['ip']}): unreachable ({e})")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Config-driven baseline test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--test-case", "-tc", required=True,
                        help="Path to test case YAML file")
    parser.add_argument("--type", "-t", dest="test_type", required=True,
                        choices=["new_baseline", "compare", "compare_with_new_calibration"],
                        help="Test type")
    parser.add_argument("--baseline-run", type=int, default=None,
                        help="Baseline run ID to compare against (for compare types). "
                             "If omitted, auto-detects from stored snapshot data.")
    parser.add_argument("--profiles", "-p", default=None,
                        help="Override profiles (comma-separated). Uses test case profiles if omitted.")
    parser.add_argument("--duration", "-d", type=int, default=None,
                        help="Override test duration in seconds (e.g. 3600 for 1 hour). "
                             "Overrides both test case YAML and DB values.")
    parser.add_argument("--template", default=None,
                        help="Override template type (e.g. server-steady, server-normal). "
                             "Uses test case value if omitted.")
    parser.add_argument("--snapshot", "-s", default=None,
                        help="Override snapshot name for all targets (e.g. 'clean-os-baseline'). "
                             "Uses per-target YAML value or latest in DB if omitted.")
    parser.add_argument("--only", default=None,
                        help="Run only these targets (comma-separated hostnames)")
    parser.add_argument("--skip-orchestrator", action="store_true",
                        help="Don't start/stop orchestrator (assumes already running)")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip emulator Maven build")
    args = parser.parse_args()

    # Load test case
    tc = load_test_case(args.test_case)

    # Override profiles if specified
    profile_names = [p.strip() for p in args.profiles.split(",")] if args.profiles else tc["profiles"]

    # Resolve template: CLI > test case YAML
    template = args.template or tc["template"]

    # Resolve duration: CLI > test case YAML > DB (None = use DB value)
    duration_override = args.duration or tc.get("duration_sec")

    # Parse --only filter
    only_filter = [h.strip() for h in args.only.split(",")] if args.only else None

    banner(f"TEST: {tc['name']}")
    info(f"Test case:  {args.test_case}")
    info(f"Type:       {args.test_type}")
    info(f"Template:   {template}")
    info(f"Profiles:   {', '.join(profile_names)}")
    if duration_override:
        info(f"Duration:   {duration_override}s ({duration_override // 60}m)")
    info(f"Targets:    {len(tc['targets'])} defined" +
         (f", filtered to {len(only_filter)}" if only_filter else ""))

    # Build emulator packages
    if not args.skip_build:
        build_emulator_packages()
    else:
        info("Skipping emulator build (--skip-build)")

    # Start orchestrator
    orch_proc = None
    if not args.skip_orchestrator:
        orch_proc = start_orchestrator()
    else:
        try:
            requests.get(f"{ORCH_BASE}/docs", timeout=5)
            ok(f"Orchestrator already running at {ORCH_BASE}")
        except Exception:
            die(f"Orchestrator not reachable at {ORCH_BASE}")

    try:
        # Resolve everything from DB
        banner("Resolving test case from database")
        session = _init_db()

        resolved_targets = resolve_servers(session, tc, only_filter, args.snapshot)
        scenario_id = resolve_scenario(session, template)
        profile_ids = resolve_profiles(session, profile_names, duration_override)

        info(f"Template: '{template}' -> scenario id={scenario_id}")
        for name, pid in zip(profile_names, profile_ids):
            info(f"Profile: '{name}' -> id={pid}")
        for rt in resolved_targets:
            info(f"Target: {rt['hostname']} (id={rt['server_id']}, snap={rt['snapshot_id']}, "
                 f"lg={rt['loadgen_hostname']}:{rt['loadgen_id']})")

        # Resolve compare snapshots if needed
        compare_map = {}
        if args.test_type != "new_baseline":
            banner("Resolving baseline snapshots for comparison")
            compare_map = resolve_compare_snapshots(
                session, resolved_targets, args.baseline_run)
            for rt in resolved_targets:
                snap_id = compare_map.get(rt["server_id"])
                info(f"  {rt['hostname']} -> compare_snapshot_id={snap_id}")

        session.close()

        # Login
        banner("Authentication")
        headers = login()

        # Pre-flight health check
        banner("Pre-flight: emulator health check")
        check_emulator_health(resolved_targets)

        # Build API payload
        targets_payload = []
        for rt in resolved_targets:
            entry = {
                "server_id": rt["server_id"],
                "test_snapshot_id": rt["snapshot_id"],
                "loadgenerator_id": rt["loadgen_id"],
            }
            if args.test_type != "new_baseline":
                entry["compare_snapshot_id"] = compare_map[rt["server_id"]]
            targets_payload.append(entry)

        create_payload = {
            "scenario_id": scenario_id,
            "test_type": args.test_type,
            "load_profile_ids": profile_ids,
            "targets": targets_payload,
        }

        # Create test run
        banner("Creating baseline test run")
        info(f"Payload:\n{json.dumps(create_payload, indent=2)}")
        result = api_post("/baseline-tests", headers, create_payload)
        if not result:
            sys.exit(1)

        test_run_id = result["id"]
        ok(f"Created test run id={test_run_id}, state={result['state']}")

        # Start
        banner("Starting test run")
        start_result = api_post(f"/baseline-tests/{test_run_id}/start", headers)
        if not start_result:
            sys.exit(1)
        ok(f"Test run {test_run_id} started: {start_result['message']}")

        # Poll
        banner("Monitoring test progress")
        info(f"Polling every {POLL_SEC}s (max {MAX_WAIT_SEC}s)")
        info("Cancel with Ctrl+C")

        start_time = time.time()
        prev_state = None
        state = "created"

        while True:
            elapsed = time.time() - start_time
            if elapsed > MAX_WAIT_SEC:
                fail(f"Timeout after {MAX_WAIT_SEC}s")
                break

            status_data = api_get(f"/baseline-tests/{test_run_id}", headers)
            if not status_data:
                info("  (API unreachable, retrying...)")
                time.sleep(POLL_SEC)
                continue

            state = status_data["state"]
            db_info = check_db_state(test_run_id)
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
        info(f"Test run ID:  {test_run_id}")
        info(f"Test case:    {tc['name']}")
        info(f"Duration:     {minutes}m {seconds}s")
        info(f"Final state:  {state}")

        if state == "completed":
            info(f"Verdict: {status_data.get('verdict', 'N/A')}")
            ok("TEST COMPLETED SUCCESSFULLY")

            comparisons = api_get(f"/baseline-tests/{test_run_id}/comparison-results", headers)
            if comparisons:
                info("\nComparison Results:")
                for cr in comparisons:
                    info(f"  Target {cr['target_id']}, Profile {cr['load_profile_id']}: "
                         f"verdict={cr['verdict']}, violations={cr['violation_count']}")
        elif state == "failed":
            fail(f"ERROR: {status_data.get('error_message', 'Unknown error')}")
        elif state == "cancelled":
            info("Test was cancelled")

        return 0 if state == "completed" else 1

    except KeyboardInterrupt:
        print(f"\n\n  {ts()}  Interrupted by user")
        try:
            info(f"Cancelling test run {test_run_id}...")
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
