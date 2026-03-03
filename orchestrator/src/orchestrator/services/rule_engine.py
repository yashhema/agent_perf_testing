"""Rule evaluation engine.

Evaluates analysis rules against measured data and determines verdicts.
"""

import logging
from dataclasses import asdict
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.models.enums import RuleSeverity, Verdict
from orchestrator.models.orm import AgentORM, AnalysisRuleORM, ScenarioAgentORM
from orchestrator.services.analysis_models import (
    ComparisonVerdict,
    JtlDelta,
    RuleEvaluation,
    SystemDeltaSummary,
    TestRunVerdict,
)
from orchestrator.services.rule_templates import RULE_PRESETS, RULE_TEMPLATES, RuleTemplate
from orchestrator.services.stats_parser import AgentStatsSummary, MetricSummary
from orchestrator.services.statistical_tests import StatisticalTestResult

logger = logging.getLogger(__name__)


def apply_preset(session: Session, agent_id: int, preset_key: str) -> int:
    """Delete existing rules for agent and create rules from a preset.

    Returns the number of rules created.
    """
    preset = RULE_PRESETS.get(preset_key)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_key}")

    # Delete existing rules
    session.query(AnalysisRuleORM).filter(
        AnalysisRuleORM.agent_id == agent_id
    ).delete()

    # Create rules from preset
    for rule in preset.rules:
        session.add(AnalysisRuleORM(
            agent_id=agent_id,
            rule_template_key=rule.template_key,
            threshold_value=rule.threshold,
            severity=RuleSeverity(rule.severity),
            is_active=True,
        ))

    session.commit()
    return len(preset.rules)


def get_rules_for_scenario(session: Session, scenario_id: int) -> List[AnalysisRuleORM]:
    """Get all active rules for agents linked to a scenario.

    Traverses: Scenario -> ScenarioAgent -> Agent -> AnalysisRule
    Returns list of active AnalysisRuleORM objects.
    """
    agent_ids = [
        sa.agent_id for sa in
        session.query(ScenarioAgentORM).filter(
            ScenarioAgentORM.scenario_id == scenario_id
        ).all()
    ]

    if not agent_ids:
        return []

    return session.query(AnalysisRuleORM).filter(
        AnalysisRuleORM.agent_id.in_(agent_ids),
        AnalysisRuleORM.is_active == True,
    ).all()


def evaluate_rule(
    rule: AnalysisRuleORM,
    template: RuleTemplate,
    system_deltas: Optional[SystemDeltaSummary],
    agent_stats: Optional[AgentStatsSummary],
    jtl_delta: Optional[JtlDelta],
    statistical_tests: Optional[List[StatisticalTestResult]] = None,
    process_statistical_tests: Optional[List[StatisticalTestResult]] = None,
    jtl_statistical_tests: Optional[List[StatisticalTestResult]] = None,
) -> RuleEvaluation:
    """Evaluate a single rule against measured data.

    Routes to the appropriate data source and extracts the actual value,
    then compares against the rule's threshold using the template's operator.
    """
    # Two-gate evaluation for system-wide statistical rules
    if template.data_source == "statistical":
        return _evaluate_statistical_rule(rule, template, statistical_tests)

    # Two-gate evaluation for per-process statistical rules
    if template.data_source == "statistical_process":
        return _evaluate_process_statistical_rule(rule, template, process_statistical_tests)

    # Two-gate evaluation for JTL statistical rules
    if template.data_source == "jtl_statistical":
        return _evaluate_jtl_statistical_rule(rule, template, jtl_statistical_tests)

    actual_value = _extract_value(template, system_deltas, agent_stats, jtl_delta)

    if actual_value is None:
        # Data not available — rule passes by default (no data to violate)
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No data available for {template.name} — skipped",
        )

    # Compare using template operator
    if template.operator == "lt":
        passed = actual_value < rule.threshold_value
    else:  # "gt"
        passed = actual_value > rule.threshold_value

    if passed:
        desc = f"{template.name}: {actual_value:.2f}{template.unit} (threshold: < {rule.threshold_value}{template.unit})"
    else:
        desc = (
            f"{template.name} VIOLATED: {actual_value:.2f}{template.unit} "
            f"exceeds threshold {rule.threshold_value}{template.unit}"
        )

    return RuleEvaluation(
        rule_id=rule.id,
        template_key=template.key,
        rule_name=template.name,
        category=template.category,
        severity=rule.severity.value,
        threshold=rule.threshold_value,
        actual_value=round(actual_value, 4),
        unit=template.unit,
        passed=passed,
        description=desc,
    )


def _extract_value(
    template: RuleTemplate,
    system_deltas: Optional[SystemDeltaSummary],
    agent_stats: Optional[AgentStatsSummary],
    jtl_delta: Optional[JtlDelta],
) -> Optional[float]:
    """Extract the actual measured value from data sources based on template config."""

    if template.data_source == "system_stats" and system_deltas:
        metric_delta = getattr(system_deltas, template.metric, None)
        if metric_delta is None:
            return None

        if template.comparison_mode == "delta_abs":
            delta_stats = metric_delta.delta_abs
            return getattr(delta_stats, template.statistic, None)
        elif template.comparison_mode == "delta_pct":
            delta_stats = metric_delta.delta_pct
            return getattr(delta_stats, template.statistic, None)
        elif template.comparison_mode == "absolute":
            # For stability CV, use the initial phase value's statistic
            if template.statistic == "cv":
                # CV is stddev/mean*100 on the initial values
                initial = metric_delta.initial
                if initial.avg != 0:
                    return (initial.stddev / initial.avg) * 100
                return 0.0
            initial = metric_delta.initial
            return getattr(initial, template.statistic, None)

    elif template.data_source == "agent_stats" and agent_stats:
        metric_summary = getattr(agent_stats, template.metric, None)
        if metric_summary is None:
            return None
        return getattr(metric_summary, template.statistic, None)

    elif template.data_source == "jtl" and jtl_delta:
        if template.comparison_mode == "delta_pct":
            # Map metric to the corresponding delta_pct field on JtlDelta
            field_map = {
                "avg_response_ms": "avg_response_delta_pct",
                "p50_response_ms": "p50_response_delta_pct",
                "p90_response_ms": "p90_response_delta_pct",
                "p95_response_ms": "p95_response_delta_pct",
                "p99_response_ms": "p99_response_delta_pct",
                "throughput_per_sec": "throughput_delta_pct",
                "error_rate_percent": "error_rate_delta_pct",
            }
            field_name = field_map.get(template.metric)
            if field_name:
                return getattr(jtl_delta, field_name, None)
        elif template.comparison_mode == "delta_abs":
            field_map = {
                "avg_response_ms": "avg_response_delta_abs",
                "p50_response_ms": "p50_response_delta_abs",
                "p90_response_ms": "p90_response_delta_abs",
                "p95_response_ms": "p95_response_delta_abs",
                "p99_response_ms": "p99_response_delta_abs",
                "throughput_per_sec": "throughput_delta_abs",
                "error_rate_percent": "error_rate_delta_abs",
            }
            field_name = field_map.get(template.metric)
            if field_name:
                return getattr(jtl_delta, field_name, None)

    return None


def _evaluate_statistical_rule(
    rule: AnalysisRuleORM,
    template: RuleTemplate,
    statistical_tests: Optional[List[StatisticalTestResult]],
) -> RuleEvaluation:
    """Evaluate a statistical rule using two-gate logic.

    Gate 1: Mann-Whitney p-value < 0.05 (statistically significant?)
    Gate 2: |Cliff's delta| >= threshold (meaningful effect size?)

    Both gates must fail for the rule to fail.
    """
    if not statistical_tests:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No statistical test data for {template.name} — skipped",
        )

    # Find the test result for this metric
    test_result = None
    for tr in statistical_tests:
        if tr.metric == template.metric:
            test_result = tr
            break

    if test_result is None:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No statistical test for metric '{template.metric}' — skipped",
        )

    cd = test_result.cliff_delta
    p_val = test_result.mann_whitney_p
    cd_interp = test_result.cliff_delta_interpretation
    ci_lo = test_result.bootstrap_ci_low
    ci_hi = test_result.bootstrap_ci_high
    effect_threshold = rule.threshold_value

    # Two-gate logic:
    # Gate 1: Is the difference statistically significant?
    significant = p_val < 0.05
    # Gate 2: Is the effect size meaningful? (positive delta = initial > base)
    meaningful = cd > effect_threshold  # one-sided: agent increased the metric

    if not significant:
        passed = True
        desc = (
            f"{template.name}: not significant (p={p_val:.4f}, "
            f"delta={cd:.3f} [{cd_interp}], CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )
    elif not meaningful:
        passed = True
        desc = (
            f"{template.name}: significant but negligible effect "
            f"(p={p_val:.4f}, delta={cd:.3f} [{cd_interp}] < {effect_threshold}, "
            f"CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )
    else:
        passed = False
        desc = (
            f"{template.name} FAILED: significant {cd_interp} effect "
            f"(p={p_val:.4f}, delta={cd:.3f} > {effect_threshold}, "
            f"CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )

    return RuleEvaluation(
        rule_id=rule.id,
        template_key=template.key,
        rule_name=template.name,
        category=template.category,
        severity=rule.severity.value,
        threshold=effect_threshold,
        actual_value=round(cd, 6),
        unit=template.unit,
        passed=passed,
        description=desc,
    )


def _evaluate_process_statistical_rule(
    rule: AnalysisRuleORM,
    template: RuleTemplate,
    process_tests: Optional[List[StatisticalTestResult]],
) -> RuleEvaluation:
    """Evaluate a per-process statistical rule using two-gate logic.

    Finds ALL per-process test results matching the template metric
    (e.g., all tests ending with ":cpu_percent") and applies two-gate
    logic to each. If ANY process fails both gates, the rule fails.
    Reports the worst-case process in the description.
    """
    if not process_tests:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=(
                f"No per-process statistical data for {template.name} — skipped "
                f"(ensure service_monitor_patterns is configured)"
            ),
        )

    # Find all test results matching this metric type
    # Per-process tests use metric format: "proc:{name}:{metric}"
    suffix = f":{template.metric}"
    matching = [t for t in process_tests if t.metric.endswith(suffix)]

    if not matching:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No per-process tests for '{template.metric}' — skipped",
        )

    effect_threshold = rule.threshold_value
    worst_cd = 0.0
    worst_proc = None
    any_failed = False
    per_proc_details = []

    for tr in matching:
        # Extract process name from metric "proc:{name}:{metric}"
        parts = tr.metric.split(":")
        proc_name = parts[1] if len(parts) >= 3 else tr.metric

        significant = tr.mann_whitney_p < 0.05
        meaningful = tr.cliff_delta > effect_threshold
        failed = significant and meaningful

        if failed:
            any_failed = True
        if tr.cliff_delta > worst_cd:
            worst_cd = tr.cliff_delta
            worst_proc = proc_name

        status = "FAIL" if failed else "ok"
        per_proc_details.append(
            f"{proc_name}({status}: d={tr.cliff_delta:.3f}, p={tr.mann_whitney_p:.4f})"
        )

    if not any_failed:
        desc = (
            f"{template.name}: all processes within threshold — "
            + ", ".join(per_proc_details)
        )
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=effect_threshold,
            actual_value=round(worst_cd, 6),
            unit=template.unit,
            passed=True,
            description=desc,
        )
    else:
        desc = (
            f"{template.name} FAILED on '{worst_proc}': "
            f"significant effect (delta={worst_cd:.3f} > {effect_threshold}) — "
            + ", ".join(per_proc_details)
        )
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=effect_threshold,
            actual_value=round(worst_cd, 6),
            unit=template.unit,
            passed=False,
            description=desc,
        )


def _evaluate_jtl_statistical_rule(
    rule: AnalysisRuleORM,
    template: RuleTemplate,
    jtl_tests: Optional[List[StatisticalTestResult]],
) -> RuleEvaluation:
    """Evaluate a JTL statistical rule using two-gate logic.

    For throughput: negative delta = agent reducing throughput (bad).
      Threshold is negative (e.g., -0.20). Fails if delta < threshold.
    For response time: positive delta = agent adding latency (bad).
      Threshold is positive (e.g., 0.20). Fails if delta > threshold.
    """
    if not jtl_tests:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No JTL statistical data for {template.name} — skipped",
        )

    # Find the test result for this metric
    test_result = None
    for tr in jtl_tests:
        if tr.metric == template.metric:
            test_result = tr
            break

    if test_result is None:
        return RuleEvaluation(
            rule_id=rule.id,
            template_key=template.key,
            rule_name=template.name,
            category=template.category,
            severity=rule.severity.value,
            threshold=rule.threshold_value,
            actual_value=0.0,
            unit=template.unit,
            passed=True,
            description=f"No JTL test for metric '{template.metric}' — skipped",
        )

    cd = test_result.cliff_delta
    p_val = test_result.mann_whitney_p
    cd_interp = test_result.cliff_delta_interpretation
    ci_lo = test_result.bootstrap_ci_low
    ci_hi = test_result.bootstrap_ci_high
    threshold = rule.threshold_value

    # Gate 1: statistically significant?
    significant = p_val < 0.05

    # Gate 2: meaningful effect?
    # For throughput (operator=gt, threshold=-0.20): fails if delta < threshold (big drop)
    # For response time (operator=lt, threshold=0.20): fails if delta > threshold (big increase)
    if template.operator == "gt":
        meaningful = cd < threshold  # negative delta worse than negative threshold
    else:
        meaningful = cd > threshold  # positive delta exceeds positive threshold

    if not significant:
        passed = True
        desc = (
            f"{template.name}: not significant (p={p_val:.4f}, "
            f"delta={cd:.3f} [{cd_interp}], CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )
    elif not meaningful:
        passed = True
        desc = (
            f"{template.name}: significant but negligible effect "
            f"(p={p_val:.4f}, delta={cd:.3f} [{cd_interp}], "
            f"threshold={threshold}, CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )
    else:
        passed = False
        desc = (
            f"{template.name} FAILED: significant {cd_interp} effect "
            f"(p={p_val:.4f}, delta={cd:.3f}, threshold={threshold}, "
            f"CI=[{ci_lo:.2f}, {ci_hi:.2f}])"
        )

    return RuleEvaluation(
        rule_id=rule.id,
        template_key=template.key,
        rule_name=template.name,
        category=template.category,
        severity=rule.severity.value,
        threshold=threshold,
        actual_value=round(cd, 6),
        unit=template.unit,
        passed=passed,
        description=desc,
    )


def evaluate_rules(
    rules: List[AnalysisRuleORM],
    system_deltas: Optional[SystemDeltaSummary],
    agent_stats: Optional[AgentStatsSummary],
    jtl_delta: Optional[JtlDelta],
    statistical_tests: Optional[List[StatisticalTestResult]] = None,
    process_statistical_tests: Optional[List[StatisticalTestResult]] = None,
    jtl_statistical_tests: Optional[List[StatisticalTestResult]] = None,
) -> List[RuleEvaluation]:
    """Evaluate all rules against measured data."""
    evaluations = []
    for rule in rules:
        template = RULE_TEMPLATES.get(rule.rule_template_key)
        if not template:
            logger.warning("Unknown rule template key: %s", rule.rule_template_key)
            continue
        evaluation = evaluate_rule(
            rule, template, system_deltas, agent_stats, jtl_delta,
            statistical_tests, process_statistical_tests, jtl_statistical_tests,
        )
        evaluations.append(evaluation)
    return evaluations


def determine_verdict(evaluations: List[RuleEvaluation]) -> ComparisonVerdict:
    """Determine verdict from rule evaluations.

    - Any critical failure -> failed
    - Any warning failure -> warning
    - Otherwise -> passed
    """
    if not evaluations:
        return ComparisonVerdict(
            verdict=Verdict.passed,
            total_rules=0,
            passed_count=0,
            failed_count=0,
            worst_failure=None,
            evaluations=evaluations,
        )

    failed = [e for e in evaluations if not e.passed]
    passed = [e for e in evaluations if e.passed]

    worst_failure = None
    verdict = Verdict.passed

    if failed:
        critical_failures = [e for e in failed if e.severity == "critical"]
        if critical_failures:
            verdict = Verdict.failed
            worst_failure = critical_failures[0].description
        else:
            verdict = Verdict.warning
            worst_failure = failed[0].description

    return ComparisonVerdict(
        verdict=verdict,
        total_rules=len(evaluations),
        passed_count=len(passed),
        failed_count=len(failed),
        worst_failure=worst_failure,
        evaluations=evaluations,
    )


def determine_overall_verdict(per_lp_verdicts: Dict[int, ComparisonVerdict]) -> TestRunVerdict:
    """Determine overall test run verdict from per-load-profile verdicts.

    Takes the worst verdict across all load profiles.
    """
    if not per_lp_verdicts:
        return TestRunVerdict(overall_verdict=Verdict.passed)

    total_rules = sum(v.total_rules for v in per_lp_verdicts.values())
    total_passed = sum(v.passed_count for v in per_lp_verdicts.values())
    total_failed = sum(v.failed_count for v in per_lp_verdicts.values())

    # Worst verdict wins
    verdicts = [v.verdict for v in per_lp_verdicts.values()]
    if Verdict.failed in verdicts:
        overall = Verdict.failed
    elif Verdict.warning in verdicts:
        overall = Verdict.warning
    else:
        overall = Verdict.passed

    summary_parts = []
    for lp_id, v in per_lp_verdicts.items():
        summary_parts.append(
            f"LP#{lp_id}: {v.verdict.value} ({v.passed_count}/{v.total_rules} passed)"
        )
    summary = "; ".join(summary_parts)

    return TestRunVerdict(
        overall_verdict=overall,
        per_load_profile=per_lp_verdicts,
        total_rules=total_rules,
        total_passed=total_passed,
        total_failed=total_failed,
        summary=summary,
    )
