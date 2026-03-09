# Comparison Methodology — Agent Performance Impact Analysis

## Purpose

This document describes how the orchestrator compares **base** (no agent) vs **initial** (with agent) test phases to determine the performance impact of installing a security agent on a server.

---

## Test Execution Matrix

Each test run executes a matrix of **3 test types x N load profiles**:

| Test Type       | JMX File              | What it exercises                                |
|-----------------|-----------------------|--------------------------------------------------|
| Normal (load)   | server-normal.jmx     | CPU, Memory, Disk operations via CSV sequence    |
| FileHeavy       | server-file-heavy.jmx | CPU, Memory, File creation + anomaly CPU spikes  |
| Stress          | server-stress.jmx     | Suspicious activities that trigger EDR/AV agents |

Each cell runs twice:
- **Base phase** (snapshot 1): Server without the security agent
- **Initial phase** (snapshot 2): Server with the security agent installed

Both phases use the **same JMeter test plan** with the **same parameters** and the **same thread count**.

---

## What We Measure

### Primary Data: System Stats (per-second samples)

Collected by the emulator's stats agent running on the server. One sample per second containing:

**Whole-machine metrics (7 metrics):**
- CPU percent
- Memory percent
- Memory used MB
- Disk read rate MB/s
- Disk write rate MB/s
- Network sent rate MB/s
- Network recv rate MB/s

**Per-process metrics (2 metrics per process):**
- CPU percent per process
- Memory RSS MB per process

These directly measure what the agent consumes. They are not influenced by test parameters.

### Secondary Data: JTL Response Times (collected but NOT used in comparison)

See [Why Response Times Are Excluded](#why-response-times-are-excluded-from-comparison) below.

---

## Comparison Algorithm

### Step 1: Collect per-second samples

For each cell (test type x load profile), collect all per-second stat samples from both phases after trimming warmup (first 30s) and cooldown (last 10s).

- Base: array of per-second values per metric (e.g., 142 CPU% values for a 3-minute test)
- Initial: array of per-second values per metric

### Step 2: Compute summary statistics

For each metric, compute from the raw per-second array:

| Statistic  | Description                          |
|------------|--------------------------------------|
| Avg        | Arithmetic mean                      |
| P50        | Median (50th percentile)             |
| P90        | 90th percentile                      |
| P95        | 95th percentile                      |
| P99        | 99th percentile                      |
| Std Dev    | Standard deviation                   |

### Step 3: Compute Cohen's d (effect size)

For each metric, compute Cohen's d between the base and initial per-second sample arrays:

```
Cohen's d = (mean_initial - mean_base) / pooled_std_dev

pooled_std_dev = sqrt((std_dev_base^2 + std_dev_initial^2) / 2)
```

Cohen's d tells you how large the shift is, **normalized by the natural variation** in the data. A 2% CPU increase means different things if the CPU is stable at 30% +/- 1% (large effect) vs fluctuating between 10-80% (negligible effect).

**Interpretation (Cohen, 1988 — industry standard):**

| |d|     | Effect     | Meaning for agent testing                          |
|----------|------------|-----------------------------------------------------|
| < 0.2    | Negligible | Agent has no measurable impact on this metric       |
| 0.2-0.5  | Small      | Agent has minor impact, likely acceptable            |
| 0.5-0.8  | Medium     | Agent has noticeable impact, review recommended      |
| >= 0.8   | Large      | Agent has significant impact, likely unacceptable    |

**Computational complexity:** O(n) — single pass for mean and std dev. Handles millions of samples instantly. No resampling, no iterations.

### Step 4: Determine verdict

The verdict is determined from the Cohen's d matrix:

- **Pass**: All cells are negligible (green)
- **Warning**: Any cell is small or medium (yellow/orange), none are large
- **Fail**: Any cell is large (red)

Custom thresholds can be configured per metric in the rule engine.

---

## Results Page Layout

### Table 1: Cohen's d Matrix (overview)

Rows = metrics (machine-level + per-process).
Columns = test type x load profile combinations.
Each cell = Cohen's d value, color-coded by effect size.

```
              | Normal LP1 | Normal LP2 | Normal LP3 | FileHeavy LP1 | ... | Stress LP3 |
--------------+------------+------------+------------+---------------+-----+------------+
CPU %         |    0.12    |    0.15    |    0.31    |     0.10      | ... |    0.28    |
Memory %      |    0.85    |    0.82    |    0.88    |     0.80      | ... |    0.86    |
Disk Read     |    0.03    |    0.05    |    0.04    |     0.02      | ... |    0.05    |
Disk Write    |    0.04    |    0.06    |    0.05    |     0.03      | ... |    0.06    |
Net Sent      |    0.01    |    0.02    |    0.01    |     0.01      | ... |    0.01    |
Net Recv      |    0.01    |    0.01    |    0.02    |     0.01      | ... |    0.01    |
agent.exe CPU |     --     |     --     |     --     |      --       | ... |     --     |
agent.exe Mem |     --     |     --     |     --     |      --       | ... |     --     |
```

**Legend:**
- Green  (|d| < 0.2): Negligible
- Yellow (0.2 <= |d| < 0.5): Small
- Orange (0.5 <= |d| < 0.8): Medium
- Red    (|d| >= 0.8): Large

### Table 2: Percentile Detail (on cell click)

Clicking a cell in Table 1 opens a detail panel showing the full statistical breakdown:

```
Metric: CPU %  |  Test: Normal  |  Load Profile: LP2

Phase    |  Avg   |  P50   |  P90   |  P95   |  P99   | StdDev
---------+--------+--------+--------+--------+--------+-------
Base     | 32.5%  | 31.0%  | 42.0%  | 45.0%  | 48.0%  |  4.2
Initial  | 37.1%  | 36.0%  | 47.0%  | 51.0%  | 54.0%  |  4.5
Delta    | +4.6%  | +5.0%  | +5.0%  | +6.0%  | +6.0%  |   --

Cohen's d: 1.06 (Large)
Samples:   Base=142, Initial=142
```

---

## Why Response Times Are Excluded from Comparison

### The emulator's design makes response times unreliable for comparison

The emulator endpoints (CPU Burn, Memory Alloc, Disk IO, etc.) accept a `duration_ms` parameter that controls how long the operation runs. The HTTP response time is dominated by this configured value:

- Call `/api/v1/operations/cpu` with `duration_ms=100` -> response time ~102ms
- Call `/api/v1/operations/cpu` with `duration_ms=5000` -> response time ~5003ms

The agent's actual impact on response time is typically 2-5ms — a tiny signal buried in a value you configured yourself.

### Variance is driven by test configuration, not agent impact

If different test runs or scenarios use different `duration_ms` values:
- 5 runs at `duration_ms=100` -> response times ~102ms
- 6 runs at `duration_ms=40000` -> response times ~40,002ms
- 60 runs at `duration_ms=10000` -> response times ~10,003ms

Grouping these under the same label produces meaningless statistics:
- Average: ~11,000ms (tells you nothing about agent impact)
- Standard deviation: enormous (driven by parameter variation)
- Cohen's d: garbage (variance is from configuration, not from the agent)
- Percentiles: meaningless across different configurations

### Response times don't add information beyond system stats

System stats directly measure what we care about:
- **CPU %**: How much CPU does the agent consume? Measured directly.
- **Memory MB**: How much memory does the agent use? Measured directly.
- **Disk IO**: How much disk activity does the agent add? Measured directly.

Response times are an indirect, noisy proxy for the same information. If the agent uses 5% CPU, the system stats say "+5% CPU." The response time says "+3ms on a 100ms request" — the same signal, measured worse.

### What we still use JTL for

- **Throughput** (requests/sec): Shown as an informational metric. A significant throughput drop indicates the agent is causing resource contention.
- **Error rate**: If the agent causes requests to fail, this is visible.
- **Debugging**: Raw JTL files are preserved for manual investigation if needed.

---

## Previous Approach (Replaced)

The previous comparison pipeline used three statistical tests on raw sample arrays:

1. **Mann-Whitney U test** — significance test, O(n log n). Scaled adequately.
2. **Cliff's delta** — effect size, O(n log n). Scaled adequately.
3. **Bootstrap CI** — confidence interval via 10,000 resampling iterations, O(B x n log n). **Did not scale.**

Bootstrap CI on a 6-hour test (21,600 system stat samples): ~5.6 minutes.
Bootstrap CI on 6-hour JTL response times (1.5M values): never completes.

Additionally, the pipeline ran statistical tests on raw JTL response time arrays (every individual HTTP request's elapsed time), which is both statistically questionable (see above) and computationally infeasible for long tests.

### Why Cohen's d replaces all three

| Old test        | What it answers                              | Cohen's d equivalent              |
|-----------------|----------------------------------------------|-----------------------------------|
| Cliff's delta   | How large is the effect? (ordinal)           | Cohen's d answers the same question (interval scale, more precise) |
| Mann-Whitney U  | Is the effect statistically significant?     | With n > 100 samples, any real effect is significant. Cohen's d tells you if the effect **matters**. |
| Bootstrap CI    | What's the confidence interval on the mean?  | With large samples, CI is trivially narrow. Cohen's d already normalizes by variance. |

Cohen's d is O(n) — one pass for mean and standard deviation. Instant at any data size.

---

## Scalability

| Data size              | Cohen's d time | Old Bootstrap CI time |
|------------------------|----------------|-----------------------|
| 142 samples (15 min)   | < 1ms          | 0.66 seconds          |
| 3,600 samples (1 hr)   | < 1ms          | 42 seconds            |
| 21,600 samples (6 hr)  | < 1ms          | 5.6 minutes           |
| 86,400 samples (24 hr) | < 1ms          | ~22 minutes (est.)    |

The comparison phase now completes instantly regardless of test duration.
