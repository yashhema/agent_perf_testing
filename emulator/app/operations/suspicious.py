"""Suspicious system-level activity operations.

Performs OS-level activities that security agents (EDR/AV) would typically
flag as suspicious. Used as an end-test after normal load profiles to
observe how security agents respond to suspicious behavior.

Activities are benign but trigger EDR heuristics:
  Linux: crontab writes, /tmp executables, process spawning, syslog injection,
         /etc/hosts modification, sensitive file access
  Windows: registry writes, scheduled tasks, service creation attempts

Each activity is atomic — does something suspicious then immediately cleans up.
"""

import asyncio
import os
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SuspiciousOperationParams:
    """Parameters for suspicious activity operation."""
    activity_type: str  # e.g., "crontab_write", "registry_write", "tmp_executable"
    duration_ms: int = 500  # how long to keep the artifact alive before cleanup


@dataclass(frozen=True)
class SuspiciousOperationResult:
    """Result of suspicious activity operation."""
    operation: str
    activity_type: str
    status: str  # "completed", "error", "skipped"
    actual_duration_ms: int
    detail: str
    os_family: str
    error_message: Optional[str] = None


# Activities available per OS
LINUX_ACTIVITIES = [
    "crontab_write",
    "tmp_executable",
    "process_spawn",
    "etc_hosts_modify",
    "sensitive_file_access",
    "syslog_inject",
    "hidden_file_create",
    "setuid_attempt",
]

WINDOWS_ACTIVITIES = [
    "registry_write",
    "scheduled_task",
    "service_query",
    "hidden_file_create",
    "powershell_encoded",
    "hosts_file_modify",
    "startup_folder_write",
    "wmi_query",
]


def _detect_os_family() -> str:
    return "windows" if platform.system() == "Windows" else "linux"


class SuspiciousOperation:
    """Execute suspicious system-level activities."""

    @staticmethod
    async def execute(params: SuspiciousOperationParams) -> SuspiciousOperationResult:
        """Execute a suspicious activity asynchronously."""
        os_family = _detect_os_family()
        start = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()
            detail = await loop.run_in_executor(
                None,
                SuspiciousOperation._execute_activity,
                params.activity_type,
                params.duration_ms,
                os_family,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return SuspiciousOperationResult(
                operation="suspicious",
                activity_type=params.activity_type,
                status="completed",
                actual_duration_ms=elapsed_ms,
                detail=detail,
                os_family=os_family,
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return SuspiciousOperationResult(
                operation="suspicious",
                activity_type=params.activity_type,
                status="error",
                actual_duration_ms=elapsed_ms,
                detail="",
                os_family=os_family,
                error_message=str(e),
            )

    @staticmethod
    def _execute_activity(activity_type: str, duration_ms: int, os_family: str) -> str:
        """Dispatch to the correct activity handler."""
        if os_family == "linux":
            return _linux_activities.get(activity_type, _noop)(duration_ms)
        else:
            return _windows_activities.get(activity_type, _noop)(duration_ms)


def _noop(duration_ms: int) -> str:
    return "skipped: unknown activity type"


# ---------------------------------------------------------------------------
# Linux suspicious activities
# ---------------------------------------------------------------------------

def _linux_crontab_write(duration_ms: int) -> str:
    """Write a temporary crontab entry (triggers crontab monitoring)."""
    cron_file = "/tmp/.emulator_cron_test"
    entry = "* * * * * /bin/echo emulator_suspicious_test > /dev/null 2>&1\n"
    try:
        with open(cron_file, "w") as f:
            f.write(entry)
        # Try to install it (may fail without root, that's OK — the file creation is the trigger)
        subprocess.run(["crontab", cron_file], capture_output=True, timeout=5)
        time.sleep(duration_ms / 1000)
        # Cleanup
        subprocess.run(["crontab", "-r"], capture_output=True, timeout=5)
    finally:
        if os.path.exists(cron_file):
            os.remove(cron_file)
    return "crontab entry written and removed"


def _linux_tmp_executable(duration_ms: int) -> str:
    """Create an executable file in /tmp (common malware staging area)."""
    tmp_path = "/tmp/.emulator_suspicious_bin"
    try:
        with open(tmp_path, "w") as f:
            f.write("#!/bin/bash\necho 'emulator test'\n")
        os.chmod(tmp_path, 0o755)
        time.sleep(duration_ms / 1000)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return f"executable created at {tmp_path} and removed"


def _linux_process_spawn(duration_ms: int) -> str:
    """Spawn shell processes (EDR monitors unusual process trees)."""
    procs = []
    try:
        for i in range(3):
            p = subprocess.Popen(
                ["bash", "-c", f"sleep {duration_ms / 1000}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            procs.append(p)
        for p in procs:
            p.wait(timeout=max(duration_ms / 1000 + 2, 5))
    except Exception:
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
    return f"spawned {len(procs)} shell processes"


def _linux_etc_hosts_modify(duration_ms: int) -> str:
    """Append and remove an entry from /etc/hosts (requires root)."""
    marker = "# emulator-suspicious-test"
    entry = f"127.0.0.1 suspicious-test.local {marker}\n"
    try:
        with open("/etc/hosts", "a") as f:
            f.write(entry)
        time.sleep(duration_ms / 1000)
        # Remove the entry
        with open("/etc/hosts", "r") as f:
            lines = f.readlines()
        with open("/etc/hosts", "w") as f:
            f.writelines(line for line in lines if marker not in line)
        return "/etc/hosts modified and restored"
    except PermissionError:
        return "/etc/hosts modify attempted (permission denied — still triggers inotify)"


def _linux_sensitive_file_access(duration_ms: int) -> str:
    """Attempt to read sensitive files (triggers file access monitoring)."""
    sensitive_paths = ["/etc/shadow", "/etc/gshadow", "/etc/sudoers"]
    accessed = []
    for path in sensitive_paths:
        try:
            with open(path, "r") as f:
                _ = f.read(1)
            accessed.append(f"{path}:read")
        except PermissionError:
            accessed.append(f"{path}:denied")
        except FileNotFoundError:
            pass
    time.sleep(duration_ms / 1000)
    return f"accessed: {', '.join(accessed)}"


def _linux_syslog_inject(duration_ms: int) -> str:
    """Write suspicious-looking entries to syslog."""
    try:
        import syslog
        messages = [
            "emulator-test: suspicious connection attempt from 10.0.0.99",
            "emulator-test: unauthorized privilege escalation detected",
            "emulator-test: kernel module loaded from /tmp",
        ]
        for msg in messages:
            syslog.syslog(syslog.LOG_WARNING, msg)
        time.sleep(duration_ms / 1000)
        return f"injected {len(messages)} syslog entries"
    except Exception as e:
        return f"syslog injection failed: {e}"


def _linux_hidden_file_create(duration_ms: int) -> str:
    """Create hidden files in home and /tmp (common persistence technique)."""
    paths = ["/tmp/.emulator_hidden_config", "/tmp/.emulator_hidden_cache"]
    try:
        for p in paths:
            with open(p, "w") as f:
                f.write("emulator_suspicious_data\n")
        time.sleep(duration_ms / 1000)
    finally:
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
    return f"created {len(paths)} hidden files and removed"


def _linux_setuid_attempt(duration_ms: int) -> str:
    """Attempt to set SUID bit on a file (triggers privilege escalation alerts)."""
    tmp_path = "/tmp/.emulator_setuid_test"
    try:
        with open(tmp_path, "w") as f:
            f.write("#!/bin/bash\necho test\n")
        try:
            os.chmod(tmp_path, 0o4755)
            detail = "SUID bit set"
        except PermissionError:
            detail = "SUID attempt denied (still triggers monitoring)"
        time.sleep(duration_ms / 1000)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return detail


# ---------------------------------------------------------------------------
# Windows suspicious activities
# ---------------------------------------------------------------------------

def _windows_registry_write(duration_ms: int) -> str:
    """Write a temporary registry key (common malware persistence)."""
    try:
        import winreg
        key_path = r"SOFTWARE\EmulatorSuspiciousTest"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "TestValue", 0, winreg.REG_SZ, "emulator_test")
        winreg.CloseKey(key)
        time.sleep(duration_ms / 1000)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        return f"registry key HKCU\\{key_path} written and removed"
    except Exception as e:
        return f"registry write: {e}"


def _windows_scheduled_task(duration_ms: int) -> str:
    """Create and remove a scheduled task."""
    task_name = "EmulatorSuspiciousTest"
    try:
        subprocess.run(
            ["schtasks", "/Create", "/TN", task_name, "/TR", "cmd /c echo test",
             "/SC", "ONCE", "/ST", "23:59", "/F"],
            capture_output=True, timeout=10,
        )
        time.sleep(duration_ms / 1000)
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, timeout=10,
        )
        return f"scheduled task '{task_name}' created and removed"
    except Exception as e:
        return f"scheduled task: {e}"


def _windows_service_query(duration_ms: int) -> str:
    """Query and enumerate services (reconnaissance activity)."""
    try:
        result = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "all"],
            capture_output=True, timeout=10, text=True,
        )
        svc_count = result.stdout.count("SERVICE_NAME")
        time.sleep(duration_ms / 1000)
        return f"enumerated {svc_count} services"
    except Exception as e:
        return f"service query: {e}"


def _windows_hidden_file_create(duration_ms: int) -> str:
    """Create hidden files in temp directory."""
    tmp_dir = tempfile.gettempdir()
    paths = [
        os.path.join(tmp_dir, "emulator_hidden_config.dat"),
        os.path.join(tmp_dir, "emulator_hidden_cache.dat"),
    ]
    try:
        for p in paths:
            with open(p, "w") as f:
                f.write("emulator_suspicious_data\n")
            subprocess.run(["attrib", "+H", p], capture_output=True, timeout=5)
        time.sleep(duration_ms / 1000)
    finally:
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
    return f"created {len(paths)} hidden files and removed"


def _windows_powershell_encoded(duration_ms: int) -> str:
    """Execute encoded PowerShell command (common evasion technique)."""
    import base64
    # Benign command encoded as base64 (EDR flags encoded PS execution)
    cmd = 'Write-Host "emulator suspicious test"'
    encoded = base64.b64encode(cmd.encode("utf-16-le")).decode()
    try:
        subprocess.run(
            ["powershell", "-EncodedCommand", encoded],
            capture_output=True, timeout=10,
        )
        time.sleep(duration_ms / 1000)
        return "executed encoded PowerShell command"
    except Exception as e:
        return f"encoded powershell: {e}"


def _windows_hosts_file_modify(duration_ms: int) -> str:
    """Modify Windows hosts file (requires admin)."""
    hosts_path = r"C:\Windows\System32\drivers\etc\hosts"
    marker = "# emulator-suspicious-test"
    entry = f"127.0.0.1 suspicious-test.local {marker}\n"
    try:
        with open(hosts_path, "a") as f:
            f.write(entry)
        time.sleep(duration_ms / 1000)
        with open(hosts_path, "r") as f:
            lines = f.readlines()
        with open(hosts_path, "w") as f:
            f.writelines(line for line in lines if marker not in line)
        return "hosts file modified and restored"
    except PermissionError:
        return "hosts file modify attempted (access denied — still triggers monitoring)"


def _windows_startup_folder_write(duration_ms: int) -> str:
    """Write to startup folder (persistence technique)."""
    startup = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
    test_file = os.path.join(startup, "emulator_suspicious_test.bat")
    try:
        with open(test_file, "w") as f:
            f.write("@echo off\necho emulator test\n")
        time.sleep(duration_ms / 1000)
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
    return "startup folder script created and removed"


def _windows_wmi_query(duration_ms: int) -> str:
    """Execute WMI queries (reconnaissance/lateral movement indicator)."""
    try:
        result = subprocess.run(
            ["wmic", "process", "list", "brief"],
            capture_output=True, timeout=10, text=True,
        )
        proc_count = len(result.stdout.strip().split("\n")) - 1
        time.sleep(duration_ms / 1000)
        return f"WMI enumerated {proc_count} processes"
    except Exception as e:
        return f"WMI query: {e}"


# Activity dispatch tables
_linux_activities = {
    "crontab_write": _linux_crontab_write,
    "tmp_executable": _linux_tmp_executable,
    "process_spawn": _linux_process_spawn,
    "etc_hosts_modify": _linux_etc_hosts_modify,
    "sensitive_file_access": _linux_sensitive_file_access,
    "syslog_inject": _linux_syslog_inject,
    "hidden_file_create": _linux_hidden_file_create,
    "setuid_attempt": _linux_setuid_attempt,
}

_windows_activities = {
    "registry_write": _windows_registry_write,
    "scheduled_task": _windows_scheduled_task,
    "service_query": _windows_service_query,
    "hidden_file_create": _windows_hidden_file_create,
    "powershell_encoded": _windows_powershell_encoded,
    "hosts_file_modify": _windows_hosts_file_modify,
    "startup_folder_write": _windows_startup_folder_write,
    "wmi_query": _windows_wmi_query,
}
