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
        resp = http_get(f"{base_url}/health")
        log(f"  [OK] Emulator healthy: {resp.get('status')}, uptime={resp.get('uptime_sec', '?')}s")
        return True
    except Exception as e:
        log(f"  [FAIL] Emulator not reachable at {base_url}: {e}")
        return False


def configure_emulator(base_url, target_ip):
    """Configure emulator: output_folders, partner, stats. Must be called before JMeter."""
    try:
        resp = http_post(f"{base_url}/api/v1/config", {
            "output_folders": ["/data/emulator/output"],
            "partner": {"fqdn": target_ip, "port": 8080},
            "stats": {"default_interval_sec": 1.0},
        })
        log(f"  [OK] Emulator configured: output_folders=[/data/emulator/output], partner={target_ip}")
        return True
    except Exception as e:
        log(f"  [FAIL] Emulator config failed: {e}")
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


def read_stats(base_url, count=10, verbose=False):
    """Read recent CPU/MEM samples from emulator."""
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count={count}")
        samples = stats.get("samples", [])
        if verbose:
            log(f"    stats: requested={count} returned={stats.get('returned_samples')} "
                f"total_in_buffer={stats.get('total_samples')} collecting={stats.get('is_collecting')}")
        return samples
    except Exception as e:
        if verbose:
            log(f"    stats read failed: {e}")
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

def run_single_test(args, threads, work_dir, quick=False):
    """Run a single JMeter test matching real calibration timings.

    Phases (matching calibration.py _run_observation + _run_stability_check):
      1. RAMP:      30s  — JMeter threads ramp up
      2. SETTLE:    30s  — JVM warmup, let CPU stabilize
      3. OBSERVE:  180s  — collect 120 samples (same as observation_reading_count)
      4. STABILITY: 900s — collect 900 samples (same as stability check)

    If quick=True (used in scaling mode): skip stability, shorter observe.
    """
    base_url = f"http://{args.target_ip}:{args.port}"
    jmx_path = os.path.join(work_dir, "test.jmx")
    csv_path = os.path.join(work_dir, "calibration_ops.csv")
    jtl_path = os.path.join(work_dir, f"test_T{threads}.jtl")
    jmeter_log_path = os.path.join(work_dir, f"test_T{threads}.log")

    # Match real calibration timings
    ramp_sec = 30
    settle_sec = 30                             # bracket_settle_sec
    observe_sec = 60 if quick else 180          # observation_duration_sec
    observe_count = 40 if quick else 120        # observation_reading_count
    stability_sec = 0 if quick else 900         # stability duration
    stability_count = 0 if quick else 900       # stability samples
    total_sec = ramp_sec + settle_sec + observe_sec + stability_sec + 15  # +buffer

    log(f"\n{'='*70}")
    log(f"  JMETER LIVE TEST: threads={threads}")
    log(f"  Target: {base_url}")
    log(f"  Params: cpu_ms={args.cpu_ms} intensity={args.intensity} "
        f"touch_mb={args.touch_mb} think_ms={args.think_ms}")
    log(f"  Phases: ramp={ramp_sec}s settle={settle_sec}s observe={observe_sec}s "
        f"stability={stability_sec}s total={total_sec}s")
    log(f"{'='*70}")

    # Pre-test state
    log(f"\n  --- Pre-test ---")
    emu_config = get_emulator_config(base_url)
    if emu_config:
        configured = emu_config.get("is_configured", False)
        folders = emu_config.get("output_folders", [])
        partner = emu_config.get("partner", {}).get("fqdn")
        log(f"  Emulator: configured={configured}, folders={len(folders)}, partner={partner}")

    baseline = read_stats(base_url, count=5)
    if baseline:
        cpu_bl = [s.get("cpu_percent", 0) for s in baseline]
        log(f"  Baseline CPU: {[round(v,1) for v in cpu_bl]}")

    # Start stats collection
    test_id = start_stats(base_url, f"live_T{threads}", threads)
    if not test_id:
        return None

    # Start JMeter
    proc = start_jmeter(
        args.jmeter_bin, jmx_path, csv_path, jtl_path, jmeter_log_path,
        threads, ramp_sec, total_sec, args.target_ip, args.port,
        args.cpu_ms, args.intensity, args.touch_mb, args.think_ms,
    )
    time.sleep(3)
    if not check_jmeter_alive(proc):
        log(f"  [FAIL] JMeter died within 3s!")
        _, stderr = proc.communicate()
        if stderr:
            log(f"  stderr: {stderr.decode()[:500]}")
        stop_stats(base_url, test_id)
        return None
    log(f"  [OK] JMeter PID {proc.pid}")

    # === PHASE 1: RAMP + SETTLE (monitor every 10s) ===
    log(f"\n  --- Phase 1: Ramp ({ramp_sec}s) + Settle ({settle_sec}s) ---")
    log(f"  {'time':>6}  {'phase':>8}  {'cpu%':>7}  {'mem%':>7}  {'n':>4}  cpu_values")
    log(f"  {'---':>6}  {'---':>8}  {'---':>7}  {'---':>7}  {'--':>4}  ---")

    elapsed = 0
    poll = 10
    try:
        while elapsed < ramp_sec + settle_sec:
            time.sleep(poll)
            elapsed += poll
            if not check_jmeter_alive(proc):
                log(f"  [FAIL] JMeter died at {elapsed}s!")
                break
            samples = read_stats(base_url, count=poll)
            if samples:
                cpus = [s.get("cpu_percent", 0) for s in samples]
                mems = [s.get("mem_percent", 0) for s in samples]
                phase = "ramp" if elapsed <= ramp_sec else "settle"
                vals = ", ".join(f"{v:.1f}" for v in cpus)
                log(f"  {elapsed:>5}s  {phase:>8}  {sum(cpus)/len(cpus):>6.1f}%  "
                    f"{sum(mems)/len(mems):>6.1f}%  {len(cpus):>4}  [{vals}]")

        # === PHASE 2: OBSERVE (180s, read 120 samples at end) ===
        log(f"\n  --- Phase 2: Observe ({observe_sec}s, reading last {observe_count} samples) ---")
        log(f"  {'time':>6}  {'cpu%':>7}  {'n':>4}  cpu_values")
        log(f"  {'---':>6}  {'---':>7}  {'--':>4}  ---")

        obs_elapsed = 0
        while obs_elapsed < observe_sec:
            time.sleep(poll)
            obs_elapsed += poll
            elapsed += poll
            if not check_jmeter_alive(proc):
                log(f"  [FAIL] JMeter died at {elapsed}s!")
                break
            samples = read_stats(base_url, count=poll)
            if samples:
                cpus = [s.get("cpu_percent", 0) for s in samples]
                vals = ", ".join(f"{v:.1f}" for v in cpus)
                log(f"  {elapsed:>5}s  {sum(cpus)/len(cpus):>6.1f}%  {len(cpus):>4}  [{vals}]")

        # Bulk read — exactly like calibration does
        log(f"\n  --- Observation bulk read ({observe_count} samples) ---")
        obs_samples = read_stats(base_url, count=observe_count, verbose=True)
        obs_cpu = [s.get("cpu_percent", 0) for s in obs_samples] if obs_samples else []
        obs_mem = [s.get("mem_percent", 0) for s in obs_samples] if obs_samples else []

        if obs_cpu:
            import math
            n = len(obs_cpu)
            avg = sum(obs_cpu) / n
            sorted_cpu = sorted(obs_cpu)
            p25 = sorted_cpu[n * 25 // 100]
            p50 = sorted_cpu[n // 2]
            p75 = sorted_cpu[n * 75 // 100]
            p90 = sorted_cpu[n * 90 // 100]
            p95 = sorted_cpu[n * 95 // 100]
            stddev = math.sqrt(sum((v - avg) ** 2 for v in obs_cpu) / n) if n > 1 else 0
            cv = stddev / avg if avg > 0 else 0

            in_range = sum(1 for v in obs_cpu if args.target_min <= v <= args.target_max)
            below = sum(1 for v in obs_cpu if v < args.target_min)
            above = sum(1 for v in obs_cpu if v > args.target_max)

            log(f"  Samples: {n}")
            log(f"  CPU: avg={avg:.1f}% p25={p25:.1f}% p50={p50:.1f}% p75={p75:.1f}% "
                f"p90={p90:.1f}% p95={p95:.1f}%")
            log(f"  min={min(obs_cpu):.1f}% max={max(obs_cpu):.1f}% stddev={stddev:.1f} CV={cv:.2f}")
            log(f"  MEM: avg={sum(obs_mem)/len(obs_mem):.1f}%")
            log(f"  In range ({args.target_min}-{args.target_max}%): "
                f"{in_range}/{n} ({in_range*100//n}%)  below={below}  above={above}")
        else:
            log(f"  [FAIL] No observation samples!")
            avg = None

        # === PHASE 3: STABILITY (900s, read 900 samples at end) ===
        stab_cpu = []
        if stability_sec > 0 and check_jmeter_alive(proc):
            log(f"\n  --- Phase 3: Stability ({stability_sec}s, reading {stability_count} samples) ---")
            log(f"  {'time':>6}  {'cpu%':>7}  {'n':>4}  cpu_values")
            log(f"  {'---':>6}  {'---':>7}  {'--':>4}  ---")

            stab_elapsed = 0
            stab_poll = 30  # less frequent for stability
            while stab_elapsed < stability_sec:
                time.sleep(stab_poll)
                stab_elapsed += stab_poll
                elapsed += stab_poll
                if not check_jmeter_alive(proc):
                    log(f"  [FAIL] JMeter died at {elapsed}s!")
                    break
                samples = read_stats(base_url, count=stab_poll)
                if samples:
                    cpus = [s.get("cpu_percent", 0) for s in samples]
                    vals = ", ".join(f"{v:.1f}" for v in cpus)
                    log(f"  {elapsed:>5}s  {sum(cpus)/len(cpus):>6.1f}%  {len(cpus):>4}  [{vals}]")

            # Stability bulk read
            log(f"\n  --- Stability bulk read ({stability_count} samples) ---")
            stab_samples = read_stats(base_url, count=stability_count, verbose=True)
            stab_cpu = [s.get("cpu_percent", 0) for s in stab_samples] if stab_samples else []

            if stab_cpu:
                n = len(stab_cpu)
                avg_s = sum(stab_cpu) / n
                sorted_s = sorted(stab_cpu)
                p25_s = sorted_s[n * 25 // 100]
                p50_s = sorted_s[n // 2]
                p75_s = sorted_s[n * 75 // 100]
                p90_s = sorted_s[n * 90 // 100]
                stddev_s = math.sqrt(sum((v - avg_s) ** 2 for v in stab_cpu) / n) if n > 1 else 0

                in_range_s = sum(1 for v in stab_cpu if args.target_min <= v <= args.target_max)
                below_s = sum(1 for v in stab_cpu if v < args.target_min)
                above_s = sum(1 for v in stab_cpu if v > args.target_max)

                log(f"  Samples: {n}")
                log(f"  CPU: avg={avg_s:.1f}% p25={p25_s:.1f}% p50={p50_s:.1f}% p75={p75_s:.1f}% p90={p90_s:.1f}%")
                log(f"  min={min(stab_cpu):.1f}% max={max(stab_cpu):.1f}% stddev={stddev_s:.1f}")
                log(f"  In range ({args.target_min}-{args.target_max}%): "
                    f"{in_range_s}/{n} ({in_range_s*100//n}%)  below={below_s}  above={above_s}")

                # Stability pass/fail (same criteria as calibration)
                pct_in_range = in_range_s * 100 / n
                passed = pct_in_range >= 55  # calibration_stability_ratio = 0.5 but v2 uses 55%
                log(f"  Stability: {'PASS' if passed else 'FAIL'} ({pct_in_range:.1f}% in range, need 55%)")

    except KeyboardInterrupt:
        log("\n  [INFO] Interrupted by user")

    # Stop JMeter
    log(f"\n  Stopping JMeter...")
    stop_jmeter(proc)
    time.sleep(2)

    post = read_stats(base_url, count=5)
    if post:
        log(f"  Post-stop CPU: {[round(s.get('cpu_percent',0), 1) for s in post]}")
    stop_stats(base_url, test_id)

    # --- JTL analysis ---
    log(f"\n  --- JTL analysis ---")
    if os.path.exists(jtl_path):
        with open(jtl_path) as f:
            jtl_lines = sum(1 for _ in f) - 1
        log(f"  Total requests: {jtl_lines}")

        if jtl_lines > 0:
            from collections import Counter
            with open(jtl_path) as f:
                reader = csv.DictReader(f)
                labels = Counter()
                success_count = 0
                error_count = 0
                response_codes = Counter()
                elapsed_times = []
                first_ts = last_ts = None

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
            log(f"  Success: {success_count}, Errors: {error_count} ({error_count*100//max(1,total)}%)")

            if first_ts and last_ts and last_ts > first_ts:
                dur = (last_ts - first_ts) / 1000
                log(f"  Duration: {dur:.1f}s, Throughput: {total/dur:.1f} req/s")

            log(f"  Response codes: {dict(response_codes.most_common())}")

            if elapsed_times:
                elapsed_times.sort()
                n = len(elapsed_times)
                log(f"  Response times: avg={sum(elapsed_times)/n:.0f}ms "
                    f"p50={elapsed_times[n//2]}ms p95={elapsed_times[int(n*0.95)]}ms "
                    f"min={elapsed_times[0]}ms max={elapsed_times[-1]}ms")

            log(f"  Request distribution:")
            for label, count in labels.most_common():
                log(f"    {label:20s}  {count:>6}  ({count*100//max(1,total)}%)")

            if error_count > 0:
                log(f"  First 5 errors:")
                with open(jtl_path) as f:
                    reader = csv.DictReader(f)
                    shown = 0
                    for row in reader:
                        if row.get('success', 'true').lower() != 'true' and shown < 5:
                            log(f"    {row.get('label')} code={row.get('responseCode')} "
                                f"msg={row.get('responseMessage', '')[:80]}")
                            shown += 1
    else:
        log(f"  [WARN] No JTL file")

    # --- JMeter log ---
    log(f"\n  --- JMeter log ---")
    if os.path.exists(jmeter_log_path):
        with open(jmeter_log_path) as f:
            lines = f.readlines()
        errors = [l.strip() for l in lines if 'ERROR' in l or 'FATAL' in l]
        warns = [l.strip() for l in lines if 'WARN' in l]
        log(f"  Lines: {len(lines)}, Errors: {len(errors)}, Warnings: {len(warns)}")
        for l in errors[:5]:
            log(f"    ERR: {l[:150]}")
        for l in warns[:3]:
            log(f"    WARN: {l[:150]}")
        log(f"  Last 5 lines:")
        for l in lines[-5:]:
            log(f"    {l.rstrip()}")

    # === FINAL ANALYSIS ===
    log(f"\n{'='*70}")
    log(f"  ANALYSIS: threads={threads}")
    log(f"{'='*70}")

    if obs_cpu:
        log(f"\n  Observation ({len(obs_cpu)} samples):")
        log(f"    avg={sum(obs_cpu)/len(obs_cpu):.1f}%  p50={sorted(obs_cpu)[len(obs_cpu)//2]:.1f}%")
        log(f"    range: {min(obs_cpu):.1f}% - {max(obs_cpu):.1f}%")

        # What calibration would decide
        obs_avg = sum(obs_cpu) / len(obs_cpu)
        if obs_avg < args.target_min:
            log(f"    Calibration verdict: TOO COLD ({obs_avg:.1f}% < {args.target_min}%) -> need more threads")
        elif obs_avg > args.target_max:
            log(f"    Calibration verdict: TOO HOT ({obs_avg:.1f}% > {args.target_max}%) -> need fewer threads")
        else:
            log(f"    Calibration verdict: IN RANGE ({args.target_min}% <= {obs_avg:.1f}% <= {args.target_max}%)")

    if stab_cpu:
        stab_avg = sum(stab_cpu) / len(stab_cpu)
        in_r = sum(1 for v in stab_cpu if args.target_min <= v <= args.target_max)
        pct = in_r * 100 / len(stab_cpu)
        log(f"\n  Stability ({len(stab_cpu)} samples):")
        log(f"    avg={stab_avg:.1f}%  in-range={pct:.1f}%  {'PASS' if pct >= 55 else 'FAIL'}")

    if jtl_lines > 0:
        err_pct = error_count * 100 // max(1, total)
        if err_pct > 5:
            log(f"\n  [WARN] High error rate: {err_pct}% — check emulator config (output_folders, partner)")

    log(f"\n  For calibration profiles:")
    if obs_cpu:
        obs_avg = sum(obs_cpu) / len(obs_cpu)
        log(f"    T={threads} -> {obs_avg:.1f}% CPU")
        if obs_avg > 0:
            for name, lo, hi in [("low", 20, 40), ("medium", 40, 60), ("high", 60, 80)]:
                mid = (lo + hi) / 2
                est_threads = int(threads * mid / obs_avg)
                log(f"    {name:>8} ({lo}-{hi}%): estimated ~{est_threads} threads")

    return sum(obs_cpu) / len(obs_cpu) if obs_cpu else None


# ---------------------------------------------------------------------------
# Scaling test
# ---------------------------------------------------------------------------

def run_scaling_test(args, work_dir):
    thread_counts = [1, 2, 4, 8, 16, 24, 32, 50]
    results = []

    log(f"\n{'='*70}")
    log(f"  SCALING TEST (quick mode: 60s observe per thread count)")
    log(f"  cpu_ms={args.cpu_ms}, touch_mb={args.touch_mb}, think_ms={args.think_ms}")
    log(f"  Thread counts: {thread_counts}")
    log(f"{'='*70}")

    for tc in thread_counts:
        avg_cpu = run_single_test(args, tc, work_dir, quick=True)
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
            if args.target_min <= cpu <= args.target_max:
                profile = f"<-- IN RANGE ({args.target_min}-{args.target_max}%)"
            elif cpu < 20:
                profile = "<-- TOO COLD"
            elif 20 <= cpu <= 40:
                profile = "<-- LOW (20-40%)"
            elif 40 < cpu <= 60:
                profile = "<-- MEDIUM (40-60%)"
            elif 60 < cpu <= 80:
                profile = "<-- HIGH (60-80%)"
            elif cpu > 80:
                profile = "<-- TOO HOT"
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
    parser.add_argument("--cpu-ms", type=int, default=200, help="CPU burn ms per /work request")
    parser.add_argument("--intensity", type=float, default=0.8, help="CPU burn intensity")
    parser.add_argument("--touch-mb", type=float, default=1.0, help="Memory touch MB per request")
    parser.add_argument("--think-ms", type=int, default=500, help="Think time between requests (ms)")
    parser.add_argument("--target-min", type=float, default=20, help="Target CPU min %% (for analysis)")
    parser.add_argument("--target-max", type=float, default=40, help="Target CPU max %% (for analysis)")
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

    # Check JMeter binary
    if not os.path.exists(args.jmeter_bin):
        log(f"  [FAIL] JMeter not found at {args.jmeter_bin}")
        log(f"         Run 'python setup_jmeter.py' first to install JMeter")
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

    # Configure emulator (output_folders, partner — needed for file and networkclient ops)
    if not configure_emulator(base_url, args.target_ip):
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
