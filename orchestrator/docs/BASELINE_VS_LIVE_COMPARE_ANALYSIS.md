# Baseline-Compare vs Live-Compare: Mode Analysis & Code Impact

## 1. Executive Summary

This document analyzes the architectural differences between **live-compare mode** (Vultr/AWS/GCP/Azure) and **baseline-compare mode** (Proxmox/vSphere), identifies code that is shared vs mode-specific, and specifies what changes are needed for baseline-compare to work end-to-end without breaking the original live-compare flow.

### Mode Grouping

| Mode               | Hypervisors           | Orchestrator Class      | Snapshot Model   | Test Run Model         |
|--------------------|-----------------------|-------------------------|------------------|------------------------|
| **live_compare**   | Vultr, AWS, GCP, Azure| `Orchestrator`          | `BaselineORM`    | `TestRunORM`           |
| **baseline_compare**| Proxmox, vSphere     | `BaselineOrchestrator`  | `SnapshotORM`    | `BaselineTestRunORM`   |

### Key Difference

- **Live-compare**: Each snapshot is an independent full-VM capture (`BaselineORM`) with embedded OS metadata (`os_vendor_family`, `os_major_ver`, `os_minor_ver`). Two snapshots are compared per test run.
- **Baseline-compare**: Snapshots form a hierarchical tree on the hypervisor (`SnapshotORM`). One "group" snapshot is the baseline; child "subgroup" snapshots are compared against it. OS metadata lives on `ServerORM` (partially) and is discovered at runtime.

---

## 2. Component-by-Component Analysis

### 2.1 Package Resolution — ROOT CAUSE OF FAILURE

**File**: `orchestrator/src/orchestrator/services/package_manager.py`

#### Current Behavior (live-compare)
```python
# orchestrator.py line 164 — passes BaselineORM
jmeter_packages = resolver.resolve(session, [lab.jmeter_package_grpid], loadgen_baseline)

# orchestrator.py line 214 — passes BaselineORM
emu_packages = resolver.resolve(session, [lab.emulator_package_grp_id], baseline)
```
`PackageResolver.resolve()` signature: `resolve(session, package_group_ids, baseline: BaselineORM)`

`_build_os_string()` accesses `baseline.os_vendor_family` and `baseline.os_major_ver` to build the OS match string (e.g., `"ubuntu/22"` or `"rhel/9/3"`).

#### Current Behavior (baseline-compare) — BROKEN
```python
# baseline_orchestrator.py line 167-168 — passes ServerORM (NOT BaselineORM!)
jmeter_packages = resolver.resolve(session, [lab.jmeter_package_grpid], loadgen)

# baseline_orchestrator.py line 238-239 — passes ServerORM
emu_packages = resolver.resolve(session, [lab.emulator_package_grp_id], server)
```

**Root cause**: `ServerORM` only has `os_family` (linux/windows). It lacks `os_vendor_family` (ubuntu/rhel/windows) and `os_major_ver` (22/9/2022). The call to `_build_os_string()` crashes with `AttributeError: 'ServerORM' object has no attribute 'os_vendor_family'`.

#### Proposed Fix

**Option A — Add `os_vendor_family` / `os_major_ver` to ServerORM** (RECOMMENDED):
- Add columns: `os_vendor_family`, `os_major_ver`, `os_minor_ver` to `servers` table
- These are populated once during server setup or first discovery
- Modify `PackageResolver.resolve()` to accept a union type or protocol:

```python
from typing import Protocol

class OSInfoProvider(Protocol):
    os_vendor_family: str
    os_major_ver: str
    os_minor_ver: Optional[str]

def resolve(self, session, package_group_ids, os_info: OSInfoProvider) -> List[ResolvedPackage]:
```

Both `BaselineORM` and `ServerORM` (with new columns) satisfy this protocol. **No changes to live-compare code path.**

**Option B — Mode-aware resolve method**:
- Add `resolve_for_server()` that builds OS string from `ServerORM.os_family` + lab mode lookup
- Less precise (can't distinguish ubuntu from rhel with just `os_family=linux`)
- Not recommended as primary approach

#### Impact on Live-Compare: NONE
The `Orchestrator` class always passes `BaselineORM` to `resolve()`. Adding a protocol doesn't change the existing call signature.

---

### 2.2 Credential Resolution

**File**: `orchestrator/src/orchestrator/config/credentials.py`

#### Current Behavior (both modes)
```python
# Cascade: by_server_id -> by_os_type
cred = credentials.get_server_credential(server.id, server.os_family.value)
```

#### Analysis
Credential resolution is **already mode-agnostic**. Both orchestrators call `get_server_credential(server_id, os_family)`. The cascade lookup works identically:
1. Check `servers.by_server_id[server.id]` — exact match
2. Fall back to `servers.by_os_type["linux"]` or `servers.by_os_type["windows"]`

#### Enhancement (per user requirement)
Add lab mode as additional lookup dimension for cases where same OS family needs different credentials per mode:

```json
{
  "servers": {
    "by_server_id": { "6": {"username": "root", "password": "..."} },
    "by_os_type": { "linux": {"username": "root", "password": "..."} },
    "by_mode_os_type": {
      "baseline_compare": { "linux": {"username": "root", "password": "..."} },
      "live_compare": { "linux": {"username": "ubuntu", "password": "..."} }
    }
  }
}
```

Updated cascade: `by_server_id -> by_mode_os_type[mode][os_family] -> by_os_type[os_family]`

#### Impact on Live-Compare: NONE
New cascade step is additive. If `by_mode_os_type` key is absent, falls through to existing `by_os_type`.

---

### 2.3 OS Version Discovery

**File**: `orchestrator/src/orchestrator/services/discovery.py`

#### Current Behavior (live-compare)
- `DiscoveryService.discover_and_store()` runs discovery scripts on targets after each snapshot restore
- Stores results on `TestRunTargetORM` fields: `os_kind`, `base_os_major_ver`, `initial_os_major_ver`, `base_agent_versions`, `initial_agent_versions`
- Discovery data is per-test-run, per-target, per-snapshot-number

#### Current Behavior (baseline-compare)
- `BaselineOrchestrator._do_setup()` calls `discovery.discover_os(target_exec)` and `discovery.discover_agents(target_exec)`
- Stores results on `BaselineTestRunORM`: `os_kind`, `os_major_ver`, `os_minor_ver`, `agent_versions`
- Discovery runs once per test run (single target per test run)

#### Key Difference
| Aspect                  | Live-Compare                          | Baseline-Compare                    |
|-------------------------|---------------------------------------|-------------------------------------|
| Discovery timing        | After each snapshot restore (2x)      | Once during setup                   |
| Storage model           | `TestRunTargetORM` (per target)       | `BaselineTestRunORM` (per test run) |
| OS info reuse           | Per test run only                     | Could persist on `ServerORM`        |
| Multiple targets        | Yes (N targets per test run)          | 1 target per test run               |

#### Proposed Enhancement
When running in baseline-compare mode, also persist discovered OS info back to `ServerORM` columns (`os_vendor_family`, `os_major_ver`, `os_minor_ver`) if they are currently NULL. This ensures package resolution works on subsequent runs without re-discovery.

#### Impact on Live-Compare: NONE
Live-compare stores discovery data on `TestRunTargetORM` and uses `BaselineORM` for package resolution. The new `ServerORM` columns are only used by baseline-compare code paths.

---

### 2.4 Snapshot Management

**Files**: `orchestrator/services/snapshot_manager.py`, `orchestrator/models/orm.py`

#### Live-Compare (Vultr/AWS/GCP/Azure)
- Uses `BaselineORM` — flat table, each row is an independent snapshot
- `BaselineORM.provider_ref` = `{"snapshot_id": "..."}` or `{"snapshot_moref_id": "..."}`
- Snapshots are restored via `hypervisor.restore_snapshot(server_infra_ref, baseline.provider_ref)`
- No parent-child relationship; snapshot 1 (base) and snapshot 2 (initial) are independent

#### Baseline-Compare (Proxmox/vSphere)
- Uses `SnapshotORM` — hierarchical tree with `parent_id` foreign key
- `SnapshotManager.sync_tree()` synchronizes hypervisor snapshot tree to DB
- Hierarchy: Group (clean OS) → Subgroup (agent installed) → Test snapshots
- `SnapshotProfileDataORM` stores calibration results, JMX data, stats per snapshot+profile
- Snapshots are restored via `provider.restore_snapshot(server_infra_ref, snapshot.provider_ref)`

#### Data Models Comparison
```
Live-Compare:                      Baseline-Compare:
  BaselineORM                        SnapshotBaselineORM (Group)
    - os_vendor_family                 - server_id
    - os_major_ver                     - snapshot_id -> SnapshotORM
    - provider_ref                   SnapshotGroupORM (Subgroup)
    - baseline_type                    - baseline_id -> SnapshotBaselineORM
                                       - snapshot_id -> SnapshotORM
  TestRunTargetORM                   SnapshotORM
    - base_snapshot_id -> BaselineORM  - parent_id -> SnapshotORM (self-ref)
    - initial_snapshot_id -> BaselineORM - group_id -> SnapshotGroupORM
                                       - provider_snapshot_id
  TestRunORM                         BaselineTestRunORM
    - N targets via TestRunTargetORM   - 1 server_id (single target)
    - 2 snapshots per target           - test_snapshot_id
                                       - compare_snapshot_id
```

#### Impact on Live-Compare: NONE
These are entirely separate tables and code paths. `SnapshotORM` and `SnapshotManager` are not used by `Orchestrator`.

---

### 2.5 Test Execution Flow

#### Live-Compare Flow (Orchestrator)
```
validating -> setting_up -> calibrating -> generating_sequences -> executing -> comparing -> completed
```
- **setting_up**: Restore ALL servers (loadgen + N targets) to their BaselineORM snapshots, deploy packages to all
- **calibrating**: For each target × load_profile, find optimal thread count
- **generating_sequences**: Generate deterministic ops CSV for each target × profile
- **executing**: 2 snapshots × N profiles × M cycles execution loop
- **comparing**: Compare snapshot-1 vs snapshot-2 results for each target × profile

#### Baseline-Compare Flow (BaselineOrchestrator)
```
new_baseline:    validating -> setting_up -> calibrating -> generating -> executing -> storing -> completed
compare:         validating -> setting_up -> executing -> comparing -> storing -> completed
compare_new_cal: validating -> setting_up -> calibrating -> generating -> executing -> comparing -> storing -> completed
```
- **setting_up**: Restore ONLY the target to test_snapshot; loadgen is persistent (never restored)
- **calibrating**: Only for new_baseline / compare_with_new_calibration
- **generating**: Generate ops CSV using calibrated thread counts
- **executing**: Single snapshot, all profiles, single cycle
- **comparing**: Compare test_snapshot results against stored compare_snapshot data
- **storing**: Save calibration + stats + JMX data to `SnapshotProfileDataORM`

#### Key Execution Differences

| Aspect                | Live-Compare                           | Baseline-Compare                       |
|-----------------------|----------------------------------------|----------------------------------------|
| Loadgen restore       | Yes (every run)                        | No (persistent)                        |
| Target count          | N targets per run                      | 1 target per run                       |
| Snapshot restore      | Both base + initial snapshots          | Only test_snapshot                     |
| Calibration           | Always runs                            | Only for new_baseline / compare_new_cal|
| Data storage          | In-memory (per test run)               | Persistent (`SnapshotProfileDataORM`)  |
| Comparison data source| Other snapshot's execution results     | Stored data from compare_snapshot      |
| Execution loop        | 2 snapshots × N profiles × M cycles   | 1 snapshot × N profiles × 1 cycle     |

---

### 2.6 Comparison Engine

**File**: `orchestrator/src/orchestrator/services/comparison.py`

#### Live-Compare
- `ComparisonEngine.run_comparison()` loads execution results from `PhaseExecutionResultORM`
- Compares snapshot-1 results vs snapshot-2 results (same test run)
- Both datasets are fresh execution data from the same run

#### Baseline-Compare
- `ComparisonEngine.run_baseline_comparison()` compares:
  - **Test data**: Fresh execution results from current run
  - **Baseline data**: Stored data from `SnapshotProfileDataORM` (captured during a previous `new_baseline` run)
- Two sub-modes:
  - **Option A** (`compare`): Reuses calibration + JMX from baseline snapshot
  - **Option B** (`compare_with_new_calibration`): Fresh calibration, compares against baseline stats

#### Impact on Live-Compare: NONE
`run_comparison()` and `run_baseline_comparison()` are separate methods. The baseline method was added without modifying the original.

---

### 2.7 Shared Components (Mode-Agnostic)

These components work identically in both modes and require NO changes:

| Component                  | File                                | Notes                                    |
|----------------------------|-------------------------------------|------------------------------------------|
| CalibrationEngine          | `core/calibration.py`               | Takes `CalibrationContext`, mode-agnostic |
| JMeterController           | `infra/jmeter_controller.py`        | SSH-based JMeter control                 |
| EmulatorClient             | `infra/emulator_client.py`          | HTTP API to emulator                     |
| RemoteExecutor             | `infra/remote_executor.py`          | SSH/WinRM execution                      |
| HypervisorProvider         | `infra/hypervisor.py`               | All 3 providers (Proxmox/vSphere/Vultr)  |
| PackageDeployer            | `services/package_manager.py`       | Upload + extract + install               |
| LoadProfileORM             | `models/orm.py`                     | Same profiles for both modes             |
| StatisticalTests           | `services/statistical_tests.py`     | Shared analysis functions                |
| JTL Parser                 | `services/jtl_parser.py`            | Parses JMeter results                    |

---

## 3. Required Changes Summary

### 3.1 Must Change (Blocking — Test Runs Fail)

| # | Component           | Change                                                      | Risk to Live-Compare |
|---|---------------------|-------------------------------------------------------------|----------------------|
| 1 | `ServerORM`         | Add `os_vendor_family`, `os_major_ver`, `os_minor_ver` cols | NONE — new nullable columns |
| 2 | `PackageResolver`   | Accept both `BaselineORM` and `ServerORM` via protocol      | NONE — duck typing   |
| 3 | `BaselineOrchestrator._do_setup` | Persist discovered OS info to ServerORM       | NONE — new code path |
| 4 | DB Migration        | ALTER TABLE servers ADD COLUMN os_vendor_family, etc.        | NONE — additive      |

### 3.2 Should Change (Robustness)

| # | Component           | Change                                                      | Risk to Live-Compare |
|---|---------------------|-------------------------------------------------------------|----------------------|
| 5 | `CredentialsStore`  | Add `by_mode_os_type` cascade step                          | NONE — additive      |
| 6 | `BaselineOrchestrator` | Save `error_message` in background thread context        | NONE — baseline only |
| 7 | `SnapshotManager`   | Validate provider_snapshot_id uniqueness before sync        | NONE — baseline only |

### 3.3 No Change Needed (Already Working)

| Component              | Status                                |
|------------------------|---------------------------------------|
| Credential resolution  | Works — `by_server_id` / `by_os_type` |
| Hypervisor providers   | Works — all 3 normalized              |
| Calibration engine     | Works — mode-agnostic                 |
| Execution engine       | Works — separate implementations      |
| Comparison engine      | Works — separate methods              |
| Load profiles          | Works — shared table                  |
| Snapshot tree sync     | Works — tested with Proxmox           |

---

## 4. Implementation Plan

### Phase 1: Fix Package Resolution (Critical)
1. Add `os_vendor_family`, `os_major_ver`, `os_minor_ver` columns to `ServerORM`
2. Create SQL migration: `ALTER TABLE servers ADD COLUMN ...`
3. Modify `PackageResolver._build_os_string()` to use protocol/duck-typing
4. Update `BaselineOrchestrator._do_setup()` to persist discovery results to `ServerORM`
5. Manually set OS info for existing servers (or run discovery to populate)

### Phase 2: Enhance Credential Resolution (Optional)
1. Add `by_mode_os_type` to credentials JSON schema
2. Update `CredentialsStore.get_server_credential()` with new cascade step
3. Update credentials.json with mode-specific entries

### Phase 3: End-to-End Test
1. Re-run baseline test with Proxmox lab (servers 6-9)
2. Verify: validation -> setup -> calibration -> generation -> execution -> storing
3. Run comparison test against stored baseline data
4. Verify live-compare still works (regression test)

---

## 5. Data Flow Diagrams

### Live-Compare Package Resolution
```
Orchestrator._do_setup()
  -> lab.loadgen_snapshot_id -> BaselineORM (has os_vendor_family, os_major_ver)
  -> PackageResolver.resolve(session, [grp_id], baseline_orm)
  -> _build_os_string(baseline) -> "ubuntu/22" or "rhel/9/3"
  -> regex match against PackageGroupMemberORM.os_match_regex
  -> ResolvedPackage
```

### Baseline-Compare Package Resolution (PROPOSED)
```
BaselineOrchestrator._do_setup()
  -> server = ServerORM (with new os_vendor_family, os_major_ver columns)
  -> PackageResolver.resolve(session, [grp_id], server)
  -> _build_os_string(server) -> "ubuntu/22" or "rhel/9/3"  (same protocol)
  -> regex match against PackageGroupMemberORM.os_match_regex
  -> ResolvedPackage
```

### Credential Resolution (Both Modes)
```
get_server_credential(server_id=7, os_family="linux")
  1. Check by_server_id["7"]        -> found? return
  2. Check by_mode_os_type[mode]["linux"]  -> found? return  (NEW, optional)
  3. Check by_os_type["linux"]       -> found? return
  4. Return None
```

---

## 6. Risk Assessment

| Risk                                        | Probability | Impact | Mitigation                          |
|---------------------------------------------|-------------|--------|-------------------------------------|
| Breaking live-compare package resolution    | Low         | High   | Protocol-based typing, no signature change |
| Missing OS info on existing ServerORM rows  | Medium      | Medium | Manual population + auto-discovery fallback |
| Credential mismatch after mode changes      | Low         | Low    | Cascade lookup preserves existing behavior |
| Schema migration fails on SQL Server        | Low         | Medium | Test migration on dev DB first      |

---

## 7. Files Modified vs New

### Files That Need Modification
- `orchestrator/src/orchestrator/models/orm.py` — Add columns to ServerORM
- `orchestrator/src/orchestrator/services/package_manager.py` — Protocol-based resolve
- `orchestrator/src/orchestrator/core/baseline_orchestrator.py` — Persist OS info to ServerORM
- `orchestrator/src/orchestrator/config/credentials.py` — Optional mode-aware cascade

### Files That Stay Unchanged (CRITICAL — Do Not Touch)
- `orchestrator/src/orchestrator/core/orchestrator.py` — Original live-compare orchestrator
- `orchestrator/src/orchestrator/core/execution.py` — Original execution engine
- `orchestrator/src/orchestrator/core/validation.py` — Original validation
- `orchestrator/src/orchestrator/core/state_machine.py` — Original state machine
- `orchestrator/src/orchestrator/services/comparison.py` — `run_comparison()` method untouched
- `orchestrator/src/orchestrator/services/discovery.py` — `discover_and_store()` untouched

### New Files Needed
- `orchestrator/migrations/add_server_os_columns.sql` — Schema migration
