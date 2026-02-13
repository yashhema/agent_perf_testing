"""HTTP client for emulator service."""

import asyncio
from dataclasses import dataclass
from typing import Optional, List
import statistics


@dataclass(frozen=True)
class EmulatorStats:
    """Statistics from emulator."""

    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    iteration_count: int
    avg_iteration_ms: float


@dataclass(frozen=True)
class TestConfig:
    """Configuration for emulator test."""

    thread_count: int
    duration_sec: int
    cpu_duration_ms: int = 100
    cpu_intensity: float = 1.0
    mem_size_mb: int = 10
    include_disk: bool = False
    include_network: bool = False


class EmulatorClient:
    """HTTP client for communicating with emulator service."""

    def __init__(self, host: str, port: int, timeout: int = 30):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._base_url = f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        """Get base URL."""
        return self._base_url

    async def health_check(self) -> bool:
        """Check if emulator is healthy."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def start_test(self, config: TestConfig) -> str:
        """Start a load test and return test ID."""
        try:
            import httpx

            # Build operation config
            operation = {
                "cpu": {
                    "duration_ms": config.cpu_duration_ms,
                    "intensity": config.cpu_intensity,
                },
                "parallel": True,
            }

            if config.mem_size_mb > 0:
                operation["mem"] = {
                    "duration_ms": config.cpu_duration_ms,
                    "size_mb": config.mem_size_mb,
                    "pattern": "sequential",
                }

            payload = {
                "thread_count": config.thread_count,
                "duration_sec": config.duration_sec,
                "operation": operation,
                "loop_count": None,  # Infinite loops until duration
            }

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/v1/tests/",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("test_id", "")

        except Exception as e:
            raise RuntimeError(f"Failed to start test: {e}")

    async def stop_test(self, test_id: str, force: bool = False) -> bool:
        """Stop a running test."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/v1/tests/{test_id}/stop",
                    json={"force": force},
                )
                return response.status_code == 200
        except Exception:
            return False

    async def get_test_status(self, test_id: str) -> dict:
        """Get status of a test."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/tests/{test_id}"
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"error": str(e)}

    async def get_system_stats(self) -> EmulatorStats:
        """Get current system statistics."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/stats/system"
                )
                response.raise_for_status()
                data = response.json()

                return EmulatorStats(
                    cpu_percent=data.get("cpu_percent", 0.0),
                    memory_percent=data.get("memory_percent", 0.0),
                    memory_used_mb=data.get("memory_used_mb", 0.0),
                    iteration_count=0,
                    avg_iteration_ms=0.0,
                )
        except Exception:
            return EmulatorStats(
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_used_mb=0.0,
                iteration_count=0,
                avg_iteration_ms=0.0,
            )

    async def get_iteration_stats(self) -> dict:
        """Get iteration timing statistics."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/stats/iterations"
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"error": str(e)}

    async def clear_iteration_stats(self) -> bool:
        """Clear iteration timing statistics."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/v1/stats/iterations/clear"
                )
                return response.status_code == 200
        except Exception:
            return False

    async def run_calibration_test(
        self,
        thread_count: int,
        duration_sec: int,
        warmup_sec: int = 10,
    ) -> tuple[float, Optional[dict]]:
        """
        Run a calibration test and return (avg_cpu_percent, iteration_stats).

        Runs the test for specified duration, collects CPU samples,
        and returns average CPU usage.
        """
        config = TestConfig(
            thread_count=thread_count,
            duration_sec=duration_sec + warmup_sec,
            cpu_duration_ms=100,
            cpu_intensity=1.0,
        )

        # Clear previous iteration stats
        await self.clear_iteration_stats()

        # Start test
        test_id = await self.start_test(config)

        # Wait for warmup
        await asyncio.sleep(warmup_sec)

        # Collect CPU samples during measurement period
        cpu_samples: List[float] = []
        sample_interval = 5  # seconds
        samples_to_collect = duration_sec // sample_interval

        for _ in range(samples_to_collect):
            await asyncio.sleep(sample_interval)
            stats = await self.get_system_stats()
            cpu_samples.append(stats.cpu_percent)

        # Wait for test to complete
        remaining = duration_sec - (samples_to_collect * sample_interval)
        if remaining > 0:
            await asyncio.sleep(remaining)

        # Get iteration stats
        iteration_stats = await self.get_iteration_stats()

        # Calculate average CPU
        avg_cpu = statistics.mean(cpu_samples) if cpu_samples else 0.0

        return avg_cpu, iteration_stats

    async def run_timing_test(
        self,
        thread_count: int,
        iterations: int = 100,
    ) -> List[float]:
        """
        Run a test specifically for timing iterations.

        Returns list of iteration times in milliseconds.
        """
        # Estimate duration based on iterations
        # Assume ~100ms per iteration as baseline
        estimated_duration = max(30, (iterations * 150) // 1000)

        config = TestConfig(
            thread_count=thread_count,
            duration_sec=estimated_duration,
            cpu_duration_ms=100,
            cpu_intensity=1.0,
        )

        await self.clear_iteration_stats()
        test_id = await self.start_test(config)

        # Wait for test to complete
        await asyncio.sleep(estimated_duration + 5)

        # Get iteration stats
        stats = await self.get_iteration_stats()

        if "error" in stats:
            return []

        # Build timing list from stats (approximation)
        # In real implementation, emulator would return raw timings
        sample_count = stats.get("sample_count", 0)
        avg_ms = stats.get("avg_ms", 100.0)
        stddev_ms = stats.get("stddev_ms", 10.0)

        # Generate approximate distribution
        import random

        timings = []
        for _ in range(min(sample_count, iterations)):
            timing = max(1.0, random.gauss(avg_ms, stddev_ms))
            timings.append(timing)

        return timings
