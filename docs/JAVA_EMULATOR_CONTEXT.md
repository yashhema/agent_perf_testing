# Java Emulator — Full Context & Background

## What We Were Trying To Do

We added a new JMeter template type called `server-steady` to the performance testing framework. Unlike `server-normal` (which cycles through CPU, MEM, DISK, NET, FILE operations) or `server-file-heavy` (file-heavy mix), `server-steady` produces **constant, predictable CPU + memory load** by:

1. **Pre-allocating a memory pool** at test startup (e.g. 1 GB contiguous block)
2. **Per request**: doing a short CPU burn (`cpu_ms`) + touching a small region of the pool (`touch_mb`)
3. No per-request allocation/deallocation spikes — just steady-state load

This is needed for calibration accuracy: the orchestrator's binary search calibration finds the thread count that produces a target CPU range (e.g. 25-35%). Spikey operations make calibration unreliable.

---

## What Was Built (Python Emulator Side)

### New emulator endpoints added:

| Endpoint | File | Purpose |
|----------|------|---------|
| `POST /api/v1/config/pool` | `emulator/app/routers/config.py` | Allocate memory pool (size_gb) |
| `GET /api/v1/config/pool` | `emulator/app/routers/config.py` | Check pool status |
| `DELETE /api/v1/config/pool` | `emulator/app/routers/config.py` | Destroy pool |
| `POST /api/v1/operations/work` | `emulator/app/routers/operations.py` | CPU burn + pool touch |

### New files created:
- `emulator/app/operations/mem_pool.py` — MemoryPool class (bytearray allocation, touch with sequential/random patterns)
- `emulator/app/operations/work.py` — WorkExecutor using `ThreadPoolExecutor` to run CPU burn + pool touch

### New request/response models:
- `WorkOperationRequest` in `emulator/app/models/requests.py` — fields: `cpu_ms`, `intensity`, `touch_mb`, `touch_pattern`
- Pool request/response in config router — fields: `size_gb` → `allocated`, `size_bytes`

### Orchestrator changes:

| File | Change |
|------|--------|
| `orchestrator/src/orchestrator/models/enums.py` | Added `server_steady = "server-steady"` to `TemplateType` enum |
| `orchestrator/src/orchestrator/services/sequence_generator.py` | Added `ServerSteadyOpsGenerator` import + handler in `_create_generator()` |
| `db-assets/generator/generators/ops_sequence_generator.py` | Added `ServerSteadyOpsGenerator` class (generates CSV with columns: `seq_id`, `op_type` where op_type is always "work") |
| `orchestrator/artifacts/jmx/server-steady.jmx` | New JMX template with: setUp ThreadGroup for pool init, main ThreadGroup calling `/operations/work`, CSV Data Set Config for ops sequence, tearDown for pool destroy |

### Database:
- Inserted scenario row: `id=1004, name="Proxmox Baseline Steady", lab_id=4, template_type="server_steady"`
- **Issue encountered**: Initially inserted `server-steady` (hyphen) as template_type value, but SQLAlchemy maps enums by NAME (underscore: `server_steady`), not VALUE (hyphen: `server-steady`). Fixed with UPDATE.
- **Issue encountered**: `created_at` column is NOT NULL — first INSERT failed. Fixed by adding `GETDATE()`.

### Packages rebuilt:
- `orchestrator/artifacts/packages/emulator-linux.tar.gz` — rebuilt with new `work.py`, `mem_pool.py`
- `orchestrator/artifacts/packages/emulator-windows.tar.gz` — rebuilt with same

---

## The Problem: Python GIL

### How `/operations/work` was implemented in Python:

```python
# work.py uses ThreadPoolExecutor (not ProcessPoolExecutor)
# because the memory pool (bytearray) must be shared across all workers
# in the same address space. Processes can't share a bytearray.

class WorkExecutor:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=4)

    def execute(self, request):
        # CPU burn in thread
        future = self._pool.submit(self._cpu_burn, request.cpu_ms, request.intensity)
        # Touch pool memory
        self._touch_pool(request.touch_mb, request.touch_pattern)
        future.result()
```

### The GIL problem:

- Python's Global Interpreter Lock (GIL) allows only **one thread to execute Python bytecode at a time**
- `ThreadPoolExecutor` gives concurrency for I/O-bound work, but **serializes CPU-bound work**
- The CPU burn loop is pure Python arithmetic — completely CPU-bound
- Even with 30 threads calling `/operations/work` simultaneously, the GIL means only 1 thread burns CPU at a time
- Result: **near-zero CPU utilization** regardless of thread count

### Why not `ProcessPoolExecutor`?
- The memory pool (`bytearray`) lives in one process's address space
- `ProcessPoolExecutor` spawns separate processes — they can't access the shared pool
- We'd need shared memory (`multiprocessing.shared_memory`), but that adds complexity and the CPU burn problem remains the core issue

### Test evidence:

We ran `test_steady_load.py` against the deployed Python emulator (10.0.0.92):

**Test 1: cpu_ms=10, 2 threads, 30 seconds**
```
   CPU avg:  0.4%    ← near zero!
   CPU min:  0.0%
   CPU max:  5.9%
   In 15-50% range: 0/12 (0%)
   Ops/sec: 85.0
```

**Test 2: cpu_ms=100, 2 threads, 30 seconds**
```
   CPU avg:  12.1%   ← better but still spikey
   CPU min:  4.5%
   CPU max:  18.7%
   CPU spread: 14.2% ← too much variance
   In 15-50% range: 4/12 (33%)
   Ops/sec: 18.2
```

Even with 100ms burns, CPU barely reaches 18% and has 14% spread. The GIL serializes the burns so only one core is utilized, and inconsistently at that.

**Memory was perfectly steady** in both tests (18.3-18.5%) — the pool mechanism works. Only CPU is the problem.

### Calibration failure (orchestrator Run 17):

The orchestrator ran binary search calibration with 30 threads. Every observation showed CPU < 15%. The calibration loop kept increasing threads but could never reach the 25-35% target range. It timed out.

Additional debugging: orchestrator logging was set to suppress INFO-level messages, so calibration CPU readings weren't visible. We had to check the actual stats data to see the readings were all near 0%.

---

## The Solution: Java Emulator

Java threads are **real OS threads** — no GIL. Multiple threads can burn CPU on multiple cores simultaneously. With 4 vCPUs and 4 threads each doing 10ms burns, we get real parallel CPU utilization.

### What needs to be built:

A Spring Boot application (`emulator_java/`) that implements **every endpoint identically** to the Python emulator. The orchestrator, JMeter templates, test scripts, and deployment pipeline should not need any changes — they just talk to the same HTTP API on port 8080.

### API specification:

Full spec is in `docs/JAVA_EMULATOR_API_SPEC.md` — covers all 23 endpoints across 7 groups:
- Health (1 endpoint)
- Config (2 endpoints)
- Pool (3 endpoints)
- Operations (7 endpoints: cpu, mem, disk, net, file, work, suspicious)
- Tests (4 endpoints)
- Stats (5 endpoints)
- Agent (4 endpoints)

### Key Java implementation requirements:

1. **Memory pool**: Single `byte[]` or `ByteBuffer` shared across all Tomcat request-handler threads. Allocated via `POST /config/pool`, destroyed via `DELETE /config/pool`.

2. **CPU burn** (`/operations/work` and `/operations/cpu`): Tight arithmetic loop (e.g. `Math.sin()`, `Math.sqrt()`) that actually saturates a core for the requested duration. NOT `Thread.sleep()`. With `intensity < 1.0`, alternate between burn and sleep sub-intervals within the duration.

3. **Pool touch** (`/operations/work`): Read/write bytes in the shared `byte[]`. Sequential = walk from offset. Random = jump around. This generates real memory bus traffic that shows up in stats.

4. **Stats collection**: Background `ScheduledExecutorService` reading system metrics via `oshi` library (cross-platform: Linux + Windows). Collects CPU%, memory%, disk I/O rates, network I/O rates, per-process stats.

5. **File operations**: Read source files from `data/normal/` and `data/confidential/` directories (same files shipped with emulator package). Assemble content, write to output folders. ZIP via `java.util.zip`.

6. **Agent management**: `ProcessBuilder` to run `systemctl` (Linux) or `sc` (Windows) commands. Same known agent configs (CrowdStrike, SentinelOne, Carbon Black).

### Package structure:

```
emulator_java/
├── pom.xml (or build.gradle)
├── src/main/java/com/emulator/
│   ├── EmulatorApplication.java
│   ├── controller/
│   │   ├── HealthController.java
│   │   ├── ConfigController.java
│   │   ├── OperationsController.java
│   │   ├── TestsController.java
│   │   ├── StatsController.java
│   │   └── AgentController.java
│   ├── model/
│   │   ├── request/   (all request DTOs)
│   │   └── response/  (all response DTOs)
│   ├── service/
│   │   ├── MemoryPoolService.java
│   │   ├── CpuBurnService.java
│   │   ├── WorkService.java
│   │   ├── FileOperationService.java
│   │   ├── DiskOperationService.java
│   │   ├── NetworkOperationService.java
│   │   ├── StatsCollectorService.java
│   │   ├── TestManagerService.java
│   │   └── AgentService.java
│   └── config/
│       └── EmulatorConfig.java
├── src/main/resources/
│   └── application.yml
└── data/               (same source files as Python emulator)
    ├── normal/
    └── confidential/
```

### Deployment:

The Java emulator will be packaged as a fat JAR (Spring Boot). The deployment script needs to:
1. Upload the JAR + data files to the target server
2. Run `java -jar emulator.jar` (requires JRE 17+ on target)
3. The start script (`start.sh` / `start.ps1`) will change from launching `uvicorn` to launching `java -jar`

The orchestrator's `RemoteExecutor` uploads and runs the start script — so the orchestrator code doesn't need to know it's Java underneath.

---

## All Scripts Used During This Work

### Test scripts (in project root):

| Script | Purpose | Usage |
|--------|---------|-------|
| `test_emulator_endpoints.py` | Tests ALL emulator endpoints after deployment. Validates health, config, cpu, mem, disk, net, file ops, pool init/status/destroy, work ops. | `python test_emulator_endpoints.py [linux\|windows\|all]` |
| `test_steady_load.py` | Multi-threaded steady-state load test. Worker threads hammer `/operations/work`, observer thread polls `/stats/system` and prints CPU/MEM readings every 2 seconds. Prints summary with avg/min/max/p50/spread. | `python test_steady_load.py [host] [threads] [duration_sec] [cpu_ms]` |
| `test_emulator_deploy.py` | Tests emulator package deployment using same code as orchestrator (RemoteExecutor). Reverts to snapshot, deploys package, verifies. | `python test_emulator_deploy.py` |
| `deploy_windows_emulator.py` | Deploys emulator package specifically to Windows target. | `python deploy_windows_emulator.py` |

### Test script details:

**`test_emulator_endpoints.py`** — 15 sequential tests:
1. `GET /health`
2. `POST /config` (set output_folders, partner, stats)
3. `GET /config` (verify input_folders auto-detected)
4. `POST /operations/cpu` (500ms, intensity 0.5)
5. `POST /operations/mem` (500ms, 10MB, sequential)
6. `POST /operations/disk` (500ms, write, 10MB)
7. `POST /operations/net` (500ms, 1024 bytes, send)
8. `POST /operations/file` (normal)
9. `POST /operations/file` (confidential + zip)
10. Bulk file ops (5x, mixed formats)
11. `POST /config/pool` (1 GB init)
12. `GET /config/pool` (verify allocated)
13. `POST /operations/work` (10ms, intensity 0.8, 1MB touch)
14. Bulk work ops (10x rapid fire)
15. `DELETE /config/pool` (cleanup)

Tests against Linux at 10.0.0.92, Windows at 10.0.0.91.

**`test_steady_load.py`** — Concurrent load test:
- Spawns N worker threads, each calling `POST /operations/work` in tight loop
- Spawns 1 stats observer thread polling `GET /stats/system` every 2 seconds
- Runs for configurable duration, then prints:
  - Per-interval table: elapsed time, CPU%, MEM%, MEM_MB, ops_ok, ops_err
  - Stats summary: avg/min/max/spread/p50 CPU, percentage in 15-50% range
  - Load summary: total ops, ops/sec, ops/sec/thread
- Initializes pool before test, destroys after

### Orchestrator-side files modified:

| File | What changed |
|------|-------------|
| `orchestrator/src/orchestrator/models/enums.py` | `server_steady = "server-steady"` added to `TemplateType` |
| `orchestrator/src/orchestrator/services/sequence_generator.py` | Import `ServerSteadyOpsGenerator`, handler in `_create_generator()` |
| `db-assets/generator/generators/ops_sequence_generator.py` | `ServerSteadyOpsGenerator` class added |
| `orchestrator/artifacts/jmx/server-steady.jmx` | New JMX template (setUp pool init → CSV-driven work loop → tearDown pool destroy) |

### Emulator-side files modified/created:

| File | What changed |
|------|-------------|
| `emulator/app/operations/mem_pool.py` | NEW — MemoryPool class |
| `emulator/app/operations/work.py` | NEW — WorkExecutor class |
| `emulator/app/routers/config.py` | Added pool endpoints (POST/GET/DELETE /config/pool) |
| `emulator/app/routers/operations.py` | Added `/operations/work` endpoint |
| `emulator/app/models/requests.py` | Added `WorkOperationRequest` |

### Packages rebuilt:
- `orchestrator/artifacts/packages/emulator-linux.tar.gz`
- `orchestrator/artifacts/packages/emulator-windows.tar.gz`

---

## Summary of Issues Faced

| # | Issue | Root Cause | Resolution |
|---|-------|-----------|------------|
| 1 | DB INSERT failed on scenarios table | `created_at` is NOT NULL, wasn't provided | Added `GETDATE()` to INSERT |
| 2 | SQLAlchemy enum lookup failed | Inserted hyphenated value `server-steady` but SQLAlchemy maps by enum NAME (underscore `server_steady`) | UPDATE'd DB value to `server_steady` |
| 3 | Calibration timed out (Run 17) | 30 threads producing 0% CPU | Python GIL — see below |
| 4 | Calibration logs not visible | Orchestrator logging suppressed INFO level | No `logging.basicConfig(level=logging.INFO)` configured |
| 5 | CPU burn produces 0% CPU with threads | Python GIL serializes CPU-bound bytecode across threads | **Decision: rewrite emulator in Java** |
| 6 | Can't use ProcessPoolExecutor for work | Memory pool (bytearray) can't be shared across processes | Threads required for shared memory, but GIL kills CPU parallelism |
| 7 | Even cpu_ms=100 is spikey | GIL releases/acquires create uneven CPU distribution | 14.2% spread is too wide for calibration |

The fundamental problem: Python's threading model cannot produce steady, parallel CPU load from multiple threads. Java's threads are real OS threads with no GIL, making it the right choice for this workload.
