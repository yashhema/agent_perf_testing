"""Rule templates and presets for the analysis engine.

Defines 25 rule templates across 5 categories and 3 presets
(standard/strict/lenient) with configured thresholds.

Categories:
  - system_overhead (10): Fixed-threshold system-wide rules (informational)
  - agent_process (7): Absolute threshold rules for agent process metrics
  - app_performance (5): JTL-based application performance rules
  - stability (1): Cross-cycle variance check
  - statistical (7): System-wide Cliff's delta rules (informational, not in presets)
  - statistical_process (2): Per-process Cliff's delta rules (verdict-determining)

Verdict is driven by per-process statistical rules + agent process rules + JTL rules.
System-wide statistical and fixed-threshold system rules are retained for display.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RuleTemplate:
    """Definition of a rule type that can be instantiated with a threshold."""
    key: str
    name: str
    category: str  # "system_overhead", "agent_process", "app_performance", "stability"
    description: str
    data_source: str  # "system_stats", "agent_stats", "jtl"
    metric: str  # field name on the source object
    statistic: str  # "avg", "p95", "p99", "max", etc.
    comparison_mode: str  # "delta_abs", "delta_pct", "absolute"
    operator: str  # "lt" (actual must be less than threshold) or "gt"
    unit: str  # "pp" (percentage points), "%", "MB", "MB/s", etc.
    default_threshold: float


@dataclass
class PresetRule:
    """One rule within a preset."""
    template_key: str
    threshold: float
    severity: str  # "critical" | "warning"


@dataclass
class RulePreset:
    """A predefined set of rules with configured thresholds."""
    key: str
    name: str
    description: str
    rules: List[PresetRule] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 23 Rule Templates
# ---------------------------------------------------------------------------

RULE_TEMPLATES: Dict[str, RuleTemplate] = {
    # ---- System Overhead (10) ----
    "sys_cpu_delta_avg": RuleTemplate(
        key="sys_cpu_delta_avg",
        name="System CPU Overhead (avg)",
        category="system_overhead",
        description="Average CPU utilization increase (percentage points) between base and initial phases",
        data_source="system_stats",
        metric="cpu_percent",
        statistic="avg",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=5.0,
    ),
    "sys_cpu_delta_p95": RuleTemplate(
        key="sys_cpu_delta_p95",
        name="System CPU Overhead (p95)",
        category="system_overhead",
        description="95th percentile CPU utilization increase between base and initial phases",
        data_source="system_stats",
        metric="cpu_percent",
        statistic="p95",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=8.0,
    ),
    "sys_cpu_delta_p99": RuleTemplate(
        key="sys_cpu_delta_p99",
        name="System CPU Overhead (p99)",
        category="system_overhead",
        description="99th percentile CPU utilization increase between base and initial phases",
        data_source="system_stats",
        metric="cpu_percent",
        statistic="p99",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=15.0,
    ),
    "sys_mem_delta_avg": RuleTemplate(
        key="sys_mem_delta_avg",
        name="System Memory Overhead (avg %)",
        category="system_overhead",
        description="Average memory utilization increase (percentage points) between base and initial phases",
        data_source="system_stats",
        metric="memory_percent",
        statistic="avg",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=5.0,
    ),
    "sys_mem_delta_max": RuleTemplate(
        key="sys_mem_delta_max",
        name="System Memory Overhead (max %)",
        category="system_overhead",
        description="Maximum memory utilization increase between base and initial phases",
        data_source="system_stats",
        metric="memory_percent",
        statistic="max",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=10.0,
    ),
    "sys_mem_mb_delta_avg": RuleTemplate(
        key="sys_mem_mb_delta_avg",
        name="System Memory Overhead (avg MB)",
        category="system_overhead",
        description="Average memory usage increase in MB between base and initial phases",
        data_source="system_stats",
        metric="memory_used_mb",
        statistic="avg",
        comparison_mode="delta_abs",
        operator="lt",
        unit="MB",
        default_threshold=1024.0,
    ),
    "sys_disk_write_delta_pct": RuleTemplate(
        key="sys_disk_write_delta_pct",
        name="Disk Write Overhead (%)",
        category="system_overhead",
        description="Percentage increase in disk write throughput between base and initial phases",
        data_source="system_stats",
        metric="disk_write_rate_mbps",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=25.0,
    ),
    "sys_disk_read_delta_pct": RuleTemplate(
        key="sys_disk_read_delta_pct",
        name="Disk Read Overhead (%)",
        category="system_overhead",
        description="Percentage increase in disk read throughput between base and initial phases",
        data_source="system_stats",
        metric="disk_read_rate_mbps",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=25.0,
    ),
    "sys_net_send_delta_pct": RuleTemplate(
        key="sys_net_send_delta_pct",
        name="Network Send Overhead (%)",
        category="system_overhead",
        description="Percentage increase in network send throughput between base and initial phases",
        data_source="system_stats",
        metric="network_sent_rate_mbps",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=20.0,
    ),
    "sys_net_recv_delta_pct": RuleTemplate(
        key="sys_net_recv_delta_pct",
        name="Network Recv Overhead (%)",
        category="system_overhead",
        description="Percentage increase in network receive throughput between base and initial phases",
        data_source="system_stats",
        metric="network_recv_rate_mbps",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=20.0,
    ),

    # ---- Agent Process (7) ----
    "agent_cpu_avg": RuleTemplate(
        key="agent_cpu_avg",
        name="Agent CPU Usage (avg)",
        category="agent_process",
        description="Average CPU consumed by agent processes in the initial phase",
        data_source="agent_stats",
        metric="agent_cpu_percent",
        statistic="avg",
        comparison_mode="absolute",
        operator="lt",
        unit="%",
        default_threshold=10.0,
    ),
    "agent_cpu_p95": RuleTemplate(
        key="agent_cpu_p95",
        name="Agent CPU Usage (p95)",
        category="agent_process",
        description="95th percentile CPU consumed by agent processes in the initial phase",
        data_source="agent_stats",
        metric="agent_cpu_percent",
        statistic="p95",
        comparison_mode="absolute",
        operator="lt",
        unit="%",
        default_threshold=15.0,
    ),
    "agent_cpu_max": RuleTemplate(
        key="agent_cpu_max",
        name="Agent CPU Usage (max)",
        category="agent_process",
        description="Maximum CPU consumed by agent processes in the initial phase",
        data_source="agent_stats",
        metric="agent_cpu_percent",
        statistic="max",
        comparison_mode="absolute",
        operator="lt",
        unit="%",
        default_threshold=25.0,
    ),
    "agent_mem_rss_avg": RuleTemplate(
        key="agent_mem_rss_avg",
        name="Agent RSS Memory (avg)",
        category="agent_process",
        description="Average resident memory used by agent processes",
        data_source="agent_stats",
        metric="agent_memory_rss_mb",
        statistic="avg",
        comparison_mode="absolute",
        operator="lt",
        unit="MB",
        default_threshold=512.0,
    ),
    "agent_mem_rss_max": RuleTemplate(
        key="agent_mem_rss_max",
        name="Agent RSS Memory (max)",
        category="agent_process",
        description="Maximum resident memory used by agent processes",
        data_source="agent_stats",
        metric="agent_memory_rss_mb",
        statistic="max",
        comparison_mode="absolute",
        operator="lt",
        unit="MB",
        default_threshold=1024.0,
    ),
    "agent_mem_vms_max": RuleTemplate(
        key="agent_mem_vms_max",
        name="Agent VMS Memory (max)",
        category="agent_process",
        description="Maximum virtual memory reserved by agent processes",
        data_source="agent_stats",
        metric="agent_memory_vms_mb",
        statistic="max",
        comparison_mode="absolute",
        operator="lt",
        unit="MB",
        default_threshold=4096.0,
    ),
    "agent_io_write_avg": RuleTemplate(
        key="agent_io_write_avg",
        name="Agent I/O Write Rate (avg)",
        category="agent_process",
        description="Average I/O write rate of agent processes",
        data_source="agent_stats",
        metric="agent_io_write_rate_mbps",
        statistic="avg",
        comparison_mode="absolute",
        operator="lt",
        unit="MB/s",
        default_threshold=50.0,
    ),

    # ---- Application Performance (5) ----
    "jtl_resp_avg_delta_pct": RuleTemplate(
        key="jtl_resp_avg_delta_pct",
        name="Response Time Increase (avg)",
        category="app_performance",
        description="Percentage increase in average response time between base and initial phases",
        data_source="jtl",
        metric="avg_response_ms",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=10.0,
    ),
    "jtl_resp_p95_delta_pct": RuleTemplate(
        key="jtl_resp_p95_delta_pct",
        name="Response Time Increase (p95)",
        category="app_performance",
        description="Percentage increase in p95 response time between base and initial phases",
        data_source="jtl",
        metric="p95_response_ms",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=20.0,
    ),
    "jtl_resp_p99_delta_pct": RuleTemplate(
        key="jtl_resp_p99_delta_pct",
        name="Response Time Increase (p99)",
        category="app_performance",
        description="Percentage increase in p99 response time between base and initial phases",
        data_source="jtl",
        metric="p99_response_ms",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="lt",
        unit="%",
        default_threshold=25.0,
    ),
    "jtl_throughput_delta_pct": RuleTemplate(
        key="jtl_throughput_delta_pct",
        name="Throughput Decrease",
        category="app_performance",
        description="Percentage decrease in throughput (requests/sec). Negative threshold means "
                    "throughput must not drop by more than this percentage.",
        data_source="jtl",
        metric="throughput_per_sec",
        statistic="avg",
        comparison_mode="delta_pct",
        operator="gt",
        unit="%",
        default_threshold=-5.0,
    ),
    "jtl_error_rate_delta_abs": RuleTemplate(
        key="jtl_error_rate_delta_abs",
        name="Error Rate Increase",
        category="app_performance",
        description="Absolute increase in error rate (percentage points) between base and initial",
        data_source="jtl",
        metric="error_rate_percent",
        statistic="avg",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=0.5,
    ),

    # ---- Stability (1) ----
    "stability_cpu_cv": RuleTemplate(
        key="stability_cpu_cv",
        name="CPU Stability (Coefficient of Variation)",
        category="stability",
        description="Cross-cycle coefficient of variation for CPU. High values indicate "
                    "unstable, unreproducible measurements.",
        data_source="system_stats",
        metric="cpu_percent",
        statistic="cv",
        comparison_mode="absolute",
        operator="lt",
        unit="%",
        default_threshold=15.0,
    ),

    # ---- Statistical Tests: System-wide (7) ----
    # Kept for informational display. Not used in presets for verdict.
    "stat_cpu_impact": RuleTemplate(
        key="stat_cpu_impact",
        name="CPU Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for CPU. Informational only; "
                    "per-process rules drive the verdict.",
        data_source="statistical",
        metric="cpu_percent",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.20,
    ),
    "stat_memory_pct_impact": RuleTemplate(
        key="stat_memory_pct_impact",
        name="Memory % Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for memory %. Informational only.",
        data_source="statistical",
        metric="memory_percent",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.25,
    ),
    "stat_memory_mb_impact": RuleTemplate(
        key="stat_memory_mb_impact",
        name="Memory MB Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for memory MB. Informational only.",
        data_source="statistical",
        metric="memory_used_mb",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.25,
    ),
    "stat_disk_write_impact": RuleTemplate(
        key="stat_disk_write_impact",
        name="Disk Write Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for disk write rate. Informational only.",
        data_source="statistical",
        metric="disk_write_rate_mbps",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.30,
    ),
    "stat_disk_read_impact": RuleTemplate(
        key="stat_disk_read_impact",
        name="Disk Read Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for disk read rate. Informational only.",
        data_source="statistical",
        metric="disk_read_rate_mbps",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.30,
    ),
    "stat_net_send_impact": RuleTemplate(
        key="stat_net_send_impact",
        name="Network Send Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for network send rate. Informational only.",
        data_source="statistical",
        metric="network_sent_rate_mbps",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.30,
    ),
    "stat_net_recv_impact": RuleTemplate(
        key="stat_net_recv_impact",
        name="Network Recv Impact (statistical, system-wide)",
        category="statistical",
        description="System-wide Cliff's delta for network recv rate. Informational only.",
        data_source="statistical",
        metric="network_recv_rate_mbps",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.30,
    ),

    # ---- Statistical Tests: Per-Process (2) ----
    # These drive the verdict. Each rule evaluates ALL monitored processes
    # and takes the worst-case result. Requires service_monitor_patterns
    # to be configured on the emulator with patterns matching the emulator
    # process and any agent/service processes.
    "stat_process_cpu_impact": RuleTemplate(
        key="stat_process_cpu_impact",
        name="Per-Process CPU Impact (statistical)",
        category="statistical_process",
        description="Cliff's delta for per-process CPU utilization. Evaluates each "
                    "monitored process individually and fails if ANY process shows "
                    "both a significant (p < 0.05) and meaningful effect size. "
                    "Requires service_monitor_patterns to be configured.",
        data_source="statistical_process",
        metric="cpu_percent",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.20,
    ),
    "stat_process_mem_impact": RuleTemplate(
        key="stat_process_mem_impact",
        name="Per-Process Memory Impact (statistical)",
        category="statistical_process",
        description="Cliff's delta for per-process RSS memory. Evaluates each "
                    "monitored process individually and fails if ANY process shows "
                    "both a significant and meaningful effect size.",
        data_source="statistical_process",
        metric="memory_rss_mb",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.25,
    ),

    # ---- Statistical Tests: JTL Application Performance (3) ----
    # Two-gate (significance + effect size) on raw JTL data.
    # Throughput uses negative delta (agent reducing throughput is bad).
    # Response time uses positive delta (agent increasing latency is bad).
    "stat_jtl_throughput_impact": RuleTemplate(
        key="stat_jtl_throughput_impact",
        name="Throughput Impact (statistical)",
        category="statistical_jtl",
        description="Cliff's delta on per-second throughput timeseries. "
                    "A negative delta means initial has lower throughput than base "
                    "(agent reducing throughput). Uses two-gate: significant + "
                    "meaningful effect size.",
        data_source="jtl_statistical",
        metric="jtl:throughput_per_sec",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="gt",  # delta must be > threshold (threshold is negative)
        unit="",
        default_threshold=-0.20,
    ),
    "stat_jtl_response_time_impact": RuleTemplate(
        key="stat_jtl_response_time_impact",
        name="Response Time Impact (statistical)",
        category="statistical_jtl",
        description="Cliff's delta on raw response time distribution. "
                    "A positive delta means initial has higher response times "
                    "(agent adding latency). Uses two-gate: significant + "
                    "meaningful effect size.",
        data_source="jtl_statistical",
        metric="jtl:response_time_ms",
        statistic="cliff_delta",
        comparison_mode="two_gate",
        operator="lt",
        unit="",
        default_threshold=0.20,
    ),
    "stat_jtl_error_rate_impact": RuleTemplate(
        key="stat_jtl_error_rate_impact",
        name="Error Rate Impact (statistical)",
        category="statistical_jtl",
        description="Simple absolute delta on error rate percentage points. "
                    "Agent must not increase error rate beyond threshold.",
        data_source="jtl",
        metric="error_rate_percent",
        statistic="avg",
        comparison_mode="delta_abs",
        operator="lt",
        unit="pp",
        default_threshold=1.0,
    ),
}


# ---------------------------------------------------------------------------
# 3 Rule Presets
# ---------------------------------------------------------------------------

RULE_PRESETS: Dict[str, RulePreset] = {
    "standard": RulePreset(
        key="standard",
        name="Standard",
        description="Balanced thresholds suitable for most environments. "
                    "Per-process statistical rules (Cliff's delta + Mann-Whitney) drive the verdict; "
                    "system-wide and agent process rules are retained for informational display.",
        rules=[
            # --- Per-process statistical rules (verdict-determining) ---
            PresetRule("stat_process_cpu_impact", 0.20, "critical"),
            PresetRule("stat_process_mem_impact", 0.25, "critical"),
            # --- Agent process rules (absolute, no base needed) ---
            PresetRule("agent_cpu_avg", 10.0, "critical"),
            PresetRule("agent_cpu_p95", 15.0, "warning"),
            PresetRule("agent_mem_rss_avg", 512.0, "warning"),
            PresetRule("agent_mem_rss_max", 1024.0, "critical"),
            # --- JTL rules (application performance — simple delta) ---
            PresetRule("jtl_resp_avg_delta_pct", 10.0, "critical"),
            PresetRule("jtl_resp_p99_delta_pct", 25.0, "warning"),
            PresetRule("jtl_throughput_delta_pct", -5.0, "critical"),
            PresetRule("jtl_error_rate_delta_abs", 0.5, "critical"),
            # --- JTL statistical rules (two-gate, verdict-determining) ---
            PresetRule("stat_jtl_throughput_impact", -0.20, "critical"),
            PresetRule("stat_jtl_response_time_impact", 0.20, "critical"),
        ],
    ),
    "strict": RulePreset(
        key="strict",
        name="Strict",
        description="Tight thresholds for production-critical servers where "
                    "any performance degradation is unacceptable.",
        rules=[
            # --- Per-process statistical rules (tighter thresholds) ---
            PresetRule("stat_process_cpu_impact", 0.147, "critical"),
            PresetRule("stat_process_mem_impact", 0.147, "critical"),
            # --- Agent process rules ---
            PresetRule("agent_cpu_avg", 5.0, "critical"),
            PresetRule("agent_cpu_p95", 10.0, "critical"),
            PresetRule("agent_mem_rss_avg", 256.0, "critical"),
            PresetRule("agent_mem_rss_max", 512.0, "critical"),
            # --- JTL rules (simple delta) ---
            PresetRule("jtl_resp_avg_delta_pct", 5.0, "critical"),
            PresetRule("jtl_resp_p99_delta_pct", 15.0, "critical"),
            PresetRule("jtl_throughput_delta_pct", -3.0, "critical"),
            PresetRule("jtl_error_rate_delta_abs", 0.1, "critical"),
            # --- JTL statistical rules (tighter thresholds) ---
            PresetRule("stat_jtl_throughput_impact", -0.147, "critical"),
            PresetRule("stat_jtl_response_time_impact", 0.147, "critical"),
        ],
    ),
    "lenient": RulePreset(
        key="lenient",
        name="Lenient",
        description="Relaxed thresholds for non-critical environments or agents "
                    "known to have higher overhead. Catches only severe impact.",
        rules=[
            # --- Per-process statistical rules (relaxed thresholds) ---
            PresetRule("stat_process_cpu_impact", 0.33, "critical"),
            PresetRule("stat_process_mem_impact", 0.33, "critical"),
            # --- Agent process rules ---
            PresetRule("agent_cpu_avg", 15.0, "critical"),
            PresetRule("agent_cpu_p95", 25.0, "warning"),
            PresetRule("agent_mem_rss_avg", 1024.0, "warning"),
            PresetRule("agent_mem_rss_max", 2048.0, "warning"),
            # --- JTL rules (simple delta) ---
            PresetRule("jtl_resp_avg_delta_pct", 15.0, "critical"),
            PresetRule("jtl_resp_p99_delta_pct", 40.0, "warning"),
            PresetRule("jtl_throughput_delta_pct", -8.0, "critical"),
            PresetRule("jtl_error_rate_delta_abs", 1.0, "critical"),
            # --- JTL statistical rules (relaxed thresholds) ---
            PresetRule("stat_jtl_throughput_impact", -0.33, "critical"),
            PresetRule("stat_jtl_response_time_impact", 0.33, "critical"),
        ],
    ),
}
