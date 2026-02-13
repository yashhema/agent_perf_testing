"""Execution coordinator for managing multiple parallel test executions."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable, Awaitable, Set

from .models import (
    ExecutionConfig,
    ExecutionEvent,
    ExecutionProgress,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    TargetInfo,
)
from .executor import TestExecutor


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchRequest:
    """Request to execute tests on multiple targets."""

    test_run_id: int
    baseline_id: int
    targets: List[TargetInfo]
    load_profile: str
    config: ExecutionConfig = field(default_factory=ExecutionConfig)


@dataclass(frozen=True)
class BatchProgress:
    """Progress of a batch execution."""

    test_run_id: int
    total_targets: int
    completed_targets: int
    failed_targets: int
    in_progress_targets: int
    pending_targets: int
    overall_progress_percent: float
    executions: List[ExecutionProgress]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class BatchResult:
    """Result of a batch execution."""

    test_run_id: int
    baseline_id: int
    load_profile: str
    started_at: datetime
    completed_at: datetime
    total_duration_sec: float
    total_targets: int
    successful_targets: int
    failed_targets: int
    cancelled_targets: int
    results: List[ExecutionResult]


class ExecutionCoordinator:
    """
    Coordinates execution of tests across multiple targets.

    Manages parallel execution with configurable concurrency limits.
    """

    def __init__(
        self,
        progress_callback: Optional[
            Callable[[BatchProgress], Awaitable[None]]
        ] = None,
        event_callback: Optional[Callable[[ExecutionEvent], Awaitable[None]]] = None,
    ):
        self._progress_callback = progress_callback
        self._event_callback = event_callback

        # Active executions
        self._executors: Dict[str, TestExecutor] = {}
        self._execution_progress: Dict[str, ExecutionProgress] = {}
        self._execution_results: Dict[str, ExecutionResult] = {}

        # State tracking
        self._active_batch: Optional[int] = None
        self._cancelled: bool = False
        self._lock = asyncio.Lock()

    @property
    def active_executions(self) -> Set[str]:
        """Get IDs of active executions."""
        return set(self._executors.keys())

    def get_execution_state(self, execution_id: str) -> Optional[ExecutionProgress]:
        """Get current state of an execution."""
        return self._execution_progress.get(execution_id)

    def get_execution_result(self, execution_id: str) -> Optional[ExecutionResult]:
        """Get result of a completed execution."""
        return self._execution_results.get(execution_id)

    async def execute_batch(self, request: BatchRequest) -> BatchResult:
        """
        Execute tests on all targets in the batch.

        Runs tests in parallel up to the configured concurrency limit.
        """
        async with self._lock:
            if self._active_batch is not None:
                raise RuntimeError(
                    f"Batch {self._active_batch} is already running"
                )
            self._active_batch = request.test_run_id
            self._cancelled = False

        started_at = datetime.utcnow()
        results: List[ExecutionResult] = []

        try:
            logger.info(
                f"Starting batch execution for test run {request.test_run_id} "
                f"with {len(request.targets)} targets"
            )

            # Create semaphore for concurrency control
            semaphore = asyncio.Semaphore(request.config.max_parallel_targets)

            # Create execution tasks
            tasks = []
            for target in request.targets:
                exec_request = ExecutionRequest(
                    test_run_id=request.test_run_id,
                    target_id=target.target_id,
                    baseline_id=request.baseline_id,
                    target_info=target,
                    load_profile=request.load_profile,
                    config=request.config,
                )
                task = self._execute_with_semaphore(
                    semaphore,
                    exec_request,
                    len(request.targets),
                )
                tasks.append(task)

            # Execute all tasks
            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in task_results:
                if isinstance(result, Exception):
                    logger.error(f"Execution failed with exception: {result}")
                    # Create a failed result for exceptions
                    # In a real implementation, we'd track which target failed
                else:
                    results.append(result)

            completed_at = datetime.utcnow()
            total_duration = (completed_at - started_at).total_seconds()

            # Calculate statistics
            successful = sum(
                1 for r in results if r.status == ExecutionStatus.COMPLETED
            )
            failed = sum(1 for r in results if r.status == ExecutionStatus.FAILED)
            cancelled = sum(
                1 for r in results if r.status == ExecutionStatus.CANCELLED
            )

            batch_result = BatchResult(
                test_run_id=request.test_run_id,
                baseline_id=request.baseline_id,
                load_profile=request.load_profile,
                started_at=started_at,
                completed_at=completed_at,
                total_duration_sec=total_duration,
                total_targets=len(request.targets),
                successful_targets=successful,
                failed_targets=failed,
                cancelled_targets=cancelled,
                results=results,
            )

            logger.info(
                f"Batch execution completed: {successful} successful, "
                f"{failed} failed, {cancelled} cancelled"
            )

            return batch_result

        finally:
            async with self._lock:
                self._active_batch = None
                self._executors.clear()

    async def _execute_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        request: ExecutionRequest,
        total_targets: int,
    ) -> ExecutionResult:
        """Execute a single target with semaphore control."""
        async with semaphore:
            if self._cancelled:
                # Return cancelled result
                return ExecutionResult(
                    execution_id="cancelled",
                    test_run_id=request.test_run_id,
                    target_id=request.target_id,
                    baseline_id=request.baseline_id,
                    status=ExecutionStatus.CANCELLED,
                    load_profile=request.load_profile,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    total_duration_sec=0.0,
                    thread_count=0,
                    target_cpu_percent=0.0,
                    achieved_cpu_percent=0.0,
                    error_message="Batch cancelled before execution",
                )

            executor = TestExecutor(
                request=request,
                progress_callback=self._on_execution_progress,
                event_callback=self._event_callback,
            )

            async with self._lock:
                self._executors[executor.execution_id] = executor

            try:
                result = await executor.execute()
                self._execution_results[executor.execution_id] = result

                # Update batch progress
                await self._report_batch_progress(
                    request.test_run_id,
                    total_targets,
                )

                return result

            finally:
                async with self._lock:
                    self._executors.pop(executor.execution_id, None)

    async def _on_execution_progress(self, progress: ExecutionProgress) -> None:
        """Handle progress update from an executor."""
        self._execution_progress[progress.execution_id] = progress

    async def _report_batch_progress(
        self,
        test_run_id: int,
        total_targets: int,
    ) -> None:
        """Report overall batch progress."""
        if not self._progress_callback:
            return

        completed = sum(
            1
            for r in self._execution_results.values()
            if r.status
            in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
            }
        )
        failed = sum(
            1
            for r in self._execution_results.values()
            if r.status == ExecutionStatus.FAILED
        )
        in_progress = len(self._executors)
        pending = total_targets - completed - in_progress

        overall_progress = (completed / total_targets) * 100 if total_targets > 0 else 0

        batch_progress = BatchProgress(
            test_run_id=test_run_id,
            total_targets=total_targets,
            completed_targets=completed,
            failed_targets=failed,
            in_progress_targets=in_progress,
            pending_targets=pending,
            overall_progress_percent=overall_progress,
            executions=list(self._execution_progress.values()),
        )

        await self._progress_callback(batch_progress)

    async def cancel_batch(self) -> None:
        """Cancel all running executions in the current batch."""
        async with self._lock:
            self._cancelled = True

            # Cancel all active executors
            for executor in self._executors.values():
                await executor.cancel()

        logger.info("Batch execution cancelled")

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a specific execution."""
        async with self._lock:
            executor = self._executors.get(execution_id)
            if executor:
                await executor.cancel()
                return True
            return False

    async def execute_single(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute a single target test.

        Convenience method for running a single test without batch context.
        """
        executor = TestExecutor(
            request=request,
            progress_callback=self._on_execution_progress,
            event_callback=self._event_callback,
        )

        async with self._lock:
            self._executors[executor.execution_id] = executor

        try:
            result = await executor.execute()
            self._execution_results[executor.execution_id] = result
            return result
        finally:
            async with self._lock:
                self._executors.pop(executor.execution_id, None)

    def get_batch_status(self) -> Optional[BatchProgress]:
        """Get current batch status."""
        if self._active_batch is None:
            return None

        total = len(self._execution_progress) + len(self._execution_results)
        if total == 0:
            return None

        completed = len(self._execution_results)
        in_progress = len(self._executors)
        failed = sum(
            1
            for r in self._execution_results.values()
            if r.status == ExecutionStatus.FAILED
        )

        return BatchProgress(
            test_run_id=self._active_batch,
            total_targets=total,
            completed_targets=completed,
            failed_targets=failed,
            in_progress_targets=in_progress,
            pending_targets=total - completed - in_progress,
            overall_progress_percent=(completed / total) * 100 if total > 0 else 0,
            executions=list(self._execution_progress.values()),
        )


class RetryCoordinator:
    """
    Handles retry logic for failed executions.

    Implements exponential backoff and configurable retry limits.
    """

    def __init__(
        self,
        coordinator: ExecutionCoordinator,
        max_retries: int = 3,
        base_delay_sec: int = 60,
        max_delay_sec: int = 600,
    ):
        self._coordinator = coordinator
        self._max_retries = max_retries
        self._base_delay_sec = base_delay_sec
        self._max_delay_sec = max_delay_sec
        self._retry_counts: Dict[int, int] = {}  # target_id -> retry_count

    def get_retry_delay(self, retry_count: int) -> int:
        """Calculate retry delay with exponential backoff."""
        delay = self._base_delay_sec * (2 ** retry_count)
        return min(delay, self._max_delay_sec)

    def should_retry(self, target_id: int) -> bool:
        """Check if target should be retried."""
        count = self._retry_counts.get(target_id, 0)
        return count < self._max_retries

    def record_retry(self, target_id: int) -> int:
        """Record a retry attempt and return new count."""
        count = self._retry_counts.get(target_id, 0) + 1
        self._retry_counts[target_id] = count
        return count

    def reset_retries(self, target_id: int) -> None:
        """Reset retry count for a target."""
        self._retry_counts.pop(target_id, None)

    async def retry_failed(
        self,
        batch_result: BatchResult,
    ) -> List[ExecutionResult]:
        """
        Retry all failed executions from a batch.

        Returns results of retry attempts.
        """
        failed_results = [
            r for r in batch_result.results if r.status == ExecutionStatus.FAILED
        ]

        if not failed_results:
            return []

        retry_results: List[ExecutionResult] = []

        for result in failed_results:
            if not self.should_retry(result.target_id):
                logger.warning(
                    f"Target {result.target_id} has exceeded max retries"
                )
                continue

            retry_count = self.record_retry(result.target_id)
            delay = self.get_retry_delay(retry_count - 1)

            logger.info(
                f"Retrying target {result.target_id} "
                f"(attempt {retry_count}/{self._max_retries}) "
                f"after {delay}s delay"
            )

            await asyncio.sleep(delay)

            # Find original target info - in real implementation
            # this would be retrieved from storage
            # For now, create a placeholder request
            request = ExecutionRequest(
                test_run_id=batch_result.test_run_id,
                target_id=result.target_id,
                baseline_id=batch_result.baseline_id,
                target_info=TargetInfo(
                    target_id=result.target_id,
                    hostname="unknown",
                    ip_address="unknown",
                    os_type="linux",
                    cpu_count=4,
                    memory_gb=8.0,
                ),
                load_profile=batch_result.load_profile,
            )

            retry_result = await self._coordinator.execute_single(request)
            retry_results.append(retry_result)

            if retry_result.status == ExecutionStatus.COMPLETED:
                self.reset_retries(result.target_id)

        return retry_results
