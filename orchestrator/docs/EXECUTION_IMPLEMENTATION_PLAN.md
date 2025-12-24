# Execution Implementation Plan

## 1. Issues Found in Current Implementation

### 1.1 Missing State Verification
**Current**: `create_execution` just creates records without verifying current state.
**Expected**: Before any action, execution should READ current state from `test_run_execution` and validate if action is allowed.

### 1.2 No Step Mode Support
**Current**: `run_mode` is stored but not used.
**Expected**:
- `run_mode = continuous`: Run all steps without stopping
- `run_mode = step`: Stop after every step, wait for "continue" command

### 1.3 No Scenario Execution Order
**Current**: No tracking of which scenario is currently executing or completed.
**Expected**:
- Scenarios have an execution order
- Track progress per scenario per loadprofile
- Resume from next incomplete scenario

### 1.4 No Pause Semantics
**Current**: `pause` just sets status to "paused".
**Expected**:
- Pause should complete current scenario/loadprofile first
- Then stop and wait for "continue"

### 1.5 Missing Execution Progress Tracking
**Current**: Only `execution_workflow_state` tracks per-target state.
**Expected**: Need higher-level tracking:
- Which scenario is currently executing?
- Which loadprofile is currently running?
- What's the overall progress?

---

## 2. New Table: `test_run_execution_scenario_status`

### 2.1 Purpose
Tracks execution status per scenario per loadprofile. A scenario executes load on ALL servers in parallel, so we need to track when a loadprofile is complete/failed for the entire scenario.

### 2.2 Schema Design

```
test_run_execution_scenario_status
├── id (PK)
├── test_run_execution_id (FK → test_run_execution.id)
├── scenario_id (FK → scenarios.id)
├── loadprofile (low/medium/high)
├── execution_order (int) - order in which scenarios execute
├── repetition (int) - which repetition (1, 2, 3...)
│
├── status (enum):
│   ├── pending      - not started yet
│   ├── calibrating  - calibration in progress
│   ├── calibrated   - calibration complete
│   ├── executing    - load test running
│   ├── completed    - successfully finished
│   ├── failed       - error occurred
│   └── skipped      - skipped due to previous failure
│
├── phase (enum):
│   ├── calibration
│   ├── base
│   ├── initial
│   └── upgrade
│
├── started_at (datetime)
├── completed_at (datetime)
├── error_message (text)
├── result_summary_json (JSONB) - aggregated results from all targets
│
├── created_at
└── updated_at

Unique: (test_run_execution_id, scenario_id, loadprofile, repetition)
```

### 2.3 Relationships

```
test_run_execution
    │
    └──1:N──► test_run_execution_scenario_status
                  │
                  ├──N:1──► scenarios
                  │
                  └── Contains aggregated status for all targets in scenario
                      (Individual target status still in execution_workflow_state)
```

---

## 3. State Machine Design

### 3.1 test_run_execution States

```
                                    ┌─────────────┐
                                    │ NOT_STARTED │
                                    └──────┬──────┘
                                           │ start/immediate_run
                                           ▼
                                    ┌─────────────┐
                          ┌────────│ CALIBRATING │────────┐
                          │        └──────┬──────┘        │
                          │               │               │
                       error         complete          abandon
                          │               │               │
                          ▼               ▼               ▼
                   ┌────────────┐  ┌───────────┐   ┌───────────┐
                   │ENDED_ERROR │  │   READY   │   │ ABANDONED │
                   └────────────┘  └─────┬─────┘   └───────────┘
                          ▲              │               ▲
                          │         continue             │
                          │              │               │
                          │              ▼               │
                          │       ┌───────────┐          │
                          ├───────│ EXECUTING │──────────┤
                          │       └─────┬─────┘          │
                          │             │                │
                          │        ┌────┴────┐           │
                          │        │         │           │
                          │      pause    complete       │
                          │        │         │           │
                          │        ▼         ▼           │
                          │   ┌────────┐ ┌───────┐       │
                          │   │ PAUSED │ │ ENDED │       │
                          │   └───┬────┘ └───────┘       │
                          │       │                      │
                          │   continue                   │
                          │       │                      │
                          └───────┴──────────────────────┘
```

### 3.2 State Transitions

| Current State | Action | Valid? | New State |
|---------------|--------|--------|-----------|
| NOT_STARTED | start | ✅ | CALIBRATING |
| CALIBRATING | complete | ✅ | READY |
| CALIBRATING | error | ✅ | ENDED_ERROR |
| CALIBRATING | abandon | ✅ | ABANDONED |
| READY | continue | ✅ | EXECUTING |
| READY | abandon | ✅ | ABANDONED |
| EXECUTING | pause | ✅ | PAUSED (after current step) |
| EXECUTING | complete | ✅ | ENDED |
| EXECUTING | error | ✅ | ENDED_ERROR |
| EXECUTING | abandon | ✅ | ABANDONED |
| PAUSED | continue | ✅ | EXECUTING |
| PAUSED | abandon | ✅ | ABANDONED |
| ENDED | * | ❌ | - (terminal) |
| ENDED_ERROR | * | ❌ | - (terminal) |
| ABANDONED | * | ❌ | - (terminal) |

### 3.3 run_mode Behavior

| run_mode | After calibration | After each scenario/loadprofile |
|----------|-------------------|--------------------------------|
| continuous | Auto → EXECUTING | Auto continue to next |
| step | READY (wait for continue) | PAUSED (wait for continue) |

---

## 4. Execution Flow (Revised)

### 4.1 Start Execution

```
POST /executions { test_run_id, run_mode, immediate_run }
    │
    ▼
1. Validate test_run exists
2. Check no active execution exists
3. Get scenarios for this test_run (ordered)
4. Get targets for each scenario
    │
    ▼
5. Create test_run_execution:
   - status = NOT_STARTED
   - run_mode = input
    │
    ▼
6. Create test_run_execution_scenario_status for each:
   - (scenario, loadprofile, repetition) combination
   - status = pending
   - execution_order = scenario order
    │
    ▼
7. Create execution_workflow_state for each:
   - (target, loadprofile, repetition) combination
   - cur_state = norun
    │
    ▼
8. IF immediate_run:
   - Update execution.status = CALIBRATING
   - Start calibration (async)
    │
    ▼
9. Return execution_id
```

### 4.2 Continue Execution

```
POST /executions/{id}/continue
    │
    ▼
1. READ current state from test_run_execution
    │
    ├── IF status = READY:
    │   → Update status = EXECUTING
    │   → Find first pending scenario_status
    │   → Start execution (async)
    │
    ├── IF status = PAUSED:
    │   → Update status = EXECUTING
    │   → Find next pending scenario_status
    │   → Resume execution (async)
    │
    └── ELSE:
        → Return error (invalid state for continue)
```

### 4.3 Pause Execution

```
POST /executions/{id}/pause
    │
    ▼
1. READ current state from test_run_execution
    │
    ├── IF status = EXECUTING:
    │   → Set pause_requested = true
    │   → Orchestrator will pause after current scenario/loadprofile
    │   → Status changes to PAUSED when step completes
    │
    └── ELSE:
        → Return error (can only pause executing)
```

### 4.4 Orchestrator Loop

```
WHILE execution.status IN (CALIBRATING, EXECUTING):
    │
    ├── READ execution state from test_run_execution
    │
    ├── IF pause_requested AND step_complete:
    │   → Update status = PAUSED
    │   → BREAK
    │
    ├── Find next scenario_status WHERE status = pending
    │   (ordered by execution_order, loadprofile, repetition)
    │
    ├── IF none found:
    │   → All complete
    │   → Update execution.status = ENDED
    │   → BREAK
    │
    ├── Execute scenario/loadprofile:
    │   │
    │   ├── Update scenario_status.status = executing
    │   ├── Update scenario_status.phase = current phase
    │   │
    │   ├── For each target in scenario (PARALLEL):
    │   │   ├── Update workflow_state.cur_state = ...
    │   │   ├── Run phase (calibration/base/initial/upgrade)
    │   │   └── Store results in workflow_state
    │   │
    │   ├── BARRIER: Wait for all targets
    │   │
    │   ├── IF all targets succeeded:
    │   │   → scenario_status.status = completed
    │   │   → Aggregate results into result_summary_json
    │   │
    │   └── ELSE:
    │       → scenario_status.status = failed
    │       → Store error_message
    │
    └── IF run_mode = step:
        → Update execution.status = PAUSED
        → BREAK (wait for continue)
```

---

## 5. Implementation Tasks

### 5.1 New ORM & Model

- [ ] Create `TestRunExecutionScenarioStatusORM` in `orm.py`
- [ ] Create `TestRunExecutionScenarioStatus` model in `models.py`
- [ ] Create `ScenarioExecutionStatus` enum in `enums.py`
- [ ] Update `TestRunExecutionORM` to add `pause_requested` field
- [ ] Add relationship: `test_run_execution` → `scenario_statuses`

### 5.2 Repository Layer

- [ ] Create `TestRunExecutionScenarioStatusRepository`
- [ ] Add methods:
  - `create(execution_id, scenario_id, loadprofile, ...)`
  - `get_next_pending(execution_id)`
  - `update_status(id, status, error_message)`
  - `get_by_execution_id(execution_id)`

### 5.3 Service Layer Updates

- [ ] Update `ExecutionService.create_execution()`:
  - Create scenario_status records
  - Validate scenarios exist

- [ ] Update `ExecutionService.execute_action()`:
  - Read state from test_run_execution FIRST
  - Validate state transition
  - Handle pause_requested flag

### 5.4 Orchestrator Updates

- [ ] Create `ExecutionOrchestrator` class
- [ ] Implement main loop with:
  - State verification
  - Pause handling
  - Step mode support
  - Scenario ordering
  - Parallel execution with barriers

---

## 6. Questions to Clarify

1. **Scenario Order**: How is execution_order determined?
   - From scenario creation order?
   - Explicit order field in scenario?
   - Order in test_run_targets?

2. **Failure Handling**: If one scenario fails:
   - Skip remaining loadprofiles for that scenario?
   - Skip remaining scenarios?
   - Continue with next?

3. **Repetitions**: How do repetitions work?
   - Run all scenarios for rep 1, then all for rep 2?
   - Or run scenario 1 (all reps), then scenario 2 (all reps)?

4. **Calibration Scope**:
   - Calibrate per scenario? (current understanding)
   - Or calibrate all scenarios before any execution?
