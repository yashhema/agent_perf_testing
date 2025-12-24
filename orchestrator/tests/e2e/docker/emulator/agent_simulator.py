"""Agent Simulator for E2E testing.

Simulates a security agent package that:
1. Gets "installed" (writes a version file)
2. Generates random CPU load (simulating agent work)
3. Can be verified (returns version from file)
4. Can be measured (provides load metrics)

This script runs inside the emulator container and simulates
what a real agent would do during performance testing.
"""

import asyncio
import os
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Agent simulation app
agent_app = FastAPI(title="Agent Simulator", version="1.0.0")


# ============================================================================
# Configuration
# ============================================================================

AGENT_INSTALL_DIR = Path("/opt/test-agent")
AGENT_VERSION_FILE = AGENT_INSTALL_DIR / "version.txt"
AGENT_STATS_FILE = AGENT_INSTALL_DIR / "stats.json"
AGENT_LOG_FILE = AGENT_INSTALL_DIR / "agent.log"


# ============================================================================
# State
# ============================================================================

@dataclass
class AgentState:
    """State of the simulated agent."""

    is_installed: bool = False
    is_running: bool = False
    version: str = ""
    install_timestamp: Optional[str] = None

    # Load simulation
    thread_count: int = 0
    cpu_target_percent: float = 0.0

    # Metrics
    iterations_completed: int = 0
    iteration_times_ms: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # Background task
    task: Optional[asyncio.Task] = None


state = AgentState()


# ============================================================================
# Request/Response Models
# ============================================================================

class InstallRequest(BaseModel):
    """Agent installation request."""
    version: str = "1.0.0"
    agent_id: int = 1
    agent_name: str = "TestAgent"


class InstallResponse(BaseModel):
    """Agent installation response."""
    success: bool
    version: str
    install_path: str
    message: str


class VerifyResponse(BaseModel):
    """Version verification response."""
    is_installed: bool
    version: str
    install_path: str
    install_timestamp: Optional[str]


class StartAgentRequest(BaseModel):
    """Start agent load simulation."""
    thread_count: int = 4
    cpu_target_percent: float = 30.0
    duration_sec: int = 0  # 0 = run until stopped


class AgentStatus(BaseModel):
    """Agent status response."""
    is_installed: bool
    is_running: bool
    version: str
    uptime_sec: float
    iterations_completed: int
    avg_iteration_time_ms: float
    cpu_load_percent: float


class AgentMetrics(BaseModel):
    """Agent performance metrics."""
    total_iterations: int
    avg_iteration_time_ms: float
    min_iteration_time_ms: float
    max_iteration_time_ms: float
    stddev_iteration_time_ms: float
    p50_iteration_time_ms: float
    p90_iteration_time_ms: float
    p99_iteration_time_ms: float
    error_count: int


# ============================================================================
# Endpoints
# ============================================================================

@agent_app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "agent_installed": state.is_installed,
        "agent_version": state.version,
    }


@agent_app.post("/install", response_model=InstallResponse)
async def install_agent(request: InstallRequest):
    """
    Simulate agent installation.

    Creates version file and initializes agent state.
    """
    try:
        # Create install directory
        AGENT_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

        # Write version file
        install_info = {
            "version": request.version,
            "agent_id": request.agent_id,
            "agent_name": request.agent_name,
            "installed_at": datetime.utcnow().isoformat(),
            "install_id": str(uuid4()),
        }

        with open(AGENT_VERSION_FILE, "w") as f:
            json.dump(install_info, f, indent=2)

        # Update state
        state.is_installed = True
        state.version = request.version
        state.install_timestamp = install_info["installed_at"]

        # Log installation
        _log(f"Agent {request.agent_name} v{request.version} installed")

        return InstallResponse(
            success=True,
            version=request.version,
            install_path=str(AGENT_INSTALL_DIR),
            message="Agent installed successfully",
        )

    except Exception as e:
        return InstallResponse(
            success=False,
            version=request.version,
            install_path=str(AGENT_INSTALL_DIR),
            message=f"Installation failed: {e}",
        )


@agent_app.post("/uninstall")
async def uninstall_agent():
    """
    Simulate agent uninstallation.

    Removes version file and stops agent.
    """
    if state.is_running:
        await stop_agent()

    try:
        if AGENT_VERSION_FILE.exists():
            AGENT_VERSION_FILE.unlink()
        if AGENT_STATS_FILE.exists():
            AGENT_STATS_FILE.unlink()

        state.is_installed = False
        state.version = ""
        state.install_timestamp = None

        _log("Agent uninstalled")

        return {"success": True, "message": "Agent uninstalled"}

    except Exception as e:
        return {"success": False, "message": f"Uninstall failed: {e}"}


@agent_app.get("/verify", response_model=VerifyResponse)
async def verify_agent():
    """
    Verify agent installation.

    Reads version file and returns installed version.
    This simulates the version_check_command.
    """
    if not AGENT_VERSION_FILE.exists():
        return VerifyResponse(
            is_installed=False,
            version="",
            install_path=str(AGENT_INSTALL_DIR),
            install_timestamp=None,
        )

    try:
        with open(AGENT_VERSION_FILE, "r") as f:
            info = json.load(f)

        return VerifyResponse(
            is_installed=True,
            version=info["version"],
            install_path=str(AGENT_INSTALL_DIR),
            install_timestamp=info.get("installed_at"),
        )

    except Exception:
        return VerifyResponse(
            is_installed=False,
            version="",
            install_path=str(AGENT_INSTALL_DIR),
            install_timestamp=None,
        )


@agent_app.post("/start")
async def start_agent(request: StartAgentRequest):
    """
    Start agent load simulation.

    Generates random CPU load to simulate agent activity.
    """
    if not state.is_installed:
        raise HTTPException(status_code=400, detail="Agent not installed")

    if state.is_running:
        raise HTTPException(status_code=400, detail="Agent already running")

    state.is_running = True
    state.thread_count = request.thread_count
    state.cpu_target_percent = request.cpu_target_percent
    state.iterations_completed = 0
    state.iteration_times_ms = []
    state.errors = []

    # Start background load simulation
    state.task = asyncio.create_task(
        _simulate_agent_work(
            request.thread_count,
            request.cpu_target_percent,
            request.duration_sec,
        )
    )

    _log(f"Agent started: {request.thread_count} threads, {request.cpu_target_percent}% CPU target")

    return {
        "status": "started",
        "thread_count": request.thread_count,
        "cpu_target_percent": request.cpu_target_percent,
    }


@agent_app.post("/stop")
async def stop_agent():
    """Stop agent load simulation."""
    if not state.is_running:
        raise HTTPException(status_code=400, detail="Agent not running")

    state.is_running = False

    if state.task:
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

    _log(f"Agent stopped: {state.iterations_completed} iterations completed")

    return {
        "status": "stopped",
        "iterations_completed": state.iterations_completed,
    }


@agent_app.get("/status", response_model=AgentStatus)
async def get_status():
    """Get agent status."""
    avg_time = 0.0
    if state.iteration_times_ms:
        avg_time = sum(state.iteration_times_ms) / len(state.iteration_times_ms)

    return AgentStatus(
        is_installed=state.is_installed,
        is_running=state.is_running,
        version=state.version,
        uptime_sec=0,  # Would calculate from start time
        iterations_completed=state.iterations_completed,
        avg_iteration_time_ms=avg_time,
        cpu_load_percent=state.cpu_target_percent if state.is_running else 0,
    )


@agent_app.get("/metrics", response_model=AgentMetrics)
async def get_metrics():
    """Get agent performance metrics."""
    if not state.iteration_times_ms:
        raise HTTPException(status_code=400, detail="No metrics available")

    times = sorted(state.iteration_times_ms)
    n = len(times)
    avg = sum(times) / n
    variance = sum((t - avg) ** 2 for t in times) / n
    stddev = variance ** 0.5

    return AgentMetrics(
        total_iterations=state.iterations_completed,
        avg_iteration_time_ms=avg,
        min_iteration_time_ms=min(times),
        max_iteration_time_ms=max(times),
        stddev_iteration_time_ms=stddev,
        p50_iteration_time_ms=times[int(n * 0.50)],
        p90_iteration_time_ms=times[int(n * 0.90)],
        p99_iteration_time_ms=times[int(n * 0.99)] if n >= 100 else times[-1],
        error_count=len(state.errors),
    )


@agent_app.post("/reset")
async def reset_agent():
    """
    Reset agent state.

    Simulates container restart - clears all state but preserves installation.
    """
    if state.is_running:
        await stop_agent()

    state.iterations_completed = 0
    state.iteration_times_ms = []
    state.errors = []

    _log("Agent state reset")

    return {"status": "reset"}


# ============================================================================
# Background Work Simulation
# ============================================================================

async def _simulate_agent_work(
    thread_count: int,
    cpu_target_percent: float,
    duration_sec: int,
):
    """
    Simulate agent work that consumes CPU.

    Generates random iteration times based on CPU target.
    Higher CPU target = shorter iteration times = more work.
    """
    # Base iteration time scales with CPU target
    # Higher CPU = faster iterations
    base_iteration_ms = 100 - (cpu_target_percent * 0.8)  # 20-100ms
    variance_ms = base_iteration_ms * 0.1  # 10% variance

    end_time = None
    if duration_sec > 0:
        end_time = time.time() + duration_sec

    try:
        while state.is_running:
            if end_time and time.time() >= end_time:
                state.is_running = False
                break

            # Simulate work iteration
            iteration_time = base_iteration_ms + random.uniform(-variance_ms, variance_ms)

            # Simulate actual work (busy wait scaled by thread count)
            work_duration = (iteration_time / 1000.0) / max(thread_count, 1)
            await asyncio.sleep(max(work_duration, 0.001))

            # Record metrics
            state.iterations_completed += 1
            state.iteration_times_ms.append(iteration_time)

            # Keep only last 10000 samples
            if len(state.iteration_times_ms) > 10000:
                state.iteration_times_ms = state.iteration_times_ms[-10000:]

            # Occasionally add random errors (1% chance)
            if random.random() < 0.01:
                state.errors.append(f"Simulated error at iteration {state.iterations_completed}")

    except asyncio.CancelledError:
        pass


def _log(message: str):
    """Log message to agent log file."""
    try:
        AGENT_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        with open(AGENT_LOG_FILE, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"{timestamp} - {message}\n")
    except Exception:
        pass


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("AGENT_PORT", "8085"))
    uvicorn.run(agent_app, host="0.0.0.0", port=port)
