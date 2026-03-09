# Baseline Compare Mode — Runbook

Step-by-step guide for using the orchestrator's baseline compare mode to measure security agent performance impact on VMs managed by vSphere or Proxmox.

---

## Prerequisites

Before you begin, ensure:

- [ ] A lab exists with `execution_mode = baseline_compare`
- [ ] Target server is registered under the lab with hypervisor credentials configured
- [ ] A load generator server is registered (or set as `default_loadgen_id` on the target server)
- [ ] At least one scenario exists with load profiles defined
- [ ] The emulator is deployed on the target server (or configured as a package for auto-deploy)
- [ ] JMeter is installed on the load generator (or configured as a package for auto-deploy)
- [ ] You can access the orchestrator web UI at `http://<orchestrator-host>:<port>`

---

## Workflow 1: First-Time Setup — Creating a New Baseline

Use this workflow when you have a fresh server and want to establish a baseline (no agent installed) that future agent tests will compare against.

### Step 1: Prepare the Server

1. Install and configure the operating system on the target VM
2. Deploy the emulator application on the server
3. Verify the emulator is accessible: `curl http://<server-ip>:8080/api/v1/operations/cpu -X POST -H "Content-Type: application/json" -d '{"duration_ms":100,"intensity":0.5}'`
4. Ensure no security agents are installed (this is your clean baseline)

### Step 2: Take a Snapshot of the Clean State

1. Navigate to **Snapshot Manager** (`/snapshots` in the sidebar under "Baseline Compare")
2. Select your target server from the dropdown
3. Click **Sync from Hypervisor** to pull any existing snapshots
4. Click **Take Snapshot**
5. Enter a descriptive name, e.g.: `Clean Base - Ubuntu 22.04 - 2026-03-07`
6. Optionally add a description: `Clean OS with emulator deployed, no security agents`
7. Click **Save**
8. The snapshot appears in the tree. This will become your baseline.

### Step 3: Create a New Baseline Test

1. Navigate to **Create Baseline Test** (`/baseline-tests/create` in the sidebar)
2. **Step 1 — Lab & Scenario:**
   - Select your lab (only labs with `baseline_compare` mode appear)
   - Select the scenario that defines your test configuration
   - Click **Next**
3. **Step 2 — Server & Test Type:**
   - Select the target server
   - Test Type: select **new_baseline**
   - Load Generator and Partner will auto-fill from server defaults (override if needed)
   - Click **Next**
4. **Step 3 — Snapshots:**
   - **Test Snapshot:** Select the snapshot you just created (`Clean Base - Ubuntu 22.04 - ...`)
   - **Compare Snapshot:** Not shown (not applicable for new_baseline)
   - Click **Next**
5. **Step 4 — Load Profiles:**
   - Check the load profiles you want to include (e.g., Light, Medium, Heavy)
   - At least one is required
   - Click **Next**
6. **Step 5 — Review:**
   - Verify all settings are correct
   - Click **Create Baseline Test**

### Step 4: Run the Baseline Test

1. You are redirected to the **Dashboard** page
2. Click the **Play** button to start the test
3. The test progresses through states:
   - `validating` — Checking server access, snapshot existence
   - `setting_up` — Restoring VM to snapshot, deploying emulator, discovering OS
   - `calibrating` — Finding optimal thread count per load profile (binary search targeting CPU%)
   - `generating` — Creating operation sequence CSVs
   - `executing` — Running JMeter tests, collecting system stats
   - `storing` — Saving calibration data, stats, and JTL files to the snapshot
   - `completed` — Done
4. The dashboard auto-refreshes every 5 seconds. Watch the Load Profile Progress table for per-LP status.
5. If the test fails, check the error message displayed in the red alert box.

### Step 5: Verify the Baseline

1. Navigate to **Snapshot Manager**
2. Select your server and click the baseline snapshot
3. The **Profile Data** panel at the bottom should show stored data for each load profile:
   - Thread count (calibrated)
   - Stats file (check mark)
   - JTL file (check mark)
   - JMX data (check mark)
4. The snapshot should now show a **[baseline]** badge in the tree

Your baseline is ready. You can now run comparison tests against it.

---

## Workflow 2: Compare Test — Measuring Agent Impact

Use this workflow when you want to measure the performance impact of a security agent by comparing against a stored baseline.

### Step 1: Install the Security Agent

1. Restore the VM to a clean state (use Snapshot Manager > **Revert VM** to your baseline snapshot)
2. Install the security agent you want to evaluate
3. Configure the agent as needed
4. Verify the agent is running: check process list, service status
5. Verify the emulator still works: `curl http://<server-ip>:8080/api/v1/operations/cpu -X POST -H "Content-Type: application/json" -d '{"duration_ms":100,"intensity":0.5}'`

### Step 2: Take a Snapshot with the Agent

1. Navigate to **Snapshot Manager**
2. Select your server
3. Click **Take Snapshot**
4. Enter a descriptive name, e.g.: `With CrowdStrike v7.2 - 2026-03-07`
5. Add description: `CrowdStrike Falcon Sensor v7.2 installed, default policy`
6. Click **Save**

### Step 3: Create a Compare Test

1. Navigate to **Create Baseline Test**
2. **Step 1 — Lab & Scenario:** Same lab and scenario as the baseline
3. **Step 2 — Server & Test Type:**
   - Same target server
   - Test Type: select **compare**
4. **Step 3 — Snapshots:**
   - **Test Snapshot:** Select the snapshot with the agent (`With CrowdStrike v7.2 - ...`)
   - **Compare Snapshot:** Select your baseline snapshot (`Clean Base - Ubuntu 22.04 - ...`)
   - The compare snapshot should show "Stored data: LP#1 (X threads), LP#2 (Y threads), ..." confirming baseline data exists
5. **Step 4 — Load Profiles:** Select the same load profiles used in the baseline
6. **Step 5 — Review & Create**

### Step 4: Run and Monitor

1. Click **Play** on the dashboard
2. The compare test skips calibration (uses baseline's thread counts):
   - `validating` → `setting_up` → `executing` → `comparing` → `storing` → `completed`
3. The `comparing` state computes Cohen's d for each metric across all test types and load profiles
4. Watch for the **Verdict** badge to appear: passed (green), warning (yellow), or failed (red)

### Step 5: Review Results

1. Click **View Results** (or navigate to `/baseline-tests/{id}/results`)
2. **Cohen's d Matrix (Table 1):**
   - Rows: CPU%, Memory%, Disk Read/Write, Network Sent/Recv, per-process metrics
   - Columns: Test type x Load Profile (Normal LP1, Normal LP2, ..., Stress LP3)
   - Each cell shows the Cohen's d value, color-coded:
     - Green (< 0.2): Negligible impact
     - Yellow (0.2–0.5): Small impact
     - Orange (0.5–0.8): Medium impact
     - Red (>= 0.8): Large impact
3. **Click any cell** to see the Percentile Detail (Table 2):
   - Base vs Initial breakdown: Avg, P50, P90, P95, P99, StdDev
   - Delta row showing the absolute difference
   - Sample counts
4. **Overall verdict** at the top summarizes pass/fail

### Interpreting Results

| Pattern | What it means | Action |
|---------|--------------|--------|
| All green | Agent has negligible performance impact | Approve for deployment |
| CPU% yellow/orange, rest green | Agent uses noticeable CPU but doesn't affect other resources | Review CPU budget |
| Memory% red | Agent uses significant memory | Check agent configuration, memory limits |
| Green at LP1, red at LP3 | Agent impact scales with load | Agent has scaling issues under high concurrency |
| Red only in Stress columns | Agent reacts to suspicious activities (expected) | Review if reaction time is acceptable |

---

## Workflow 3: Compare with New Calibration

Use this workflow when the server environment has changed since the baseline was created (e.g., OS upgrade, hardware change, VM resource reallocation) and you need fresh calibration data.

### When to Use This Instead of Regular Compare

- VM was moved to different host hardware
- CPU/memory allocation changed
- OS was updated or reconfigured
- Significant time has passed since baseline creation
- You suspect the baseline calibration is no longer representative

### Steps

The process is identical to Workflow 2 (Compare Test) with one difference:

**Step 3 — Create the Test:**
- Test Type: select **compare_with_new_calibration** instead of **compare**

**What changes in execution:**
- The test runs calibration on the test snapshot (fresh thread count discovery)
- Generates new operation sequence CSVs
- Then executes and compares against the baseline's stored stats
- Stores the fresh calibration + results in the test snapshot

**State flow:**
```
validating -> setting_up -> calibrating -> generating -> executing -> comparing -> storing -> completed
```

This takes longer than a regular compare test (calibration adds time), but ensures the test parameters match the current server capabilities.

---

## Workflow 4: Comparing Multiple Agents

To evaluate multiple security agents against the same baseline:

1. **Create one baseline** (Workflow 1) — this is your reference point
2. **For each agent:**
   a. Revert VM to baseline snapshot (Snapshot Manager > Revert VM)
   b. Install the agent
   c. Take a snapshot (e.g., `With AgentX v2.1`, `With AgentY v1.0`, `With AgentZ v3.5`)
   d. Run a compare test against the baseline
3. **Compare results** across agents by viewing each test's results page

The snapshot tree will look like:

```
Clean Base [baseline] [has data]
  +-- With AgentX v2.1 [has data]
  +-- With AgentY v1.0 [has data]
  +-- With AgentZ v3.5 [has data]
```

Each agent's compare test produces its own Cohen's d matrix, allowing side-by-side evaluation.

---

## Workflow 5: Re-Baselining

When you need to create a new baseline (e.g., new OS version, new server hardware):

1. Prepare the new server environment
2. Take a new snapshot
3. Run a `new_baseline` test against the new snapshot
4. Future compare tests should use this new snapshot as their `compare_snapshot`
5. The old baseline snapshot can be archived via Snapshot Manager (it remains in the DB for historical reference)

---

## Troubleshooting

### Test stuck in "setting_up"
- Check target server is reachable (SSH/WinRM)
- Check hypervisor credentials are correct
- Check snapshot exists on the hypervisor (use Sync from Hypervisor)
- Check emulator is deployed and port is open

### Test fails during "calibrating"
- CPU target range may be unreachable — check load profile CPU range settings
- Server may be too slow or too fast for the configured thread count bounds
- Check calibration logs for iteration details

### Compare test says "no stored data for load profile"
- The compare snapshot must have SnapshotProfileData for ALL selected load profiles
- Run a `new_baseline` test first to populate the data
- Check Snapshot Manager > Profile Data panel to verify what's stored

### Cohen's d shows "large" for memory but "negligible" for CPU
- The agent consumes significant memory but doesn't impact CPU
- This is common for agents with large signature databases or in-memory caches
- Check per-process metrics to see exact agent memory usage

### All cells are "negligible" but you expected impact
- The load profile may be too light to surface the agent's impact
- Try heavier load profiles (more threads, longer duration)
- Check if the agent was actually running during the test (review discovery info)

---

## Quick Reference

### Sidebar Navigation

Under **Baseline Compare**:
- **Baseline Tests** — List all test runs, filter by server/state
- **Create Baseline Test** — 5-step wizard
- **Snapshot Manager** — Manage VM snapshots

### Key URLs

| Page | URL |
|------|-----|
| Snapshot Manager | `/snapshots` |
| Baseline Test List | `/baseline-tests` |
| Create Wizard | `/baseline-tests/create` |
| Test Dashboard | `/baseline-tests/{id}/dashboard` |
| Test Results | `/baseline-tests/{id}/results` |

### Cohen's d Legend

| Value | Effect | Color | Meaning |
|-------|--------|-------|---------|
| < 0.2 | Negligible | Green | No measurable agent impact |
| 0.2–0.5 | Small | Yellow | Minor impact, likely acceptable |
| 0.5–0.8 | Medium | Orange | Noticeable impact, review recommended |
| >= 0.8 | Large | Red | Significant impact, likely unacceptable |
