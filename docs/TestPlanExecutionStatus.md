# Test Plan Execution Status

## Tracking Sheet

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

---

## Phase 1: Pre-flight Checks

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 1.1 | Infrastructure reachability | NOT STARTED | |
| 1.2 | Snapshot existence on Proxmox | NOT STARTED | |
| 1.3 | API smoke test | NOT STARTED | |
| 1.4 | Regression — migrated runs | NOT STARTED | |
| 1.5 | API validation errors | NOT STARTED | |

## Phase 2: Run 1 — New Baseline (2 targets)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 2.1 | Create test run | NOT STARTED | |
| 2.2 | Start and monitor | NOT STARTED | |
| 2.3 | Verify stored data | NOT STARTED | |
| 2.4 | Verify path isolation | NOT STARTED | |
| 2.5 | UI validation | NOT STARTED | |

## Phase 3: Prepare Subgroup Snapshots

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 3.1 | Install agent / simulate change | NOT STARTED | |
| 3.2 | Take snapshots on Proxmox | NOT STARTED | |
| 3.3 | Sync snapshots to DB | NOT STARTED | |
| 3.4 | Verify snapshot tree | NOT STARTED | |

## Phase 4: Run 2 — Compare Subgroup vs Group

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 4.1 | Create test run | NOT STARTED | |
| 4.2 | Start and monitor | NOT STARTED | |
| 4.3 | Verify comparison results | NOT STARTED | |
| 4.4 | UI validation | NOT STARTED | |

## Phase 5: Prepare Second Subgroup Snapshots

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 5.1 | Make a change on both targets | NOT STARTED | |
| 5.2 | Take snapshots | NOT STARTED | |
| 5.3 | Sync and verify | NOT STARTED | |
| 5.4 | Verify snapshot tree | NOT STARTED | |

## Phase 6: Run 3 — Compare New Subgroup vs Group

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 6.1 | Create test run | NOT STARTED | |
| 6.2 | Validation checks | NOT STARTED | |
| 6.3 | State progression | NOT STARTED | |
| 6.4 | Verify | NOT STARTED | |

## Phase 7: Prepare Fourth Snapshots

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 7.1 | Create agent-v3 snapshots | NOT STARTED | |
| 7.2 | Sync and verify | NOT STARTED | |
| 7.3 | Verify full tree | NOT STARTED | |

## Phase 8: Run 4 — Compare Against Previous Subgroup

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 8.1 | Create test run | NOT STARTED | |
| 8.2 | Validation checks | NOT STARTED | |
| 8.3 | State progression | NOT STARTED | |
| 8.4 | Verify | NOT STARTED | |
| 8.5 | Final snapshot tree | NOT STARTED | |

## Phase 9: Error Handling

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 9.1 | Target unreachable | NOT STARTED | |
| 9.2 | Snapshot missing | NOT STARTED | |
| 9.3 | Cancel | NOT STARTED | |

## Phase 10: UI Validation

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 10.1 | Create page | NOT STARTED | |
| 10.2 | List page | NOT STARTED | |
| 10.3 | Dashboard page | NOT STARTED | |
| 10.4 | Results page | NOT STARTED | |
