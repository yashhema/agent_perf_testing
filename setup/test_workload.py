#!/usr/bin/env python3
"""Standalone workload test — measures actual CPU impact of JMeter + emulator.

Connects to a target emulator and loadgen, fires controlled workloads,
and measures real CPU% to determine correct cpu_ms / thread_count settings.

Tests:
  1. Direct emulator test: POST /work with various cpu_ms, measure wall_ms + cpu_ms_actual
  2. Direct CPU% test: fire N concurrent /work requests, read CPU% from emulator stats
  3. JMeter CSV test: fire JMeter with known CSV for 30s, compare emulator CPU% vs expected
  4. Summary: recommended cpu_ms for target CPU range

Usage:
    python test_workload.py --target-ip 10.0.0.5
    python test_workload.py --target-ip 10.0.0.5 --loadgen-ip 10.0.0.10 --test-name "my test"
    python test_workload.py --target-ip 10.0.0.5 --emulator-port 8080
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


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


def test_emulator_health(base_url):
    """Check emulator is alive."""
    print("\n" + "=" * 60)
    print("  TEST 0: Emulator Health")
    print("=" * 60)
    try:
        resp = http_get(f"{base_url}/api/v1/health")
        ok(f"Emulator healthy: {resp.get('status', 'unknown')}")
        return True
    except Exception as e:
        fail(f"Emulator unreachable: {e}")
        return False


def test_work_endpoint(base_url):
    """Test 1: Direct /work endpoint — measure actual burn times for various cpu_ms values."""
    print("\n" + "=" * 60)
    print("  TEST 1: Direct /work endpoint (single request)")
    print("=" * 60)
    print(f"  {'cpu_ms':>8} {'intensity':>10} {'wall_ms':>10} {'cpu_actual':>12} {'status':>10}")
    print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*12} {'-'*10}")

    test_cases = [
        (10, 0.8),
        (50, 0.8),
        (100, 0.8),
        (200, 0.8),
        (500, 0.8),
        (200, 1.0),
        (200, 0.5),
    ]

    results = []
    for cpu_ms, intensity in test_cases:
        try:
            resp = http_post(f"{base_url}/api/v1/operations/work", {
                "cpu_ms": cpu_ms,
                "intensity": intensity,
                "touch_mb": 1.0,
                "touch_pattern": "random",
            })
            wall = resp.get("wall_ms", "?")
            actual = resp.get("cpu_ms_actual", "?")
            status = resp.get("status", "?")
            print(f"  {cpu_ms:>8} {intensity:>10.1f} {wall:>10} {actual:>12} {status:>10}")
            results.append((cpu_ms, intensity, wall, actual, status))
        except Exception as e:
            print(f"  {cpu_ms:>8} {intensity:>10.1f} {'ERROR':>10} {'':>12} {str(e)[:30]:>10}")
            results.append((cpu_ms, intensity, None, None, "error"))

    return results


def test_concurrent_cpu(base_url, cpu_ms=200, intensity=0.8, threads=16, duration_sec=15):
    """Test 2: Fire concurrent /work requests and measure CPU% from emulator stats."""
    print("\n" + "=" * 60)
    print(f"  TEST 2: Concurrent CPU load ({threads} threads, cpu_ms={cpu_ms}, {duration_sec}s)")
    print("=" * 60)

    # Start stats collection
    try:
        http_post(f"{base_url}/api/v1/tests/start", {
            "test_run_id": "workload_test",
            "scenario_id": "workload_test",
            "mode": "calibration",
            "collect_interval_sec": 1.0,
            "thread_count": threads,
        })
        info("Stats collection started")
    except Exception as e:
        fail(f"Failed to start stats: {e}")
        return None

    # Fire concurrent requests for duration_sec
    stop_flag = False
    request_count = [0]
    error_count = [0]

    def worker():
        while not stop_flag:
            try:
                http_post(f"{base_url}/api/v1/operations/work", {
                    "cpu_ms": cpu_ms,
                    "intensity": intensity,
                    "touch_mb": 1.0,
                    "touch_pattern": "random",
                }, timeout=10)
                request_count[0] += 1
            except Exception:
                error_count[0] += 1
            # Think time to simulate JMeter behavior
            time.sleep(0.5)

    info(f"Firing {threads} concurrent workers for {duration_sec}s...")
    pool = ThreadPoolExecutor(max_workers=threads)
    futures = [pool.submit(worker) for _ in range(threads)]

    time.sleep(duration_sec)
    stop_flag = True
    pool.shutdown(wait=True, cancel_futures=True)

    info(f"Completed: {request_count[0]} requests, {error_count[0]} errors")
    info(f"Throughput: {request_count[0] / duration_sec:.1f} req/sec")

    # Read CPU stats
    time.sleep(2)  # let last samples collect
    try:
        stats = http_get(f"{base_url}/api/v1/stats/recent?count=10")
        samples = stats.get("samples", [])
        if samples:
            cpu_values = [s.get("cpu_percent", 0) for s in samples]
            avg_cpu = sum(cpu_values) / len(cpu_values)
            min_cpu = min(cpu_values)
            max_cpu = max(cpu_values)
            print(f"\n  CPU Stats ({len(cpu_values)} samples):")
            print(f"    avg: {avg_cpu:.1f}%  min: {min_cpu:.1f}%  max: {max_cpu:.1f}%")
            for i, v in enumerate(cpu_values):
                print(f"    sample {i+1}: {v:.1f}%")
        else:
            fail("No CPU samples returned")
            avg_cpu = None
    except Exception as e:
        fail(f"Failed to read stats: {e}")
        avg_cpu = None

    # Stop stats
    try:
        http_post(f"{base_url}/api/v1/tests/stop", {"test_id": "workload_test"})
    except Exception:
        pass

    return avg_cpu


def test_scaling(base_url, cpu_ms=200, intensity=0.8):
    """Test 3: Measure CPU% at different thread counts to find the scaling curve."""
    print("\n" + "=" * 60)
    print(f"  TEST 3: Thread scaling (cpu_ms={cpu_ms}, intensity={intensity})")
    print("=" * 60)

    thread_counts = [1, 2, 4, 8, 16, 24, 32]
    results = []

    print(f"  {'threads':>8} {'cpu_avg%':>10} {'req/sec':>10} {'cpu/thread':>12}")
    print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*12}")

    for tc in thread_counts:
        # Start stats
        try:
            http_post(f"{base_url}/api/v1/tests/start", {
                "test_run_id": f"scale_test_{tc}",
                "scenario_id": "scale_test",
                "mode": "calibration",
                "collect_interval_sec": 1.0,
                "thread_count": tc,
            })
        except Exception:
            pass

        # Fire load
        stop_flag = False
        req_count = [0]

        def worker():
            while not stop_flag:
                try:
                    http_post(f"{base_url}/api/v1/operations/work", {
                        "cpu_ms": cpu_ms,
                        "intensity": intensity,
                        "touch_mb": 1.0,
                    }, timeout=10)
                    req_count[0] += 1
                except Exception:
                    pass
                time.sleep(0.5)

        pool = ThreadPoolExecutor(max_workers=tc)
        futures = [pool.submit(worker) for _ in range(tc)]

        test_dur = 15
        time.sleep(test_dur)
        stop_flag = True
        pool.shutdown(wait=True, cancel_futures=True)

        time.sleep(2)

        # Read stats
        try:
            stats = http_get(f"{base_url}/api/v1/stats/recent?count=8")
            samples = stats.get("samples", [])
            if samples:
                cpu_values = [s.get("cpu_percent", 0) for s in samples]
                avg_cpu = sum(cpu_values) / len(cpu_values)
            else:
                avg_cpu = 0
        except Exception:
            avg_cpu = 0

        rps = req_count[0] / test_dur
        cpu_per_thread = avg_cpu / tc if tc > 0 else 0
        print(f"  {tc:>8} {avg_cpu:>10.1f} {rps:>10.1f} {cpu_per_thread:>12.2f}")
        results.append((tc, avg_cpu, rps, cpu_per_thread))

        # Stop stats
        try:
            http_post(f"{base_url}/api/v1/tests/stop", {"test_id": f"scale_test_{tc}"})
        except Exception:
            pass

        # Brief cooldown between tests
        time.sleep(3)

    return results


def recommend(scaling_results, target_min=20, target_max=40):
    """Recommend cpu_ms and thread count based on scaling results."""
    print("\n" + "=" * 60)
    print(f"  RECOMMENDATION (target CPU range: {target_min}-{target_max}%)")
    print("=" * 60)

    if not scaling_results:
        fail("No scaling data to analyze")
        return

    for tc, avg_cpu, rps, cpt in scaling_results:
        marker = ""
        if target_min <= avg_cpu <= target_max:
            marker = " <-- IN RANGE"
        elif avg_cpu > target_max:
            marker = " <-- TOO HOT"
        print(f"  {tc:>3} threads -> {avg_cpu:.1f}% CPU{marker}")

    # Find thread count range that hits target
    in_range = [(tc, cpu) for tc, cpu, _, _ in scaling_results if target_min <= cpu <= target_max]
    below = [(tc, cpu) for tc, cpu, _, _ in scaling_results if cpu < target_min]
    above = [(tc, cpu) for tc, cpu, _, _ in scaling_results if cpu > target_max]

    if in_range:
        info(f"Thread counts in target range: {[tc for tc, _ in in_range]}")
        info("Calibration should work with current cpu_ms")
    elif below and not above:
        max_tc, max_cpu = max(scaling_results, key=lambda x: x[1])[:2]
        needed_factor = target_min / max_cpu if max_cpu > 0 else 10
        info(f"Even {max_tc} threads only reaches {max_cpu:.1f}%")
        info(f"Need ~{needed_factor:.1f}x more CPU burn per request")
        info(f"Suggestion: increase cpu_ms or reduce think time")
    elif above and not below:
        info("Even 1 thread exceeds target — reduce cpu_ms")


def main():
    parser = argparse.ArgumentParser(description="Workload test")
    parser.add_argument("--target-ip", required=True, help="Target emulator IP")
    parser.add_argument("--emulator-port", type=int, default=8080)
    parser.add_argument("--cpu-ms", type=int, default=200, help="cpu_ms to test with")
    parser.add_argument("--intensity", type=float, default=0.8)
    parser.add_argument("--target-min", type=float, default=20, help="Target CPU min %")
    parser.add_argument("--target-max", type=float, default=40, help="Target CPU max %")
    parser.add_argument("--skip-scaling", action="store_true", help="Skip scaling test (slow)")
    args = parser.parse_args()

    base_url = f"http://{args.target_ip}:{args.emulator_port}"

    print("=" * 60)
    print(f"  WORKLOAD TEST")
    print(f"  Target: {base_url}")
    print(f"  cpu_ms: {args.cpu_ms}  intensity: {args.intensity}")
    print(f"  Target CPU range: {args.target_min}-{args.target_max}%")
    print("=" * 60)

    # Test 0: Health
    if not test_emulator_health(base_url):
        sys.exit(1)

    # Test 1: Direct endpoint — verify burn times
    work_results = test_work_endpoint(base_url)

    # Test 2: Concurrent load — verify CPU% reading
    avg_cpu = test_concurrent_cpu(base_url, cpu_ms=args.cpu_ms,
                                   intensity=args.intensity, threads=16)

    # Test 3: Scaling curve
    if not args.skip_scaling:
        scaling = test_scaling(base_url, cpu_ms=args.cpu_ms, intensity=args.intensity)
        recommend(scaling, args.target_min, args.target_max)
    else:
        info("Scaling test skipped (--skip-scaling)")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
