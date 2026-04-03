#!/usr/bin/env python3
"""Agent Performance Testing — Interactive CLI Tool.

Project-based workflow for testing security agent impact on servers.
Supports 4 projects: CrowdStrike, Tanium, PkWare, Thales CTE.

Usage:
    python run_test.py
    python run_test.py --url http://orchestrator:8000
    python run_test.py --last-errors
    python run_test.py --last-errors 20
"""

import argparse
import getpass
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"run_test_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_test")

# Also log INFO+ to console
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(console)


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------
class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.session = requests.Session()

    def login(self, username, password):
        resp = self._post("/api/auth/login", data={"username": username, "password": password}, is_form=True)
        self.token = resp.get("access_token")
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        return resp

    def _url(self, path):
        return f"{self.base_url}{path}"

    def _post(self, path, data=None, json_data=None, is_form=False):
        url = self._url(path)
        logger.debug("POST %s %s", url, json.dumps(json_data or data or {}, default=str)[:500])
        if is_form:
            resp = self.session.post(url, data=data)
        else:
            resp = self.session.post(url, json=json_data or data)
        logger.debug("Response %d: %s", resp.status_code, resp.text[:500])
        if resp.status_code >= 400:
            logger.error("API error %d: %s", resp.status_code, resp.text[:500])
            raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 204:
            return {}
        return resp.json()

    def _get(self, path, params=None):
        url = self._url(path)
        logger.debug("GET %s %s", url, params or "")
        resp = self.session.get(url, params=params)
        logger.debug("Response %d: %s", resp.status_code, resp.text[:500])
        if resp.status_code >= 400:
            logger.error("API error %d: %s", resp.status_code, resp.text[:500])
            raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _put(self, path, data):
        url = self._url(path)
        logger.debug("PUT %s %s", url, json.dumps(data, default=str)[:500])
        resp = self.session.put(url, json=data)
        logger.debug("Response %d: %s", resp.status_code, resp.text[:500])
        if resp.status_code >= 400:
            raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _delete(self, path):
        url = self._url(path)
        logger.debug("DELETE %s", url)
        resp = self.session.delete(url)
        if resp.status_code >= 400:
            raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
        return {}

    # --- Convenience methods ---
    def list_servers(self, role=None):
        params = {"role": role} if role else {}
        return self._get("/api/admin/servers", params)

    def list_agents(self):
        return self._get("/api/admin/agents")

    def get_agent(self, agent_id):
        return self._get(f"/api/admin/agents/{agent_id}")

    def create_agent(self, data):
        return self._post("/api/admin/agents", json_data=data)

    def list_detection_rules(self, agent_id):
        return self._get(f"/api/admin/agents/{agent_id}/detection-rules")

    def create_detection_rule(self, agent_id, data):
        return self._post(f"/api/admin/agents/{agent_id}/detection-rules", json_data=data)

    def list_agent_sets(self):
        return self._get("/api/admin/subgroup-definitions")

    def create_agent_set(self, data):
        return self._post("/api/admin/subgroup-definitions", json_data=data)

    def list_load_profiles(self):
        return self._get("/api/admin/load-profiles")

    def list_tests(self):
        return self._get("/api/baseline-tests")

    def create_test(self, data):
        return self._post("/api/baseline-tests/v2", json_data=data)

    def start_test(self, run_id):
        return self._post(f"/api/baseline-tests/{run_id}/start")

    def get_test(self, run_id):
        return self._get(f"/api/baseline-tests/{run_id}")

    def list_snapshots(self, server_id):
        return self._get(f"/api/servers/{server_id}/snapshots")

    def take_snapshot(self, server_id, name, description="", group_id=None):
        data = {"name": name, "description": description}
        if group_id:
            data["group_id"] = group_id
        return self._post(f"/api/servers/{server_id}/snapshots/take", json_data=data)

    def revert_snapshot(self, server_id, snapshot_id):
        return self._post(f"/api/servers/{server_id}/snapshots/{snapshot_id}/revert")

    def get_server_baselines(self, server_id):
        return self._get(f"/api/servers/{server_id}/snapshot-baselines")

    def update_server(self, server_id, data):
        return self._put(f"/api/admin/servers/{server_id}", data)

    def prepare_server(self, server_id, delete_all=False):
        return self._post(f"/api/admin/servers/{server_id}/prepare-snapshot",
                          json_data={"delete_all_snapshots": delete_all})

    def get_prepare_status(self, server_id):
        return self._get(f"/api/admin/servers/{server_id}/prepare-status")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def prompt(msg, default=None):
    if default:
        val = input(f"  {msg} [{default}]: ").strip()
        return val if val else default
    return input(f"  {msg}: ").strip()


def prompt_choice(msg, options, allow_multiple=False):
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    if allow_multiple:
        val = input(f"  {msg} (comma-separated): ").strip()
        indices = [int(x.strip()) - 1 for x in val.split(",") if x.strip().isdigit()]
        return [options[i] for i in indices if 0 <= i < len(options)]
    while True:
        val = input(f"  {msg}: ").strip()
        if val.isdigit() and 1 <= int(val) <= len(options):
            return options[int(val) - 1]
        print(f"  Invalid choice. Enter 1-{len(options)}")


def prompt_yn(msg, default=True):
    suffix = "[Y/n]" if default else "[y/N]"
    val = input(f"  {msg} {suffix}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def wait_for_test(api, run_id, poll_sec=15):
    """Poll test status until terminal state."""
    terminal = {"completed", "failed", "cancelled"}
    print(f"\n  Monitoring test #{run_id}...")
    print(f"  Dashboard: {api.base_url}/baseline-tests/{run_id}/dashboard")
    while True:
        try:
            test = api.get_test(run_id)
            state = test.get("state", "unknown")
            lp_name = ""
            if test.get("current_load_profile_id"):
                lp_name = f" (LP: {test['current_load_profile_id']}, cycle: {test.get('current_cycle', '?')})"
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] State: {state}{lp_name}")
            if state in terminal:
                return test
        except Exception as e:
            print(f"  Poll error: {e}")
        time.sleep(poll_sec)


def setup_sudo_for_user(api, server, sudo_username, sudo_password):
    """Add a user to sudoers on a server via the service account."""
    print(f"\n  Adding '{sudo_username}' to sudoers on {server['hostname']}...")
    # We need to SSH via the service account — use the prepare endpoint's
    # inline approach, but simpler: just call a one-off SSH command
    # This requires paramiko
    try:
        import paramiko
    except ImportError:
        print("  ERROR: paramiko not installed. Run: pip install paramiko")
        print(f"  Manual alternative: SSH into {server['ip_address']} and run:")
        print(f"    sudo bash -c \"echo '{sudo_username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{sudo_username.replace(chr(92), '_')}\"")
        print(f"    sudo chmod 440 /etc/sudoers.d/{sudo_username.replace(chr(92), '_')}")
        return False

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # Connect with service account credentials from the API
        # We don't have credentials directly — ask user
        print(f"  SSH credentials for {server['hostname']} ({server['ip_address']}):")
        ssh_user = prompt("SSH username (service account)")
        ssh_pass = getpass.getpass("  SSH password: ")

        client.connect(server['ip_address'], username=ssh_user, password=ssh_pass, timeout=30)

        safe_name = sudo_username.replace("\\", "_").replace("@", "_")
        SUDO_S = f"echo '{ssh_pass}' | sudo -S"

        commands = [
            f"{SUDO_S} bash -c \"echo '{sudo_username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{safe_name}\" 2>&1",
            f"{SUDO_S} chmod 440 /etc/sudoers.d/{safe_name} 2>&1",
            f"{SUDO_S} visudo -cf /etc/sudoers.d/{safe_name} 2>&1",
        ]
        for cmd in commands:
            stdin, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if err and "password" not in err.lower():
                logger.warning("sudo cmd stderr: %s", err)

        # Verify
        stdin, stdout, stderr = client.exec_command(f"sudo -u {sudo_username} sudo -n whoami 2>&1")
        result = stdout.read().decode().strip()
        client.close()

        if "root" in result:
            print(f"  Passwordless sudo configured for '{sudo_username}'")
            return True
        else:
            print(f"  WARNING: Verification returned: {result}")
            print(f"  Sudo may not be working. Check manually.")
            return True  # Continue anyway
    except Exception as e:
        print(f"  ERROR: {e}")
        print(f"  Add manually: SSH into {server['ip_address']} and run:")
        safe_name = sudo_username.replace("\\", "_").replace("@", "_")
        print(f"    sudo bash -c \"echo '{sudo_username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{safe_name}\"")
        return False


# ---------------------------------------------------------------------------
# Agent Setup
# ---------------------------------------------------------------------------
def ensure_agent(api, name, vendor, agent_type="edr"):
    """Ensure agent exists, create if not. Return agent dict."""
    agents = api.list_agents()
    for a in agents:
        if a["name"].lower() == name.lower():
            return a
    print(f"\n  Creating agent: {name}")
    return api.create_agent({"name": name, "vendor": vendor, "agent_type": agent_type})


def ensure_detection_rules(api, agent):
    """Ensure detection rules exist for RHEL and Windows. Interactive if missing."""
    agent_id = agent["id"]
    rules = api.list_detection_rules(agent_id)

    has_rhel = any(r for r in rules if "rhel" in r.get("os_regex", "").lower() or "rocky" in r.get("os_regex", "").lower())
    has_win = any(r for r in rules if "windows" in r.get("os_regex", "").lower())

    print(f"\n  Agent: {agent['name']} (ID={agent_id})")
    print(f"  Detection rules:")
    if rules:
        for r in rules:
            print(f"    [{r['cmd_type']}] os={r['os_regex']} service={r['service_regex']} version_cmd={r.get('version_cmd', '-')}")
    else:
        print(f"    (none)")

    if not has_rhel:
        print(f"\n  RHEL/Rocky detection rule needed for {agent['name']}:")
        service_regex = prompt(f"RHEL service regex (e.g. falcon-sensor*)")
        version_cmd = prompt(f"RHEL version command", "")
        if service_regex:
            api.create_detection_rule(agent_id, {
                "os_regex": "rhel|rocky|centos",
                "cmd_type": "bash",
                "service_regex": service_regex,
                "version_cmd": version_cmd or None,
            })
            print(f"  RHEL detection rule saved.")

    if not has_win:
        print(f"\n  Windows detection rule needed for {agent['name']}:")
        service_regex = prompt(f"Windows service regex (e.g. CrowdStrike*)")
        version_cmd = prompt(f"Windows version command", "")
        if service_regex:
            api.create_detection_rule(agent_id, {
                "os_regex": "windows",
                "cmd_type": "powershell",
                "service_regex": service_regex,
                "version_cmd": version_cmd or None,
            })
            print(f"  Windows detection rule saved.")

    # Return updated rules
    return api.list_detection_rules(agent_id)


def get_monitoring_patterns(api, agent_ids, server_os):
    """Derive service_monitor_patterns from agents' detection rules matching server OS."""
    patterns = []
    for aid in agent_ids:
        rules = api.list_detection_rules(aid)
        for r in rules:
            import re
            if re.search(r["os_regex"], server_os, re.IGNORECASE):
                patterns.append(r["service_regex"])
    return patterns


# ---------------------------------------------------------------------------
# Agent Set Setup
# ---------------------------------------------------------------------------
def ensure_agent_set(api, name, agent_ids):
    """Ensure agent set exists, create if not."""
    sets = api.list_agent_sets()
    for s in sets:
        if s["name"].lower() == name.lower():
            return s
    print(f"  Creating agent set: {name}")
    return api.create_agent_set({"name": name, "agent_ids": agent_ids})


# ---------------------------------------------------------------------------
# Snapshot Management
# ---------------------------------------------------------------------------
def find_snapshot_by_name(api, server_id, name_contains):
    """Find a snapshot by partial name match."""
    snaps = api.list_snapshots(server_id)
    for s in snaps:
        if not s["is_archived"] and name_contains.lower() in s["name"].lower():
            return s
    return None


def setup_snapshot(api, servers, snapshot_name, revert_to_snapshot_name=None):
    """Interactive snapshot setup for servers.

    Reverts each server (to OS Level or named snapshot), waits for user
    to install agents, then takes snapshot.
    """
    print(f"\n{'='*60}")
    print(f"  SNAPSHOT SETUP: {snapshot_name}")
    print(f"{'='*60}")

    snapshots = {}
    for srv in servers:
        sid = srv["id"]
        hostname = srv["hostname"]

        # Check if snapshot already exists
        existing = find_snapshot_by_name(api, sid, snapshot_name)
        if existing:
            print(f"\n  {hostname}: Snapshot '{existing['name']}' already exists (ID={existing['id']})")
            if prompt_yn(f"Use existing snapshot?"):
                snapshots[sid] = existing
                continue

        # Determine what to revert to
        if revert_to_snapshot_name:
            revert_snap = find_snapshot_by_name(api, sid, revert_to_snapshot_name)
            if not revert_snap:
                print(f"  ERROR: Cannot find snapshot '{revert_to_snapshot_name}' on {hostname}")
                print(f"  Available snapshots:")
                for s in api.list_snapshots(sid):
                    if not s["is_archived"]:
                        print(f"    {s['name']} (ID={s['id']})")
                continue
            revert_id = revert_snap["id"]
            revert_label = revert_snap["name"]
        else:
            # Revert to OS Level (root snapshot)
            if not srv.get("root_snapshot_id"):
                print(f"  ERROR: {hostname} has no root snapshot. Run Prepare & Snapshot first.")
                continue
            revert_id = srv["root_snapshot_id"]
            revert_label = "OS Level (root)"

        print(f"\n  {hostname}: Reverting to '{revert_label}'...")
        try:
            api.revert_snapshot(sid, revert_id)
            print(f"  Reverted. VM may take a minute to come up.")
        except Exception as e:
            print(f"  ERROR reverting: {e}")
            if not prompt_yn("Continue anyway?", False):
                continue

        print(f"\n  *** SSH into {hostname} ({srv['ip_address']}) and install agents ***")
        print(f"      ssh user@{srv['ip_address']}")
        input(f"\n  Press ENTER when agents are installed and ready to take snapshot...")

        # Take snapshot
        actual_name = prompt("Snapshot name", snapshot_name)
        try:
            snap = api.take_snapshot(sid, actual_name, f"Agent snapshot: {actual_name}")
            print(f"  Snapshot taken: {snap['name']} (ID={snap['id']})")
            snapshots[sid] = snap
        except Exception as e:
            print(f"  ERROR taking snapshot: {e}")

    return snapshots


# ---------------------------------------------------------------------------
# Test Creation
# ---------------------------------------------------------------------------
def create_and_run_test(api, name, test_type, targets, duration_minutes,
                        parent_run_id=None, template="server-steady"):
    """Create a test and start it.

    targets: list of dicts with server_id, loadgen_id, test_snapshot_id,
             compare_snapshot_id (optional), service_monitor_patterns (optional)
    """
    load_profiles = api.list_load_profiles()
    if not load_profiles:
        print("  ERROR: No load profiles configured")
        return None

    duration_sec = duration_minutes * 60
    ramp_up_sec = 60  # standard

    lp_entries = [
        {"load_profile_id": lp["id"], "duration_sec": duration_sec, "ramp_up_sec": ramp_up_sec}
        for lp in load_profiles
    ]

    payload = {
        "name": name,
        "test_type": test_type,
        "template_type": template,
        "cycle_count": 2,
        "targets": targets,
        "load_profiles": lp_entries,
    }
    if parent_run_id:
        payload["parent_run_id"] = parent_run_id

    print(f"\n  Creating test: {name}")
    print(f"    Type: {test_type}")
    print(f"    Duration: {duration_minutes} min per profile, 2 cycles")
    print(f"    Profiles: {', '.join(lp['name'] for lp in load_profiles)}")
    print(f"    Servers: {len(targets)}")

    test = api.create_test(payload)
    run_id = test["id"]
    print(f"  Test created: #{run_id}")

    if prompt_yn("Start test now?"):
        api.start_test(run_id)
        print(f"  Test #{run_id} started.")
        if prompt_yn("Wait for completion?"):
            result = wait_for_test(api, run_id)
            print(f"\n  Test #{run_id} finished: {result['state']}")
            return result
    return test


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def find_completed_baseline(api):
    """Find a completed OS Level Test."""
    tests = api.list_tests()
    baselines = [t for t in tests if t["test_type"] == "new_baseline" and t["state"] == "completed"]
    if not baselines:
        return None
    baselines.sort(key=lambda t: t.get("completed_at", ""), reverse=True)
    return baselines[0]


def run_baseline(api, targets_info, duration_minutes):
    """Create and run OS Level Test."""
    targets = []
    for srv, lg in targets_info:
        targets.append({
            "server_id": srv["id"],
            "loadgenerator_id": lg["id"],
            "test_snapshot_id": srv["root_snapshot_id"],
        })
    return create_and_run_test(
        api, f"OS Level Baseline {datetime.now().strftime('%Y-%m-%d')}",
        "new_baseline", targets, duration_minutes,
    )


def run_agent_set_test(api, parent_run, agent_set_name, targets_with_snaps, duration_minutes):
    """Create and run Agent Set Test."""
    parent_targets = {t["target_id"]: t for t in parent_run.get("targets", [])}
    targets = []
    for srv_id, snap in targets_with_snaps.items():
        pt = parent_targets.get(srv_id, {})
        targets.append({
            "server_id": srv_id,
            "loadgenerator_id": pt.get("loadgenerator_id"),
            "test_snapshot_id": snap["id"],
            "compare_snapshot_id": pt.get("test_snapshot_id"),
            "service_monitor_patterns": snap.get("_monitor_patterns"),
        })
    return create_and_run_test(
        api, f"{agent_set_name} — {datetime.now().strftime('%Y-%m-%d')}",
        "compare", targets, duration_minutes,
        parent_run_id=parent_run["id"],
    )


def project_crowdstrike(api, targets_info, baseline_run):
    """Project CrowdStrike: Setup agent, create snapshots, run tests."""
    print(f"\n{'='*60}")
    print(f"  PROJECT: CrowdStrike")
    print(f"{'='*60}")

    # Step 1: Agent setup
    cs_agent = ensure_agent(api, "CrowdStrike", "CrowdStrike Inc.", "edr")
    cs_rules = ensure_detection_rules(api, cs_agent)

    # Step 2: Agent set
    cs_set = ensure_agent_set(api, "CrowdStrike Only", [cs_agent["id"]])

    # Step 3: Snapshot — CrowdStrike only
    servers = [srv for srv, _ in targets_info]
    cs_snaps = setup_snapshot(api, servers, "CrowdStrike-only")

    # Add monitoring patterns
    for sid, snap in cs_snaps.items():
        srv = next(s for s, _ in targets_info if s["id"] == sid)
        patterns = get_monitoring_patterns(api, [cs_agent["id"]], srv.get("os_vendor_family", "rhel"))
        snap["_monitor_patterns"] = patterns
        print(f"  {srv['hostname']} monitoring: {patterns}")

    # Step 4: Test — CrowdStrike Only 15 min
    print(f"\n--- CrowdStrike Only — 15 minute test ---")
    if prompt_yn("Run 15-minute test?"):
        run_agent_set_test(api, baseline_run, "CrowdStrike Only (15min)", cs_snaps, 15)

    # Step 5: Test — CrowdStrike Only 90 min
    print(f"\n--- CrowdStrike Only — 90 minute test ---")
    if prompt_yn("Run 90-minute test?"):
        run_agent_set_test(api, baseline_run, "CrowdStrike Only (90min)", cs_snaps, 90)

    return cs_agent, cs_snaps


def project_tanium(api, targets_info, baseline_run, cs_agent):
    """Project Tanium: Setup agent, create snapshots, run tests."""
    print(f"\n{'='*60}")
    print(f"  PROJECT: Tanium")
    print(f"{'='*60}")

    # Step 1: Agent setup
    tan_agent = ensure_agent(api, "Tanium", "Tanium Inc.", "monitoring")
    tan_rules = ensure_detection_rules(api, tan_agent)

    # Step 2: Agent sets
    tan_set = ensure_agent_set(api, "Tanium Only", [tan_agent["id"]])
    cstan_set = ensure_agent_set(api, "CrowdStrike + Tanium", [cs_agent["id"], tan_agent["id"]])

    servers = [srv for srv, _ in targets_info]

    # Step 3: Snapshot — Tanium only
    tan_snaps = setup_snapshot(api, servers, "Tanium-only")
    for sid, snap in tan_snaps.items():
        srv = next(s for s, _ in targets_info if s["id"] == sid)
        snap["_monitor_patterns"] = get_monitoring_patterns(api, [tan_agent["id"]], srv.get("os_vendor_family", "rhel"))

    # Step 4: Snapshot — CS+Tanium (revert to CrowdStrike-only, add Tanium)
    print(f"\n  For CS+Tanium snapshot: will revert to 'CrowdStrike-only' and install Tanium on top.")
    cstan_snaps = setup_snapshot(api, servers, "CS+Tanium", revert_to_snapshot_name="CrowdStrike-only")
    for sid, snap in cstan_snaps.items():
        srv = next(s for s, _ in targets_info if s["id"] == sid)
        snap["_monitor_patterns"] = get_monitoring_patterns(api, [cs_agent["id"], tan_agent["id"]], srv.get("os_vendor_family", "rhel"))

    # Step 5: Test — Tanium Only 15 + 90 min
    print(f"\n--- Tanium Only — 15 minute test ---")
    if prompt_yn("Run 15-minute test?"):
        run_agent_set_test(api, baseline_run, "Tanium Only (15min)", tan_snaps, 15)

    print(f"\n--- Tanium Only — 90 minute test ---")
    if prompt_yn("Run 90-minute test?"):
        run_agent_set_test(api, baseline_run, "Tanium Only (90min)", tan_snaps, 90)

    # Step 6: Test — CS+Tanium 15 + 90 min
    print(f"\n--- CrowdStrike + Tanium — 15 minute test ---")
    if prompt_yn("Run 15-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium (15min)", cstan_snaps, 15)

    print(f"\n--- CrowdStrike + Tanium — 90 minute test ---")
    if prompt_yn("Run 90-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium (90min)", cstan_snaps, 90)

    return tan_agent, cstan_snaps


def project_pkware(api, targets_info, baseline_run, cs_agent, tan_agent):
    """Project PkWare: Build on CS+Tanium, add PkWare."""
    print(f"\n{'='*60}")
    print(f"  PROJECT: PkWare")
    print(f"{'='*60}")

    pk_agent = ensure_agent(api, "PkWare", "PKWARE Inc.", "dlp")
    pk_rules = ensure_detection_rules(api, pk_agent)

    pk_set = ensure_agent_set(api, "CS + Tanium + PkWare", [cs_agent["id"], tan_agent["id"], pk_agent["id"]])

    servers = [srv for srv, _ in targets_info]

    # Snapshot: revert to CS+Tanium, install PkWare
    print(f"\n  For CS+Tanium+PkWare snapshot: will revert to 'CS+Tanium' and install PkWare on top.")
    snaps = setup_snapshot(api, servers, "CS+Tanium+PkWare", revert_to_snapshot_name="CS+Tanium")
    for sid, snap in snaps.items():
        srv = next(s for s, _ in targets_info if s["id"] == sid)
        snap["_monitor_patterns"] = get_monitoring_patterns(
            api, [cs_agent["id"], tan_agent["id"], pk_agent["id"]], srv.get("os_vendor_family", "rhel"))

    print(f"\n--- CS + Tanium + PkWare — 15 minute test ---")
    if prompt_yn("Run 15-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium+PkWare (15min)", snaps, 15)

    print(f"\n--- CS + Tanium + PkWare — 90 minute test ---")
    if prompt_yn("Run 90-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium+PkWare (90min)", snaps, 90)


def project_thales(api, targets_info, baseline_run, cs_agent, tan_agent):
    """Project Thales CTE: Build on CS+Tanium, add Thales."""
    print(f"\n{'='*60}")
    print(f"  PROJECT: Thales CTE")
    print(f"{'='*60}")

    th_agent = ensure_agent(api, "Thales CTE", "Thales Group", "dlp")
    th_rules = ensure_detection_rules(api, th_agent)

    th_set = ensure_agent_set(api, "CS + Tanium + Thales CTE", [cs_agent["id"], tan_agent["id"], th_agent["id"]])

    servers = [srv for srv, _ in targets_info]

    print(f"\n  For CS+Tanium+Thales snapshot: will revert to 'CS+Tanium' and install Thales on top.")
    snaps = setup_snapshot(api, servers, "CS+Tanium+ThalesCTE", revert_to_snapshot_name="CS+Tanium")
    for sid, snap in snaps.items():
        srv = next(s for s, _ in targets_info if s["id"] == sid)
        snap["_monitor_patterns"] = get_monitoring_patterns(
            api, [cs_agent["id"], tan_agent["id"], th_agent["id"]], srv.get("os_vendor_family", "rhel"))

    print(f"\n--- CS + Tanium + Thales CTE — 15 minute test ---")
    if prompt_yn("Run 15-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium+ThalesCTE (15min)", snaps, 15)

    print(f"\n--- CS + Tanium + Thales CTE — 90 minute test ---")
    if prompt_yn("Run 90-minute test?"):
        run_agent_set_test(api, baseline_run, "CS+Tanium+ThalesCTE (90min)", snaps, 90)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def show_last_errors(count=10):
    """Show last N errors from log file."""
    if not LOG_FILE.exists():
        print("No log file found.")
        return
    errors = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            if "[ERROR]" in line or "Traceback" in line or "Exception" in line:
                errors.append(line.rstrip())
    if not errors:
        print("No errors found in log.")
    else:
        print(f"\nLast {count} errors from {LOG_FILE}:")
        for line in errors[-count:]:
            print(f"  {line}")


def main():
    parser = argparse.ArgumentParser(description="Agent Performance Testing CLI")
    parser.add_argument("--url", default="http://localhost:8000", help="Orchestrator URL")
    parser.add_argument("--last-errors", nargs="?", const=10, type=int, help="Show last N errors from log")
    args = parser.parse_args()

    if args.last_errors is not None:
        show_last_errors(args.last_errors)
        return

    print(f"\n{'='*60}")
    print(f"  Agent Performance Testing CLI")
    print(f"  Log file: {LOG_FILE}")
    print(f"{'='*60}")

    # Login
    url = prompt("Orchestrator URL", args.url)
    api = APIClient(url)

    username = prompt("Username")
    password = getpass.getpass("  Password: ")
    try:
        api.login(username, password)
        print(f"  Logged in as {username}.")
    except Exception as e:
        print(f"  Login failed: {e}")
        return

    # Sudo setup
    print(f"\n--- User Sudo Setup ---")
    if prompt_yn("Setup passwordless sudo for a user on target servers?"):
        sudo_user = prompt("Username to add to sudoers (e.g. DOMAIN\\user or user@domain)")
        targets = api.list_servers(role="target")
        for srv in targets:
            if prompt_yn(f"Add sudo for '{sudo_user}' on {srv['hostname']} ({srv['ip_address']})?"):
                setup_sudo_for_user(api, srv, sudo_user, "")

    while True:
        print(f"\n{'='*60}")
        print(f"  Main Menu")
        print(f"{'='*60}")
        print(f"  1. List servers")
        print(f"  2. Run Baseline (OS Level Test)")
        print(f"  3. Project: CrowdStrike")
        print(f"  4. Project: Tanium")
        print(f"  5. Project: PkWare")
        print(f"  6. Project: Thales CTE")
        print(f"  7. List all tests")
        print(f"  8. Show last errors")
        print(f"  9. Exit")

        choice = prompt("Choice")

        if choice == "1":
            servers = api.list_servers()
            print(f"\n  {'ID':<4} {'Hostname':<20} {'IP':<18} {'Role':<8} {'OS':<15} {'Ready'}")
            print(f"  {'-'*80}")
            for s in servers:
                os_label = f"{(s.get('os_vendor_family') or '').upper()} {s.get('os_major_ver', '')}"
                ready = "YES" if s.get("is_ready") else "no"
                print(f"  {s['id']:<4} {s['hostname']:<20} {s['ip_address']:<18} {s['role']:<8} {os_label:<15} {ready}")

        elif choice == "2":
            # Baseline
            targets = api.list_servers(role="target")
            ready_targets = [t for t in targets if t.get("is_ready")]
            if not ready_targets:
                print("  No ready target servers. Run Prepare & Snapshot first.")
                continue

            loadgens = api.list_servers(role="loadgen")
            if not loadgens:
                print("  No load generators found.")
                continue

            print(f"\n  Available targets ({len(ready_targets)}):")
            for i, t in enumerate(ready_targets, 1):
                lg = next((l for l in loadgens if l["id"] == t.get("default_loadgen_id")), None)
                lg_label = lg["hostname"] if lg else "none"
                print(f"    {i}. {t['hostname']} ({t['ip_address']}) — LG: {lg_label}")

            num = int(prompt("How many targets", str(len(ready_targets))))
            selected = ready_targets[:num]
            targets_info = []
            for srv in selected:
                lg = next((l for l in loadgens if l["id"] == srv.get("default_loadgen_id")), loadgens[0])
                targets_info.append((srv, lg))

            dur = prompt("Duration per profile (minutes)", "15")
            baseline = run_baseline(api, targets_info, int(dur))

        elif choice in ("3", "4", "5", "6"):
            # Projects need baseline + targets
            baseline_run = find_completed_baseline(api)
            if not baseline_run:
                print("  No completed OS Level Test found. Run baseline first (option 2).")
                continue

            baseline_run = api.get_test(baseline_run["id"])  # get full details
            print(f"  Using baseline: #{baseline_run['id']} '{baseline_run.get('name', '')}' ({baseline_run['state']})")

            targets = api.list_servers(role="target")
            loadgens = api.list_servers(role="loadgen")
            targets_info = []
            for t in baseline_run.get("targets", []):
                srv = next((s for s in targets if s["id"] == t["target_id"]), None)
                lg = next((l for l in loadgens if l["id"] == t.get("loadgenerator_id")), None)
                if srv and lg:
                    targets_info.append((srv, lg))

            if choice == "3":
                cs_agent, cs_snaps = project_crowdstrike(api, targets_info, baseline_run)
            elif choice == "4":
                cs_agent = ensure_agent(api, "CrowdStrike", "CrowdStrike Inc.", "edr")
                tan_agent, cstan_snaps = project_tanium(api, targets_info, baseline_run, cs_agent)
            elif choice == "5":
                cs_agent = ensure_agent(api, "CrowdStrike", "CrowdStrike Inc.", "edr")
                tan_agent = ensure_agent(api, "Tanium", "Tanium Inc.", "monitoring")
                project_pkware(api, targets_info, baseline_run, cs_agent, tan_agent)
            elif choice == "6":
                cs_agent = ensure_agent(api, "CrowdStrike", "CrowdStrike Inc.", "edr")
                tan_agent = ensure_agent(api, "Tanium", "Tanium Inc.", "monitoring")
                project_thales(api, targets_info, baseline_run, cs_agent, tan_agent)

        elif choice == "7":
            tests = api.list_tests()
            tests.sort(key=lambda t: t.get("created_at", ""), reverse=True)
            print(f"\n  {'ID':<5} {'Name':<40} {'Type':<15} {'State':<12} {'Created'}")
            print(f"  {'-'*95}")
            for t in tests[:20]:
                name = (t.get("name") or "")[:38]
                created = (t.get("created_at") or "")[:10]
                print(f"  {t['id']:<5} {name:<40} {t['test_type']:<15} {t['state']:<12} {created}")

        elif choice == "8":
            show_last_errors(20)

        elif choice == "9":
            print("  Goodbye!")
            break

        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
