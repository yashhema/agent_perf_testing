#!/usr/bin/env python3
"""Live calibration test — runs JMeter with the real CSV+JMX and shows CPU in real time.

Generates a calibration CSV, starts JMeter, polls emulator stats every 5s,
and prints exactly what's happening. No orchestrator, no DB, no SSH — just
JMeter → emulator on the same machine or across the network.

Prerequisites:
  - JMeter installed (default: /data/jmeter/bin/jmeter)
  - Emulator running on target (default: localhost:8080)
  - Pool allocated on emulator (script does this automatically)

Usage:
    # Local: JMeter and emulator on same machine
    python test_calibration_live.py --target-ip localhost --threads 4 --duration 60

    # Remote emulator, local JMeter
    python test_calibration_live.py --target-ip 10.200.157.107 --threads 8

    # Custom JMeter path
    python test_calibration_live.py --target-ip localhost --jmeter-bin /opt/jmeter/bin/jmeter

    # Scaling test: run multiple thread counts back-to-back
    python test_calibration_live.py --target-ip localhost --scaling

    # Test with different think time
    python test_calibration_live.py --target-ip localhost --threads 4 --think-ms 100
"""

import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DB_ASSETS = os.path.join(REPO_ROOT, "db-assets")
JMX_SOURCE = os.path.join(REPO_ROOT, "orchestrator", "artifacts", "jmx", "server-steady.jmx")

if DB_ASSETS not in sys.path:
    sys.path.insert(0, DB_ASSETS)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_post(url, data, timeout=30):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Emulator helpers
# ---------------------------------------------------------------------------

def check_health(base_url):
    try:
        resp = http_get(f"{base_url}/api/v1/health")
        print(f"  [OK] Emulator healthy: {resp.get('status')}, uptime={resp.get('uptime_sec', '?')}s")
        return True
    except Exception as e:
        print(f"  [FAIL] Emulator not reachable: {e}")
        return False


def allocate_pool(base_url, heap_pct=0.5):
    try:
        resp = http_post(f"{base_url}/api/v1/config/pool", {"heap_percent": heap_pct})
        if resp.get("allocated"):
            size_mb = resp.get("size_bytes", 0) / 1024 / 1024
            print(f"  [OK] Pool allocated: {size_mb:.0f} MB ({heap_pct*100:.0f}% of heap)")
        else:
            print(f"  [OK] Pool already allocated")
        return True
    except Exception as e:
        print(f"  [FAIL] Pool allocation failed: {e}")
        return False


def start_stats(base_url, tag, threads):
    try:
        resp = http_post(f"{base_url}/api/v1/tests/start", {
            "test_run_id": tag,
            "scenario_id": tag,
            "mode": "calibration",
            "collect_interval_sec": 1.0,
            "thread_count": threads,
        })
        return resp.get("test_id", tag)
    except Exception as e:
        print(f"  [FAIL] Start stats failed: {e}")
        return None


def stop_stats(base_url, test_id):
    try:
        http_post(f"{base_url}/api/v1/tests/{test_id}/stop", {})
    except Exception:
        pass


def read_stats(base_url, count=10):
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count={count}")
        samples = stats.get("samples", [])
        return [s.get("cpu_percent", 0) for s in samples]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

def generate_calibration_csv(output_path, count=500000):
    from generator.generators.ops_sequence_generator import ServerSteadyOpsGenerator, SERVER_FIELDNAMES
    gen = ServerSteadyOpsGenerator(test_run_id="live_test", load_profile="test")
    ops = gen.generate(count)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=SERVER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(ops)

    # Count op distribution
    from collections import Counter
    dist = Counter(row['op_type'] for row in ops[:1000])
    total = sum(dist.values())
    dist_str = ", ".join(f"{op}={c*100//total}%" for op, c in dist.most_common())
    print(f"  [OK] Generated {count} rows → {output_path}")
    print(f"       Op mix (first 1000): {dist_str}")
    return output_path


# ---------------------------------------------------------------------------
# JMeter runner
# ---------------------------------------------------------------------------

def start_jmeter(jmeter_bin, jmx_path, csv_path, jtl_path, log_path,
                 threads, ramp_sec, duration_sec, target_host, target_port,
                 cpu_ms, intensity, touch_mb, think_ms):
    cmd = [
        jmeter_bin, "-n",
        f"-t", jmx_path,
        f"-l", jtl_path,
        f"-j", log_path,
        f"-Jthreads={threads}",
        f"-Jrampup={ramp_sec}",
        f"-Jduration={duration_sec}",
        f"-Jhost={target_host}",
        f"-Jport={target_port}",
        f"-Jops_sequence={csv_path}",
        f"-Jcpu_ms={cpu_ms}",
        f"-Jintensity={intensity}",
        f"-Jtouch_mb={touch_mb}",
        f"-Jthink_ms={think_ms}",
        f"-Jloopcount=-1",
    ]
    print(f"  [CMD] {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc


def stop_jmeter(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_jmeter_alive(proc):
    return proc and proc.poll() is None


# ---------------------------------------------------------------------------
# Single run: start JMeter, monitor CPU, stop
# ---------------------------------------------------------------------------

def run_single_test(args, threads, work_dir, duration_sec=None):
    if duration_sec is None:
        duration_sec = args.duration

    base_url = f"http://{args.target_ip}:{args.port}"
    jmx_path = os.path.join(work_dir, "test.jmx")
    csv_path = os.path.join(work_dir, "calibration_ops.csv")
    jtl_path = os.path.join(work_dir, f"test_T{threads}.jtl")
    log_path = os.path.join(work_dir, f"test_T{threads}.log")

    ramp_sec = min(30, duration_sec // 3)
    observe_after = ramp_sec + 10  # start reading stats after ramp + 10s settle

    print(f"\n{'='*70}")
    print(f"  JMETER LIVE TEST: threads={threads}, duration={duration_sec}s")
    print(f"  Target: {base_url}")
    print(f"  cpu_ms={args.cpu_ms}, intensity={args.intensity}, "
          f"touch_mb={args.touch_mb}, think_ms={args.think_ms}")
    print(f"{'='*70}")

    # Start emulator stats
    test_id = start_stats(base_url, f"live_T{threads}", threads)
    if not test_id:
        return None

    # Start JMeter
    proc = start_jmeter(
        args.jmeter_bin, jmx_path, csv_path, jtl_path, log_path,
        threads, ramp_sec, duration_sec, args.target_ip, args.port,
        args.cpu_ms, args.intensity, args.touch_mb, args.think_ms,
    )

    time.sleep(3)
    if not check_jmeter_alive(proc):
        print(f"  [FAIL] JMeter died within 3 seconds!")
        stdout, stderr = proc.communicate()
        if stderr:
            print(f"  stderr: {stderr.decode()[:500]}")
        stop_stats(base_url, test_id)
        return None

    print(f"  [OK] JMeter started (PID {proc.pid})")
    print(f"  [INFO] Waiting {observe_after}s for ramp+settle...")
    print()

    # Monitor CPU every 5 seconds
    all_cpu = []
    elapsed = 0
    poll_interval = 5
    header_printed = False

    try:
        while elapsed < duration_sec:
            time.sleep(poll_interval)
            elapsed += poll_interval

            if not check_jmeter_alive(proc):
                print(f"\n  [FAIL] JMeter died at {elapsed}s!")
                break

            cpu_vals = read_stats(base_url, count=poll_interval)
            if cpu_vals:
                avg = sum(cpu_vals) / len(cpu_vals)
                phase = "ramp" if elapsed < ramp_sec else "settle" if elapsed < observe_after else "observe"

                if not header_printed:
                    print(f"  {'time':>6}  {'phase':>8}  {'cpu_avg':>8}  {'samples':>8}  {'jmeter':>8}  values")
                    print(f"  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*30}")
                    header_printed = True

                jmeter_status = "alive" if check_jmeter_alive(proc) else "DEAD"
                vals_str = ", ".join(f"{v:.1f}" for v in cpu_vals[-5:])
                print(f"  {elapsed:>5}s  {phase:>8}  {avg:>7.1f}%  {len(cpu_vals):>8}  {jmeter_status:>8}  [{vals_str}]")

                if phase == "observe":
                    all_cpu.extend(cpu_vals)
    except KeyboardInterrupt:
        print("\n  [INFO] Interrupted by user")

    # Stop
    stop_jmeter(proc)
    time.sleep(1)
    stop_stats(base_url, test_id)

    # JTL analysis
    if os.path.exists(jtl_path):
        with open(jtl_path) as f:
            jtl_lines = sum(1 for _ in f) - 1  # minus header
        print(f"\n  JTL: {jtl_lines} requests recorded")

        # Count by label (op type)
        with open(jtl_path) as f:
            reader = csv.DictReader(f)
            from collections import Counter
            labels = Counter()
            errors = 0
            for row in reader:
                labels[row.get('label', '?')] += 1
                if row.get('success', 'true') == 'false':
                    errors += 1
            print(f"  Errors: {errors}/{sum(labels.values())}")
            print(f"  Request distribution:")
            for label, count in labels.most_common():
                print(f"    {label:20s}  {count:>6}  ({count*100//max(1,sum(labels.values()))}%)")

    # Check JMeter log for errors
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_content = f.read()
        error_lines = [l for l in log_content.splitlines()
                       if 'ERROR' in l or 'FATAL' in l or 'Exception' in l]
        if error_lines:
            print(f"\n  [WARN] JMeter log errors ({len(error_lines)}):")
            for line in error_lines[:5]:
                print(f"    {line[:120]}")

    # Summary
    if all_cpu:
        avg_cpu = sum(all_cpu) / len(all_cpu)
        min_cpu = min(all_cpu)
        max_cpu = max(all_cpu)
        print(f"\n  {'─'*50}")
        print(f"  RESULT: threads={threads} → avg CPU={avg_cpu:.1f}% "
              f"(min={min_cpu:.1f}%, max={max_cpu:.1f}%, samples={len(all_cpu)})")
        print(f"  {'─'*50}")
        return avg_cpu
    else:
        print(f"\n  [FAIL] No CPU samples collected")
        return None


# ---------------------------------------------------------------------------
# Scaling test: multiple thread counts
# ---------------------------------------------------------------------------

def run_scaling_test(args, work_dir):
    thread_counts = [1, 2, 4, 8, 16, 24, 32, 50]
    results = []
    dur = 45  # shorter per step for scaling

    print(f"\n{'='*70}")
    print(f"  SCALING TEST (cpu_ms={args.cpu_ms}, touch_mb={args.touch_mb}, think_ms={args.think_ms})")
    print(f"{'='*70}")

    for tc in thread_counts:
        avg_cpu = run_single_test(args, tc, work_dir, duration_sec=dur)
        if avg_cpu is not None:
            results.append((tc, avg_cpu))
        time.sleep(5)  # cooldown

    if results:
        print(f"\n{'='*70}")
        print(f"  SCALING SUMMARY")
        print(f"{'='*70}")
        print(f"\n  {'threads':>8}  {'cpu_avg':>8}  {'profile':>20}")
        print(f"  {'─'*8}  {'─'*8}  {'─'*20}")
        for tc, cpu in results:
            profile = ""
            if 20 <= cpu <= 40:
                profile = "← LOW (20-40%)"
            elif 40 < cpu <= 60:
                profile = "← MEDIUM (40-60%)"
            elif 60 < cpu <= 80:
                profile = "← HIGH (60-80%)"
            elif cpu > 80:
                profile = "← TOO HOT"
            print(f"  {tc:>8}  {cpu:>7.1f}%  {profile}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live calibration test — runs real JMeter+CSV and shows CPU in real time")
    parser.add_argument("--target-ip", default="localhost", help="Emulator target IP")
    parser.add_argument("--port", type=int, default=8080, help="Emulator port")
    parser.add_argument("--threads", type=int, default=4, help="JMeter thread count")
    parser.add_argument("--duration", type=int, default=90, help="Test duration in seconds")
    parser.add_argument("--cpu-ms", type=int, default=200, help="CPU burn ms per /work request")
    parser.add_argument("--intensity", type=float, default=0.8, help="CPU burn intensity")
    parser.add_argument("--touch-mb", type=float, default=1.0, help="Memory touch MB per request")
    parser.add_argument("--think-ms", type=int, default=500, help="Think time between requests")
    parser.add_argument("--jmeter-bin", default="/data/jmeter/bin/jmeter", help="JMeter binary path")
    parser.add_argument("--scaling", action="store_true", help="Run scaling test (1,2,4,8,16,24,32,50 threads)")
    args = parser.parse_args()

    base_url = f"http://{args.target_ip}:{args.port}"

    # Preflight
    print(f"\n{'='*70}")
    print(f"  PREFLIGHT CHECKS")
    print(f"{'='*70}")

    # Check JMeter
    if not os.path.exists(args.jmeter_bin):
        # Try common locations
        for alt in ["/data/jmeter/bin/jmeter", "/opt/jmeter/bin/jmeter",
                    shutil.which("jmeter") or ""]:
            if alt and os.path.exists(alt):
                args.jmeter_bin = alt
                break
        else:
            print(f"  [FAIL] JMeter not found at {args.jmeter_bin}")
            print(f"  Install JMeter or use --jmeter-bin /path/to/jmeter")
            sys.exit(1)
    print(f"  [OK] JMeter: {args.jmeter_bin}")

    # Check JMX
    if not os.path.exists(JMX_SOURCE):
        print(f"  [FAIL] JMX not found: {JMX_SOURCE}")
        sys.exit(1)
    print(f"  [OK] JMX: {JMX_SOURCE}")

    # Check emulator
    if not check_health(base_url):
        sys.exit(1)

    # Allocate pool
    if not allocate_pool(base_url):
        sys.exit(1)

    # Setup work directory
    work_dir = tempfile.mkdtemp(prefix="cal_live_")
    print(f"  [OK] Work dir: {work_dir}")

    try:
        # Copy JMX
        jmx_dest = os.path.join(work_dir, "test.jmx")
        shutil.copy2(JMX_SOURCE, jmx_dest)
        print(f"  [OK] Copied JMX → {jmx_dest}")

        # Generate CSV
        csv_dest = os.path.join(work_dir, "calibration_ops.csv")
        generate_calibration_csv(csv_dest, count=500000)

        # Run test
        if args.scaling:
            run_scaling_test(args, work_dir)
        else:
            run_single_test(args, args.threads, work_dir)

    finally:
        # Cleanup
        print(f"\n  Cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\n{'='*70}")
    print(f"  DONE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
