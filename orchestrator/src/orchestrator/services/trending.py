"""Trending service — cross-run trend queries for agent impact analysis.

Provides time-series views of agent performance metrics across completed
test runs, with filtering by OS, hardware profile, and load profile.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from orchestrator.models.enums import TestRunState, Verdict
from orchestrator.models.orm import (
    AgentORM,
    ComparisonResultORM,
    HardwareProfileORM,
    LoadProfileORM,
    ScenarioAgentORM,
    ScenarioORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)

logger = logging.getLogger(__name__)


@dataclass
class TrendPoint:
    """A single data point in a trend series."""
    test_run_id: int
    agent_version: Optional[str] = None
    os_kind: Optional[str] = None
    os_major_ver: Optional[str] = None
    os_minor_ver: Optional[str] = None
    hardware_profile_name: Optional[str] = None
    load_profile_name: Optional[str] = None
    value: Optional[float] = None
    is_ratio: bool = False
    base_value: Optional[float] = None
    run_date: Optional[datetime] = None
    verdict: Optional[Verdict] = None


def _extract_jsonb_value(data: Dict[str, Any], dotted_path: str) -> Optional[float]:
    """Navigate nested dict by dot-separated path, returning the leaf value."""
    parts = dotted_path.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    if isinstance(current, (int, float)):
        return float(current)
    return None


class TrendingService:
    """Queries cross-run trend data for agent metrics."""

    def query_trend(
        self,
        session: Session,
        agent_id: int,
        metric: str,
        statistic: str = "avg",
        os_kind: Optional[str] = None,
        os_major_ver: Optional[str] = None,
        hardware_profile_id: Optional[int] = None,
        load_profile_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[TrendPoint]:
        """Query trend data across completed test runs for an agent.

        Args:
            agent_id: The agent to track.
            metric: Metric name. Suffix '_ratio' selects from normalized_ratios.
                    Prefix 'agent_' selects from agent_overhead.
                    Otherwise selects from system_deltas.
            statistic: Which statistic to extract (avg, p50, p90, p95, p99, etc.).
            os_kind: Filter by OS kind.
            os_major_ver: Filter by initial OS major version.
            hardware_profile_id: Filter by hardware profile.
            load_profile_id: Filter by load profile.
            limit: Maximum number of data points.

        Returns:
            List of TrendPoint, ordered chronologically.
        """
        # Build the JSONB extraction path based on metric name
        is_ratio = metric.endswith("_ratio")
        jsonb_path = self._build_metric_path(metric, statistic)
        base_value_path = self._build_base_value_path(metric, statistic) if is_ratio else None

        # Find completed test runs that include this agent
        scenario_ids = (
            session.query(ScenarioAgentORM.scenario_id)
            .filter(ScenarioAgentORM.agent_id == agent_id)
            .subquery()
        )

        query = (
            session.query(
                ComparisonResultORM,
                TestRunORM,
                TestRunTargetORM,
                ServerORM,
                HardwareProfileORM,
                LoadProfileORM,
            )
            .join(TestRunORM, ComparisonResultORM.test_run_id == TestRunORM.id)
            .join(
                TestRunTargetORM,
                and_(
                    TestRunTargetORM.test_run_id == TestRunORM.id,
                    TestRunTargetORM.target_id == ComparisonResultORM.target_id,
                ),
            )
            .join(ServerORM, ServerORM.id == TestRunTargetORM.target_id)
            .join(HardwareProfileORM, HardwareProfileORM.id == ServerORM.hardware_profile_id)
            .join(LoadProfileORM, LoadProfileORM.id == ComparisonResultORM.load_profile_id)
            .filter(
                TestRunORM.state == TestRunState.completed,
                TestRunORM.scenario_id.in_(scenario_ids),
                ComparisonResultORM.comparison_type == "per_target",
                ComparisonResultORM.result_data.isnot(None),
            )
        )

        # Apply optional filters
        if os_kind:
            query = query.filter(TestRunTargetORM.os_kind == os_kind)
        if os_major_ver:
            query = query.filter(TestRunTargetORM.initial_os_major_ver == os_major_ver)
        if hardware_profile_id:
            query = query.filter(ServerORM.hardware_profile_id == hardware_profile_id)
        if load_profile_id:
            query = query.filter(ComparisonResultORM.load_profile_id == load_profile_id)

        query = query.order_by(TestRunORM.created_at).limit(limit)

        results = query.all()
        data_points: List[TrendPoint] = []

        for comp, test_run, trt, server, hw, lp in results:
            result_data = comp.result_data or {}

            value = _extract_jsonb_value(result_data, jsonb_path)
            base_val = (
                _extract_jsonb_value(result_data, base_value_path)
                if base_value_path
                else None
            )

            # Extract agent version from initial_agent_versions
            agent_version = self._extract_agent_version(
                trt.initial_agent_versions, agent_id
            )

            data_points.append(
                TrendPoint(
                    test_run_id=test_run.id,
                    agent_version=agent_version,
                    os_kind=trt.os_kind,
                    os_major_ver=trt.initial_os_major_ver,
                    os_minor_ver=trt.initial_os_minor_ver,
                    hardware_profile_name=hw.name,
                    load_profile_name=lp.name,
                    value=value,
                    is_ratio=is_ratio,
                    base_value=base_val,
                    run_date=test_run.created_at,
                    verdict=comp.verdict,
                )
            )

        return data_points

    def get_available_filters(
        self, session: Session, agent_id: int
    ) -> Dict[str, Any]:
        """Return distinct filter values available for an agent's test runs.

        Used to populate UI filter dropdowns.
        """
        scenario_ids = (
            session.query(ScenarioAgentORM.scenario_id)
            .filter(ScenarioAgentORM.agent_id == agent_id)
            .subquery()
        )

        base_query = (
            session.query(TestRunTargetORM, ServerORM, HardwareProfileORM)
            .join(TestRunORM, TestRunTargetORM.test_run_id == TestRunORM.id)
            .join(ServerORM, ServerORM.id == TestRunTargetORM.target_id)
            .join(HardwareProfileORM, HardwareProfileORM.id == ServerORM.hardware_profile_id)
            .filter(
                TestRunORM.state == TestRunState.completed,
                TestRunORM.scenario_id.in_(scenario_ids),
            )
        )

        rows = base_query.all()

        os_kinds = set()
        os_major_vers = set()
        hw_profiles = {}
        for trt, server, hw in rows:
            if trt.os_kind:
                os_kinds.add(trt.os_kind)
            if trt.initial_os_major_ver:
                os_major_vers.add(trt.initial_os_major_ver)
            hw_profiles[hw.id] = hw.name

        # Load profiles used in completed test runs for this agent
        lp_query = (
            session.query(LoadProfileORM)
            .join(TestRunLoadProfileORM, TestRunLoadProfileORM.load_profile_id == LoadProfileORM.id)
            .join(TestRunORM, TestRunORM.id == TestRunLoadProfileORM.test_run_id)
            .filter(
                TestRunORM.state == TestRunState.completed,
                TestRunORM.scenario_id.in_(scenario_ids),
            )
            .distinct()
        )

        load_profiles = {lp.id: lp.name for lp in lp_query.all()}

        return {
            "os_kinds": sorted(os_kinds),
            "os_major_vers": sorted(os_major_vers),
            "hardware_profiles": [
                {"id": k, "name": v} for k, v in sorted(hw_profiles.items())
            ],
            "load_profiles": [
                {"id": k, "name": v} for k, v in sorted(load_profiles.items())
            ],
        }

    @staticmethod
    def _build_metric_path(metric: str, statistic: str) -> str:
        """Build the dotted JSONB path for a metric value."""
        if metric.endswith("_ratio"):
            # e.g. "agent_cpu_percent_ratio" -> normalized_ratios.agent_cpu_percent.ratios.avg
            base_metric = metric[:-6]  # strip "_ratio"
            return f"normalized_ratios.{base_metric}.ratios.{statistic}"
        elif metric.startswith("agent_") or metric == "process_count":
            return f"agent_overhead.{metric}.{statistic}"
        else:
            return f"system_deltas.{metric}.delta_pct.{statistic}"

    @staticmethod
    def _build_base_value_path(metric: str, statistic: str) -> Optional[str]:
        """Build the dotted JSONB path for the base (denominator) value of a ratio metric."""
        if not metric.endswith("_ratio"):
            return None
        base_metric = metric[:-6]
        return f"normalized_ratios.{base_metric}.base_values.{statistic}"

    @staticmethod
    def _extract_agent_version(
        agent_versions: Optional[List[Dict[str, Any]]], agent_id: int
    ) -> Optional[str]:
        """Extract discovered version for a specific agent from agent_versions JSONB."""
        if not agent_versions:
            return None
        for entry in agent_versions:
            if entry.get("agent_id") == agent_id:
                return entry.get("discovered_version")
        return None
