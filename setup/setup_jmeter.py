#!/usr/bin/env python3
"""Setup JMeter on the local machine for calibration testing.

Mounts /dev/sdc to /data (formats if raw), extracts JMeter from the
artifact tar.gz, and validates the binary works.

Run once on any machine where you want to run test_calibration_live.py.

Usage:
    python setup_jmeter.py              # mount /dev/sdc, install JMeter
    python setup_jmeter.py --dry-run    # show what would happen
    python setup_jmeter.py --disk sdb   # use /dev/sdb instead of sdc
    python setup_jmeter.py --skip-mount # skip disk mount, just install JMeter to /data/jmeter
"""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tarfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
JMETER_ARTIFACT = os.path.join(REPO_ROOT, "orchestrator", "artifacts", "packages", "jmeter-5.6.3-linux.tar.gz")
KILL_SCRIPT = os.path.join(REPO_ROOT, "orchestrator", "artifacts", "scripts", "jmeter_kill.py")

DATA_MOUNT = "/data"
JMETER_DIR = "/data/jmeter"
JMETER_BIN = "/data/jmeter/bin/jmeter"


def run(cmd, desc=None, check=False):
    """Run a shell command, print output."""
    if desc:
        print(f"  [{desc}] {cmd}")
    else:
        print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.returncode != 0 and result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            print(f"    (stderr) {line}")
    if check and result.returncode != 0:
        print(f"  [FAIL] Command failed with exit code {result.returncode}")
        sys.exit(1)
    return result.returncode == 0, result.stdout.strip()


def setup_data_disk(disk_device, dry_run=False):
    """Format and mount disk to /data. Idempotent."""
    dev_path = f"/dev/{disk_device}"

    print(f"\n{'='*60}")
    print(f"  STEP 1: Mount {dev_path} -> {DATA_MOUNT}")
    print(f"{'='*60}")

    if dry_run:
        print(f"  [DRY RUN] Would format {dev_path}, mount to {DATA_MOUNT}")
        return True

    # Check disk exists
    ok, out = run(f"lsblk {dev_path} 2>&1 | head -5", "Check disk exists")
    if not ok:
        print(f"  [FAIL] {dev_path} not found")
        print(f"  Available disks:")
        run("lsblk -d -o NAME,SIZE,TYPE,MOUNTPOINT 2>&1")
        return False

    # Check if already mounted
    ok, out = run(f"mountpoint -q {DATA_MOUNT} 2>/dev/null && echo MOUNTED || echo NOTMOUNTED",
                  "Check mount status")
    if out.splitlines()[-1].strip() == "MOUNTED":
        print(f"  [OK] {DATA_MOUNT} already mounted")
        # Verify it's on the right disk
        run(f"df -h {DATA_MOUNT} | tail -1", "Verify mount")
        return True

    # Check if raw (no filesystem)
    ok, out = run(f"sudo file -s {dev_path} 2>&1", "Check filesystem")
    if ": data" in out:
        print(f"  [INFO] {dev_path} is raw, formatting as ext4...")
        ok, _ = run(f"sudo mkfs.ext4 -F {dev_path} 2>&1", "Format disk")
        if not ok:
            print(f"  [FAIL] Format failed")
            return False
        print(f"  [OK] Formatted {dev_path} as ext4")
    else:
        print(f"  [OK] Filesystem exists: {out}")

    # Mount
    run(f"sudo mkdir -p {DATA_MOUNT}", "Create mount point")
    ok, _ = run(f"sudo mount {dev_path} {DATA_MOUNT} 2>&1", "Mount disk")
    if not ok:
        print(f"  [FAIL] Mount failed")
        return False

    # Add to fstab
    run(f"grep -q '{dev_path}' /etc/fstab || echo '{dev_path} {DATA_MOUNT} ext4 defaults 0 2' | sudo tee -a /etc/fstab",
        "Add to fstab")

    # Chown to current user
    user = getpass.getuser()
    run(f"sudo chown {user}:{user} {DATA_MOUNT}", f"Chown to {user}")

    # Verify
    ok, out = run(f"df -h {DATA_MOUNT} | tail -1", "Verify mount")
    print(f"  [OK] {dev_path} mounted to {DATA_MOUNT}")
    return True


def install_jmeter(dry_run=False):
    """Extract JMeter from artifact to /data/jmeter."""
    print(f"\n{'='*60}")
    print(f"  STEP 2: Install JMeter to {JMETER_DIR}")
    print(f"{'='*60}")

    # Check if already installed
    if os.path.exists(JMETER_BIN):
        print(f"  [OK] JMeter already installed at {JMETER_BIN}")
        run(f"{JMETER_BIN} --version 2>&1 | head -3", "Version check")
        return True

    # Check artifact exists
    if not os.path.exists(JMETER_ARTIFACT):
        print(f"  [FAIL] Artifact not found: {JMETER_ARTIFACT}")
        return False
    print(f"  [OK] Artifact: {JMETER_ARTIFACT}")

    if dry_run:
        print(f"  [DRY RUN] Would extract to {JMETER_DIR}")
        return True

    # Ensure /data exists and is writable
    if not os.path.exists(DATA_MOUNT):
        user = getpass.getuser()
        run(f"sudo mkdir -p {DATA_MOUNT}", "Create /data")
        run(f"sudo chown {user}:{user} {DATA_MOUNT}", f"Chown to {user}")

    # Check we can write
    if not os.access(DATA_MOUNT, os.W_OK):
        user = getpass.getuser()
        print(f"  [INFO] {DATA_MOUNT} not writable, fixing ownership...")
        run(f"sudo chown {user}:{user} {DATA_MOUNT}", f"Chown to {user}")

    # Extract
    print(f"  [INFO] Extracting JMeter...")
    os.makedirs(JMETER_DIR, exist_ok=True)
    with tarfile.open(JMETER_ARTIFACT, "r:gz") as tar:
        tar.extractall(JMETER_DIR)

    # Flatten: apache-jmeter-X.Y.Z/* -> /data/jmeter/*
    subdirs = [d for d in os.listdir(JMETER_DIR)
               if os.path.isdir(os.path.join(JMETER_DIR, d)) and d.startswith("apache-jmeter")]
    if subdirs:
        extracted = os.path.join(JMETER_DIR, subdirs[0])
        for item in os.listdir(extracted):
            src = os.path.join(extracted, item)
            dst = os.path.join(JMETER_DIR, item)
            if not os.path.exists(dst):
                shutil.move(src, dst)
        shutil.rmtree(extracted, ignore_errors=True)
        print(f"  [OK] Flattened {subdirs[0]} -> {JMETER_DIR}")

    # Make executable
    if os.path.exists(JMETER_BIN):
        os.chmod(JMETER_BIN, 0o755)
        print(f"  [OK] JMeter binary: {JMETER_BIN}")
        run(f"{JMETER_BIN} --version 2>&1 | head -3", "Version check")
    else:
        print(f"  [FAIL] {JMETER_BIN} not found after extraction")
        print(f"  Contents of {JMETER_DIR}:")
        for item in sorted(os.listdir(JMETER_DIR)):
            print(f"    {item}")
        return False

    return True


def deploy_kill_script():
    """Copy jmeter_kill.py to the expected location."""
    print(f"\n{'='*60}")
    print(f"  STEP 3: Deploy jmeter_kill.py")
    print(f"{'='*60}")

    target = "/opt/jmeter/bin/jmeter_kill.py"
    if os.path.exists(target):
        print(f"  [OK] Already at {target}")
        return True

    if not os.path.exists(KILL_SCRIPT):
        print(f"  [WARN] Kill script not found: {KILL_SCRIPT}")
        return True  # non-fatal

    run(f"sudo mkdir -p /opt/jmeter/bin", "Create dir")
    run(f"sudo cp {KILL_SCRIPT} {target}", "Copy kill script")
    run(f"sudo chmod +x {target}", "Make executable")
    print(f"  [OK] Deployed to {target}")
    return True


def check_java():
    """Verify Java is available (JMeter needs it)."""
    print(f"\n{'='*60}")
    print(f"  STEP 4: Check Java")
    print(f"{'='*60}")

    ok, out = run("java -version 2>&1 | head -1", "Java version")
    if ok:
        print(f"  [OK] Java available")
        return True
    else:
        print(f"  [FAIL] Java not found — JMeter requires Java 8+")
        print(f"  Install with: sudo dnf install -y java-11-openjdk-headless")
        return False


def main():
    parser = argparse.ArgumentParser(description="Setup JMeter on local machine")
    parser.add_argument("--disk", default="sdc", help="Disk device name (default: sdc)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--skip-mount", action="store_true", help="Skip disk mount, just install JMeter")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  JMETER SETUP")
    print(f"  User: {getpass.getuser()}")
    print(f"  Disk: /dev/{args.disk}")
    print(f"  Mount: {DATA_MOUNT}")
    print(f"  JMeter: {JMETER_DIR}")
    print(f"  Artifact: {JMETER_ARTIFACT}")
    print(f"{'='*60}")

    # Step 1: Mount disk
    if not args.skip_mount:
        if not setup_data_disk(args.disk, dry_run=args.dry_run):
            print(f"\n  [FAIL] Disk setup failed. Use --skip-mount to skip.")
            sys.exit(1)
    else:
        # Still ensure /data exists
        if not os.path.exists(DATA_MOUNT):
            user = getpass.getuser()
            run(f"sudo mkdir -p {DATA_MOUNT}", "Create /data")
            run(f"sudo chown {user}:{user} {DATA_MOUNT}", f"Chown to {user}")

    # Step 2: Install JMeter
    if not install_jmeter(dry_run=args.dry_run):
        sys.exit(1)

    # Step 3: Deploy kill script
    deploy_kill_script()

    # Step 4: Check Java
    check_java()

    print(f"\n{'='*60}")
    print(f"  SETUP COMPLETE")
    print(f"  JMeter: {JMETER_BIN}")
    print(f"  Now run: python test_calibration_live.py --target-ip <IP> --threads 4")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
