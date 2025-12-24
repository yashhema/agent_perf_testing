"""JMeter management router."""

from typing import List

from fastapi import APIRouter, HTTPException

from ..models.requests import StartJMeterRequest, StopJMeterRequest
from ..models.responses import (
    StartJMeterResponse,
    StopJMeterResponse,
    JMeterStatusResponse,
    ListProcessesResponse,
)
from ..jmeter.manager import JMeterConfig, get_jmeter_manager


router = APIRouter(prefix="/jmeter")


@router.post("/start", response_model=StartJMeterResponse)
async def start_jmeter(request: StartJMeterRequest) -> StartJMeterResponse:
    """Start a JMeter test for a target."""
    manager = get_jmeter_manager()

    if not manager.is_jmeter_available():
        raise HTTPException(status_code=503, detail="JMeter is not available")

    try:
        # Allocate port if not specified
        port = manager._allocate_port(request.jmeter_port)

        config = JMeterConfig(
            target_id=request.target_id,
            test_run_id=request.test_run_id,
            jmx_file=request.jmx_file,
            thread_count=request.thread_count,
            ramp_up_sec=request.ramp_up_sec,
            loop_count=request.loop_count,
            duration_sec=request.duration_sec,
            emulator_host=request.emulator_host,
            emulator_port=request.emulator_port,
            jmeter_port=port,
            additional_props=request.additional_props,
        )

        process = await manager.start_jmeter(config)

        return StartJMeterResponse(
            success=True,
            message=f"JMeter started for target {request.target_id}",
            target_id=request.target_id,
            jmeter_port=port,
            pid=process.pid,
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop", response_model=StopJMeterResponse)
async def stop_jmeter(request: StopJMeterRequest) -> StopJMeterResponse:
    """Stop a JMeter test."""
    manager = get_jmeter_manager()

    success = await manager.stop_jmeter(request.target_id, force=request.force)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"No running JMeter process for target {request.target_id}",
        )

    return StopJMeterResponse(
        success=True,
        message=f"JMeter stopped for target {request.target_id}",
        target_id=request.target_id,
    )


@router.get("/status/{target_id}", response_model=JMeterStatusResponse)
async def get_jmeter_status(target_id: int) -> JMeterStatusResponse:
    """Get status of JMeter process for a target."""
    manager = get_jmeter_manager()

    process = manager.get_status(target_id)

    if not process:
        raise HTTPException(
            status_code=404,
            detail=f"No JMeter process for target {target_id}",
        )

    return JMeterStatusResponse(
        target_id=process.config.target_id,
        test_run_id=process.config.test_run_id,
        status=process.status.value,
        jmeter_port=process.config.jmeter_port,
        thread_count=process.config.thread_count,
        started_at=process.started_at,
        elapsed_sec=process.elapsed_sec,
        pid=process.pid,
    )


@router.get("/processes", response_model=ListProcessesResponse)
async def list_processes() -> ListProcessesResponse:
    """List all JMeter processes."""
    manager = get_jmeter_manager()

    processes = manager.get_all_processes()

    return ListProcessesResponse(
        processes=[
            JMeterStatusResponse(
                target_id=p.config.target_id,
                test_run_id=p.config.test_run_id,
                status=p.status.value,
                jmeter_port=p.config.jmeter_port,
                thread_count=p.config.thread_count,
                started_at=p.started_at,
                elapsed_sec=p.elapsed_sec,
                pid=p.pid,
            )
            for p in processes
        ]
    )


@router.get("/running", response_model=ListProcessesResponse)
async def list_running_processes() -> ListProcessesResponse:
    """List only running JMeter processes."""
    manager = get_jmeter_manager()

    processes = manager.get_running_processes()

    return ListProcessesResponse(
        processes=[
            JMeterStatusResponse(
                target_id=p.config.target_id,
                test_run_id=p.config.test_run_id,
                status=p.status.value,
                jmeter_port=p.config.jmeter_port,
                thread_count=p.config.thread_count,
                started_at=p.started_at,
                elapsed_sec=p.elapsed_sec,
                pid=p.pid,
            )
            for p in processes
        ]
    )


@router.post("/cleanup")
async def cleanup_completed() -> dict:
    """Clean up completed/stopped processes."""
    manager = get_jmeter_manager()

    count = manager.cleanup_completed()

    return {
        "success": True,
        "message": f"Cleaned up {count} completed processes",
        "count": count,
    }
