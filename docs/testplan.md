# Test Plan — Baseline-Compare Multi-Server

## Prerequisites & Environment

### Codebase
- **Project root**: `C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing`
- **Orchestrator source**: `orchestrator/src/orchestrator/`
- **Config**: `orchestrator/config/orchestrator.yaml`
- **Credentials**: `orchestrator/config/credentials.json`
- **Migrations**: `orchestrator/migrations/`
- **Templates**: `orchestrator/src/orchestrator/templates/baseline_tests/`
- **Results dir**: `orchestrator/results/` (relative to orchestrator root)

### Starting the Orchestrator
```bash
cd C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator
python -m orchestrator.cli serve --host 0.0.0.0 --port 8000
```
- FastAPI app runs at `http://localhost:8000`
- Web UI at `http://localhost:8000/baseline-tests/`
- API base: `http://localhost:8000/api/`

### Database
- **SQL Server** on localhost, database `orchestrator`
- **Connection**: `mssql+pyodbc://@localhost/orchestrator?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes`
- Windows trusted auth, no username/password needed
- Use SSMS or `sqlcmd` for direct queries

### Credentials (from credentials.json)

| Target | Username | Password |
|--------|----------|----------|
| Linux servers (SSH) | root | Test1234! |
| Windows servers (WinRM) | Administrator | Test1234! |
| Proxmox API | root@pam!mytoken | `5b31793a-a852-470c-9f0b-968309223007` |

Proxmox API token header: `Authorization: PVEAPIToken=root@pam!mytoken=5b31793a-a852-470c-9f0b-968309223007`

### Key Files for Debugging
- **Orchestrator logs**: stdout/stderr of the `serve` command
- **State machine**: `core/baseline_state_machine.py`
- **Orchestrator flow**: `core/baseline_orchestrator.py` — `_do_setup`, `_do_calibration`, `_do_generation`, `_do_execution`, `_do_comparison`, `_do_storing`
- **Execution engine**: `core/baseline_execution.py` — barrier pattern per load profile
- **Validation**: `core/baseline_validation.py` — pre-flight checks
- **Calibration**: `core/calibration.py` — binary search for thread count
- **API endpoints**: `api/baseline_test_runs.py`
- **ORM models**: `models/orm.py` — `BaselineTestRunORM`, `BaselineTestRunTargetORM`
- **Schemas**: `api/schemas.py` — `BaselineTestRunCreate`, `BaselineTestRunResponse`

### Design Document
Full architecture: `docs/BASELINE_MULTI_SERVER_DESIGN.md`
Implementation status: `docs/status.md`

---

## Overview

Validate the entire baseline-compare flow end-to-end with 2 targets (Linux + Windows) through a realistic 4-run progression across a snapshot hierarchy.

### State Flows by Test Type

```
new_baseline:                 created → validating → setting_up → calibrating → generating → executing → storing → completed
compare:                      created → validating → setting_up → executing → comparing → storing → completed
compare_with_new_calibration: created → validating → setting_up → calibrating → generating → executing → comparing → storing → completed
```

Key differences:
- `compare` **skips** calibrating + generating (reuses stored thread counts + ops sequences from compare_snapshot)
- `new_baseline` **skips** comparing (no baseline to compare against)
- Only `new_baseline` marks the test snapshot as `is_baseline = True`
- ALL types store `snapshot_profile_data` on the test snapshot

### Snapshot Hierarchy (built during testing)

```
Server 8 (target-rky-01, VMID 410):           Server 9 (TARGET-WIN-01, VMID 321):
  clean-rocky-baseline (id=3)                    clean-win-baseline (id=4)
    └── agent-v1-rocky (id=A)                      └── agent-v1-win (id=B)
        └── agent-v2-rocky (id=C)                      └── agent-v2-win (id=D)
            └── agent-v3-rocky (id=E)                      └── agent-v3-win (id=F)

IDs A-F are assigned by the DB during test execution. Record them as you go.
```

### 4-Run Progression

| Run | Type | Test Snapshot | Compare Snapshot | Purpose |
|-----|------|--------------|-----------------|---------|
| 1 | `new_baseline` | group (3, 4) | — | Capture clean baseline at group level |
| 2 | `compare` | subgroup (A, B) | group (3, 4) | Compare agent-v1 against clean baseline |
| 3 | `compare` | new subgroup (C, D) | group (3, 4) | Compare agent-v2 against clean baseline |
| 4 | `compare` | latest (E, F) | previous (C, D) | Compare agent-v3 against agent-v2 |

### Lab Inventory

| ID | Hostname | IP | OS | Role | Default Loadgen |
|----|----------|----|----|------|-----------------|
| 7 | loadgen-rky-01 | 10.0.0.83 | linux | Load Generator | — |
| 8 | target-rky-01 | 10.0.0.92 | linux | Target | 7 |
| 9 | TARGET-WIN-01 | 10.0.0.91 | windows | Target | 7 |

Lab ID=4, Scenario ID=3, Proxmox host=10.0.0.72:8006

---

## Phase 1: Pre-flight Checks

### 1.1: Infrastructure reachability
- [ ] `ping 10.0.0.83` (loadgen) responds
- [ ] `ping 10.0.0.92` (target-rky-01) responds
- [ ] `ping 10.0.0.91` (TARGET-WIN-01) responds
- [ ] SSH to 10.0.0.83 with root/Test1234! works
- [ ] SSH to 10.0.0.92 with root/Test1234! works
- [ ] WinRM to 10.0.0.91 with Administrator/Test1234! works
- [ ] Proxmox API at 10.0.0.72:8006 responds

### 1.2: Snapshot existence on Proxmox
- [ ] Snapshot `clean-rocky-baseline` exists on VMID 410
- [ ] Snapshot `clean-win-baseline` exists on VMID 321

### 1.3: API smoke test
- [ ] `GET /api/baseline-tests` returns 200
- [ ] `GET /api/admin/servers` returns servers 7, 8, 9
- [ ] `GET /api/admin/load-profiles` returns profiles 1 (low), 2 (medium), 3 (high)

### 1.4: Regression — migrated runs still accessible
- [ ] `GET /api/baseline-tests/1` returns response with `targets` array (1 entry, target_id=8)
- [ ] `GET /api/baseline-tests/2` returns response with `targets` array (1 entry, target_id=9)
- [ ] `GET /api/baseline-tests?server_id=8` includes run 1
- [ ] `GET /api/baseline-tests?server_id=9` includes run 2

### 1.5: API validation errors
- [ ] `POST /api/baseline-tests` with `targets: []` → 422
- [ ] `POST /api/baseline-tests` with `server_id: 999` → 404
- [ ] `POST /api/baseline-tests` with `test_type: "compare"` without `compare_snapshot_id` → 400
- [ ] `POST /api/baseline-tests` with `test_type: "new_baseline"` and `compare_snapshot_id` set → 400

---

## Phase 2: Run 1 — New Baseline at Group Level (2 targets)

Capture clean baseline data on root snapshots (3, 4). Both targets run in parallel with barriers.

### 2.1: Create test run

```
POST /api/baseline-tests
{
  "scenario_id": 3,
  "test_type": "new_baseline",
  "load_profile_ids": [1],
  "targets": [
    {"server_id": 8, "test_snapshot_id": 3},
    {"server_id": 9, "test_snapshot_id": 4}
  ]
}
```

**Record:** Run ID = ____

**Checklist:**
- [ ] Returns 201
- [ ] Response `targets` has 2 entries
- [ ] Both targets have `loadgenerator_id` = 7 (resolved from default)
- [ ] `targets[0].test_snapshot_id` = 3, `targets[1].test_snapshot_id` = 4
- [ ] State = `created`

### 2.2: Start and monitor

```
POST /api/baseline-tests/{run_id}/start
```

Monitor via `GET /api/baseline-tests/{run_id}` and orchestrator logs.

**State progression:**
- [ ] `created` → `validating`: Pre-flight checks all targets + loadgen
- [ ] `validating` → `setting_up`
- [ ] **Setting up** (both targets):
  - [ ] JMeter deployed/verified on loadgen (10.0.0.83)
  - [ ] Run dirs created: `lg_7/target_8/` and `lg_7/target_9/`
  - [ ] JMX templates + calibration CSVs uploaded for both targets
  - [ ] VM 410 reverted to `clean-rocky-baseline`
  - [ ] VM 321 reverted to `clean-win-baseline`
  - [ ] SSH/WinRM reachable after restore on both
  - [ ] Emulator deployed on both targets
  - [ ] Discovery writes `os_kind`, `os_major_ver`, `os_minor_ver` to both `baseline_test_run_targets` rows
- [ ] `setting_up` → `calibrating`
- [ ] **Calibrating** (sequential per target, per LP):
  - [ ] Server 8 calibrated for LP 1 (low) — binary search completes
  - [ ] Server 9 calibrated for LP 1 (low) — binary search completes
  - [ ] `calibration_results` has 2 rows (server 8 + server 9)
- [ ] `calibrating` → `generating`
- [ ] **Generating**:
  - [ ] Ops sequence CSVs generated for both servers
  - [ ] Uploaded to loadgen: `target_8/ops_sequence_low.csv` and `target_9/ops_sequence_low.csv`
- [ ] `generating` → `executing`
- [ ] **Executing** (barrier pattern for LP 1):
  - [ ] Phase 1: BOTH VMs restored to their respective snapshots
  - [ ] Phase 2: BOTH emulators configured + stats started
  - [ ] Phase 3: BOTH JMeter instances started (different target IPs, same loadgen)
  - [ ] Phase 4: Single `time.sleep` — NOT two separate sleeps
  - [ ] Phase 5: BOTH JMeter stopped, BOTH stats collected
- [ ] `executing` → `storing` (skips comparing — new_baseline)
- [ ] **Storing**:
  - [ ] `snapshot_profile_data` row created for snapshot 3, LP 1
  - [ ] `snapshot_profile_data` row created for snapshot 4, LP 1
  - [ ] Both rows have non-null `stats_data`, `jtl_data`, `stats_summary`, `thread_count`
  - [ ] Snapshots 3 and 4 `is_baseline` set to True
- [ ] `storing` → `completed`
- [ ] Final state = `completed`, verdict = NULL (new_baseline has no comparison)

### 2.3: Verify stored data

```sql
-- Both snapshots should have profile data
SELECT snapshot_id, load_profile_id, thread_count,
       CASE WHEN stats_data IS NOT NULL THEN 'yes' ELSE 'no' END as has_stats,
       CASE WHEN jtl_data IS NOT NULL THEN 'yes' ELSE 'no' END as has_jtl
FROM snapshot_profile_data WHERE snapshot_id IN (3, 4);

-- Both targets should have calibration results
SELECT server_id, load_profile_id, thread_count, status
FROM calibration_results WHERE baseline_test_run_id = {run_id};

-- Both targets should have discovery data
SELECT target_id, os_kind, os_major_ver, os_minor_ver
FROM baseline_test_run_targets WHERE baseline_test_run_id = {run_id};

-- Both snapshots marked as baseline
SELECT id, name, is_baseline FROM snapshots WHERE id IN (3, 4);
```

- [ ] 2 `snapshot_profile_data` rows (one per snapshot), both with stats + jtl
- [ ] 2 `calibration_results` rows, both status='completed', thread_count > 0
- [ ] 2 targets with `os_kind` populated ("Rocky Linux" and "Windows Server" or similar)
- [ ] Both snapshots `is_baseline` = 1

**Record thread counts:** Server 8 = ____ threads, Server 9 = ____ threads

### 2.4: Verify path isolation

**On loadgen (10.0.0.83):**
```bash
ls -la /opt/jmeter/runs/baseline_{run_id}/lg_7/target_8/
ls -la /opt/jmeter/runs/baseline_{run_id}/lg_7/target_9/
```
- [ ] Both directories exist with `test.jmx`, `calibration_ops.csv`, `ops_sequence_low.csv`, `results_low.jtl`

**On orchestrator (results dir):**
- [ ] `results/{run_id}/server_8/stats/lp1_stats.json` exists with valid `samples` array
- [ ] `results/{run_id}/server_8/jtl/lp1.jtl` exists
- [ ] `results/{run_id}/server_9/stats/lp1_stats.json` exists with valid `samples` array
- [ ] `results/{run_id}/server_9/jtl/lp1.jtl` exists

### 2.5: UI validation after Run 1

- [ ] List page shows the run with server name + target count
- [ ] Dashboard shows state=completed, both targets' discovery info
- [ ] Results page shows stored profile data for both snapshots

---

## Phase 3: Prepare Subgroup Snapshots

Before Run 2, create child snapshots with an agent installed.

### 3.1: Install agent (or simulate a change) on both targets

The purpose of this step is to create a VM state that differs from the clean baseline, so the compare run has something to measure. You can either install an actual security agent or simulate a change (e.g., install a package, start a CPU-consuming service, change a config).

**Option A — Simulate with a dummy service (fastest for testing):**

**Server 8 (Linux - SSH to 10.0.0.92):**
```bash
ssh root@10.0.0.92
# Create a small background CPU consumer to simulate agent overhead
cat > /usr/local/bin/fake-agent.sh << 'SCRIPT'
#!/bin/bash
while true; do head -c 1M /dev/urandom | md5sum > /dev/null; sleep 0.5; done
SCRIPT
chmod +x /usr/local/bin/fake-agent.sh
nohup /usr/local/bin/fake-agent.sh &
```

**Server 9 (Windows - WinRM/RDP to 10.0.0.91):**
```powershell
# Create a small background task to simulate agent overhead
$script = {while($true){1..1000|%{[math]::Sqrt($_)}>$null; Start-Sleep -Milliseconds 500}}
Start-Job -ScriptBlock $script -Name "FakeAgent"
```

**Option B — Install actual agent** (if you have installer packages, follow your agent's install docs)

- [ ] Change applied on target-rky-01
- [ ] Change applied on TARGET-WIN-01

### 3.2: Take snapshots on Proxmox

Via Proxmox API (or Proxmox UI at https://10.0.0.72:8006):
```bash
TOKEN="PVEAPIToken=root@pam!mytoken=5b31793a-a852-470c-9f0b-968309223007"

# Linux target (VMID 410)
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/410/snapshot" \
  -H "Authorization: $TOKEN" \
  -d "snapname=agent-v1-rocky&description=Agent v1 installed"

# Windows target (VMID 321)
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/321/snapshot" \
  -H "Authorization: $TOKEN" \
  -d "snapname=agent-v1-win&description=Agent v1 installed"
```
- [ ] Snapshot `agent-v1-rocky` created on VMID 410
- [ ] Snapshot `agent-v1-win` created on VMID 321

### 3.3: Sync snapshots to orchestrator DB

```
POST /api/servers/8/snapshots/sync
POST /api/servers/9/snapshots/sync
```

Then verify:
```
GET /api/servers/8/snapshots
GET /api/servers/9/snapshots
```

- [ ] `agent-v1-rocky` appears in server 8 snapshots with `parent_id` pointing to snapshot 3
- [ ] `agent-v1-win` appears in server 9 snapshots with `parent_id` pointing to snapshot 4

**Record snapshot IDs:** agent-v1-rocky = ____ (A), agent-v1-win = ____ (B)

### 3.4: Verify snapshot tree

```
GET /api/servers/8/snapshots/tree
GET /api/servers/9/snapshots/tree
```

- [ ] Tree shows `clean-rocky-baseline` → `agent-v1-rocky` parent-child relationship
- [ ] Tree shows `clean-win-baseline` → `agent-v1-win` parent-child relationship

---

## Phase 4: Run 2 — Compare Subgroup vs Group (2 targets)

Compare agent-v1 snapshots against the clean baseline. Tests the `compare` flow with snapshot hierarchy validation.

### 4.1: Create test run

```
POST /api/baseline-tests
{
  "scenario_id": 3,
  "test_type": "compare",
  "load_profile_ids": [1],
  "targets": [
    {"server_id": 8, "test_snapshot_id": A, "compare_snapshot_id": 3},
    {"server_id": 9, "test_snapshot_id": B, "compare_snapshot_id": 4}
  ]
}
```

(Replace A, B with actual snapshot IDs from Phase 3)

**Record:** Run ID = ____

**Checklist:**
- [ ] Returns 201
- [ ] `targets[0]`: test_snapshot=A, compare_snapshot=3
- [ ] `targets[1]`: test_snapshot=B, compare_snapshot=4
- [ ] State = `created`

### 4.2: Start and monitor

```
POST /api/baseline-tests/{run_id}/start
```

**State progression for `compare` type:**

`created → validating → setting_up → executing → comparing → storing → completed`

Note: `compare` type **skips** `calibrating` and `generating` entirely. Thread counts and ops sequences come from the stored `snapshot_profile_data` on the compare snapshot.

- [ ] `validating`:
  - [ ] Snapshot hierarchy validated — A is child of 3, B is child of 4
  - [ ] Stored data verified — snapshot 3 and 4 have `snapshot_profile_data` for LP 1
- [ ] `setting_up`:
  - [ ] Both VMs reverted to their TEST snapshots (A, B) — the agent-installed ones
  - [ ] Stored JMX data from compare snapshots (3, 4) deployed to loadgen (NOT calibration CSV)
  - [ ] Emulator deployed on both
  - [ ] Discovery captures agent version info in `baseline_test_run_targets`
- [ ] **NO `calibrating` state** — thread counts reused from `snapshot_profile_data` on compare snapshots (3, 4)
- [ ] **NO `generating` state** — ops sequences reused from stored data
- [ ] `executing` (barrier pattern):
  - [ ] BOTH VMs restored, configured, JMeter started with stored thread counts, single wait, collected
  - [ ] Results saved per server: `results/{run_id}/server_8/...` and `results/{run_id}/server_9/...`
- [ ] `comparing`:
  - [ ] Cohen's d analysis runs for each target (test stats vs stored baseline stats)
  - [ ] `comparison_results` rows created (1 per target per LP = 2 total)
  - [ ] Each comparison has `verdict` (passed/failed/warning)
- [ ] `storing`:
  - [ ] `snapshot_profile_data` rows created for test snapshots A and B
  - [ ] A and B are NOT marked `is_baseline` (only `new_baseline` type does that)
- [ ] `completed`:
  - [ ] Overall `verdict` set based on comparison results

### 4.3: Verify comparison results

```sql
-- Comparison results for this run
SELECT id, server_id, load_profile_id, comparison_type, verdict,
       violation_count, summary_text
FROM comparison_results WHERE baseline_test_run_id = {run_id};

-- Stored data now exists for subgroup snapshots too
SELECT snapshot_id, load_profile_id, thread_count
FROM snapshot_profile_data WHERE snapshot_id IN (A, B);
```

- [ ] 2 comparison results (server 8 + server 9)
- [ ] Each has `verdict` set
- [ ] Snapshots A and B now have `snapshot_profile_data`

### 4.4: UI validation

- [ ] Dashboard shows comparison verdict
- [ ] Results page shows comparison table with 2 rows
- [ ] Detail modal shows Cohen's d values per metric

---

## Phase 5: Prepare Second Subgroup Snapshots

Create new child snapshots (agent v2) under agent-v1.

### 5.1: Make a change on both targets

Revert to agent-v1 snapshots (A, B) via Proxmox, apply a different change to simulate a version upgrade. For example, increase the fake-agent's CPU load or install an additional service.

```bash
TOKEN="PVEAPIToken=root@pam!mytoken=5b31793a-a852-470c-9f0b-968309223007"

# Revert server 8 to snapshot A
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/410/snapshot/agent-v1-rocky/rollback" \
  -H "Authorization: $TOKEN"

# Revert server 9 to snapshot B
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/321/snapshot/agent-v1-win/rollback" \
  -H "Authorization: $TOKEN"
```

Wait for VMs to come back up, then SSH/WinRM and apply a different change (e.g., run a second fake-agent process, or change `sleep 0.5` to `sleep 0.2` for more load).

- [ ] VMs reverted to agent-v1 snapshots
- [ ] New change applied on target-rky-01
- [ ] New change applied on TARGET-WIN-01

### 5.2: Take snapshots

```bash
TOKEN="PVEAPIToken=root@pam!mytoken=5b31793a-a852-470c-9f0b-968309223007"

curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/410/snapshot" \
  -H "Authorization: $TOKEN" \
  -d "snapname=agent-v2-rocky&description=Agent v2 installed"

curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/321/snapshot" \
  -H "Authorization: $TOKEN" \
  -d "snapname=agent-v2-win&description=Agent v2 installed"
```
- [ ] `agent-v2-rocky` created on Proxmox
- [ ] `agent-v2-win` created on Proxmox

### 5.3: Sync and verify

```
POST /api/servers/8/snapshots/sync
POST /api/servers/9/snapshots/sync
```

- [ ] `agent-v2-rocky` has `parent_id` = A (child of agent-v1-rocky)
- [ ] `agent-v2-win` has `parent_id` = B (child of agent-v1-win)

**Record snapshot IDs:** agent-v2-rocky = ____ (C), agent-v2-win = ____ (D)

### 5.4: Verify snapshot tree (3 levels deep now)

```
GET /api/servers/8/snapshots/tree
```
- [ ] Shows: `clean-rocky-baseline` → `agent-v1-rocky` → `agent-v2-rocky`

---

## Phase 6: Run 3 — Compare New Subgroup vs Group (2 targets)

Compare agent-v2 against the original clean baseline (NOT against agent-v1). This tests comparing a grandchild snapshot against the root.

### 6.1: Create test run

```
POST /api/baseline-tests
{
  "scenario_id": 3,
  "test_type": "compare",
  "load_profile_ids": [1],
  "targets": [
    {"server_id": 8, "test_snapshot_id": C, "compare_snapshot_id": 3},
    {"server_id": 9, "test_snapshot_id": D, "compare_snapshot_id": 4}
  ]
}
```

**Record:** Run ID = ____

### 6.2: Validation checks

- [ ] Snapshot hierarchy valid — C is grandchild of 3 (C → A → 3), D is grandchild of 4 (D → B → 4)
- [ ] Stored data for compare snapshots (3, 4) still exists from Run 1

### 6.3: State progression (same `compare` flow as Run 2)

`created → validating → setting_up → executing → comparing → storing → completed`

(Skips `calibrating` and `generating` — reuses stored thread counts and ops sequences from compare snapshots 3, 4)

- [ ] `setting_up`: VMs reverted to TEST snapshots (C, D), stored JMX data from compare snapshots (3, 4) deployed
- [ ] `executing`: Both targets execute with barrier pattern, using stored thread counts from snapshots 3, 4
- [ ] `comparing`: Cohen's d runs against group-level stored data (snapshot 3 and 4)
- [ ] `comparison_results` created for this run (2 rows)
- [ ] `storing`: `snapshot_profile_data` created for snapshots C and D (NOT marked is_baseline)

### 6.4: Verify

```sql
-- C and D now have stored data
SELECT snapshot_id, thread_count FROM snapshot_profile_data
WHERE snapshot_id IN (C, D);

-- Comparison used group-level baseline
SELECT server_id, verdict, summary_text FROM comparison_results
WHERE baseline_test_run_id = {run_id};
```

- [ ] Snapshots C, D have `snapshot_profile_data` rows
- [ ] 2 comparison results with verdicts
- [ ] State = `completed`, overall verdict set

---

## Phase 7: Prepare Fourth Snapshots

### 7.1: Create agent-v3 snapshots

Revert to agent-v2 snapshots (C, D), apply another change (e.g., third fake-agent process or different config), take snapshots.

```bash
TOKEN="PVEAPIToken=root@pam!mytoken=5b31793a-a852-470c-9f0b-968309223007"

# Revert to agent-v2 snapshots
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/410/snapshot/agent-v2-rocky/rollback" \
  -H "Authorization: $TOKEN"
curl -k -X POST "https://10.0.0.72:8006/api2/json/nodes/proxmox/qemu/321/snapshot/agent-v2-win/rollback" \
  -H "Authorization: $TOKEN"
```

Wait for VMs, apply change, then take snapshots.

- [ ] VMs reverted to agent-v2 snapshots
- [ ] Change applied on both targets
- [ ] `agent-v3-rocky` created on VMID 410
- [ ] `agent-v3-win` created on VMID 321

### 7.2: Sync and verify

```
POST /api/servers/8/snapshots/sync
POST /api/servers/9/snapshots/sync
```

- [ ] `agent-v3-rocky` has `parent_id` = C
- [ ] `agent-v3-win` has `parent_id` = D

**Record snapshot IDs:** agent-v3-rocky = ____ (E), agent-v3-win = ____ (F)

### 7.3: Verify full tree (4 levels)

```
GET /api/servers/8/snapshots/tree
```
- [ ] `clean-rocky-baseline` → `agent-v1-rocky` → `agent-v2-rocky` → `agent-v3-rocky`

---

## Phase 8: Run 4 — Compare Against Previous Subgroup (2 targets)

Compare agent-v3 against agent-v2 (NOT against the root). This tests comparing sibling-level snapshots — measuring the delta between two agent versions.

### 8.1: Create test run

```
POST /api/baseline-tests
{
  "scenario_id": 3,
  "test_type": "compare",
  "load_profile_ids": [1],
  "targets": [
    {"server_id": 8, "test_snapshot_id": E, "compare_snapshot_id": C},
    {"server_id": 9, "test_snapshot_id": F, "compare_snapshot_id": D}
  ]
}
```

**Record:** Run ID = ____

### 8.2: Validation checks

- [ ] Snapshot hierarchy valid — E is child of C, F is child of D
- [ ] Stored data for compare snapshots C and D exists from Run 3

### 8.3: State progression (same `compare` flow)

`created → validating → setting_up → executing → comparing → storing → completed`

(Skips `calibrating` and `generating` — reuses stored thread counts and ops sequences from compare snapshots C, D)

- [ ] `setting_up`: VMs reverted to TEST snapshots (E, F), stored JMX data from compare snapshots (C, D) deployed
- [ ] `executing`: Both targets execute with barrier pattern, using stored thread counts from snapshots C, D
- [ ] `comparing`: Cohen's d runs against Run 3's stored data (snapshots C, D) — measures agent-v3 vs agent-v2 delta
- [ ] `comparison_results` created (2 rows)
- [ ] `storing`: `snapshot_profile_data` created for snapshots E and F (NOT marked is_baseline)
- [ ] State = `completed`, verdict set

### 8.4: Verify

```sql
-- Full snapshot_profile_data chain
SELECT snapshot_id, load_profile_id, thread_count
FROM snapshot_profile_data
WHERE snapshot_id IN (3, 4, A, B, C, D, E, F)
ORDER BY snapshot_id;

-- All comparison results across runs
SELECT cr.baseline_test_run_id, cr.server_id, cr.verdict, cr.summary_text
FROM comparison_results cr
WHERE cr.baseline_test_run_id IN ({run2_id}, {run3_id}, {run4_id})
ORDER BY cr.baseline_test_run_id, cr.server_id;
```

- [ ] 8 `snapshot_profile_data` rows total (2 per run × 4 runs)
- [ ] 6 `comparison_results` rows total (2 per compare run × 3 compare runs)
- [ ] Snapshots E, F have data stored

### 8.5: Final snapshot tree verification

```
GET /api/servers/8/snapshots/tree
```

Expected:
```
clean-rocky-baseline (baseline, has data)
  └── agent-v1-rocky (has data)
      └── agent-v2-rocky (has data)
          └── agent-v3-rocky (has data)
```

- [ ] All 4 snapshots have `has_data` badge in tree view
- [ ] `clean-rocky-baseline` has `baseline` badge
- [ ] Same structure confirmed for server 9

---

## Phase 9: Error Handling

### 9.1: Target unreachable
- [ ] Shut down target-rky-01 (VMID 410)
- [ ] Create + start a test run targeting server 8
- [ ] Validation fails with "target not reachable"
- [ ] State = `failed`, error_message populated

### 9.2: Snapshot missing on hypervisor
- [ ] Create test with a bogus snapshot → validation fails

### 9.3: Cancel
- [ ] Start a test, then `POST /api/baseline-tests/{id}/cancel`
- [ ] State → `cancelled`

---

## Phase 10: UI Validation

### 10.1: Create page (`create.html`)
- [ ] Wizard loads labs, scenarios, servers
- [ ] Selecting a server populates loadgen/partner dropdowns
- [ ] Snapshot step loads and displays full snapshot tree (4 levels after all runs)
- [ ] Submit sends `targets: [{server_id, test_snapshot_id, ...}]` format (verify in Network tab)
- [ ] Redirects to dashboard on success

### 10.2: List page (`list.html`)
- [ ] Table shows all 4+ runs
- [ ] Server column shows "target-rky-01 +1" for multi-target runs
- [ ] Snapshot columns show correct IDs from `targets[0]`
- [ ] Filters by server_id and state work
- [ ] Action buttons work

### 10.3: Dashboard page (`dashboard.html`)
- [ ] Server name resolves from `targets[0].target_id`
- [ ] Snapshot section shows names loaded via target's server ID
- [ ] Discovery panel shows per-target OS/agent info (2 rows for 2 targets)
- [ ] Auto-refresh works during active states

### 10.4: Results page (`results.html`)
- [ ] Summary shows both server IDs
- [ ] Comparison results table has 2 rows (one per target)
- [ ] Stored profile data table loads correctly
- [ ] Detail modal opens with Cohen's d values

---

## Execution Order

| # | Phase | What | Depends On |
|---|-------|------|-----------|
| 1 | Phase 1 | Pre-flight checks + API smoke test | — |
| 2 | Phase 2 | **Run 1**: new_baseline on group snapshots (3, 4) | Phase 1 |
| 3 | Phase 3 | Take agent-v1 snapshots (A, B) | Phase 2 |
| 4 | Phase 4 | **Run 2**: compare subgroup (A, B) vs group (3, 4) | Phase 3 |
| 5 | Phase 5 | Take agent-v2 snapshots (C, D) | Phase 4 |
| 6 | Phase 6 | **Run 3**: compare new subgroup (C, D) vs group (3, 4) | Phase 5 |
| 7 | Phase 7 | Take agent-v3 snapshots (E, F) | Phase 6 |
| 8 | Phase 8 | **Run 4**: compare (E, F) vs previous (C, D) | Phase 7 |
| 9 | Phase 9 | Error handling tests | Phase 2 |
| 10 | Phase 10 | UI validation | Phase 8 |

## Tracking Sheet

Fill in as you go:

| Item | Value |
|------|-------|
| Run 1 ID | |
| Run 1 thread count (server 8) | |
| Run 1 thread count (server 9) | |
| Snapshot A ID (agent-v1-rocky) | |
| Snapshot B ID (agent-v1-win) | |
| Run 2 ID | |
| Run 2 verdict | |
| Snapshot C ID (agent-v2-rocky) | |
| Snapshot D ID (agent-v2-win) | |
| Run 3 ID | |
| Run 3 verdict | |
| Snapshot E ID (agent-v3-rocky) | |
| Snapshot F ID (agent-v3-win) | |
| Run 4 ID | |
| Run 4 verdict | |
