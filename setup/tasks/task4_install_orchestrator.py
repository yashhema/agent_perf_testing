"""Task 4: Install orchestrator prerequisites on the local (orchestrator) machine.

This runs on the orchestrator RHEL machine itself. Steps:
  1. Install PostgreSQL (if not already installed)
  2. Configure PostgreSQL for local password auth
  3. Install Python 3.11 and dev dependencies
  4. Create virtualenv and install orchestrator package
  5. Install JMeter on loadgen machines (via SSH)
  6. Verify connectivity to all servers
"""

import logging
import os
import shutil
import subprocess

from .common import (
    SetupConfig, load_servers, load_credentials, validate_servers,
    ssh_run, winrm_run,
)

logger = logging.getLogger("setup.task4")


def _run_local(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a local shell command."""
    logger.info("  [LOCAL] %s", cmd)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        logger.warning("  rc=%d: %s", result.returncode, result.stderr.strip())
    return result


def _install_postgres():
    """Install and configure PostgreSQL on RHEL."""
    logger.info("Checking PostgreSQL installation ...")

    # Check if already installed
    result = _run_local("which psql", check=False)
    if result.returncode == 0:
        logger.info("  PostgreSQL already installed")
    else:
        logger.info("  Installing PostgreSQL ...")
        _run_local("sudo dnf install -y postgresql-server postgresql-contrib")
        _run_local("sudo postgresql-setup --initdb")

    # Ensure running
    _run_local("sudo systemctl enable --now postgresql")

    # Configure pg_hba.conf for local password auth
    logger.info("  Configuring pg_hba.conf for md5 auth ...")
    hba_paths = [
        "/var/lib/pgsql/data/pg_hba.conf",
        "/var/lib/pgsql/16/data/pg_hba.conf",
        "/var/lib/pgsql/15/data/pg_hba.conf",
    ]
    hba_path = None
    for p in hba_paths:
        result = _run_local(f"test -f {p}", check=False)
        if result.returncode == 0:
            hba_path = p
            break

    if hba_path:
        # Replace ident with md5 for local IPv4/IPv6 connections
        _run_local(f"sudo sed -i 's/^\\(local.*all.*all.*\\)peer/\\1md5/' {hba_path}")
        _run_local(f"sudo sed -i 's/^\\(host.*all.*all.*\\)ident/\\1md5/' {hba_path}")
        _run_local("sudo systemctl restart postgresql")
        logger.info("  pg_hba.conf updated and PostgreSQL restarted")
    else:
        logger.warning("  Could not find pg_hba.conf — configure auth manually")


def _install_python():
    """Install Python 3.11+ if not available."""
    logger.info("Checking Python installation ...")

    # Check for python3.11 or python3
    for pybin in ["python3.11", "python3.12", "python3"]:
        result = _run_local(f"which {pybin}", check=False)
        if result.returncode == 0:
            ver = _run_local(f"{pybin} --version", check=False)
            logger.info("  Found: %s", ver.stdout.strip())
            return pybin

    logger.info("  Installing Python 3.11 ...")
    _run_local("sudo dnf install -y python3.11 python3.11-pip python3.11-devel")
    return "python3.11"


def _setup_venv(config: SetupConfig, python_bin: str):
    """Create virtualenv and install orchestrator + deps."""
    venv_path = os.path.join(config.repo_path, ".venv")

    if os.path.exists(os.path.join(venv_path, "bin", "python")):
        logger.info("  Virtualenv already exists at %s", venv_path)
    else:
        logger.info("  Creating virtualenv at %s ...", venv_path)
        _run_local(f"{python_bin} -m venv {venv_path}")

    pip = os.path.join(venv_path, "bin", "pip")

    # Install orchestrator with PostgreSQL support
    orch_dir = os.path.join(config.repo_path, "orchestrator")
    logger.info("  Installing orchestrator[postgresql] ...")
    _run_local(f"{pip} install -e '{orch_dir}[postgresql]'")

    # Install emulator deps
    emu_reqs = os.path.join(config.repo_path, "emulator", "requirements.txt")
    if os.path.exists(emu_reqs):
        logger.info("  Installing emulator deps ...")
        _run_local(f"{pip} install -r {emu_reqs}")

    # Install loadgen deps
    lg_reqs = os.path.join(config.repo_path, "loadgen", "requirements.txt")
    if os.path.exists(lg_reqs):
        logger.info("  Installing loadgen deps ...")
        _run_local(f"{pip} install -r {lg_reqs}")

    # Install setup deps
    setup_reqs = os.path.join(config.repo_path, "setup", "requirements.txt")
    if os.path.exists(setup_reqs):
        logger.info("  Installing setup deps ...")
        _run_local(f"{pip} install -r {setup_reqs}")

    # Also install gcc and libpq-devel if needed (for psycopg2)
    _run_local("sudo dnf install -y gcc libpq-devel 2>/dev/null", check=False)


def _install_jmeter_on_loadgens(config: SetupConfig):
    """Install Java 17 and JMeter 5.6.3 on all loadgen machines."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)

    loadgens = [s for s in servers if s.role == "loadgen"]
    if not loadgens:
        logger.info("  No loadgen servers defined — skipping JMeter install")
        return

    jmeter_version = "5.6.3"
    jmeter_url = f"https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-{jmeter_version}.tgz"

    for lg in loadgens:
        logger.info("  Installing JMeter on loadgen: %s (%s)", lg.hostname, lg.ip)
        commands = [
            # Install Java 17
            "dnf install -y java-17-openjdk-headless",
            # Check if JMeter already installed
            f"test -d /opt/apache-jmeter-{jmeter_version} && echo 'JMETER_EXISTS' || echo 'JMETER_MISSING'",
            # Download and extract JMeter
            f"""
            if [ ! -d /opt/apache-jmeter-{jmeter_version} ]; then
                cd /tmp
                curl -sLO {jmeter_url}
                tar xzf apache-jmeter-{jmeter_version}.tgz -C /opt/
                rm -f apache-jmeter-{jmeter_version}.tgz
                echo 'JMETER_INSTALLED'
            fi
            """,
            # Set up PATH
            f"""
            grep -q 'JMETER_HOME' /etc/profile.d/jmeter.sh 2>/dev/null || {{
                echo 'export JMETER_HOME=/opt/apache-jmeter-{jmeter_version}' > /etc/profile.d/jmeter.sh
                echo 'export PATH=$JMETER_HOME/bin:$PATH' >> /etc/profile.d/jmeter.sh
                echo 'JMETER_PATH_SET'
            }}
            """,
            # Verify
            f"/opt/apache-jmeter-{jmeter_version}/bin/jmeter --version 2>&1 | head -5",
        ]

        try:
            results = ssh_run(lg.ip, creds.svc_user, creds.svc_pass, commands)
            for r in results:
                if r["rc"] != 0 and "EXISTS" not in r.get("stdout", ""):
                    logger.warning("    Command failed: %s", r["stderr"][:200])
            logger.info("    JMeter ready on %s", lg.hostname)
        except Exception as e:
            logger.error("    Failed on %s: %s", lg.hostname, e)


def _verify_connectivity(config: SetupConfig):
    """Test SSH/WinRM connectivity to all servers using the service account."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)

    logger.info("Verifying connectivity to all servers ...")
    ok = 0
    fail = 0

    for server in servers:
        try:
            if server.is_linux:
                results = ssh_run(server.ip, creds.svc_user, creds.svc_pass,
                                  ["hostname && whoami"])
                if results[0]["rc"] == 0:
                    logger.info("  OK: %s (%s) — %s", server.hostname, server.ip, results[0]["stdout"])
                    ok += 1
                else:
                    logger.error("  FAIL: %s — %s", server.hostname, results[0]["stderr"])
                    fail += 1
            else:
                results = winrm_run(server.ip, creds.svc_user, creds.svc_pass,
                                    ["$env:COMPUTERNAME; whoami"])
                if results[0]["rc"] == 0:
                    logger.info("  OK: %s (%s) — %s", server.hostname, server.ip, results[0]["stdout"])
                    ok += 1
                else:
                    logger.error("  FAIL: %s — %s", server.hostname, results[0]["stderr"])
                    fail += 1
        except Exception as e:
            logger.error("  FAIL: %s — %s", server.hostname, e)
            fail += 1

    logger.info("Connectivity: %d OK, %d failed out of %d", ok, fail, len(servers))
    return fail == 0


def run(config: SetupConfig):
    """Run Task 4: install prerequisites on orchestrator machine."""
    logger.info("=" * 60)
    logger.info("TASK 4: Install orchestrator prerequisites")
    logger.info("  Repo path: %s", config.repo_path)
    logger.info("=" * 60)

    # Step 1: Install PostgreSQL
    logger.info("[Step 1/5] PostgreSQL ...")
    _install_postgres()

    # Step 2: Install Python
    logger.info("[Step 2/5] Python ...")
    python_bin = _install_python()

    # Step 3: Setup virtualenv + install deps
    logger.info("[Step 3/5] Virtualenv and dependencies ...")
    _setup_venv(config, python_bin)

    # Step 4: Install JMeter on loadgens
    logger.info("[Step 4/5] JMeter on loadgen servers ...")
    _install_jmeter_on_loadgens(config)

    # Step 5: Verify connectivity
    logger.info("[Step 5/5] Verify connectivity ...")
    all_ok = _verify_connectivity(config)

    logger.info("-" * 60)
    if all_ok:
        logger.info("Task 4 complete — all prerequisites installed.")
    else:
        logger.warning("Task 4 complete with warnings — some connectivity checks failed.")

    return all_ok
