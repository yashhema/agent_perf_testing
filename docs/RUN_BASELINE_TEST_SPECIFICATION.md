# run_baseline_test.py -- End-to-End Baseline Test Runner

## Overview

`run_baseline_test.py` is the single entry-point script that drives a complete baseline performance test from the command line. It automates every step of the pipeline: building the emulator from source, starting the orchestrator server, creating a test run via the REST API, monitoring progress through all state machine phases, and reporting final results.

The script runs on the **orchestrator host machine** (Windows) and coordinates work across remote Linux/Windows target servers and load generators through the orchestrator's API.

---

## Usage

```bash
# Default: Linux target, low profile
python run_baseline_test.py

# Specify target OS
python run_baseline_test.py --target linux
python run_baseline_test.py --target windows
python run_baseline_test.py --target both

# Specify load profiles (comma-separated)
python run_baseline_test.py --profile low
python run_baseline_test.py --profile low,medium
python run_baseline_test.py --profile low,medium,high

# Test types
python run_baseline_test.py --test-type new_baseline              # default
python run_baseline_test.py --test-type compare --compare-snapshot-id 5
python run_baseline_test.py --test-type compare_with_new_calibration --compare-snapshot-id 5

# Skip steps
python run_baseline_test.py --skip-build            # Skip Maven build (use existing jar)
python run_baseline_test.py --skip-orchestrator     # Assume orchestrator already running
```

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--target` | `linux` | Target server(s): `linux`, `windows`, or `both` |
| `--profile` | `low` | Comma-separated load profile names: `low`, `medium`, `high` |
| `--test-type` | `new_baseline` | One of: `new_baseline`, `compare`, `compare_with_new_calibration` |
| `--skip-orchestrator` | off | Don't start/stop orchestrator (expects it already running on port 8000) |
| `--skip-build` | off | Skip emulator Maven build and tar.gz package creation |
| `--compare-snapshot-id` | none | Required when `--test-type` is `compare` or `compare_with_new_calibration` |

---

## Execution Phases

The script executes the following phases in order. Each phase is announced with a timestamped banner in the console output.

### Phase 1: Build Emulator Packages

**Function:** `build_emulator_packages()`
**Skipped by:** `--skip-build`

Builds the Java emulator from source and packages it for deployment to target servers.

**Steps:**
1. Runs `mvn package -DskipTests -q` in the `emulator_java/` directory
2. Verifies `emulator_java/target/emulator.jar` was produced
3. For each platform (`linux`, `windows`):
   - Creates a staging directory `emulator-java-{platform}/` containing:
     - `emulator.jar` -- the compiled application
     - `start.sh` (Linux) or `start.ps1` (Windows) -- startup script
     - `data/` -- DLP test files and normal files from `emulator/data/`
   - Creates `emulator-java-{platform}.tar.gz` in `orchestrator/artifacts/packages/`
   - Cleans up the staging directory

**Why this exists:** The emulator jar deployed to targets must match the current source code. A previous incident where an old jar was deployed (missing the oshi CPU stats fix) caused calibration to see 0% CPU despite JMeter generating load. Building before every test run prevents version mismatches.

**Output artifacts:**
- `orchestrator/artifacts/packages/emulator-java-linux.tar.gz`
- `orchestrator/artifacts/packages/emulator-java-windows.tar.gz`

---

### Phase 2: Start Orchestrator Server

**Function:** `start_orchestrator()`
**Skipped by:** `--skip-orchestrator`

Starts the FastAPI orchestrator as a subprocess.

**Steps:**
1. **Kill existing process:** `kill_existing_orchestrator()` runs `netstat -ano` to find any process LISTENING on port 8000, then kills it with `taskkill /F /PID`. This prevents "address already in use" errors from stale orchestrator instances.

2. **Set up environment:**
   - `CWD` = `orchestrator/` (required because `orchestrator.app` loads `config/orchestrator.yaml` via relative path)
   - `PYTHONPATH` = `orchestrator/src/` (so Python can find the `orchestrator` package)

3. **Launch subprocess:**
   ```
   python -m uvicorn orchestrator.app:app --host 127.0.0.1 --port 8000
   ```
   - stdout/stderr are written to `orchestrator/logs/orchestrator_run.log` (NOT piped to the parent process -- piping caused buffer fill issues where the orchestrator would block when the pipe buffer was full, leading to API timeouts)

4. **Wait for readiness:** Polls `GET http://127.0.0.1:8000/docs` every 1 second, up to 30 seconds. Exits if the orchestrator doesn't become ready.

**When `--skip-orchestrator` is used:** The script verifies the orchestrator is reachable at `http://127.0.0.1:8000/docs` and exits if not.

---

### Phase 3: Authentication

**Function:** `login()`

Authenticates with the orchestrator API to get a Bearer token.

- Endpoint: `POST /api/auth/login`
- Credentials: `admin` / `admin` (from seed data)
- Returns: `{"Authorization": "Bearer <token>"}` headers dict used for all subsequent API calls

---

### Phase 4: Resolve Load Profile IDs

**Function:** `resolve_profile_ids(headers, profile_names)`

Maps human-readable profile names (`low`, `medium`, `high`) to database IDs.

**Implementation:** Queries the database directly (not via API, since there's no load-profiles endpoint) by importing the orchestrator's ORM and opening a SQLAlchemy session. Loads the orchestrator's `config/orchestrator.yaml` to get the database URL.

---

### Phase 5: Pre-flight Emulator Health Check

**Function:** `check_emulator_health(targets_config)`

Verifies each target server's emulator is reachable before starting the test.

- Endpoint per target: `GET http://{target_ip}:8080/health`
- Reports: health status and uptime in seconds
- This is an informational check only -- the test will still proceed even if the emulator is not reachable (the orchestrator's own validation phase will catch this and fail the test properly)

**Note:** At this point the emulator on the target may be from a previous snapshot. The orchestrator's setup phase will revert the VM to a clean snapshot and redeploy the freshly-built emulator package.

---

### Phase 6: Create Baseline Test Run

**Function:** `api_post("/baseline-tests", ...)`

Creates a new test run record in the database via the orchestrator API.

**Payload structure:**
```json
{
    "scenario_id": 1005,
    "test_type": "new_baseline",
    "load_profile_ids": [1],
    "targets": [
        {
            "server_id": 8,
            "test_snapshot_id": 3
        }
    ]
}
```

For `compare` and `compare_with_new_calibration` test types, each target also includes `compare_snapshot_id`.

**Response:** Returns the created test run with its `id` and initial `state` ("created").

---

### Phase 7: Start Test Run

**Function:** `api_post(f"/baseline-tests/{test_run_id}/start", ...)`

Triggers the orchestrator to begin executing the test run asynchronously. The orchestrator processes the test in a background thread, advancing through its state machine.

---

### Phase 8: Monitor Progress (Polling Loop)

The core monitoring loop that tracks the test through all orchestrator states until a terminal state is reached.

**Polling configuration:**
- Interval: every 15 seconds (`POLL_SEC`)
- Maximum wait: 2 hours (7200 seconds, `MAX_WAIT_SEC`)
- Cancel: Ctrl+C sends a cancel request to the API

**Two data sources per poll cycle:**

1. **API poll:** `GET /api/baseline-tests/{test_run_id}` -- returns the current state
2. **Direct DB query:** `check_db_state(test_run_id)` -- returns detailed progress data that the API may not expose, including:
   - Calibration progress: current thread count, observed CPU%, iteration number, phase, status message
   - Comparison results: verdict, violation count per target/profile

**Error resilience:** Both `api_get` and `api_post` catch `ReadTimeout` and `ConnectionError` exceptions. If the API is unreachable during a poll, the script prints a warning and retries on the next cycle instead of crashing.

#### Orchestrator State Machine

The script tracks these states and displays descriptive banners on each transition:

| State | Description | What the orchestrator is doing |
|---|---|---|
| `created` | Test created, waiting to start | Record exists in DB, no work started |
| `validating` | Pre-flight validation | Checking targets exist, snapshots exist, connectivity, emulator reachable |
| `setting_up` | Infrastructure setup | Reverting VMs to clean snapshots, deploying JMeter to load generators, deploying emulator to targets, running agent discovery |
| `calibrating` | Calibrating thread counts | Binary search: runs JMeter at different thread counts to find the count that produces target CPU utilization (e.g. 40-60%). Runs stability verification. Collects JMeter + emulator logs per iteration |
| `generating` | Generating operation sequences | Creates deterministic CSV files of operation sequences (CPU, disk, network, memory, file ops) sized for the calibrated thread count and profile duration |
| `executing` | Running load test | For each load profile: restores snapshots, deploys emulator, starts stats collection, runs JMeter for the configured duration, stops and collects stats/JTL/logs |
| `storing` | Storing results | Writes stats summary, thread count, JMX test case data, JTL paths to `SnapshotProfileDataORM` in the database. Marks snapshot as baseline for `new_baseline` tests |
| `comparing` | Comparing against baseline | (Only for `compare`/`compare_with_new_calibration`) Runs the comparison engine against stored baseline data. Produces per-metric verdicts |
| `completed` | Done | Terminal state -- test finished successfully |
| `failed` | Error | Terminal state -- test failed with error message |
| `cancelled` | Cancelled | Terminal state -- user cancelled via Ctrl+C or API |

**State transitions by test type:**

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

#### Calibration Progress Display

During the `calibrating` state, the DB query returns real-time calibration data displayed as:

```
Calibration: server=8 profile=1 threads=30 cpu=45.2% status=running iter=5 phase=binary_search
    Adjusting: CPU 45.2% within target range [40-60%]
```

Fields:
- `threads` -- reads `current_thread_count` (the working value during binary search), NOT `thread_count` (which is 0 until calibration completes and stores the final result)
- `cpu` -- last observed CPU utilization from emulator stats
- `iter` -- current iteration number in the binary search or stability check
- `phase` -- `binary_search` or `stability_attemptN`
- `message` -- status text from the calibration engine

---

### Phase 9: Final Report

After the polling loop exits (terminal state reached or timeout), the script prints:

- Test run ID
- Total elapsed time (minutes and seconds)
- Final state

**On `completed`:**
- Prints the verdict (`passed`, `failed`, `warning`)
- Queries `GET /api/baseline-tests/{id}/comparison-results` and prints per-target/profile comparison details (verdict, violation count)

**On `failed`:**
- Prints the error message from the API response
- Queries DB directly for additional error context

**On timeout:**
- Prints a failure message -- the test is still running on the orchestrator but the script stops waiting

---

### Cleanup: Stop Orchestrator

**Function:** `stop_orchestrator(proc)`

In the `finally` block, if the script started the orchestrator, it terminates the subprocess:
1. `proc.terminate()` -- sends SIGTERM
2. Waits up to 10 seconds for graceful shutdown
3. `proc.kill()` if it doesn't stop in time

If `--skip-orchestrator` was used, this step is skipped (the orchestrator was not started by this script).

---

### Ctrl+C Handling

If the user presses Ctrl+C during the polling loop:
1. Catches `KeyboardInterrupt`
2. Sends `POST /api/baseline-tests/{id}/cancel` to the orchestrator
3. The orchestrator will stop the current phase and transition to `cancelled` state
4. Script returns exit code 1

---

## Hardcoded Configuration

These values are set as constants at the top of the script and come from the lab setup (`setup_proxmox_lab.py` output and seed data):

### Target Servers

| Name | Server ID | Snapshot ID | Hostname | IP | Snapshot Name |
|---|---|---|---|---|---|
| linux | 8 | 3 | target-rky-01 | 10.0.0.92 | clean-rocky-baseline |
| windows | 9 | 4 | TARGET-WIN-01 | 10.0.0.91 | clean-win-baseline |

### Other IDs

| Entity | ID/Value |
|---|---|
| Scenario | 1005 (Normal Server Load) |
| Lab | 4 |
| Emulator API port | 8080 (on targets) |
| Orchestrator port | 8000 (localhost) |

---

## Directory Structure

### Source Directories (inputs)

```
agent_perf_testing/
  emulator_java/               # Java emulator source (Maven project)
    src/                        # Java source code
    pom.xml                     # Maven build file
    start.sh                    # Linux startup script
    start.ps1                   # Windows startup script
    target/                     # Maven output (emulator.jar)
  emulator/
    data/                       # DLP test files, normal files (copied into packages)
  orchestrator/
    config/orchestrator.yaml    # Orchestrator configuration
    src/orchestrator/           # Python package
    artifacts/
      jmx/                     # JMX templates (server-normal.jmx, etc.)
      packages/                 # Built deployment packages (tar.gz)
```

### Output Directories (generated during test)

```
orchestrator/
  logs/
    orchestrator_run.log        # Orchestrator stdout/stderr

  results/{test_run_id}/
    server_{server_id}/
      stats/
        lp{lp_id}_stats.json           # Raw stats from emulator
      jtl/
        lp{lp_id}.jtl                  # JMeter results (JTL)
      logs/
        lp{lp_id}_jmeter.log           # JMeter log file
        lp{lp_id}_emulator_logs.tar.gz # Emulator log files (tar.gz from API)
        calibration_{phase}_iter{N}/    # Per-calibration-iteration logs
          jmeter_cal.jtl
          jmeter_cal.log
          jmeter_stability.jtl
          jmeter_stability.log
          emulator_logs.tar.gz
      jmx_data/
        lp{lp_id}_ops_sequence.csv     # Operation sequence used for test
      comparison/                       # Comparison results (for compare tests)
      execution_manifest.json           # ExecutionResult paths for crash recovery

  generated/{test_run_id}/
    calibration/
      server_{server_id}/
        calibration_ops.csv             # 500K-row calibration CSV
    ops_sequences/
      {server_id}/
        ops_sequence_{profile_name}.csv # Deterministic operation sequence
```

### Remote Directories (on load generators)

```
/opt/jmeter/runs/baseline_{test_run_id}/
  lg_{loadgen_id}/target_{server_id}/
    test.jmx                          # JMX template
    calibration_ops.csv               # Calibration operation sequence
    ops_sequence_{profile_name}.csv   # Test operation sequence
    results_{profile_name}.jtl        # JMeter output (downloaded after test)
    jmeter_{profile_name}.log         # JMeter log (downloaded after test)
```

### Remote Directories (on target servers)

```
/opt/emulator/           (Linux)
C:\emulator\             (Windows)
  emulator.jar           # Deployed application
  start.sh / start.ps1   # Startup script
  data/                  # Test data files
  output/                # Emulator output (cleaned before each profile)
  stats/                 # Emulator stats (cleaned before each profile)
  *.log                  # Emulator log files (downloaded via /api/v1/logs/download)
```

---

## Log Collection

The framework collects three types of logs after each test phase completes:

### 1. Emulator Stats (JSON)
- Collected via: `GET /api/v1/stats/all?test_run_id={id}` on the emulator
- Contains: CPU, memory, disk I/O, network samples at configured intervals
- Saved to: `results/{id}/server_{sid}/stats/lp{lpid}_stats.json`
- Used for: calibration CPU measurement, comparison against baseline

### 2. JMeter Results (JTL)
- Collected via: SFTP download from load generator
- Contains: per-request latency, response code, timestamps
- Saved to: `results/{id}/server_{sid}/jtl/lp{lpid}.jtl`
- Used for: throughput and latency analysis

### 3. JMeter Logs
- Collected via: SFTP download from load generator
- Contains: JMeter startup, thread group status, errors, warnings
- Saved to: `results/{id}/server_{sid}/logs/lp{lpid}_jmeter.log`
- Used for: debugging JMeter issues (connection failures, thread errors)
- Non-fatal if download fails

### 4. Emulator Logs (tar.gz)
- Collected via: `GET /api/v1/logs/download` on the emulator (Java LogsController)
- Contains: all `*.log` files from the emulator directory, tar'd and gzipped
- Saved to: `results/{id}/server_{sid}/logs/lp{lpid}_emulator_logs.tar.gz`
- Used for: debugging emulator behavior, operation processing issues
- Non-fatal if download fails

### Calibration Logs
During calibration, logs are collected at the end of **each iteration** (not just the final result):
- Binary search iterations: saved under `logs/calibration_binary_search_iter{N}/`
- Stability check iterations: saved under `logs/calibration_stability_attempt{A}_iter{N}/`
- Each iteration directory contains: JMeter JTL, JMeter log, and emulator logs

This allows post-mortem analysis of why calibration converged (or failed to converge) to a particular thread count.

---

## What the Orchestrator Does After the Script Starts the Test

The script's role is to build, launch, create, and monitor. The actual test execution is performed by the orchestrator in a background thread. Here is what each orchestrator state does in detail:

### VALIDATING (`BaselinePreFlightValidator`)
- Checks all referenced DB entities exist (lab, scenario, targets, snapshots, load profiles)
- Verifies emulator is reachable on each target (`GET /health`)
- Verifies SSH/WinRM connectivity to targets and load generators
- Fails the test immediately if any check fails

### SETTING_UP (`_do_setup`)
- **Load generator setup** (deduplicated -- shared load generator only set up once):
  - Deploys JMeter package if not already installed
  - Creates per-target run directories on load generator
  - Uploads JMX template
  - For new_baseline/compare_with_new_calibration: generates and uploads a 500K-row calibration CSV
  - For compare: uploads stored JMX data from compare snapshot
- **Target server setup** (all targets):
  - Reverts VM to clean snapshot via hypervisor API (Proxmox)
  - Waits for SSH/WinRM to become reachable (port polling with timeout)
  - Updates IP address in DB if changed after snapshot restore
  - Deploys emulator package (tar.gz extracted to /opt/emulator)
  - Starts the emulator process
  - Cleans emulator output/stats directories
  - Runs agent discovery (OS version, installed agent versions)

### CALIBRATING (`CalibrationEngine.calibrate`)
For each (target x load_profile):
1. Health-checks the emulator
2. Binary search loop (configurable iterations):
   - Starts JMeter at current thread count
   - Waits for stats collection interval
   - Reads CPU utilization from emulator
   - Adjusts thread count: increase if CPU too low, decrease if too high
   - Stops JMeter, cleans up, collects logs
3. Stability verification:
   - Runs multiple consecutive checks at the converged thread count
   - All checks must produce CPU within target range
   - If stability fails, re-runs binary search with narrower bounds
4. Stores final `thread_count` to `CalibrationResultORM`

### GENERATING (`_do_generation`)
For each (target x load_profile):
- Reads calibrated thread count from DB
- Calculates sequence length: `thread_count * duration_sec * ops_per_second_estimate`
- Generates deterministic operation sequence CSV (CPU, disk, network, memory, file operations with specific parameters)
- Uploads CSV to load generator

### EXECUTING (`BaselineExecutionEngine.execute`)
For each load profile (with barriers between profiles):
1. **Restore** all targets to snapshot (parallel across targets)
2. **Deploy + configure** emulator on all targets:
   - Sets output folders, partner config, stats interval, service monitor patterns
   - Starts emulator test/stats collection
3. **Start JMeter** on all targets (barrier -- all start together)
4. **Wait** for `duration + ramp_up + margin` seconds
5. **Stop + collect** from all targets:
   - Stop JMeter process
   - Stop emulator test
   - Download stats JSON from emulator
   - Download JTL from load generator
   - Download JMeter log from load generator
   - Download emulator logs via API
   - Compute stats summary (with trim of start/end seconds)
   - Download JMX test case data CSV

### STORING (`_do_storing`)
For each (target x load_profile):
- Creates/updates `SnapshotProfileDataORM` record with:
  - `thread_count`, `jmx_test_case_data` path, `stats_data` path, `stats_summary` dict, `jtl_data` path
- Marks snapshot as `is_baseline = True` for new_baseline tests
- This data becomes the "stored baseline" that future `compare` tests compare against

### COMPARING (`ComparisonEngine`, compare tests only)
For each (target x load_profile):
- Loads current test stats and stored baseline stats
- Runs per-metric comparison (CPU, memory, disk, network) using configured thresholds
- Produces verdict per metric and overall: `passed`, `warning`, or `failed`
- Stores comparison results to `ComparisonResultORM`

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Maven build fails | Script exits with error message and build output |
| Orchestrator fails to start in 30s | Script exits |
| Login fails | Script exits |
| Load profile name not found in DB | Script exits |
| API call returns non-200 | Returns `None`, caller decides (polling retries, create/start exits) |
| API ReadTimeout or ConnectionError | Caught, returns `None`, polling loop retries on next cycle |
| Orchestrator process dies mid-test | API polls return `None`, script retries until timeout |
| Ctrl+C | Sends cancel API request, returns exit code 1 |
| Test reaches `failed` state | Prints error message and DB context, returns exit code 1 |
| Polling timeout (2 hours) | Prints timeout message, returns exit code 1 |
| JMeter log download fails | Warning logged, empty path stored -- non-fatal |
| Emulator log download fails | Warning logged, empty path stored -- non-fatal |

---

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Test completed successfully |
| 1 | Test failed, cancelled, timed out, or interrupted |
