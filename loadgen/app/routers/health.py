"""Health check router."""

from fastapi import APIRouter

from ..models.responses import HealthResponse
from ..jmeter.manager import get_jmeter_manager


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health."""
    manager = get_jmeter_manager()

    return HealthResponse(
        status="healthy",
        service="loadgen",
        version="1.0.0",
        jmeter_available=manager.is_jmeter_available(),
        jmeter_version=manager.get_jmeter_version(),
    )
