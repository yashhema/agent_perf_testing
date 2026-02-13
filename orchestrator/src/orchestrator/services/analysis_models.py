"""Analysis pipeline data classes.

All dataclasses for the analysis pipeline, organized in 5 layers:
  Layer 1: Raw Input (RawAgentStats)
  Layer 2: Parsed Summaries (SystemStatsSummary, AgentStatsSummary, CycleConsistency, PhaseData)
  Layer 3: Comparison / Delta (MetricDeltaStats, MetricDelta, SystemDeltaSummary, JtlDelta, FullComparisonData)
  Layer 4: Rule Evaluation (RuleEvaluation)
  Layer 5: Verdict (ComparisonVerdict, TestRunVerdict)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestrator.models.enums import Verdict
from orchestrator.services.stats_parser import (
    AgentStatsSummary,
    CycleConsistency,
    MetricSummary,
    StatsSummary as SystemStatsSummary,
)
from orchestrator.services.jtl_parser import JtlResult

# Re-export for consumers that import from analysis_models
__all__ = [
    "RawAgentStats", "SystemStatsSummary", "AgentStatsSummary", "CycleConsistency",
    "PhaseData", "MetricDeltaStats", "MetricDelta", "SystemDeltaSummary",
    "JtlDelta", "FullComparisonData", "RuleEvaluation", "ComparisonVerdict",
    "TestRunVerdict",
]


# ---------------------------------------------------------------------------
# Layer 1: Raw Input
# ---------------------------------------------------------------------------

@dataclass
class RawAgentStats:
    """Aggregated agent process stats from one sample."""
    process_count: int
    agent_cpu_percent: float
    agent_memory_rss_mb: float
    agent_memory_vms_mb: float
    agent_thread_count: int
    agent_handle_count: Optional[int]
    agent_io_read_bytes: int
    agent_io_write_bytes: int


# ---------------------------------------------------------------------------
# Layer 2: Parsed Summaries
# SystemStatsSummary, AgentStatsSummary, CycleConsistency are imported
# from stats_parser to avoid duplication.
# ---------------------------------------------------------------------------

@dataclass
class PhaseData:
    """All parsed data for one phase, with cross-cycle validation."""
    snapshot_num: int
    target_id: int
    load_profile_id: int
    total_cycles: int
    included_cycles: int
    excluded_cycles: List[int]
    system_stats: Optional[SystemStatsSummary]
    agent_stats: Optional[AgentStatsSummary]
    jtl_result: Optional[JtlResult]
    cycle_consistency: Dict[str, CycleConsistency] = field(default_factory=dict)
    has_anomalies: bool = False
    consistency_warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 3: Comparison / Delta
# ---------------------------------------------------------------------------

@dataclass
class MetricDeltaStats:
    """Delta values for all 7 statistics of a metric."""
    avg: float = 0.0
    min: float = 0.0
    max: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


@dataclass
class MetricDelta:
    """Full comparison for a single metric across base and initial."""
    base: MetricSummary
    initial: MetricSummary
    delta_abs: MetricDeltaStats
    delta_pct: MetricDeltaStats


@dataclass
class SystemDeltaSummary:
    """Delta comparison for all 7 system metrics."""
    cpu_percent: MetricDelta
    memory_percent: MetricDelta
    memory_used_mb: MetricDelta
    disk_read_rate_mbps: MetricDelta
    disk_write_rate_mbps: MetricDelta
    network_sent_rate_mbps: MetricDelta
    network_recv_rate_mbps: MetricDelta


@dataclass
class JtlDelta:
    """Delta comparison for JTL application performance metrics."""
    base: Optional[JtlResult]
    initial: Optional[JtlResult]
    avg_response_delta_abs: float = 0.0
    avg_response_delta_pct: float = 0.0
    p50_response_delta_abs: float = 0.0
    p50_response_delta_pct: float = 0.0
    p90_response_delta_abs: float = 0.0
    p90_response_delta_pct: float = 0.0
    p95_response_delta_abs: float = 0.0
    p95_response_delta_pct: float = 0.0
    p99_response_delta_abs: float = 0.0
    p99_response_delta_pct: float = 0.0
    throughput_delta_abs: float = 0.0
    throughput_delta_pct: float = 0.0
    error_rate_delta_abs: float = 0.0
    error_rate_delta_pct: float = 0.0


@dataclass
class FullComparisonData:
    """Complete comparison data for one target x one load profile."""
    system_deltas: Optional[SystemDeltaSummary]
    agent_overhead: Optional[AgentStatsSummary]
    jtl_delta: Optional[JtlDelta]
    rule_evaluations: List["RuleEvaluation"] = field(default_factory=list)
    verdict: Optional[Verdict] = None
    verdict_summary: str = ""
    normalized_ratios: Optional[Any] = None


# ---------------------------------------------------------------------------
# Layer 4: Rule Evaluation
# ---------------------------------------------------------------------------

@dataclass
class RuleEvaluation:
    """Result of evaluating a single rule against measured data."""
    rule_id: Optional[int]
    template_key: str
    rule_name: str
    category: str
    severity: str
    threshold: float
    actual_value: float
    unit: str
    passed: bool
    description: str


# ---------------------------------------------------------------------------
# Layer 5: Verdict
# ---------------------------------------------------------------------------

@dataclass
class ComparisonVerdict:
    """Verdict for one comparison (target x load profile)."""
    verdict: Verdict
    total_rules: int
    passed_count: int
    failed_count: int
    worst_failure: Optional[str]
    evaluations: List[RuleEvaluation] = field(default_factory=list)


@dataclass
class TestRunVerdict:
    """Overall verdict for an entire test run."""
    overall_verdict: Verdict
    per_load_profile: Dict[int, ComparisonVerdict] = field(default_factory=dict)
    total_rules: int = 0
    total_passed: int = 0
    total_failed: int = 0
    summary: str = ""
