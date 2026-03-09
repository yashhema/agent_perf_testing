# End-to-End Test Plan — Baseline-Compare on Proxmox

## Lab Environment

| VM | VMID | IP | OS | Role |
|----|------|----|----|------|
| ORCH-RKY-01 | 400 | 10.0.0.82 | Rocky 9.7 | Orchestrator |
| LOADGEN-RKY-01 | 401 | 10.0.0.83 | Rocky 9.7 | JMeter loadgen |
| TARGET-RKY-01 | 410 | 10.0.0.92 | Rocky 9.7 | Linux target |
| TARGET-WIN-01 | 321 | 10.0.0.91 | Win 2022 | Windows target |

- Proxmox host: 10.0.0.72 (Web UI: https://10.0.0.72:8006)
- All VMs on same subnet: 10.0.0.0/24, gateway 10.0.0.1
- Linux creds: root / Test1234!
- Windows creds: Administrator / Test1234!

---

## What the Orchestrator Handles Automatically

Once running, the orchestrator **does all of this without manual intervention**:

| Step | What It Does | How |
|------|-------------|-----|
| Snapshot restore | Reverts target VM to clean state | Proxmox API (`qm rollback`) |
| Wait for VM ready | Polls SSH/WinRM until reachable | `wait_for_ssh()` |
| Prereq install | Java JRE on loadgen, Python on targets | `prereq_script` from package member |
| JMeter deploy | Uploads + extracts JMeter archive to loadgen | `PackageDeployer` via SSH |
| Emulator deploy | Uploads + installs emulator on target | `PackageDeployer` via SSH |
| JMX upload | Copies `.jmx` test plan to loadgen run dir | `loadgen_exec.upload()` |
| Calibration | Binary search for thread count per load profile | `CalibrationEngine` |
| Ops sequence gen | Creates CSV test data for each profile | `OpsSequenceGenerator` |
| Test execution | Starts JMeter, collects stats, downloads results | `BaselineExecutionEngine` |
| Comparison | Cohen's d statistical analysis (compare mode) | `ComparisonEngine` |
| Storage | Persists results to DB for future comparisons | `SnapshotProfileDataORM` |

**You do NOT need to manually install JMeter, emulator, or Java.** The orchestrator deploys everything via SSH using the package group members registered in the DB.

---

## Prerequisites (one-time setup)

### Step 0: Verify VMs are running and reachable

From your laptop:
```bash
ssh root@10.0.0.82 "hostname"   # orch-rky-01
ssh root@10.0.0.83 "hostname"   # loadgen-rky-01
ssh root@10.0.0.92 "hostname"   # target-rky-01
```

For Windows:
```powershell
Test-NetConnection 10.0.0.91 -Port 5985
```

### Step 1: Run the DB setup script (on your Windows dev machine)

```bash
cd C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator
python scripts/setup_proxmox_lab.py
```

**What it creates (everything the orchestrator needs):**

| Category | Records |
|----------|---------|
| Hardware profiles | `Proxmox-4c-8g-40g`, `Proxmox-4c-8g-60g` |
| OS Baselines | `Rocky 9.7 Clean`, `Win 2022 Clean`, `Rocky 9.7 LoadGen` |
| Package groups | `jmeter-5.6.3`, `emulator-1.0` |
| Package members | JMeter for `rhel/9/*`, Emulator for `rhel/9/*` + `windows/2022` — with prereq scripts, install/extract/status commands |
| Lab | `Proxmox Lab` (execution_mode=baseline_compare, hypervisor=proxmox) |
| Servers | 4 VMs with OS version info, infra refs (node/vmid), default loadgen links |
| Scenario | `Normal Server Load` (template_type=server-normal, linked to JMeter package) |
| Snapshots | `clean-rocky97` for target-rky-01, `clean-win2022` for TARGET-WIN-01 |
| Load profiles | low (20-40% CPU, 300s), medium (40-60%, 600s), high (60-80%, 600s) |
| Admin user | admin / admin |

The script prints all **DB IDs** at the end — note them for the next steps.

### Step 2: Run the migration for baseline-compare fixes

Execute on SQL Server (orchestrator DB):
```sql
-- File: orchestrator/migrations/fix_baseline_compare_issues.sql
-- Adds: baseline_test_run_id FK to calibration_results,
--        makes test_run_id nullable, adds query indexes
```

### Step 3: Take clean snapshots on Proxmox

SSH into the Proxmox host (10.0.0.72):
```bash
qm snapshot 410 clean-rocky97 --description "Clean Rocky 9.7 baseline"
qm snapshot 321 clean-win2022 --description "Clean Win 2022 baseline"
```

These names **must match** the `provider_snapshot_id` values in the snapshot DB records:
- `clean-rocky97` → TARGET-RKY-01 (VMID 410)
- `clean-win2022` → TARGET-WIN-01 (VMID 321)

### Step 4: Update credentials.json

The setup script prints server IDs. Update `config/credentials.json` `by_server_id` keys to match:
```json
{
  "servers": {
    "by_server_id": {
      "<target_rky_id>": { "username": "root", "password": "Test1234!" },
      "<loadgen_id>":    { "username": "root", "password": "Test1234!" },
      "<target_win_id>": { "username": "Administrator", "password": "Test1234!" }
    }
  }
}
```

### Step 5: Start the orchestrator

```bash
cd C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator
python -m uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000
```

Web UI: http://localhost:8000
API docs: http://localhost:8000/docs

---

## Running a Test

### Create + start a baseline test

Use the IDs printed by the setup script:

```bash
# Create the test
curl -X POST http://localhost:8000/api/baseline-test-runs \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": <target_rky_id>,
    "scenario_id": <scenario_id>,
    "test_type": "new_baseline",
    "test_snapshot_id": <snapshot_id>,
    "load_profile_ids": [1, 2, 3]
  }'

# Start it (orchestrator does everything from here)
curl -X POST http://localhost:8000/api/baseline-test-runs/<test_id>/start
```

Or use the Web UI: Baseline Tests → New Baseline Test → fill form → Submit → Start.

### What happens automatically after you hit Start

```
created → validating → setting_up → calibrating → generating → executing → storing → completed
```

1. **Validating** — checks SSH/WinRM connectivity, emulator health, snapshot exists on Proxmox
2. **Setting up** — restores snapshot, deploys JMeter (with Java prereq) to loadgen, deploys emulator (with Python prereq) to target, uploads JMX template
3. **Calibrating** — binary search per load profile to find thread count for target CPU range
4. **Generating** — creates ops_sequence CSV per load profile, uploads to loadgen
5. **Executing** — for each load profile: restore snapshot → deploy emulator → start stats → run JMeter → collect results
6. **Storing** — persists thread counts, stats, JTL paths to DB as `SnapshotProfileDataORM`

### Monitor progress

```bash
# Poll status
curl http://localhost:8000/api/baseline-test-runs/<test_id>

# Watch orchestrator console logs for real-time progress
```

---

## What Happens at Each Stage (detailed)

### Validating
- Checks load profiles exist in DB
- Verifies server and loadgen are SSH/WinRM reachable
- Confirms emulator health on target (port 8080)
- Validates snapshot exists on Proxmox hypervisor

### Setting Up
- Reverts target VM to clean snapshot via Proxmox API
- Waits for SSH to come back (`wait_for_ssh`, 120s timeout)
- Resolves package groups → OS-specific members (regex match on `rhel/9/7`)
- Runs prereq scripts (`rhel/java_jre.sh` on loadgen, `rhel/python_emulator.sh` on target)
- Deploys JMeter archive to loadgen, extracts to `/opt/jmeter`
- Deploys emulator archive to target, installs via pip, starts on port 8080
- Creates run directory on loadgen: `/opt/jmeter/runs/baseline_<test_id>/lg_<lg_id>/target_<srv_id>/`
- Uploads JMX test plan (`artifacts/jmx/server-normal.jmx`) to run dir

### Calibrating (for `new_baseline` and `compare_with_new_calibration`)
- Deploys calibration ops_sequence CSV to loadgen
- For each load profile, binary search:
  - Start JMeter with N threads for 30s
  - Read CPU stats from emulator (last 20 samples)
  - Adjust thread count up/down based on CPU vs target range
  - Confirm stable with 2 consecutive passes
- Temp files: `/tmp/calibration_r<run_id>_s<srv_id>_lp<lp_id>.{jtl,log}`
- Saves `CalibrationResultORM` to DB with found thread_count

### Generating
- Creates ops_sequence CSV for each load profile using calibrated thread count
- Dispatches to correct generator based on `scenario.template_type`:
  - `server_normal` → `ServerNormalOpsGenerator`
  - `server_file_heavy` → `ServerFileHeavyOpsGenerator`
  - `db_load` → `DbLoadOpsGenerator`
- Uploads CSV to loadgen at run_dir path

### Executing
- For each load profile:
  1. Reverts target VM to snapshot (fresh state per profile)
  2. Waits for SSH, deploys emulator if needed, cleans working dirs
  3. Configures emulator (input/output folders, partner, stats interval)
  4. Starts emulator stats collection
  5. Starts JMeter on loadgen with calibrated thread_count + ramp_up + duration
  6. Waits for duration + ramp_up + 20% margin
  7. Stops JMeter, stops emulator test
  8. Downloads stats JSON and JTL from remote
  9. Computes trimmed stats summary
- Results saved to: `results/<test_id>/server_<srv_id>/stats/`, `jtl/`, `jmx_data/`
- Execution manifest persisted to: `results/<test_id>/server_<srv_id>/execution_manifest.json`

### Comparing (for `compare` and `compare_with_new_calibration`)
- Loads stored baseline profile data from DB (`SnapshotProfileDataORM`)
- Runs Cohen's d statistical comparison for each metric
- Verdict: negligible/small → passed, medium → warning, large → failed
- Creates `ComparisonResultORM` in DB
- Saves comparison JSON to: `results/<test_id>/server_<srv_id>/comparison/`

### Storing
- Persists calibration results, stats summaries, and thread counts to `SnapshotProfileDataORM`
- Links data to test snapshot for future comparison runs

---

## Verification Checklist

| # | Check | How to Verify |
|---|-------|---------------|
| 1 | VMs reachable | SSH/WinRM from orchestrator machine |
| 2 | DB tables + data created | `SELECT COUNT(*) FROM servers` returns 4 |
| 3 | Snapshot exists on Proxmox | `qm listsnapshot 410` shows `clean-rocky97` |
| 4 | Snapshot restored correctly | Proxmox UI shows target VM at baseline snapshot |
| 5 | SSH reconnects after restore | Orchestrator log: "Port 22 reachable on 10.0.0.92" |
| 6 | Java installed on loadgen | Orchestrator log: prereq script completed |
| 7 | JMeter deployed to loadgen | Orchestrator log: "Package 'jmeter-5.6.3' already installed" or deployed |
| 8 | Emulator deployed + healthy | Orchestrator log: emulator health check passed |
| 9 | Calibration runs | Log shows binary search iterations with thread counts |
| 10 | JMeter starts on loadgen | `ssh root@10.0.0.83 "ps aux \| grep jmeter"` shows process |
| 11 | Stats collected | `results/<id>/server_<srv_id>/stats/lp*_stats.json` exists |
| 12 | JTL downloaded | `results/<id>/server_<srv_id>/jtl/lp*.jtl` exists |
| 13 | Ops sequence CSV generated | `generated/<id>/` contains CSV files |
| 14 | Execution manifest saved | `results/<id>/server_<srv_id>/execution_manifest.json` exists |
| 15 | State reaches `completed` | `GET /api/baseline-test-runs/<id>` returns `state: "completed"` |
| 16 | CalibrationResult in DB | `SELECT * FROM calibration_results WHERE baseline_test_run_id = <id>` |
| 17 | StoredProfileData in DB | `SELECT * FROM stored_profile_data WHERE baseline_test_run_id = <id>` |

---

## Path Isolation Reference

All paths include test_run_id, server_id, and loadgen_id to prevent collisions when running concurrent tests.

### Remote paths (on loadgen)

| Path | Purpose |
|------|---------|
| `/opt/jmeter/runs/baseline_<test_id>/lg_<lg_id>/target_<srv_id>/test.jmx` | JMX test plan |
| `/opt/jmeter/runs/baseline_<test_id>/lg_<lg_id>/target_<srv_id>/results_<lp_name>.jtl` | JMeter results |
| `/opt/jmeter/runs/baseline_<test_id>/lg_<lg_id>/target_<srv_id>/jmeter_<lp_name>.log` | JMeter log |
| `/opt/jmeter/runs/baseline_<test_id>/lg_<lg_id>/target_<srv_id>/calibration_ops.csv` | Calibration CSV |
| `/tmp/calibration_r<run_id>_s<srv_id>_lp<lp_id>.jtl` | Calibration temp JTL |
| `/tmp/calibration_r<run_id>_s<srv_id>_lp<lp_id>.log` | Calibration temp log |
| `/tmp/calibration-stability_r<run_id>_s<srv_id>_lp<lp_id>.jtl` | Stability check JTL |

### Local paths (on orchestrator)

| Path | Purpose |
|------|---------|
| `results/<test_id>/server_<srv_id>/stats/lp<lp_id>_stats.json` | Collected stats |
| `results/<test_id>/server_<srv_id>/jtl/lp<lp_id>.jtl` | Downloaded JTL |
| `results/<test_id>/server_<srv_id>/jmx_data/lp<lp_id>_ops_sequence.csv` | Ops sequence CSV |
| `results/<test_id>/server_<srv_id>/execution_manifest.json` | Execution results manifest |
| `results/<test_id>/server_<srv_id>/comparison/` | Comparison results JSON |
| `generated/<test_id>/calibration/server_<srv_id>/calibration_ops.csv` | Calibration CSV (local) |

---

## Package Deployment Details

The orchestrator auto-deploys software via `PackageDeployer`. Each package group has OS-specific members with install instructions.

### JMeter (on loadgen)

| Field | Value |
|-------|-------|
| OS match | `rhel/9/.*` |
| Package archive | `artifacts/packages/jmeter-5.6.3-linux.tar.gz` |
| Install path | `/opt/jmeter` |
| Prereq script | `prerequisites/rhel/java_jre.sh` (installs Java JRE) |
| Status check | `test -x /opt/jmeter/bin/jmeter` |

### Emulator — Linux (on target)

| Field | Value |
|-------|-------|
| OS match | `rhel/9/.*` |
| Package archive | `artifacts/packages/emulator-linux.tar.gz` |
| Install path | `/opt/emulator` |
| Prereq script | `prerequisites/rhel/python_emulator.sh` (installs Python 3 + pip) |
| Install command | `pip3 install -r requirements.txt` |
| Run command | `uvicorn app.main:app --host 0.0.0.0 --port 8080` |
| Status check | `curl -sf http://localhost:8080/health` |

### Emulator — Windows (on target)

| Field | Value |
|-------|-------|
| OS match | `windows/2022` |
| Package archive | `artifacts/packages/emulator-windows.tar.gz` |
| Install path | `C:\emulator` |
| Prereq script | `prerequisites/windows_server/python_emulator.ps1` |
| Status check | `Invoke-WebRequest http://localhost:8080/health` |

---

## Configuration Reference

### orchestrator.yaml

```yaml
calibration:
  observation_duration_sec: 30
  observation_reading_count: 20
  max_thread_count: 30          # Upper bound for 4-core VMs
  max_calibration_iterations: 50
  stability_min_in_range_pct: 55.0
  stability_max_below_pct: 10.0

stats:
  collect_interval_sec: 5
  stats_trim_start_sec: 30      # Trim first 30s of stats (settling time)
  stats_trim_end_sec: 10        # Trim last 10s of stats (cooldown)

barrier:
  barrier_timeout_margin_percent: 0.20  # 20% extra wait after duration

emulator:
  emulator_api_port: 8080

database:
  url: "mssql+pyodbc://@localhost/orchestrator?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
```

### Load Profiles (seeded by setup script)

| Name | CPU Target | Duration | Ramp Up |
|------|-----------|----------|---------|
| low | 20-40% | 300s (5 min) | 30s |
| medium | 40-60% | 600s (10 min) | 60s |
| high | 60-80% | 600s (10 min) | 60s |

---

## Troubleshooting

### Test stuck in "validating"
- Check orchestrator logs for validation errors
- Verify SSH connectivity to target and loadgen
- Verify emulator is running: `curl http://<target_ip>:8080/health`
- Verify snapshot exists: `qm listsnapshot <vmid>`

### Package deploy fails
- Check prereq script output in orchestrator logs
- Verify the package archive exists in `artifacts/packages/`
- Check OS match regex: server's `os_vendor_family/os_major_ver/os_minor_ver` must match (e.g., `rhel/9/7`)
- Manually test SSH: `ssh root@<ip> "java -version"` or `python3 --version`

### Calibration fails to converge
- Check `max_thread_count` in config (30 is reasonable for 4-core VMs)
- Check `max_calibration_iterations` (50 should be enough)
- Look at calibration logs for CPU readings — if always 0%, emulator may not be running
- If CPU readings are erratic, increase `observation_reading_count`

### JMeter fails to start
- Verify JMeter is installed: `ssh root@10.0.0.83 "ls /opt/jmeter/bin/jmeter"`
- Check Java: `ssh root@10.0.0.83 "java -version"`
- Check JMeter log on loadgen: `/opt/jmeter/runs/baseline_<id>/lg_<lg_id>/target_<srv_id>/jmeter_*.log`

### Snapshot restore hangs
- Check Proxmox task log in Web UI
- Verify VM is not locked: `qm unlock <vmid>` on Proxmox host
- Check `infrastructure.snapshot_restore_timeout_sec` (default 600s)

### Stats collection returns empty
- Verify emulator started test: check emulator logs on target
- Verify `collect_interval_sec` is reasonable (5s default)
- Check emulator API: `curl http://<target_ip>:8080/api/stats`

### Connection refused after snapshot restore
- Wait time may be insufficient — check `wait_for_ssh()` timeout (120s default)
- VM may have different IP after restore — check Proxmox guest agent for current IP
- For Windows, verify WinRM is enabled and port 5985 is open

### credentials.json server ID mismatch
- The setup script prints server IDs — they depend on DB auto-increment state
- If IDs don't match credentials.json, the orchestrator can't authenticate to VMs
- Fix: update `by_server_id` keys in `config/credentials.json` to match actual DB IDs
