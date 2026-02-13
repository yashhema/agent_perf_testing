"""Stats parser for emulator stats JSON files.

Matches ORCHESTRATOR_INTERFACES.md Section 3 exactly.
Input: AllStatsResponse JSON (from emulator GET /api/v1/stats/all or saved file)
Output: Trimmed, summarized metrics for comparison engine.

Enhanced with:
  - Robust statistics (trimmed_mean, stddev, iqr, count) in MetricSummary
  - memory_used_mb metric (7 metrics instead of 6)
  - Agent stats parsing (compute_agent_summary)
  - Cross-cycle validation (compute_per_cycle_stats)
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MetricSummary:
    """Statistical summary for a single metric."""
    avg: float
    min: float
    max: float
    p50: float
    p90: float
    p95: float
    p99: float
    # Robust statistics
    trimmed_mean: float = 0.0
    stddev: float = 0.0
    iqr: float = 0.0
    count: int = 0


@dataclass
class StatsSummary:
    """Summary across all 7 metric categories.

    Backward-compatible alias: StatsSummary includes memory_used_mb
    alongside the original 6 metrics.
    """
    cpu_percent: MetricSummary
    memory_percent: MetricSummary
    memory_used_mb: MetricSummary
    disk_read_rate_mbps: MetricSummary
    disk_write_rate_mbps: MetricSummary
    network_sent_rate_mbps: MetricSummary
    network_recv_rate_mbps: MetricSummary


# Backward-compatible alias
SystemStatsSummary = StatsSummary


@dataclass
class AgentStatsSummary:
    """Summary across all agent process metric categories."""
    agent_cpu_percent: MetricSummary
    agent_memory_rss_mb: MetricSummary
    agent_memory_vms_mb: MetricSummary
    agent_thread_count: MetricSummary
    agent_handle_count: MetricSummary
    agent_io_read_rate_mbps: MetricSummary
    agent_io_write_rate_mbps: MetricSummary
    process_count: MetricSummary


@dataclass
class CycleConsistency:
    """Cross-cycle consistency check results for one metric."""
    metric_name: str
    cycle_count: int
    per_cycle_avg: List[float]
    per_cycle_p99: List[float]
    inter_cycle_mean: float
    inter_cycle_stddev: float
    inter_cycle_cv: float
    anomalous_cycles: List[int]
    excluded_cycles: List[int]
    is_consistent: bool
    note: Optional[str] = None


class StatsParser:
    """Parses emulator stats JSON files for comparison engine."""

    def parse_stats_file(self, file_path: str) -> Dict[str, Any]:
        """Load stats from JSON file saved by emulator.

        Returns: dict matching AllStatsResponse structure
                 (metadata, samples, summary)
        """
        with open(file_path, "r") as f:
            return json.load(f)

    def trim_samples(
        self,
        samples: List[Dict[str, Any]],
        trim_start_sec: float,
        trim_end_sec: float,
    ) -> List[Dict[str, Any]]:
        """Remove warmup/cooldown samples.

        Trims samples where elapsed_sec < trim_start_sec
        or elapsed_sec > (max_elapsed - trim_end_sec).
        """
        if not samples:
            return []

        max_elapsed = max(s["elapsed_sec"] for s in samples)
        end_cutoff = max_elapsed - trim_end_sec

        return [
            s for s in samples
            if s["elapsed_sec"] >= trim_start_sec and s["elapsed_sec"] <= end_cutoff
        ]

    def compute_summary(self, samples: List[Dict[str, Any]]) -> StatsSummary:
        """Compute statistical summary from trimmed samples.

        7 metrics x 11 stats each (avg, min, max, p50, p90, p95, p99,
        trimmed_mean, stddev, iqr, count).
        """
        if not samples:
            empty = MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0)
            return StatsSummary(
                cpu_percent=empty, memory_percent=empty,
                memory_used_mb=empty,
                disk_read_rate_mbps=empty, disk_write_rate_mbps=empty,
                network_sent_rate_mbps=empty, network_recv_rate_mbps=empty,
            )

        metrics = [
            "cpu_percent", "memory_percent", "memory_used_mb",
            "disk_read_rate_mbps", "disk_write_rate_mbps",
            "network_sent_rate_mbps", "network_recv_rate_mbps",
        ]

        summaries = {}
        for metric in metrics:
            values = [s.get(metric, 0.0) for s in samples]
            summaries[metric] = self._summarize(values)

        return StatsSummary(**summaries)

    def compute_agent_summary(
        self, samples: List[Dict[str, Any]]
    ) -> Optional[AgentStatsSummary]:
        """Compute agent process stats summary from samples.

        Filters samples that have agent_stats, computes I/O rates
        from consecutive byte deltas.
        Returns AgentStatsSummary or None if no agent data found.
        """
        agent_samples = [s for s in samples if s.get("agent_stats")]
        if not agent_samples:
            return None

        # Direct metrics
        cpu_vals = [s["agent_stats"]["agent_cpu_percent"] for s in agent_samples]
        rss_vals = [s["agent_stats"]["agent_memory_rss_mb"] for s in agent_samples]
        vms_vals = [s["agent_stats"]["agent_memory_vms_mb"] for s in agent_samples]
        thread_vals = [float(s["agent_stats"]["agent_thread_count"]) for s in agent_samples]
        handle_vals = [float(s["agent_stats"].get("agent_handle_count", 0) or 0) for s in agent_samples]
        proc_vals = [float(s["agent_stats"]["process_count"]) for s in agent_samples]

        # Compute I/O rates from consecutive byte deltas
        io_read_rates = []
        io_write_rates = []
        for i in range(1, len(agent_samples)):
            prev = agent_samples[i - 1]
            curr = agent_samples[i]
            dt = curr.get("elapsed_sec", 0) - prev.get("elapsed_sec", 0)
            if dt <= 0:
                continue
            read_delta = (
                curr["agent_stats"]["agent_io_read_bytes"]
                - prev["agent_stats"]["agent_io_read_bytes"]
            )
            write_delta = (
                curr["agent_stats"]["agent_io_write_bytes"]
                - prev["agent_stats"]["agent_io_write_bytes"]
            )
            # Convert bytes/sec to MB/sec
            io_read_rates.append(max(0, read_delta / dt / (1024 * 1024)))
            io_write_rates.append(max(0, write_delta / dt / (1024 * 1024)))

        if not io_read_rates:
            io_read_rates = [0.0]
        if not io_write_rates:
            io_write_rates = [0.0]

        return AgentStatsSummary(
            agent_cpu_percent=self._summarize(cpu_vals),
            agent_memory_rss_mb=self._summarize(rss_vals),
            agent_memory_vms_mb=self._summarize(vms_vals),
            agent_thread_count=self._summarize(thread_vals),
            agent_handle_count=self._summarize(handle_vals),
            agent_io_read_rate_mbps=self._summarize(io_read_rates),
            agent_io_write_rate_mbps=self._summarize(io_write_rates),
            process_count=self._summarize(proc_vals),
        )

    def compute_per_cycle_stats(
        self,
        cycle_samples: List[List[Dict[str, Any]]],
        metric_name: str,
    ) -> CycleConsistency:
        """Compute per-cycle statistics and detect anomalous cycles.

        Uses 2-sigma threshold on inter-cycle avg and p99 to flag anomalies.
        """
        cycle_count = len(cycle_samples)
        if cycle_count <= 1:
            return CycleConsistency(
                metric_name=metric_name,
                cycle_count=cycle_count,
                per_cycle_avg=[],
                per_cycle_p99=[],
                inter_cycle_mean=0.0,
                inter_cycle_stddev=0.0,
                inter_cycle_cv=0.0,
                anomalous_cycles=[],
                excluded_cycles=[],
                is_consistent=True,
                note="Single cycle - no cross-cycle validation performed"
                     if cycle_count == 1 else "No cycles",
            )

        per_cycle_avg = []
        per_cycle_p99 = []
        for samples in cycle_samples:
            values = [s.get(metric_name, 0.0) for s in samples]
            summary = self._summarize(values)
            per_cycle_avg.append(summary.avg)
            per_cycle_p99.append(summary.p99)

        # Inter-cycle statistics on avg
        ic_mean = sum(per_cycle_avg) / cycle_count
        ic_variance = sum((v - ic_mean) ** 2 for v in per_cycle_avg) / cycle_count
        ic_stddev = math.sqrt(ic_variance)
        ic_cv = (ic_stddev / ic_mean * 100) if ic_mean != 0 else 0.0

        # Detect anomalous cycles: avg or p99 deviates > 2 sigma
        anomalous = []
        p99_mean = sum(per_cycle_p99) / cycle_count
        p99_variance = sum((v - p99_mean) ** 2 for v in per_cycle_p99) / cycle_count
        p99_stddev = math.sqrt(p99_variance)

        for i in range(cycle_count):
            avg_anomaly = ic_stddev > 0 and abs(per_cycle_avg[i] - ic_mean) > 2 * ic_stddev
            p99_anomaly = p99_stddev > 0 and abs(per_cycle_p99[i] - p99_mean) > 2 * p99_stddev
            if avg_anomaly or p99_anomaly:
                anomalous.append(i)

        # Decide exclusions: only exclude if fewer than all cycles are anomalous
        excluded = anomalous if len(anomalous) < cycle_count else []
        is_consistent = len(excluded) == 0

        note = None
        if excluded:
            note = (
                f"Cycles {excluded} excluded: anomalous values detected "
                f"(inter-cycle mean={ic_mean:.2f}, stddev={ic_stddev:.2f})"
            )
        elif anomalous and not excluded:
            note = (
                f"High inter-cycle variance across ALL cycles - "
                f"results may be unreliable (CV={ic_cv:.1f}%)"
            )

        return CycleConsistency(
            metric_name=metric_name,
            cycle_count=cycle_count,
            per_cycle_avg=[round(v, 4) for v in per_cycle_avg],
            per_cycle_p99=[round(v, 4) for v in per_cycle_p99],
            inter_cycle_mean=round(ic_mean, 4),
            inter_cycle_stddev=round(ic_stddev, 4),
            inter_cycle_cv=round(ic_cv, 2),
            anomalous_cycles=anomalous,
            excluded_cycles=excluded,
            is_consistent=is_consistent,
            note=note,
        )

    def _summarize(self, values: List[float]) -> MetricSummary:
        """Compute summary statistics for a list of values.

        Includes robust statistics: trimmed_mean, stddev, iqr, count.
        """
        if not values:
            return MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0)

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        avg = sum(sorted_vals) / n

        # Standard deviation
        variance = sum((v - avg) ** 2 for v in sorted_vals) / n
        stddev = math.sqrt(variance)

        # Trimmed mean (5% trim)
        trim_count = max(1, int(n * 0.05))
        if n > 2 * trim_count:
            trimmed = sorted_vals[trim_count:-trim_count]
            trimmed_mean = sum(trimmed) / len(trimmed)
        else:
            trimmed_mean = avg

        # IQR
        p25 = self._percentile(sorted_vals, 25)
        p75 = self._percentile(sorted_vals, 75)
        iqr = p75 - p25

        return MetricSummary(
            avg=round(avg, 4),
            min=round(sorted_vals[0], 4),
            max=round(sorted_vals[-1], 4),
            p50=round(self._percentile(sorted_vals, 50), 4),
            p90=round(self._percentile(sorted_vals, 90), 4),
            p95=round(self._percentile(sorted_vals, 95), 4),
            p99=round(self._percentile(sorted_vals, 99), 4),
            trimmed_mean=round(trimmed_mean, 4),
            stddev=round(stddev, 4),
            iqr=round(iqr, 4),
            count=n,
        )

    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        """Compute percentile using linear interpolation."""
        n = len(sorted_values)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_values[0]

        k = (percentile / 100.0) * (n - 1)
        f = math.floor(k)
        c = math.ceil(k)

        if f == c:
            return sorted_values[int(k)]

        lower = sorted_values[f]
        upper = sorted_values[c]
        return lower + (upper - lower) * (k - f)
