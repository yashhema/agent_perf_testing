"""Trending API router — cross-run trend data for agent performance."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from orchestrator.api.schemas import TrendDataPoint, TrendFiltersResponse, TrendResponse
from orchestrator.models.database import get_session
from orchestrator.models.orm import AgentORM
from orchestrator.services.trending import TrendingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trending", tags=["trending"])

_trending_service = TrendingService()


@router.get("/agents/{agent_id}/trend", response_model=TrendResponse)
def get_agent_trend(
    agent_id: int,
    metric: str = Query(..., description="Metric name (e.g. agent_cpu_percent, agent_cpu_percent_ratio, cpu_percent)"),
    statistic: str = Query("avg", description="Statistic to extract (avg, p50, p90, p95, p99)"),
    os_kind: Optional[str] = Query(None, description="Filter by OS kind"),
    os_major_ver: Optional[str] = Query(None, description="Filter by OS major version"),
    hardware_profile_id: Optional[int] = Query(None, description="Filter by hardware profile"),
    load_profile_id: Optional[int] = Query(None, description="Filter by load profile"),
    limit: int = Query(50, ge=1, le=500, description="Max data points"),
    session: Session = Depends(get_session),
):
    """Get trend data for a specific agent and metric across test runs."""
    agent = session.get(AgentORM, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    data_points = _trending_service.query_trend(
        session=session,
        agent_id=agent_id,
        metric=metric,
        statistic=statistic,
        os_kind=os_kind,
        os_major_ver=os_major_ver,
        hardware_profile_id=hardware_profile_id,
        load_profile_id=load_profile_id,
        limit=limit,
    )

    filters_applied = {
        "os_kind": os_kind,
        "os_major_ver": os_major_ver,
        "hardware_profile_id": hardware_profile_id,
        "load_profile_id": load_profile_id,
    }

    return TrendResponse(
        agent_name=agent.name,
        metric=metric,
        statistic=statistic,
        data_points=[
            TrendDataPoint(
                test_run_id=p.test_run_id,
                agent_version=p.agent_version,
                os_kind=p.os_kind,
                os_major_ver=p.os_major_ver,
                os_minor_ver=p.os_minor_ver,
                hardware_profile_name=p.hardware_profile_name,
                load_profile_name=p.load_profile_name,
                value=p.value,
                is_ratio=p.is_ratio,
                base_value=p.base_value,
                run_date=p.run_date,
                verdict=p.verdict,
            )
            for p in data_points
        ],
        filters_applied=filters_applied,
    )


@router.get("/agents/{agent_id}/filters", response_model=TrendFiltersResponse)
def get_agent_filters(
    agent_id: int,
    session: Session = Depends(get_session),
):
    """Get available filter values for an agent's trend queries."""
    agent = session.get(AgentORM, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    filters = _trending_service.get_available_filters(session, agent_id)

    return TrendFiltersResponse(
        os_kinds=filters["os_kinds"],
        os_major_vers=filters["os_major_vers"],
        hardware_profiles=filters["hardware_profiles"],
        load_profiles=filters["load_profiles"],
    )
