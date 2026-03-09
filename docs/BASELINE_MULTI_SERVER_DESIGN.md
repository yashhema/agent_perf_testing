# Baseline-Compare Multi-Server Design

## 1. Problem Statement

The current `BaselineTestRunORM` is hardcoded to a single server:

```
BaselineTestRunORM
  server_id           FK -> servers.id        (single)
  test_snapshot_id    FK -> snapshots.id       (single)
  compare_snapshot_id FK -> snapshots.id       (single)
  loadgenerator_id    FK -> servers.id         (single)
  partner_id          FK -> servers.id         (single)
  ...
```

This means each test run operates on one server. To test N servers, you create N independent test runs. They have no coordination — no barriers between states, no synchronized execution.

The live_compare mode already solved this with `TestRunTargetORM`: one test run, N target rows, barriers between phases. Baseline_compare needs the same pattern.

---

## 2. How live_compare Already Handles This

```
TestRunORM                          (1 row — run-level state, scenario, lab)
  |
  +-- TestRunTargetORM              (N rows — per-server: server, loadgen, snapshots, discovery)
  +-- TestRunLoadProfileORM         (M rows — shared load profiles)
  +-- CalibrationResultORM          (N x M rows — per server x per profile)
  +-- PhaseExecutionResultORM       (N x M x phases — per server x per profile x per phase)
  +-- ComparisonResultORM           (N x M — per server x per profile)
```

The `Orchestrator` and `ExecutionEngine` loop over `targets`:

```python
# orchestrator.py - _do_calibration
for target_config in targets:
    for lp in load_profiles:
        calibration_engine.calibrate(session, test_run, ctx)

# execution.py - _execute_cycle (with barriers)
for target in targets:              # setup all
    restore_snapshot(target)
    deploy_emulator(target)
    configure_emulator(target)
    start_stats(target)
# ── BARRIER: all targets set up ──
for target in targets:              # start all
    start_jmeter(target)
# ── BARRIER: time.sleep(duration + margin) ──
for target in targets:              # collect all
    collect_results(target)
```

---

## 3. Proposed Changes

### 3.1 New Table: `BaselineTestRunTargetORM`

Follows the `TestRunTargetORM` pattern. Per-server fields move out of `BaselineTestRunORM` into target rows.

```
baseline_test_run_targets
  id                      PK
  baseline_test_run_id    FK -> baseline_test_runs.id    NOT NULL
  target_id               FK -> servers.id               NOT NULL  (the server under test)
  loadgenerator_id        FK -> servers.id               NOT NULL
  partner_id              FK -> servers.id               NULL
  test_snapshot_id        FK -> snapshots.id             NOT NULL
  compare_snapshot_id     FK -> snapshots.id             NULL
  service_monitor_patterns JSON                          NULL

  # Discovery results (written during setting_up)
  os_kind                 VARCHAR(100)                   NULL
  os_major_ver            VARCHAR(20)                    NULL
  os_minor_ver            VARCHAR(20)                    NULL
  agent_versions          JSON                           NULL

  UNIQUE(baseline_test_run_id, target_id)
```

### 3.2 Fields That Stay on `BaselineTestRunORM`

These are run-level, shared across all targets:

| Field | Why run-level |
|-------|---------------|
| `lab_id` | All targets in same lab |
| `scenario_id` | Same test scenario for all |
| `test_type` | Same type (new_baseline / compare / compare_with_new_calibration) |
| `state` | Single state machine for the whole run |
| `current_load_profile_id` | All targets on same profile during execution |
| `error_message` | Run-level error |
| `verdict` | Aggregate verdict across all targets |
| `created_at`, `started_at`, `completed_at` | Run-level timestamps |

### 3.3 Fields That Move to `BaselineTestRunTargetORM`

| Field | Why per-target |
|-------|---------------|
| `server_id` -> `target_id` | Each target is a different server |
| `test_snapshot_id` | Each server has its own snapshot tree |
| `compare_snapshot_id` | Each server compares against its own baseline data |
| `loadgenerator_id` | Could differ per target |
| `partner_id` | Per-target configuration |
| `service_monitor_patterns` | Per-target agent processes to monitor |
| `os_kind`, `os_major_ver`, `os_minor_ver`, `agent_versions` | Discovery is per-server |

### 3.4 Fields Removed from `BaselineTestRunORM`

These columns are dropped (replaced by target rows):

```sql
-- Removed from baseline_test_runs:
server_id, test_snapshot_id, compare_snapshot_id,
loadgenerator_id, partner_id, service_monitor_patterns,
os_kind, os_major_ver, os_minor_ver, agent_versions
```

### 3.5 No Change Needed on Existing Supporting Tables

| Table | Why no change |
|-------|---------------|
| `CalibrationResultORM` | Already has `server_id` + `baseline_test_run_id`. Queries by (baseline_test_run_id, server_id, load_profile_id) already work for multi-server. |
| `ComparisonResultORM` | Already has `baseline_test_run_id` + `target_id` (nullable). Set `target_id` to the server being compared. |
| `SnapshotProfileDataORM` | Keyed by (snapshot_id, load_profile_id). No test run FK. Each server's snapshot stores its own data independently. |
| `BaselineTestRunLoadProfileORM` | Load profiles are shared across all targets. No change. |

---

## 4. State Machine (Unchanged)

The state machine remains run-level. All targets advance together:

```
new_baseline:
  created -> validating -> setting_up -> calibrating -> generating
          -> executing -> storing -> completed

compare:
  created -> validating -> setting_up -> executing -> comparing
          -> storing -> completed

compare_with_new_calibration:
  created -> validating -> setting_up -> calibrating -> generating
          -> executing -> comparing -> storing -> completed
```

Failure at any state for any target fails the entire run.

---

## 5. Execution Flow with Barriers

### 5.1 Validating (all targets)

```python
for target in targets:
    check server reachable (SSH/WinRM)
    check loadgen reachable
    check emulator reachable (soft — deployed during setup)
    check test_snapshot exists on hypervisor
    if compare mode: check compare_snapshot has stored data
# If any target fails validation -> fail the run
```

### 5.2 Setting Up (all targets)

```python
# Loadgen setup (deduplicated — shared loadgen only set up once)
seen_loadgens = set()
for target in targets:
    if target.loadgenerator_id not in seen_loadgens:
        deploy JMeter to loadgen
        seen_loadgens.add(target.loadgenerator_id)
    create run directory on loadgen
    upload JMX template
    upload calibration CSV (if new_baseline or compare_with_new_calibration)

# Target setup
for target in targets:
    restore VM to test_snapshot via hypervisor API
    wait_for_vm_ready()
    wait_for_ssh()
    deploy emulator
    run discovery -> write to BaselineTestRunTargetORM
```

### 5.3 Calibrating (all targets, all profiles)

```python
for target in targets:
    for load_profile in load_profiles:
        # Each target calibrates independently
        # JMeter on shared loadgen targets different server IPs
        # Run dirs are isolated: baseline_{run_id}/lg_{lg_id}/target_{srv_id}
        binary_search for thread_count
        save CalibrationResultORM(baseline_test_run_id, server_id, load_profile_id)
# ── BARRIER: all targets calibrated for all profiles ──
```

Note: Multiple JMeter instances on the same loadgen targeting different servers is safe — each is a separate process with isolated paths. The loadgen (4 cores, 8GB) has sufficient capacity since calibration uses low thread counts.

### 5.4 Generating (all targets)

```python
for target in targets:
    for load_profile in load_profiles:
        read CalibrationResultORM -> thread_count
        generate ops_sequence CSV
        upload to loadgen at run_dir
# ── BARRIER: all sequences generated and uploaded ──
```

### 5.5 Executing (coordinated — barriers per load profile)

This follows the live_compare `execution.py._execute_cycle` pattern:

```python
for load_profile in load_profiles:

    # Step 1: Restore all targets to snapshot
    for target in targets:
        restore VM to test_snapshot
        wait_for_vm_ready()
        wait_for_ssh()
    # ── BARRIER: all targets restored ──

    # Step 2: Deploy + configure all targets
    for target in targets:
        deploy emulator if needed
        clean emulator dirs
        configure emulator (set_config)
        start stats collection (start_test)
    # ── BARRIER: all targets configured and collecting stats ──

    # Step 3: Start JMeter on all targets
    for target in targets:
        start JMeter (loadgen -> target server)
    # ── BARRIER: all JMeter instances running ──

    # Step 4: Single wait
    time.sleep(duration + ramp_up + margin)

    # Step 5: Stop + collect from all targets
    for target in targets:
        stop JMeter
        stop emulator stats
        download stats JSON
        download JTL
        compute stats summary
        save ExecutionResult
```

### 5.6 Comparing (per-target, independent)

No barrier needed — this is pure computation on already-collected data.

```python
for target in targets:
    if test_type in (compare, compare_with_new_calibration):
        load stored baseline data from compare_snapshot's SnapshotProfileDataORM
        for load_profile in load_profiles:
            Cohen's d: test execution stats vs stored baseline stats
            save ComparisonResultORM(baseline_test_run_id, target_id, load_profile_id)

aggregate verdict across all targets
```

### 5.7 Storing (per-target, independent)

No barrier needed.

```python
for target in targets:
    for load_profile in load_profiles:
        save/update SnapshotProfileDataORM on test_snapshot:
            thread_count, stats_data path, jtl_data path, jmx_test_case_data path, stats_summary
    if new_baseline:
        mark test_snapshot as is_baseline = True
```

---

## 6. API Changes

### 6.1 Create Endpoint

`POST /api/baseline-tests`

Current request body (single server):
```json
{
  "server_id": 8,
  "scenario_id": 3,
  "test_type": "new_baseline",
  "test_snapshot_id": 3,
  "load_profile_ids": [1, 2, 3]
}
```

New request body (multi-server):
```json
{
  "scenario_id": 3,
  "test_type": "new_baseline",
  "load_profile_ids": [1, 2, 3],
  "targets": [
    {
      "server_id": 8,
      "test_snapshot_id": 3
    },
    {
      "server_id": 9,
      "test_snapshot_id": 4,
      "compare_snapshot_id": null
    }
  ]
}
```

Single-server is just `targets` with one entry. No separate single-server API needed.

Defaults resolution per target:
- `loadgenerator_id`: from target entry or `ServerORM.default_loadgen_id`
- `partner_id`: from target entry or `ServerORM.default_partner_id`
- `service_monitor_patterns`: from target entry or `ServerORM.service_monitor_patterns`

### 6.2 Response

`BaselineTestRunResponse` includes a `targets` list instead of flat server fields:

```json
{
  "id": 1,
  "lab_id": 4,
  "scenario_id": 3,
  "test_type": "new_baseline",
  "state": "executing",
  "current_load_profile_id": 2,
  "targets": [
    {
      "target_id": 8,
      "loadgenerator_id": 7,
      "test_snapshot_id": 3,
      "os_kind": "Rocky Linux",
      "os_major_ver": "9",
      "os_minor_ver": "7"
    },
    {
      "target_id": 9,
      "loadgenerator_id": 7,
      "test_snapshot_id": 4,
      "os_kind": "Windows Server",
      "os_major_ver": "2022"
    }
  ],
  "verdict": "passed",
  "created_at": "..."
}
```

### 6.3 Start Endpoint

`POST /api/baseline-tests/{id}/start` — unchanged. Spawns one background thread that runs the orchestrator for the whole test run (all targets).

### 6.4 Removed Endpoints

- `POST /api/baseline-tests/batch` — no longer needed (use targets array in create)
- `POST /api/baseline-tests/batch-start` — no longer needed (single run, single start)

---

## 7. Code Changes Summary

### 7.1 New Files

| File | Purpose |
|------|---------|
| `migrations/add_baseline_test_run_targets.sql` | DDL for new table, data migration, column drops |

### 7.2 Modified Files

| File | Change |
|------|--------|
| `models/orm.py` | Add `BaselineTestRunTargetORM`. Remove per-server fields from `BaselineTestRunORM`. Add `targets` relationship. |
| `api/schemas.py` | Restructure `BaselineTestRunCreate` with `targets` list. Update `BaselineTestRunResponse`. Remove batch schemas. |
| `api/baseline_test_runs.py` | Create endpoint builds target rows. Remove batch endpoints. |
| `core/baseline_orchestrator.py` | `_load_context` returns targets list. All `_do_*` methods loop over targets. `_do_execution` follows `execution.py` barrier pattern. |
| `core/baseline_execution.py` | `execute()` accepts targets list. Per-profile loop uses setup-all/start-all/wait/collect-all pattern. |
| `core/baseline_validation.py` | `validate()` loops over targets. Reuses existing `_check_*` functions per target. |
| `templates/baseline_tests/create.html` | Multi-server target selection UI |
| `templates/baseline_tests/list.html` | Display target count instead of single server |
| `templates/baseline_tests/results.html` | Per-target result tabs |

### 7.3 Deleted Files

| File | Reason |
|------|--------|
| `core/baseline_multi_orchestrator.py` | Logic merges into `baseline_orchestrator.py` |

### 7.4 Reused Functions (no duplication)

| Function | Location | Used by |
|----------|----------|---------|
| `_check_server_reachable(server, role)` | `baseline_validation.py` | Called per target in a loop |
| `_check_emulator_reachable(server)` | `baseline_validation.py` | Called per target |
| `_check_snapshot_exists_on_hypervisor(lab, server, snapshot)` | `baseline_validation.py` | Called per target |
| `_check_stored_data(session, snapshot, lp_ids)` | `baseline_validation.py` | Called per target's compare_snapshot |
| `CalibrationEngine.calibrate()` | `core/calibration.py` | Already per-server (takes CalibrationContext with server) |
| `ComparisonEngine.run_baseline_comparison()` | `services/comparison.py` | Already per-server (takes server_id param) |
| `PackageResolver.resolve()` | `services/package_manager.py` | Already per-server (takes server ORM) |
| `PackageDeployer.deploy_all()` | `services/package_manager.py` | Already per-executor |
| `create_executor()` | `infra/remote_executor.py` | Already per-host |
| `EmulatorClient` | `infra/emulator_client.py` | Already per-host |
| `wait_for_ssh()` | `core/baseline_execution.py` | Already per-host |
| `StatsParser.trim_samples()`, `.compute_summary()` | `services/stats_parser.py` | Stateless, reusable |

---

## 8. SQL Migration

```sql
-- 1. Create new targets table
CREATE TABLE baseline_test_run_targets (
    id INT IDENTITY(1,1) PRIMARY KEY,
    baseline_test_run_id INT NOT NULL
        REFERENCES baseline_test_runs(id),
    target_id INT NOT NULL
        REFERENCES servers(id),
    loadgenerator_id INT NOT NULL
        REFERENCES servers(id),
    partner_id INT NULL
        REFERENCES servers(id),
    test_snapshot_id INT NOT NULL
        REFERENCES snapshots(id),
    compare_snapshot_id INT NULL
        REFERENCES snapshots(id),
    service_monitor_patterns NVARCHAR(MAX) NULL,
    os_kind VARCHAR(100) NULL,
    os_major_ver VARCHAR(20) NULL,
    os_minor_ver VARCHAR(20) NULL,
    agent_versions NVARCHAR(MAX) NULL,
    CONSTRAINT uq_baseline_run_target
        UNIQUE(baseline_test_run_id, target_id)
);

CREATE INDEX ix_btrt_run_id ON baseline_test_run_targets(baseline_test_run_id);

-- 2. Migrate existing data (one target row per existing run)
INSERT INTO baseline_test_run_targets
    (baseline_test_run_id, target_id, loadgenerator_id,
     partner_id, test_snapshot_id, compare_snapshot_id,
     service_monitor_patterns, os_kind, os_major_ver,
     os_minor_ver, agent_versions)
SELECT
    id, server_id, loadgenerator_id,
    partner_id, test_snapshot_id, compare_snapshot_id,
    service_monitor_patterns, os_kind, os_major_ver,
    os_minor_ver, agent_versions
FROM baseline_test_runs
WHERE server_id IS NOT NULL;

-- 3. Drop moved columns from baseline_test_runs
-- (run after code is updated to use targets table)
ALTER TABLE baseline_test_runs DROP COLUMN server_id;
ALTER TABLE baseline_test_runs DROP COLUMN test_snapshot_id;
ALTER TABLE baseline_test_runs DROP COLUMN compare_snapshot_id;
ALTER TABLE baseline_test_runs DROP COLUMN loadgenerator_id;
ALTER TABLE baseline_test_runs DROP COLUMN partner_id;
ALTER TABLE baseline_test_runs DROP COLUMN service_monitor_patterns;
ALTER TABLE baseline_test_runs DROP COLUMN os_kind;
ALTER TABLE baseline_test_runs DROP COLUMN os_major_ver;
ALTER TABLE baseline_test_runs DROP COLUMN os_minor_ver;
ALTER TABLE baseline_test_runs DROP COLUMN agent_versions;
```

---

## 9. Path Isolation

All paths already include `test_run_id` + `loadgen_id` + `server_id`, so multi-server execution has no path collisions:

### Remote (loadgen)
```
/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}/test.jmx
/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}/results_{lp_name}.jtl
/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}/ops_sequence_{lp_name}.csv
```

### Local (orchestrator)
```
results/{test_run_id}/server_{server_id}/stats/lp{lp_id}_stats.json
results/{test_run_id}/server_{server_id}/jtl/lp{lp_id}.jtl
results/{test_run_id}/server_{server_id}/jmx_data/lp{lp_id}_ops_sequence.csv
results/{test_run_id}/server_{server_id}/execution_manifest.json
results/{test_run_id}/server_{server_id}/comparison/
```

---

## 10. Single-Server Backward Compatibility

A single-server test run is a test run with one entry in `targets`. All for-loops execute once. No special-casing needed.

API request with one target:
```json
{
  "scenario_id": 3,
  "test_type": "new_baseline",
  "load_profile_ids": [1, 2, 3],
  "targets": [
    {"server_id": 8, "test_snapshot_id": 3}
  ]
}
```

---

## 11. Comparison Clarification

### live_compare
Generates **2 result sets** in one run (base snapshot phase + initial snapshot phase). Compares them against each other. Both are fresh.

### baseline_compare
Generates **1 result set** per target (test_snapshot execution). Comparison is per-target, independent:
- **new_baseline**: No comparison. Store results as baseline data on the snapshot.
- **compare**: Compare against stored data from `compare_snapshot`. Reuses compare_snapshot's calibration (thread counts) and test case data (ops_sequence CSVs).
- **compare_with_new_calibration**: Fresh calibration, then compare against stored data from `compare_snapshot`.

Each target compares against its **own** compare_snapshot's stored data. There is no cross-server comparison.

If a target's compare_snapshot has no stored data for a load profile, that profile is skipped for that target (with a warning).

### Verdict aggregation
The run-level verdict is the worst verdict across all targets:
- All passed -> `passed`
- Any warning, none failed -> `warning`
- Any failed -> `failed`
