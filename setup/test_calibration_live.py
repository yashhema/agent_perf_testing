#!/usr/bin/env python3
"""Live calibration test -- runs JMeter with the real CSV+JMX and shows CPU in real time.

Generates a calibration CSV, starts JMeter, polls emulator stats every 5s,
and prints exactly what's happening. All output is printed AND saved to a log file.
Also fetches emulator-side request logs to see what the emulator actually received.

Prerequisites:
  - JMeter installed (default: /data/jmeter/bin/jmeter)
  - Emulator running on target (default: localhost:8080)
  - Pool allocated on emulator (script does this automatically)

Usage:
    # Single thread count test
    python test_calibration_live.py --target-ip 10.200.157.107 --threads 4 --duration 60

    # Scaling test: thread counts 1,2,4,8,16,24,32,50
    python test_calibration_live.py --target-ip 10.200.157.107 --scaling

    # Custom params
    python test_calibration_live.py --target-ip localhost --threads 8 --cpu-ms 200 --think-ms 100

Output saved to: calibration_live_<timestamp>.log
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DB_ASSETS = os.path.join(REPO_ROOT, "db-assets")
JMX_SOURCE = os.path.join(REPO_ROOT, "orchestrator", "artifacts", "jmx", "server-steady.jmx")
JMETER_ARTIFACT = os.path.join(REPO_ROOT, "orchestrator", "artifacts", "packages", "jmeter-5.6.3-linux.tar.gz")

if DB_ASSETS not in sys.path:
    sys.path.insert(0, DB_ASSETS)


# ---------------------------------------------------------------------------
# Logging -- print to console AND write to file
# ---------------------------------------------------------------------------

_log_file = None

def log(msg=""):
    print(msg)
    if _log_file:
        _log_file.write(msg + "\n")
        _log_file.flush()


def init_log(log_path):
    global _log_file
    _log_file = open(log_path, "w", encoding="utf-8")
    log(f"Log file: {log_path}")


def close_log():
    global _log_file
    if _log_file:
        _log_file.close()
        _log_file = None


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
        log(f"  [OK] Emulator healthy: {resp.get('status')}, uptime={resp.get('uptime_sec', '?')}s")
        return True
    except Exception as e:
        log(f"  [FAIL] Emulator not reachable at {base_url}: {e}")
        return False


def allocate_pool(base_url, heap_pct=0.5):
    try:
        resp = http_post(f"{base_url}/api/v1/config/pool", {"heap_percent": heap_pct})
        if resp.get("allocated"):
            size_mb = resp.get("size_bytes", 0) / 1024 / 1024
            log(f"  [OK] Pool allocated: {size_mb:.0f} MB ({heap_pct*100:.0f}% of heap)")
        else:
            log(f"  [OK] Pool already allocated")
        return True
    except Exception as e:
        log(f"  [FAIL] Pool allocation failed: {e}")
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
        log(f"  [FAIL] Start stats failed: {e}")
        return None


def stop_stats(base_url, test_id):
    try:
        http_post(f"{base_url}/api/v1/tests/{test_id}/stop", {})
    except Exception:
        pass


def read_stats(base_url, count=10):
    """Read recent CPU/MEM samples from emulator."""
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count={count}")
        samples = stats.get("samples", [])
        return samples  # return full samples, not just CPU
    except Exception:
        return []


def get_emulator_request_log(base_url, count=20):
    """Get the emulator's recent request log -- shows what endpoints were hit."""
    # Try multiple possible endpoints
    for endpoint in [
        f"{base_url}/api/v1/stats/requests",
        f"{base_url}/api/v1/operations/stats",
        f"{base_url}/api/v1/stats/operations",
    ]:
        try:
            resp = http_get(endpoint)
            return resp
        except Exception:
            continue
    return None


def get_emulator_config(base_url):
    """Get current emulator config."""
    try:
        resp = http_get(f"{base_url}/api/v1/config")
        return resp
    except Exception:
        return None


def check_emulator_test_status(base_url):
    """Check if emulator has an active test running."""
    try:
        resp = http_get(f"{base_url}/api/v1/tests/current")
        return resp
    except Exception:
        return None


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
    log(f"  [OK] Generated {count} rows -> {output_path}")
    log(f"       Op mix (first 1000): {dist_str}")

    # Show first 5 data rows
    log(f"       First 5 rows:")
    for row in ops[:5]:
        log(f"         {row['seq_id']:>5}  op={row['op_type']}")

    return output_path


# ---------------------------------------------------------------------------
# JMeter runner
# ---------------------------------------------------------------------------

def start_jmeter(jmeter_bin, jmx_path, csv_path, jtl_path, log_path,
                 threads, ramp_sec, duration_sec, target_host, target_port,
                 cpu_ms, intensity, touch_mb, think_ms):
    cmd = [
        jmeter_bin, "-n",
        "-t", jmx_path,
        "-l", jtl_path,
        "-j", log_path,
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
        "-Jloopcount=-1",
    ]
    log(f"  [CMD] {' '.join(cmd)}")
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
# Single run: start JMeter, monitor CPU, stop, analyze everything
# ---------------------------------------------------------------------------

def run_single_test(args, threads, work_dir, duration_sec=None):
    if duration_sec is None:
        duration_sec = args.duration

    base_url = f"http://{args.target_ip}:{args.port}"
    jmx_path = os.path.join(work_dir, "test.jmx")
    csv_path = os.path.join(work_dir, "calibration_ops.csv")
    jtl_path = os.path.join(work_dir, f"test_T{threads}.jtl")
    jmeter_log_path = os.path.join(work_dir, f"test_T{threads}.log")

    ramp_sec = min(30, duration_sec // 3)
    observe_after = ramp_sec + 10

    log(f"\n{'='*70}")
    log(f"  JMETER LIVE TEST: threads={threads}, duration={duration_sec}s")
    log(f"  Target: {base_url}")
    log(f"  cpu_ms={args.cpu_ms}, intensity={args.intensity}, "
        f"touch_mb={args.touch_mb}, think_ms={args.think_ms}")
    log(f"  JMX: {jmx_path}")
    log(f"  CSV: {csv_path}")
    log(f"  JTL: {jtl_path}")
    log(f"{'='*70}")

    # Check emulator state BEFORE starting
    log(f"\n  --- Pre-test emulator state ---")
    emu_config = get_emulator_config(base_url)
    if emu_config:
        log(f"  Emulator config: {json.dumps(emu_config, indent=2)[:500]}")

    test_status = check_emulator_test_status(base_url)
    if test_status:
        log(f"  Active test: {json.dumps(test_status)[:200]}")

    # Read baseline CPU before JMeter starts
    baseline_samples = read_stats(base_url, count=5)
    if baseline_samples:
        baseline_cpu = [s.get("cpu_percent", 0) for s in baseline_samples]
        log(f"  Baseline CPU (before JMeter): {[round(v, 1) for v in baseline_cpu]}")
    else:
        log(f"  Baseline CPU: no samples available")

    # Start emulator stats
    test_id = start_stats(base_url, f"live_T{threads}", threads)
    if not test_id:
        return None
    log(f"  Stats collection started (test_id={test_id})")

    # Start JMeter
    proc = start_jmeter(
        args.jmeter_bin, jmx_path, csv_path, jtl_path, jmeter_log_path,
        threads, ramp_sec, duration_sec, args.target_ip, args.port,
        args.cpu_ms, args.intensity, args.touch_mb, args.think_ms,
    )

    time.sleep(3)
    if not check_jmeter_alive(proc):
        log(f"  [FAIL] JMeter died within 3 seconds!")
        stdout, stderr = proc.communicate()
        if stdout:
            log(f"  stdout: {stdout.decode()[:500]}")
        if stderr:
            log(f"  stderr: {stderr.decode()[:500]}")
        stop_stats(base_url, test_id)
        return None

    log(f"  [OK] JMeter started (PID {proc.pid})")
    log(f"  Ramp={ramp_sec}s, observe_after={observe_after}s, total={duration_sec}s")
    log()

    # Monitor loop
    all_cpu = []
    all_mem = []
    elapsed = 0
    poll_interval = 5
    header_printed = False
    request_count_at_start = None

    try:
        while elapsed < duration_sec:
            time.sleep(poll_interval)
            elapsed += poll_interval

            jmeter_alive = check_jmeter_alive(proc)
            if not jmeter_alive:
                log(f"\n  [FAIL] JMeter died at {elapsed}s!")
                stdout, stderr = proc.communicate()
                if stderr:
                    log(f"  stderr: {stderr.decode()[:300]}")
                break

            samples = read_stats(base_url, count=poll_interval)
            if samples:
                cpu_vals = [s.get("cpu_percent", 0) for s in samples]
                mem_vals = [s.get("mem_percent", 0) for s in samples]
                avg_cpu = sum(cpu_vals) / len(cpu_vals)
                avg_mem = sum(mem_vals) / len(mem_vals) if mem_vals else 0
                phase = "ramp" if elapsed < ramp_sec else "settle" if elapsed < observe_after else "observe"

                if not header_printed:
                    log(f"  {'time':>6}  {'phase':>8}  {'cpu%':>7}  {'mem%':>7}  {'samples':>7}  {'jmeter':>7}  cpu_values")
                    log(f"  {'---':>6}  {'---':>8}  {'---':>7}  {'---':>7}  {'---':>7}  {'---':>7}  {'---':>30}")
                    header_printed = True

                jm_str = "alive" if jmeter_alive else "DEAD"
                vals_str = ", ".join(f"{v:.1f}" for v in cpu_vals[-5:])
                log(f"  {elapsed:>5}s  {phase:>8}  {avg_cpu:>6.1f}%  {avg_mem:>6.1f}%  {len(cpu_vals):>7}  {jm_str:>7}  [{vals_str}]")

                if phase == "observe":
                    all_cpu.extend(cpu_vals)
                    all_mem.extend(mem_vals)
            else:
                log(f"  {elapsed:>5}s  {'---':>8}  {'---':>7}  {'---':>7}  {'0':>7}  {'?':>7}  [no samples!]")

    except KeyboardInterrupt:
        log("\n  [INFO] Interrupted by user")

    # Stop JMeter
    log(f"\n  Stopping JMeter...")
    stop_jmeter(proc)
    time.sleep(2)

    # Read final stats before stopping collection
    final_samples = read_stats(base_url, count=5)
    if final_samples:
        final_cpu = [s.get("cpu_percent", 0) for s in final_samples]
        log(f"  Post-stop CPU: {[round(v, 1) for v in final_cpu]}")

    stop_stats(base_url, test_id)

    # --- Emulator request log ---
    log(f"\n  --- Emulator request analysis ---")
    req_log = get_emulator_request_log(base_url)
    if req_log:
        log(f"  Emulator request stats: {json.dumps(req_log, indent=2)[:1000]}")
    else:
        log(f"  No emulator request log endpoint available")

    # --- JTL analysis ---
    log(f"\n  --- JTL analysis ---")
    if os.path.exists(jtl_path):
        with open(jtl_path) as f:
            jtl_lines = sum(1 for _ in f) - 1
        log(f"  Total requests: {jtl_lines}")

        if jtl_lines > 0:
            with open(jtl_path) as f:
                reader = csv.DictReader(f)
                from collections import Counter
                labels = Counter()
                success_count = 0
                error_count = 0
                response_codes = Counter()
                elapsed_times = []
                first_ts = None
                last_ts = None

                for row in reader:
                    labels[row.get('label', '?')] += 1
                    if row.get('success', 'true').lower() == 'true':
                        success_count += 1
                    else:
                        error_count += 1
                    response_codes[row.get('responseCode', '?')] += 1
                    try:
                        elapsed_times.append(int(row.get('elapsed', 0)))
                    except (ValueError, TypeError):
                        pass
                    try:
                        ts = int(row.get('timeStamp', 0))
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                    except (ValueError, TypeError):
                        pass

            total = sum(labels.values())
            log(f"  Success: {success_count}, Errors: {error_count}")

            if first_ts and last_ts and last_ts > first_ts:
                actual_duration = (last_ts - first_ts) / 1000
                throughput = total / actual_duration if actual_duration > 0 else 0
                log(f"  Actual duration: {actual_duration:.1f}s, Throughput: {throughput:.1f} req/s")

            log(f"  Response codes: {dict(response_codes.most_common())}")

            if elapsed_times:
                elapsed_times.sort()
                avg_rt = sum(elapsed_times) / len(elapsed_times)
                p50_rt = elapsed_times[len(elapsed_times) // 2]
                p95_rt = elapsed_times[int(len(elapsed_times) * 0.95)]
                log(f"  Response times: avg={avg_rt:.0f}ms p50={p50_rt}ms p95={p95_rt}ms "
                    f"min={elapsed_times[0]}ms max={elapsed_times[-1]}ms")

            log(f"\n  Request distribution:")
            for label, count in labels.most_common():
                pct = count * 100 // max(1, total)
                avg_rt_label = ""
                log(f"    {label:20s}  {count:>6}  ({pct}%)")

            # Show first 5 error rows if any
            if error_count > 0:
                log(f"\n  First 5 errors:")
                with open(jtl_path) as f:
                    reader = csv.DictReader(f)
                    shown = 0
                    for row in reader:
                        if row.get('success', 'true').lower() != 'true' and shown < 5:
                            log(f"    label={row.get('label')} code={row.get('responseCode')} "
                                f"msg={row.get('responseMessage', '')[:80]}")
                            shown += 1
    else:
        log(f"  [WARN] No JTL file found at {jtl_path}")

    # --- JMeter log analysis ---
    log(f"\n  --- JMeter log analysis ---")
    if os.path.exists(jmeter_log_path):
        with open(jmeter_log_path) as f:
            log_lines = f.readlines()

        total_lines = len(log_lines)
        error_lines = [l.strip() for l in log_lines
                       if 'ERROR' in l or 'FATAL' in l]
        warn_lines = [l.strip() for l in log_lines
                      if 'WARN' in l]

        log(f"  Log lines: {total_lines}, Errors: {len(error_lines)}, Warnings: {len(warn_lines)}")

        if error_lines:
            log(f"  ERROR lines:")
            for line in error_lines[:10]:
                log(f"    {line[:150]}")

        if warn_lines:
            log(f"  WARN lines (first 5):")
            for line in warn_lines[:5]:
                log(f"    {line[:150]}")

        # Show last 10 lines of JMeter log
        log(f"\n  Last 10 lines of JMeter log:")
        for line in log_lines[-10:]:
            log(f"    {line.rstrip()}")
    else:
        log(f"  [WARN] No JMeter log found at {jmeter_log_path}")

    # --- CPU Summary ---
    if all_cpu:
        avg_cpu = sum(all_cpu) / len(all_cpu)
        min_cpu = min(all_cpu)
        max_cpu = max(all_cpu)
        avg_mem = sum(all_mem) / len(all_mem) if all_mem else 0

        log(f"\n  {'='*50}")
        log(f"  RESULT: threads={threads}")
        log(f"    CPU:  avg={avg_cpu:.1f}%  min={min_cpu:.1f}%  max={max_cpu:.1f}%  samples={len(all_cpu)}")
        log(f"    MEM:  avg={avg_mem:.1f}%")
        log(f"  {'='*50}")
        return avg_cpu
    else:
        log(f"\n  [FAIL] No CPU samples collected during observe phase")
        return None


# ---------------------------------------------------------------------------
# Scaling test
# ---------------------------------------------------------------------------

def run_scaling_test(args, work_dir):
    thread_counts = [1, 2, 4, 8, 16, 24, 32, 50]
    results = []
    dur = 45

    log(f"\n{'='*70}")
    log(f"  SCALING TEST")
    log(f"  cpu_ms={args.cpu_ms}, touch_mb={args.touch_mb}, think_ms={args.think_ms}")
    log(f"  Thread counts: {thread_counts}")
    log(f"  Duration per step: {dur}s")
    log(f"{'='*70}")

    for tc in thread_counts:
        avg_cpu = run_single_test(args, tc, work_dir, duration_sec=dur)
        if avg_cpu is not None:
            results.append((tc, avg_cpu))
        time.sleep(5)

    if results:
        log(f"\n{'='*70}")
        log(f"  SCALING SUMMARY")
        log(f"{'='*70}")
        log(f"\n  {'threads':>8}  {'cpu_avg':>8}  {'profile':>20}")
        log(f"  {'--------':>8}  {'--------':>8}  {'--------------------':>20}")
        for tc, cpu in results:
            profile = ""
            if 20 <= cpu <= 40:
                profile = "<-- LOW (20-40%)"
            elif 40 < cpu <= 60:
                profile = "<-- MEDIUM (40-60%)"
            elif 60 < cpu <= 80:
                profile = "<-- HIGH (60-80%)"
            elif cpu > 80:
                profile = "<-- TOO HOT"
            elif cpu < 20:
                profile = "<-- TOO COLD"
            log(f"  {tc:>8}  {cpu:>7.1f}%  {profile}")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live calibration test -- runs real JMeter+CSV, shows CPU live, saves everything to log")
    parser.add_argument("--target-ip", default="localhost", help="Emulator target IP")
    parser.add_argument("--port", type=int, default=8080, help="Emulator port")
    parser.add_argument("--threads", type=int, default=4, help="JMeter thread count")
    parser.add_argument("--duration", type=int, default=90, help="Test duration in seconds")
    parser.add_argument("--cpu-ms", type=int, default=200, help="CPU burn ms per /work request")
    parser.add_argument("--intensity", type=float, default=0.8, help="CPU burn intensity")
    parser.add_argument("--touch-mb", type=float, default=1.0, help="Memory touch MB per request")
    parser.add_argument("--think-ms", type=int, default=500, help="Think time between requests (ms)")
    parser.add_argument("--jmeter-bin", default="/data/jmeter/bin/jmeter", help="JMeter binary path")
    parser.add_argument("--scaling", action="store_true", help="Run scaling test (1,2,4,8,16,24,32,50 threads)")
    parser.add_argument("--log-dir", default=".", help="Directory for log file output")
    args = parser.parse_args()

    base_url = f"http://{args.target_ip}:{args.port}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(args.log_dir, f"calibration_live_{timestamp}.log")

    # Init logging
    init_log(log_path)

    log(f"{'='*70}")
    log(f"  CALIBRATION LIVE TEST")
    log(f"  Started: {datetime.now().isoformat()}")
    log(f"  Target: {base_url}")
    log(f"  Params: cpu_ms={args.cpu_ms} intensity={args.intensity} "
        f"touch_mb={args.touch_mb} think_ms={args.think_ms}")
    log(f"  Mode: {'scaling' if args.scaling else f'single (threads={args.threads})'}")
    log(f"  Log: {log_path}")
    log(f"{'='*70}")

    # --- Preflight ---
    log(f"\n  --- Preflight ---")

    # Check JMeter — use existing install or extract from artifact to /data/jmeter
    jmeter_bin = args.jmeter_bin
    jmeter_found = os.path.exists(jmeter_bin)

    if not jmeter_found:
        # Not at default/user path — try to install from artifact
        if not os.path.exists(JMETER_ARTIFACT):
            log(f"  [FAIL] JMeter not found at {jmeter_bin}")
            log(f"         Artifact not found: {JMETER_ARTIFACT}")
            close_log()
            sys.exit(1)

        import tarfile
        import getpass
        install_dir = "/data/jmeter"
        log(f"  [INFO] JMeter not found at {jmeter_bin}")
        log(f"  [INFO] Installing from {JMETER_ARTIFACT} to {install_dir}...")

        # Create /data if it doesn't exist
        if not os.path.exists("/data"):
            log(f"  [INFO] Creating /data ...")
            os.system("sudo mkdir -p /data")
            user = getpass.getuser()
            os.system(f"sudo chown {user}:{user} /data")
            log(f"  [OK] Created /data, owned by {user}")

        # Extract: tar.gz has apache-jmeter-5.6.3/ at the top level
        os.makedirs(install_dir, exist_ok=True)
        with tarfile.open(JMETER_ARTIFACT, "r:gz") as tar:
            tar.extractall(install_dir)
        log(f"  [OK] Extracted to {install_dir}")

        # The tar extracts to apache-jmeter-X.Y.Z/ — flatten it
        subdirs = [d for d in os.listdir(install_dir)
                   if os.path.isdir(os.path.join(install_dir, d)) and d.startswith("apache-jmeter")]
        if subdirs:
            extracted = os.path.join(install_dir, subdirs[0])
            # Move contents up: /data/jmeter/apache-jmeter-5.6.3/* -> /data/jmeter/*
            for item in os.listdir(extracted):
                src = os.path.join(extracted, item)
                dst = os.path.join(install_dir, item)
                if not os.path.exists(dst):
                    shutil.move(src, dst)
            shutil.rmtree(extracted, ignore_errors=True)
            log(f"  [OK] Flattened {subdirs[0]} -> {install_dir}")

        # Make binary executable
        jmeter_bin = os.path.join(install_dir, "bin", "jmeter")
        if os.path.exists(jmeter_bin):
            os.chmod(jmeter_bin, 0o755)
            args.jmeter_bin = jmeter_bin
            jmeter_found = True
        else:
            # List what's actually there
            log(f"  [FAIL] Expected {jmeter_bin} but not found")
            log(f"  Contents of {install_dir}:")
            for item in os.listdir(install_dir):
                log(f"    {item}")
            close_log()
            sys.exit(1)

    log(f"  [OK] JMeter: {args.jmeter_bin}")

    # Check JMX
    if not os.path.exists(JMX_SOURCE):
        log(f"  [FAIL] JMX not found: {JMX_SOURCE}")
        close_log()
        sys.exit(1)
    log(f"  [OK] JMX: {JMX_SOURCE}")

    # Check emulator
    if not check_health(base_url):
        close_log()
        sys.exit(1)

    # Allocate pool
    if not allocate_pool(base_url):
        close_log()
        sys.exit(1)

    # Show emulator config
    emu_config = get_emulator_config(base_url)
    if emu_config:
        log(f"  Emulator config: {json.dumps(emu_config, indent=2)[:800]}")

    # Setup work dir
    work_dir = tempfile.mkdtemp(prefix="cal_live_")
    log(f"  [OK] Work dir: {work_dir}")

    try:
        # Copy JMX
        jmx_dest = os.path.join(work_dir, "test.jmx")
        shutil.copy2(JMX_SOURCE, jmx_dest)
        log(f"  [OK] Copied JMX -> {jmx_dest}")

        # Verify JMX content
        with open(jmx_dest) as f:
            jmx_content = f.read()
        if "SwitchController" in jmx_content:
            log(f"  [OK] JMX has SwitchController")
        else:
            log(f"  [WARN] JMX missing SwitchController!")
        if "think_ms" in jmx_content:
            log(f"  [OK] JMX has think_ms property")
        else:
            log(f"  [WARN] JMX missing think_ms property (using hardcoded 500ms)")
        if "ignoreFirstLine\">true" in jmx_content:
            log(f"  [OK] JMX ignoreFirstLine=true")
        elif "ignoreFirstLine\">false" in jmx_content:
            log(f"  [WARN] JMX ignoreFirstLine=false -- header row will be read as data!")

        # Generate CSV
        csv_dest = os.path.join(work_dir, "calibration_ops.csv")
        generate_calibration_csv(csv_dest, count=500000)

        # Run test
        if args.scaling:
            results = run_scaling_test(args, work_dir)
        else:
            run_single_test(args, args.threads, work_dir)

    except Exception as e:
        log(f"\n  [ERROR] Unhandled exception: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        log(f"\n  Cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    log(f"\n{'='*70}")
    log(f"  DONE at {datetime.now().isoformat()}")
    log(f"  Full log saved to: {log_path}")
    log(f"{'='*70}")

    close_log()


if __name__ == "__main__":
    main()
