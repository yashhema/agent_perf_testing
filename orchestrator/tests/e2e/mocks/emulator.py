"""Mock emulator server for E2E testing."""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List


class TestState(str, Enum):
    """Test execution states."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MockTestRun:
    """Mock test run state."""
    test_id: str
    thread_count: int
    duration_sec: int
    state: TestState = TestState.IDLE
    started_at: Optional[datetime] = None
    cpu_samples: List[float] = field(default_factory=list)
    iteration_count: int = 0
    avg_iteration_ms: float = 0.0


class EmulatorSimulator:
    """
    Simulates emulator agent behavior.

    Generates realistic CPU usage and timing metrics.
    """

    def __init__(
        self,
        base_cpu_per_thread: float = 5.0,
        cpu_variance: float = 2.0,
        base_iteration_ms: float = 50.0,
        iteration_variance: float = 10.0,
    ):
        self._base_cpu_per_thread = base_cpu_per_thread
        self._cpu_variance = cpu_variance
        self._base_iteration_ms = base_iteration_ms
        self._iteration_variance = iteration_variance

        self._current_test: Optional[MockTestRun] = None
        self._test_history: List[MockTestRun] = []
        self._healthy = True
        self._test_counter = 0

    def set_healthy(self, healthy: bool) -> None:
        """Set emulator health status."""
        self._healthy = healthy

    def is_healthy(self) -> bool:
        """Check if emulator is healthy."""
        return self._healthy

    def get_current_test(self) -> Optional[MockTestRun]:
        """Get current running test."""
        return self._current_test

    def calculate_cpu_for_threads(self, thread_count: int) -> float:
        """Calculate expected CPU usage for thread count."""
        base_cpu = thread_count * self._base_cpu_per_thread
        variance = random.uniform(-self._cpu_variance, self._cpu_variance)
        return min(100.0, max(0.0, base_cpu + variance))

    def calculate_iteration_time(self) -> float:
        """Calculate iteration time in milliseconds."""
        variance = random.uniform(
            -self._iteration_variance,
            self._iteration_variance,
        )
        return max(1.0, self._base_iteration_ms + variance)

    def start_test(self, thread_count: int, duration_sec: int) -> str:
        """Start a new test."""
        if not self._healthy:
            raise RuntimeError("Emulator is not healthy")

        self._test_counter += 1
        test_id = f"test-{self._test_counter:04d}"

        self._current_test = MockTestRun(
            test_id=test_id,
            thread_count=thread_count,
            duration_sec=duration_sec,
            state=TestState.RUNNING,
            started_at=datetime.utcnow(),
        )

        return test_id

    def stop_test(self) -> bool:
        """Stop current test."""
        if self._current_test is None:
            return False

        self._current_test.state = TestState.COMPLETED
        self._test_history.append(self._current_test)
        self._current_test = None
        return True

    def get_system_stats(self) -> Dict:
        """Get current system statistics."""
        if not self._healthy:
            return {"cpu_percent": 0.0, "memory_percent": 0.0}

        if self._current_test and self._current_test.state == TestState.RUNNING:
            cpu = self.calculate_cpu_for_threads(self._current_test.thread_count)
            self._current_test.cpu_samples.append(cpu)
        else:
            cpu = random.uniform(1.0, 5.0)  # Idle CPU

        return {
            "cpu_percent": round(cpu, 2),
            "memory_percent": round(random.uniform(20.0, 40.0), 2),
            "disk_percent": round(random.uniform(10.0, 30.0), 2),
        }

    def get_iteration_stats(self) -> Dict:
        """Get iteration timing statistics."""
        if self._current_test and self._current_test.state == TestState.RUNNING:
            # Simulate some iterations
            sample_count = random.randint(100, 1000)
            avg_ms = self.calculate_iteration_time()
            stddev_ms = avg_ms * 0.1

            return {
                "sample_count": sample_count,
                "avg_ms": round(avg_ms, 3),
                "min_ms": round(avg_ms * 0.8, 3),
                "max_ms": round(avg_ms * 1.5, 3),
                "stddev_ms": round(stddev_ms, 3),
                "p50_ms": round(avg_ms, 3),
                "p95_ms": round(avg_ms * 1.2, 3),
                "p99_ms": round(avg_ms * 1.4, 3),
            }

        return {
            "sample_count": 0,
            "avg_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "stddev_ms": 0.0,
        }

    def clear_iteration_stats(self) -> bool:
        """Clear iteration statistics."""
        if self._current_test:
            self._current_test.iteration_count = 0
            self._current_test.avg_iteration_ms = 0.0
        return True


class MockEmulatorServer:
    """
    Mock HTTP server interface for emulator.

    Provides the same API as the real emulator agent.
    """

    def __init__(self, simulator: EmulatorSimulator):
        self._simulator = simulator
        self._request_delay_sec = 0.01

    async def _delay(self) -> None:
        """Simulate network delay."""
        await asyncio.sleep(self._request_delay_sec)

    async def health_check(self) -> Dict:
        """Health check endpoint."""
        await self._delay()

        if not self._simulator.is_healthy():
            return {"status": "unhealthy", "error": "Emulator not responding"}

        return {"status": "healthy", "version": "1.0.0"}

    async def start_test(
        self,
        thread_count: int,
        duration_sec: int,
        cpu_duration_ms: int = 100,
        cpu_intensity: float = 1.0,
    ) -> Dict:
        """Start a load test."""
        await self._delay()

        if not self._simulator.is_healthy():
            raise RuntimeError("Emulator is not healthy")

        test_id = self._simulator.start_test(thread_count, duration_sec)

        return {
            "test_id": test_id,
            "status": "started",
            "thread_count": thread_count,
            "duration_sec": duration_sec,
        }

    async def stop_test(self) -> Dict:
        """Stop current test."""
        await self._delay()

        success = self._simulator.stop_test()

        return {
            "status": "stopped" if success else "no_test_running",
            "success": success,
        }

    async def get_test_status(self) -> Dict:
        """Get current test status."""
        await self._delay()

        test = self._simulator.get_current_test()

        if test is None:
            return {"status": "idle", "test_id": None}

        return {
            "status": test.state.value,
            "test_id": test.test_id,
            "thread_count": test.thread_count,
            "duration_sec": test.duration_sec,
            "elapsed_sec": (
                (datetime.utcnow() - test.started_at).total_seconds()
                if test.started_at else 0
            ),
        }

    async def get_system_stats(self) -> Dict:
        """Get system statistics."""
        await self._delay()

        return self._simulator.get_system_stats()

    async def get_iteration_stats(self) -> Dict:
        """Get iteration timing statistics."""
        await self._delay()

        return self._simulator.get_iteration_stats()

    async def clear_iteration_stats(self) -> Dict:
        """Clear iteration statistics."""
        await self._delay()

        success = self._simulator.clear_iteration_stats()

        return {"status": "cleared" if success else "failed"}


@dataclass(frozen=True)
class MockEmulatorClientConfig:
    """Configuration for mock emulator client."""
    host: str = "localhost"
    port: int = 8080
    timeout_sec: int = 30


class MockEmulatorClient:
    """
    Drop-in replacement for EmulatorClient that uses MockEmulatorServer.

    Can be used to patch the real client in E2E tests.
    """

    def __init__(
        self,
        server: MockEmulatorServer,
        config: Optional[MockEmulatorClientConfig] = None,
    ):
        self._server = server
        self._config = config or MockEmulatorClientConfig()

    async def health_check(self) -> bool:
        """Check if emulator is healthy."""
        result = await self._server.health_check()
        return result.get("status") == "healthy"

    async def start_test(
        self,
        thread_count: int,
        duration_sec: int,
        cpu_duration_ms: int = 100,
        cpu_intensity: float = 1.0,
    ) -> str:
        """Start a load test and return test ID."""
        result = await self._server.start_test(
            thread_count=thread_count,
            duration_sec=duration_sec,
            cpu_duration_ms=cpu_duration_ms,
            cpu_intensity=cpu_intensity,
        )
        return result["test_id"]

    async def stop_test(self) -> bool:
        """Stop current test."""
        result = await self._server.stop_test()
        return result.get("success", False)

    async def get_test_status(self) -> Dict:
        """Get current test status."""
        return await self._server.get_test_status()

    async def get_system_stats(self) -> Dict:
        """Get system statistics."""
        return await self._server.get_system_stats()

    async def get_iteration_stats(self) -> Dict:
        """Get iteration statistics."""
        return await self._server.get_iteration_stats()

    async def clear_iteration_stats(self) -> bool:
        """Clear iteration statistics."""
        result = await self._server.clear_iteration_stats()
        return result.get("status") == "cleared"
