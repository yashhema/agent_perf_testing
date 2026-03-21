#!/usr/bin/env python3
"""Retake snapshots for a baseline test run — targets AND loadgens.

Both loadgens and targets follow the same unified flow:
  1. Revert to snapshot (loadgen: clean_snapshot, target: parent or self)
  2. Wait for SSH/WinRM
  3. Fix passwordless sudo (Linux only — echo pass | sudo -S)
  4. Open firewall port 8080
  5. Install prerequisites (Java 17 for emulator, Python3+pip if needed)
  6. Setup data disk (/dev/sdc -> /data, create output folders, update DB)
  7. Cleanup (kill processes, rm dirs)
  8. Verify cleanliness
  9. Delete old snapshot from hypervisor
 10. Take new snapshot
 11. Update DB record
 12. VALIDATE: Revert to new snapshot, verify sudo + firewall + cleanliness

Usage:
    python retake_snapshots.py "Win2022 CrowdStrike v7.18 baseline" --sudo-user svc_account
    python retake_snapshots.py --test-id 42 --sudo-user svc_account
    python retake_snapshots.py "my test" --sudo-user svc_account --dry-run
    python retake_snapshots.py "my test" --sudo-user svc_account --targets srv1,srv2
    python retake_snapshots.py "my test" --sudo-user svc_account --loadgens-only
    python retake_snapshots.py "my test" --sudo-user svc_account --targets-only
    python retake_snapshots.py "my test" --sudo-user svc_account --force
"""

import argparse
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


FIREWALL_PORT = 8080
DATA_DISK = "/dev/sdc"
DATA_MOUNT = "/data"
OUTPUT_FOLDERS = ["/data/output1", "/data/output2", "/data/output3"]

# ---------------------------------------------------------------------------
# Cleanup commands
# ---------------------------------------------------------------------------
LOADGEN_CLEANUP_COMMANDS_LINUX = [
    ("Kill JMeter processes", "pgrep -f '[j]meter' | xargs -r kill -9 2>/dev/null; echo done"),
    ("Kill emulator processes", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done"),
    ("Remove JMeter", "rm -rf /data/jmeter /data/jmeter-pkg 2>&1; echo done"),
    ("Remove emulator", "rm -rf /data/emulator /data/emulator-pkg 2>&1; echo done"),
    ("Remove stale run dirs", "rm -rf /tmp/jmeter* /tmp/emulator* 2>&1; echo done"),
]

LOADGEN_VERIFY_COMMANDS_LINUX = [
    ("No JMeter processes", "pgrep -f '[j]meter' -c 2>/dev/null || echo 0", "0"),
    ("No emulator processes", "pgrep -f '[e]mulator' -c 2>/dev/null || echo 0", "0"),
    ("JMeter dir gone", "test -d /data/jmeter && echo EXISTS || echo GONE", "GONE"),
    ("Emulator dir gone", "test -d /data/emulator && echo EXISTS || echo GONE", "GONE"),
]

TARGET_CLEANUP_COMMANDS = {
    "linux": [
        ("Disable emulator service", "systemctl stop emulator 2>/dev/null; systemctl disable emulator 2>/dev/null; echo done"),
        ("Kill emulator processes", "pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; sleep 1; pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done"),
        ("Clean emulator output", "rm -rf /data/emulator/output/* /data/emulator/stats/* 2>/dev/null; echo done"),
    ],
    "windows": [
        ("Kill emulator", 'powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"'),
        ("Clean emulator output",
         'powershell -Command "'
         "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
         "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
         '"'),
    ],
}

TARGET_VERIFY_COMMANDS = {
    "linux": [
        ("No emulator processes", "pgrep -f '[e]mulator' -c 2>/dev/null || echo 0", "0"),
        ("No emulator output files", "find /data/emulator/output -type f 2>/dev/null | head -1 | wc -l", "0"),
        ("No emulator stats files", "find /data/emulator/stats -type f 2>/dev/null | head -1 | wc -l", "0"),
    ],
    "windows": [
        ("No emulator processes", 'powershell -Command "(Get-Process -Name *emulator* -ErrorAction SilentlyContinue | Measure-Object).Count"', "0"),
    ],
}


# ---------------------------------------------------------------------------
# Helper: run command and print result
# ---------------------------------------------------------------------------
def _run_cmd(executor, desc, cmd, warn_only=False):
    """Execute a command, print output, return (success, stdout)."""
    print(f"    {desc}...")
    print(f"      cmd: {cmd}")
    result = executor.execute(cmd)
    if result.stdout.strip():
        print(f"      stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        print(f"      stderr: {result.stderr.strip()}")
    if not result.success:
        label = "WARN" if warn_only else "ERROR"
        print(f"    [{label}] {desc}: exit_code={result.exit_code}")
    else:
        print(f"    [OK] {desc}")
    return result.success, result.stdout.strip()


def _verify_commands(executor, commands):
    """Run verification commands. Returns True if all pass."""
    all_ok = True
    for desc, cmd, expected in commands:
        result = executor.execute(cmd)
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        actual = lines[-1] if lines else ""
        if actual == expected:
            print(f"    [PASS] {desc}: {actual}")
        else:
            print(f"    [FAIL] {desc}: expected={expected!r}, got={actual!r}")
            all_ok = False
    return all_ok


# ---------------------------------------------------------------------------
# Step: Fix passwordless sudo (Linux only)
# ---------------------------------------------------------------------------
def fix_sudo(executor, password, sudo_user, os_family, dry_run=False):
    """Restore passwordless sudo for sudo_user. Uses echo pass | sudo -S to bootstrap."""
    if os_family == "windows":
        print(f"    [SKIP] Sudo not applicable for Windows")
        return True

    if dry_run:
        print(f"    [DRY RUN] Would fix passwordless sudo for '{sudo_user}'")
        return True

    print(f"\n  --- Fixing passwordless sudo for '{sudo_user}' ---")

    # Safe filename for sudoers.d (no backslashes or @)
    sudoers_file = sudo_user.replace("\\", "_").replace("@", "_")
    SUDO_S = f"echo '{password}' | sudo -S"

    # Create sudoers entry (same as task1_provision_accounts.py)
    ok1, _ = _run_cmd(executor, "Create sudoers entry",
        f"{SUDO_S} bash -c \"echo '{sudo_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{sudoers_file}\" 2>&1")
    if not ok1:
        print(f"    [ERROR] Failed to create sudoers entry")
        return False

    ok2, _ = _run_cmd(executor, "Set sudoers permissions",
        f"{SUDO_S} chmod 440 /etc/sudoers.d/{sudoers_file} 2>&1")
    if not ok2:
        print(f"    [ERROR] Failed to chmod sudoers file")
        return False

    ok3, _ = _run_cmd(executor, "Validate sudoers file",
        f"{SUDO_S} visudo -cf /etc/sudoers.d/{sudoers_file} 2>&1")
    if not ok3:
        print(f"    [ERROR] Sudoers file validation failed")
        return False

    # Verify passwordless sudo now works
    ok4, stdout = _run_cmd(executor, "Verify sudo -n whoami",
        "sudo -n whoami 2>&1")
    if ok4 and "root" in stdout:
        print(f"    [OK] Passwordless sudo works")
        return True
    else:
        print(f"    [ERROR] sudo -n whoami failed after fix — got: {stdout!r}")
        return False


# ---------------------------------------------------------------------------
# Step: Open firewall
# ---------------------------------------------------------------------------
def open_firewall(executor, os_family, port=FIREWALL_PORT, dry_run=False):
    """Open firewall port. Linux: firewall-cmd with iptables fallback. Windows: New-NetFirewallRule."""
    if dry_run:
        print(f"    [DRY RUN] Would open firewall port {port}/tcp")
        return True

    print(f"\n  --- Opening firewall port {port}/tcp ---")

    if os_family == "windows":
        ok, _ = _run_cmd(executor, f"Open port {port} (Windows firewall)",
            f'powershell -Command "'
            f"New-NetFirewallRule -DisplayName 'Emulator {port}' "
            f"-Direction Inbound -Port {port} -Protocol TCP "
            f'-Action Allow -ErrorAction SilentlyContinue"',
            warn_only=True)
        return True  # Windows firewall rule add is idempotent
    else:
        # Try firewall-cmd (RHEL/CentOS)
        ok, _ = _run_cmd(executor, f"Open port {port} (firewall-cmd)",
            f"sudo firewall-cmd --permanent --add-port={port}/tcp 2>&1 && "
            f"sudo firewall-cmd --reload 2>&1",
            warn_only=True)

        if not ok:
            # Fallback: iptables
            _run_cmd(executor, f"Open port {port} (iptables fallback)",
                f"sudo iptables -C INPUT -p tcp --dport {port} -j ACCEPT 2>/dev/null || "
                f"sudo iptables -I INPUT -p tcp --dport {port} -j ACCEPT",
                warn_only=True)

        # Verify
        verify_result = executor.execute(
            f"sudo firewall-cmd --list-ports 2>/dev/null | grep -q {port} && echo OPEN || "
            f"sudo iptables -C INPUT -p tcp --dport {port} -j ACCEPT 2>/dev/null && echo OPEN || "
            f"echo CLOSED"
        )
        status = verify_result.stdout.strip().split('\n')[-1].strip()
        if "OPEN" in status:
            print(f"    [VERIFIED] Port {port} is open")
            return True
        else:
            print(f"    [WARN] Could not verify port {port} is open")
            return False


# ---------------------------------------------------------------------------
# Step: Install prerequisites (Java 17, Python3+pip)
# ---------------------------------------------------------------------------
def install_prerequisites(executor, os_family, dry_run=False):
    """Install Java 17 on Linux and Windows. Idempotent."""
    import re

    if dry_run:
        print(f"    [DRY RUN] Would install Java 17 prerequisites")
        return True

    print(f"\n  --- Installing prerequisites ---")
    all_ok = True

    if os_family == "windows":
        return _install_prereqs_windows(executor)
    else:
        return _install_prereqs_linux(executor)


def _install_prereqs_linux(executor):
    """Install Java 17 + Python3 on Linux (RHEL/Rocky). Idempotent."""
    import re
    all_ok = True

    # 1. Ensure tar is available
    _run_cmd(executor, "Ensure tar is installed",
        "command -v tar >/dev/null || sudo dnf install -y -q tar 2>&1",
        warn_only=True)

    # 2. Install Java 17 (required for Java emulator)
    needs_java17 = True
    ok, stdout = _run_cmd(executor, "Check Java version",
        'java -version 2>&1 | head -1')
    if ok and stdout:
        m = re.search(r'"(\d+)', stdout)
        if m:
            major = int(m.group(1))
            if major >= 17:
                print(f"    [OK] Java {major} already installed")
                needs_java17 = False
            else:
                print(f"    Java {major} found but need 17+")

    if needs_java17:
        ok, _ = _run_cmd(executor, "Install Java 17 (OpenJDK headless)",
            "sudo dnf install -y java-17-openjdk-headless 2>&1")
        if not ok:
            ok, _ = _run_cmd(executor, "Install Java 17 (yum fallback)",
                "sudo yum install -y java-17-openjdk-headless 2>&1")
        if not ok:
            print(f"    [ERROR] Failed to install Java 17")
            all_ok = False
        else:
            # Set Java 17 as default via alternatives
            _run_cmd(executor, "Set Java 17 as default",
                "sudo alternatives --set java $(find /usr/lib/jvm/java-17-openjdk-*/bin/java -maxdepth 0 2>/dev/null | head -1) 2>&1",
                warn_only=True)
            # Verify
            ok, stdout = _run_cmd(executor, "Verify Java 17 is default",
                "java -version 2>&1 | head -1")
            if ok:
                m = re.search(r'"(\d+)', stdout)
                if m and int(m.group(1)) >= 17:
                    print(f"    [OK] Java 17 is default: {stdout}")
                else:
                    print(f"    [WARN] Java default still not 17: {stdout}")
                    all_ok = False

    # 3. Install Python3 + pip (needed for JMeter kill script etc.)
    ok, _ = _run_cmd(executor, "Check Python3",
        "python3 --version 2>&1")
    if not ok:
        _run_cmd(executor, "Install Python3",
            "sudo dnf install -y python3 python3-pip 2>&1",
            warn_only=True)

    return all_ok


def _install_prereqs_windows(executor):
    """Install Java 17 (Microsoft OpenJDK MSI) on Windows. Idempotent."""
    all_ok = True

    # Check if Java 17+ is already available
    ok, stdout = _run_cmd(executor, "Check Java version",
        'powershell -Command "try { $v = & java -version 2>&1 | Out-String; Write-Host $v.Trim() } catch { Write-Host NOTFOUND }"')

    needs_java17 = True
    if ok and stdout and "NOTFOUND" not in stdout:
        import re
        m = re.search(r'"(1[7-9]|[2-9]\d)', stdout)
        if m:
            print(f"    [OK] Java 17+ already installed: {stdout.splitlines()[0]}")
            needs_java17 = False
        else:
            print(f"    Java found but not 17+: {stdout.splitlines()[0]}")

    if not needs_java17:
        return True

    # Also check standard install paths before downloading
    ok, stdout = _run_cmd(executor, "Check standard Java 17 paths",
        'powershell -Command "'
        "$found = Get-Item 'C:\\Program Files\\Microsoft\\jdk-17*\\bin\\java.exe' -ErrorAction SilentlyContinue | Select-Object -First 1; "
        'if ($found) { Write-Host $found.FullName } else { Write-Host NOTFOUND }"')
    if ok and "NOTFOUND" not in stdout:
        print(f"    [OK] Java 17 found at: {stdout}")
        # Add to PATH if not already there
        _run_cmd(executor, "Refresh PATH with Java 17",
            'powershell -Command "'
            "$javaDir = (Get-Item 'C:\\Program Files\\Microsoft\\jdk-17*\\bin' -ErrorAction SilentlyContinue | Select-Object -First 1).FullName; "
            "if ($javaDir -and ($env:Path -notlike \\\"*$javaDir*\\\")) { "
            "[Environment]::SetEnvironmentVariable('Path', $env:Path + ';' + $javaDir, 'Machine') }"
            '"',
            warn_only=True)
        return True

    # Download and install Microsoft OpenJDK 17 MSI
    print(f"    Java 17 not found — downloading Microsoft OpenJDK 17...")
    install_script = (
        '$ErrorActionPreference = "Stop"; '
        "$downloadDir = 'C:\\jdk_install'; "
        "New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null; "
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
        "$msiUrl = 'https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.msi'; "
        "$msiPath = Join-Path $downloadDir 'jdk17.msi'; "
        "Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing; "
        "$fileSize = (Get-Item $msiPath).Length; "
        "Write-Host \"Downloaded: $fileSize bytes\"; "
        "if ($fileSize -lt 1000000) { throw 'Download too small' }; "
        "$proc = Start-Process msiexec.exe -ArgumentList \"/i `\"$msiPath`\" /quiet /norestart ADDLOCAL=FeatureMain,FeatureEnvironment,FeatureJarFileRunWith,FeatureJavaHome\" -Wait -PassThru -NoNewWindow; "
        "if ($proc.ExitCode -ne 0) { throw \"MSI failed: $($proc.ExitCode)\" }; "
        "$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine'); "
        "$userPath = [Environment]::GetEnvironmentVariable('Path', 'User'); "
        "$env:Path = \"$machinePath;$userPath\"; "
        "Remove-Item $downloadDir -Force -Recurse -ErrorAction SilentlyContinue; "
        "Write-Host 'Java 17 installed successfully'"
    )

    ok, stdout = _run_cmd(executor, "Download and install Microsoft OpenJDK 17 MSI",
        f'powershell -Command "{install_script}"')
    if not ok:
        print(f"    [ERROR] Failed to install Java 17 on Windows")
        return False

    # Verify
    ok, stdout = _run_cmd(executor, "Verify Java 17 installed",
        'powershell -Command "'
        "$javaExe = Get-Item 'C:\\Program Files\\Microsoft\\jdk-17*\\bin\\java.exe' -ErrorAction SilentlyContinue | Select-Object -First 1; "
        'if ($javaExe) { & $javaExe.FullName -version 2>&1 | Out-String | Write-Host } else { Write-Host NOTFOUND }"')
    if ok and "NOTFOUND" not in stdout:
        print(f"    [OK] Java 17 installed on Windows: {stdout.splitlines()[0] if stdout else ''}")
    else:
        print(f"    [WARN] Could not verify Java 17 after install")
        all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Step: Cleanup
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Step: Setup data disk (/dev/sdc -> /data) for Linux targets
# ---------------------------------------------------------------------------
def setup_data_disk(executor, os_family, ssh_user, dry_run=False):
    """Format /dev/sdc, mount to /data, create output folders. Linux only. Idempotent."""
    if os_family == "windows":
        print(f"    [SKIP] Data disk setup not applicable for Windows")
        return True

    if dry_run:
        print(f"    [DRY RUN] Would format {DATA_DISK}, mount to {DATA_MOUNT}, create output folders")
        return True

    print(f"\n  --- Setting up data disk {DATA_DISK} -> {DATA_MOUNT} ---")

    # Check if disk exists
    ok, stdout = _run_cmd(executor, f"Check {DATA_DISK} exists",
        f"lsblk {DATA_DISK} 2>&1 | head -2")
    if not ok:
        print(f"    [ERROR] {DATA_DISK} not found — cannot proceed without data disk")
        return False

    # Check if already mounted
    ok, stdout = _run_cmd(executor, f"Check if {DATA_MOUNT} is mounted",
        f"mountpoint -q {DATA_MOUNT} 2>/dev/null && echo MOUNTED || echo NOTMOUNTED")
    if stdout.strip().splitlines()[-1].strip() == "MOUNTED":
        print(f"    [OK] {DATA_MOUNT} already mounted")
    else:
        # Check if disk has a filesystem
        ok, stdout = _run_cmd(executor, f"Check filesystem on {DATA_DISK}",
            f"sudo file -s {DATA_DISK} 2>&1")
        if ok and ": data" in stdout:
            # Raw disk — format it
            ok, _ = _run_cmd(executor, f"Format {DATA_DISK} as ext4",
                f"sudo mkfs.ext4 -F {DATA_DISK} 2>&1")
            if not ok:
                print(f"    [ERROR] Failed to format {DATA_DISK}")
                return False
        else:
            print(f"    Filesystem already exists: {stdout}")

        # Create mount point and mount
        _run_cmd(executor, f"Create {DATA_MOUNT} mount point",
            f"sudo mkdir -p {DATA_MOUNT}")
        ok, _ = _run_cmd(executor, f"Mount {DATA_DISK} to {DATA_MOUNT}",
            f"sudo mount {DATA_DISK} {DATA_MOUNT} 2>&1")
        if not ok:
            print(f"    [ERROR] Failed to mount {DATA_DISK}")
            return False

        # Add to fstab if not already there
        _run_cmd(executor, "Add to /etc/fstab (idempotent)",
            f"grep -q '{DATA_DISK}' /etc/fstab || echo '{DATA_DISK} {DATA_MOUNT} ext4 defaults 0 2' | sudo tee -a /etc/fstab",
            warn_only=True)

    # Verify mount is on the actual disk (not root filesystem)
    ok, stdout = _run_cmd(executor, f"Verify {DATA_MOUNT} is on {DATA_DISK}",
        f"df {DATA_MOUNT} 2>/dev/null | grep -q '{DATA_DISK}' && echo ON_DISK || echo ON_ROOT")
    if "ON_ROOT" in stdout:
        print(f"    [ERROR] {DATA_MOUNT} is on root filesystem, not {DATA_DISK}")
        return False

    # Verify disk space (should be ~200GB)
    ok, stdout = _run_cmd(executor, f"Check disk space on {DATA_MOUNT}",
        f"df --output=avail {DATA_MOUNT} 2>/dev/null | tail -1")
    try:
        avail_kb = int(stdout.strip())
        avail_gb = avail_kb / (1024 * 1024)
        if avail_gb < 50:
            print(f"    [ERROR] {DATA_MOUNT} has only {avail_gb:.1f} GB — expected ~200GB")
            return False
        print(f"    {avail_gb:.1f} GB free on {DATA_MOUNT}")
    except (ValueError, TypeError):
        print(f"    [WARN] Could not parse disk space: {stdout}")

    # Create output folders
    for folder in OUTPUT_FOLDERS:
        ok, _ = _run_cmd(executor, f"Create {folder}",
            f"sudo mkdir -p {folder}")
        if not ok:
            print(f"    [ERROR] Failed to create {folder}")
            return False

    # Set ownership and permissions
    ok, _ = _run_cmd(executor, f"Set ownership of {DATA_MOUNT}",
        f"sudo chown -R {ssh_user} {DATA_MOUNT}")
    if not ok:
        print(f"    [ERROR] Failed to chown {DATA_MOUNT}")
        return False

    ok, _ = _run_cmd(executor, f"Set permissions on {DATA_MOUNT}",
        f"sudo chmod -R 755 {DATA_MOUNT}")
    if not ok:
        print(f"    [ERROR] Failed to chmod {DATA_MOUNT}")
        return False

    # Final verify: writable by ssh user
    ok, stdout = _run_cmd(executor, f"Verify {DATA_MOUNT} writable by {ssh_user}",
        f"echo test > {DATA_MOUNT}/_write_test && rm {DATA_MOUNT}/_write_test && echo WRITABLE || echo NOWRITE")
    if "WRITABLE" not in stdout:
        print(f"    [ERROR] {DATA_MOUNT} not writable by {ssh_user} after chown/chmod")
        return False

    print(f"    [OK] Data disk ready")
    return True


def cleanup_loadgen(executor, hostname, dry_run=False):
    """Kill all processes and rm -rf JMeter + emulator from a loadgen. Returns True if clean."""
    print(f"\n  --- Cleaning loadgen: {hostname} ---")

    if dry_run:
        for desc, _ in LOADGEN_CLEANUP_COMMANDS_LINUX:
            print(f"    [DRY RUN] {desc}")
        return True

    for desc, cmd in LOADGEN_CLEANUP_COMMANDS_LINUX:
        _run_cmd(executor, desc, cmd, warn_only=True)

    time.sleep(2)

    print(f"    --- Verifying ---")
    return _verify_commands(executor, LOADGEN_VERIFY_COMMANDS_LINUX)


def cleanup_target(executor, hostname, os_family, dry_run=False):
    """Clean a target VM. Returns True if verified clean."""
    commands = TARGET_CLEANUP_COMMANDS.get(os_family, TARGET_CLEANUP_COMMANDS["linux"])
    verify_cmds = TARGET_VERIFY_COMMANDS.get(os_family, TARGET_VERIFY_COMMANDS.get("linux", []))

    if dry_run:
        for desc, _ in commands:
            print(f"    [DRY RUN] {desc}")
        return True

    for desc, cmd in commands:
        _run_cmd(executor, desc, cmd, warn_only=True)

    time.sleep(2)

    print(f"    --- Verifying target cleanup ---")
    return _verify_commands(executor, verify_cmds)


# ---------------------------------------------------------------------------
# Step: Validate snapshot (revert to new snapshot and verify everything)
# ---------------------------------------------------------------------------
def validate_snapshot(provider, server, snapshot_ref, credentials, sudo_user, os_family, wait_for_ssh_fn):
    """Revert to the snapshot we just took, verify sudo + firewall + cleanliness + /data.

    Returns (all_ok, checks) where checks is a list of (name, passed, detail).
    """
    checks = []
    print(f"\n  --- Validating snapshot (revert + verify) ---")

    # Revert to the new snapshot
    print(f"    Reverting to newly created snapshot...")
    new_ip = provider.restore_snapshot(server.server_infra_ref, snapshot_ref)
    provider.wait_for_vm_ready(server.server_infra_ref)

    actual_ip = new_ip if (new_ip and new_ip != server.ip_address) else server.ip_address

    # Wait for connectivity
    proto = "WinRM" if os_family == "windows" else "SSH"
    print(f"    Waiting for {proto}...")
    wait_for_ssh_fn(actual_ip, os_family=os_family, timeout_sec=120)
    print(f"    Connected")

    # Create executor
    cred = credentials.get_server_credential(server.id, os_family)
    from orchestrator.infra.remote_executor import create_executor
    executor = create_executor(
        os_family=os_family,
        host=actual_ip,
        username=cred.username,
        password=cred.password,
    )

    all_ok = True

    def _check(name, passed, detail=""):
        nonlocal all_ok
        checks.append((name, passed, detail))
        icon = "PASS" if passed else "FAIL"
        print(f"    [{icon}] {name}{': ' + detail if detail else ''}")
        if not passed:
            all_ok = False

    try:
        # 1. Sudo (Linux)
        if os_family != "windows":
            result = executor.execute("sudo -n whoami 2>&1")
            got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
            _check("sudo", result.success and "root" in got, got)

        # 2. Firewall
        if os_family == "windows":
            result = executor.execute(
                f'powershell -Command "(Get-NetFirewallRule -DisplayName \'Emulator {FIREWALL_PORT}\' '
                f'-ErrorAction SilentlyContinue | Measure-Object).Count"')
            got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else "0"
            _check("firewall", got != "0", f"port {FIREWALL_PORT}")
        else:
            result = executor.execute(
                f"sudo firewall-cmd --list-ports 2>/dev/null | grep -q {FIREWALL_PORT} && echo OPEN || "
                f"sudo iptables -C INPUT -p tcp --dport {FIREWALL_PORT} -j ACCEPT 2>/dev/null && echo OPEN || echo CLOSED")
            got = result.stdout.strip().split('\n')[-1].strip()
            _check("firewall", "OPEN" in got, f"port {FIREWALL_PORT}")

        # 3. Cleanliness
        if os_family != "windows":
            for desc, cmd, expected in [
                ("no_jmeter_procs", "pgrep -f '[j]meter' -c 2>/dev/null || echo 0", "0"),
                ("no_emulator_procs", "pgrep -f '[e]mulator' -c 2>/dev/null || echo 0", "0"),
            ]:
                result = executor.execute(cmd)
                got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
                _check(desc, got == expected, got)

        # 4. Java 17+
        if os_family != "windows":
            import re
            result = executor.execute("java -version 2>&1 | head -1")
            java_out = result.stdout.strip()
            m = re.search(r'"(\d+)', java_out)
            major = int(m.group(1)) if m else 0
            _check("java_17+", major >= 17, java_out)

        # 5. /data checks (Linux)
        if os_family != "windows":
            result = executor.execute(f"mountpoint -q {DATA_MOUNT} && echo YES || echo NO")
            got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else "NO"
            _check("data_mounted", got == "YES")

            result = executor.execute(f"echo test > {DATA_MOUNT}/_val_test && rm {DATA_MOUNT}/_val_test && echo OK || echo FAIL")
            got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else "FAIL"
            _check("data_writable", got == "OK", result.stderr.strip() if got != "OK" else "")

            for folder in OUTPUT_FOLDERS:
                result = executor.execute(f"test -d {folder} && echo YES || echo NO")
                got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else "NO"
                _check(f"folder_{folder.split('/')[-1]}", got == "YES")

            result = executor.execute(f"df --output=avail {DATA_MOUNT} 2>/dev/null | tail -1")
            try:
                avail_gb = int(result.stdout.strip()) / (1024 * 1024)
                _check("data_space", avail_gb >= 50, f"{avail_gb:.1f} GB")
            except (ValueError, TypeError):
                _check("data_space", False, "could not parse")

            result = executor.execute(f"mkdir -p {DATA_MOUNT}/_val_dir && rm -rf {DATA_MOUNT}/_val_dir && echo OK || echo FAIL")
            got = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else "FAIL"
            _check("data_mkdir", got == "OK")

    finally:
        executor.close()

    return all_ok, checks


# ---------------------------------------------------------------------------
# Unified retake flow for one machine
# ---------------------------------------------------------------------------
def retake_one(
    *,
    label,             # "Loadgen" or "Target"
    server,            # ServerORM
    snapshot,          # SnapshotORM (the snapshot to delete + recreate)
    revert_ref,        # provider_ref to revert to (parent snapshot or self)
    revert_name,       # display name of revert target
    provider,
    credentials,
    session,
    sudo_user,
    cleanup_fn,        # callable(executor, hostname, os_family?, dry_run?) -> bool
    target_orm=None,   # BaselineTestRunTargetORM (if target — for output_folders update)
    dry_run=False,
    wait_for_ssh_fn=None,
):
    """
    Unified retake flow:
      1. Revert  2. SSH  3. Fix sudo  4. Open firewall
      5. Install prereqs  6. Setup data disk  7. Cleanup  8. Verify
      9. Delete old snap  10. Take new snap  11. Update DB
      12. Validate (revert to new + verify)

    Returns True on success, False on failure.
    """
    os_family = server.os_family.value
    TOTAL_STEPS = 12

    if dry_run:
        print(f"  [DRY RUN] Would: revert -> fix sudo -> open firewall -> cleanup -> "
              f"delete old snap -> take new -> update DB -> validate")
        return True, []

    # --- Step 1: Revert ---
    print(f"  [1/{TOTAL_STEPS}] Reverting to '{revert_name}'...")
    new_ip = provider.restore_snapshot(server.server_infra_ref, revert_ref)
    provider.wait_for_vm_ready(server.server_infra_ref)
    actual_ip = server.ip_address
    if new_ip and new_ip != server.ip_address:
        actual_ip = new_ip
        server.ip_address = new_ip
        session.commit()
        print(f"         IP changed: {server.ip_address} -> {new_ip}")

    # --- Step 2: Wait for SSH/WinRM ---
    proto = "WinRM" if os_family == "windows" else "SSH"
    print(f"  [2/{TOTAL_STEPS}] Waiting for {proto}...")
    wait_for_ssh_fn(actual_ip, os_family=os_family, timeout_sec=120)
    print(f"         Connected")

    # Create executor
    cred = credentials.get_server_credential(server.id, os_family)
    from orchestrator.infra.remote_executor import create_executor
    executor = create_executor(
        os_family=os_family,
        host=actual_ip,
        username=cred.username,
        password=cred.password,
    )

    try:
        # --- Step 3: Fix passwordless sudo ---
        print(f"  [3/{TOTAL_STEPS}] Fixing passwordless sudo...")
        if not fix_sudo(executor, cred.password, sudo_user, os_family, dry_run):
            print(f"  [ERROR] Failed to fix sudo on {server.hostname}")
            return False, []

        # --- Step 4: Open firewall ---
        print(f"  [4/{TOTAL_STEPS}] Opening firewall port {FIREWALL_PORT}...")
        if not open_firewall(executor, os_family, FIREWALL_PORT, dry_run):
            print(f"  [WARN] Firewall fix may have failed on {server.hostname} — continuing")

        # --- Step 5: Install prerequisites ---
        print(f"  [5/{TOTAL_STEPS}] Installing prerequisites...")
        if not install_prerequisites(executor, os_family, dry_run):
            print(f"  [WARN] Some prerequisites may have failed on {server.hostname} — continuing")

        # --- Step 6: Setup data disk ---
        print(f"  [6/{TOTAL_STEPS}] Setting up data disk...")
        if not setup_data_disk(executor, os_family, cred.username, dry_run):
            print(f"  [ERROR] Data disk setup failed on {server.hostname} — aborting retake")
            return False, []
        # Update output_folders in DB for this target
        if target_orm is not None and os_family != "windows":
            new_folders = ",".join(OUTPUT_FOLDERS)
            if target_orm.output_folders != new_folders:
                old_val = target_orm.output_folders
                target_orm.output_folders = new_folders
                session.commit()
                print(f"    [DB] Updated output_folders: {old_val!r} -> {new_folders!r}")
            else:
                print(f"    [DB] output_folders already set: {new_folders}")

        # --- Step 7: Cleanup ---
        print(f"  [7/{TOTAL_STEPS}] Running cleanup on {server.hostname}...")
        is_clean = cleanup_fn(executor, server.hostname, os_family)
        if not is_clean:
            print(f"  [ERROR] {server.hostname} not clean after cleanup — aborting retake")
            return False, []
        print(f"  [8/{TOTAL_STEPS}] Verification passed")

    finally:
        executor.close()

    # --- Step 9: Delete old snapshot from hypervisor ---
    print(f"  [9/{TOTAL_STEPS}] Deleting old snapshot '{snapshot.name}' from hypervisor...")
    try:
        provider.delete_snapshot(server.server_infra_ref, snapshot.provider_ref)
        print(f"         Deleted")
    except Exception as e:
        print(f"         Delete failed (non-fatal, may already be gone): {e}")

    # --- Step 10: Take new snapshot ---
    print(f"  [10/{TOTAL_STEPS}] Taking new snapshot '{snapshot.name}'...")
    result = provider.create_snapshot(
        server.server_infra_ref,
        snapshot_name=snapshot.name,
        description=snapshot.description or "",
    )
    new_provider_id = (
        result.get("snapshot_moref_id")
        or result.get("snapshot_id")
        or result.get("snapshot_name")
    )
    print(f"         Created: provider_id={new_provider_id}")

    # --- Step 11: Update DB record in-place ---
    print(f"  [11/{TOTAL_STEPS}] Updating DB record (ID={snapshot.id})...")
    old_provider_id = snapshot.provider_snapshot_id
    snapshot.provider_snapshot_id = str(new_provider_id)
    snapshot.provider_ref = result
    snapshot.snapshot_tree = [
        s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)
    ]
    session.commit()
    print(f"         Updated: provider_id {old_provider_id} -> {new_provider_id}")
    print(f"         DB record ID={snapshot.id} preserved")

    # Verify snapshot exists on hypervisor
    exists = provider.snapshot_exists(server.server_infra_ref, result)
    if exists:
        print(f"         [VERIFIED] Snapshot exists on hypervisor")
    else:
        print(f"         [WARN] Snapshot not found on hypervisor after creation!")

    # --- Step 12: Validate by reverting to new snapshot ---
    print(f"  [12/{TOTAL_STEPS}] Validating snapshot (revert to new + verify)...")
    # Re-read snapshot from DB to use the updated provider_ref
    session.refresh(snapshot)
    valid, val_checks = validate_snapshot(
        provider, server, snapshot.provider_ref, credentials,
        sudo_user, os_family, wait_for_ssh_fn,
    )
    if valid:
        print(f"  [OK] {label} {server.hostname}: snapshot validated successfully")
    else:
        print(f"  [WARN] {label} {server.hostname}: snapshot validation had failures (see above)")

    return True, val_checks


# ---------------------------------------------------------------------------
# Cleanup wrapper that matches the unified signature (executor, hostname, os_family)
# ---------------------------------------------------------------------------
def _cleanup_loadgen_wrapper(executor, hostname, os_family):
    """Loadgen cleanup — os_family ignored (always Linux commands)."""
    return cleanup_loadgen(executor, hostname)


def _cleanup_target_wrapper(executor, hostname, os_family):
    """Target cleanup — dispatches by os_family."""
    return cleanup_target(executor, hostname, os_family)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Retake snapshots for a baseline test run (loadgens + targets)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("name", nargs="?", default=None,
                       help="Test run name (case-insensitive search)")
    group.add_argument("--test-id", type=int, default=None,
                       help="Test run ID (exact)")
    parser.add_argument("--sudo-user", required=True,
                        help="Username to configure passwordless sudo for (e.g. svc_account)")
    parser.add_argument("--targets", default=None,
                        help="Comma-separated hostnames to retake (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--loadgens-only", action="store_true",
                        help="Only clean and snapshot loadgens")
    parser.add_argument("--targets-only", action="store_true",
                        help="Only retake target snapshots")
    parser.add_argument("--force", action="store_true",
                        help="Force re-create loadgen snapshots even if one already exists")

    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.models.orm import (
        BaselineTestRunORM, BaselineTestRunTargetORM,
        LabORM, ServerORM, SnapshotORM,
    )
    from orchestrator.config.settings import load_config
    from orchestrator.config.credentials import CredentialsStore
    from orchestrator.infra.hypervisor import create_hypervisor_provider
    from orchestrator.core.baseline_execution import wait_for_ssh

    # Initialize DB
    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    cred_path = os.path.join(REPO_ROOT, "orchestrator", "config", "credentials.json")
    credentials = CredentialsStore(cred_path)
    session = SessionLocal()

    # --- Find test run ---
    if args.test_id:
        test_run = session.get(BaselineTestRunORM, args.test_id)
        if not test_run:
            print(f"ERROR: Test run ID {args.test_id} not found")
            sys.exit(1)
    else:
        from sqlalchemy import func
        results = session.query(BaselineTestRunORM).filter(
            func.lower(BaselineTestRunORM.name) == args.name.lower(),
        ).all()
        if not results:
            results = session.query(BaselineTestRunORM).filter(
                func.lower(BaselineTestRunORM.name).contains(args.name.lower()),
            ).all()
        if not results:
            print(f"ERROR: No test run found matching '{args.name}'")
            sys.exit(1)
        if len(results) > 1:
            print(f"Multiple test runs match '{args.name}':")
            for r in results:
                print(f"  ID={r.id}  name='{r.name}'  state={r.state.value}  created={r.created_at}")
            print("\nUse --test-id to specify exactly which one.")
            sys.exit(1)
        test_run = results[0]

    print(f"Test run: #{test_run.id} '{test_run.name}' (state={test_run.state.value})")
    print(f"Sudo user: {args.sudo_user}")

    # --- Get targets ---
    target_orms = session.query(BaselineTestRunTargetORM).filter(
        BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
    ).all()

    if not target_orms:
        print("ERROR: No targets found for this test run")
        sys.exit(1)

    target_filter = None
    if args.targets:
        target_filter = {h.strip().lower() for h in args.targets.split(",")}

    # --- Get lab + hypervisor ---
    lab = session.get(LabORM, test_run.lab_id)
    hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    validation_results = {}  # {hostname: [(check, passed, detail), ...]}

    # ===================================================================
    # PHASE 1: Loadgens
    # ===================================================================
    if not args.targets_only:
        print(f"\n{'='*60}")
        print(f"  PHASE 1: Loadgen Retake")
        print(f"{'='*60}")

        seen_loadgens = set()
        loadgen_ok = 0
        loadgen_fail = 0

        for t_orm in target_orms:
            loadgen = session.get(ServerORM, t_orm.loadgenerator_id)
            if not loadgen or loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)

            if target_filter and loadgen.hostname.lower() not in target_filter:
                continue

            print(f"\n{'='*60}")
            print(f"  Loadgen: {loadgen.hostname} ({loadgen.ip_address})")

            # Check if clean snapshot already exists (skip unless --force)
            if loadgen.clean_snapshot_id and not args.force:
                old_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                if old_snap:
                    try:
                        exists = provider.snapshot_exists(loadgen.server_infra_ref, old_snap.provider_ref)
                        if exists:
                            print(f"  [SKIP] Clean snapshot already exists: '{old_snap.name}' "
                                  f"(ID={old_snap.id}) — use --force to recreate")
                            loadgen_ok += 1
                            continue
                    except Exception:
                        pass

            # Determine snapshot to work with
            snap_orm = None
            if loadgen.clean_snapshot_id:
                snap_orm = session.get(SnapshotORM, loadgen.clean_snapshot_id)

            if snap_orm is None:
                # First time — no snapshot to revert to. Create a new one.
                # We still fix sudo + firewall + cleanup, then take first snapshot.
                print(f"  No existing clean snapshot — will create new one")
                snap_name = f"clean-{loadgen.hostname}"

                if args.dry_run:
                    print(f"  [DRY RUN] Would: fix sudo -> open firewall -> cleanup -> take snapshot '{snap_name}'")
                    loadgen_ok += 1
                    continue

                try:
                    from orchestrator.infra.remote_executor import create_executor
                    cred = credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                    executor = create_executor(
                        os_family=loadgen.os_family.value,
                        host=loadgen.ip_address,
                        username=cred.username,
                        password=cred.password,
                    )
                    try:
                        # Fix sudo
                        print(f"  [1] Fixing passwordless sudo...")
                        if not fix_sudo(executor, cred.password, args.sudo_user, loadgen.os_family.value):
                            print(f"  [ERROR] Failed to fix sudo — skipping")
                            loadgen_fail += 1
                            continue

                        # Open firewall
                        print(f"  [2] Opening firewall...")
                        open_firewall(executor, loadgen.os_family.value)

                        # Install prerequisites
                        print(f"  [3] Installing prerequisites...")
                        install_prerequisites(executor, loadgen.os_family.value)

                        # Cleanup
                        print(f"  [4] Cleaning...")
                        is_clean = cleanup_loadgen(executor, loadgen.hostname)
                        if not is_clean:
                            print(f"  [ERROR] Not clean — skipping")
                            loadgen_fail += 1
                            continue
                    finally:
                        executor.close()

                    # Take snapshot
                    print(f"  [5] Taking snapshot '{snap_name}'...")
                    result = provider.create_snapshot(
                        loadgen.server_infra_ref,
                        snapshot_name=snap_name,
                        description=f"Clean loadgen state — auto-created by retake_snapshots.py",
                    )
                    new_provider_id = (
                        result.get("snapshot_moref_id")
                        or result.get("snapshot_id")
                        or result.get("snapshot_name")
                    )
                    print(f"      Created: provider_id={new_provider_id}")

                    # Create DB record
                    print(f"  [6] Creating DB snapshot record...")
                    snap_orm = SnapshotORM(
                        name=snap_name,
                        description=f"Clean loadgen snapshot for {loadgen.hostname}",
                        server_id=loadgen.id,
                        parent_id=None,
                        group_id=None,
                        provider_snapshot_id=str(new_provider_id),
                        provider_ref=result,
                        snapshot_tree=[
                            s.to_dict() for s in provider.list_snapshots(loadgen.server_infra_ref)
                        ],
                        is_baseline=False,
                        is_archived=False,
                    )
                    session.add(snap_orm)
                    session.flush()
                    loadgen.clean_snapshot_id = snap_orm.id
                    session.commit()
                    print(f"      DB record ID={snap_orm.id}, linked to server.clean_snapshot_id")

                    # Validate
                    print(f"  [7] Validating snapshot (revert + verify)...")
                    session.refresh(snap_orm)
                    valid, val_checks = validate_snapshot(
                        provider, loadgen, snap_orm.provider_ref, credentials,
                        args.sudo_user, loadgen.os_family.value, wait_for_ssh,
                    )
                    validation_results[f"loadgen:{loadgen.hostname}"] = val_checks
                    if valid:
                        print(f"  [OK] Loadgen {loadgen.hostname}: snapshot validated")
                    else:
                        print(f"  [WARN] Loadgen {loadgen.hostname}: validation had failures")

                    loadgen_ok += 1

                except Exception as e:
                    print(f"  [ERROR] {e}")
                    import traceback
                    traceback.print_exc()
                    loadgen_fail += 1
                    try:
                        session.rollback()
                    except Exception:
                        pass
                continue

            # Has existing snapshot — use unified retake flow
            print(f"  Snapshot: '{snap_orm.name}' (ID={snap_orm.id})")

            try:
                ok, val_checks = retake_one(
                    label="Loadgen",
                    server=loadgen,
                    snapshot=snap_orm,
                    revert_ref=snap_orm.provider_ref,
                    revert_name=snap_orm.name,
                    provider=provider,
                    credentials=credentials,
                    session=session,
                    sudo_user=args.sudo_user,
                    cleanup_fn=_cleanup_loadgen_wrapper,
                    dry_run=args.dry_run,
                    wait_for_ssh_fn=wait_for_ssh,
                )
                validation_results[f"loadgen:{loadgen.hostname}"] = val_checks
                if ok:
                    loadgen_ok += 1
                else:
                    loadgen_fail += 1
            except Exception as e:
                print(f"  [ERROR] {e}")
                import traceback
                traceback.print_exc()
                loadgen_fail += 1
                try:
                    session.rollback()
                except Exception:
                    pass

        print(f"\n  Loadgens: {loadgen_ok} ok, {loadgen_fail} failed")

    # ===================================================================
    # PHASE 2: Targets
    # ===================================================================
    if not args.loadgens_only:
        print(f"\n{'='*60}")
        print(f"  PHASE 2: Target Retake")
        print(f"{'='*60}")

        success_count = 0
        fail_count = 0
        skip_count = 0

        for t_orm in target_orms:
            server = session.get(ServerORM, t_orm.target_id)
            snapshot = session.get(SnapshotORM, t_orm.test_snapshot_id)

            if not server or not snapshot:
                print(f"\n  SKIP: target_id={t_orm.target_id} — server or snapshot not found")
                skip_count += 1
                continue

            if target_filter and server.hostname.lower() not in target_filter:
                continue

            print(f"\n{'='*60}")
            print(f"  Target: {server.hostname} ({server.ip_address})")
            print(f"  Snapshot: '{snapshot.name}' (ID={snapshot.id}, provider={snapshot.provider_snapshot_id})")

            # Determine revert target
            has_parent = snapshot.parent_id is not None
            parent = None
            if has_parent:
                parent = session.get(SnapshotORM, snapshot.parent_id)
                if parent:
                    print(f"  Parent: '{parent.name}' (ID={parent.id})")
                else:
                    print(f"  Parent ID={snapshot.parent_id} not found in DB — treating as root")
                    has_parent = False

            if has_parent:
                revert_ref = parent.provider_ref
                revert_name = parent.name
            else:
                revert_ref = snapshot.provider_ref
                revert_name = f"{snapshot.name} (root — clean in-place)"

            try:
                ok, val_checks = retake_one(
                    label="Target",
                    server=server,
                    snapshot=snapshot,
                    revert_ref=revert_ref,
                    revert_name=revert_name,
                    provider=provider,
                    credentials=credentials,
                    session=session,
                    sudo_user=args.sudo_user,
                    cleanup_fn=_cleanup_target_wrapper,
                    target_orm=t_orm,
                    dry_run=args.dry_run,
                    wait_for_ssh_fn=wait_for_ssh,
                )
                validation_results[f"target:{server.hostname}"] = val_checks
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback
                traceback.print_exc()
                fail_count += 1
                try:
                    session.rollback()
                except Exception:
                    pass

        print(f"\n  Targets: {success_count} ok, {fail_count} failed, {skip_count} skipped")

    # ===================================================================
    # Validation Summary Table
    # ===================================================================
    print(f"\n\n{'='*80}")
    print(f"  VALIDATION SUMMARY")
    print(f"{'='*80}")

    if validation_results:
        # Header
        all_checks = set()
        for checks in validation_results.values():
            for name, _, _ in checks:
                all_checks.add(name)
        check_names = sorted(all_checks)

        # Table header
        col_w = 18
        header = f"  {'Server':<30}"
        for c in check_names:
            header += f" {c:<{col_w}}"
        print(header)
        print(f"  {'-'*30}" + f" {'-'*col_w}" * len(check_names))

        # Table rows
        for server_label, checks in validation_results.items():
            check_map = {name: (passed, detail) for name, passed, detail in checks}
            row = f"  {server_label:<30}"
            for c in check_names:
                if c in check_map:
                    passed, detail = check_map[c]
                    icon = "PASS" if passed else "FAIL"
                    cell = f"{icon}"
                    if detail and not passed:
                        cell += f" ({detail[:10]})"
                    row += f" {cell:<{col_w}}"
                else:
                    row += f" {'-':<{col_w}}"
            print(row)

        # Failed checks detail
        any_fail = False
        for server_label, checks in validation_results.items():
            fails = [(name, detail) for name, passed, detail in checks if not passed]
            if fails:
                if not any_fail:
                    print(f"\n  FAILURES:")
                    any_fail = True
                for name, detail in fails:
                    print(f"    {server_label} / {name}: {detail}")
    else:
        print(f"  No validation results (dry run or all failed before validation)")

    print(f"\n{'='*80}")
    print(f"  DONE")
    if not args.targets_only:
        print(f"  Run sanity check from the UI to confirm all green.")
    print(f"{'='*80}")

    session.close()


if __name__ == "__main__":
    main()
