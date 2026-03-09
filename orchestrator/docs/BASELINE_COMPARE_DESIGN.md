# Baseline Compare Mode — Design Document

## 1. Overview

Baseline Compare is a testing mode designed for on-premise environments (vSphere, Proxmox) where VMs can be snapshotted. Instead of creating temporary VMs (like the live_compare Vultr mode), it uses VM snapshots to create reproducible test baselines and compare agent impact against stored reference data.

## 2. Key Concepts

### Execution Modes

The system supports two execution modes, configured per lab:

| Mode | Infrastructure | How base/initial is achieved |
|------|---------------|-------------------------------|
| `live_compare` | Cloud (Vultr) | Create 2 VMs, test in parallel |
| `baseline_compare` | On-premise (vSphere/Proxmox) | Use VM snapshots, test sequentially |

### Three Test Types

| Test Type | Purpose | Calibration | Comparison |
|-----------|---------|-------------|------------|
| `new_baseline` | Create initial reference data | Yes (binary search for thread count) | No |
| `compare` | Test agent impact using stored calibration | No (reuse baseline's thread count) | Yes (against stored baseline) |
| `compare_with_new_calibration` | Re-calibrate then compare | Yes (fresh calibration) | Yes (against stored baseline) |

### Snapshot Hierarchy

Snapshots form a tree (parent-child) matching the hypervisor's snapshot tree:

```
Clean Install (root)
  +-- Base OS Configured
       +-- Clean Baseline [baseline] [has data]      <-- compare_snapshot
       +-- With AgentX v2.1                          <-- test_snapshot
       +-- With AgentY v1.0                          <-- test_snapshot
```

Each snapshot can store **profile data** (calibrated thread counts, stats files, JTL files, JMX CSVs) per load profile, making it a reusable baseline.

## 3. Data Model

### SnapshotORM

| Field | Type | Description |
|-------|------|-------------|
| id | PK | Database ID |
| server_id | FK | Which server |
| name | String | User-friendly name |
| provider_snapshot_id | String | Hypervisor-specific unique ID (vSphere MoRef, Proxmox name) |
| parent_id | FK (self) | Parent snapshot for tree structure |
| is_baseline | Boolean | Marked as baseline (has stored data) |
| is_archived | Boolean | Soft-deleted |
| provider_ref | JSON | Hypervisor reference data |

**Unique constraint:** `(server_id, provider_snapshot_id)` — vSphere allows duplicate names, MoRef ID is the true key.

### SnapshotProfileDataORM

Stores calibration and test results per snapshot per load profile:

| Field | Type | Description |
|-------|------|-------------|
| snapshot_id | FK | Which snapshot owns this data |
| load_profile_id | FK | Which load profile |
| thread_count | Integer | Calibrated thread count |
| stats_data | String | Path to stats.csv |
| jtl_data | String | Path to JTL results |
| jmx_test_case_data | String | Path to generated JMX CSV |
| stats_summary | JSON | Summary statistics |
| source_snapshot_id | FK | If copied from another snapshot |

### BaselineTestRunORM

| Field | Type | Description |
|-------|------|-------------|
| id | PK | Test run ID |
| server_id | FK | Target server |
| scenario_id | FK | Test scenario |
| test_type | Enum | new_baseline / compare / compare_with_new_calibration |
| test_snapshot_id | FK | VM restores to this before test |
| compare_snapshot_id | FK | Baseline to compare against (null for new_baseline) |
| state | Enum | Current execution state |
| verdict | Enum | passed / failed / warning / pending |

## 4. State Machine

### State Flow by Test Type

**new_baseline:**
```
created -> validating -> setting_up -> calibrating -> generating -> executing -> storing -> completed
```

**compare:**
```
created -> validating -> setting_up -> executing -> comparing -> storing -> completed
```

**compare_with_new_calibration:**
```
created -> validating -> setting_up -> calibrating -> generating -> executing -> comparing -> storing -> completed
```

### State Descriptions

| State | What happens |
|-------|-------------|
| `created` | Test run created, waiting for user to start |
| `validating` | Pre-flight checks (lab mode, server access, snapshot existence) |
| `setting_up` | Restore VM to snapshot, deploy emulator, discover OS/agents |
| `calibrating` | Binary search for thread count that achieves target CPU% |
| `generating` | Generate operation sequence CSVs from calibrated thread counts |
| `executing` | Run JMeter tests, collect stats and JTL data |
| `comparing` | Compare execution results against stored baseline |
| `storing` | Save results to SnapshotProfileDataORM |
| `completed` | Success — results available |
| `failed` | Error occurred — error_message has details |
| `cancelled` | User cancelled the test |

## 5. Comparison Methodology

See [COMPARISON_METHODOLOGY.md](COMPARISON_METHODOLOGY.md) for the full comparison approach.

**Summary:**
- Primary metric: **System stats** (CPU%, memory%, disk IO, network IO) — per-second samples
- Effect size: **Cohen's d** — normalized measure of distribution shift
- Per-process metrics: Track agent-specific processes (CPU% and memory per process)
- JTL response times: **Not used in comparison** (dominated by test configuration, not agent impact)
- JTL throughput + error rate: Shown as informational metrics
- Results: Cohen's d matrix (rows = metrics, columns = test type x load profile) with percentile detail on click

## 6. API Endpoints

### Baseline Test Runs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/baseline-tests` | Create test run |
| GET | `/api/baseline-tests` | List test runs (filter by server_id, state) |
| GET | `/api/baseline-tests/{id}` | Get single test run |
| POST | `/api/baseline-tests/{id}/start` | Begin execution (background thread) |
| POST | `/api/baseline-tests/{id}/cancel` | Cancel execution |
| GET | `/api/baseline-tests/{id}/comparison-results` | Get comparison results |

### Snapshot Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/servers/{id}/snapshots` | List all snapshots for server |
| GET | `/api/servers/{id}/snapshots/tree` | Get snapshot tree hierarchy |
| POST | `/api/servers/{id}/snapshots/sync` | Sync snapshots from hypervisor |
| POST | `/api/servers/{id}/snapshots/take` | Create new snapshot |
| POST | `/api/servers/{id}/snapshots/delete` | Archive snapshot |
| POST | `/api/servers/{id}/snapshots/{snap_id}/revert` | Revert VM to snapshot |
| GET | `/api/servers/{id}/snapshots/{snap_id}/profile-data` | Get stored baseline data |

## 7. UI Pages

| Page | Route | Purpose |
|------|-------|---------|
| Snapshot Manager | `/snapshots` | Manage VM snapshots, sync with hypervisor |
| Baseline Test List | `/baseline-tests` | Browse all baseline test runs |
| Create Wizard | `/baseline-tests/create` | 5-step wizard to configure and create a test |
| Dashboard | `/baseline-tests/{id}/dashboard` | Live monitoring during execution |
| Results | `/baseline-tests/{id}/results` | Cohen's d matrix + percentile detail |

### Results Page Layout

**Table 1 — Cohen's d Matrix:**
- Rows: system metrics (CPU%, memory%, disk read/write, net sent/recv) + per-process metrics
- Columns: test type x load profile combinations
- Cells: Cohen's d value, color-coded (green < 0.2, yellow 0.2-0.5, orange 0.5-0.8, red >= 0.8)
- Legend below table

**Table 2 — Percentile Detail (on cell click):**
- Shows base vs initial breakdown: Avg, P50, P90, P95, P99, StdDev
- Delta row with absolute differences
- Sample counts

## 8. vSphere Snapshot Identification

vSphere allows duplicate snapshot names on the same VM. The system uses `provider_snapshot_id` (the MoRef integer ID) as the unique identifier:

- **vSphere:** `provider_snapshot_id` = MoRef ID (e.g., "3"), `provider_ref` = `{"snapshot_name": "...", "snapshot_moref_id": "3"}`
- **Proxmox:** `provider_snapshot_id` = snapshot name (names are unique per VM in Proxmox)
- **Vultr:** `provider_snapshot_id` = UUID

All snapshot operations (restore, delete, exists check) resolve by `provider_snapshot_id` first, falling back to name-based lookup.

## 9. JMeter Test Plan Labels

Sampler labels in JTL files identify which emulator endpoint was exercised:

| Label | Endpoint | JMX File |
|-------|----------|----------|
| `CPU Burn` | `/api/v1/operations/cpu` | server-normal, server-file-heavy |
| `Memory Alloc` | `/api/v1/operations/mem` | server-normal, server-file-heavy |
| `Disk Mixed IO` | `/api/v1/operations/disk` | server-normal |
| `File Create` | `/api/v1/operations/file` | server-file-heavy |
| `CPU Spike` | `/api/v1/operations/cpu` (5s, intensity 1.0) | server-file-heavy |
| `Suspicious - {activity_type}` | `/api/v1/operations/suspicious` | server-stress |

## 10. File Structure

```
orchestrator/
  src/orchestrator/
    models/
      orm.py                  # SnapshotORM, SnapshotProfileDataORM, BaselineTestRunORM
      enums.py                # BaselineTestState, BaselineTestType, ExecutionMode
    core/
      baseline_orchestrator.py # State machine and orchestration logic
    api/
      baseline_test_runs.py   # REST endpoints
    services/
      snapshot_manager.py     # Snapshot sync, tree management
      comparison.py           # ComparisonEngine with Cohen's d
      statistical_tests.py    # Cohen's d implementation
    templates/
      snapshots/
        manager.html          # Snapshot tree + detail + profile data
      baseline_tests/
        list.html             # Browse test runs
        create.html           # 5-step creation wizard
        dashboard.html        # Live execution monitoring
        results.html          # Cohen's d matrix + detail
  artifacts/jmx/
    server-normal.jmx        # Normal load test (CPU Burn, Memory Alloc, Disk Mixed IO)
    server-file-heavy.jmx    # File-heavy test (CPU Burn, Memory Alloc, File Create, CPU Spike)
    server-stress.jmx        # Suspicious activities (Suspicious - {type})
  migrations/
    add_baseline_compare_tables.sql
    add_snapshot_provider_id.sql
```
