"""CPU Emulator server for E2E testing.

Simulates CPU load generation on target servers.
Provides REST API for controlling load and health checks.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="CPU Emulator", version="1.0.0")

# Global state
@dataclass
class EmulatorState:
    is_running: bool = False
    thread_count: int = 0
    start_time: Optional[float] = None
    cpu_usage_percent: float = 0.0
    iteration_times_ms: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None


state = EmulatorState()


class StartRequest(BaseModel):
    thread_count: int
    duration_sec: int = 0  # 0 means run until stopped


class EmulatorStatus(BaseModel):
    is_running: bool
    thread_count: int
    uptime_sec: float
    cpu_usage_percent: float
    avg_iteration_time_ms: float
    iteration_count: int


class CalibrationResponse(BaseModel):
    thread_count: int
    cpu_percent: float
    avg_iteration_time_ms: float
    stddev_iteration_time_ms: float
    min_iteration_time_ms: float
    max_iteration_time_ms: float
    sample_count: int


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "emulator_id": os.getenv("EMULATOR_ID", "1")}


@app.get("/status", response_model=EmulatorStatus)
async def get_status():
    """Get current emulator status."""
    uptime = 0.0
    if state.start_time:
        uptime = time.time() - state.start_time

    avg_iteration = 0.0
    if state.iteration_times_ms:
        avg_iteration = sum(state.iteration_times_ms) / len(state.iteration_times_ms)

    return EmulatorStatus(
        is_running=state.is_running,
        thread_count=state.thread_count,
        uptime_sec=uptime,
        cpu_usage_percent=state.cpu_usage_percent,
        avg_iteration_time_ms=avg_iteration,
        iteration_count=len(state.iteration_times_ms),
    )


@app.post("/start")
async def start_emulator(request: StartRequest):
    """Start CPU load emulation."""
    if state.is_running:
        raise HTTPException(status_code=400, detail="Emulator already running")

    state.is_running = True
    state.thread_count = request.thread_count
    state.start_time = time.time()
    state.iteration_times_ms = []

    # Simulate CPU usage based on thread count
    # ~5% CPU per thread (for testing purposes)
    state.cpu_usage_percent = min(request.thread_count * 5.0, 100.0)

    # Start background task for load simulation
    state.task = asyncio.create_task(
        _simulate_load(request.thread_count, request.duration_sec)
    )

    return {
        "status": "started",
        "thread_count": request.thread_count,
        "estimated_cpu_percent": state.cpu_usage_percent,
    }


@app.post("/stop")
async def stop_emulator():
    """Stop CPU load emulation."""
    if not state.is_running:
        raise HTTPException(status_code=400, detail="Emulator not running")

    state.is_running = False

    if state.task:
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

    return {"status": "stopped", "iterations_completed": len(state.iteration_times_ms)}


@app.get("/calibration", response_model=CalibrationResponse)
async def get_calibration():
    """Get calibration data from current or last run."""
    if not state.iteration_times_ms:
        raise HTTPException(status_code=400, detail="No calibration data available")

    times = state.iteration_times_ms
    avg_time = sum(times) / len(times)
    variance = sum((t - avg_time) ** 2 for t in times) / len(times)
    stddev = variance ** 0.5

    return CalibrationResponse(
        thread_count=state.thread_count,
        cpu_percent=state.cpu_usage_percent,
        avg_iteration_time_ms=avg_time,
        stddev_iteration_time_ms=stddev,
        min_iteration_time_ms=min(times),
        max_iteration_time_ms=max(times),
        sample_count=len(times),
    )


@app.post("/reset")
async def reset_emulator():
    """Reset emulator state (simulates container restart)."""
    if state.is_running:
        await stop_emulator()

    state.thread_count = 0
    state.start_time = None
    state.cpu_usage_percent = 0.0
    state.iteration_times_ms = []

    return {"status": "reset", "message": "Emulator state reset successfully"}


async def _simulate_load(thread_count: int, duration_sec: int):
    """Simulate CPU load by recording iteration times.

    For E2E testing, we simulate work iterations with realistic timing.
    """
    base_iteration_ms = 50.0  # Base iteration time
    variance_ms = 5.0  # Variance in iteration time

    end_time = None
    if duration_sec > 0:
        end_time = time.time() + duration_sec

    import random

    try:
        while state.is_running:
            if end_time and time.time() >= end_time:
                state.is_running = False
                break

            # Simulate work iteration with some variance
            iteration_time = base_iteration_ms + random.uniform(-variance_ms, variance_ms)
            state.iteration_times_ms.append(iteration_time)

            # Simulate thread work (scaled by thread count)
            work_time = (iteration_time / 1000.0) / thread_count
            await asyncio.sleep(max(work_time, 0.001))

            # Keep only last 1000 samples
            if len(state.iteration_times_ms) > 1000:
                state.iteration_times_ms = state.iteration_times_ms[-1000:]

    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    port = int(os.getenv("EMULATOR_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
