# Group, Subgroup & Snapshot Hierarchy — How It Works

## The Problem This Solves

When testing security agents on servers, we need to answer: **"How much overhead does this agent add?"**

To answer that, we need:
1. A **clean reference point** (no agent installed) with known performance data
2. A way to **install the agent**, test again, and compare
3. A way to **track multiple agent versions** over time and compare any two

VM snapshots give us reproducible states. But raw snapshots are just flat files on a hypervisor — they don't carry meaning. The **Group → Subgroup → Snapshot** hierarchy adds that meaning.

---

## The Three Levels

```
Level 1: GROUP  (snapshot_baselines table)
│        "What clean OS am I comparing against?"
│
└── Level 2: SUBGROUP  (snapshot_groups table)
    │        "Which agent/team owns these snapshots?"
    │
    └── Level 3: SNAPSHOTS  (snapshots table)
                 "What exact VM state is this?"
```

### Level 1 — Group (aka Baseline Group)

**Table:** `snapshot_baselines`
**UI Label:** "Group"

A Group represents a **clean OS installation** on a specific server — the reference point that all agent tests compare against.

| Field | Meaning |
|-------|---------|
| `server_id` | Which physical/virtual server this group belongs to |
| `snapshot_id` | The root snapshot representing this clean state |
| `name` | Human-readable label, e.g. "Rocky Baseline", "Windows Baseline" |

**Key rule:** One Group = one clean starting point per server. A server can have multiple Groups (e.g. "Clean Rocky 9.5" and "Clean Rocky 9.7"), but each Group points to exactly one root snapshot.

**Current DB state:**
```
Group 1: MyFirstGrp         → server 8, snapshot 1 (MyFirstBaseSnapshot)
Group 2: Rocky Baseline      → server 8, snapshot 3 (clean-rocky-baseline)
Group 3: Windows Baseline    → server 9, snapshot 4 (clean-win-baseline)
```

### Level 2 — Subgroup (aka Agent Group)

**Table:** `snapshot_groups`
**UI Label:** "Subgroup"

A Subgroup lives under a Group and represents **a team, an agent, or a category of snapshots**. It organizes the snapshots that branch off from the clean baseline.

| Field | Meaning |
|-------|---------|
| `baseline_id` | Which Group this Subgroup belongs to |
| `snapshot_id` | Optional — a representative snapshot for this subgroup |
| `name` | Human-readable label, e.g. "AgentX Team", "CrowdStrike", "Testing" |

**Why Subgroups?** In real-world use, multiple teams may test different agents against the same clean baseline. Subgroups prevent their snapshots from being mixed together.

**Example:**
```
Group: "Clean Rocky 9.7" (server 8)
├── Subgroup: "CrowdStrike Team"
│   ├── Snapshot: cs-agent-v7.14
│   ├── Snapshot: cs-agent-v7.15
│   └── Snapshot: cs-agent-v7.16
├── Subgroup: "SentinelOne Team"
│   ├── Snapshot: s1-agent-v23.1
│   └── Snapshot: s1-agent-v23.2
└── Subgroup: "Default"
    └── Snapshot: clean-rocky-baseline (the root itself)
```

**Current DB state** (auto-created default subgroups):
```
Subgroup 1: MyFirstGrp_default       → baseline_id=1, snapshot 1
Subgroup 2: Rocky Baseline_default   → baseline_id=2, snapshot 3
Subgroup 3: Windows Baseline_default → baseline_id=3, snapshot 4
```

### Level 3 — Snapshot

**Table:** `snapshots`
**UI Label:** "Snapshot"

A Snapshot represents **one exact VM state** on a hypervisor. It can be restored, tested, and compared.

| Field | Meaning |
|-------|---------|
| `server_id` | Which server this snapshot belongs to |
| `parent_id` | The parent snapshot (tree hierarchy — mirrors hypervisor) |
| `group_id` | Which Subgroup this snapshot is organized under |
| `is_baseline` | True if this snapshot has been tested via `new_baseline` and stores reference data |
| `provider_snapshot_id` | The hypervisor's own ID for this snapshot |
| `provider_ref` | JSON with hypervisor-specific metadata |

**Key fields for tracking:**

- `parent_id` → **tree structure**. Snapshot "agent-v1-rocky" has parent "clean-rocky-baseline", which has parent "MyFirstBaseSnapshot". This mirrors the hypervisor's snapshot chain.
- `is_baseline` → **tested and stored**. When a `new_baseline` test completes successfully, this flag is set to True and the snapshot has performance data stored against it.
- `group_id` → **organizational**. Links to a Subgroup for UI grouping.

---

## How Data Gets Attached to Snapshots

### SnapshotProfileData — The Performance Record

**Table:** `snapshot_profile_data`

When a test run completes, results are stored *on the snapshot itself* — not on the test run. This is the key insight: **snapshots carry their own performance data**.

| Field | Meaning |
|-------|---------|
| `snapshot_id` | Which snapshot this data belongs to |
| `load_profile_id` | Which load profile (low/medium/high) |
| `thread_count` | Calibrated thread count from binary search |
| `stats_data` | Path to the collected system stats (CPU, memory, disk, network) |
| `jtl_data` | Path to JMeter results file |
| `jmx_test_case_data` | Path to the generated operation sequence CSV |
| `stats_summary` | JSON with computed averages, percentiles |
| `source_snapshot_id` | If this data was copied from another snapshot (data lineage) |

**Unique constraint:** `(snapshot_id, load_profile_id)` — one data record per snapshot per load level.

**Why store on the snapshot, not the test run?**

Because future tests need to *look up* baseline data by snapshot. When you run a `compare` test:
- You specify: `test_snapshot_id=A` (agent installed) and `compare_snapshot_id=3` (clean baseline)
- The system looks up `snapshot_profile_data WHERE snapshot_id=3` to get the reference data
- It runs the test on snapshot A, collects new data
- It compares new data vs stored data using Cohen's d

If data lived on the test run, you'd need to trace back through test runs to find which run tested which snapshot — fragile and slow.

---

## How Tracking Works — The Full Picture

### Scenario: Testing 3 versions of an agent

**Starting state:**
```
Server 8 (Rocky Linux):
  Snapshot 3: clean-rocky-baseline [is_baseline=True]
    └── profile_data: thread_count=45, stats, jtl (from new_baseline Run 1)
```

**After installing Agent v1 and running a compare test:**
```
Server 8:
  Snapshot 3: clean-rocky-baseline [is_baseline=True]
    ├── profile_data: {lp=1, threads=45, stats, jtl}  ← reference data
    └── Snapshot A: agent-v1-rocky [parent=3]
        └── profile_data: {lp=1, threads=45, stats, jtl}  ← test data
            comparison_result: Cohen's d = 0.35 (small effect)
```

**After installing Agent v2 (branching from v1):**
```
Server 8:
  Snapshot 3: clean-rocky-baseline [is_baseline=True]
    ├── profile_data: {lp=1, threads=45, stats, jtl}
    └── Snapshot A: agent-v1-rocky [parent=3]
        ├── profile_data: {lp=1, threads=45, stats, jtl}
        └── Snapshot C: agent-v2-rocky [parent=A]
            └── profile_data: {lp=1, threads=45, stats, jtl}
                comparison_result vs snapshot 3: Cohen's d = 0.52 (medium effect)
```

**After installing Agent v3 (branching from v2), comparing against v2:**
```
Server 8:
  Snapshot 3: clean-rocky-baseline [is_baseline=True]
    └── Snapshot A: agent-v1-rocky [parent=3]
        └── Snapshot C: agent-v2-rocky [parent=A]
            ├── profile_data: {lp=1, threads=45, stats, jtl}
            └── Snapshot E: agent-v3-rocky [parent=C]
                └── profile_data: {lp=1, threads=45, stats, jtl}
                    comparison_result vs snapshot C: Cohen's d = 0.12 (negligible)
```

### What you can now track:

| Question | How to answer |
|----------|---------------|
| How much overhead does Agent v1 add vs clean? | Look at comparison_result for snapshot A vs snapshot 3 |
| Is Agent v2 worse than v1? | Compare snapshot C's data vs snapshot A's data |
| Did v3 fix the regression from v2? | Compare snapshot E vs snapshot C (Cohen's d = 0.12 → negligible) |
| What was the clean baseline thread count? | `snapshot_profile_data WHERE snapshot_id=3` → thread_count |
| Which snapshots have been tested? | `SELECT * FROM snapshots WHERE is_baseline=True` or `WHERE id IN (SELECT snapshot_id FROM snapshot_profile_data)` |
| What's the full version history? | Walk the snapshot tree via `parent_id`: E → C → A → 3 |

---

## The source_snapshot_id Field — Data Lineage

When a `compare` test runs, it **reuses** the compare snapshot's calibration data (thread count + ops sequence). The system copies this reference into the test snapshot's `snapshot_profile_data` with `source_snapshot_id` set to the compare snapshot.

This answers: **"Where did this snapshot's test parameters come from?"**

- `source_snapshot_id = NULL` → This snapshot was calibrated independently (via `new_baseline` or `compare_with_new_calibration`)
- `source_snapshot_id = 3` → This snapshot reused calibration from snapshot 3

---

## Multi-Server Testing

The hierarchy works per-server. In a multi-target test run, each target has its own snapshot tree:

```
Test Run 5 (new_baseline, 2 targets):
├── Target: server 8 → test_snapshot=3 (clean-rocky-baseline)
│   └── Results stored on snapshot 3's profile_data
└── Target: server 9 → test_snapshot=4 (clean-win-baseline)
    └── Results stored on snapshot 4's profile_data

Test Run 6 (compare, 2 targets):
├── Target: server 8 → test_snapshot=A, compare_snapshot=3
│   └── New data on A, compared against snapshot 3's stored data
└── Target: server 9 → test_snapshot=B, compare_snapshot=4
    └── New data on B, compared against snapshot 4's stored data
```

Each server maintains its own independent snapshot tree. The test run ties them together as "tested at the same time" but the data lives on each server's snapshots independently.

---

## Summary — Mental Model

Think of it as a filing cabinet:

```
FILING CABINET (Server 8 - Rocky Linux)
│
├── DRAWER: "Clean Rocky 9.7"                    ← GROUP (baseline group)
│   │
│   ├── FOLDER: "CrowdStrike Testing"            ← SUBGROUP (agent/team)
│   │   ├── FILE: cs-v7.14 snapshot              ← SNAPSHOT (with profile_data)
│   │   ├── FILE: cs-v7.15 snapshot              ← SNAPSHOT (with profile_data)
│   │   └── FILE: cs-v7.16 snapshot              ← SNAPSHOT (with profile_data)
│   │
│   └── FOLDER: "Default"                        ← SUBGROUP (auto-created)
│       └── FILE: clean-rocky-baseline snapshot   ← SNAPSHOT (the reference baseline)
│
└── DRAWER: "Clean Rocky 9.5"                    ← another GROUP (older OS)
    └── FOLDER: "Legacy Agent Testing"
        └── FILE: ...
```

- **Group** = which clean OS you're comparing against
- **Subgroup** = which team/agent/category owns the snapshots
- **Snapshot** = one exact VM state, with performance data attached after testing
- **SnapshotProfileData** = the actual numbers (thread count, stats, JTL) per load profile
- **parent_id** = version history chain (v3 → v2 → v1 → clean)
- **source_snapshot_id** = "I borrowed my test parameters from this snapshot"
