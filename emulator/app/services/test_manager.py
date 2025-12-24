"""Test execution manager for running load tests."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor

from ..operations.cpu import CPUOperation, CPUOperationParams
from ..operations.memory import MEMOperation, MEMOperationParams
from ..operations.disk import DISKOperation, DISKOperationParams
from ..operations.network import NETOperation, NETOperationParams
from ..stats.collector import get_stats_collector


class TestStatus(str, Enum):
    """Test execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class TestConfig:
    """Configuration for a load test."""

    thread_count: int
    duration_sec: int
    loop_count: Optional[int]
    cpu_params: Optional[CPUOperationParams]
    mem_params: Optional[MEMOperationParams]
    disk_params: Optional[DISKOperationParams]
    net_params: Optional[NETOperationParams]
    parallel: bool = True


@dataclass
class TestState:
    """State of a running test."""

    test_id: str
    config: TestConfig
    status: TestStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    iterations_completed: int = 0
    error_count: int = 0
    errors: List[str] = field(default_factory=list)
    _cancel_event: Optional[asyncio.Event] = field(default=None, repr=False)


class TestManager:
    """Manages load test execution."""

    def __init__(self, max_workers: int = 50):
        self._tests: Dict[str, TestState] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running_tasks: Dict[str, List[asyncio.Task]] = {}

    async def start_test(self, config: TestConfig) -> str:
        """Start a new load test."""
        test_id = str(uuid.uuid4())

        state = TestState(
            test_id=test_id,
            config=config,
            status=TestStatus.PENDING,
            _cancel_event=asyncio.Event(),
        )
        self._tests[test_id] = state

        # Start test execution
        task = asyncio.create_task(self._run_test(test_id))
        self._running_tasks[test_id] = [task]

        return test_id

    async def stop_test(self, test_id: str, force: bool = False) -> bool:
        """Stop a running test."""
        if test_id not in self._tests:
            return False

        state = self._tests[test_id]
        if state.status not in [TestStatus.RUNNING, TestStatus.PAUSED]:
            return False

        # Signal cancellation
        if state._cancel_event:
            state._cancel_event.set()

        if force:
            # Cancel all tasks immediately
            for task in self._running_tasks.get(test_id, []):
                task.cancel()

        state.status = TestStatus.STOPPED
        state.completed_at = datetime.utcnow()
        return True

    def get_test_status(self, test_id: str) -> Optional[TestState]:
        """Get status of a test."""
        return self._tests.get(test_id)

    def get_all_tests(self) -> List[TestState]:
        """Get all tests."""
        return list(self._tests.values())

    async def _run_test(self, test_id: str) -> None:
        """Execute the test."""
        state = self._tests[test_id]
        state.status = TestStatus.RUNNING
        state.started_at = datetime.utcnow()

        config = state.config
        stats_collector = get_stats_collector()
        stats_collector.start()

        try:
            # Create worker tasks
            tasks = []
            for _ in range(config.thread_count):
                task = asyncio.create_task(
                    self._worker_loop(state, config, stats_collector)
                )
                tasks.append(task)

            # Wait for all workers or until duration expires
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=config.duration_sec,
                )
            except asyncio.TimeoutError:
                # Duration expired, cancel remaining work
                for task in tasks:
                    task.cancel()

            if state.status == TestStatus.RUNNING:
                state.status = TestStatus.COMPLETED

        except Exception as e:
            state.status = TestStatus.FAILED
            state.errors.append(str(e))
            state.error_count += 1

        finally:
            state.completed_at = datetime.utcnow()
            stats_collector.stop()

    async def _worker_loop(
        self, state: TestState, config: TestConfig, stats_collector: Any
    ) -> None:
        """Worker loop executing operations."""
        loop_count = config.loop_count or float("inf")
        iteration = 0

        while iteration < loop_count:
            # Check for cancellation
            if state._cancel_event and state._cancel_event.is_set():
                break

            if state.status != TestStatus.RUNNING:
                break

            try:
                start_time = time.perf_counter()

                if config.parallel:
                    # Run operations in parallel
                    await self._run_operations_parallel(config)
                else:
                    # Run operations sequentially
                    await self._run_operations_sequential(config)

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                stats_collector.record_iteration(elapsed_ms)
                state.iterations_completed += 1

            except Exception as e:
                state.error_count += 1
                if len(state.errors) < 100:  # Limit stored errors
                    state.errors.append(str(e))

            iteration += 1

    async def _run_operations_parallel(self, config: TestConfig) -> None:
        """Run configured operations in parallel."""
        tasks = []

        if config.cpu_params:
            tasks.append(CPUOperation.execute(config.cpu_params))

        if config.mem_params:
            tasks.append(MEMOperation.execute(config.mem_params))

        if config.disk_params:
            tasks.append(DISKOperation.execute(config.disk_params))

        if config.net_params:
            tasks.append(NETOperation.execute(config.net_params))

        if tasks:
            await asyncio.gather(*tasks)

    async def _run_operations_sequential(self, config: TestConfig) -> None:
        """Run configured operations sequentially."""
        if config.cpu_params:
            await CPUOperation.execute(config.cpu_params)

        if config.mem_params:
            await MEMOperation.execute(config.mem_params)

        if config.disk_params:
            await DISKOperation.execute(config.disk_params)

        if config.net_params:
            await NETOperation.execute(config.net_params)


# Global test manager instance
_test_manager: Optional[TestManager] = None


def get_test_manager() -> TestManager:
    """Get the global test manager instance."""
    global _test_manager
    if _test_manager is None:
        _test_manager = TestManager()
    return _test_manager
