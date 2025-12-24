"""Load Generator server for E2E testing.

Simulates JMeter load generator functionality.
Provides REST API for controlling load tests.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Load Generator", version="1.0.0")


@dataclass
class LoadTestState:
    is_running: bool = False
    target_host: str = ""
    target_port: int = 8080
    thread_count: int = 0
    duration_sec: int = 0
    start_time: Optional[float] = None
    request_count: int = 0
    error_count: int = 0
    response_times_ms: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None


# Track multiple load tests by JMeter port
load_tests: Dict[int, LoadTestState] = {}


class StartLoadTestRequest(BaseModel):
    target_host: str
    target_port: int = 8080
    jmeter_port: int
    thread_count: int
    duration_sec: int
    warmup_sec: int = 10


class LoadTestStatus(BaseModel):
    is_running: bool
    target_host: str
    jmeter_port: int
    thread_count: int
    uptime_sec: float
    request_count: int
    error_count: int
    avg_response_time_ms: float
    throughput_per_sec: float


class LoadTestResult(BaseModel):
    jmeter_port: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    throughput_per_sec: float
    duration_sec: float


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "loadgen_id": os.getenv("LOADGEN_ID", "1")}


@app.get("/status/{jmeter_port}", response_model=LoadTestStatus)
async def get_load_test_status(jmeter_port: int):
    """Get status of a specific load test."""
    if jmeter_port not in load_tests:
        raise HTTPException(status_code=404, detail="Load test not found")

    state = load_tests[jmeter_port]
    uptime = 0.0
    if state.start_time:
        uptime = time.time() - state.start_time

    avg_response = 0.0
    if state.response_times_ms:
        avg_response = sum(state.response_times_ms) / len(state.response_times_ms)

    throughput = 0.0
    if uptime > 0:
        throughput = state.request_count / uptime

    return LoadTestStatus(
        is_running=state.is_running,
        target_host=state.target_host,
        jmeter_port=jmeter_port,
        thread_count=state.thread_count,
        uptime_sec=uptime,
        request_count=state.request_count,
        error_count=state.error_count,
        avg_response_time_ms=avg_response,
        throughput_per_sec=throughput,
    )


@app.get("/status")
async def get_all_load_tests():
    """Get status of all load tests."""
    results = []
    for jmeter_port in load_tests:
        try:
            status = await get_load_test_status(jmeter_port)
            results.append(status)
        except HTTPException:
            pass
    return {"load_tests": results}


@app.post("/start")
async def start_load_test(request: StartLoadTestRequest):
    """Start a load test against target."""
    if request.jmeter_port in load_tests and load_tests[request.jmeter_port].is_running:
        raise HTTPException(
            status_code=400,
            detail=f"Load test on port {request.jmeter_port} already running",
        )

    state = LoadTestState(
        is_running=True,
        target_host=request.target_host,
        target_port=request.target_port,
        thread_count=request.thread_count,
        duration_sec=request.duration_sec,
        start_time=time.time(),
    )
    load_tests[request.jmeter_port] = state

    # Start background task for load generation
    state.task = asyncio.create_task(
        _run_load_test(
            request.jmeter_port,
            request.target_host,
            request.target_port,
            request.thread_count,
            request.duration_sec,
            request.warmup_sec,
        )
    )

    return {
        "status": "started",
        "jmeter_port": request.jmeter_port,
        "target": f"{request.target_host}:{request.target_port}",
        "thread_count": request.thread_count,
        "duration_sec": request.duration_sec,
    }


@app.post("/stop/{jmeter_port}")
async def stop_load_test(jmeter_port: int):
    """Stop a specific load test."""
    if jmeter_port not in load_tests:
        raise HTTPException(status_code=404, detail="Load test not found")

    state = load_tests[jmeter_port]
    if not state.is_running:
        raise HTTPException(status_code=400, detail="Load test not running")

    state.is_running = False

    if state.task:
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

    return await _get_test_result(jmeter_port)


@app.get("/result/{jmeter_port}", response_model=LoadTestResult)
async def get_load_test_result(jmeter_port: int):
    """Get results of a completed load test."""
    return await _get_test_result(jmeter_port)


async def _get_test_result(jmeter_port: int) -> LoadTestResult:
    """Calculate and return test results."""
    if jmeter_port not in load_tests:
        raise HTTPException(status_code=404, detail="Load test not found")

    state = load_tests[jmeter_port]
    duration = 0.0
    if state.start_time:
        duration = time.time() - state.start_time

    times = state.response_times_ms or [0]
    avg_time = sum(times) / len(times) if times else 0.0

    throughput = state.request_count / duration if duration > 0 else 0.0

    return LoadTestResult(
        jmeter_port=jmeter_port,
        total_requests=state.request_count,
        successful_requests=state.request_count - state.error_count,
        failed_requests=state.error_count,
        avg_response_time_ms=avg_time,
        min_response_time_ms=min(times) if times else 0.0,
        max_response_time_ms=max(times) if times else 0.0,
        throughput_per_sec=throughput,
        duration_sec=duration,
    )


@app.delete("/test/{jmeter_port}")
async def cleanup_load_test(jmeter_port: int):
    """Cleanup a load test entry."""
    if jmeter_port in load_tests:
        state = load_tests[jmeter_port]
        if state.is_running:
            await stop_load_test(jmeter_port)
        del load_tests[jmeter_port]
    return {"status": "cleaned", "jmeter_port": jmeter_port}


async def _run_load_test(
    jmeter_port: int,
    target_host: str,
    target_port: int,
    thread_count: int,
    duration_sec: int,
    warmup_sec: int,
):
    """Run the actual load test simulation.

    For E2E testing, we simulate HTTP requests to the emulator.
    """
    state = load_tests[jmeter_port]
    end_time = time.time() + warmup_sec + duration_sec

    # Calculate delay between requests based on thread count
    # More threads = more requests per second
    request_delay = max(0.1 / thread_count, 0.01)

    async with httpx.AsyncClient() as client:
        while state.is_running and time.time() < end_time:
            try:
                start = time.time()
                response = await client.get(
                    f"http://{target_host}:{target_port}/status",
                    timeout=5.0,
                )
                elapsed_ms = (time.time() - start) * 1000

                state.request_count += 1
                state.response_times_ms.append(elapsed_ms)

                # Keep only last 10000 samples
                if len(state.response_times_ms) > 10000:
                    state.response_times_ms = state.response_times_ms[-10000:]

                if response.status_code != 200:
                    state.error_count += 1

            except Exception:
                state.request_count += 1
                state.error_count += 1

            await asyncio.sleep(request_delay)

    state.is_running = False


if __name__ == "__main__":
    port = int(os.getenv("LOADGEN_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port)
