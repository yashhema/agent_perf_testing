#!/usr/bin/env python3
"""Standalone workload test — measures actual CPU impact on emulator target.

Connects to a target's Java emulator, fires controlled workloads,
and measures real CPU% to determine correct cpu_ms / thread_count settings.

Tests:
  1. Direct /work endpoint: verify burn times at various cpu_ms values
  2. Concurrent load: fire N threads with think time, read CPU% from stats
  3. Scaling curve: CPU% at thread counts 1,2,4,8,16,24,32
  4. Recommendation for target CPU range

Usage:
    python test_workload.py --target-ip 10.0.0.5
    python test_workload.py --target-ip 10.0.0.5 --cpu-ms 200 --target-min 20 --target-max 40
    python test_workload.py --target-ip 10.0.0.5 --skip-scaling
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor


def ok(msg):
    print(f"  [PASS] {msg}")

def fail(msg):
    print(f"  [FAIL] {msg}")

def info(msg):
    print(f"  [INFO] {msg}")


def http_post(url, data, timeout=30):
    """POST JSON, return parsed response."""
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, timeout=10):
    """GET JSON, return parsed response."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def start_stats(base_url, tag, threads=1):
    """Start emulator stats collection, return test_id."""
    try:
        resp = http_post(f"{base_url}/api/v1/tests/start", {
            "test_run_id": tag,
            "scenario_id": tag,
            "mode": "calibration",
            "collect_interval_sec": 1.0,
            "thread_count": threads,
        })
        test_id = resp.get("test_id", tag)
        return test_id
    except Exception as e:
        fail(f"Failed to start stats: {e}")
        return None


def stop_stats(base_url, test_id):
    """Stop emulator stats collection."""
    try:
        http_post(f"{base_url}/api/v1/tests/{test_id}/stop", {})
    except Exception:
        pass


def read_cpu_stats(base_url, count=10):
    """Read recent CPU% samples from emulator."""
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count={count}")
        samples = stats.get("samples", [])
        if not samples:
            return []
        return [s.get("cpu_percent", 0) for s in samples]
    except Exception as e:
        fail(f"Failed to read stats: {e}")
        return []


def fire_load(base_url, cpu_ms, intensity, threads, duration_sec, think_ms=500, touch_mb=0.2):
    """Fire concurrent /work requests for duration_sec. Returns (req_count, error_count)."""
    stop_flag = [False]
    req_count = [0]
    err_count = [0]

    def worker():
        while not stop_flag[0]:
            try:
                http_post(f"{base_url}/api/v1/operations/work", {
                    "cpu_ms": cpu_ms,
                    "intensity": intensity,
                    "touch_mb": touch_mb,
                    "touch_pattern": "random",
                }, timeout=10)
                req_count[0] += 1
            except Exception:
                err_count[0] += 1
            if think_ms > 0:
                time.sleep(think_ms / 1000.0)

    pool = ThreadPoolExecutor(max_workers=threads)
    futures = [pool.submit(worker) for _ in range(threads)]
    time.sleep(duration_sec)
    stop_flag[0] = True
    pool.shutdown(wait=True, cancel_futures=True)
    return req_count[0], err_count[0]


# ======================================================================
# TEST 0: Health
# ======================================================================
def test_health(base_url):
    print("\n" + "=" * 60)
    print("  TEST 0: Emulator Health")
    print("=" * 60)
    try:
        resp = http_get(f"{base_url}/health")
        ok(f"Healthy: {resp.get('status')}, version={resp.get('version')}, uptime={resp.get('uptime_sec')}s")
        return True
    except Exception as e:
        fail(f"Emulator unreachable: {e}")
        return False


# ======================================================================
# TEST 1: Direct /work endpoint — measure actual burn durations
# ======================================================================
def test_work_direct(base_url):
    print("\n" + "=" * 60)
    print("  TEST 1: Direct /work endpoint (single request)")
    print("=" * 60)

    # Check if pool is allocated
    try:
        resp = http_post(f"{base_url}/api/v1/operations/work", {
            "cpu_ms": 10, "intensity": 0.5, "touch_mb": 0.1,
        })
    except urllib.error.HTTPError as e:
        if e.code == 400:
            fail("Memory pool not allocated — call POST /api/v1/config/pool first")
            info("The emulator needs to be configured before /work operations")
            return None
        raise

    test_cases = [
        (10, 0.8),
        (50, 0.8),
        (100, 0.8),
        (200, 0.8),
        (500, 0.8),
        (200, 1.0),
        (200, 0.5),
    ]

    print(f"\n  {'cpu_ms':>8} {'intensity':>10} {'duration_ms':>12} {'status':>10}")
    print(f"  {'-'*8} {'-'*10} {'-'*12} {'-'*10}")

    results = []
    for cpu_ms, intensity in test_cases:
        try:
            resp = http_post(f"{base_url}/api/v1/operations/work", {
                "cpu_ms": cpu_ms,
                "intensity": intensity,
                "touch_mb": 1.0,
                "touch_pattern": "random",
            })
            duration = resp.get("duration_ms", "?")
            status = resp.get("status", "?")
            print(f"  {cpu_ms:>8} {intensity:>10.1f} {duration:>12} {status:>10}")
            results.append((cpu_ms, intensity, duration, status))
        except Exception as e:
            print(f"  {cpu_ms:>8} {intensity:>10.1f} {'ERROR':>12} {str(e)[:20]:>10}")
            results.append((cpu_ms, intensity, None, "error"))

    # Verify burn is actually working
    if results:
        r10 = next((d for ms, _, d, s in results if ms == 10 and d is not None), None)
        r200 = next((d for ms, _, d, s in results if ms == 200 and d is not None and _ == 0.8), None)
        if r10 is not None and r200 is not None:
            ratio = r200 / r10 if r10 > 0 else 0
            if ratio > 5:
                ok(f"CPU burn scales correctly: 200ms/10ms ratio = {ratio:.1f}x")
            else:
                fail(f"CPU burn NOT scaling: 200ms/10ms ratio = {ratio:.1f}x (expected ~20x)")

    return results


# ======================================================================
# TEST 2: Concurrent load — measure CPU% from emulator stats
# ======================================================================
def test_concurrent(base_url, cpu_ms, intensity, threads=16, duration_sec=20, touch_mb=0.2):
    print("\n" + "=" * 60)
    print(f"  TEST 2: Concurrent load ({threads} threads, cpu_ms={cpu_ms}, {duration_sec}s)")
    print("=" * 60)

    test_id = start_stats(base_url, "workload_test", threads)
    if not test_id:
        return None

    info(f"Firing {threads} concurrent workers for {duration_sec}s (500ms think time)...")
    req_count, err_count = fire_load(base_url, cpu_ms, intensity, threads, duration_sec, touch_mb=touch_mb)

    info(f"Completed: {req_count} requests, {err_count} errors")
    info(f"Throughput: {req_count / duration_sec:.1f} req/sec")

    time.sleep(2)
    cpu_values = read_cpu_stats(base_url, count=15)
    stop_stats(base_url, test_id)

    if cpu_values:
        # Skip first 3 samples (ramp-up)
        stable = cpu_values[3:] if len(cpu_values) > 5 else cpu_values
        avg_cpu = sum(stable) / len(stable)
        min_cpu = min(stable)
        max_cpu = max(stable)
        print(f"\n  CPU Stats ({len(stable)} stable samples, skipped first 3):")
        print(f"    avg: {avg_cpu:.1f}%  min: {min_cpu:.1f}%  max: {max_cpu:.1f}%")
        print(f"    all samples: {[round(v, 1) for v in cpu_values]}")
        return avg_cpu
    else:
        fail("No CPU samples")
        return None


# ======================================================================
# TEST 3: Scaling curve — CPU% at different thread counts
# ======================================================================
def test_scaling(base_url, cpu_ms, intensity, touch_mb=0.2):
    print("\n" + "=" * 60)
    print(f"  TEST 3: Thread scaling curve (cpu_ms={cpu_ms}, intensity={intensity})")
    print("=" * 60)

    thread_counts = [1, 2, 4, 8, 16, 24, 32]
    results = []
    test_dur = 15

    print(f"\n  {'threads':>8} {'cpu_avg%':>10} {'req/sec':>10} {'cpu/thread':>12}")
    print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*12}")

    for tc in thread_counts:
        test_id = start_stats(base_url, f"scale_{tc}", tc)

        # Short warmup
        time.sleep(2)

        req_count, _ = fire_load(base_url, cpu_ms, intensity, tc, test_dur, touch_mb=touch_mb)

        time.sleep(2)
        cpu_values = read_cpu_stats(base_url, count=10)
        stop_stats(base_url, test_id)

        if cpu_values:
            stable = cpu_values[2:] if len(cpu_values) > 4 else cpu_values
            avg_cpu = sum(stable) / len(stable)
        else:
            avg_cpu = 0

        rps = req_count / test_dur
        cpu_per_thread = avg_cpu / tc if tc > 0 else 0
        print(f"  {tc:>8} {avg_cpu:>10.1f} {rps:>10.1f} {cpu_per_thread:>12.2f}")
        results.append((tc, avg_cpu, rps, cpu_per_thread))

        # Cooldown between tests
        time.sleep(3)

    return results


# ======================================================================
# RECOMMENDATION
# ======================================================================
def recommend(scaling_results, target_min, target_max, cpu_ms):
    print("\n" + "=" * 60)
    print(f"  RECOMMENDATION (target CPU: {target_min}-{target_max}%, cpu_ms={cpu_ms})")
    print("=" * 60)

    if not scaling_results:
        fail("No scaling data")
        return

    for tc, avg_cpu, rps, cpt in scaling_results:
        marker = ""
        if target_min <= avg_cpu <= target_max:
            marker = " <-- IN RANGE"
        elif avg_cpu > target_max:
            marker = " <-- TOO HOT"
        print(f"  {tc:>3} threads -> {avg_cpu:5.1f}% CPU ({rps:.0f} req/s){marker}")

    in_range = [(tc, cpu) for tc, cpu, _, _ in scaling_results if target_min <= cpu <= target_max]
    below = [(tc, cpu) for tc, cpu, _, _ in scaling_results if cpu < target_min]
    above = [(tc, cpu) for tc, cpu, _, _ in scaling_results if cpu > target_max]

    print()
    if in_range:
        ok(f"Thread counts in range: {[tc for tc, _ in in_range]}")
        ok(f"Calibration should work with cpu_ms={cpu_ms}")
    elif below and not above:
        max_tc, max_cpu = max(scaling_results, key=lambda x: x[1])[:2]
        factor = target_min / max_cpu if max_cpu > 0 else 999
        fail(f"Even {max_tc} threads only reaches {max_cpu:.1f}% — below target {target_min}%")
        info(f"Need ~{factor:.1f}x more CPU load")
        suggested_ms = int(cpu_ms * factor * 1.2)
        info(f"Try: cpu_ms={suggested_ms} or reduce think time or increase max_thread_count")
    elif above and not below:
        info("Even 1 thread exceeds target — reduce cpu_ms")
        min_tc, min_cpu = min(scaling_results, key=lambda x: x[1])[:2]
        suggested_ms = int(cpu_ms * target_max / min_cpu * 0.8)
        info(f"Try: cpu_ms={suggested_ms}")


def main():
    parser = argparse.ArgumentParser(description="Workload CPU test")
    parser.add_argument("--target-ip", required=True, help="Target emulator IP")
    parser.add_argument("--port", type=int, default=8080, help="Emulator port")
    parser.add_argument("--cpu-ms", type=int, default=200, help="cpu_ms for load tests")
    parser.add_argument("--intensity", type=float, default=0.8, help="CPU burn intensity")
    parser.add_argument("--touch-mb", type=float, default=0.2, help="Memory touch size in MB per request")
    parser.add_argument("--target-min", type=float, default=20, help="Target CPU min %%")
    parser.add_argument("--target-max", type=float, default=40, help="Target CPU max %%")
    parser.add_argument("--skip-scaling", action="store_true", help="Skip scaling test")
    args = parser.parse_args()

    base_url = f"http://{args.target_ip}:{args.port}"

    print("=" * 60)
    print(f"  WORKLOAD TEST")
    print(f"  Target: {base_url}")
    print(f"  cpu_ms={args.cpu_ms}  intensity={args.intensity}  touch_mb={args.touch_mb}")
    print(f"  Target CPU range: {args.target_min}-{args.target_max}%")
    print("=" * 60)

    if not test_health(base_url):
        sys.exit(1)

    work_results = test_work_direct(base_url)
    if work_results is None:
        sys.exit(1)

    avg_cpu = test_concurrent(base_url, args.cpu_ms, args.intensity, touch_mb=args.touch_mb)

    if not args.skip_scaling:
        scaling = test_scaling(base_url, args.cpu_ms, args.intensity, touch_mb=args.touch_mb)
        recommend(scaling, args.target_min, args.target_max, args.cpu_ms)
    else:
        info("Scaling test skipped (--skip-scaling)")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
