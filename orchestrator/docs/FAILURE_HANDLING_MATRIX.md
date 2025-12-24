# Failure Handling Matrix

## Overview

This document defines all possible failure scenarios during test execution and the corresponding actions.

**Key Principles:**
1. Retry with preconfigured count before failing
2. On failure, restart from the failed point (not from beginning)
3. Calibration failure → Redo whole calibration
4. Scenario/loadprofile failure → Redo from that loadprofile

---

## Execution Phases & States

```
CALIBRATION PHASE
    └── calibrating → calibrated

EXECUTION PHASE (per scenario, per loadprofile, per repetition)
    ├── PHASE: base
    │   ├── snapshot_revert
    │   ├── power_on
    │   ├── waiting_ready
    │   ├── load_running
    │   ├── stats_collecting
    │   └── phase_complete
    │
    ├── PHASE: initial (with agent V1)
    │   ├── snapshot_revert
    │   ├── power_on
    │   ├── waiting_ready
    │   ├── package_installing    ← agent install
    │   ├── config_verifying      ← check agent config
    │   ├── load_running
    │   ├── stats_collecting
    │   ├── functional_testing    ← optional
    │   └── phase_complete
    │
    └── PHASE: upgrade (with agent V2)
        ├── package_upgrading     ← agent upgrade (no snapshot revert)
        ├── config_verifying
        ├── load_running
        ├── stats_collecting
        ├── functional_testing
        └── phase_complete
```

---

## Failure Categories

### 1. CONNECTION FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| Any | SSH/WinRM connection failed | ✅ | 3 | Mark scenario_status=failed, stop execution | Same state |
| snapshot_revert | Cannot connect to vSphere/Intune | ✅ | 3 | Mark failed | Same state |
| power_on | Cannot connect to hypervisor | ✅ | 3 | Mark failed | Same state |
| waiting_ready | Target not responding after power on | ✅ | 5 | Mark failed | power_on (re-power) |
| load_running | Lost connection mid-test | ✅ | 2 | Mark loadprofile failed | Restart loadprofile from snapshot_revert |
| stats_collecting | Cannot retrieve stats | ✅ | 3 | Mark failed (data loss) | Continue to next phase (soft fail) |

### 2. PACKAGE FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| package_installing | Download failed | ✅ | 3 | Mark failed | Same state |
| package_installing | Install command failed | ✅ | 3 | Mark failed | Same state |
| package_installing | Install timeout | ✅ | 2 | Mark failed | Same state |
| config_verifying | Version mismatch | ✅ | 2 | Mark failed | package_installing (reinstall) |
| config_verifying | Config mismatch | ❌ | - | Log warning, continue | N/A (soft fail) |
| package_upgrading | Upgrade failed | ✅ | 3 | Mark failed | package_upgrading |
| package_upgrading | Requires restart, restart failed | ✅ | 2 | Mark failed | package_upgrading |

### 3. CALIBRATION FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| calibrating | Emulator not responding | ✅ | 3 | Mark scenario failed | Redo entire calibration |
| calibrating | Cannot reach target CPU% | ✅ | 2 | Mark failed with achieved CPU | Redo entire calibration |
| calibrating | Timeout waiting for stable CPU | ✅ | 2 | Use last stable reading | Redo entire calibration |
| calibrating | Binary search not converging | ❌ | - | Use best effort value | N/A (soft fail with warning) |

### 4. LOAD TEST FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| load_running | JMeter failed to start | ✅ | 3 | Mark loadprofile failed | Restart from snapshot_revert |
| load_running | Emulator crashed | ✅ | 2 | Mark loadprofile failed | Restart from snapshot_revert |
| load_running | Target crashed (BSOD/kernel panic) | ✅ | 2 | Mark loadprofile failed | Restart from snapshot_revert |
| load_running | Load gen connection lost | ✅ | 2 | Mark loadprofile failed | Restart from snapshot_revert |
| load_running | Timeout (duration exceeded) | ❌ | - | Mark failed, collect partial stats | Continue to stats_collecting |

### 5. INFRASTRUCTURE FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| snapshot_revert | Snapshot not found | ❌ | - | Mark scenario failed | N/A (unrecoverable) |
| snapshot_revert | Revert failed | ✅ | 3 | Mark failed | Same state |
| power_on | Power on failed | ✅ | 3 | Mark failed | Same state |
| power_on | VM stuck in intermediate state | ✅ | 2 | Force power off, retry | power_off then power_on |
| waiting_ready | Guest tools not running | ✅ | 5 | Mark failed | power_on |
| Any | Disk full on target | ❌ | - | Mark failed | N/A (unrecoverable) |
| Any | Database connection lost | ✅ | 5 | Abort execution | N/A (orchestrator issue) |

### 6. DATA COLLECTION FAILURES

| State | Failure | Retry? | Max Retries | On Max Retry Failure | Resume Point |
|-------|---------|--------|-------------|---------------------|--------------|
| stats_collecting | Stats file not found | ✅ | 2 | Log warning, continue | N/A (soft fail) |
| stats_collecting | Stats collection timeout | ✅ | 2 | Partial data, continue | N/A (soft fail) |
| functional_testing | Test script failed | ❌ | - | Log result, continue | N/A (record failure) |
| functional_testing | Test timeout | ❌ | - | Log as timeout, continue | N/A (record failure) |

---

## Retry Configuration (Defaults)

```python
RETRY_CONFIG = {
    # Connection retries
    "connection_retry_count": 3,
    "connection_retry_delay_sec": 10,

    # Package retries
    "package_install_retry_count": 3,
    "package_install_retry_delay_sec": 30,

    # Calibration retries
    "calibration_retry_count": 2,
    "calibration_retry_delay_sec": 60,

    # Load test retries
    "loadtest_retry_count": 2,
    "loadtest_retry_delay_sec": 120,

    # Infrastructure retries
    "snapshot_revert_retry_count": 3,
    "snapshot_revert_retry_delay_sec": 30,
    "power_on_retry_count": 3,
    "power_on_retry_delay_sec": 20,
    "waiting_ready_retry_count": 5,
    "waiting_ready_retry_delay_sec": 30,
    "waiting_ready_timeout_sec": 300,

    # Stats collection retries
    "stats_collect_retry_count": 2,
    "stats_collect_retry_delay_sec": 10,
}
```

---

## Resume Point Logic

```python
def get_resume_point(current_state: str, failure_type: str) -> str:
    """
    Determine where to resume from after a failure.

    Returns the state to restart from.
    """

    # Calibration failures: redo entire calibration
    if current_state == "calibrating":
        return "calibrating"  # Start calibration from scratch

    # Connection lost during load test: restart loadprofile
    if current_state == "load_running" and failure_type == "connection_lost":
        return "snapshot_revert"  # Restart the entire loadprofile phase

    # Package install failure: retry same state
    if current_state == "package_installing":
        return "package_installing"

    # Config verification failed: reinstall package
    if current_state == "config_verifying" and failure_type == "version_mismatch":
        return "package_installing"

    # Default: retry same state
    return current_state
```

---

## State Transition on Failure

```
Normal Flow:
    state_A → state_B → state_C → complete

On Failure at state_B (with retries remaining):
    state_A → state_B → [RETRY] → state_B → state_C → complete

On Failure at state_B (max retries exceeded):
    state_A → state_B → [FAILED]
                           │
                           ▼
              scenario_status = failed
              error_message = "..."
              execution.status = PAUSED (if step mode) or continues to next scenario
```

---

## Failure Recording

All failures are recorded in `execution_workflow_state.error_history`:

```json
{
  "error_history": [
    {
      "timestamp": "2024-01-15T10:30:00Z",
      "state": "package_installing",
      "phase": "initial",
      "error_type": "install_failed",
      "error_message": "Exit code 1: Package conflict detected",
      "retry_count": 1,
      "action_taken": "retry"
    },
    {
      "timestamp": "2024-01-15T10:31:00Z",
      "state": "package_installing",
      "phase": "initial",
      "error_type": "install_failed",
      "error_message": "Exit code 1: Package conflict detected",
      "retry_count": 2,
      "action_taken": "retry"
    },
    {
      "timestamp": "2024-01-15T10:32:00Z",
      "state": "package_installing",
      "phase": "initial",
      "error_type": "install_failed",
      "error_message": "Exit code 1: Package conflict detected",
      "retry_count": 3,
      "action_taken": "failed"
    }
  ]
}
```

---

## Soft Failures vs Hard Failures

### Soft Failures (Continue Execution)
- Stats collection timeout (partial data is acceptable)
- Config mismatch warning (just log it)
- Functional test failure (record result, continue)
- Cannot reach exact target CPU% (use best effort)

### Hard Failures (Stop/Mark Failed)
- Snapshot not found
- Cannot connect after max retries
- Package install failed after max retries
- Target crashed during load test (after retries)
- Calibration completely failed

---

## Execution Order with Failures

Given: 2 scenarios, 3 loadprofiles (low, medium, high), 2 repetitions

**Normal execution order (Option A):**
```
S1-low-rep1 → S1-low-rep2 → S1-medium-rep1 → S1-medium-rep2 → S1-high-rep1 → S1-high-rep2
    → S2-low-rep1 → S2-low-rep2 → S2-medium-rep1 → S2-medium-rep2 → S2-high-rep1 → S2-high-rep2
```

**If S1-medium-rep1 fails:**
```
S1-low-rep1 ✓
S1-low-rep2 ✓
S1-medium-rep1 ✗ (failed after retries)
    │
    ▼
Mark scenario_status(S1, medium, rep1) = failed
    │
    ▼
On resume/continue:
    → S1-medium-rep1 (retry from scratch - snapshot_revert)
    → S1-medium-rep2
    → ... (continue normally)
```
