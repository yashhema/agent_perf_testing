"""
Test steady-state load on emulator: worker threads + stats observer.

Usage:
  python test_steady_load.py [host] [threads] [duration_sec] [cpu_ms]

Examples:
  python test_steady_load.py 10.0.0.92 2 30 10
  python test_steady_load.py 10.0.0.92 5 60 50
  python test_steady_load.py 10.0.0.92 10 30 100
"""
import sys
import time
import threading
import requests

HOST = sys.argv[1] if len(sys.argv) > 1 else "10.0.0.92"
THREADS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
DURATION = int(sys.argv[3]) if len(sys.argv) > 3 else 30
CPU_MS = int(sys.argv[4]) if len(sys.argv) > 4 else 10

BASE = f"http://{HOST}:8080/api/v1"
STATS_INTERVAL = 2  # poll stats every 2 seconds
POOL_GB = 1.0
TOUCH_MB = 1.0

stop_flag = threading.Event()
worker_counts = {"ok": 0, "err": 0}
count_lock = threading.Lock()


def worker(thread_id):
    """Call /work in a tight loop."""
    body = {"cpu_ms": CPU_MS, "intensity": 0.8, "touch_mb": TOUCH_MB, "touch_pattern": "random"}
    session = requests.Session()
    while not stop_flag.is_set():
        try:
            r = session.post(f"{BASE}/operations/work", json=body, timeout=10)
            with count_lock:
                if r.status_code == 200:
                    worker_counts["ok"] += 1
                else:
                    worker_counts["err"] += 1
        except Exception:
            with count_lock:
                worker_counts["err"] += 1


def stats_observer():
    """Poll stats/system and print CPU readings."""
    session = requests.Session()
    readings = []
    print(f"\n{'TIME':>8}  {'CPU%':>6}  {'MEM%':>6}  {'MEM_MB':>8}  {'OPS_OK':>8}  {'OPS_ERR':>8}")
    print("-" * 60)

    while not stop_flag.is_set():
        time.sleep(STATS_INTERVAL)
        try:
            r = session.get(f"{BASE}/stats/system", timeout=5)
            data = r.json()
            cpu = data.get("cpu_percent", 0)
            mem = data.get("memory_percent", 0)
            mem_mb = data.get("memory_used_mb", 0)
            with count_lock:
                ok = worker_counts["ok"]
                err = worker_counts["err"]
            elapsed = time.time() - start_time
            readings.append(cpu)
            print(f"{elapsed:7.1f}s  {cpu:5.1f}%  {mem:5.1f}%  {mem_mb:7.1f}  {ok:>8}  {err:>8}")
        except Exception as e:
            print(f"  stats error: {e}")

    # Print summary
    if readings:
        readings_trimmed = readings[2:] if len(readings) > 4 else readings  # skip first 2 warmup
        print(f"\n{'=' * 60}")
        print(f"STATS SUMMARY ({len(readings_trimmed)} samples after warmup trim)")
        print(f"  CPU avg:  {sum(readings_trimmed)/len(readings_trimmed):.1f}%")
        print(f"  CPU min:  {min(readings_trimmed):.1f}%")
        print(f"  CPU max:  {max(readings_trimmed):.1f}%")
        print(f"  CPU spread: {max(readings_trimmed) - min(readings_trimmed):.1f}%")
        sorted_r = sorted(readings_trimmed)
        p50 = sorted_r[len(sorted_r) // 2]
        print(f"  CPU p50:  {p50:.1f}%")
        in_range = sum(1 for r in readings_trimmed if 15 <= r <= 50)
        print(f"  In 15-50% range: {in_range}/{len(readings_trimmed)} ({100*in_range/len(readings_trimmed):.0f}%)")


def main():
    global start_time

    print(f"Target: {HOST}")
    print(f"Threads: {THREADS}, Duration: {DURATION}s, cpu_ms: {CPU_MS}")
    print(f"Pool: {POOL_GB} GB, touch_mb: {TOUCH_MB}")

    # Health check
    try:
        r = requests.get(f"http://{HOST}:8080/health", timeout=5)
        print(f"Health: {r.json().get('status')}")
    except Exception as e:
        print(f"Emulator not reachable: {e}")
        return

    # Init pool
    print(f"\nInitializing pool ({POOL_GB} GB)...")
    r = requests.post(f"{BASE}/config/pool", json={"size_gb": POOL_GB}, timeout=30)
    print(f"  Pool: {r.json()}")

    # Start emulator stats collection
    print("Starting stats collection...")
    try:
        r = requests.post(f"{BASE}/tests/start", json={
            "test_run_id": "steady-load-test",
            "scenario_id": "steady-test",
            "mode": "normal",
            "collect_interval_sec": STATS_INTERVAL,
        }, timeout=10)
        print(f"  Test started: {r.json().get('test_id', 'ok')}")
    except Exception as e:
        print(f"  Warning: start_test failed ({e}), stats/system still works")

    # Start stats observer
    start_time = time.time()
    observer = threading.Thread(target=stats_observer, daemon=True)
    observer.start()

    # Start worker threads
    print(f"\nStarting {THREADS} worker threads...")
    workers = []
    for i in range(THREADS):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        t.start()
        workers.append(t)

    # Wait for duration
    try:
        time.sleep(DURATION)
    except KeyboardInterrupt:
        print("\nInterrupted!")

    # Stop
    stop_flag.set()
    time.sleep(1)  # let observer print final reading

    with count_lock:
        total_ok = worker_counts["ok"]
        total_err = worker_counts["err"]

    print(f"\n{'=' * 60}")
    print(f"LOAD SUMMARY")
    print(f"  Total ops: {total_ok + total_err} (ok={total_ok}, err={total_err})")
    print(f"  Ops/sec: {total_ok / DURATION:.1f}")
    print(f"  Ops/sec/thread: {total_ok / DURATION / THREADS:.1f}")

    # Cleanup pool
    print("\nDestroying pool...")
    try:
        requests.delete(f"{BASE}/config/pool", timeout=5)
    except Exception:
        pass

    # Stop stats
    try:
        requests.post(f"{BASE}/tests/steady-load-test/stop", timeout=5)
    except Exception:
        pass

    print("Done.")


if __name__ == "__main__":
    main()
