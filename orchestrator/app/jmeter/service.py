"""JMeter execution service."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Callable, Awaitable

from app.jmeter.models import (
    JMeterConfig,
    JMeterExecutionResult,
    JMeterProgress,
    JMeterStatus,
)
from app.results.models import JMeterResult


logger = logging.getLogger(__name__)


class RemoteExecutor(Protocol):
    """Protocol for remote command execution."""

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command and return (exit_code, stdout, stderr)."""
        ...

    async def execute_background(
        self,
        command: str,
    ) -> str:
        """Execute command in background, return process ID."""
        ...

    async def check_process(
        self,
        process_id: str,
    ) -> bool:
        """Check if process is still running."""
        ...

    async def kill_process(
        self,
        process_id: str,
    ) -> bool:
        """Kill a background process."""
        ...

    async def read_file(
        self,
        file_path: str,
    ) -> Optional[str]:
        """Read file contents."""
        ...

    async def file_exists(
        self,
        file_path: str,
    ) -> bool:
        """Check if file exists."""
        ...

    async def get_file_size(
        self,
        file_path: str,
    ) -> int:
        """Get file size in bytes."""
        ...


@dataclass
class JMeterExecution:
    """Tracks a running JMeter execution."""

    config: JMeterConfig
    process_id: str
    started_at: datetime
    warmup_end_time: datetime
    expected_end_time: datetime

    # Callbacks
    progress_callback: Optional[Callable[[JMeterProgress], Awaitable[None]]] = None

    # State
    cancelled: bool = False


class JMeterService:
    """
    Service for managing JMeter load test execution.

    Handles:
    - Starting JMeter on load generator machine
    - Monitoring execution progress
    - Collecting results when complete
    - Cancellation
    """

    def __init__(
        self,
        executor: RemoteExecutor,
        progress_interval_sec: int = 10,
    ):
        self.executor = executor
        self.progress_interval_sec = progress_interval_sec
        self._active_execution: Optional[JMeterExecution] = None

    async def start_load_test(
        self,
        config: JMeterConfig,
        progress_callback: Optional[Callable[[JMeterProgress], Awaitable[None]]] = None,
    ) -> JMeterExecutionResult:
        """
        Start JMeter load test and wait for completion.

        Args:
            config: JMeter configuration
            progress_callback: Optional callback for progress updates

        Returns:
            JMeterExecutionResult with outcome
        """
        started_at = datetime.utcnow()
        command = config.build_command()

        result = JMeterExecutionResult(
            status=JMeterStatus.STARTING,
            config=config,
            started_at=started_at,
            command_used=command,
            result_file_path=config.result_file_path,
        )

        logger.info(f"Starting JMeter load test: {command}")

        try:
            # Calculate end times
            warmup_end = started_at.timestamp() + config.warmup_sec
            expected_end = started_at.timestamp() + config.total_duration_sec

            # Start JMeter in background
            process_id = await self.executor.execute_background(command)

            # Track execution
            execution = JMeterExecution(
                config=config,
                process_id=process_id,
                started_at=started_at,
                warmup_end_time=datetime.fromtimestamp(warmup_end),
                expected_end_time=datetime.fromtimestamp(expected_end),
                progress_callback=progress_callback,
            )
            self._active_execution = execution

            # Monitor until completion
            result = await self._monitor_execution(execution, result)

        except asyncio.CancelledError:
            result.status = JMeterStatus.CANCELLED
            result.error_message = "Execution cancelled"
            if self._active_execution:
                await self._cleanup_execution(self._active_execution)

        except Exception as e:
            logger.error(f"JMeter execution failed: {e}")
            result.status = JMeterStatus.FAILED
            result.error_message = str(e)
            result.error_type = type(e).__name__

        finally:
            result.completed_at = datetime.utcnow()
            if result.started_at:
                result.duration_sec = (
                    result.completed_at - result.started_at
                ).total_seconds()
            self._active_execution = None

        return result

    async def _monitor_execution(
        self,
        execution: JMeterExecution,
        result: JMeterExecutionResult,
    ) -> JMeterExecutionResult:
        """Monitor JMeter execution until completion."""
        config = execution.config

        while not execution.cancelled:
            # Check if process is still running
            is_running = await self.executor.check_process(execution.process_id)

            if not is_running:
                # Process completed
                result.status = JMeterStatus.COMPLETED
                break

            # Calculate progress
            now = datetime.utcnow()
            elapsed = (now - execution.started_at).total_seconds()

            if elapsed < config.warmup_sec:
                status = JMeterStatus.WARMUP
            else:
                status = JMeterStatus.RUNNING

            progress = JMeterProgress(
                status=status,
                elapsed_sec=elapsed,
                total_sec=config.total_duration_sec,
                progress_percent=min(100, (elapsed / config.total_duration_sec) * 100),
            )

            # Call progress callback
            if execution.progress_callback:
                await execution.progress_callback(progress)

            # Check for timeout
            if elapsed > config.total_duration_sec + 60:  # 60s grace period
                logger.warning("JMeter execution exceeded timeout, killing process")
                await self.executor.kill_process(execution.process_id)
                result.status = JMeterStatus.TIMEOUT
                result.error_message = "Execution exceeded timeout"
                break

            # Wait before next check
            await asyncio.sleep(self.progress_interval_sec)

        # Check result file
        result.result_file_exists = await self.executor.file_exists(
            config.result_file_path
        )
        if result.result_file_exists:
            result.result_file_size_bytes = await self.executor.get_file_size(
                config.result_file_path
            )

        return result

    async def _cleanup_execution(self, execution: JMeterExecution) -> None:
        """Clean up after cancelled execution."""
        try:
            await self.executor.kill_process(execution.process_id)
        except Exception as e:
            logger.warning(f"Failed to kill JMeter process: {e}")

    async def cancel(self) -> bool:
        """Cancel the current execution."""
        if not self._active_execution:
            return False

        self._active_execution.cancelled = True
        await self._cleanup_execution(self._active_execution)
        return True

    async def collect_results(
        self,
        config: JMeterConfig,
    ) -> Optional[JMeterResult]:
        """
        Collect JMeter results from result file.

        Args:
            config: JMeter configuration with result file path

        Returns:
            JMeterResult or None if collection failed
        """
        try:
            # Read JTL file
            jtl_content = await self.executor.read_file(config.result_file_path)

            if not jtl_content:
                return JMeterResult(
                    success=False,
                    error_message="JTL file not found or empty",
                )

            # Parse JTL and calculate metrics
            metrics = self._parse_jtl(jtl_content)

            return JMeterResult(
                success=True,
                thread_count=config.thread_count,
                warmup_sec=config.warmup_sec,
                measured_sec=config.measured_sec,
                total_requests=metrics.get("total_requests", 0),
                successful_requests=metrics.get("successful_requests", 0),
                failed_requests=metrics.get("failed_requests", 0),
                avg_response_time_ms=metrics.get("avg_response_time_ms"),
                min_response_time_ms=metrics.get("min_response_time_ms"),
                max_response_time_ms=metrics.get("max_response_time_ms"),
                p50_response_time_ms=metrics.get("p50_response_time_ms"),
                p90_response_time_ms=metrics.get("p90_response_time_ms"),
                p95_response_time_ms=metrics.get("p95_response_time_ms"),
                p99_response_time_ms=metrics.get("p99_response_time_ms"),
                stddev_response_time_ms=metrics.get("stddev_response_time_ms"),
                throughput_rps=metrics.get("throughput_rps"),
                error_counts=metrics.get("error_counts"),
                jtl_file_path=config.result_file_path,
            )

        except Exception as e:
            logger.error(f"Failed to collect JMeter results: {e}")
            return JMeterResult(
                success=False,
                error_message=f"Failed to collect results: {e}",
            )

    def _parse_jtl(self, jtl_content: str) -> dict:
        """
        Parse JMeter JTL file and calculate metrics.

        JTL format (CSV):
        timeStamp,elapsed,label,responseCode,responseMessage,threadName,
        dataType,success,failureMessage,bytes,sentBytes,grpThreads,
        allThreads,URL,Latency,IdleTime,Connect
        """
        import statistics

        lines = jtl_content.strip().split('\n')
        if len(lines) < 2:
            return {}

        # Skip header
        data_lines = lines[1:]

        response_times = []
        success_count = 0
        fail_count = 0
        error_counts: dict[str, int] = {}
        first_timestamp = None
        last_timestamp = None

        for line in data_lines:
            try:
                fields = line.split(',')
                if len(fields) < 8:
                    continue

                timestamp = int(fields[0])
                elapsed = int(fields[1])
                response_code = fields[3]
                success = fields[7].lower() == 'true'

                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

                response_times.append(elapsed)

                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    error_key = response_code or "unknown"
                    error_counts[error_key] = error_counts.get(error_key, 0) + 1

            except (ValueError, IndexError):
                continue

        if not response_times:
            return {}

        # Calculate metrics
        sorted_times = sorted(response_times)
        total = len(response_times)

        duration_ms = (last_timestamp - first_timestamp) if first_timestamp and last_timestamp else 0
        duration_sec = duration_ms / 1000.0 if duration_ms else 1

        return {
            "total_requests": total,
            "successful_requests": success_count,
            "failed_requests": fail_count,
            "avg_response_time_ms": statistics.mean(response_times),
            "min_response_time_ms": min(response_times),
            "max_response_time_ms": max(response_times),
            "p50_response_time_ms": sorted_times[int(total * 0.50)],
            "p90_response_time_ms": sorted_times[int(total * 0.90)],
            "p95_response_time_ms": sorted_times[int(total * 0.95)],
            "p99_response_time_ms": sorted_times[int(total * 0.99)] if total >= 100 else sorted_times[-1],
            "stddev_response_time_ms": statistics.stdev(response_times) if total > 1 else 0,
            "throughput_rps": total / duration_sec if duration_sec > 0 else 0,
            "error_counts": error_counts if error_counts else None,
        }

    async def run_and_collect(
        self,
        config: JMeterConfig,
        progress_callback: Optional[Callable[[JMeterProgress], Awaitable[None]]] = None,
    ) -> tuple[JMeterExecutionResult, Optional[JMeterResult]]:
        """
        Run JMeter load test and collect results.

        Convenience method that combines start_load_test and collect_results.

        Args:
            config: JMeter configuration
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (execution_result, jmeter_result)
        """
        # Run load test
        execution_result = await self.start_load_test(
            config=config,
            progress_callback=progress_callback,
        )

        # Collect results if execution was successful
        jmeter_result = None
        if execution_result.success:
            jmeter_result = await self.collect_results(config)

        return execution_result, jmeter_result
