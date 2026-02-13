# Workflow State Creation Flow

## Overview

This document describes how `ExecutionWorkflowState` records are created and populated during execution initialization.

**Key Concept:** Package lists are built per-phase, where each phase may have a different OS (from different baselines/snapshots).

---

## New Structure: List-Based Package Tracking

The workflow state uses list-based tracking instead of individual configuration fields:

```
ExecutionWorkflowState
├── base_package_lst          # Packages to install in BASE phase
├── base_package_lst_measured # Installation results
├── base_packages_matched     # All packages matched?
├── base_results_json         # Load test results
├── base_stats_json           # Stats collected
├── base_logs_json            # Execution logs
│
├── initial_package_lst       # Packages for INITIAL phase
├── initial_package_lst_measured
├── initial_packages_matched
├── initial_results_json
├── initial_stats_json
├── initial_logs_json
│
├── upgrade_package_lst       # Packages for UPGRADE phase
├── upgrade_package_lst_measured
├── upgrade_packages_matched
├── upgrade_results_json
├── upgrade_stats_json
├── upgrade_logs_json
│
└── upgrade_revert_required   # Flag: revert or install on top?
```

---

## Phase/Snapshot/Package Combinations

### Phase Execution Logic

| base_snapshot | initial_snapshot | upgrade_snapshot | upgrade_pkg_grp | Phases Run | Notes |
|---------------|------------------|------------------|-----------------|------------|-------|
| YES | NO | NO | NO | BASE only | Just baseline measurement |
| YES | YES | NO | NO | BASE, INITIAL | Initial agent install |
| YES | YES | NO | YES | BASE, INITIAL, UPGRADE | Upgrade ON TOP of initial (no revert) |
| YES | YES | YES | YES | BASE, INITIAL, UPGRADE | Upgrade with separate snapshot (revert) |
| NO | YES | NO | NO | INITIAL only | No baseline measurement |
| NO | YES | NO | YES | INITIAL, UPGRADE | Upgrade ON TOP of initial |
| NO | YES | YES | YES | INITIAL, UPGRADE | Upgrade with separate snapshot |

### Invalid Combinations (Should Fail Validation)

| Combination | Why Invalid |
|-------------|-------------|
| upgrade_snapshot WITHOUT initial_snapshot | Can't have upgrade baseline without initial |
| upgrade_pkg_grp WITHOUT initial_pkg_grp | Can't upgrade without something to upgrade from |
| NO snapshots at all | Nothing to run |

---

## OS Info Comes From Baseline

**Critical:** OS information for package selection comes from the **baseline** table, NOT from target/server.

Each phase uses the OS from its respective baseline:
- BASE phase → uses `base_snapshot_id` → baseline.os_* fields
- INITIAL phase → uses `initial_snapshot_id` → baseline.os_* fields
- UPGRADE phase → uses `upgrade_snapshot_id` (or `initial_snapshot_id` if no upgrade snapshot) → baseline.os_* fields

### Building OS String

```python
def build_os_string(baseline: Baseline, package_group: PackageGroup) -> str:
    """
    Build OS string for package matching.
    Format: '{os_vendor}/{os_major}/{os_minor}[/{kernel}]'

    Kernel is included ONLY if package_group.req_kernel_version=True
    """
    os_string = f"{baseline.os_vendor_family}/{baseline.os_major_ver}/{baseline.os_minor_ver}"

    if package_group.req_kernel_version and baseline.os_kernel_ver:
        os_string += f"/{baseline.os_kernel_ver}"

    return os_string

# Examples:
# "Windows/10/22H2"
# "RHEL/8/4"
# "RHEL/8/4/4.18.0-372"  (with kernel)
```

---

## Package List Structure

Each `*_package_lst` field contains a list of packages to install:

```json
[
    {
        "package_id": 101,
        "package_name": "JMeter Load Generator",
        "package_version": "5.5.0",
        "package_type": "load_runner_euc",
        "package_group_id": 5,
        "package_group_member_id": 15,
        "con_type": "script",
        "delivery_config": {...},
        "requires_restart": false,
        "version_check_command": "jmeter --version",
        "expected_version_regex": "5\\.5\\..*",
        "is_measured": false
    },
    {
        "package_id": 201,
        "package_name": "CrowdStrike Agent",
        "package_version": "6.50.0",
        "package_type": "agent",
        "package_group_id": 10,
        "package_group_member_id": 25,
        "con_type": "intune",
        "delivery_config": {...},
        "requires_restart": true,
        "restart_timeout_sec": 300,
        "version_check_command": "...",
        "expected_version_regex": "6\\.50\\..*",
        "is_measured": true,
        "agent_id": 1,
        "agent_name": "CrowdStrike"
    }
]
```

### Package List Measured Structure

After installation, `*_package_lst_measured` contains results:

```json
[
    {
        "package_id": 101,
        "package_name": "JMeter Load Generator",
        "expected_version": "5.5.0",
        "install_status": "success",
        "install_timestamp": "2024-01-15T10:30:00Z",
        "measured_version": "5.5.0",
        "version_matched": true,
        "error_message": null
    },
    {
        "package_id": 201,
        "package_name": "CrowdStrike Agent",
        "expected_version": "6.50.0",
        "install_status": "success",
        "install_timestamp": "2024-01-15T10:32:00Z",
        "measured_version": "6.50.14358",
        "version_matched": true,
        "restart_performed": true,
        "restart_duration_sec": 45,
        "error_message": null
    }
]
```

---

## Building Package Lists Per Phase

### BASE Phase Packages

BASE phase gets **loadgen packages only** (no agents):

```python
def build_base_package_list(
    test_run: TestRun,
    baseline: Baseline,  # base_snapshot
    lab: Lab,
) -> list[dict]:
    """Build package list for BASE phase - loadgen only."""

    packages = []

    # Get loadgen package groups from test_run
    for pkg_grp_id in test_run.loadgenerator_package_grpid_lst:
        package_group = get_package_group(pkg_grp_id)
        os_string = build_os_string(baseline, package_group)

        selected = select_package_for_os(
            package_group_id=pkg_grp_id,
            os_string=os_string,
            lab_id=lab.id,
        )

        packages.append({
            "package_id": selected.package_id,
            "package_name": selected.package_name,
            "package_version": selected.package_version,
            "package_type": package_group.group_type,
            "package_group_id": pkg_grp_id,
            "package_group_member_id": selected.member_id,
            "con_type": selected.con_type,
            "delivery_config": selected.delivery_config,
            "is_measured": False,  # Loadgen not measured for impact
            # ... other fields
        })

    return packages
```

### INITIAL Phase Packages

INITIAL phase gets **loadgen + agent + other packages**:

```python
def build_initial_package_list(
    test_run: TestRun,
    scenario: Scenario,
    scenario_cases: list[ScenarioCase],
    baseline: Baseline,  # initial_snapshot
    lab: Lab,
) -> list[dict]:
    """Build package list for INITIAL phase - loadgen + agent + other."""

    packages = []
    os_string_cache = {}  # Cache OS strings per package_group

    # 1. Add loadgen packages (same as BASE, needed to run load!)
    for pkg_grp_id in test_run.loadgenerator_package_grpid_lst:
        package_group = get_package_group(pkg_grp_id)
        os_string = build_os_string(baseline, package_group)

        selected = select_package_for_os(pkg_grp_id, os_string, lab.id)
        packages.append({
            **build_package_dict(selected, package_group),
            "is_measured": False,
        })

    # 2. Add agent packages from scenario_cases
    for case in scenario_cases:
        if case.initial_package_grp_id:
            package_group = get_package_group(case.initial_package_grp_id)
            os_string = build_os_string(baseline, package_group)

            selected = select_package_for_os(
                case.initial_package_grp_id, os_string, lab.id
            )
            packages.append({
                **build_package_dict(selected, package_group),
                "is_measured": True,  # Agent IS measured
                "agent_id": case.agent_id,
                "agent_name": case.agent.name,
            })

        # 3. Add "other" packages (functional tests, policy, etc.)
        if case.other_package_grp_ids:
            for pkg_grp_id in case.other_package_grp_ids:
                package_group = get_package_group(pkg_grp_id)
                os_string = build_os_string(baseline, package_group)

                selected = select_package_for_os(pkg_grp_id, os_string, lab.id)
                packages.append({
                    **build_package_dict(selected, package_group),
                    "is_measured": False,  # Functional tests not measured
                })

    return packages
```

### UPGRADE Phase Packages

UPGRADE phase gets **loadgen + upgrade_agent + other packages**:

```python
def build_upgrade_package_list(
    test_run: TestRun,
    scenario: Scenario,
    scenario_cases: list[ScenarioCase],
    baseline: Baseline,  # upgrade_snapshot OR initial_snapshot
    lab: Lab,
) -> list[dict]:
    """Build package list for UPGRADE phase."""

    packages = []

    # 1. Add loadgen packages (REQUIRED - can't run load without them!)
    for pkg_grp_id in test_run.loadgenerator_package_grpid_lst:
        package_group = get_package_group(pkg_grp_id)
        os_string = build_os_string(baseline, package_group)

        selected = select_package_for_os(pkg_grp_id, os_string, lab.id)
        packages.append({
            **build_package_dict(selected, package_group),
            "is_measured": False,
        })

    # 2. Add UPGRADE agent packages from scenario_cases
    for case in scenario_cases:
        if case.upgrade_package_grp_id:
            package_group = get_package_group(case.upgrade_package_grp_id)
            os_string = build_os_string(baseline, package_group)

            selected = select_package_for_os(
                case.upgrade_package_grp_id, os_string, lab.id
            )
            packages.append({
                **build_package_dict(selected, package_group),
                "is_measured": True,  # Agent IS measured
                "agent_id": case.agent_id,
                "agent_name": case.agent.name,
            })

        # 3. Add "other" packages (may be different for upgrade)
        if case.other_package_grp_ids:
            for pkg_grp_id in case.other_package_grp_ids:
                package_group = get_package_group(pkg_grp_id)
                os_string = build_os_string(baseline, package_group)

                selected = select_package_for_os(pkg_grp_id, os_string, lab.id)
                packages.append({
                    **build_package_dict(selected, package_group),
                    "is_measured": False,
                })

    return packages
```

---

## Complete Creation Flow

```
POST /executions { test_run_id, run_mode, immediate_run }
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. VALIDATION                                                    │
├─────────────────────────────────────────────────────────────────┤
│ • test_run exists?                                               │
│ • No active execution?                                           │
│ • Has targets configured?                                        │
│ • Validate snapshot combinations (see rules above)               │
│ • All scenario_cases have valid package_groups?                  │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. CREATE test_run_execution                                     │
├─────────────────────────────────────────────────────────────────┤
│ • status = NOT_STARTED                                           │
│ • run_mode = input                                               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. FOR EACH (scenario, loadprofile, repetition):                 │
├─────────────────────────────────────────────────────────────────┤
│ CREATE test_run_execution_scenario_status                        │
│ • status = pending                                               │
│ • execution_order = scenario.execution_order                     │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. FOR EACH test_run_target:                                     │
│    FOR EACH loadprofile:                                         │
│    FOR EACH repetition:                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  4a. DETERMINE WHICH PHASES TO RUN                               │
│  ────────────────────────────────────                            │
│  has_base = target.base_snapshot_id is not None                  │
│  has_initial = target.initial_snapshot_id is not None            │
│  has_upgrade_snapshot = target.upgrade_snapshot_id is not None   │
│  has_upgrade_pkg = any(c.upgrade_package_grp_id for c in cases)  │
│                                                                   │
│  phases_to_run = []                                              │
│  if has_base: phases_to_run.append("base")                       │
│  if has_initial: phases_to_run.append("initial")                 │
│  if has_upgrade_pkg: phases_to_run.append("upgrade")             │
│                                                                   │
│  upgrade_revert_required = has_upgrade_snapshot                  │
│                                                                   │
│  4b. GET BASELINES AND BUILD OS STRINGS                          │
│  ────────────────────────────────────────                         │
│  base_baseline = get_baseline(target.base_snapshot_id)           │
│  initial_baseline = get_baseline(target.initial_snapshot_id)     │
│  upgrade_baseline = get_baseline(                                │
│      target.upgrade_snapshot_id or target.initial_snapshot_id    │
│  )                                                                │
│                                                                   │
│  4c. BUILD PACKAGE LISTS                                         │
│  ────────────────────────────                                     │
│  base_package_lst = None                                         │
│  initial_package_lst = None                                      │
│  upgrade_package_lst = None                                      │
│                                                                   │
│  if "base" in phases_to_run:                                     │
│      base_package_lst = build_base_package_list(                 │
│          test_run, base_baseline, lab                            │
│      )                                                           │
│                                                                   │
│  if "initial" in phases_to_run:                                  │
│      initial_package_lst = build_initial_package_list(           │
│          test_run, scenario, scenario_cases,                     │
│          initial_baseline, lab                                   │
│      )                                                           │
│                                                                   │
│  if "upgrade" in phases_to_run:                                  │
│      upgrade_package_lst = build_upgrade_package_list(           │
│          test_run, scenario, scenario_cases,                     │
│          upgrade_baseline, lab                                   │
│      )                                                           │
│                                                                   │
│  4d. CREATE execution_workflow_state                             │
│  ─────────────────────────────────────                            │
│  workflow_state = create(                                        │
│      test_run_execution_id = execution.id,                       │
│      target_id = target.target_id,                               │
│      loadprofile = loadprofile,                                  │
│      runcount = repetition,                                      │
│      cur_state = "norun",                                        │
│                                                                   │
│      # Baseline references                                       │
│      base_baseline_id = target.base_snapshot_id,                 │
│      initial_baseline_id = target.initial_snapshot_id,           │
│      upgrade_baseline_id = target.upgrade_snapshot_id,           │
│      upgrade_revert_required = upgrade_revert_required,          │
│                                                                   │
│      # Package lists (pre-populated)                             │
│      base_package_lst = base_package_lst,                        │
│      initial_package_lst = initial_package_lst,                  │
│      upgrade_package_lst = upgrade_package_lst,                  │
│                                                                   │
│      # Results/stats start as NULL                               │
│      base_package_lst_measured = None,                           │
│      base_results_json = None,                                   │
│      ...                                                         │
│  )                                                               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. IF immediate_run:                                             │
├─────────────────────────────────────────────────────────────────┤
│ • Update execution.status = CALIBRATING                          │
│ • Start calibration orchestrator (async)                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Package Selection Logic

### Step 1: Get Package Group Members

```python
def select_package_for_os(
    package_group_id: int,
    os_string: str,
    lab_id: int,
) -> SelectedPackage:
    """Select the correct package from a group for target OS."""

    # Get all members of this package group
    members = get_package_group_members(package_group_id)

    if not members:
        raise PackageGroupEmptyError(
            f"Package group {package_group_id} has no members"
        )

    # Filter members that match OS
    matched = []
    for member in members:
        if regex_match(member.os_match_regex, os_string):
            matched.append(member)

    if not matched:
        raise NoMatchingPackageError(
            f"No package in group {package_group_id} matches OS: {os_string}"
        )

    # Get lab preferences for ranking
    preferences = get_lab_package_preferences(lab_id)

    # Sort by preference rank, then member priority
    matched.sort(key=lambda m: (
        get_con_type_rank(m.con_type, preferences),
        m.priority
    ))

    # Return best match
    best = matched[0]
    package = get_package(best.package_id)

    return SelectedPackage(
        package_id=package.id,
        package_name=package.name,
        package_version=package.version,
        member_id=best.id,
        con_type=best.con_type,
        delivery_config=package.delivery_config,
        # ... etc
    )
```

### OS Matching Examples

```
os_match_regex patterns:

# Exact Windows 10 match
"Windows/10/.*"

# Windows 10 or 11
"Windows/(10|11)/.*"

# Any Windows
"Windows/.*"

# RHEL 8.x with specific kernel
"RHEL/8/.*/4\\.18\\.0-.*"

# Any Linux
"(RHEL|Ubuntu|CentOS|Debian)/.*"

# macOS 13+
"macOS/(13|14|15)/.*"
```

### Selection Example

**Given:**
- Target OS String: `"Windows/10/22H2"`
- Lab: lab_id=1 (prefers INTUNE over SCRIPT)
- Package Group: CrowdStrike v6.50 (id=10)

**package_group_members for group 10:**
| id | os_match_regex | con_type | priority | package_id |
|----|----------------|----------|----------|------------|
| 1 | `Windows/10/.*` | INTUNE | 0 | 101 |
| 2 | `Windows/10/.*` | SCRIPT | 0 | 102 |
| 3 | `Windows/11/.*` | INTUNE | 0 | 103 |
| 4 | `Windows/.*` | SCRIPT | 10 | 104 |

**Selection Process:**
1. Match: [1, 2, 4] (id=3 doesn't match Windows/10)
2. Rank by preference: INTUNE=0, SCRIPT=1
3. Sort: [(1, 0, 0), (2, 1, 0), (4, 1, 10)]
4. **Selected: id=1 (package_id=101, INTUNE)**

---

## Validation Errors

```python
class PackageSelectionError(Exception):
    """Base class for package selection errors."""
    pass

class NoMatchingPackageError(PackageSelectionError):
    """No package found matching target OS."""
    pass

class PackageGroupEmptyError(PackageSelectionError):
    """Package group has no members."""
    pass

class InvalidSnapshotCombinationError(Exception):
    """Invalid combination of snapshots."""
    pass

# Example validation:
def validate_snapshot_combination(
    base_snapshot_id: Optional[int],
    initial_snapshot_id: Optional[int],
    upgrade_snapshot_id: Optional[int],
    has_upgrade_package: bool,
) -> None:
    """Validate snapshot combination is valid."""

    # Cannot have upgrade_snapshot without initial_snapshot
    if upgrade_snapshot_id and not initial_snapshot_id:
        raise InvalidSnapshotCombinationError(
            "Cannot have upgrade_snapshot without initial_snapshot"
        )

    # Cannot have upgrade package without initial package
    if has_upgrade_package and not initial_snapshot_id:
        raise InvalidSnapshotCombinationError(
            "Cannot have upgrade_package without initial_snapshot"
        )

    # Must have at least one snapshot
    if not any([base_snapshot_id, initial_snapshot_id]):
        raise InvalidSnapshotCombinationError(
            "Must have at least one snapshot (base or initial)"
        )
```

---

## Summary

1. **OS info comes from BASELINE**, not target/server
2. **Loadgen packages needed in ALL phases** (can't run load without them)
3. **Package lists are pre-populated** during workflow state creation
4. **Measured results stored separately** after installation completes
5. **upgrade_revert_required flag** indicates if upgrade reverts or installs on top
