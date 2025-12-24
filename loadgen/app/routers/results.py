"""Results router for JTL parsing and analysis."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException

from ..models.responses import JTLSummaryResponse, OperationStatsResponse
from ..jmeter.manager import get_jmeter_manager
from ..jmeter.result_parser import JTLParser


router = APIRouter(prefix="/results")


@router.get("/{target_id}", response_model=JTLSummaryResponse)
async def get_results(target_id: int) -> JTLSummaryResponse:
    """Get results for a target's JMeter test."""
    manager = get_jmeter_manager()

    process = manager.get_status(target_id)

    if not process:
        raise HTTPException(
            status_code=404,
            detail=f"No JMeter process for target {target_id}",
        )

    if not process.jtl_file or not os.path.exists(process.jtl_file):
        raise HTTPException(
            status_code=404,
            detail="JTL results file not found",
        )

    summary = JTLParser.parse_jtl_to_summary(process.jtl_file)

    return JTLSummaryResponse(
        target_id=target_id,
        test_run_id=process.config.test_run_id,
        total_samples=summary.total_samples,
        success_count=summary.success_count,
        failure_count=summary.failure_count,
        error_rate=summary.error_rate,
        avg_response_time_ms=summary.avg_response_time_ms,
        duration_sec=summary.duration_sec,
        throughput=summary.throughput,
        per_operation=[
            OperationStatsResponse(
                operation=op.operation,
                count=op.count,
                success_count=op.success_count,
                failure_count=op.failure_count,
                error_rate=op.error_rate,
                avg_response_time_ms=op.avg_response_time_ms,
                min_response_time_ms=op.min_response_time_ms,
                max_response_time_ms=op.max_response_time_ms,
                p50_ms=op.p50_ms,
                p90_ms=op.p90_ms,
                p99_ms=op.p99_ms,
                throughput=op.throughput,
            )
            for op in summary.per_operation
        ],
    )


@router.get("/{target_id}/live")
async def get_live_results(target_id: int) -> dict:
    """Get live results (partial) for a running test."""
    manager = get_jmeter_manager()

    process = manager.get_status(target_id)

    if not process:
        raise HTTPException(
            status_code=404,
            detail=f"No JMeter process for target {target_id}",
        )

    if not process.jtl_file:
        return {
            "target_id": target_id,
            "status": process.status.value,
            "message": "No results file yet",
            "samples": 0,
        }

    if not os.path.exists(process.jtl_file):
        return {
            "target_id": target_id,
            "status": process.status.value,
            "message": "Results file not created yet",
            "samples": 0,
        }

    # Parse current results
    result = JTLParser.parse_jtl(process.jtl_file)

    if "error" in result and "summary" not in result:
        return {
            "target_id": target_id,
            "status": process.status.value,
            "message": result.get("error", "Error parsing results"),
            "samples": 0,
        }

    summary = result.get("summary", {})

    return {
        "target_id": target_id,
        "status": process.status.value,
        "elapsed_sec": process.elapsed_sec,
        "samples": summary.get("total_samples", 0),
        "success_count": summary.get("success_count", 0),
        "failure_count": summary.get("failure_count", 0),
        "error_rate": summary.get("error_rate", 0.0),
        "avg_response_time_ms": summary.get("avg_response_time_ms", 0.0),
        "throughput": summary.get("throughput", 0.0),
    }


@router.post("/parse")
async def parse_jtl_file(jtl_path: str) -> dict:
    """Parse an arbitrary JTL file."""
    if not os.path.exists(jtl_path):
        raise HTTPException(status_code=404, detail=f"File not found: {jtl_path}")

    result = JTLParser.parse_jtl(jtl_path)

    if "error" in result and "summary" not in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result
