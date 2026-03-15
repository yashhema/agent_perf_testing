"""
Standalone deployment test using REAL orchestrator code paths.

Exercises the same classes the orchestrator uses during _do_setup:
  - ProxmoxProvider.restore_snapshot()  (revert to clean snapshot)
  - ProxmoxProvider.wait_for_vm_ready() (wait for VM to boot)
  - wait_for_ssh()                      (wait for SSH/WinRM port)
  - create_executor()                   (SSHExecutor or WinRMExecutor)
  - PackageResolver.resolve()           (resolve package from DB)
  - PackageDeployer.deploy()            (prereq + upload + extract + install)
  - run_command / status_command        (start + health check)

Usage:
    cd orchestrator
    python ../test_deploy_all.py emulator-linux
    python ../test_deploy_all.py emulator-windows
    python ../test_deploy_all.py jmeter
    python ../test_deploy_all.py all

Logs:
    Each run creates a timestamped log file under logs/ directory.
    Console shows summary; log file has FULL command output + timing.
"""

import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from datetime import datetime

# ── Bootstrap orchestrator imports ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ORCH_DIR = os.path.join(SCRIPT_DIR, "orchestrator")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
sys.path.insert(0, os.path.join(ORCH_DIR, "src"))

from orchestrator.config.settings import load_config
from orchestrator.config.credentials import CredentialsStore
from orchestrator.models.database import init_db, SessionLocal
from orchestrator.models.orm import ServerORM, LabORM, SnapshotORM
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.remote_executor import create_executor
from orchestrator.core.baseline_execution import wait_for_ssh   # the OS-aware version
from orchestrator.services.package_manager import PackageResolver, PackageDeployer


def setup_logging(phases, verbose=False):
    """Set up dual logging: console (summary) + file (full detail).

    Returns the log file path.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    phase_tag = "_".join(phases)
    log_file = os.path.join(LOG_DIR, f"deploy_{phase_tag}_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler — DEBUG level, captures everything
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # Console handler — INFO level (or DEBUG if --verbose)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root_logger.addHandler(ch)

    return log_file


log = logging.getLogger("deploy-test")


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def banner(msg):
    line = "=" * 60
    log.info(line)
    log.info("  %s", msg)
    log.info(line)


def step(n, msg):
    log.info("--- Step %d: %s ---", n, msg)


def ok(msg="OK"):
    log.info("  [OK] %s", msg)


def fail(msg):
    log.error("  [FAIL] %s", msg)


def load_orchestrator():
    """Load config, credentials, init DB, return (config, credentials, session)."""
    config_path = os.path.join(ORCH_DIR, "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url, echo=False)

    creds_path = os.path.join(ORCH_DIR, config.credentials_path)
    credentials = CredentialsStore(creds_path)

    session = SessionLocal()
    return config, credentials, session


def get_lab_and_provider(session, credentials):
    """Load the Proxmox lab and create its hypervisor provider."""
    lab = session.query(LabORM).filter_by(name="Proxmox Lab").first()
    if not lab:
        raise RuntimeError("Lab 'Proxmox Lab' not found in DB. Run setup_proxmox_lab.py first.")

    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )
    return lab, provider


def revert_and_wait(provider, server, snapshot_name):
    """Revert VM to snapshot and wait for SSH/WinRM — same as _do_setup."""
    snapshot_ref = {"snapshot_name": snapshot_name}

    log.info("Reverting VMID %s to '%s'...",
             server.server_infra_ref["vmid"], snapshot_name)
    t0 = time.time()
    provider.restore_snapshot(server.server_infra_ref, snapshot_ref)
    log.debug("restore_snapshot completed in %.1fs", time.time() - t0)

    log.info("Waiting for VM to become running...")
    t0 = time.time()
    ready = provider.wait_for_vm_ready(server.server_infra_ref, timeout_sec=120)
    if not ready:
        fail("VM did not become 'running' within 120s")
        return False
    log.debug("VM running after %.1fs", time.time() - t0)
    ok("VM is running")

    log.info("Waiting for SSH/WinRM port...")
    t0 = time.time()
    try:
        wait_for_ssh(server.ip_address, os_family=server.os_family.value, timeout_sec=120)
        log.debug("Port reachable after %.1fs", time.time() - t0)
        ok(f"Port reachable on {server.ip_address}")
    except TimeoutError as e:
        fail(str(e))
        return False

    # Extra settle time (OS services still starting)
    settle = 10 if server.os_family.value == "windows" else 5
    log.info("Settling %ds for OS services...", settle)
    time.sleep(settle)
    return True


def resolve_packages(session, package_group_ids, server):
    """Resolve packages from DB — same as orchestrator does."""
    resolver = PackageResolver()
    return resolver.resolve(session, package_group_ids, server)


def deploy_packages(executor, packages):
    """Deploy packages — same as orchestrator does."""
    deployer = PackageDeployer()
    deployer.deploy_all(executor, packages)


def _filter_winrm_clixml(stderr_text):
    """Remove WinRM CLIXML noise from stderr."""
    noise_tags = [
        "CLIXML", "<Obj", "<TN", "</MS>", "<I64", "<PR ", "</TN>",
        "</Obj", "<MS>", "<AV>", "<AI>", "</PR>", "<Objs", "</Objs>",
        "<S ", "<T>", "</T>",
    ]
    clean = [l for l in stderr_text.split("\n")
             if not any(tag in l for tag in noise_tags)]
    return "\n".join(clean).strip()


def run_command(executor, command, label="", timeout=60):
    """Run a remote command with timeout enforcement and full logging.

    Uses a thread pool to enforce hard timeout — if WinRM hangs,
    the thread is abandoned and we continue with an error.
    """
    cmd_preview = command[:200] + ("..." if len(command) > 200 else "")
    log.debug("CMD [%s] timeout=%ds: %s", label, timeout, cmd_preview)

    t0 = time.time()
    # Use ThreadPoolExecutor to enforce hard timeout on WinRM calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(executor.execute, command, timeout)
        try:
            result = future.result(timeout=timeout + 15)  # 15s grace over WinRM timeout
        except concurrent.futures.TimeoutError:
            elapsed = time.time() - t0
            log.error("CMD [%s] HARD TIMEOUT after %.1fs (limit=%ds): %s",
                      label, elapsed, timeout, cmd_preview)
            log.error("  WinRM call did not return — likely hung. Continuing.")
            # Return a synthetic failure result
            from orchestrator.infra.remote_executor import CommandResult
            return CommandResult(exit_code=-1, stdout="", stderr=f"HARD TIMEOUT after {elapsed:.0f}s")

    elapsed = time.time() - t0
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Always log full output to file
    log.debug("CMD [%s] completed in %.1fs, exit_code=%d", label, elapsed, result.exit_code)
    if stdout:
        log.debug("CMD [%s] STDOUT (%d chars):\n%s", label, len(stdout), stdout)
    if stderr:
        log.debug("CMD [%s] STDERR (%d chars):\n%s", label, len(stderr), stderr)

    # Console-friendly output (last 20 lines of stdout, filtered stderr)
    if stdout:
        for line in stdout.split("\n")[-20:]:
            log.info("  [%s] %s", label, line)
    if stderr:
        clean_err = _filter_winrm_clixml(stderr)
        if clean_err:
            log.info("  [%s] STDERR: %s", label, clean_err[:500])

    if elapsed > 10:
        log.info("  [%s] (took %.1fs)", label, elapsed)

    return result


# ═══════════════════════════════════════════════════════════════════
# PHASE: EMULATOR ON LINUX TARGET
# ═══════════════════════════════════════════════════════════════════

def test_emulator_linux(config, credentials, session, lab, provider, skip_revert):
    banner("EMULATOR DEPLOY — Linux Target")

    # Find the linux target server
    server = session.query(ServerORM).filter_by(
        hostname="target-rky-01", lab_id=lab.id,
    ).first()
    if not server:
        fail("Server 'target-rky-01' not found in DB")
        return False
    log.info("  Server: %s (id=%d, ip=%s)", server.hostname, server.id, server.ip_address)

    # Find clean snapshot
    snapshot = session.query(SnapshotORM).filter_by(
        server_id=server.id, is_baseline=True,
    ).first()
    if not snapshot:
        fail("No baseline snapshot found for target-rky-01")
        return False
    log.info("  Snapshot: %s (id=%d)", snapshot.name, snapshot.id)
    log.info("  VMID: %s", server.server_infra_ref['vmid'])

    # Step 0: Revert snapshot
    step(0, f"Revert to snapshot '{snapshot.name}'")
    if skip_revert:
        log.info("  [SKIPPED]")
    else:
        if not revert_and_wait(provider, server, snapshot.name):
            return False

    # Step 1: Connect via SSH (create_executor — real code)
    step(1, "Connect via create_executor()")
    cred = credentials.get_server_credential(server.id, server.os_family.value)
    if not cred:
        fail(f"No credentials for server {server.id}")
        return False
    log.info("  Credentials: %s / ****", cred.username)

    try:
        executor = create_executor(
            os_family=server.os_family.value,
            host=server.ip_address,
            username=cred.username,
            password=cred.password,
        )
    except Exception as e:
        fail(f"create_executor failed: {e}")
        return False
    ok("SSHExecutor connected")

    try:
        run_command(executor, "hostname && cat /etc/os-release | head -3", "info")

        # Step 2: Resolve emulator package from DB (PackageResolver — real code)
        step(2, "PackageResolver.resolve() from DB")
        try:
            packages = resolve_packages(
                session, [lab.emulator_package_grp_id], server,
            )
        except Exception as e:
            fail(f"PackageResolver.resolve() failed: {e}")
            return False
        pkg = packages[0]
        ok(f"Resolved: group='{pkg.group_name}', member={pkg.member_id}")
        log.info("  path:               %s", pkg.path)
        log.info("  root_install_path:  %s", pkg.root_install_path)
        log.info("  extraction_command: %s", pkg.extraction_command)
        log.info("  run_command:        %s", pkg.run_command)
        log.info("  status_command:     %s", pkg.status_command)
        log.info("  prereq_script:      %s", pkg.prereq_script)

        # Resolve local path for package file
        local_pkg_path = os.path.join(ORCH_DIR, pkg.path)
        if not os.path.exists(local_pkg_path):
            fail(f"Package file not found: {local_pkg_path}")
            return False
        size_mb = os.path.getsize(local_pkg_path) / 1024 / 1024
        ok(f"Package file exists: {size_mb:.1f} MB")

        # Step 3: Deploy via PackageDeployer.deploy() (real code)
        step(3, "PackageDeployer.deploy() — prereq + upload + extract + install")
        # The path in ResolvedPackage is relative; deployer needs absolute path
        # Let's see if the real deploy works with the path as-is
        # The deploy method calls executor.upload(package.path, ...) so path must be valid
        import copy
        pkg_abs = copy.copy(pkg)
        pkg_abs.path = local_pkg_path
        try:
            deployer = PackageDeployer()
            deployer.deploy(executor, pkg_abs)
            ok("PackageDeployer.deploy() succeeded")
        except Exception as e:
            fail(f"PackageDeployer.deploy() failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Verify extraction
        run_command(executor, "ls -la /opt/emulator/ | head -15", "contents")

        # Step 4: Start emulator (run_command — same as orchestrator should do)
        step(4, "Start emulator via run_command")
        if pkg_abs.run_command:
            result = run_command(executor, pkg_abs.run_command, "start", timeout=30)
            if not result.success:
                fail(f"run_command failed (rc={result.exit_code})")
                run_command(executor, "cat /opt/emulator/emulator.log 2>/dev/null | tail -20",
                            "log")
                return False
            ok("Emulator started")
        else:
            log.info("  [WARN] No run_command defined — skipping start")

        # Step 5: Health check via status_command (real code)
        step(5, "Health check via status_command")
        if pkg_abs.status_command:
            result = run_command(executor, pkg_abs.status_command, "health")
            if result.success:
                ok("status_command passed")
            else:
                fail(f"status_command failed (rc={result.exit_code})")
                run_command(executor, "cat /opt/emulator/emulator.log 2>/dev/null | tail -20",
                            "log")
                return False

        # Also verify via deployer.check_status (real code)
        healthy = deployer.check_status(executor, pkg_abs)
        if healthy:
            ok("PackageDeployer.check_status() = True")
        else:
            fail("PackageDeployer.check_status() = False")
            return False

        # Remote HTTP health check from this machine
        import urllib.request
        try:
            resp = urllib.request.urlopen(
                f"http://{server.ip_address}:8080/health", timeout=10,
            )
            body = json.loads(resp.read().decode())
            ok(f"Remote health: {body}")
        except Exception as e:
            fail(f"Remote health check failed: {e}")
            log.info("  (Check firewall — port 8080 may be blocked)")
            return False

    finally:
        executor.close()

    banner("EMULATOR LINUX — ALL PASSED")
    return True


# ═══════════════════════════════════════════════════════════════════
# PHASE: EMULATOR ON WINDOWS TARGET
# ═══════════════════════════════════════════════════════════════════

def test_emulator_windows(config, credentials, session, lab, provider, skip_revert):
    banner("EMULATOR DEPLOY — Windows Target")

    server = session.query(ServerORM).filter_by(
        hostname="TARGET-WIN-01", lab_id=lab.id,
    ).first()
    if not server:
        fail("Server 'TARGET-WIN-01' not found in DB")
        return False
    log.info("  Server: %s (id=%s, ip=%s)", server.hostname, server.id, server.ip_address)

    snapshot = session.query(SnapshotORM).filter_by(
        server_id=server.id, is_baseline=True,
    ).first()
    if not snapshot:
        fail("No baseline snapshot found for TARGET-WIN-01")
        return False
    log.info("  Snapshot: %s (id=%s)", snapshot.name, snapshot.id)
    log.info("  VMID: %s", server.server_infra_ref['vmid'])

    # Step 0: Revert snapshot
    step(0, f"Revert to snapshot '{snapshot.name}'")
    if skip_revert:
        log.info("  [SKIPPED]")
    else:
        if not revert_and_wait(provider, server, snapshot.name):
            return False

    # Step 1: Connect via WinRM (create_executor — real code)
    step(1, "Connect via create_executor()")
    cred = credentials.get_server_credential(server.id, server.os_family.value)
    if not cred:
        fail(f"No credentials for server {server.id}")
        return False
    log.info("  Credentials: %s / ****", cred.username)

    # NOTE: create_executor needs orchestrator_url for Windows HTTP-pull uploads.
    # The real baseline_orchestrator.py does NOT pass this — that's a bug we're testing.
    # For now, pass it explicitly so we can test the rest of the flow.
    # The fix for baseline_orchestrator.py is tracked separately.
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((server.ip_address, 80))
        my_ip = s.getsockname()[0]
    finally:
        s.close()

    # WinRMExecutor.upload() builds URLs matching FastAPI mounts:
    #   /packages/foo.tar.gz        (from artifacts/packages/)
    #   /prerequisites/rhel/foo.sh  (from prerequisites/)
    # We create a temp dir that mirrors this layout for the HTTP server.
    import http.server
    import threading
    import shutil
    import tempfile

    serve_root = tempfile.mkdtemp(prefix="orch_serve_")
    # Mirror FastAPI mounts: /packages/ and /prerequisites/
    pkg_serve = os.path.join(serve_root, "packages")
    prereq_serve = os.path.join(serve_root, "prerequisites")
    shutil.copytree(os.path.join(ORCH_DIR, "artifacts", "packages"), pkg_serve)
    shutil.copytree(os.path.join(ORCH_DIR, "prerequisites"), prereq_serve)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=serve_root, **kwargs)
        def log_message(self, fmt, *args):
            log.debug("HTTP: %s", fmt % args)

    http_port = 9090
    httpd = http.server.HTTPServer(("0.0.0.0", http_port), QuietHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    orchestrator_url = f"http://{my_ip}:{http_port}"
    log.info("  HTTP file server: %s (serving %s)", orchestrator_url, serve_root)

    try:
        executor = create_executor(
            os_family=server.os_family.value,
            host=server.ip_address,
            username=cred.username,
            password=cred.password,
            orchestrator_url=orchestrator_url,
        )
    except Exception as e:
        fail(f"create_executor failed: {e}")
        return False
    ok("WinRMExecutor connected")

    try:
        result = run_command(executor, "hostname", "info")

        # Step 2: Resolve emulator package from DB
        step(2, "PackageResolver.resolve() from DB")
        try:
            packages = resolve_packages(
                session, [lab.emulator_package_grp_id], server,
            )
        except Exception as e:
            fail(f"PackageResolver.resolve() failed: {e}")
            return False
        pkg = packages[0]
        ok(f"Resolved: group='{pkg.group_name}', member={pkg.member_id}")
        log.info("  path:               %s", pkg.path)
        log.info("  root_install_path:  %s", pkg.root_install_path)
        log.info("  extraction_command: %s", pkg.extraction_command)
        log.info("  run_command:        %s", pkg.run_command)
        log.info("  status_command:     %s", pkg.status_command)
        log.info("  prereq_script:      %s", pkg.prereq_script)

        local_pkg_path = os.path.join(ORCH_DIR, pkg.path)
        if not os.path.exists(local_pkg_path):
            fail(f"Package file not found: {local_pkg_path}")
            return False
        size_mb = os.path.getsize(local_pkg_path) / 1024 / 1024
        ok(f"Package file exists: {size_mb:.1f} MB")

        # Step 3: Deploy via PackageDeployer.deploy()
        step(3, "PackageDeployer.deploy() — prereq + upload + extract + install")
        import copy
        pkg_abs = copy.copy(pkg)
        pkg_abs.path = local_pkg_path
        try:
            deployer = PackageDeployer()
            deployer.deploy(executor, pkg_abs)
            ok("PackageDeployer.deploy() succeeded")
        except Exception as e:
            fail(f"PackageDeployer.deploy() failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Verify extraction
        run_command(executor, "dir C:\\emulator", "contents")

        # Step 4: Start emulator
        step(4, "Start emulator via run_command")
        if pkg_abs.run_command:
            result = run_command(executor, pkg_abs.run_command, "start", timeout=45)
            if not result.success:
                fail(f"run_command failed (rc={result.exit_code})")
                run_command(executor,
                    'powershell -Command "Get-Content C:\\emulator\\emulator.log -Tail 20 -ErrorAction SilentlyContinue"',
                    "log")
                run_command(executor,
                    'powershell -Command "Get-Content C:\\emulator\\emulator_err.log -Tail 20 -ErrorAction SilentlyContinue"',
                    "err-log")
                return False
            ok("Emulator started")
        else:
            log.info("  [WARN] No run_command defined")

        # Step 5: Health check (with retry — emulator may need a few seconds to start)
        step(5, "Health check via status_command")
        if pkg_abs.status_command:
            # Retry health check up to 5 times with 3s intervals
            health_ok = False
            for attempt in range(5):
                result = run_command(executor, pkg_abs.status_command, "health", timeout=10)
                if result.success:
                    health_ok = True
                    break
                log.info("  Health check attempt %d/5 failed, waiting 3s...", attempt + 1)
                time.sleep(3)
            if health_ok:
                ok("status_command passed")
            else:
                fail("status_command failed after 5 attempts")
                run_command(executor,
                    'powershell -Command "Get-Content C:\\emulator\\emulator_err.log -Tail 20 -ErrorAction SilentlyContinue"',
                    "err-log")
                run_command(executor, "netstat -an | findstr 8080", "netstat")
                return False

        healthy = deployer.check_status(executor, pkg_abs)
        if healthy:
            ok("PackageDeployer.check_status() = True")
        else:
            fail("PackageDeployer.check_status() = False")
            return False

        # Remote HTTP health check
        import urllib.request
        try:
            resp = urllib.request.urlopen(
                f"http://{server.ip_address}:8080/health", timeout=10,
            )
            body = json.loads(resp.read().decode())
            ok(f"Remote health: {body}")
        except Exception as e:
            fail(f"Remote health check failed: {e}")
            log.info("  (Check firewall — port 8080 may be blocked)")
            return False

    finally:
        executor.close()
        httpd.shutdown()
        shutil.rmtree(serve_root, ignore_errors=True)

    banner("EMULATOR WINDOWS — ALL PASSED")
    return True


# ═══════════════════════════════════════════════════════════════════
# PHASE: JMETER ON LOADGEN
# ═══════════════════════════════════════════════════════════════════

def test_jmeter(config, credentials, session, lab, provider, skip_revert):
    banner("JMETER DEPLOY — Loadgen")

    server = session.query(ServerORM).filter_by(
        hostname="loadgen-rky-01", lab_id=lab.id,
    ).first()
    if not server:
        fail("Server 'loadgen-rky-01' not found in DB")
        return False
    log.info("  Server: %s (id=%s, ip=%s)", server.hostname, server.id, server.ip_address)
    log.info("  VMID: %s", server.server_infra_ref['vmid'])

    # Step 0: Revert snapshot
    step(0, "Revert loadgen to clean snapshot")
    if skip_revert:
        log.info("  [SKIPPED]")
    else:
        # Loadgen uses its own baseline snapshot
        snapshot_name = server.baseline.provider_ref.get("snapshot_name") if server.baseline else None
        if not snapshot_name:
            # Fallback — try to find a snapshot
            snap = session.query(SnapshotORM).filter_by(server_id=server.id).first()
            snapshot_name = snap.name if snap else "clean-loadgen"
        log.info("  Snapshot: %s", snapshot_name)
        if not revert_and_wait(provider, server, snapshot_name):
            return False

    # Step 1: Connect
    step(1, "Connect via create_executor()")
    cred = credentials.get_server_credential(server.id, server.os_family.value)
    if not cred:
        fail(f"No credentials for server {server.id}")
        return False

    try:
        executor = create_executor(
            os_family=server.os_family.value,
            host=server.ip_address,
            username=cred.username,
            password=cred.password,
        )
    except Exception as e:
        fail(f"create_executor failed: {e}")
        return False
    ok("SSHExecutor connected")

    try:
        run_command(executor, "hostname && cat /etc/os-release | head -3", "info")

        # Step 2: Resolve JMeter package from DB
        step(2, "PackageResolver.resolve() from DB")
        try:
            packages = resolve_packages(
                session, [lab.jmeter_package_grpid], server,
            )
        except Exception as e:
            fail(f"PackageResolver.resolve() failed: {e}")
            return False
        pkg = packages[0]
        ok(f"Resolved: group='{pkg.group_name}', member={pkg.member_id}")
        log.info("  path:               %s", pkg.path)
        log.info("  root_install_path:  %s", pkg.root_install_path)
        log.info("  extraction_command: %s", pkg.extraction_command)
        log.info("  status_command:     %s", pkg.status_command)
        log.info("  prereq_script:      %s", pkg.prereq_script)

        local_pkg_path = os.path.join(ORCH_DIR, pkg.path)
        if not os.path.exists(local_pkg_path):
            fail(f"Package file not found: {local_pkg_path}")
            return False
        size_mb = os.path.getsize(local_pkg_path) / 1024 / 1024
        ok(f"Package file exists: {size_mb:.1f} MB")

        # Step 3: Deploy via PackageDeployer.deploy()
        step(3, "PackageDeployer.deploy() — prereq + upload + extract")
        import copy
        pkg_abs = copy.copy(pkg)
        pkg_abs.path = local_pkg_path
        try:
            deployer = PackageDeployer()
            deployer.deploy(executor, pkg_abs)
            ok("PackageDeployer.deploy() succeeded")
        except Exception as e:
            fail(f"PackageDeployer.deploy() failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Step 4: Verify JMeter binary via status_command
        step(4, "Verify JMeter via status_command")
        if pkg_abs.status_command:
            result = run_command(executor, pkg_abs.status_command, "status")
            if result.success:
                ok("status_command passed")
            else:
                fail("status_command failed — JMeter binary not found")
                run_command(executor, "ls -la /opt/jmeter/bin/ 2>/dev/null", "ls")
                run_command(executor, "ls -la /opt/ 2>/dev/null", "opt")
                return False

        healthy = deployer.check_status(executor, pkg_abs)
        if healthy:
            ok("PackageDeployer.check_status() = True")
        else:
            fail("PackageDeployer.check_status() = False")
            return False

        # Verify JMeter version
        run_command(executor, "/opt/jmeter/bin/jmeter --version 2>&1 | head -5", "version")

        # Step 5: Smoke test — run JMeter against linux target emulator
        step(5, "JMeter smoke test")
        linux_target = session.query(ServerORM).filter_by(
            hostname="target-rky-01", lab_id=lab.id,
        ).first()
        if not linux_target:
            log.info("  [SKIP] No linux target found in DB")
            banner("JMETER DEPLOY — PASSED (smoke test skipped)")
            return True

        # Check if emulator is running on linux target
        result = run_command(executor,
                             f"curl -sf http://{linux_target.ip_address}:8080/health 2>/dev/null",
                             "emu-check")
        if not result.success:
            log.info("  [SKIP] Emulator not reachable on %s:8080", linux_target.ip_address)
            log.info("  [SKIP] Run 'emulator-linux' phase first for smoke test")
            banner("JMETER DEPLOY — PASSED (smoke test skipped)")
            return True

        ok(f"Emulator reachable at {linux_target.ip_address}:8080")

        # Create run dir + minimal JMX
        run_dir = "/opt/jmeter/runs/smoke_test"
        run_command(executor, f"rm -rf {run_dir} && mkdir -p {run_dir}", "mkdir")

        # Try to use real JMX template from artifacts
        from pathlib import Path
        jmx_dir = Path(ORCH_DIR) / "artifacts" / "jmx"
        jmx_file = jmx_dir / "server-normal.jmx"
        if jmx_file.exists():
            executor.upload(str(jmx_file), f"{run_dir}/test.jmx")
            ok("Uploaded server-normal.jmx template")
            # This JMX may need CSV data files — create a minimal one instead
            # if it errors out
        else:
            log.info("  [INFO] No JMX template found, creating minimal smoke test")

        # Create minimal health-check JMX (guaranteed to work without CSVs)
        # Uses scheduler mode with 10s duration to ensure JMeter terminates
        minimal_jmx = f"""<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Smoke Test">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments"/>
      <boolProp name="TestPlan.serialize_threadgroups">false</boolProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="Smoke">
        <intProp name="ThreadGroup.num_threads">1</intProp>
        <intProp name="ThreadGroup.ramp_time">0</intProp>
        <boolProp name="ThreadGroup.same_user_on_next_iteration">true</boolProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">10</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="Health">
          <stringProp name="HTTPSampler.domain">{linux_target.ip_address}</stringProp>
          <intProp name="HTTPSampler.port">8080</intProp>
          <stringProp name="HTTPSampler.path">/health</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree>
          <ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" testname="Think Time">
            <stringProp name="ConstantTimer.delay">500</stringProp>
          </ConstantTimer>
          <hashTree/>
        </hashTree>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>"""

        # Write minimal JMX via SFTP
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jmx", delete=False) as f:
            f.write(minimal_jmx)
            tmp_jmx = f.name
        try:
            executor.upload(tmp_jmx, f"{run_dir}/smoke.jmx")
        finally:
            os.unlink(tmp_jmx)
        ok("Uploaded smoke test JMX")

        # Run JMeter (no pipe — redirect to file, then read separately)
        jmeter_cmd = (
            f"/opt/jmeter/bin/jmeter -n -t {run_dir}/smoke.jmx "
            f"-l {run_dir}/results.jtl -j {run_dir}/jmeter.log "
            f"> {run_dir}/jmeter_stdout.log 2>&1"
        )
        result = run_command(executor, jmeter_cmd, "jmeter", timeout=90)
        run_command(executor, f"tail -10 {run_dir}/jmeter_stdout.log", "jmeter-out")
        if not result.success:
            fail("JMeter execution failed")
            run_command(executor, f"tail -30 {run_dir}/jmeter.log", "log")
            return False

        # Check results
        result = run_command(executor, f"wc -l {run_dir}/results.jtl", "jtl-lines")
        result = run_command(executor,
            f"awk -F',' 'NR>1 && $8==\"false\" {{count++}} END {{print \"errors: \" count+0}}' {run_dir}/results.jtl",
            "errors")
        error_count = result.stdout.strip().replace("errors: ", "")
        if error_count == "0":
            ok("No errors in JTL — JMeter works end-to-end")
        else:
            fail(f"{error_count} request errors in JTL")
            run_command(executor,
                f"awk -F',' 'NR>1 && $8==\"false\"' {run_dir}/results.jtl | head -3",
                "failed-rows")
            return False

    finally:
        executor.close()

    banner("JMETER DEPLOY — ALL PASSED")
    return True


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Test deployment using real orchestrator code paths",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Run from the orchestrator directory:
    cd orchestrator
    python ../test_deploy_all.py emulator-linux
    python ../test_deploy_all.py emulator-windows
    python ../test_deploy_all.py jmeter
    python ../test_deploy_all.py all

Iterative cycle:
    1. Run the test
    2. If it fails — analyze, fix the real orchestrator code
    3. Re-run (starts from step 0 = snapshot revert)
    Use --skip-revert to skip revert during rapid iteration.
        """,
    )
    parser.add_argument(
        "phases", nargs="+",
        choices=["emulator-linux", "emulator-windows", "jmeter", "all"],
    )
    parser.add_argument("--skip-revert", action="store_true",
                        help="Skip snapshot revert (for re-testing without clean slate)")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    phases = args.phases
    if "all" in phases:
        phases = ["emulator-linux", "emulator-windows", "jmeter"]

    log_file = setup_logging(phases, verbose=args.verbose)
    log.info("Log file: %s", log_file)
    print(f"\n  Log file: {log_file}\n")

    # Load orchestrator — DB, config, credentials
    banner("Loading orchestrator config + DB")
    try:
        config, credentials, session = load_orchestrator()
        ok("Config loaded, DB connected")
    except Exception as e:
        fail(f"Failed to load orchestrator: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Create hypervisor provider
    try:
        lab, provider = get_lab_and_provider(session, credentials)
        ok(f"Lab: {lab.name} (id={lab.id}), hypervisor: {lab.hypervisor_type.value}")
    except Exception as e:
        fail(f"Failed to create hypervisor provider: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Run phases
    results = {}
    for phase in phases:
        if phase == "emulator-linux":
            results[phase] = test_emulator_linux(
                config, credentials, session, lab, provider, args.skip_revert)
        elif phase == "emulator-windows":
            results[phase] = test_emulator_windows(
                config, credentials, session, lab, provider, args.skip_revert)
        elif phase == "jmeter":
            results[phase] = test_jmeter(
                config, credentials, session, lab, provider, args.skip_revert)

        if not results[phase]:
            log.info("\n%s", '!'*60)
            log.info("  PHASE '%s' FAILED — fix and re-run:", phase)
            log.info("    python ../test_deploy_all.py %s", phase)
            log.info("%s", '!'*60)
            break

    # Summary
    banner("DEPLOYMENT TEST SUMMARY")
    all_ok = True
    for phase, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        log.info("  %s %s", phase, status)
        if not passed:
            all_ok = False

    remaining = [p for p in phases if p not in results]
    for phase in remaining:
        log.info("  %s SKIPPED", phase)

    if all_ok:
        log.info("All deployments verified successfully!")
    else:
        log.info("Fix failures, then re-run from step 0 (revert + deploy)")
    log.info("Full log: %s", log_file)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
