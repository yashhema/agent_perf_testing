"""
Test all package deployments using actual orchestrator code paths.

Tests:
  1. Emulator on Windows target (10.0.0.91) — via WinRM
  2. Emulator on Linux target (10.0.0.92) — via SSH
  3. JMeter on Linux loadgen (10.0.0.83) — via SSH

Usage: python test_all_packages.py [emulator-win|emulator-linux|jmeter|all]
"""
import logging
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "orchestrator", "src"))

from orchestrator.infra.remote_executor import SSHExecutor, WinRMExecutor
from orchestrator.services.package_manager import PackageDeployer, ResolvedPackage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ORCH_URL = "http://10.0.0.11:9090"
ARTIFACTS = os.path.join(os.path.dirname(__file__), "orchestrator", "artifacts", "packages")


def test_emulator_windows():
    """Test emulator deployment on Windows target."""
    print("\n" + "=" * 60)
    print("TEST: Emulator on Windows (10.0.0.91)")
    print("=" * 60)

    executor = WinRMExecutor(
        host="10.0.0.91", username="Administrator", password="Test1234!",
        orchestrator_url=ORCH_URL,
    )
    r = executor.execute("hostname")
    print(f"Connected: {r.stdout.strip()}")

    package = ResolvedPackage(
        group_id=0, group_name="emulator-1.0", member_id=0,
        os_match_regex="windows/2022",
        path=os.path.join(ARTIFACTS, "emulator-windows.tar.gz"),
        root_install_path="C:\\emulator-pkg\\emulator-windows.tar.gz",
        extraction_command="mkdir C:\\emulator 2>nul & tar -xzf C:\\emulator-pkg\\emulator-windows.tar.gz -C C:\\emulator",
        install_command=None,
        run_command="powershell -ExecutionPolicy Bypass -File C:\\emulator\\start.ps1",
        output_path=None, uninstall_command=None,
        status_command='powershell -Command "(Invoke-WebRequest -Uri http://localhost:8080/health -UseBasicParsing).StatusCode"',
        prereq_script="windows_server/python_emulator.ps1",
    )

    deployer = PackageDeployer()

    # Step 0: Prereq
    print("\n--- Prereq (Python + pip packages) ---")
    deployer._run_prereq_script(executor, package)
    r = executor.execute("python --version")
    print(f"  Python: {r.stdout.strip()}")

    # Steps 1-3: Deploy
    print("\n--- Deploy (upload via HTTP, extract, install) ---")
    deployer.deploy(executor, package)
    print("  Deploy OK")

    # Verify files
    r = executor.execute("dir C:\\emulator\\app")
    print(f"  Files: {r.stdout.strip()[:200]}")

    # Step 4: Run
    print("\n--- Run (start.ps1) ---")
    r = executor.execute(package.run_command, timeout_sec=120)
    print(f"  rc={r.exit_code}, stdout={r.stdout.strip()[:200]}")
    if r.stderr.strip():
        print(f"  stderr={r.stderr.strip()[:200]}")

    # Health check
    print("\n--- Health check ---")
    r = executor.execute(package.status_command)
    print(f"  rc={r.exit_code}, out={r.stdout.strip()[:100]}")
    ok = r.exit_code == 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")

    executor.close()
    return ok


def test_emulator_linux():
    """Test emulator deployment on Linux target."""
    print("\n" + "=" * 60)
    print("TEST: Emulator on Linux (10.0.0.92)")
    print("=" * 60)

    executor = SSHExecutor(host="10.0.0.92", username="root", password="Test1234!")
    r = executor.execute("hostname")
    print(f"Connected: {r.stdout.strip()}")

    package = ResolvedPackage(
        group_id=0, group_name="emulator-1.0", member_id=0,
        os_match_regex="rhel/9/.*",
        path=os.path.join(ARTIFACTS, "emulator-linux.tar.gz"),
        root_install_path="/opt/emulator-pkg/emulator-linux.tar.gz",
        extraction_command="mkdir -p /opt/emulator && tar -xzf /opt/emulator-pkg/emulator-linux.tar.gz -C /opt/emulator --strip-components=1",
        install_command=None,
        run_command="bash /opt/emulator/start.sh",
        output_path=None, uninstall_command=None,
        status_command="curl -sf http://localhost:8080/health",
        prereq_script="rhel/python_emulator.sh",
    )

    deployer = PackageDeployer()

    # Step 0: Prereq
    print("\n--- Prereq (Python + pip packages) ---")
    deployer._run_prereq_script(executor, package)
    r = executor.execute("python3 --version")
    print(f"  Python: {r.stdout.strip()}")

    # Steps 1-3: Deploy
    print("\n--- Deploy (upload via SFTP, extract, install) ---")
    deployer.deploy(executor, package)
    print("  Deploy OK")

    # Verify files
    r = executor.execute("ls -la /opt/emulator/app/")
    print(f"  Files: {r.stdout.strip()[:200]}")

    # Step 4: Run
    print("\n--- Run (start.sh) ---")
    r = executor.execute(package.run_command, timeout_sec=30)
    print(f"  rc={r.exit_code}, stdout={r.stdout.strip()[:200]}")
    if r.stderr.strip():
        print(f"  stderr={r.stderr.strip()[:200]}")

    # Health check
    print("\n--- Health check ---")
    r = executor.execute(package.status_command)
    print(f"  rc={r.exit_code}, out={r.stdout.strip()[:100]}")
    ok = r.exit_code == 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")

    executor.close()
    return ok


def test_jmeter_linux():
    """Test JMeter deployment on Linux loadgen."""
    print("\n" + "=" * 60)
    print("TEST: JMeter on Linux loadgen (10.0.0.83)")
    print("=" * 60)

    executor = SSHExecutor(host="10.0.0.83", username="root", password="Test1234!")
    r = executor.execute("hostname")
    print(f"Connected: {r.stdout.strip()}")

    package = ResolvedPackage(
        group_id=0, group_name="jmeter-5.6.3", member_id=0,
        os_match_regex="rhel/9/.*",
        path=os.path.join(ARTIFACTS, "jmeter-5.6.3-linux.tar.gz"),
        root_install_path="/opt/jmeter-pkg/jmeter-5.6.3-linux.tar.gz",
        extraction_command="tar -xzf /opt/jmeter-pkg/jmeter-5.6.3-linux.tar.gz -C /opt && ln -sfn /opt/apache-jmeter-5.6.3 /opt/jmeter",
        install_command=None,
        run_command=None,
        output_path=None, uninstall_command=None,
        status_command="test -x /opt/jmeter/bin/jmeter",
        prereq_script="rhel/java_jre.sh",
    )

    deployer = PackageDeployer()

    # Step 0: Prereq
    print("\n--- Prereq (Java JRE) ---")
    deployer._run_prereq_script(executor, package)
    r = executor.execute("java -version 2>&1 | head -1")
    print(f"  Java: {r.stdout.strip()}")

    # Steps 1-3: Deploy
    print("\n--- Deploy (upload via SFTP, extract) ---")
    deployer.deploy(executor, package)
    print("  Deploy OK")

    # Verify
    r = executor.execute("ls -la /opt/jmeter/bin/jmeter")
    print(f"  JMeter binary: {r.stdout.strip()}")

    r = executor.execute("/opt/jmeter/bin/jmeter --version 2>&1 | head -5")
    print(f"  Version: {r.stdout.strip()[:200]}")

    # Status check
    print("\n--- Status check ---")
    r = executor.execute(package.status_command)
    ok = r.exit_code == 0
    print(f"  rc={r.exit_code}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")

    executor.close()
    return ok


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = {}

    if target in ("emulator-win", "all"):
        results["emulator-win"] = test_emulator_windows()

    if target in ("emulator-linux", "all"):
        results["emulator-linux"] = test_emulator_linux()

    if target in ("jmeter", "all"):
        results["jmeter"] = test_jmeter_linux()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    if all(results.values()):
        print("\nALL TESTS PASSED")
    else:
        print("\nSOME TESTS FAILED")
        sys.exit(1)
