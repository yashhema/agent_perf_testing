"""
Standalone test: Deploy emulator to Windows target (10.0.0.91)
using the same code paths as the orchestrator.

Requires: HTTP file server running on port 9090 (serve_packages.py)
"""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "orchestrator", "src"))

from orchestrator.infra.remote_executor import WinRMExecutor
from orchestrator.services.package_manager import PackageDeployer, ResolvedPackage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

HOST = "10.0.0.91"
USER = "Administrator"
PASS = "Test1234!"
ORCH_URL = "http://10.0.0.11:9090"

EMULATOR_PACKAGE = os.path.join(
    os.path.dirname(__file__),
    "orchestrator", "artifacts", "packages", "emulator-windows.tar.gz"
)

def main():
    print(f"Connecting to {HOST} via WinRM (NTLM)...")
    executor = WinRMExecutor(host=HOST, username=USER, password=PASS,
                             orchestrator_url=ORCH_URL)

    r = executor.execute("hostname")
    print(f"Connected to: {r.stdout.strip()}")

    package = ResolvedPackage(
        group_id=0,
        group_name="emulator-1.0",
        member_id=0,
        os_match_regex="windows/2022",
        path=EMULATOR_PACKAGE,
        root_install_path="C:\\emulator-pkg\\emulator-windows.tar.gz",
        extraction_command="mkdir C:\\emulator 2>nul & tar -xzf C:\\emulator-pkg\\emulator-windows.tar.gz -C C:\\emulator",
        install_command="pip install -r C:\\emulator\\requirements.txt",
        run_command="powershell -ExecutionPolicy Bypass -File C:\\emulator\\start.ps1",
        output_path=None,
        uninstall_command=None,
        status_command='powershell -Command "(Invoke-WebRequest -Uri http://localhost:8080/health -UseBasicParsing).StatusCode"',
        prereq_script="windows_server/python_emulator.ps1",
    )

    deployer = PackageDeployer()

    # Step 0: Prerequisite script
    print("\n=== Step 0: Running prerequisite script (Python install) ===")
    try:
        deployer._run_prereq_script(executor, package)
        print("  OK")
    except Exception as e:
        print(f"  FAILED: {e}")

    r = executor.execute("python --version")
    print(f"  Python: {r.stdout.strip()} (rc={r.exit_code})")

    # Steps 1-3: Deploy (upload, extract, install)
    print("\n=== Steps 1-3: Deploy (upload via HTTP, extract, install) ===")
    try:
        deployer.deploy(executor, package)
        print("  OK")
    except Exception as e:
        print(f"  FAILED: {e}")

    # Verify files
    print("\n=== Verify emulator files ===")
    r = executor.execute("dir C:\\emulator")
    print(f"  {r.stdout.strip()[:300]}")

    # Step 4: Run emulator via start.ps1
    print("\n=== Step 4: Start emulator via start.ps1 ===")
    r = executor.execute(package.run_command, timeout_sec=30)
    print(f"  rc={r.exit_code}")
    print(f"  stdout: {r.stdout.strip()[:200]}")
    print(f"  stderr: {r.stderr.strip()[:200]}")

    # Health check
    print("\n=== Health check ===")
    r = executor.execute(package.status_command)
    print(f"  rc={r.exit_code}, out={r.stdout.strip()[:100]}")

    executor.close()
    print("\n=== DONE ===")

if __name__ == "__main__":
    main()
