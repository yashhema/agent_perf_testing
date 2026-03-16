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
    "setup/requirements.txt": "setup/requirements.txt",
    "setup/servers.csv.example": "setup/servers.csv.example",
    "setup/mycred.txt.example": "setup/mycred.txt.example",
}

TESTER_FILES = {
    "setup/testers/test_sudo.py": "setup/testers/test_sudo.py",
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

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w") as f:
        f.write(content)
    print(f"  UPDATED: {remote_path}")
    return True


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
    all_files.update(ROOT_FILES)

    if args.list:
        print("Syncable files:")
        for remote_path, rel_path in sorted(all_files.items()):
            protected = " (PROTECTED)" if rel_path in PROTECTED else ""
            print(f"  {remote_path}{protected}")
        return

    repo_path = get_repo_path()
    print(f"Repo path: {repo_path}")
    print(f"Source:    {RAW_BASE}")
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
