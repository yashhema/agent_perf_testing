"""Health check router."""

from fastapi import APIRouter

from ..models.responses import HealthResponse
from ..state import get_uptime


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health."""
    return HealthResponse(
        status="healthy",
        service="emulator",
        version="1.0.0",
        uptime_sec=get_uptime(),
    )
