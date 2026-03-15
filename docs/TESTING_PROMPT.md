# Agent Performance Testing — Continuation Prompt

## Your Mission

You are continuing work on a **distributed performance testing framework** that measures the overhead of security agents (EDR, AV, DLP) on servers. The system runs controlled load tests before and after agent installation, then statistically compares results.

**Current task: Run a successful `new_baseline` test on the Linux target (server 8, Rocky Linux) using the `server-steady` template (scenario 1004).** Previous runs (up to Run 27) failed during calibration. Two bugs were fixed — now we need to verify the fixes by running a new test.

---

## What Was Just Fixed (not yet tested)

### Fix 1: Missing `set_config()` in calibration (baseline_orchestrator.py)
- `_do_calibration()` never called `em_client.set_config()` with partner + output_folders
- Mixed-load JMX templates (server-steady, server-file-heavy) send requests to `/networkclient` (20%) and `/file` (10%), both returning HTTP 400 instantly when emulator is unconfigured
- This caused threads to cycle through errors at ~2ms each instead of doing real CPU work → 0% CPU readings
- **Fix**: Added `set_config()` call in `_do_calibration()` before pool allocation, matching the pattern in `baseline_execution.py`

### Fix 2: JMeter timing race in calibration (calibration.py)
- JMeter `duration_sec` was set to exactly match the orchestrator sleep time (observation: 45s sleep, 45s JMeter; stability: 75s sleep, 75s JMeter)
- JMeter has 1-2s startup overhead, so it finishes before the orchestrator reads stats → 0% CPU
- **Fix**: Set JMeter `duration_sec=3600` (1 hour) in both `_run_observation()` and `_run_stability_check()`. JMeter never self-terminates during calibration. Orchestrator reads stats while load is guaranteed active, then explicitly kills JMeter via `jmeter_controller.stop(pid)`.

---

## How to Run a Test

```bash
# From agent_perf_testing/ directory
python run_baseline_test.py --target linux --profile low --test-type new_baseline

# Skip Maven build if jar is already current
python run_baseline_test.py --target linux --profile low --test-type new_baseline --skip-build

# Skip orchestrator start if already running
python run_baseline_test.py --skip-build --skip-orchestrator
```

The script (`run_baseline_test.py`) does everything: builds emulator jar, starts orchestrator, creates test via API, monitors state machine, reports verdict.

**Current hardcoded values in `run_baseline_test.py`:**
- `SCENARIO_ID = 1004` — Proxmox Baseline Steady (template_type = `server-steady`)
- `LAB_ID = 4`
- Linux target: server_id=8, snapshot_id=3, IP 10.0.0.92
- Windows target: server_id=9, snapshot_id=4, IP 10.0.0.91

---

## Template Types (Critical Concept)

The `template_type` is set on the **scenario** in the DB (`scenarios` table). It determines which JMX file is used, what sequence generator runs, and how calibration/execution behave.

```python
# orchestrator/src/orchestrator/models/enums.py
class TemplateType(str, Enum):
    server_normal = "server-normal"       # CSV-driven: cpu/mem/disk ops via SwitchController (500ms each)
    server_file_heavy = "server-file-heavy"  # File-heavy variant with /networkclient + /file
    db_load = "db-load"                   # Database load variant
    server_steady = "server-steady"       # /work endpoint with pre-allocated pool (5-10ms ops)
```

**How template_type flows through the system:**
1. **Scenario** in DB has `template_type` column → e.g. scenario 1004 = `server-steady`
2. **Setup** (`_do_setup`): selects JMX file → `artifacts/jmx/{template_type.value}.jmx`
3. **Generation** (`_do_generation`): dispatches to generator by template_type; `server_steady` skips CSV generation entirely (no ops_sequence needed)
4. **Calibration**: template-agnostic but `server-steady` and `server-file-heavy` need pool allocation + `set_config()` for partner/output_folders
5. **Execution**: `server-steady` and `server-file-heavy` get `extra_properties` (pool_gb, cpu_ms, etc.) passed as JMeter -J flags
6. **Comparison**: template-agnostic (compares raw stats regardless of how load was generated)

**Templates that need pool + set_config during calibration:**
```python
# baseline_orchestrator.py
_POOL_RAM_PERCENT = {
    TemplateType.server_steady: 0.6,      # 60% of target RAM
    TemplateType.server_file_heavy: 0.4,  # 40% of target RAM
}
```

---

## Key Diagnostic Scripts

When debugging test failures, these scripts let you test components independently:

| Script | Purpose | Usage |
|--------|---------|-------|
| `test_steady_load.py` | Steady-state load: worker threads calling `/work`, stats observer tracking CPU/mem | `python test_steady_load.py 10.0.0.92 5 60 10` (host, threads, duration, cpu_ms) |
| `test_emulator_endpoints.py` | Tests all emulator endpoints after deployment (health, config, cpu, mem, disk, net, file) | `python test_emulator_endpoints.py linux` |
| `test_deploy_all.py` | Tests real orchestrator code paths: snapshot restore, SSH/WinRM, package deploy, health check | `python test_deploy_all.py` |
| `test_all_packages.py` | Validates emulator + JMeter deployments on all targets and loadgen | `python test_all_packages.py` |
| `test_check_emulator.py` | Checks emulator deployment state: files, pip packages, startup, health | `python test_check_emulator.py` |
| `test_emulator_deploy.py` | Deploys emulator to Windows target, runs start.ps1, validates health | `python test_emulator_deploy.py` |
| `check_win.py` | Quick WinRM connectivity check on Windows target | `python check_win.py` |

---

## Key Documentation (in `docs/`)

| File | What It Contains |
|------|------------------|
| `Architecture.md` | Full system design: components, DB tables (15 ORM entities), 9-state machine, stats format, JMX templates, emulator API endpoints |
| `RUN_BASELINE_TEST_SPECIFICATION.md` | Complete guide to `run_baseline_test.py`: all 9 phases, CLI args, state machine, monitoring, error handling, directory structure |
| `workfile.txt` | **Source code change log** — every change to src/ code with date, file, and summary. **You MUST add an entry here for every code change you make.** |
| `BASELINE_MULTI_SERVER_DESIGN.md` | Multi-server coordination design |
| `snapshot_hierarchy_explained.md` | Snapshot tree model and lineage tracking |
| `JAVA_EMULATOR_CONTEXT.md` | Context on Java emulator (Spring Boot 3.2.4, OSHI stats) |
| `JAVA_EMULATOR_API_SPEC.md` | Java emulator REST API specification |

---

## Hard Rules

1. **No mid-run fixes**: Test runs either pass or fail completely. Never correct issues mid-run or restart from middle. Let it fail, analyze logs, fix code, rerun from scratch.
2. **All src code changes must be documented**: Every change to source code must have a summary entry in `docs/workfile.txt` with date, file path, and description.
3. **Don't guess — read the code**: Before changing anything, read the relevant file. The codebase is well-structured but has subtle interactions (e.g., set_config must happen before calibration for mixed-load templates).

---

## Architecture Quick Reference

**3 physical roles:**
- **Orchestrator** (this machine, Windows): FastAPI + state machine + MSSQL DB. Port 8000.
- **Target Server** (Linux 10.0.0.92 / Windows 10.0.0.91): Java emulator (Spring Boot). Port 8080.
- **Load Generator** (Linux): JMeter. Controlled via SSH from orchestrator.

**State machine:** `created → validating → setting_up → calibrating → generating → executing → storing → completed`

**Key source paths:**
```
orchestrator/src/orchestrator/
  core/baseline_orchestrator.py    # State machine, setup, calibration coordination
  core/calibration.py              # Binary search + stability verification
  core/baseline_execution.py       # 5-phase barrier execution engine
  core/baseline_validation.py      # Pre-flight checks
  services/comparison.py           # Cohen's d statistical comparison
  services/sequence_generator.py   # Generates ops_sequence CSV by template_type
  infra/jmeter_controller.py       # Start/stop JMeter via SSH
  infra/emulator_client.py         # HTTP client for emulator REST API
  infra/remote_executor.py         # SSH/WinRM execution
  models/orm.py                    # 15 SQLAlchemy ORM entities
  models/enums.py                  # All enums (TemplateType, BaselineTestState, etc.)
  config/settings.py               # AppConfig from orchestrator.yaml
```

**Emulator (Java) source:** `emulator_java/src/main/java/com/emulator/`

**Results go to:** `orchestrator/results/{test_run_id}/server_{server_id}/` (stats/, jtl/, logs/, jmx_data/)

**Orchestrator log:** `orchestrator/logs/orchestrator_run.log`

---

## RUN_BASELINE_TEST_SPECIFICATION.md — Needed Updates

The spec at `docs/RUN_BASELINE_TEST_SPECIFICATION.md` has these outdated values that should be corrected:

1. **Scenario ID**: Spec says `1005` (Normal Server Load / server-normal). Script now uses `1004` (Proxmox Baseline Steady / server-steady). Update the payload example and hardcoded config table.
2. **Template type context**: The spec doesn't explain that `template_type` on the scenario determines the entire test behavior (JMX selection, CSV generation, pool allocation). Consider adding a brief section or cross-reference to Architecture.md Section 6.
3. **server-steady specifics**: The spec describes `server-normal` flow (CSV Data Set Config, SwitchController). It should note that `server-steady` skips CSV generation, needs pool allocation before calibration, and uses ThroughputController-based operation mix (68% /work, 10% /file, 20% /networkclient, 1% /cpu spike, 1% /suspicious).
4. **Calibration behavior**: The spec says JMeter runs for `observation_duration_sec` (30s). This was changed — JMeter now runs with `duration_sec=3600` and is explicitly killed after stats are read. Update the CALIBRATING section.
5. **set_config during calibration**: The spec's CALIBRATING section doesn't mention that mixed-load templates need `set_config()` (partner + output_folders) before calibration can work. This is now done in `_do_calibration()`.

---

## Recent Bug History (for context)

All fixes are documented in `docs/workfile.txt`. Key ones from Run 27 debugging:

- **JMeter SwitchController StackOverflow**: Sampler testnames didn't match `${op_type}` values from CSV → infinite recursion
- **OSHI CPU 0%**: Stats collection ran in same async event loop as HTTP handlers → moved to daemon thread
- **WinRM timeout**: Default 30s read_timeout too short for tar extraction → increased to 120s
- **Calibration unique constraint**: NULL test_run_id in baseline runs caused SQL Server NULL==NULL collision
- **Cohen's d false-positive on memory**: Low variance (0.2% std) triggered large effect size on meaningless 70MB difference → added minimum delta thresholds
- **SSH keepalive**: Paramiko connection went stale during 25min idle → added transport.set_keepalive(30)
- **set_config missing in calibration**: /networkclient and /file returned 400 → added set_config() call
- **JMeter timing race in calibration**: JMeter finished before stats read → set duration=3600, explicit kill
