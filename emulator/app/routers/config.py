"""Configuration router for emulator settings."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_config_manager, EmulatorConfig
from ..stats.collector import get_stats_collector
from ..operations import mem_pool


router = APIRouter(prefix="/config")


class PartnerConfigRequest(BaseModel):
    """Partner configuration in request."""
    fqdn: str = Field(..., description="Partner hostname/FQDN")
    port: int = Field(default=8080, gt=0, le=65535, description="Partner port")


class StatsConfigRequest(BaseModel):
    """Stats configuration in request."""
    output_dir: str = Field(default="./stats", description="Directory for stats files")
    max_memory_samples: int = Field(default=10000, gt=0, description="Max samples in memory buffer")
    default_interval_sec: float = Field(default=1.0, gt=0, description="Default collection interval")
    service_monitor_patterns: List[str] = Field(
        default_factory=list,
        description="Regex patterns matching process names to monitor (e.g., ['^CrowdStrike.*', '^MsMpEng.*'])"
    )


class ConfigRequest(BaseModel):
    """Configuration request model."""
    output_folders: List[str] = Field(..., min_length=1, description="List of output folder paths")
    partner: PartnerConfigRequest = Field(..., description="Network partner configuration")
    stats: Optional[StatsConfigRequest] = Field(default=None, description="Stats collection configuration")


class ConfigResponse(BaseModel):
    """Configuration response model."""
    input_folders: dict
    output_folders: List[str]
    partner: dict
    stats: dict
    is_configured: bool


@router.get("", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Get current emulator configuration."""
    manager = get_config_manager()
    config = manager.config

    return ConfigResponse(
        input_folders={
            "normal": config.input_folders.normal,
            "confidential": config.input_folders.confidential,
        },
        output_folders=config.output_folders,
        partner={
            "fqdn": config.partner.fqdn,
            "port": config.partner.port,
        },
        stats={
            "output_dir": config.stats.output_dir,
            "max_memory_samples": config.stats.max_memory_samples,
            "default_interval_sec": config.stats.default_interval_sec,
            "service_monitor_patterns": config.stats.service_monitor_patterns,
        },
        is_configured=config.is_configured(),
    )


@router.post("", response_model=ConfigResponse)
async def set_config(request: ConfigRequest) -> ConfigResponse:
    """Set emulator configuration. Input folders are auto-detected from install path."""
    manager = get_config_manager()

    config_data = {
        "output_folders": request.output_folders,
        "partner": {
            "fqdn": request.partner.fqdn,
            "port": request.partner.port,
        },
    }

    # Include stats config if provided
    if request.stats:
        config_data["stats"] = {
            "output_dir": request.stats.output_dir,
            "max_memory_samples": request.stats.max_memory_samples,
            "default_interval_sec": request.stats.default_interval_sec,
            "service_monitor_patterns": request.stats.service_monitor_patterns,
        }

    config = manager.update_config(config_data)

    # Apply stats config to collector
    collector = get_stats_collector()
    collector.configure(
        output_dir=config.stats.output_dir,
        max_samples=config.stats.max_memory_samples,
        default_interval_sec=config.stats.default_interval_sec,
        service_monitor_patterns=config.stats.service_monitor_patterns,
    )

    return ConfigResponse(
        input_folders={
            "normal": config.input_folders.normal,
            "confidential": config.input_folders.confidential,
        },
        output_folders=config.output_folders,
        partner={
            "fqdn": config.partner.fqdn,
            "port": config.partner.port,
        },
        stats={
            "output_dir": config.stats.output_dir,
            "max_memory_samples": config.stats.max_memory_samples,
            "default_interval_sec": config.stats.default_interval_sec,
            "service_monitor_patterns": config.stats.service_monitor_patterns,
        },
        is_configured=config.is_configured(),
    )


# ── Memory pool management ─────────────────────────────────────────


class PoolRequest(BaseModel):
    """Request to allocate / resize the memory pool."""
    size_gb: float = Field(..., gt=0, le=64, description="Pool size in GB")


class PoolResponse(BaseModel):
    allocated: bool
    size_bytes: int


@router.post("/pool", response_model=PoolResponse)
async def init_memory_pool(request: PoolRequest) -> PoolResponse:
    """Allocate the shared memory pool and touch all pages.

    Call this once during setup, before sending /work requests.
    Safe to call again to resize.
    """
    size_bytes = mem_pool.init_pool(request.size_gb)
    return PoolResponse(allocated=True, size_bytes=size_bytes)


@router.get("/pool", response_model=PoolResponse)
async def get_pool_status() -> PoolResponse:
    """Check whether the memory pool is allocated."""
    return PoolResponse(
        allocated=mem_pool.pool_allocated(),
        size_bytes=mem_pool.pool_size_bytes(),
    )


@router.delete("/pool", response_model=PoolResponse)
async def destroy_memory_pool() -> PoolResponse:
    """Release the memory pool."""
    mem_pool.destroy_pool()
    return PoolResponse(allocated=False, size_bytes=0)
