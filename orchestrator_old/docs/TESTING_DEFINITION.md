# What "Testing" Means in Agent Performance Testing

## Overview

Testing in this framework is **NOT about creating new infrastructure**. The infrastructure (Docker images, database servers, load generators) is assumed to exist and be defined in the database.

Testing is the **orchestrated execution** of performance load against target systems to measure the impact of security agents.

---

## What Testing IS

### 1. Execution Against Pre-Defined Infrastructure

Testing means running the application's executor to:
- Read configuration from database (baselines, servers, scenarios, packages)
- Restore/create target environments from baseline images
- Deploy required packages to targets and load generators
- Execute load tests with calibrated thread counts
- Collect metrics and results

### 2. The Test Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TEST EXECUTION FLOW                           │
└─────────────────────────────────────────────────────────────────────────┘

1. READ CONFIGURATION
   ├── Test Run (which scenarios, load profiles, repetitions)
   ├── Scenarios (which targets, which load generators)
   ├── Baselines (Docker images to restore/create from)
   └── Packages (what to deploy - JMeter, emulator, agents)

2. ENVIRONMENT PREPARATION (per scenario)
   ├── Restore targets to baseline state (docker pull/create)
   ├── Deploy packages to targets (emulator, test files)
   └── Deploy packages to load generators (JMeter, JDBC drivers)

3. CALIBRATION (if not already calibrated)
   ├── Run binary search to find thread count for target CPU%
   ├── LOW profile: 20-30% CPU
   ├── MEDIUM profile: 45-55% CPU
   └── HIGH profile: 70-80% CPU

4. EXECUTION (3 phases per scenario)
   │
   ├── BASE PHASE (no agent installed)
   │   ├── Target is at baseline state
   │   ├── Run JMeter load with calibrated threads
   │   └── Collect: CPU, memory, response times, throughput
   │
   ├── INITIAL PHASE (agent version A installed)
   │   ├── Deploy agent package to target
   │   ├── Run JMeter load with SAME thread count
   │   └── Collect: CPU, memory, response times, throughput
   │
   └── UPGRADE PHASE (agent version B installed)
       ├── Deploy upgraded agent to target
       ├── Run JMeter load with SAME thread count
       └── Collect: CPU, memory, response times, throughput

5. RESULTS COMPARISON
   └── Compare metrics across BASE vs INITIAL vs UPGRADE
       to measure agent performance impact
```

### 3. What the Application Does

| Component | Responsibility |
|-----------|---------------|
| **Executor** | Orchestrates the entire test flow |
| **PackageResolver** | Determines which packages to deploy based on OS matching |
| **CalibrationService** | Finds optimal thread count for target CPU% |
| **JMeterService** | Runs JMeter, monitors progress, collects results |
| **RemoteExecutor** | SSH/WinRM/Docker exec to deploy and run commands |

### 4. Load Types

| Load Type | What It Tests | JMeter Template |
|-----------|---------------|-----------------|
| **Normal Server (99%+1%)** | Typical API calls with rare anomalies | `server-normal.jmx` |
| **File-Heavy (69%+30%+1%)** | File I/O intensive workload | `server-file-heavy.jmx` |
| **Database Load** | CRUD, complex queries, sensitive data access | `db-load.jmx` |

---

## What Testing is NOT

### 1. NOT Infrastructure Creation

Testing does NOT:
- Create Docker images from scratch
- Set up Docker networks
- Install database servers
- Configure load generator machines
- Write JMeter test plans

These are **prerequisites** that must exist before testing.

### 2. NOT Development

Testing does NOT:
- Write new application code
- Create new emulator endpoints
- Design database schemas
- Develop JMX templates

These are **assets** that testing consumes.

---

## Test Data vs Test Assets

| Category | Examples | Stored In |
|----------|----------|-----------|
| **Test Data** (DB entries) | Labs, Servers, Baselines, Scenarios, Packages | Database tables |
| **Test Assets** (files) | Docker images, JMX files, SQL schemas, Emulator code | File system / Registry |

### Test Data (What We Configure)

```
Database Tables:
├── labs                 → Lab environment definition
├── servers              → Target and load generator definitions
├── baseline             → Docker images, snapshots references
├── packages             → Installable software definitions
├── package_groups       → Groups of packages (JMeter, Emulator)
├── package_group_members → OS-specific package mappings
├── scenarios            → Test scenario configurations
├── test_runs            → Test run parameters
└── test_run_targets     → Target-to-loadgen mappings
```

### Test Assets (What We Create Beforehand)

```
File System / Registry:
├── Docker Images
│   ├── ubuntu:22.04, ubuntu:20.04
│   ├── postgres:15, mysql:8
│   └── custom-emulator:latest (optional)
│
├── JMX Templates (in app/jmeter/templates/)
│   ├── server-normal.jmx
│   ├── server-file-heavy.jmx
│   └── db-load.jmx
│
├── Database Assets (in app/db/schemas/)
│   ├── schema.sql (500 tables)
│   └── seed-data.sql (10K-50K records)
│
└── Emulator Package (in packages/)
    ├── cpu-emulator.tar.gz
    └── test-files/ (files emulator downloads)
```

---

## Summary

**Testing = Execution using pre-existing configuration and assets**

1. Database has entries defining WHAT to test (servers, scenarios, packages)
2. File system has assets defining HOW to test (JMX files, Docker images)
3. Application reads #1, uses #2, and executes the test
4. Results are collected and stored for comparison

The application is the **orchestrator**, not the **creator**.
