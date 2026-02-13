"""Normalized ratio computation for cross-run comparability.

Computes ratio = agent_metric / emulator_baseline (same run, same statistic).
This normalizes agent impact against the actual workload level, enabling
comparison across runs that had different absolute load levels.

Selective normalization:
  - Ratio metrics (load-proportional): agent_cpu_percent, agent_io_read_rate_mbps,
    agent_io_write_rate_mbps  divided by their system counterpart from base phase.
  - Absolute metrics (fixed costs): agent_memory_rss_mb, agent_memory_vms_mb,
    agent_thread_count, agent_handle_count, process_count  stored as-is.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from orchestrator.services.stats_parser import AgentStatsSummary, MetricSummary, StatsSummary

logger = logging.getLogger(__name__)

STATS_FIELDS = ["avg", "min", "max", "p50", "p90", "p95", "p99"]

# Maps agent metric -> base system metric for ratio computation.
# Metrics not listed here are treated as absolute (no denominator).
RATIO_DENOMINATOR_MAP = {
    "agent_cpu_percent": "cpu_percent",
    "agent_io_read_rate_mbps": "disk_read_rate_mbps",
    "agent_io_write_rate_mbps": "disk_write_rate_mbps",
}

# All agent metrics to include in the output
AGENT_METRICS = [
    "agent_cpu_percent",
    "agent_memory_rss_mb",
    "agent_memory_vms_mb",
    "agent_thread_count",
    "agent_handle_count",
    "agent_io_read_rate_mbps",
    "agent_io_write_rate_mbps",
    "process_count",
]


@dataclass
class NormalizedMetricRatio:
    """Normalized ratio data for one agent metric."""
    agent_metric: str
    normalization_type: str  # "ratio" or "absolute"
    ratios: Dict[str, Optional[float]]  # stat -> ratio value
    base_values: Dict[str, float]       # denominator context (for ratio type)
    agent_values: Dict[str, float]      # numerator context


@dataclass
class NormalizedRatioSummary:
    """Collection of normalized ratios for all agent metrics."""
    metrics: Dict[str, NormalizedMetricRatio] = field(default_factory=dict)


def _get_stat_dict(ms: MetricSummary) -> Dict[str, float]:
    """Extract the 7 standard stats from a MetricSummary as a dict."""
    return {s: getattr(ms, s) for s in STATS_FIELDS}


def compute_normalized_ratios(
    base_sys: StatsSummary,
    agent_stats: AgentStatsSummary,
) -> NormalizedRatioSummary:
    """Compute normalized ratios for all agent metrics.

    Args:
        base_sys: System stats from the base phase (emulator-only baseline).
        agent_stats: Agent process stats from the initial phase.

    Returns:
        NormalizedRatioSummary with per-metric ratio data.
    """
    summary = NormalizedRatioSummary()

    for metric in AGENT_METRICS:
        agent_ms: MetricSummary = getattr(agent_stats, metric)
        agent_vals = _get_stat_dict(agent_ms)

        denominator_metric = RATIO_DENOMINATOR_MAP.get(metric)

        if denominator_metric:
            # Ratio type: divide agent stat by corresponding base system stat
            base_ms: MetricSummary = getattr(base_sys, denominator_metric)
            base_vals = _get_stat_dict(base_ms)

            ratios = {}
            for stat in STATS_FIELDS:
                base_val = base_vals[stat]
                agent_val = agent_vals[stat]
                if base_val != 0:
                    ratios[stat] = round(agent_val / base_val, 6)
                else:
                    ratios[stat] = None

            summary.metrics[metric] = NormalizedMetricRatio(
                agent_metric=metric,
                normalization_type="ratio",
                ratios=ratios,
                base_values=base_vals,
                agent_values=agent_vals,
            )
        else:
            # Absolute type: store raw values as the "ratio" (identity)
            summary.metrics[metric] = NormalizedMetricRatio(
                agent_metric=metric,
                normalization_type="absolute",
                ratios=agent_vals,
                base_values={},
                agent_values=agent_vals,
            )

    return summary


def serialize_ratios(summary: NormalizedRatioSummary) -> Dict[str, Any]:
    """Serialize NormalizedRatioSummary to a JSON-safe dict for JSONB storage."""
    result = {}
    for metric_name, nrm in summary.metrics.items():
        result[metric_name] = {
            "normalization_type": nrm.normalization_type,
            "ratios": nrm.ratios,
            "base_values": nrm.base_values,
            "agent_values": nrm.agent_values,
        }
    return result
