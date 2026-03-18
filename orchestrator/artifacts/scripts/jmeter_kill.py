#!/usr/bin/env python3
"""Kill JMeter processes on the load generator.

Deployed alongside JMeter. Uses /proc directly (Linux) — no psutil needed.
Called by the orchestrator via SSH instead of fragile shell pipes.

Usage:
    python3 jmeter_kill.py --stop-pid PID [--jtl-path /path/to.jtl]
    python3 jmeter_kill.py --kill-for-target 10.0.0.92
"""

import argparse
import os
import signal
import sys
import time


JMETER_MARKER = "ApacheJMeter"


def read_cmdline(pid):
    """Read /proc/{pid}/cmdline, return as a single string (NUL -> space)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except (OSError, PermissionError):
        return ""


def find_jmeter_processes(filter_fn=None):
    """Find all JMeter java processes. Returns list of (pid, cmdline)."""
    results = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        cmdline = read_cmdline(pid)
        if JMETER_MARKER not in cmdline:
            continue
        if filter_fn and not filter_fn(cmdline):
            continue
        results.append((pid, cmdline))
    return results


def kill_pid(pid, sig=signal.SIGTERM):
    """Send signal to a process. Returns True if signal was sent."""
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        print(f"ERROR: permission denied killing PID {pid}", file=sys.stderr)
        return False


def stop_pid(pid, jtl_path=None):
    """Stop a JMeter process tree.

    1. Kill the shell wrapper by PID.
    2. If jtl_path is given, find the orphaned Java child by matching
       the JTL path in its command line and kill it too.
    """
    killed = []

    # Kill the wrapper PID
    if kill_pid(pid):
        killed.append(pid)
        print(f"Killed wrapper PID {pid}")
    else:
        print(f"Wrapper PID {pid} not found (already exited)")

    # Give a moment for reparenting
    time.sleep(0.5)

    # Find and kill orphaned Java child by JTL path
    if jtl_path:
        matches = find_jmeter_processes(lambda cmd: jtl_path in cmd)
        for child_pid, cmdline in matches:
            if child_pid == pid:
                continue
            if kill_pid(child_pid):
                killed.append(child_pid)
                print(f"Killed orphaned Java PID {child_pid}")

    if not killed:
        print("No processes killed")
    else:
        print(f"Total killed: {len(killed)} PIDs: {killed}")

    return len(killed)


def kill_for_target(target_host):
    """Kill all JMeter processes targeting a specific server.

    Matches -Jhost={target_host} in the command line so JMeter
    processes for other targets on a shared loadgen are not affected.
    """
    marker = f"Jhost={target_host}"
    matches = find_jmeter_processes(lambda cmd: marker in cmd)

    if not matches:
        print(f"No JMeter processes found for target {target_host}")
        return 0

    killed = []
    for pid, cmdline in matches:
        if kill_pid(pid):
            killed.append(pid)
            print(f"Killed PID {pid} (target={target_host})")

    # Wait briefly then verify
    time.sleep(1)
    remaining = find_jmeter_processes(lambda cmd: marker in cmd)
    if remaining:
        print(f"WARNING: {len(remaining)} processes still running, sending SIGKILL")
        for pid, _ in remaining:
            kill_pid(pid, signal.SIGKILL)

    print(f"Total killed: {len(killed)} PIDs: {killed}")
    return len(killed)


def main():
    parser = argparse.ArgumentParser(description="Kill JMeter processes on load generator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stop-pid", type=int, help="Stop JMeter by wrapper PID")
    group.add_argument("--kill-for-target", type=str, help="Kill all JMeter for a target host")

    parser.add_argument("--jtl-path", type=str, help="JTL path to identify orphaned Java child (with --stop-pid)")

    args = parser.parse_args()

    if args.stop_pid:
        count = stop_pid(args.stop_pid, args.jtl_path)
    else:
        count = kill_for_target(args.kill_for_target)

    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
