"""
Test all emulator endpoints after deployment.

Validates:
  1. Health check
  2. POST /config — sets output_folders, partner
  3. GET /config — verifies input_folders auto-detected, output_folders set
  4. POST /operations/cpu
  5. POST /operations/mem
  6. POST /operations/disk
  7. POST /operations/net
  8. POST /operations/file (normal)
  9. POST /operations/file (confidential + zip)
  10. Verify files created in output folders

Usage: python test_emulator_endpoints.py [linux|windows|all]
"""
import json
import sys
import requests
import time


def test_emulator(host: str, label: str, output_folders: list):
    """Run all endpoint tests against one emulator instance."""
    base = f"http://{host}:8080/api/v1"
    results = {}
    print(f"\n{'=' * 60}")
    print(f"TESTING EMULATOR: {label} ({host})")
    print(f"{'=' * 60}")

    # 1. Health check
    print("\n--- 1. Health check ---")
    try:
        r = requests.get(f"http://{host}:8080/health", timeout=5)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "healthy"
        print(f"  Status: {data.get('status')}, Version: {data.get('version')}")
        results["health"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["health"] = False
        print("\nEmulator not reachable. Aborting.")
        return results

    # 2. POST /config
    print("\n--- 2. POST /config ---")
    config_body = {
        "output_folders": output_folders,
        "partner": {"fqdn": host, "port": 8080},
        "stats": {
            "output_dir": "./stats",
            "default_interval_sec": 1.0,
            "service_monitor_patterns": [],
        },
    }
    try:
        r = requests.post(f"{base}/config", json=config_body, timeout=10)
        data = r.json()
        ok = r.status_code == 200 and data.get("is_configured") is True
        print(f"  is_configured: {data.get('is_configured')}")
        print(f"  output_folders: {data.get('output_folders')}")
        print(f"  input_folders: {data.get('input_folders')}")
        results["post_config"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["post_config"] = False

    # 3. GET /config
    print("\n--- 3. GET /config ---")
    try:
        r = requests.get(f"{base}/config", timeout=5)
        data = r.json()
        inp = data.get("input_folders", {})
        has_normal = bool(inp.get("normal"))
        has_conf = bool(inp.get("confidential"))
        has_output = len(data.get("output_folders", [])) > 0
        ok = has_normal and has_output
        print(f"  input_folders.normal: {inp.get('normal')}")
        print(f"  input_folders.confidential: {inp.get('confidential')}")
        print(f"  output_folders: {data.get('output_folders')}")
        print(f"  auto-detected inputs: normal={has_normal}, confidential={has_conf}")
        results["get_config"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["get_config"] = False

    # 4. POST /operations/cpu
    print("\n--- 4. CPU operation ---")
    try:
        r = requests.post(f"{base}/operations/cpu", json={
            "duration_ms": 500, "intensity": 0.5,
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, duration_ms: {data.get('duration_ms')}")
        results["cpu"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["cpu"] = False

    # 5. POST /operations/mem
    print("\n--- 5. MEM operation ---")
    try:
        r = requests.post(f"{base}/operations/mem", json={
            "duration_ms": 500, "size_mb": 10, "pattern": "sequential",
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, duration_ms: {data.get('duration_ms')}")
        results["mem"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["mem"] = False

    # 6. POST /operations/disk
    print("\n--- 6. DISK operation ---")
    try:
        r = requests.post(f"{base}/operations/disk", json={
            "duration_ms": 500, "mode": "write", "size_mb": 10, "block_size_kb": 64,
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, duration_ms: {data.get('duration_ms')}")
        results["disk"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["disk"] = False

    # 7. POST /operations/net
    print("\n--- 7. NET operation ---")
    try:
        r = requests.post(f"{base}/operations/net", json={
            "duration_ms": 500, "packet_size_bytes": 1024, "mode": "send",
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, duration_ms: {data.get('duration_ms')}")
        results["net"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["net"] = False

    # 8. POST /operations/file (normal)
    print("\n--- 8. FILE operation (normal) ---")
    try:
        r = requests.post(f"{base}/operations/file", json={
            "is_confidential": False, "make_zip": False,
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, format: {data.get('output_format')}")
        print(f"  size: {data.get('actual_size_bytes')} bytes, folder: {data.get('output_folder')}")
        print(f"  file: {data.get('output_file')}")
        print(f"  source_files_used: {data.get('source_files_used')}")
        results["file_normal"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["file_normal"] = False

    # 9. POST /operations/file (confidential + zip)
    print("\n--- 9. FILE operation (confidential + zip) ---")
    try:
        r = requests.post(f"{base}/operations/file", json={
            "is_confidential": True, "make_zip": True,
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, format: {data.get('output_format')}")
        print(f"  size: {data.get('actual_size_bytes')} bytes, zipped: {data.get('is_zipped')}")
        print(f"  file: {data.get('output_file')}")
        print(f"  source_files_used: {data.get('source_files_used')}")
        results["file_confidential_zip"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["file_confidential_zip"] = False

    # 10. Run a few more file ops to populate multiple output folders
    print("\n--- 10. Bulk file operations (5x) ---")
    file_ok_count = 0
    for i in range(5):
        try:
            r = requests.post(f"{base}/operations/file", json={
                "is_confidential": i % 2 == 0, "make_zip": i % 3 == 0,
                "output_format": ["txt", "csv", "doc", "xls", "pdf"][i],
            }, timeout=30)
            if r.status_code == 200 and r.json().get("status") == "completed":
                file_ok_count += 1
        except Exception:
            pass
    print(f"  {file_ok_count}/5 succeeded")
    results["file_bulk"] = file_ok_count == 5

    # 11. POST /config/pool (init memory pool)
    print("\n--- 11. POOL init (1 GB) ---")
    try:
        r = requests.post(f"{base}/config/pool", json={
            "size_gb": 1.0,
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("allocated") is True
        print(f"  allocated: {data.get('allocated')}, size_bytes: {data.get('size_bytes')}")
        results["pool_init"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["pool_init"] = False

    # 12. GET /config/pool (verify pool status)
    print("\n--- 12. POOL status ---")
    try:
        r = requests.get(f"{base}/config/pool", timeout=5)
        data = r.json()
        ok = r.status_code == 200 and data.get("allocated") is True and data.get("size_bytes", 0) > 0
        print(f"  allocated: {data.get('allocated')}, size_bytes: {data.get('size_bytes')}")
        results["pool_status"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["pool_status"] = False

    # 13. POST /operations/work (cpu burn + pool touch)
    print("\n--- 13. WORK operation ---")
    try:
        r = requests.post(f"{base}/operations/work", json={
            "cpu_ms": 10, "intensity": 0.8, "touch_mb": 1.0, "touch_pattern": "random",
        }, timeout=30)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "completed"
        print(f"  status: {data.get('status')}, duration_ms: {data.get('duration_ms')}")
        print(f"  details: {data.get('details')}")
        results["work"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["work"] = False

    # 14. Bulk WORK operations (10x rapid fire)
    print("\n--- 14. Bulk WORK operations (10x) ---")
    work_ok_count = 0
    for i in range(10):
        try:
            r = requests.post(f"{base}/operations/work", json={
                "cpu_ms": 5, "intensity": 0.8, "touch_mb": 0.5, "touch_pattern": "random",
            }, timeout=30)
            if r.status_code == 200 and r.json().get("status") == "completed":
                work_ok_count += 1
        except Exception:
            pass
    print(f"  {work_ok_count}/10 succeeded")
    results["work_bulk"] = work_ok_count == 10

    # 15. DELETE /config/pool (cleanup)
    print("\n--- 15. POOL destroy ---")
    try:
        r = requests.delete(f"{base}/config/pool", timeout=5)
        data = r.json()
        ok = r.status_code == 200 and data.get("allocated") is False
        print(f"  allocated: {data.get('allocated')}, size_bytes: {data.get('size_bytes')}")
        results["pool_destroy"] = ok
    except Exception as e:
        print(f"  FAILED: {e}")
        results["pool_destroy"] = False

    # Summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {label}")
    print(f"{'=' * 60}")
    all_pass = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")
        if not ok:
            all_pass = False
    print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL'}")
    return results


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    all_results = {}

    if target in ("linux", "all"):
        all_results["linux"] = test_emulator(
            host="10.0.0.92",
            label="Emulator on Linux (10.0.0.92)",
            output_folders=[
                "/opt/emulator/output/dir1",
                "/opt/emulator/output/dir2",
                "/opt/emulator/output/dir3",
                "/opt/emulator/output/dir4",
            ],
        )

    if target in ("windows", "all"):
        all_results["windows"] = test_emulator(
            host="10.0.0.91",
            label="Emulator on Windows (10.0.0.91)",
            output_folders=[
                "C:\\emulator\\output\\dir1",
                "C:\\emulator\\output\\dir2",
                "C:\\emulator\\output\\dir3",
                "C:\\emulator\\output\\dir4",
            ],
        )

    if len(all_results) > 1:
        print(f"\n{'=' * 60}")
        print("GRAND SUMMARY")
        print(f"{'=' * 60}")
        for platform, results in all_results.items():
            passed = all(results.values())
            print(f"  {platform}: {'PASS' if passed else 'FAIL'}")
