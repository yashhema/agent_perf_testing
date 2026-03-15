# Agent Performance Testing Framework — Architecture Document

## 1. System Overview

The framework measures the performance impact of security agents (EDR, AV, DLP) on servers by running controlled load tests before and after agent installation, then statistically comparing the results.

**Three deployment modes:**

| Mode | Description |
|------|-------------|
| `live_compare` | Two snapshots in one run (base → initial), side-by-side |
| `baseline_compare` → `new_baseline` | Run load on a clean snapshot, store stats as reference |
| `baseline_compare` → `compare` | Run load on agent-installed snapshot, compare against stored baseline |

**Three physical roles:**

| Role | What runs there |
|------|----------------|
| **Orchestrator** | FastAPI web app + state machine + DB (MSSQL). Controls everything. |
| **Target Server(s)** | Emulator (Spring Boot/Java 17). Receives load, collects system stats. |
| **Load Generator(s)** | JMeter. Drives HTTP requests to targets. |

> **Note:** The emulator was migrated from Python (FastAPI/uvicorn) to Java (Spring Boot 3.2.4).
> The Python emulator source remains in `emulator/` for reference but is no longer deployed.
> The active emulator source is `emulator_java/` — a Maven project producing `emulator.jar`.

---

## 2. Component File Map

### 2.1 Orchestrator

```
orchestrator/
├── config/
│   ├── orchestrator.yaml              # All tuning knobs (calibration, stats, barriers, DB)
│   └── credentials.json               # Server SSH/WinRM credentials
├── artifacts/
│   └── jmx/
│       ├── server-normal.jmx          # CSV-driven: cpu/mem/disk ops via SwitchController
│       ├── server-file-heavy.jmx      # File-heavy variant
│       ├── db-load.jmx                # Database load variant
│       └── server-steady.jmx          # NEW: single /work endpoint, pre-allocated pool
├── prerequisites/
│   ├── ubuntu/python_emulator.sh      # Legacy: Apt-based Python + pip deps
│   ├── rhel/python_emulator.sh        # Legacy: Dnf/yum-based Python + pip deps
│   └── windows_server/python_emulator.ps1  # Legacy: Windows Python installer + pip
│   # Note: Java emulator only requires JRE 17+ on targets (bundled or system)
│   # Startup scripts (start.sh/start.ps1) auto-detect JRE location
├── src/orchestrator/
│   ├── main.py                        # FastAPI app entry point
│   ├── config/
│   │   ├── settings.py                # AppConfig from orchestrator.yaml
│   │   └── credentials.py             # CredentialsStore
│   ├── models/
│   │   ├── enums.py                   # All enums (OSFamily, TemplateType, BaselineTestState, etc.)
│   │   └── orm.py                     # 15 SQLAlchemy ORM entities
│   ├── core/
│   │   ├── baseline_orchestrator.py   # State machine: created→validating→…→completed
│   │   ├── baseline_execution.py      # 5-phase barrier execution engine
│   │   ├── baseline_validation.py     # Pre-flight checks for baseline-compare
│   │   ├── calibration.py             # Binary search for thread_count
│   │   ├── validation.py              # Pre-flight checks for live-compare
│   │   └── execution.py              # Live-compare execution engine
│   ├── services/
│   │   ├── comparison.py              # Cohen's d statistical comparison
│   │   ├── stats_parser.py            # Stats JSON → MetricSummary/StatsSummary
│   │   ├── sequence_generator.py      # Generates ops_sequence CSV files
│   │   └── package_manager.py         # PackageResolver + PackageDeployer
│   ├── infra/
│   │   ├── jmeter_controller.py       # Start/stop JMeter via SSH/WinRM
│   │   ├── emulator_client.py         # HTTP client for emulator REST API
│   │   ├── remote_executor.py         # SSHExecutor / WinRMExecutor
│   │   └── hypervisor.py              # Proxmox/vSphere/Vultr snapshot ops
│   ├── api/
│   │   ├── baseline_test_runs.py      # POST/GET /api/baseline-tests, snapshots
│   │   ├── test_runs.py               # POST/GET /api/test-runs (live-compare)
│   │   ├── admin.py                   # CRUD for labs, servers, scenarios, etc.
│   │   ├── trending.py                # Cross-run trend analysis
│   │   ├── auth.py                    # JWT login
│   │   └── schemas.py                 # All Pydantic request/response models
│   └── web/
│       └── views.py                   # Jinja2 HTML views (dashboard, admin, results)
```

### 2.2 Emulator (Java — active)

```
emulator_java/
├── pom.xml                            # Maven build (Spring Boot 3.2.4, Java 17, oshi-core 6.5.0)
├── start.sh                           # Linux startup (firewall, kill old java, JVM heap sizing, nohup)
├── start.ps1                          # Windows startup (firewall, WMI process create, JVM heap sizing)
├── src/main/java/com/emulator/
│   ├── EmulatorApplication.java       # Spring Boot entry point
│   ├── config/
│   │   ├── JacksonConfig.java         # JavaTimeModule, ISO_INSTANT timestamps
│   │   └── WebConfig.java             # CORS allow-all
│   ├── controller/
│   │   ├── HealthController.java      # GET /health
│   │   ├── ConfigController.java      # GET/POST /api/v1/config, POST/GET/DELETE /api/v1/config/pool
│   │   ├── OperationsController.java  # POST /api/v1/operations/{cpu,mem,disk,net,file,suspicious,work}
│   │   ├── TestsController.java       # POST /api/v1/tests/start, GET /tests/{id}, POST /tests/{id}/stop
│   │   ├── StatsController.java       # GET /stats/system, /stats/recent, /stats/all, /stats/iterations
│   │   ├── AgentController.java       # Agent install/uninstall/service control
│   │   └── LogsController.java        # GET /api/v1/logs/download (tar.gz of *.log files)
│   ├── model/
│   │   ├── request/                   # CpuRequest, MemRequest, DiskRequest, NetRequest, WorkRequest, etc.
│   │   └── response/                  # OperationResult, FileOperationResult, PoolResponse, TestStatusResponse
│   ├── service/
│   │   ├── CpuBurnService.java        # Math.sin/sqrt/cos tight loops, real OS threads (no GIL)
│   │   ├── MemoryPoolService.java     # Pre-allocated byte[] pool, sequential/random page touch
│   │   ├── DiskOperationService.java  # RandomAccessFile I/O, fsync on write
│   │   ├── NetworkOperationService.java # Socket send/receive
│   │   ├── FileOperationService.java  # File create with size brackets, ZIP support
│   │   ├── SuspiciousOperationService.java # Platform-specific EDR-triggering activities
│   │   ├── AgentService.java          # Agent install/uninstall/service via OS commands
│   │   ├── ConfigService.java         # In-memory config with ReentrantLock
│   │   ├── TestManagerService.java    # Test lifecycle, starts/stops stats collection
│   │   └── StatsCollectorService.java # OSHI-based background stats (CPU, mem, disk, net, per-process)
│   └── util/
│       └── PlatformUtil.java          # OS detection (Windows vs Linux)
├── src/main/resources/
│   └── application.yml                # server.port=8080, jackson config
└── target/
    └── emulator.jar                   # Built fat jar (Spring Boot executable)
```

### 2.2.1 Emulator (Python — legacy, reference only)

```
emulator/
├── start.sh / start.ps1               # Legacy startup scripts
├── app/                               # FastAPI app (no longer deployed)
│   ├── main.py, config.py, routers/, operations/, services/, stats/
└── data/                              # DLP test files, normal files (still used — copied into Java packages)
```

### 2.3 Root-Level Scripts

```
agent_perf_testing/
├── run_baseline_test.py               # End-to-end: build jar → start orchestrator → create test → poll → verdict
├── run_baseline_test.sh               # Legacy shell wrapper (deprecated)
├── test_calibration.sh                # Standalone calibration test
├── test_emulator_cpu.sh               # Quick CPU load test with JMeter
├── check_win.py                       # WinRM connectivity check
├── deploy_windows_emulator.py         # Deploy emulator to Windows via WinRM
└── deploy_win_emu.py                  # Full Windows deploy with prerequisites
```

---

## 3. Database Tables (ORM Entities)

All tables live in the `orchestrator` database (MSSQL, trusted connection).

### 3.1 Configuration Tables

| Table | ORM Class | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `labs` | `LabORM` | Lab environment | name, hypervisor_type, jmeter_package_grp_id, emulator_package_grp_id, loadgen_snapshot_id |
| `hardware_profiles` | `HardwareProfileORM` | Server hardware specs | cpu_count, memory_gb, disk_type, disk_size_gb, nic_speed_gbps |
| `servers` | `ServerORM` | All machines (targets, loadgens, orchestrator) | hostname, ip_address, os_family, os_version, lab_id, default_loadgen_id, default_partner_id, server_infra_ref |
| `baselines` | `BaselineORM` | Snapshot metadata | name, os_family, os_version, kernel_version, db_type |
| `package_groups` | `PackageGroupORM` | Installable package groups | name, agent_type, vendor |
| `package_group_members` | `PackageGroupMemberORM` | Per-OS package details | package_group_id, os_match_string, package_path, install_command, run_command |
| `scenarios` | `ScenarioORM` | Test scenario config | name, lab_id, template_type, package_group_ids (JSON), stress_*, network_degradation_* |
| `load_profiles` | `LoadProfileORM` | Load level definitions | name, target_cpu_min_pct, target_cpu_max_pct, ramp_up_sec, duration_sec |
| `db_schema_configs` | `DBSchemaConfigORM` | DB schema generation config | schema_name, table_count, etc. |

### 3.2 Test Execution Tables (live_compare)

| Table | ORM Class | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `test_runs` | `TestRunORM` | Test execution state | state, run_mode, scenario_id, current_load_profile_id, verdict |
| `test_run_targets` | `TestRunTargetORM` | Per-target config | test_run_id, server_id, loadgen_id, base_snapshot_id, initial_snapshot_id |
| `test_run_load_profiles` | `TestRunLoadProfileORM` | LPs linked to run | test_run_id, load_profile_id |
| `calibration_results` | `CalibrationResultORM` | Calibrated thread counts | test_run_id, server_id, load_profile_id, thread_count, phase, current_iteration, last_observed_cpu_pct |
| `phase_execution_results` | `PhaseExecutionResultORM` | Execution stats paths | test_run_id, server_id, load_profile_id, phase (base/initial), status, stats_path, jtl_path |
| `comparison_results` | `ComparisonResultORM` | Statistical comparison | test_run_id, server_id, load_profile_id, verdict, violation_count, details_json |

### 3.3 Baseline-Compare Tables

| Table | ORM Class | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `baseline_test_runs` | `BaselineTestRunORM` | Baseline test state | test_type (new_baseline/compare/compare_with_new_calibration), state, scenario_id, current_load_profile_id |
| `baseline_test_targets` | `BaselineTestTargetORM` | Targets in baseline test | baseline_test_id, server_id, loadgen_id, test_snapshot_id, compare_snapshot_id, partner_id, output_folders, service_monitor_patterns |
| `snapshots` | `SnapshotORM` | Snapshot registry | server_id, name, provider_ref, parent_snapshot_id |
| `snapshot_profile_data` | `SnapshotProfileDataORM` | Stored baseline data per (snapshot, LP) | snapshot_id, load_profile_id, thread_count, stats_path, jtl_path, jmx_test_case_data_path, stats_summary_json |

---

## 4. Complete Test Flow (Baseline-Compare Mode)

### 4.1 State Machine

```
created → validating → setting_up → calibrating → generating → executing → storing → completed
                                                                    ↓
                                                              comparing (for compare types)
                                                                    ↓
                                                                completed
```

On any error: → `failed`
On user cancel: → `cancelled`

State tracked in: `baseline_test_runs.state` (`BaselineTestState` enum)

### 4.2 Step-by-Step Flow

#### Step 1: Test Creation
**API:** `POST /api/baseline-tests`
**File:** `orchestrator/src/orchestrator/api/baseline_test_runs.py`

User provides:
- `scenario_id` → links to lab, template_type, packages
- `test_type` → new_baseline | compare | compare_with_new_calibration
- `targets[]` → each with server_id, test_snapshot_id, compare_snapshot_id (for compare types)
- `load_profile_ids[]` → which load levels to test

Creates rows in: `baseline_test_runs`, `baseline_test_targets`

#### Step 2: Validation (`validating`)
**File:** `orchestrator/src/orchestrator/core/baseline_validation.py`
**Class:** `BaselinePreFlightValidator`

Checks:
1. Server reachable (SSH port 22 or WinRM port 5985)
2. Emulator health (soft check, may not be running yet)
3. Snapshot exists on hypervisor
4. Snapshot hierarchy valid (test_snapshot descends from compare_snapshot)
5. Stored data exists for compare_snapshot (for compare types) — reads `snapshot_profile_data`

#### Step 3: Setup (`setting_up`)
**File:** `orchestrator/src/orchestrator/core/baseline_orchestrator.py` → `_do_setup()`

For each target:
1. **Restore snapshot** via hypervisor API (`hypervisor.restore_snapshot()`)
2. **Wait for VM ready** (`hypervisor.wait_for_vm_ready()`)
3. **Wait for SSH/WinRM** (`wait_for_ssh()` — polls port 22 or 5985)
4. **Update IP** if changed after restore
5. **Deploy emulator** if `lab.emulator_package_grp_id` is set:
   - `PackageResolver.resolve()` → finds OS-matched package
   - `PackageDeployer.deploy_all()` → uploads + runs install_command
   - Runs `run_command` (starts emulator)
6. **Deploy JMeter** to loadgen:
   - Similar package resolution for `lab.jmeter_package_grp_id`
7. **Upload JMX template** to loadgen:
   - Source: `orchestrator/artifacts/jmx/{scenario.template_type.value}.jmx`
   - Dest: `/opt/jmeter/runs/baseline_{test_id}/lg_{lg_id}/target_{srv_id}/test.jmx`
8. **Discover** OS version, agent info on target

#### Step 4: Calibration (`calibrating`)
**File:** `orchestrator/src/orchestrator/core/calibration.py`
**Class:** `CalibrationEngine`
**Config:** `orchestrator.yaml` → calibration section

For each (target, load_profile):

**Phase A — Binary Search:**
1. Set search range: `low=1`, `high=max_thread_count` (default 30)
2. Pick `mid = (low + high) // 2`
3. Start emulator stats collection (`em_client.start_test()`)
4. Start JMeter with `mid` threads for `observation_duration_sec` (30s)
5. Wait, then poll `em_client.get_recent_stats()` → average CPU%
6. Stop JMeter, stop emulator test
7. If CPU < target_min → `low = mid + 1`; if CPU > target_max → `high = mid - 1`; if in range → found
8. Update `calibration_results` row: phase, current_iteration, last_observed_cpu_pct, message
9. Repeat until converged or `low > high`

**Phase B — Stability Verification:**
1. Run with found thread_count for `observation_duration_sec * stability_ratio` (15s)
2. Collect multiple readings
3. Check: ≥ `stability_min_in_range_pct` (55%) of readings in target range
4. Check: ≤ `stability_max_below_pct` (10%) of readings below range
5. If unstable, decrement thread_count by 1 and retry (up to `confirmation_count` times)

Result stored in: `calibration_results.thread_count`

**Calibration skipped** for `compare` test type (reuses `snapshot_profile_data.thread_count` from compare_snapshot).

#### Step 5: Sequence Generation (`generating`)
**File:** `orchestrator/src/orchestrator/services/sequence_generator.py`
**Class:** `SequenceGenerationService`

For each (target, load_profile):
1. Look up `thread_count` from calibration results
2. Select generator by `scenario.template_type`:
   - `server_normal` → `ServerNormalOpsGenerator` → CSV with columns: `op_type,cpu_ms,intensity,mem_mb,...`
   - `server_file_heavy` → `ServerFileHeavyOpsGenerator`
   - `db_load` → `DbLoadOpsGenerator`
3. Generate CSV to: `config.generated_dir/baseline_{test_id}/srv_{srv_id}/lp_{lp_id}_ops_sequence.csv`
4. Upload CSV to loadgen: `/opt/jmeter/runs/baseline_{test_id}/lg_{lg_id}/target_{srv_id}/ops_sequence.csv`

#### Step 6: Execution (`executing`)
**File:** `orchestrator/src/orchestrator/core/baseline_execution.py`
**Class:** `BaselineExecutionEngine`

Executes with **barrier pattern** — all targets synchronized per phase:

```
For each load_profile:
  ┌─ Phase 1: RESTORE all targets to snapshot ─────────────────────┐
  │   hypervisor.restore_snapshot() + wait_for_vm_ready()          │
  │   wait_for_ssh()                                               │
  └─── BARRIER: all targets restored ─────────────────────────────┘

  ┌─ Phase 2: CONFIGURE all targets ──────────────────────────────┐
  │   For each target:                                             │
  │     • Deploy emulator if needed                                │
  │     • Clean emulator output/stats dirs                         │
  │     • EmulatorClient.set_config(output_folders, partner, stats) │
  │     • EmulatorClient.start_test(test_run_id, scenario, mode,   │
  │       collect_interval_sec, thread_count, duration_sec)        │
  │     • Prepare loadgen executor + JMeterController              │
  └─── BARRIER: all targets configured, stats collecting ─────────┘

  ┌─ Phase 3: START JMETER on all targets ────────────────────────┐
  │   jmeter_ctrl.start(jmx_path, jtl_path, log_path,            │
  │     thread_count, ramp_up_sec, duration_sec,                  │
  │     target_host, target_port, ops_sequence_path)              │
  └─── BARRIER: all JMeter instances running ─────────────────────┘

  ┌─ Phase 4: WAIT ───────────────────────────────────────────────┐
  │   total_wait = duration + ramp_up + (duration * margin_pct)    │
  │   time.sleep(total_wait)                                       │
  └─── BARRIER: test duration complete ───────────────────────────┘

  ┌─ Phase 5: COLLECT from all targets ───────────────────────────┐
  │   For each target:                                             │
  │     • jmeter_ctrl.stop(pid)                                    │
  │     • em_client.stop_test(test_id)                             │
  │     • em_client.get_all_stats() → JSON                         │
  │     • Save stats to: results/{test_id}/server_{srv_id}/stats/  │
  │     • Download JTL from loadgen                                │
  │     • StatsParser.trim_samples() + compute_summary()           │
  │     • Download ops_sequence CSV from loadgen                   │
  └───────────────────────────────────────────────────────────────┘
```

**Results stored on disk:**
```
results/{test_id}/server_{srv_id}/
├── stats/lp{lp_id}_stats.json        # Full stats from emulator
├── jtl/lp{lp_id}.jtl                 # JMeter transaction log
└── jmx_data/lp{lp_id}_ops_sequence.csv  # The CSV that drove the test
```

#### Step 7: Storing (`storing`) — new_baseline only
**File:** `orchestrator/src/orchestrator/core/baseline_orchestrator.py` → `_do_storing()`

For each (target, load_profile), creates a `snapshot_profile_data` row:
- `snapshot_id` = test_snapshot_id
- `load_profile_id` = lp.id
- `thread_count` = calibrated thread count
- `stats_path` = path to stats JSON on disk
- `jtl_path` = path to JTL on disk
- `jmx_test_case_data_path` = path to ops_sequence CSV
- `stats_summary_json` = computed summary (avg, p50, p90, p95, p99 for all metrics)

This stored data becomes the baseline reference for future `compare` runs.

#### Step 8: Comparison (`comparing`) — compare types only
**File:** `orchestrator/src/orchestrator/services/comparison.py`
**Method:** `run_baseline_comparison()`

1. Load **test stats** from execution results
2. Load **baseline stats** from `snapshot_profile_data` (compare_snapshot)
3. Trim warmup/cooldown from both (`trim_start_sec=30`, `trim_end_sec=10`)
4. Compute per-metric summaries for both
5. **Cohen's d** effect size for each metric:
   - `d = (mean_test - mean_baseline) / pooled_stddev`
   - Thresholds from agent analysis rules
6. Per-metric verdict: passed / warning / failed
7. Overall verdict: worst metric determines result
8. Store in `comparison_results` table (for live_compare) or inline in baseline test state

**7 system metrics compared:**
- `cpu_percent`, `memory_percent`, `memory_used_mb`
- `disk_read_rate_mbps`, `disk_write_rate_mbps`
- `network_sent_rate_mbps`, `network_recv_rate_mbps`

---

## 5. Stats Collection & Format

### 5.1 Collection
**File:** `emulator_java/src/main/java/com/emulator/service/StatsCollectorService.java`

- ScheduledExecutorService background thread collects at `collect_interval_sec` (configurable, default 1s)
- CPU% calculated via OSHI `getSystemCpuLoadBetweenTicks()` (cross-platform, no /proc/stat parsing needed)
- Each sample: timestamp, elapsed_sec, cpu_percent, memory_percent, memory_used_mb, memory_available_mb, disk_read/write bytes + rates, network sent/recv bytes + rates
- Per-process monitoring via OSHI `getProcessCpuLoadBetweenTicks()` for configured `service_monitor_patterns` (regex)
- Saves stats JSON to disk on test stop; file lookup by test_run_id for `/stats/all` endpoint

### 5.2 Stats JSON Format

```json
{
  "metadata": {
    "test_run_id": "16",
    "scenario_id": "Proxmox Baseline Compare",
    "start_time": "2025-03-11T10:30:00Z",
    "end_time": "2025-03-11T10:32:00Z",
    "duration_sec": 120,
    "collect_interval_sec": 5
  },
  "samples": [
    {
      "timestamp": "2025-03-11T10:30:05Z",
      "cpu_percent": 23.5,
      "memory_percent": 45.2,
      "memory_used_mb": 1845.3,
      "disk_read_rate_mbps": 0.5,
      "disk_write_rate_mbps": 1.2,
      "network_sent_rate_mbps": 0.1,
      "network_recv_rate_mbps": 0.3,
      "per_process": {}
    }
  ],
  "summary": {
    "cpu_percent": {"avg": 15.2, "min": 0.0, "max": 45.3, "p50": 12.1, "p90": 35.2, "p95": 40.1, "p99": 44.8},
    "memory_percent": { ... },
    ...
  }
}
```

### 5.3 Stats Trimming
**File:** `orchestrator/src/orchestrator/services/stats_parser.py`
- `trim_start_sec=30` — removes ramp-up warmup samples
- `trim_end_sec=10` — removes cooldown samples
- Only trimmed samples used for comparison

---

## 6. JMX Template Mechanism

### 6.1 Template Selection

The scenario's `template_type` column (varchar, values from `TemplateType` enum) determines which JMX file is used:

| template_type | JMX File | Generator |
|---------------|----------|-----------|
| `server-normal` | `server-normal.jmx` | `ServerNormalOpsGenerator` |
| `server-file-heavy` | `server-file-heavy.jmx` | `ServerFileHeavyOpsGenerator` |
| `db-load` | `db-load.jmx` | `DbLoadOpsGenerator` |

**Selection code** in `baseline_orchestrator.py` → `_do_setup()`:
```python
jmx_src = config.artifacts_dir / "jmx" / f"{scenario.template_type.value}.jmx"
```

### 6.2 Current Template: server-normal.jmx

**Structure:**
1. **CSV Data Set Config** reads `ops_sequence.csv` (column: `op_type`)
2. **SwitchController** dispatches by `${op_type}`:
   - `0` → POST `/api/v1/operations/cpu` (500ms, 0.8 intensity)
   - `1` → POST `/api/v1/operations/mem` (500ms, 10MB, random)
   - `2` → POST `/api/v1/operations/disk` (500ms, mixed, 10MB, 64KB blocks)
3. **Thread Group** with `${THREAD_COUNT}` threads, `${RAMP_UP_SEC}` ramp, `${DURATION_SEC}` duration

**JMeter properties passed via -J flags:**
- `threads`, `rampup`, `duration`, `host`, `port`, `ops_sequence`

**Problem:** Each 500ms operation causes CPU/memory spikes followed by idle periods. With 5-second stat intervals, readings swing 0-45%.

### 6.3 New Template: server-steady.jmx

**Structure:**
1. **setUp Thread Group** → POST `/api/v1/config/pool` with `{"size_gb": ${pool_gb}}`
2. **Main Thread Group** → continuous POST `/api/v1/operations/work` with:
   ```json
   {"cpu_ms": ${CPU_MS}, "intensity": ${INTENSITY}, "touch_mb": ${TOUCH_MB}, "touch_pattern": "random"}
   ```
3. No CSV, no SwitchController — every iteration is identical

**JMeter properties:** `threads`, `rampup`, `duration`, `host`, `port`, `pool_gb`, `cpu_ms`, `intensity`, `touch_mb`

**Why steadier:** Short 5-10ms CPU burns + memory pool touches (no alloc/dealloc) → near-constant load profile.

---

## 7. Emulator API Endpoints

| Method | Path | Purpose | Used By |
|--------|------|---------|---------|
| GET | `/health` | Health check | Orchestrator validation, scripts |
| GET | `/api/v1/config` | Get config | — |
| POST | `/api/v1/config` | Set config (output folders, partner, stats) | Orchestrator setup |
| POST | `/api/v1/config/pool` | Allocate memory pool | server-steady.jmx setUp |
| GET | `/api/v1/config/pool` | Pool status | — |
| DELETE | `/api/v1/config/pool` | Destroy pool | — |
| POST | `/api/v1/operations/cpu` | CPU burn | server-normal.jmx |
| POST | `/api/v1/operations/mem` | Memory alloc/touch | server-normal.jmx |
| POST | `/api/v1/operations/disk` | Disk I/O | server-normal.jmx |
| POST | `/api/v1/operations/net` | Network I/O | server-normal.jmx |
| POST | `/api/v1/operations/file` | File operations | server-file-heavy.jmx |
| POST | `/api/v1/operations/suspicious` | EDR-triggering ops | — |
| POST | `/api/v1/operations/work` | Combined cpu+mem (steady) | server-steady.jmx |
| POST | `/api/v1/tests/start` | Start stats collection | Orchestrator execution |
| POST | `/api/v1/tests/{id}/stop` | Stop stats collection | Orchestrator execution |
| GET | `/api/v1/stats/recent` | Recent samples (calibration polling) | Orchestrator calibration |
| GET | `/api/v1/stats/all` | All stats JSON | Orchestrator collection |
| GET | `/api/v1/stats/system` | Current system snapshot | — |
| GET | `/api/v1/stats/iterations` | Iteration timing stats | — |
| POST | `/api/v1/stats/iterations/clear` | Clear iteration timing | — |
| GET | `/api/v1/logs/download` | Download tar.gz of all *.log files | Orchestrator log collection |
| GET | `/api/v1/agent/{type}` | Agent info | Orchestrator discovery |
| POST | `/api/v1/agent/install` | Install agent | Orchestrator setup |
| POST | `/api/v1/agent/uninstall` | Uninstall agent | — |
| POST | `/api/v1/agent/service` | Start/stop/restart agent | Orchestrator control |

---

## 8. Key Configuration (orchestrator.yaml)

```yaml
calibration:
  observation_duration_sec: 30       # Duration of each calibration probe
  observation_reading_count: 20      # Stats readings to average
  stability_ratio: 0.5               # Stability run = observation * ratio
  confirmation_count: 2              # Max stability retries
  max_thread_count: 30               # Binary search upper bound
  stability_min_in_range_pct: 55     # % readings that must be in target range
  stability_max_below_pct: 10        # Max % readings allowed below range

stats:
  collect_interval_sec: 5            # Emulator stats polling interval
  stats_trim_start_sec: 30           # Trim warmup from stats
  stats_trim_end_sec: 10             # Trim cooldown from stats

barrier:
  barrier_timeout_margin_percent: 0.20  # Extra wait after duration expires

emulator:
  emulator_api_port: 8080            # Emulator listening port
```

---

## 9. Integration Points for server-steady Template

To add `server-steady` as a usable template type, the following touchpoints need changes:

### 9.1 Already Created (emulator side — Java)
- `emulator_java/.../service/MemoryPoolService.java` — pre-allocated byte[] pool with sequential/random touch
- `emulator_java/.../service/CpuBurnService.java` — real OS thread CPU burn (no GIL), Math.sin/sqrt/cos loops
- `emulator_java/.../model/request/WorkRequest.java` — WorkOperationRequest model
- `emulator_java/.../controller/OperationsController.java` — `POST /work` endpoint
- `emulator_java/.../controller/ConfigController.java` — `POST/GET/DELETE /pool` endpoints
- `orchestrator/artifacts/jmx/server-steady.jmx` — streamlined JMX template

### 9.2 Required Changes (orchestrator side)

| File | Change | Notes |
|------|--------|-------|
| `models/enums.py` | Add `server_steady = "server-steady"` to `TemplateType` | Allows DB column value |
| `services/sequence_generator.py` | Handle `server_steady` → skip CSV generation | No ops_sequence needed |
| `core/baseline_orchestrator.py` → `_do_setup()` | Pass `extra_properties` (pool_gb, cpu_ms, etc.) when template is server-steady | JMeter needs -J flags |
| `core/baseline_orchestrator.py` → `_do_generation()` | Skip generation for server-steady | No CSV to generate |
| `core/baseline_execution.py` → Phase 3 | Pass `extra_properties` for pool/CPU params; `ops_sequence_path=None` | Already Optional |
| `core/baseline_execution.py` → Phase 5 | Skip CSV download when no ops_sequence | Conditional on template |
| `api/schemas.py` | Add `server-steady` to template_type validation | If enum-validated |
| DB: `scenarios` table | `UPDATE scenarios SET template_type='server-steady' WHERE id=<new>` or update existing | varchar column, no constraint |

### 9.3 No Changes Needed
- `calibration.py` — already works with any JMX; just passes thread_count
- `comparison.py` — compares stats JSON regardless of how load was generated
- `stats_parser.py` — template-agnostic
- `emulator_client.py` — already has all needed methods
- `jmeter_controller.py` — already supports `extra_properties` dict and `ops_sequence_path=None`

---

## 9.4 Java Emulator Build & Deploy Pipeline

The `run_baseline_test.py` script handles the full lifecycle:

1. **Build** (`build_emulator_packages()`):
   - Sets `JAVA_HOME=C:\jdk-17.0.18.8-hotspot` for Maven
   - Runs `mvn package -DskipTests -q` in `emulator_java/`
   - Produces `emulator_java/target/emulator.jar`
   - Creates `emulator-java-linux.tar.gz` and `emulator-java-windows.tar.gz` in `orchestrator/artifacts/packages/`
   - Each tar.gz contains: `emulator.jar`, `start.sh`/`start.ps1`, and `data/` (from `emulator/data/`)

2. **Deploy** (orchestrator `_do_setup()` via `PackageDeployer`):
   - Uploads tar.gz to target via SSH/WinRM
   - Extracts to `/opt/emulator/` (Linux) or `C:\emulator\` (Windows)
   - Runs `start.sh` / `start.ps1` which:
     - Opens firewall port 8080
     - Kills existing Java process on 8080
     - Detects JRE (bundled `jre/` or system PATH)
     - Calculates JVM heap: `total_ram - 2GB` (min 1GB)
     - Launches `java -jar emulator.jar` with nohup (Linux) or WMI Create (Windows)
     - Health-checks `/health` (30s timeout)

3. **Key differences from Python emulator deployment:**
   - No Python/pip prerequisites needed on targets — only JRE 17+
   - Single fat jar vs Python venv with pip dependencies
   - Real OS threads (no GIL) — CPU burn accuracy is inherently better
   - OSHI library for cross-platform stats (replaces psutil + /proc/stat parsing)

---

## 10. Current Test Runs (from DB)

Latest baseline test runs (Run 16 most recent completed):

| Run ID | Test Type | State | Scenario | Targets |
|--------|-----------|-------|----------|---------|
| 16 | compare | completed | Proxmox Baseline Compare | Server 8 (Linux) |
| 14 | new_baseline | completed | Proxmox Baseline Compare | Server 8 |
| 13 | new_baseline | completed | Proxmox Baseline Compare | Server 8 |

- **Run 13**: new_baseline → stored stats as reference (snapshot 3: clean-rocky-baseline)
- **Run 16**: compare → compared against Run 13's stored data
- Load profile 1 ("low"): target 15-50% CPU, ramp=15s, duration=120s
- Calibrated thread_count=2 for both
- Current template: `server-normal` with CSV-driven ops

### Observed Stats Behavior (Run 16)
- 2 threads, 500ms operations, 5s stat intervals
- CPU swings: 0% → 45% → 12% → 0% → 38% (high variance)
- Only ~25 of 58 samples show active load
- Root cause: long operation bursts (500ms) with gaps between requests

### Expected Behavior with server-steady
- 2 threads, 5-10ms operations, continuous loop
- ~200 operations/sec per thread vs ~2 ops/sec currently
- CPU should stay near-constant within each 5s sample window
- No memory allocation spikes (pool pre-allocated)
