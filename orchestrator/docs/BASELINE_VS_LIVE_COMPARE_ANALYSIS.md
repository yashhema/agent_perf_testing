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

---

## 8. Additional Issues Found During Analysis

### 8.1 `PackageDeployer.check_status_any()` — Also Passes ServerORM

**File**: `orchestrator/src/orchestrator/services/package_manager.py` (line 304)

```python
def check_status_any(self, session, executor, package_group_ids, server):
    resolver = PackageResolver()
    packages = resolver.resolve(session, package_group_ids, server)  # <-- same bug
```

This method also calls `resolver.resolve()` passing `server` (a `ServerORM`). While not directly called from `BaselineOrchestrator` yet, it would fail if used. The protocol-based fix for `resolve()` (Section 2.1) automatically fixes this too.

### 8.2 `LabORM.loadgen_snapshot_id` — Not Used in Baseline-Compare Mode

**File**: `orchestrator/src/orchestrator/models/orm.py` (line 59)

`LabORM` has `loadgen_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)` which points to a `BaselineORM` row. This is required for live-compare mode (the loadgen is restored to this snapshot every run).

In baseline-compare mode, the loadgen is **persistent** (never snapshot-restored). The `loadgen_snapshot_id` FK is still required (non-nullable), so a dummy `BaselineORM` record must exist for baseline-compare labs. This is a schema constraint issue — not a runtime bug — but it means baseline-compare labs still depend on the `baselines` table existing.

**Current workaround**: Lab id=4 (Proxmox Lab) references a valid `BaselineORM` record even though it's not used. This is acceptable but could be improved by making `loadgen_snapshot_id` nullable for baseline-compare labs.

### 8.3 Discovery Timing vs Package Deployment — Ordering Issue

In `BaselineOrchestrator._do_setup()`, the current sequence is:

```
1. Deploy JMeter to loadgen       <-- needs PackageResolver -> FAILS (no OS info)
2. Restore target to snapshot
3. Deploy emulator to target      <-- needs PackageResolver -> FAILS (no OS info)
4. Run discovery on target        <-- discovers OS info
```

**Problem**: Package deployment happens BEFORE discovery. Even with `ServerORM` columns added, on the FIRST run they will be NULL because no discovery has happened yet.

**Fix**: Either:
- **(A)** Pre-populate `ServerORM.os_vendor_family` etc. via admin UI / API when adding servers
- **(B)** Run discovery FIRST (before package deployment), persist to `ServerORM`, then deploy
- **(C)** Both — allow pre-population but also auto-discover on first run

**Recommended**: Option C — pre-populate via admin UI for immediate use, with auto-discovery as fallback/verification.

### 8.4 Multi-Server Baseline Test Runs

The user's plan involves 2 target servers being tested in parallel (like the original live-compare mode). However, `BaselineTestRunORM` only has a single `server_id` field — it's designed for 1 target per test run.

**Current design**: Run separate `BaselineTestRunORM` records for each target, launched in parallel via the API.

**Implication**: Unlike live-compare (which coordinates N targets in a single `TestRunORM`), baseline-compare relies on the API/UI layer to launch multiple test runs concurrently. The orchestrator itself handles one target per run. This is by design but worth noting for the test plan.

### 8.5 Error Message Persistence in Background Threads

When `BaselineOrchestrator.run()` is invoked in a background thread (via `threading.Thread`), the SQLAlchemy session may not persist `error_message` correctly if the exception occurs after the session's transaction scope ends.

**File**: `orchestrator/src/orchestrator/api/baseline_test_runs.py` — the background thread creates its own session, but `sm.fail()` must commit within that session's scope.

**Current code** (baseline_orchestrator.py line 100-102):
```python
except Exception as e:
    logger.exception("Baseline test run %d failed: %s", test_run.id, e)
    sm.fail(session, test_run, str(e))
```

This should work since `sm.fail()` calls `session.commit()`, but the session must still be open (not expired). Need to verify `session.expire_on_commit` behavior for background threads.

---

## 9. Checklist: What Stays Untouched

The following code paths MUST NOT be modified. Any change here risks breaking the original live-compare mode:

- [ ] `Orchestrator.run()` — complete method
- [ ] `Orchestrator._do_setup()` — snapshot restore + package deploy flow
- [ ] `Orchestrator._do_calibration()` — multi-target calibration loop
- [ ] `Orchestrator._do_execution()` — 2-snapshot × N-profile × M-cycle loop
- [ ] `Orchestrator._do_comparison()` — `run_comparison()` call
- [ ] `ExecutionEngine.execute()` — complete class
- [ ] `PreFlightValidator.validate()` — complete class
- [ ] `state_machine.py` — `TestRunState` transitions
- [ ] `PackageResolver.resolve_for_phase()` — existing method signature
- [ ] `DiscoveryService.discover_and_store()` — existing method
- [ ] `BaselineORM` — no column changes
- [ ] `TestRunORM` — no column changes
- [ ] `TestRunTargetORM` — no column changes
- [ ] `ComparisonEngine.run_comparison()` — existing method

---

## 10. Concrete Code Changes (Reference Implementation)

### 10.1 SQL Migration — `add_server_os_columns.sql`

```sql
-- Migration: Add OS version columns to servers table for baseline-compare package resolution
-- These columns are populated by discovery and used by PackageResolver._build_os_string()

ALTER TABLE servers ADD os_vendor_family VARCHAR(100) NULL;
ALTER TABLE servers ADD os_major_ver VARCHAR(20) NULL;
ALTER TABLE servers ADD os_minor_ver VARCHAR(20) NULL;

-- For existing baseline-compare servers, populate from manual input or first discovery run
-- Example: UPDATE servers SET os_vendor_family='ubuntu', os_major_ver='22' WHERE id=6;
```

### 10.2 ORM Change — `ServerORM`

```python
# In models/orm.py, add to ServerORM class (after os_family):
os_vendor_family = Column(String(100), nullable=True)   # e.g., "ubuntu", "rhel", "windows"
os_major_ver = Column(String(20), nullable=True)        # e.g., "22", "9", "2022"
os_minor_ver = Column(String(20), nullable=True)        # e.g., "04", "3"
```

### 10.3 PackageResolver Change

```python
# In package_manager.py, change _build_os_string to accept duck-typed object:
@staticmethod
def _build_os_string(os_info) -> str:
    """Build OS match string: '{vendor}/{major}/{minor}'.

    Accepts any object with os_vendor_family and os_major_ver attributes.
    Works with both BaselineORM (live-compare) and ServerORM (baseline-compare).
    """
    parts = [os_info.os_vendor_family, os_info.os_major_ver]
    if os_info.os_minor_ver:
        parts.append(os_info.os_minor_ver)
    return "/".join(parts)
```

**Type annotation change** (resolve method):
```python
# Before:
def resolve(self, session, package_group_ids, baseline: BaselineORM) -> List[ResolvedPackage]:

# After (duck typing — no import change needed):
def resolve(self, session, package_group_ids, os_info) -> List[ResolvedPackage]:
```

Note: Parameter name changes from `baseline` to `os_info` but the internal call `self._build_os_string(os_info)` works the same. The `Orchestrator` still passes `BaselineORM` objects — they have the same attributes.

### 10.4 BaselineOrchestrator Change — Persist Discovery to ServerORM

```python
# In baseline_orchestrator.py _do_setup(), after running discovery:
os_info = discovery.discover_os(target_exec)
test_run.os_kind = os_info.get("os_kind")
test_run.os_major_ver = os_info.get("os_major_ver")
test_run.os_minor_ver = os_info.get("os_minor_ver")

# NEW: Also persist to ServerORM for package resolution on subsequent runs
if not server.os_vendor_family:
    server.os_vendor_family = os_info.get("os_vendor_family") or os_info.get("os_kind")
if not server.os_major_ver:
    server.os_major_ver = os_info.get("os_major_ver")
if not server.os_minor_ver:
    server.os_minor_ver = os_info.get("os_minor_ver")
session.commit()
```

### 10.5 Setup Reordering — Fix Discovery-Before-Deploy

```python
# Current order (BROKEN for first run):
#   1. Deploy JMeter (needs OS info) -> FAILS
#   2. Restore target
#   3. Deploy emulator (needs OS info) -> FAILS
#   4. Run discovery (gets OS info)

# Fixed order:
#   1. Check if ServerORM has OS info for loadgen
#   2. If not, SSH to loadgen, run discovery, persist to ServerORM
#   3. Deploy JMeter (OS info now available)
#   4. Restore target
#   5. Run discovery on target, persist to ServerORM
#   6. Deploy emulator (OS info now available)
```

The loadgen needs special handling: in baseline-compare mode it's never snapshot-restored, so we can SSH to it and run discovery before anything else. For the target, we must restore the snapshot first, then discover, then deploy.

---

## 11. Test Plan

### 11.1 Phase 1 Validation — Package Resolution Fix

| Test Case | Steps | Expected Result |
|-----------|-------|-----------------|
| Baseline new_baseline | Create test run with Proxmox lab | Passes validation, setup completes, packages deployed |
| Live-compare regression | Create test run with Vultr lab | Existing behavior unchanged, uses BaselineORM |
| Missing OS info | Run with ServerORM.os_vendor_family=NULL | Discovery runs first, populates ServerORM, then deploy succeeds |
| Populated OS info | Run with ServerORM.os_vendor_family set | Skips discovery for package resolution, deploys immediately |

### 11.2 Phase 2 Validation — Full E2E

| Test Case | Steps | Expected Result |
|-----------|-------|-----------------|
| new_baseline (2 targets) | Launch 2 BaselineTestRunORM in parallel | Both complete independently, SnapshotProfileDataORM populated |
| compare (Option A) | Run compare against stored baseline | Reuses calibration + JMX, produces comparison verdict |
| compare_with_new_calibration (Option B) | Fresh calibration + compare | New calibration, compares against stored baseline stats |

### 11.3 Regression Gates

Before merging any changes:
1. Verify `Orchestrator.run()` is UNCHANGED (git diff confirms no modifications)
2. Verify `PackageResolver.resolve()` still works with `BaselineORM` argument
3. Verify `CredentialsStore.get_server_credential()` cascade still works without `by_mode_os_type`
4. Verify all existing DB tables and columns are unchanged

---

## 12. Deep Analysis Pass (v4) — Additional Findings

Re-analysis of execution engine, state machine, validation, API, comparison, UI, schemas, and configuration uncovered **32 new issues** not covered in sections 1-11. Organized by severity.

### 12.1 CRITICAL Issues (will crash at runtime)

**C1. CalibrationEngine.calibrate() expects TestRunORM, receives BaselineTestRunORM**
- `calibration.py` line 61: `calibrate(session, test_run: TestRunORM, ctx)`
- `baseline_orchestrator.py` line 367: passes `BaselineTestRunORM`
- Inside `_get_or_create_record()`, `CalibrationResultORM.test_run_id = test_run.id` writes into `ForeignKey("test_runs.id")` — the live-compare table
- A `BaselineTestRunORM.id` value in this FK will cause `IntegrityError` unless IDs happen to collide with `test_runs`

**C2. CalibrationResultORM has no FK to baseline_test_runs**
- `CalibrationResultORM` only has `test_run_id = ForeignKey("test_runs.id")`
- No `baseline_test_run_id` column exists
- `_do_generation()` (line 409) and `_do_execution()` (line 474) query by `test_run_id == test_run.id` where `test_run` is `BaselineTestRunORM` — will find wrong or no data

**C3. run_baseline_comparison() never creates ComparisonResultORM**
- `comparison.py` `run_baseline_comparison()` saves results to disk JSON only
- API endpoint `get_baseline_comparison_results` (baseline_test_runs.py line 201) queries `ComparisonResultORM` by `baseline_test_run_id`
- Will always return empty list — comparison results are never queryable via API

**C4. DiscoveryService constructor mismatch + missing methods**
- `baseline_orchestrator.py` line 248: `DiscoveryService(self._credentials)` — passes 1 arg
- `discovery.py` `__init__` requires 2 args: `credentials` and `discovery_dir` — `TypeError` at runtime
- Calls `discovery.discover_os(target_exec)` and `discovery.discover_agents(target_exec)` — these methods do not exist on `DiscoveryService`
- Actual method is `discover_and_store(session, test_run, snapshot_num)` designed for live-compare `TestRunTargetORM`

### 12.2 HIGH Issues (wrong behavior, data corruption, or feature broken)

**H1. wait_for_ssh() hardcodes port 22 — fails on Windows targets (WinRM uses 5985/5986)**
- `baseline_execution.py` lines 54-65: always connects to port 22
- Called after every snapshot restore (line 139, 224)
- Windows targets will always timeout after 120s, then `TimeoutError`

**H2. _do_generation() always uses ServerNormalOpsGenerator, ignores scenario template_type**
- `baseline_orchestrator.py` line 425: hardcodes `ServerNormalOpsGenerator`
- Live-compare's `SequenceGenerationService` dispatches to `ServerFileHeavyOpsGenerator` or `DbLoadOpsGenerator` based on template type
- Baseline mode generates wrong operations for `server_file_heavy` or `db_load` scenarios

**H3. _deploy_calibration_csv() also hardcodes ServerNormalOpsGenerator**
- `baseline_orchestrator.py` line 283: `ServerNormalOpsGenerator("calibration", "calibration")`
- Calibration runs with wrong op mix for non-normal scenarios, producing incorrect thread counts

**H4. Emulator stop_test() called with wrong test_id**
- `baseline_execution.py` line 182: constructs `test_id = f"baseline-{baseline_test.id}-lp{lp.id}"`
- Line 183-190: `em_client.start_test()` called with `test_run_id=str(baseline_test.id)` — emulator returns its own test_id
- Code ignores returned test_id and passes locally-constructed one to `stop_test()` — stops wrong/nonexistent test

**H5. _execution_results stored as instance variable — lost on process restart**
- `baseline_orchestrator.py` line 494: `self._execution_results = engine.execute(...)`
- Read in `_do_comparison()` (line 537) and `_do_storing()` (line 586)
- No DB persistence of execution result paths until STORING completes
- Process crash between EXECUTING and STORING loses all result paths permanently

**H6. Vultr list_snapshots() returns ALL account snapshots, not filtered to VM**
- `hypervisor.py` Vultr provider: `GET /snapshots` returns account-wide snapshots
- Unlike Proxmox/vSphere where snapshots are per-VM, Vultr shows all
- Snapshot manager and UI display unrelated snapshots from other instances

**H7. BaselineTestRunResponse schema missing load_profile_ids**
- `schemas.py` `BaselineTestRunResponse` does not include load profile list
- Dashboard falls back to showing all system load profiles instead of run's actual profiles
- LP progress information is incorrect

**H8. ServerCreate/ServerUpdate schemas missing baseline-compare fields**
- `default_loadgen_id`, `default_partner_id`, `service_monitor_patterns` not in create/update schemas
- Admin UI server page does not list these fields
- Cannot set `default_loadgen_id` via API/UI — every baseline test creation needs explicit loadgen_id

**H9. doPickSnapshot() uses snapshot name, not provider_snapshot_id — broken on vSphere**
- `manager.html` line 841: passes `hs.name` to `doPickSnapshot()`
- Searches `_snapshots.find(s => s.provider_snapshot_id === providerSnapshotName)`
- Proxmox: works (provider_id = name)
- vSphere: fails (provider_id = MoRef ID like "3", name = "clean-base") — match always fails

### 12.3 MEDIUM Issues (data quality, robustness, security)

**M1. Emulator config paths hardcoded as Linux — fail on Windows targets**
- `baseline_execution.py` lines 168-175: `/opt/emulator/data/normal`, `/opt/emulator/output`
- `_clean_emulator_dirs()` (lines 311-312): `rm -rf /opt/emulator/output/*`
- Windows targets: paths and commands invalid

**M2. JMeter paths hardcoded to Linux even when loadgen could be Windows**
- `baseline_execution.py` lines 203, 207-210: `/opt/jmeter/bin/jmeter`
- `baseline_orchestrator.py` lines 180-182, 356: `/opt/jmeter/runs/...`
- Windows loadgen: paths invalid

**M3. partner_server lookup has no null check**
- `baseline_execution.py` lines 164-166: `session.get(ServerORM, partner_id)` may return None
- Immediately accesses `.ip_address` — `AttributeError` if partner was deleted after test creation

**M4. _do_comparison() accesses compare_data without null check**
- `baseline_orchestrator.py` lines 531-556: `compare_data.stats_data` crashes if query returns None
- Time window between validation and comparison where data could be removed

**M5. _do_execution() accesses profile_data.thread_count without null check (compare type)**
- `baseline_orchestrator.py` lines 464-469: same pattern as M4

**M6. _deploy_stored_jmx_data() uses local file path that may not exist**
- `baseline_orchestrator.py` line 308: `loadgen_exec.upload(profile_data.jmx_test_case_data, ...)`
- Path was stored during previous run — if results dir was cleaned, upload fails

**M7. loadgen_executor created in per-profile loop but not closed on error**
- `baseline_execution.py` lines 193-201, 263: `loadgen_executor` created inside loop
- `finally` block (line 278) only closes `target_executor`, not `loadgen_executor`
- Leaks SSH connections on the load generator

**M8. Proxmox snapshot names not validated — names with spaces/special chars fail**
- `TakeSnapshotRequest` and `SnapshotBaselineCreate` accept any string
- Proxmox requires alphanumeric + dashes + underscores only
- User enters "Clean OS (Rocky)" — Proxmox API returns 400 with no clear error message

**M9. Admin UI missing emulator_package_grp_id field for Labs**
- `views.py` Lab CRUD page `fields` list does not include `emulator_package_grp_id`
- Cannot configure emulator package through UI — emulator deployment silently skipped

**M10. SnapshotBaselineORM unique constraint prevents reuse of existing snapshots across groups**
- `uq_sb_server_snapshot` on `(server_id, snapshot_id)` prevents two groups using same snapshot
- IntegrityError if user tries to create second group with same snapshot

**M11. No AppConfig settings for baseline-compare mode**
- No `discovery_dir` setting despite `DiscoveryService.__init__` requiring it
- No baseline-specific comparison thresholds or data retention config

**M12. XSS vulnerability in doPickSnapshot() — snapshot names with single quotes break onclick handler**
- `manager.html` line 841: `onclick="doPickSnapshot('${escHtml(hs.name)}')"`
- `escHtml` escapes `&<>"` but NOT single quotes
- Snapshot name `it's-clean` breaks JS string literal — potential injection

### 12.4 LOW Issues (cosmetic, feature parity gaps)

**L1. State machine comparing->completed transition is unreachable**
- `baseline_state_machine.py` line 62 allows `comparing -> completed`
- But `_do_comparison()` always routes to `storing` — dead transition

**L2. Validation checks emulator reachability before snapshot restore**
- Checks against pre-revert VM state — meaningless and wastes network call time

**L3. BaselineTestState has no `paused` state**
- Live-compare has `paused` + `run_mode` (complete/step_by_step)
- Baseline-compare silently only supports `complete` runs — feature parity gap

**L4. Snapshot picker UI does not show `created` timestamp**
- When multiple snapshots share a name (vSphere), users can't distinguish them

**L5. CSS classes for baseline-specific states may be undefined**
- `state-storing` and `state-generating` used by baseline states
- If CSS only defines live-compare state styles, these render without background color

**L6. ComparisonResultORM.target_id may be null in baseline-compare mode**
- Trending/analytics that filter by target_id will silently drop these records

---

## 13. Updated Severity Summary

| Severity | v1-v3 Count | v4 New Count | Total |
|----------|-------------|--------------|-------|
| Critical | 1           | 4            | **5** |
| High     | 2           | 9            | **11**|
| Medium   | 3           | 12           | **15**|
| Low      | 2           | 6            | **8** |
| **Total**| **8**       | **31**       | **39**|

### Updated Priority Order for Fixes

**Must fix before any baseline test run (blockers):**
1. C1+C2: CalibrationResultORM FK / CalibrationEngine type mismatch
2. C3: ComparisonResultORM not created by baseline comparison
3. C4: DiscoveryService constructor + missing methods
4. H2+H3: Hardcoded ServerNormalOpsGenerator
5. H4: Emulator test_id mismatch
6. H5: Execution results not persisted to DB

**Must fix before production use:**
7. H1: wait_for_ssh Windows support
8. H8: ServerCreate/Update missing baseline fields
9. H9: doPickSnapshot broken on vSphere
10. M1+M2: Hardcoded Linux paths
11. M7: loadgen_executor connection leak
12. M12: XSS in snapshot picker

---

## 14. Deep Analysis Pass (v5) — Method-Level Findings

Fifth pass focused on actual method signatures, constructor parameters, API serialization, concurrent access, and migration completeness. Found **22 new issues** not covered in previous passes.

### 14.1 CRITICAL

**C5. ComparisonResultResponse.test_run_id typed as non-optional int, but ORM column is nullable**
- `schemas.py` line 644: `test_run_id: int`
- `orm.py` line 419: `Column(Integer, nullable=True)`
- For baseline-compare results, `test_run_id` is NULL (only `baseline_test_run_id` is set)
- Pydantic raises ValidationError when serializing — breaks `/comparison-results` endpoint

### 14.2 HIGH

**H10. CalibrationEngine constructor receives AppConfig instead of CalibrationConfig**
- `baseline_orchestrator.py` line 322: `CalibrationEngine(self._config)` passes `AppConfig`
- `calibration.py` line 58: expects `CalibrationConfig`
- Accesses `self._config.max_thread_count`, `self._config.observation_duration_sec` etc. — `AttributeError` at runtime
- Live-compare (orchestrator.py line 281) correctly passes `self._config.calibration`

**H11. executor.run() does not exist — should be executor.execute()**
- `baseline_orchestrator.py` lines 181-182: `loadgen_exec.run(f"rm -rf ...")`
- `baseline_orchestrator.py` lines 244-245: `target_exec.run(...)`
- `baseline_execution.py` line 317: `_clean_emulator_dirs` calls `.run()`
- `RemoteExecutor` has `.execute()`, not `.run()` — `AttributeError` at runtime

**H12. StatsParser instantiated with arguments it doesn't accept**
- `baseline_execution.py` lines 82-85: `StatsParser(trim_start_sec=..., trim_end_sec=...)`
- `StatsParser.__init__` accepts no parameters — `TypeError` at construction time

**H13. em_client.get_all_stats() called without required test_run_id argument**
- `baseline_execution.py` line 234: `em_client.get_all_stats()` — no args
- `EmulatorClient.get_all_stats()` requires `test_run_id` as positional parameter
- `TypeError` at runtime during stats collection

**H14. compute_summary() receives wrong data format**
- `baseline_execution.py` line 254: `self._stats_parser.compute_summary(stats_json)`
- `stats_json` is the full AllStatsResponse dict (with `metadata`, `samples`, `summary` keys)
- `compute_summary()` expects `List[Dict]` of sample records
- Iterating a dict yields string keys, all metrics come back as zero

**H15. snap.group_id = default_subgroup.id set before session.flush()**
- `baseline_test_runs.py` line 576: `snap.group_id = default_subgroup.id`
- `default_subgroup` was just created (line 567) and added (line 573) but NOT flushed
- `default_subgroup.id` is `None` until flush/commit — `group_id` persisted as NULL

**H16. No concurrency guard on shared loadgen**
- `baseline_test_runs.py` lines 161-177: Multiple test runs can start simultaneously using same `loadgenerator_id`
- No check if loadgen is already in use by another active test run
- Two concurrent tests on same loadgen corrupt JMeter results, calibration data

**H17. sync_tree() has no concurrency protection**
- `snapshot_manager.py` + `baseline_test_runs.py` line 264-275
- Sync button in UI + take_snapshot (which calls sync_tree internally) can run simultaneously
- Race on insert violates `(server_id, provider_snapshot_id)` unique constraint — IntegrityError

**H18. Migration missing snapshot_id column in snapshot_groups table**
- `add_snapshot_groups.sql` lines 26-34: `CREATE TABLE snapshot_groups` omits `snapshot_id` column
- ORM model `SnapshotGroupORM` has `snapshot_id = Column(Integer, ForeignKey("snapshots.id"))`
- `setup_proxmox_lab.py` adds it via ALTER TABLE, but standalone migration is incomplete

### 14.3 MEDIUM

**M13. Calibration JTL paths not unique across concurrent runs**
- `calibration.py` lines 408, 498: hardcoded `/tmp/calibration.jtl`, `/tmp/calibration-stability.jtl`
- No test_run_id or server_id in filename
- Two concurrent baseline test runs sharing loadgen write same file — data corruption

**M14. exec_result.stats_summary is a dataclass, not JSON-serializable**
- `baseline_orchestrator.py` line 621-633: assigns `StatsSummary` dataclass to `SnapshotProfileDataORM.stats_summary` (JSON column)
- `json.dumps` on dataclass — `TypeError: Object of type StatsSummary is not JSON serializable`
- Need `dataclasses.asdict(stats_summary)` before assignment

**M15. Start endpoint returns hardcoded "state": "validating" but actual state is "created"**
- `baseline_test_runs.py` line 179: response has `"state": "validating"`
- Background thread hasn't transitioned the state yet — misleads UI/API consumers

**M16. create_snapshot_group silently skips snapshot reassignment**
- `baseline_test_runs.py` line 719: `if snap_obj and not snap_obj.group_id` — guard
- If snapshot already belongs to another subgroup, it's silently NOT moved to the new one
- No error/warning raised — user thinks link succeeded

**M17. take_snapshot group_id not validated against correct server**
- `baseline_test_runs.py` lines 291-294: validates `group_id` exists but not that the group's parent baseline belongs to the same server
- Snapshot could be linked to a subgroup from a different server's hierarchy

**M18. Step 3 of test creation wizard always triggers hypervisor sync**
- `create.html` line 172/288: entering step 3 calls `snapshots/sync` every time
- No debounce or caching — going back/forth between steps hammers the hypervisor API

**M19. escHtml double-encodes snapshot names in onclick handler**
- `manager.html` line 841: `onclick="doPickSnapshot('${escHtml(hs.name)}')"`
- HTML entities (e.g., `&amp;`) passed as literal strings to JS function
- Snapshot names with `&`, `<`, `>`, `"` get mangled in the lookup

**M20. Emulator client and SSH connections not cleaned between profile iterations**
- `baseline_execution.py` lines 120-279: `EmulatorClient` created at line 160 never closed between loop iterations
- Emulator state (running tests, stats) carries over between profiles

**M21. Missing indexes on baseline_test_runs table**
- `add_baseline_compare_tables.sql`: no indexes on `server_id`, `state`, `created_at`
- API queries filter by these columns and ORDER BY created_at DESC

### 14.4 LOW

**L7. baseline_stats_summary parameter in run_baseline_comparison() is dead code**
- `comparison.py` line 101: `baseline_stats_summary` accepted but never used

**L8. Emulator not reset between profile calibrations**
- `baseline_orchestrator.py` lines 329-374: no emulator stop/reset between profiles
- Accumulated stats from profile 1 calibration may bleed into profile 2

**L9. Compare snapshot filter in create wizard is a no-op**
- `create.html` line 299: `liveSnaps.filter(s => s.is_baseline || s.id)` — `s.id` always truthy
- Dropdown shows all snapshots instead of only those with stored data

---

## 15. Final Severity Summary (v1-v5)

| Severity | v1-v3 | v4 | v5 | Total |
|----------|-------|-----|-----|-------|
| Critical | 1     | 4   | 1   | **6** |
| High     | 2     | 9   | 9   | **20**|
| Medium   | 3     | 12  | 9   | **24**|
| Low      | 2     | 6   | 3   | **11**|
| **Total**| **8** | **31**| **22**| **61**|

### Updated Top-Priority Fix Order

**Tier 1 — Absolute blockers (will crash immediately):**
1. C1+C2: CalibrationResultORM FK / CalibrationEngine type (TestRunORM vs BaselineTestRunORM)
2. C4: DiscoveryService constructor + missing methods
3. H10: CalibrationEngine receives AppConfig not CalibrationConfig
4. H11: executor.run() → executor.execute()
5. H12: StatsParser constructor args
6. H13: get_all_stats() missing test_run_id
7. H14: compute_summary() wrong data format

**Tier 2 — Data corruption / wrong results:**
8. C3: ComparisonResultORM never created
9. C5: ComparisonResultResponse.test_run_id non-nullable schema
10. H2+H3: Hardcoded ServerNormalOpsGenerator
11. H4: Emulator stop_test wrong test_id
12. H15: snap.group_id NULL (unflushed ID)
13. M13: Calibration JTL path collision
14. M14: StatsSummary not JSON-serializable

**Tier 3 — Concurrency / robustness:**
15. H16: No loadgen concurrency guard
16. H17: sync_tree race condition
17. H5: Execution results in-memory only
18. H18: Migration missing snapshot_id column
