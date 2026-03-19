#!/usr/bin/env python3
"""Sync setup files from GitHub repo without re-downloading the full zip.

Reads setup_config.yaml to find repo_path, then downloads only the setup/
directory files from GitHub and overwrites them in place.

Usage:
    python3 sync_setup.py                    # sync all setup files
    python3 sync_setup.py --dry-run          # show what would be updated
    python3 sync_setup.py --file task1       # sync only task1_provision_accounts.py
    python3 sync_setup.py --file common      # sync only common.py
    python3 sync_setup.py --file run_test    # sync run_test.py (root level)

Also syncs: run_test.py, test_cases/*.yaml from repo root.

Preserves local files: servers.csv, mycred.txt, setup_config.yaml, discovery_output.json, credentials.json
"""

import os
import sys
import json
import urllib.request
import urllib.error
import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "setup_config.yaml")

# GitHub raw content base URL
GITHUB_REPO = "yashhema/agent_perf_testing"
GITHUB_BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}"

# Files to sync (remote path -> local path relative to repo root)
SETUP_FILES = {
    "setup/tasks/__init__.py": "setup/tasks/__init__.py",
    "setup/tasks/common.py": "setup/tasks/common.py",
    "setup/tasks/task1_provision_accounts.py": "setup/tasks/task1_provision_accounts.py",
    "setup/tasks/task2_vsphere_discovery.py": "setup/tasks/task2_vsphere_discovery.py",
    "setup/tasks/task3_seed_and_configure.py": "setup/tasks/task3_seed_and_configure.py",
    "setup/tasks/task4_install_orchestrator.py": "setup/tasks/task4_install_orchestrator.py",
    "setup/setup.py": "setup/setup.py",
    "setup/install_postgres.sh": "setup/install_postgres.sh",
    "setup/manage_snapshots.py": "setup/manage_snapshots.py",
    "setup/cleanup_targets.py": "setup/cleanup_targets.py",
    "setup/retake_snapshots.py": "setup/retake_snapshots.py",
    "setup/requirements.txt": "setup/requirements.txt",
    "setup/build_artifacts.sh": "setup/build_artifacts.sh",
    "setup/servers.csv.example": "setup/servers.csv.example",
    "setup/mycred.txt.example": "setup/mycred.txt.example",
}

TESTER_FILES = {
    "setup/testers/test_sudo.py": "setup/testers/test_sudo.py",
}

ORCHESTRATOR_FILES = {
    # Web UI
    "orchestrator/src/orchestrator/web/views.py": "orchestrator/src/orchestrator/web/views.py",
    "orchestrator/src/orchestrator/static/js/app.js": "orchestrator/src/orchestrator/static/js/app.js",
    "orchestrator/src/orchestrator/static/css/app.css": "orchestrator/src/orchestrator/static/css/app.css",
    "orchestrator/src/orchestrator/templates/admin/crud.html": "orchestrator/src/orchestrator/templates/admin/crud.html",
    "orchestrator/src/orchestrator/templates/admin/scenarios.html": "orchestrator/src/orchestrator/templates/admin/scenarios.html",
    "orchestrator/src/orchestrator/templates/admin/packages.html": "orchestrator/src/orchestrator/templates/admin/packages.html",
    "orchestrator/src/orchestrator/templates/admin/agents.html": "orchestrator/src/orchestrator/templates/admin/agents.html",
    "orchestrator/src/orchestrator/templates/admin/dashboard.html": "orchestrator/src/orchestrator/templates/admin/dashboard.html",
    "orchestrator/src/orchestrator/templates/base.html": "orchestrator/src/orchestrator/templates/base.html",
    "orchestrator/src/orchestrator/templates/login.html": "orchestrator/src/orchestrator/templates/login.html",
    "orchestrator/src/orchestrator/templates/baseline_tests/create.html": "orchestrator/src/orchestrator/templates/baseline_tests/create.html",
    "orchestrator/src/orchestrator/templates/baseline_tests/list.html": "orchestrator/src/orchestrator/templates/baseline_tests/list.html",
    "orchestrator/src/orchestrator/templates/baseline_tests/dashboard.html": "orchestrator/src/orchestrator/templates/baseline_tests/dashboard.html",
    "orchestrator/migrations/restructure_baseline_tests.sql": "orchestrator/migrations/restructure_baseline_tests.sql",
    "orchestrator/migrations/state_machine_redesign.sql": "orchestrator/migrations/state_machine_redesign.sql",
    "orchestrator/migrations/state_machine_redesign_postgres.sql": "orchestrator/migrations/state_machine_redesign_postgres.sql",
    "orchestrator/seed_packages.py": "orchestrator/seed_packages.py",
    # JMX templates + scripts (small files, not binary packages)
    "orchestrator/artifacts/jmx/server-normal.jmx": "orchestrator/artifacts/jmx/server-normal.jmx",
    "orchestrator/artifacts/jmx/server-file-heavy.jmx": "orchestrator/artifacts/jmx/server-file-heavy.jmx",
    "orchestrator/artifacts/jmx/server-steady.jmx": "orchestrator/artifacts/jmx/server-steady.jmx",
    "orchestrator/artifacts/jmx/server-stress.jmx": "orchestrator/artifacts/jmx/server-stress.jmx",
    "orchestrator/artifacts/scripts/jmeter_kill.py": "orchestrator/artifacts/scripts/jmeter_kill.py",
    "orchestrator/src/orchestrator/templates/snapshots/manager.html": "orchestrator/src/orchestrator/templates/snapshots/manager.html",
    # Core
    "orchestrator/src/orchestrator/core/baseline_state_machine.py": "orchestrator/src/orchestrator/core/baseline_state_machine.py",
    "orchestrator/src/orchestrator/core/baseline_orchestrator.py": "orchestrator/src/orchestrator/core/baseline_orchestrator.py",
    "orchestrator/src/orchestrator/core/baseline_execution.py": "orchestrator/src/orchestrator/core/baseline_execution.py",
    "orchestrator/src/orchestrator/core/calibration.py": "orchestrator/src/orchestrator/core/calibration.py",
    # API
    "orchestrator/src/orchestrator/api/baseline_test_runs.py": "orchestrator/src/orchestrator/api/baseline_test_runs.py",
    "orchestrator/src/orchestrator/api/admin.py": "orchestrator/src/orchestrator/api/admin.py",
    "orchestrator/src/orchestrator/api/schemas.py": "orchestrator/src/orchestrator/api/schemas.py",
    # Config / Models
    "orchestrator/src/orchestrator/config/settings.py": "orchestrator/src/orchestrator/config/settings.py",
    "orchestrator/src/orchestrator/models/orm.py": "orchestrator/src/orchestrator/models/orm.py",
    "orchestrator/src/orchestrator/models/enums.py": "orchestrator/src/orchestrator/models/enums.py",
    "orchestrator/src/orchestrator/models/database.py": "orchestrator/src/orchestrator/models/database.py",
    # Infra
    "orchestrator/src/orchestrator/infra/remote_executor.py": "orchestrator/src/orchestrator/infra/remote_executor.py",
    "orchestrator/src/orchestrator/infra/emulator_client.py": "orchestrator/src/orchestrator/infra/emulator_client.py",
    "orchestrator/src/orchestrator/infra/jmeter_controller.py": "orchestrator/src/orchestrator/infra/jmeter_controller.py",
    # Services
    "orchestrator/src/orchestrator/services/package_manager.py": "orchestrator/src/orchestrator/services/package_manager.py",
    "orchestrator/src/orchestrator/services/comparison.py": "orchestrator/src/orchestrator/services/comparison.py",
    # App + CLI
    "orchestrator/src/orchestrator/app.py": "orchestrator/src/orchestrator/app.py",
    "orchestrator/src/orchestrator/cli.py": "orchestrator/src/orchestrator/cli.py",
    "orchestrator/src/orchestrator/seed.py": "orchestrator/src/orchestrator/seed.py",
    # Config files
    "orchestrator/config/orchestrator.yaml": "orchestrator/config/orchestrator.yaml",
}

EMULATOR_JAVA_FILES = {
    "emulator_java/pom.xml": "emulator_java/pom.xml",
    "emulator_java/start.sh": "emulator_java/start.sh",
    "emulator_java/start.ps1": "emulator_java/start.ps1",
    "emulator_java/src/main/resources/application.yml": "emulator_java/src/main/resources/application.yml",
    "emulator_java/src/main/java/com/emulator/EmulatorApplication.java": "emulator_java/src/main/java/com/emulator/EmulatorApplication.java",
    # Config
    "emulator_java/src/main/java/com/emulator/config/JacksonConfig.java": "emulator_java/src/main/java/com/emulator/config/JacksonConfig.java",
    "emulator_java/src/main/java/com/emulator/config/WebConfig.java": "emulator_java/src/main/java/com/emulator/config/WebConfig.java",
    # Controllers
    "emulator_java/src/main/java/com/emulator/controller/AgentController.java": "emulator_java/src/main/java/com/emulator/controller/AgentController.java",
    "emulator_java/src/main/java/com/emulator/controller/ConfigController.java": "emulator_java/src/main/java/com/emulator/controller/ConfigController.java",
    "emulator_java/src/main/java/com/emulator/controller/HealthController.java": "emulator_java/src/main/java/com/emulator/controller/HealthController.java",
    "emulator_java/src/main/java/com/emulator/controller/LogsController.java": "emulator_java/src/main/java/com/emulator/controller/LogsController.java",
    "emulator_java/src/main/java/com/emulator/controller/OperationsController.java": "emulator_java/src/main/java/com/emulator/controller/OperationsController.java",
    "emulator_java/src/main/java/com/emulator/controller/StatsController.java": "emulator_java/src/main/java/com/emulator/controller/StatsController.java",
    "emulator_java/src/main/java/com/emulator/controller/TestsController.java": "emulator_java/src/main/java/com/emulator/controller/TestsController.java",
    # Request models
    "emulator_java/src/main/java/com/emulator/model/request/AgentInstallRequest.java": "emulator_java/src/main/java/com/emulator/model/request/AgentInstallRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/AgentServiceRequest.java": "emulator_java/src/main/java/com/emulator/model/request/AgentServiceRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/AgentUninstallRequest.java": "emulator_java/src/main/java/com/emulator/model/request/AgentUninstallRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/ConfigRequest.java": "emulator_java/src/main/java/com/emulator/model/request/ConfigRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/CpuRequest.java": "emulator_java/src/main/java/com/emulator/model/request/CpuRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/DiskRequest.java": "emulator_java/src/main/java/com/emulator/model/request/DiskRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/FileOperationRequest.java": "emulator_java/src/main/java/com/emulator/model/request/FileOperationRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/MemRequest.java": "emulator_java/src/main/java/com/emulator/model/request/MemRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/NetRequest.java": "emulator_java/src/main/java/com/emulator/model/request/NetRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/NetworkClientRequest.java": "emulator_java/src/main/java/com/emulator/model/request/NetworkClientRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/NetworkServerRequest.java": "emulator_java/src/main/java/com/emulator/model/request/NetworkServerRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/PoolRequest.java": "emulator_java/src/main/java/com/emulator/model/request/PoolRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/StartTestRequest.java": "emulator_java/src/main/java/com/emulator/model/request/StartTestRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/StopTestRequest.java": "emulator_java/src/main/java/com/emulator/model/request/StopTestRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/SuspiciousRequest.java": "emulator_java/src/main/java/com/emulator/model/request/SuspiciousRequest.java",
    "emulator_java/src/main/java/com/emulator/model/request/WorkRequest.java": "emulator_java/src/main/java/com/emulator/model/request/WorkRequest.java",
    # Response models
    "emulator_java/src/main/java/com/emulator/model/response/FileOperationResult.java": "emulator_java/src/main/java/com/emulator/model/response/FileOperationResult.java",
    "emulator_java/src/main/java/com/emulator/model/response/OperationResult.java": "emulator_java/src/main/java/com/emulator/model/response/OperationResult.java",
    "emulator_java/src/main/java/com/emulator/model/response/PoolResponse.java": "emulator_java/src/main/java/com/emulator/model/response/PoolResponse.java",
    "emulator_java/src/main/java/com/emulator/model/response/TestStatusResponse.java": "emulator_java/src/main/java/com/emulator/model/response/TestStatusResponse.java",
    # Services
    "emulator_java/src/main/java/com/emulator/service/AgentService.java": "emulator_java/src/main/java/com/emulator/service/AgentService.java",
    "emulator_java/src/main/java/com/emulator/service/ConfigService.java": "emulator_java/src/main/java/com/emulator/service/ConfigService.java",
    "emulator_java/src/main/java/com/emulator/service/CpuBurnService.java": "emulator_java/src/main/java/com/emulator/service/CpuBurnService.java",
    "emulator_java/src/main/java/com/emulator/service/DiskOperationService.java": "emulator_java/src/main/java/com/emulator/service/DiskOperationService.java",
    "emulator_java/src/main/java/com/emulator/service/FileOperationService.java": "emulator_java/src/main/java/com/emulator/service/FileOperationService.java",
    "emulator_java/src/main/java/com/emulator/service/MemoryPoolService.java": "emulator_java/src/main/java/com/emulator/service/MemoryPoolService.java",
    "emulator_java/src/main/java/com/emulator/service/NetworkClientService.java": "emulator_java/src/main/java/com/emulator/service/NetworkClientService.java",
    "emulator_java/src/main/java/com/emulator/service/NetworkOperationService.java": "emulator_java/src/main/java/com/emulator/service/NetworkOperationService.java",
    "emulator_java/src/main/java/com/emulator/service/StatsCollectorService.java": "emulator_java/src/main/java/com/emulator/service/StatsCollectorService.java",
    "emulator_java/src/main/java/com/emulator/service/SuspiciousOperationService.java": "emulator_java/src/main/java/com/emulator/service/SuspiciousOperationService.java",
    "emulator_java/src/main/java/com/emulator/service/TestManagerService.java": "emulator_java/src/main/java/com/emulator/service/TestManagerService.java",
    # Util
    "emulator_java/src/main/java/com/emulator/util/PlatformUtil.java": "emulator_java/src/main/java/com/emulator/util/PlatformUtil.java",
}

ROOT_FILES = {
    "run_test.py": "run_test.py",
    "test_cases/example_5server_steady.yaml": "test_cases/example_5server_steady.yaml",
}

# Never overwrite these local files
PROTECTED = {
    "setup/servers.csv",
    "setup/mycred.txt",
    "setup/setup_config.yaml",
    "setup/discovery_output.json",
    "setup/credentials.json",
    "setup/sync_setup.py",
    "orchestrator/config/credentials.json",
}


def download_file(url: str) -> str:
    """Download a file from URL and return its content."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_repo_path() -> str:
    """Read repo_path from setup_config.yaml."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return config.get("repo_path", SCRIPT_DIR.rsplit("/setup", 1)[0])
    # Fallback: assume setup/ is inside repo
    return os.path.dirname(SCRIPT_DIR)


def sync_file(remote_path: str, local_path: str, dry_run: bool = False) -> bool:
    """Download one file and write it locally. Returns True if updated."""
    url = f"{RAW_BASE}/{remote_path}"
    content = download_file(url)

    if content is None:
        print(f"  SKIP (not found): {remote_path}")
        return False

    # Check if local file exists and is same
    if os.path.exists(local_path):
        with open(local_path) as f:
            existing = f.read()
        if existing == content:
            print(f"  UP-TO-DATE: {remote_path}")
            return False

    if dry_run:
        print(f"  WOULD UPDATE: {remote_path} -> {local_path}")
        return True

    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            f.write(content)
        print(f"  UPDATED: {remote_path} -> {local_path}")
        return True
    except PermissionError as e:
        print(f"  PERMISSION ERROR: {local_path} — {e}")
        print(f"    Try: sudo chown -R $(whoami) {os.path.dirname(local_path)}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync setup files from GitHub")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    parser.add_argument("--file", "-f", default=None,
                        help="Sync only files matching this keyword (e.g. task1, common, run_test, test_sudo)")
    parser.add_argument("--list", action="store_true", help="List all syncable files")
    args = parser.parse_args()

    all_files = {}
    all_files.update(SETUP_FILES)
    all_files.update(TESTER_FILES)
    all_files.update(ORCHESTRATOR_FILES)
    all_files.update(EMULATOR_JAVA_FILES)
    all_files.update(ROOT_FILES)

    if args.list:
        print("Syncable files:")
        for remote_path, rel_path in sorted(all_files.items()):
            protected = " (PROTECTED)" if rel_path in PROTECTED else ""
            print(f"  {remote_path}{protected}")
        return

    repo_path = get_repo_path()
    print(f"Repo path:    {repo_path}")
    print(f"Source:       {RAW_BASE}")
    print(f"Files:        {len(all_files)} total ({len(SETUP_FILES)} setup, "
          f"{len(ORCHESTRATOR_FILES)} orchestrator, {len(EMULATOR_JAVA_FILES)} emulator_java, "
          f"{len(TESTER_FILES)} testers, {len(ROOT_FILES)} root)")
    print()

    updated = 0
    skipped = 0

    for remote_path, rel_path in sorted(all_files.items()):
        # Apply file filter
        if args.file and args.file.lower() not in remote_path.lower():
            continue

        # Skip protected local files
        if rel_path in PROTECTED:
            print(f"  PROTECTED: {rel_path}")
            skipped += 1
            continue

        local_path = os.path.join(repo_path, rel_path)
        if sync_file(remote_path, local_path, args.dry_run):
            updated += 1

    print(f"\n{'Would update' if args.dry_run else 'Updated'}: {updated} files, "
          f"Protected: {skipped}")


if __name__ == "__main__":
    main()
