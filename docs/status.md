# Baseline-Compare Multi-Server — Implementation Status

## Date: 2026-03-09

---

## 1. What Was Done

### 1.1 Design
- Created `BASELINE_MULTI_SERVER_DESIGN.md` — full architecture for multi-target baseline-compare

### 1.2 Database
- **Created** `baseline_test_run_targets` table with per-target fields (target_id, loadgenerator_id, partner_id, test_snapshot_id, compare_snapshot_id, service_monitor_patterns, os_kind, os_major_ver, os_minor_ver, agent_versions)
- **Migrated** 2 existing test runs into the targets table
- **Dropped** per-server columns from `baseline_test_runs` (server_id, test_snapshot_id, compare_snapshot_id, loadgenerator_id, partner_id, service_monitor_patterns, os_kind, os_major_ver, os_minor_ver, agent_versions, batch_id)
- **Migration file**: `migrations/add_baseline_test_run_targets.sql`

### 1.3 Code Changes

| File | Change |
|------|--------|
| `models/orm.py` | Added `BaselineTestRunTargetORM`. Removed per-server fields + `batch_id` from `BaselineTestRunORM`. Added `targets` relationship. |
| `api/schemas.py` | New `BaselineTestRunTargetEntry`, `BaselineTestRunTargetResponse`. `BaselineTestRunCreate` now takes `targets` list. `BaselineTestRunResponse` includes `targets[]`. Removed all batch schemas. |
| `api/baseline_test_runs.py` | Create endpoint builds target rows. List endpoint joins through targets for server_id filter. Removed `/batch` and `/batch-start` endpoints. |
| `core/baseline_validation.py` | `validate()` loops over all targets. Deduplicates loadgen checks. All `_check_*` helpers reused unchanged. |
| `core/baseline_orchestrator.py` | Full rewrite. `_load_context()` returns `(lab, scenario, targets, load_profiles)`. All `_do_*` methods loop over targets. Execution results keyed by `server_id → lp_id`. |
| `core/baseline_execution.py` | Full rewrite with barrier pattern. Per-profile: restore all → configure all → start all JMeter → single sleep → collect all. Returns `Dict[server_id, Dict[lp_id, ExecutionResult]]`. |

### 1.4 Files Deleted
- `core/baseline_multi_orchestrator.py` — superseded by changes in `baseline_orchestrator.py`

---

## 2. Current Database State

### 2.1 `baseline_test_runs` (run-level only)
| Column | Type |
|--------|------|
| id | INT PK |
| lab_id | INT FK |
| scenario_id | INT FK |
| test_type | VARCHAR (enum) |
| state | VARCHAR (enum) |
| current_load_profile_id | INT FK (nullable) |
| error_message | NVARCHAR (nullable) |
| verdict | VARCHAR (nullable) |
| created_at | DATETIME |
| started_at | DATETIME (nullable) |
| completed_at | DATETIME (nullable) |

### 2.2 `baseline_test_run_targets` (per-server)
| Column | Type |
|--------|------|
| id | INT PK |
| baseline_test_run_id | INT FK |
| target_id | INT FK (servers) |
| loadgenerator_id | INT FK (servers) |
| partner_id | INT FK (nullable) |
| test_snapshot_id | INT FK (snapshots) |
| compare_snapshot_id | INT FK (nullable) |
| service_monitor_patterns | NVARCHAR(MAX) |
| os_kind | VARCHAR(100) |
| os_major_ver | VARCHAR(20) |
| os_minor_ver | VARCHAR(20) |
| agent_versions | NVARCHAR(MAX) |
| UQ: (baseline_test_run_id, target_id) |

### 2.3 Existing Test Runs (migrated)

| Run ID | Type | State | Target | Loadgen | Snapshot |
|--------|------|-------|--------|---------|----------|
| 1 | new_baseline | failed | 8 (target-rky-01) | 7 (loadgen-rky-01) | 3 (clean-rocky-baseline) |
| 2 | new_baseline | failed | 9 (TARGET-WIN-01) | 7 (loadgen-rky-01) | 4 (clean-win-baseline) |

Both failed previously (error_message is NULL — likely failed before the error was recorded, or from a prior code version).

### 2.4 Lab Inventory

| ID | Hostname | IP | OS | Role | Default Loadgen |
|----|----------|----|----|------|-----------------|
| 6 | orch-rky-01 | 10.0.0.82 | linux | Orchestrator | — |
| 7 | loadgen-rky-01 | 10.0.0.83 | linux | Load Generator | — |
| 8 | target-rky-01 | 10.0.0.92 | linux | Target | 7 |
| 9 | TARGET-WIN-01 | 10.0.0.91 | windows | Target | 7 |

Lab: Proxmox Lab (ID=4), Hypervisor: 10.0.0.72:8006, Scenario: ID=3 "Proxmox Baseline Compare"

### 2.5 Snapshots

| ID | Name | Server |
|----|------|--------|
| 1 | MyFirstBaseSnapshot | 8 |
| 2 | clean-loadgen | 7 |
| 3 | clean-rocky-baseline | 8 |
| 4 | clean-win-baseline | 9 |

### 2.6 Load Profiles

| ID | Name | CPU Min-Max | Duration | Ramp Up |
|----|------|-------------|----------|---------|
| 1 | low | 20-40% | 120s | 15s |
| 2 | medium | 40-60% | 180s | 30s |
| 3 | high | 60-80% | 180s | 30s |

---

### 1.5 HTML Template Fixes (2026-03-09)

Deep validation found ALL 4 baseline HTML templates were broken — they accessed removed fields (`run.server_id`, `run.test_snapshot_id`, `run.compare_snapshot_id`, `run.os_kind`, etc.) that no longer exist on the API response.

| File | What Was Broken | Fix Applied |
|------|----------------|-------------|
| `create.html` | `submitTest()` sent flat body with `server_id`, `test_snapshot_id` at top level | Now sends `targets: [{server_id, test_snapshot_id, ...}]` format |
| `list.html` | Used `r.server_id`, `r.test_snapshot_id`, `r.compare_snapshot_id` | Now uses `r.targets[0].target_id` etc., shows "+N" for multi-target runs |
| `dashboard.html` | Used `_run.server_id` for header, snapshot API calls, discovery panel (`os_kind`, `os_major_ver`, etc.) | Now uses `_run.targets[0]` for all per-target fields, discovery shows all targets |
| `results.html` | Used `run.server_id`, `run.test_snapshot_id` for summary and profile data API call | Now uses `run.targets[0]` for API calls, shows all target IDs in summary |

---

## 3. What Has NOT Been Done Yet

- [ ] **End-to-end test** — No test run has been executed with the new multi-target code
- [x] ~~**HTML templates** — `create.html`, `list.html`, `results.html` not updated for multi-target UI~~ **DONE**
- [ ] **Setup script** (`setup_proxmox_lab.py`) — Not updated to use new targets-based API
- [ ] **Known issue**: L8 (Emulator not reset between calibration profiles) still open
- [ ] **Known issue**: `os_vendor_family`/`os_major_ver`/`os_minor_ver` missing on some ServerORM inserts in setup script

---

## 4. Test Plan

See [testplan.md](testplan.md) for the full test plan with checklists (8 phases).
