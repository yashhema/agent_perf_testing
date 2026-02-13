"""Comparison and reporting engine.

Phase 9: Compares base vs initial phase stats to measure agent impact.

Enhanced pipeline:
  1. Parse stats JSON files for all PhaseExecutionResults
  2. Trim samples (warmup/cooldown)
  3. Cross-cycle validation: detect and exclude anomalous cycles
  4. Compute per-phase summaries (system + agent + JTL, all 7 stats)
  5. Compute deltas: initial - base (absolute and percentage) for all metrics
  6. Evaluate rules from linked agents
  7. Determine per-comparison verdict
  8. Generate per-target ComparisonResultORM (enriched with verdict)
  9. Generate aggregated ComparisonResultORM
 10. Determine overall TestRunVerdict
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from orchestrator.models.enums import ExecutionStatus, Verdict
from orchestrator.models.orm import (
    ComparisonResultORM,
    LoadProfileORM,
    PhaseExecutionResultORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)
from orchestrator.services.analysis_models import (
    FullComparisonData,
    JtlDelta,
    MetricDelta,
    MetricDeltaStats,
    SystemDeltaSummary,
)
from orchestrator.services.jtl_parser import JtlParser, JtlResult
from orchestrator.services.ratio_normalizer import (
    compute_normalized_ratios,
    serialize_ratios,
)
from orchestrator.services.rule_engine import (
    determine_overall_verdict,
    determine_verdict,
    evaluate_rules,
    get_rules_for_scenario,
)
from orchestrator.services.stats_parser import (
    AgentStatsSummary,
    MetricSummary,
    StatsParser,
    StatsSummary,
)

logger = logging.getLogger(__name__)

# Metric names for system stats
SYSTEM_METRICS = [
    "cpu_percent", "memory_percent", "memory_used_mb",
    "disk_read_rate_mbps", "disk_write_rate_mbps",
    "network_sent_rate_mbps", "network_recv_rate_mbps",
]


class ComparisonEngine:
    """Compares base vs initial phase results with full analysis pipeline."""

    def __init__(self, trim_start_sec: float = 30, trim_end_sec: float = 10):
        self._parser = StatsParser()
        self._jtl_parser = JtlParser()
        self._trim_start = trim_start_sec
        self._trim_end = trim_end_sec

    def run_comparison(self, session: Session, test_run: TestRunORM, results_dir: str) -> None:
        """Run full comparison for a completed test run.

        Creates ComparisonResultORM records (per-target and aggregated),
        evaluates rules, determines verdicts, and updates overall_verdict.
        """
        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()
        load_profile_links = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()

        # Load rules for the scenario
        rules = get_rules_for_scenario(session, test_run.scenario_id)

        per_lp_verdicts = {}

        for lp_link in load_profile_links:
            lp = session.get(LoadProfileORM, lp_link.load_profile_id)
            all_target_comparisons: List[FullComparisonData] = []

            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)

                # Get system stats summaries (all 7 metrics)
                base_sys, base_agent = self._aggregate_phase_stats(
                    session, test_run.id, server.id, lp.id, snapshot_num=1
                )
                initial_sys, initial_agent = self._aggregate_phase_stats(
                    session, test_run.id, server.id, lp.id, snapshot_num=2
                )

                if base_sys is None or initial_sys is None:
                    logger.warning(
                        "Skipping comparison for server %s / profile %s: missing stats",
                        server.hostname, lp.name,
                    )
                    continue

                # Compute system deltas (all 7 metrics x all stats)
                system_deltas = self._compute_system_delta(base_sys, initial_sys)

                # Get JTL results
                base_jtl = self._aggregate_jtl(
                    session, test_run.id, server.id, lp.id, snapshot_num=1
                )
                initial_jtl = self._aggregate_jtl(
                    session, test_run.id, server.id, lp.id, snapshot_num=2
                )
                jtl_delta = self._compute_jtl_delta(base_jtl, initial_jtl)

                # Compute normalized ratios
                ratios = (
                    compute_normalized_ratios(base_sys, initial_agent)
                    if base_sys and initial_agent
                    else None
                )

                # Evaluate rules
                evaluations = evaluate_rules(rules, system_deltas, initial_agent, jtl_delta)
                verdict = determine_verdict(evaluations)

                comparison = FullComparisonData(
                    system_deltas=system_deltas,
                    agent_overhead=initial_agent,
                    jtl_delta=jtl_delta,
                    rule_evaluations=evaluations,
                    verdict=verdict.verdict,
                    verdict_summary=verdict.worst_failure or "",
                    normalized_ratios=ratios,
                )
                all_target_comparisons.append(comparison)

                # Save per-target result
                summary_text = self._generate_summary_text(
                    system_deltas, server.hostname, lp.name, verdict.verdict
                )
                self._save_result(
                    session, test_run.id, server.id, lp.id,
                    "per_target", comparison, summary_text, results_dir,
                    verdict.verdict, verdict.failed_count,
                )

            # Aggregated comparison across all targets
            if all_target_comparisons:
                aggregated = self._aggregate_full_comparisons(all_target_comparisons)
                agg_evaluations = evaluate_rules(
                    rules, aggregated.system_deltas, aggregated.agent_overhead, aggregated.jtl_delta
                )
                agg_verdict = determine_verdict(agg_evaluations)
                aggregated.rule_evaluations = agg_evaluations
                aggregated.verdict = agg_verdict.verdict
                aggregated.verdict_summary = agg_verdict.worst_failure or ""

                agg_text = self._generate_summary_text(
                    aggregated.system_deltas, "all targets", lp.name, agg_verdict.verdict
                )
                self._save_result(
                    session, test_run.id, None, lp.id,
                    "aggregated", aggregated, agg_text, results_dir,
                    agg_verdict.verdict, agg_verdict.failed_count,
                )
                per_lp_verdicts[lp.id] = agg_verdict

        # Determine overall verdict
        if per_lp_verdicts:
            overall = determine_overall_verdict(per_lp_verdicts)
            test_run.overall_verdict = overall.overall_verdict
        else:
            test_run.overall_verdict = Verdict.pending

        session.commit()

    def _aggregate_phase_stats(
        self,
        session: Session,
        test_run_id: int,
        target_id: int,
        load_profile_id: int,
        snapshot_num: int,
    ) -> Tuple[Optional[StatsSummary], Optional[AgentStatsSummary]]:
        """Load and aggregate stats across all cycles for a phase.

        Returns (system_summary, agent_summary) tuple.
        Performs cross-cycle validation on cpu_percent and excludes anomalous cycles.
        """
        results = session.query(PhaseExecutionResultORM).filter(
            PhaseExecutionResultORM.test_run_id == test_run_id,
            PhaseExecutionResultORM.target_id == target_id,
            PhaseExecutionResultORM.load_profile_id == load_profile_id,
            PhaseExecutionResultORM.snapshot_num == snapshot_num,
            PhaseExecutionResultORM.status == ExecutionStatus.completed,
        ).order_by(PhaseExecutionResultORM.cycle_number).all()

        if not results:
            return None, None

        # Collect samples per cycle
        per_cycle_samples: List[List[Dict[str, Any]]] = []
        for result in results:
            if not result.stats_file_path or not Path(result.stats_file_path).exists():
                per_cycle_samples.append([])
                continue
            stats_data = self._parser.parse_stats_file(result.stats_file_path)
            samples = stats_data.get("samples", [])
            trimmed = self._parser.trim_samples(samples, self._trim_start, self._trim_end)
            per_cycle_samples.append(trimmed)

        # Cross-cycle validation on cpu_percent
        non_empty_cycles = [s for s in per_cycle_samples if s]
        if len(non_empty_cycles) > 1:
            consistency = self._parser.compute_per_cycle_stats(non_empty_cycles, "cpu_percent")
            excluded_indices = set(consistency.excluded_cycles)
            if excluded_indices:
                logger.info(
                    "Excluding cycles %s for target=%d, lp=%d, snap=%d: %s",
                    excluded_indices, target_id, load_profile_id, snapshot_num,
                    consistency.note,
                )
        else:
            excluded_indices = set()

        # Merge samples from non-excluded cycles
        all_samples = []
        cycle_idx = 0
        for samples in per_cycle_samples:
            if samples:
                if cycle_idx not in excluded_indices:
                    all_samples.extend(samples)
                cycle_idx += 1

        if not all_samples:
            return None, None

        system_summary = self._parser.compute_summary(all_samples)
        agent_summary = self._parser.compute_agent_summary(all_samples)

        return system_summary, agent_summary

    def _aggregate_jtl(
        self,
        session: Session,
        test_run_id: int,
        target_id: int,
        load_profile_id: int,
        snapshot_num: int,
    ) -> Optional[JtlResult]:
        """Aggregate JTL results across all cycles for a phase."""
        results = session.query(PhaseExecutionResultORM).filter(
            PhaseExecutionResultORM.test_run_id == test_run_id,
            PhaseExecutionResultORM.target_id == target_id,
            PhaseExecutionResultORM.load_profile_id == load_profile_id,
            PhaseExecutionResultORM.snapshot_num == snapshot_num,
            PhaseExecutionResultORM.status == ExecutionStatus.completed,
        ).order_by(PhaseExecutionResultORM.cycle_number).all()

        jtl_results: List[JtlResult] = []
        for result in results:
            if not result.jmeter_jtl_path or not Path(result.jmeter_jtl_path).exists():
                continue
            try:
                jtl = self._jtl_parser.parse(result.jmeter_jtl_path)
                if jtl.total_requests > 0:
                    jtl_results.append(jtl)
            except Exception as e:
                logger.warning("Failed to parse JTL %s: %s", result.jmeter_jtl_path, e)

        if not jtl_results:
            return None

        return self._merge_jtl_results(jtl_results)

    def _merge_jtl_results(self, results: List[JtlResult]) -> JtlResult:
        """Merge multiple JTL results using weighted average by request count."""
        if len(results) == 1:
            return results[0]

        total_requests = sum(r.total_requests for r in results)
        total_errors = sum(r.total_errors for r in results)
        total_duration = sum(r.duration_sec for r in results)

        if total_requests == 0:
            return results[0]

        # Weighted averages
        avg_resp = sum(r.avg_response_ms * r.total_requests for r in results) / total_requests
        p50_resp = sum(r.p50_response_ms * r.total_requests for r in results) / total_requests
        p90_resp = sum(r.p90_response_ms * r.total_requests for r in results) / total_requests
        p95_resp = sum(r.p95_response_ms * r.total_requests for r in results) / total_requests
        p99_resp = sum(r.p99_response_ms * r.total_requests for r in results) / total_requests
        throughput = total_requests / total_duration if total_duration > 0 else 0

        return JtlResult(
            total_requests=total_requests,
            total_errors=total_errors,
            error_rate_percent=round((total_errors / total_requests) * 100, 2) if total_requests > 0 else 0,
            throughput_per_sec=round(throughput, 2),
            duration_sec=round(total_duration, 2),
            avg_response_ms=round(avg_resp, 2),
            p50_response_ms=round(p50_resp, 2),
            p90_response_ms=round(p90_resp, 2),
            p95_response_ms=round(p95_resp, 2),
            p99_response_ms=round(p99_resp, 2),
        )

    def _compute_system_delta(
        self, base: StatsSummary, initial: StatsSummary
    ) -> SystemDeltaSummary:
        """Compute full delta between base and initial system stats."""
        deltas = {}
        for metric in SYSTEM_METRICS:
            base_ms: MetricSummary = getattr(base, metric)
            init_ms: MetricSummary = getattr(initial, metric)
            deltas[metric] = self._compute_metric_delta(base_ms, init_ms)

        return SystemDeltaSummary(**deltas)

    def _compute_metric_delta(
        self, base: MetricSummary, initial: MetricSummary
    ) -> MetricDelta:
        """Compute delta between base and initial for a single metric."""
        stats = ["avg", "min", "max", "p50", "p90", "p95", "p99"]

        abs_deltas = {}
        pct_deltas = {}
        for stat in stats:
            base_val = getattr(base, stat)
            init_val = getattr(initial, stat)
            abs_delta = round(init_val - base_val, 4)
            pct_delta = round(
                ((init_val - base_val) / base_val) * 100, 2
            ) if base_val != 0 else 0.0
            abs_deltas[stat] = abs_delta
            pct_deltas[stat] = pct_delta

        return MetricDelta(
            base=base,
            initial=initial,
            delta_abs=MetricDeltaStats(**abs_deltas),
            delta_pct=MetricDeltaStats(**pct_deltas),
        )

    def _compute_jtl_delta(
        self, base_jtl: Optional[JtlResult], initial_jtl: Optional[JtlResult]
    ) -> Optional[JtlDelta]:
        """Compute JTL delta between base and initial phases."""
        if not base_jtl or not initial_jtl:
            return None

        def pct(base_val, init_val):
            if base_val != 0:
                return round(((init_val - base_val) / base_val) * 100, 2)
            return 0.0

        return JtlDelta(
            base=base_jtl,
            initial=initial_jtl,
            avg_response_delta_abs=round(initial_jtl.avg_response_ms - base_jtl.avg_response_ms, 2),
            avg_response_delta_pct=pct(base_jtl.avg_response_ms, initial_jtl.avg_response_ms),
            p50_response_delta_abs=round(initial_jtl.p50_response_ms - base_jtl.p50_response_ms, 2),
            p50_response_delta_pct=pct(base_jtl.p50_response_ms, initial_jtl.p50_response_ms),
            p90_response_delta_abs=round(initial_jtl.p90_response_ms - base_jtl.p90_response_ms, 2),
            p90_response_delta_pct=pct(base_jtl.p90_response_ms, initial_jtl.p90_response_ms),
            p95_response_delta_abs=round(initial_jtl.p95_response_ms - base_jtl.p95_response_ms, 2),
            p95_response_delta_pct=pct(base_jtl.p95_response_ms, initial_jtl.p95_response_ms),
            p99_response_delta_abs=round(initial_jtl.p99_response_ms - base_jtl.p99_response_ms, 2),
            p99_response_delta_pct=pct(base_jtl.p99_response_ms, initial_jtl.p99_response_ms),
            throughput_delta_abs=round(initial_jtl.throughput_per_sec - base_jtl.throughput_per_sec, 2),
            throughput_delta_pct=pct(base_jtl.throughput_per_sec, initial_jtl.throughput_per_sec),
            error_rate_delta_abs=round(initial_jtl.error_rate_percent - base_jtl.error_rate_percent, 2),
            error_rate_delta_pct=pct(base_jtl.error_rate_percent, initial_jtl.error_rate_percent),
        )

    def _aggregate_full_comparisons(
        self, comparisons: List[FullComparisonData]
    ) -> FullComparisonData:
        """Average system deltas across multiple targets for aggregated result."""
        n = len(comparisons)

        # Average system deltas
        if any(c.system_deltas for c in comparisons):
            valid = [c for c in comparisons if c.system_deltas]
            n_valid = len(valid)
            agg_deltas = {}
            for metric in SYSTEM_METRICS:
                base_avgs = [getattr(c.system_deltas, metric).base.avg for c in valid]
                init_avgs = [getattr(c.system_deltas, metric).initial.avg for c in valid]
                avg_base = sum(base_avgs) / n_valid
                avg_init = sum(init_avgs) / n_valid
                base_ms = MetricSummary(
                    avg=round(avg_base, 4), min=0, max=0, p50=0, p90=0, p95=0, p99=0
                )
                init_ms = MetricSummary(
                    avg=round(avg_init, 4), min=0, max=0, p50=0, p90=0, p95=0, p99=0
                )
                agg_deltas[metric] = self._compute_metric_delta(base_ms, init_ms)
            system_deltas = SystemDeltaSummary(**agg_deltas)
        else:
            system_deltas = None

        # Use first non-None agent stats (agent overhead is target-specific)
        agent_overhead = next(
            (c.agent_overhead for c in comparisons if c.agent_overhead), None
        )

        # Use first non-None JTL delta
        jtl_delta = next((c.jtl_delta for c in comparisons if c.jtl_delta), None)

        return FullComparisonData(
            system_deltas=system_deltas,
            agent_overhead=agent_overhead,
            jtl_delta=jtl_delta,
        )

    def _generate_summary_text(
        self,
        system_deltas: Optional[SystemDeltaSummary],
        target_name: str,
        profile_name: str,
        verdict: Optional[Verdict] = None,
    ) -> str:
        """Generate a 1-paragraph summary of agent impact."""
        if not system_deltas:
            return f"No comparison data available for {target_name} under '{profile_name}'."

        cpu = system_deltas.cpu_percent
        mem = system_deltas.memory_percent

        cpu_delta = cpu.delta_abs.avg
        mem_delta = mem.delta_abs.avg
        cpu_pct = cpu.delta_pct.avg
        mem_pct = mem.delta_pct.avg

        direction = "increased" if cpu_delta > 0 else "decreased"
        mem_direction = "increased" if mem_delta > 0 else "decreased"

        verdict_str = ""
        if verdict:
            verdict_str = f" Verdict: {verdict.value.upper()}."

        return (
            f"Under the '{profile_name}' load profile on {target_name}, "
            f"the security agent {direction} average CPU utilization by "
            f"{abs(cpu_delta):.1f} percentage points "
            f"({abs(cpu_pct):.1f}% relative change, "
            f"from {cpu.base.avg:.1f}% to {cpu.initial.avg:.1f}%). "
            f"Memory utilization {mem_direction} by "
            f"{abs(mem_delta):.1f} percentage points "
            f"({abs(mem_pct):.1f}% relative change). "
            f"Disk and network impact were "
            f"{abs(system_deltas.disk_read_rate_mbps.delta_pct.avg):.1f}% and "
            f"{abs(system_deltas.network_sent_rate_mbps.delta_pct.avg):.1f}% respectively."
            f"{verdict_str}"
        )

    def _save_result(
        self,
        session: Session,
        test_run_id: int,
        target_id: Optional[int],
        load_profile_id: int,
        comparison_type: str,
        data: FullComparisonData,
        summary_text: str,
        results_dir: str,
        verdict: Optional[Verdict] = None,
        violation_count: int = 0,
    ) -> None:
        """Save comparison result to DB and optionally to file."""
        result_data = self._serialize_comparison(data)

        # Save JSON file
        comp_dir = Path(results_dir) / str(test_run_id) / "comparison"
        comp_dir.mkdir(parents=True, exist_ok=True)
        target_label = str(target_id) if target_id else "aggregated"
        file_path = comp_dir / f"comparison_{target_label}_lp{load_profile_id}.json"
        with open(file_path, "w") as f:
            json.dump({"result_data": result_data, "summary_text": summary_text}, f, indent=2)

        session.add(ComparisonResultORM(
            test_run_id=test_run_id,
            target_id=target_id,
            load_profile_id=load_profile_id,
            comparison_type=comparison_type,
            result_file_path=str(file_path),
            result_data=result_data,
            summary_text=summary_text,
            verdict=verdict,
            violation_count=violation_count,
        ))

    def _serialize_comparison(self, data: FullComparisonData) -> Dict[str, Any]:
        """Serialize FullComparisonData to JSON-safe dict."""
        result: Dict[str, Any] = {}

        # System deltas
        if data.system_deltas:
            sys_data = {}
            for metric in SYSTEM_METRICS:
                md = getattr(data.system_deltas, metric)
                sys_data[metric] = {
                    "base_avg": md.base.avg,
                    "initial_avg": md.initial.avg,
                    "delta_abs": {
                        "avg": md.delta_abs.avg, "min": md.delta_abs.min,
                        "max": md.delta_abs.max, "p50": md.delta_abs.p50,
                        "p90": md.delta_abs.p90, "p95": md.delta_abs.p95,
                        "p99": md.delta_abs.p99,
                    },
                    "delta_pct": {
                        "avg": md.delta_pct.avg, "min": md.delta_pct.min,
                        "max": md.delta_pct.max, "p50": md.delta_pct.p50,
                        "p90": md.delta_pct.p90, "p95": md.delta_pct.p95,
                        "p99": md.delta_pct.p99,
                    },
                }
            result["system_deltas"] = sys_data

        # Agent overhead
        if data.agent_overhead:
            agent_data = {}
            for field_name in [
                "agent_cpu_percent", "agent_memory_rss_mb", "agent_memory_vms_mb",
                "agent_thread_count", "agent_handle_count",
                "agent_io_read_rate_mbps", "agent_io_write_rate_mbps", "process_count",
            ]:
                ms = getattr(data.agent_overhead, field_name)
                agent_data[field_name] = {
                    "avg": ms.avg, "min": ms.min, "max": ms.max,
                    "p50": ms.p50, "p90": ms.p90, "p95": ms.p95, "p99": ms.p99,
                }
            result["agent_overhead"] = agent_data

        # JTL delta
        if data.jtl_delta:
            jtl_data = {
                "avg_response_delta_abs": data.jtl_delta.avg_response_delta_abs,
                "avg_response_delta_pct": data.jtl_delta.avg_response_delta_pct,
                "p50_response_delta_pct": data.jtl_delta.p50_response_delta_pct,
                "p90_response_delta_pct": data.jtl_delta.p90_response_delta_pct,
                "p95_response_delta_pct": data.jtl_delta.p95_response_delta_pct,
                "p99_response_delta_abs": data.jtl_delta.p99_response_delta_abs,
                "p99_response_delta_pct": data.jtl_delta.p99_response_delta_pct,
                "throughput_delta_abs": data.jtl_delta.throughput_delta_abs,
                "throughput_delta_pct": data.jtl_delta.throughput_delta_pct,
                "error_rate_delta_abs": data.jtl_delta.error_rate_delta_abs,
                "error_rate_delta_pct": data.jtl_delta.error_rate_delta_pct,
            }
            if data.jtl_delta.base:
                jtl_data["base"] = {
                    "avg_response_ms": data.jtl_delta.base.avg_response_ms,
                    "p99_response_ms": data.jtl_delta.base.p99_response_ms,
                    "throughput_per_sec": data.jtl_delta.base.throughput_per_sec,
                    "error_rate_percent": data.jtl_delta.base.error_rate_percent,
                }
            if data.jtl_delta.initial:
                jtl_data["initial"] = {
                    "avg_response_ms": data.jtl_delta.initial.avg_response_ms,
                    "p99_response_ms": data.jtl_delta.initial.p99_response_ms,
                    "throughput_per_sec": data.jtl_delta.initial.throughput_per_sec,
                    "error_rate_percent": data.jtl_delta.initial.error_rate_percent,
                }
            result["jtl_comparison"] = jtl_data

        # Rule evaluations
        if data.rule_evaluations:
            result["rule_evaluations"] = [
                {
                    "rule_id": e.rule_id,
                    "template_key": e.template_key,
                    "rule_name": e.rule_name,
                    "category": e.category,
                    "severity": e.severity,
                    "threshold": e.threshold,
                    "actual_value": e.actual_value,
                    "unit": e.unit,
                    "passed": e.passed,
                    "description": e.description,
                }
                for e in data.rule_evaluations
            ]

        # Normalized ratios
        if data.normalized_ratios:
            result["normalized_ratios"] = serialize_ratios(data.normalized_ratios)

        # Verdict
        if data.verdict:
            result["verdict"] = data.verdict.value
            result["verdict_summary"] = data.verdict_summary

        return result
