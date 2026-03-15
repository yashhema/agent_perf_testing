# Java Emulator — API Specification

All endpoints must return **identical JSON structures** to the Python emulator.
The Java emulator listens on **port 8080** with base path `/api/v1`.

> **Validated against Python emulator code on 2026-03-11. All field names, types, defaults, and error responses match the Python implementation.**

---

## 1. Health

### GET /health

No request body.

**Response 200:**
```json
{
  "status": "healthy",
  "service": "emulator",
  "version": "1.0.0",
  "uptime_sec": 123.4
}
```

---

## 2. Configuration

### POST /api/v1/config

Configure output folders, partner, stats settings.

**Request:**
```json
{
  "output_folders": ["/opt/emulator/output/dir1", "/opt/emulator/output/dir2"],
  "partner": {"fqdn": "10.0.0.92", "port": 8080},
  "stats": {
    "output_dir": "./stats",
    "default_interval_sec": 1.0,
    "max_memory_samples": 10000,
    "service_monitor_patterns": []
  }
}
```
- `output_folders`: list of strings, required
- `partner`: object, required
  - `fqdn`: string, required
  - `port`: int, optional (default 8080)
- `stats`: object, **optional** (nullable)
  - `output_dir`: string (default "./stats")
  - `default_interval_sec`: float (default 1.0)
  - `max_memory_samples`: int (default 10000), > 0
  - `service_monitor_patterns`: list of strings (default [])

**Response 200:**
```json
{
  "is_configured": true,
  "output_folders": ["/opt/emulator/output/dir1", "/opt/emulator/output/dir2"],
  "input_folders": {
    "normal": "/opt/emulator/data/normal",
    "confidential": "/opt/emulator/data/confidential"
  },
  "partner": {"fqdn": "10.0.0.92", "port": 8080},
  "stats": {
    "output_dir": "./stats",
    "default_interval_sec": 1.0,
    "max_memory_samples": 10000,
    "service_monitor_patterns": []
  }
}
```

> **Note**: `input_folders.normal` and `input_folders.confidential` are **strings** (not arrays). They are auto-detected from the installation directory (e.g., `data/normal/`, `data/confidential/`).

### GET /api/v1/config

**Response 200:** Same structure as POST response.

---

## 3. Memory Pool

### POST /api/v1/config/pool

Allocate a contiguous memory pool (used by `/operations/work`).

**Request:**
```json
{
  "size_gb": 1.0
}
```
- `size_gb`: float, required, > 0, **<= 64**

**Response 200:**
```json
{
  "allocated": true,
  "size_bytes": 1073741824
}
```

### GET /api/v1/config/pool

**Response 200:**
```json
{
  "allocated": true,
  "size_bytes": 1073741824
}
```
If no pool: `{"allocated": false, "size_bytes": 0}`

### DELETE /api/v1/config/pool

**Response 200:**
```json
{
  "allocated": false,
  "size_bytes": 0
}
```

---

## 4. Operations

All operation endpoints return within the requested duration.

### POST /api/v1/operations/cpu

Burns CPU for `duration_ms` using busy loops.

**Request:**
```json
{
  "duration_ms": 500,
  "intensity": 0.5
}
```
- `duration_ms`: int, required, > 0
- `intensity`: float, optional (default 1.0), range [0.0, 1.0]

**Response 200:**
```json
{
  "operation": "CPU",
  "status": "completed",
  "duration_ms": 503,
  "details": {
    "requested_duration_ms": 500,
    "intensity": 0.5
  }
}
```

### POST /api/v1/operations/mem

Allocates memory, accesses with given pattern, then releases.

**Request:**
```json
{
  "duration_ms": 500,
  "size_mb": 10,
  "pattern": "sequential"
}
```
- `duration_ms`: int, required, > 0
- `size_mb`: int, required, > 0
- `pattern`: "sequential" | "random" (default "sequential")

**Response 200:**
```json
{
  "operation": "MEM",
  "status": "completed",
  "duration_ms": 510,
  "details": {
    "requested_duration_ms": 500,
    "size_mb": 10,
    "pattern": "sequential",
    "access_count": 1280
  }
}
```

### POST /api/v1/operations/disk

Performs disk I/O (read/write/mixed).

**Request:**
```json
{
  "duration_ms": 500,
  "mode": "write",
  "size_mb": 100,
  "block_size_kb": 64
}
```
- `duration_ms`: int, required, > 0
- `mode`: "read" | "write" | "mixed", required
- `size_mb`: int, optional (default 100), > 0
- `block_size_kb`: int, optional (default 64), > 0

**Response 200:**
```json
{
  "operation": "DISK",
  "status": "completed",
  "duration_ms": 512,
  "details": {
    "requested_duration_ms": 500,
    "mode": "write",
    "size_mb": 100,
    "block_size_kb": 64,
    "bytes_written": 104857600,
    "bytes_read": 0
  }
}
```

### POST /api/v1/operations/net

Network send/receive to partner.

**Request:**
```json
{
  "duration_ms": 500,
  "target_host": null,
  "target_port": null,
  "packet_size_bytes": 1024,
  "mode": "send"
}
```
- `duration_ms`: int, required, > 0
- `target_host`: string, optional (uses configured partner)
- `target_port`: int, optional (uses configured partner), range [1, 65535]
- `packet_size_bytes`: int, optional (default 1024), > 0
- `mode`: "send" | "receive" | "both" (default "both")

**Response 200:**
```json
{
  "operation": "NET",
  "status": "completed",
  "duration_ms": 505,
  "details": {
    "requested_duration_ms": 500,
    "target_host": "10.0.0.92",
    "target_port": 8080,
    "mode": "send",
    "bytes_sent": 102400,
    "bytes_received": 0,
    "connection_established": true,
    "error_message": null
  }
}
```

**Error 400** (no target and no partner configured):
```json
{
  "detail": "No target host specified and no partner configured"
}
```

### POST /api/v1/operations/file

Creates an output file from source data.

**Request:**
```json
{
  "is_confidential": false,
  "make_zip": false,
  "size_bracket": null,
  "target_size_kb": null,
  "output_format": null,
  "output_folder_idx": null,
  "source_file_ids": null
}
```
- `is_confidential`: bool, optional (default false)
- `make_zip`: bool, optional (default false)
- `size_bracket`: "small" | "medium" | "large" | "xlarge" | null (random if null)
- `target_size_kb`: int | null, > 0 (random within bracket if null)
- `output_format`: "txt" | "csv" | "doc" | "xls" | "pdf" | null (random if null)
- `output_folder_idx`: int | null, >= 0 (random if null)
- `source_file_ids`: string | null (semicolon-separated IDs, auto-select if null)

**Response 200:**
```json
{
  "operation": "FILE",
  "status": "completed",
  "duration_ms": 45,
  "size_bracket": "50-100KB",
  "actual_size_bytes": 67234,
  "output_format": "csv",
  "output_folder": "/opt/emulator/output/dir1",
  "output_file": "/opt/emulator/output/dir1/file_20250309_143022_abc123.csv",
  "is_confidential": false,
  "is_zipped": false,
  "source_files_used": 3,
  "error_message": null
}
```

**Error 400** (no output folders configured):
```json
{
  "detail": "No output folders configured. POST /api/v1/config first."
}
```

**Size bracket mappings:**
| Bracket | Range | Display |
|---------|-------|---------|
| small | 50-100 KB | "50-100KB" |
| medium | 100-500 KB | "100-500KB" |
| large | 500 KB - 2 MB | "500KB-2MB" |
| xlarge | 2-10 MB | "2MB-10MB" |

### POST /api/v1/operations/work

**CRITICAL ENDPOINT** — CPU burn + memory pool touch. This is the steady-state load generator.

**Request:**
```json
{
  "cpu_ms": 10,
  "intensity": 0.8,
  "touch_mb": 1.0,
  "touch_pattern": "random"
}
```
- `cpu_ms`: int, optional (default 10), > 0 — CPU burn duration in ms
- `intensity`: float, optional (default 0.8), range [0.0, 1.0]
- `touch_mb`: float, optional (default 1.0), >= 0.0 — MB of pool to touch. 0 = skip.
- `touch_pattern`: "sequential" | "random" (default "random")

**Response 200:**
```json
{
  "operation": "WORK",
  "status": "completed",
  "duration_ms": 15,
  "details": {
    "cpu_ms_actual": 10,
    "pages_touched": 256
  }
}
```

**Error 400** (no pool allocated):
```json
{
  "detail": "Memory pool not initialised. POST /api/v1/config/pool first."
}
```

> **Note**: Error is HTTP 400, not an in-band error in the response body.

### POST /api/v1/operations/suspicious

Performs OS-level activity that EDR/AV would flag.

**Request:**
```json
{
  "activity_type": "crontab_write",
  "duration_ms": 500
}
```
- `activity_type`: string, required
- `duration_ms`: int, optional (default 500), > 0

**Response 200:**
```json
{
  "operation": "suspicious",
  "status": "completed",
  "duration_ms": 503,
  "details": {
    "activity_type": "crontab_write",
    "detail": "Wrote crontab entry...",
    "os_family": "linux",
    "error_message": null
  }
}
```

> **Note**: `operation` is lowercase `"suspicious"` (not uppercase).

**Supported activities:**

Linux: `crontab_write`, `tmp_executable`, `process_spawn`, `etc_hosts_modify`, `sensitive_file_access`, `syslog_inject`, `hidden_file_create`, `setuid_attempt`

Windows: `registry_write`, `scheduled_task`, `service_query`, `hidden_file_create`, `powershell_encoded`, `hosts_file_modify`, `startup_folder_write`, `wmi_query`

---

## 5. Tests (Stats Collection Control)

### POST /api/v1/tests/start

Starts stats collection (and optionally an internal operation loop).

**Request:**
```json
{
  "test_run_id": "run-001",
  "scenario_id": "steady-test",
  "mode": "normal",
  "collect_interval_sec": 1.0,
  "thread_count": 1,
  "duration_sec": null,
  "loop_count": null,
  "operation": null
}
```
- `test_run_id`: string, required
- `scenario_id`: string, required
- `mode`: "calibration" | "normal" (default "normal")
- `collect_interval_sec`: float, optional (default 1.0), > 0
- `thread_count`: int, required, > 0
- `duration_sec`: int | null, > 0
- `loop_count`: int | null
- `operation`: CompositeOperationRequest | null (null = stats-only mode)

**CompositeOperationRequest:**
```json
{
  "cpu": {"duration_ms": 500, "intensity": 0.8},
  "mem": {"duration_ms": 500, "size_mb": 10, "pattern": "sequential"},
  "disk": {"duration_ms": 500, "mode": "write", "size_mb": 100, "block_size_kb": 64},
  "net": {"duration_ms": 500, "packet_size_bytes": 1024, "mode": "send"},
  "parallel": true
}
```
- `cpu`: CpuRequest | null (optional)
- `mem`: MemRequest | null (optional)
- `disk`: DiskRequest | null (optional)
- `net`: NetRequest | null (optional)
- `parallel`: bool, optional (default true)

When `operation` is null, the emulator runs stats collection only — no internal load loop. JMeter drives the load externally via `/operations/*`.

**Response 200:**
```json
{
  "test_id": "test-abc123",
  "test_run_id": "run-001",
  "scenario_id": "steady-test",
  "mode": "normal",
  "status": "running",
  "thread_count": 1,
  "iterations_completed": 0,
  "started_at": "2025-03-09T14:30:00",
  "elapsed_sec": 0.0,
  "error_count": 0,
  "stats_collection": {
    "enabled": true,
    "interval_sec": 1.0,
    "samples_collected": 0
  }
}
```

> **Note**: `test_run_id`, `scenario_id`, `mode`, `stats_collection` can be null in some edge cases.

### POST /api/v1/tests/

Legacy alias for `/api/v1/tests/start`. Same request/response.

### GET /api/v1/tests/

List all tests.

**Response 200:**
```json
[
  {
    "test_id": "test-abc123",
    "test_run_id": "run-001",
    "scenario_id": "steady-test",
    "mode": "normal",
    "status": "running",
    "thread_count": 1,
    "iterations_completed": 50,
    "started_at": "2025-03-09T14:30:00",
    "elapsed_sec": 60.0,
    "error_count": 0,
    "stats_collection": { "enabled": true, "interval_sec": 1.0, "samples_collected": 60 }
  }
]
```

### GET /api/v1/tests/{test_id}

Get single test status.

**Response 200:** Same `TestStatusResponse` as above (single object, not array).

**Response 404:** `{"detail": "Test not found"}`

### POST /api/v1/tests/{test_id}/stop

Stop a running test and finalize stats.

**Request (optional body):**
```json
{
  "force": false
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Test stopped and stats saved",
  "stats_file": "./stats/test-abc123_stats.json",
  "total_samples": 60
}
```

---

## 6. Stats

### GET /api/v1/stats/system

Current system stats snapshot.

**Response 200:**
```json
{
  "timestamp": "2025-03-09T14:31:00Z",
  "cpu_percent": 25.3,
  "memory_percent": 45.2,
  "memory_used_mb": 3612.5,
  "memory_available_mb": 4387.5,
  "disk_read_bytes": 1234567,
  "disk_write_bytes": 2345678,
  "network_sent_bytes": 345678,
  "network_recv_bytes": 456789
}
```

### GET /api/v1/stats/recent?count=100

Recent stats samples from the current collection.

**Query params:**
- `count`: int, optional (default 100), range [1, 1000]

**Response 200:**
```json
{
  "test_id": "test-abc123",
  "test_run_id": "run-001",
  "is_collecting": true,
  "total_samples": 60,
  "returned_samples": 10,
  "samples": [
    {
      "timestamp": "2025-03-09T14:31:00Z",
      "elapsed_sec": 60.0,
      "cpu_percent": 25.3,
      "memory_percent": 45.2,
      "memory_used_mb": 3612.5,
      "memory_available_mb": 4387.5,
      "disk_read_bytes": 1234567,
      "disk_write_bytes": 2345678,
      "disk_read_rate_mbps": 1.2,
      "disk_write_rate_mbps": 2.3,
      "network_sent_bytes": 345678,
      "network_recv_bytes": 456789,
      "network_sent_rate_mbps": 0.3,
      "network_recv_rate_mbps": 0.4,
      "process_stats": [
        {"name": "csfalconservice", "pid": 1234, "cpu_percent": 5.0, "memory_percent": 2.0, "memory_rss_mb": 160.0}
      ]
    }
  ]
}
```

### GET /api/v1/stats/all?test_run_id=run-001&scenario_id=steady-test

All stats from a completed test (reads from saved stats file).

**Query params:**
- `test_run_id`: string, required
- `scenario_id`: string, optional

**Response 200:**
```json
{
  "metadata": {
    "test_id": "test-abc123",
    "test_run_id": "run-001",
    "scenario_id": "steady-test",
    "mode": "normal",
    "started_at": "2025-03-09T14:30:00Z",
    "ended_at": "2025-03-09T14:31:00Z",
    "duration_sec": 60.0,
    "collect_interval_sec": 1.0,
    "total_samples": 60
  },
  "samples": [ ... ],
  "summary": {
    "cpu_percent": {"avg": 25.0, "min": 15.0, "max": 35.0, "p50": 25.0, "p90": 32.0, "p95": 33.5, "p99": 34.8},
    "memory_percent": {"avg": 45.0, "min": 44.0, "max": 46.0, "p50": 45.0, "p90": 45.5, "p95": 45.8, "p99": 46.0},
    "disk_read_rate_mbps": {"avg": 0.5, "min": 0.0, "max": 2.0, "p50": 0.4, "p90": 1.5, "p95": 1.8, "p99": 2.0},
    "disk_write_rate_mbps": {"avg": 1.2, "min": 0.0, "max": 5.0, "p50": 1.0, "p90": 3.0, "p95": 4.0, "p99": 4.8},
    "network_sent_rate_mbps": {"avg": 0.1, "min": 0.0, "max": 0.5, "p50": 0.1, "p90": 0.3, "p95": 0.4, "p99": 0.5},
    "network_recv_rate_mbps": {"avg": 0.3, "min": 0.0, "max": 1.0, "p50": 0.2, "p90": 0.7, "p95": 0.8, "p99": 0.9},
    "process_stats": {}
  }
}
```

**Error 400** (test still running):
```json
{
  "detail": "Test is still running. Stop the test first."
}
```

**Error 404** (stats file not found):
```json
{
  "detail": "Stats file not found for test_run_id: run-001"
}
```

### GET /api/v1/stats/iterations

Iteration timing statistics.

**Response 200:**
```json
{
  "sample_count": 1000,
  "avg_ms": 15.2,
  "stddev_ms": 3.1,
  "min_ms": 10.0,
  "max_ms": 45.0,
  "p50_ms": 14.5,
  "p90_ms": 19.0,
  "p99_ms": 32.0
}
```

### POST /api/v1/stats/iterations/clear

Clear iteration timing buffer.

**Response 200:**
```json
{
  "success": true,
  "message": "Iteration stats cleared"
}
```

---

## 7. Agent Management

### GET /api/v1/agent/{agent_type}

Get info about an installed security agent.

**Path params:**
- `agent_type`: string — "crowdstrike" | "sentinelone" | "carbonblack"

**Response 200:**
```json
{
  "agent_type": "crowdstrike",
  "installed": true,
  "version": null,
  "service_status": "running",
  "install_path": "/opt/CrowdStrike"
}
```

**Response 400:** `{"detail": "Unknown agent type: foo"}`

### POST /api/v1/agent/install

**Request:**
```json
{
  "agent_type": "crowdstrike",
  "installer_path": "/tmp/falcon-sensor.deb",
  "install_options": {"CID": "abc123"}
}
```
- `agent_type`: string, required
- `installer_path`: string, required
- `install_options`: dict, optional (default {})

**Response 200:**
```json
{
  "success": true,
  "message": "Agent crowdstrike installed successfully"
}
```

**Error response:**
```json
{
  "success": false,
  "message": "Installation failed: ...",
  "exit_code": 1
}
```

### POST /api/v1/agent/uninstall

**Request:**
```json
{
  "agent_type": "crowdstrike",
  "force": false
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Agent crowdstrike uninstalled successfully"
}
```

### POST /api/v1/agent/service

**Request:**
```json
{
  "agent_type": "crowdstrike",
  "action": "restart"
}
```
- `agent_type`: string, required
- `action`: "start" | "stop" | "restart", required

**Response 200:**
```json
{
  "success": true,
  "message": "Service CSFalconService restart successful"
}
```

---

## Java Implementation Notes

### Why Java?
Python's GIL serializes CPU-bound work in threads. Even with 30 threads calling `/operations/work` (10ms burn each), total CPU stays near 0%. Java threads run truly in parallel on multiple cores.

### Critical for `/operations/work`:
1. **Memory pool** must be a single `byte[]` (or `ByteBuffer`) shared across all request-handler threads
2. **CPU burn** must actually saturate a core for `cpu_ms` — use a tight arithmetic loop (not `Thread.sleep`)
3. **Pool touch** must read/write bytes in the shared pool to generate real memory traffic
4. With `intensity < 1.0`, alternate between burn and sleep within `cpu_ms`

### Framework:
- Spring Boot with embedded Tomcat on port 8080
- Jackson for JSON serialization
- `oshi` library for system stats (CPU%, memory, disk I/O, network I/O) — cross-platform
- `lombok` for boilerplate reduction

### Stats collection:
- Background `ScheduledExecutorService` thread reads system metrics at `collect_interval_sec`
- Stores samples in a `ConcurrentLinkedDeque` (thread-safe)
- On test stop, writes JSON file to `stats.output_dir`
- CPU% from oshi: `CentralProcessor.getSystemCpuLoadBetweenTicks()`
- Disk/network rates: delta-based calculation between samples

### File operations:
- Read source files from `data/normal/` and `data/confidential/`
- Assemble output file content, write to randomly/deterministically chosen output folder
- ZIP support via `java.util.zip.ZipOutputStream`

### Agent management:
- `ProcessBuilder` for service control commands
- Same known agent configs (CrowdStrike, SentinelOne, Carbon Black)
- Platform detection via `System.getProperty("os.name")`
