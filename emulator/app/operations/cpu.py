"""CPU load generation operation."""

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CPUOperationParams:
    """Parameters for CPU operation."""

    duration_ms: int
    intensity: float = 1.0  # 0.0 to 1.0


@dataclass(frozen=True)
class CPUOperationResult:
    """Result of CPU operation."""

    operation: str
    duration_ms: int
    intensity: float
    status: str
    actual_duration_ms: int


class CPUOperation:
    """CPU load generation operation."""

    @staticmethod
    def _burn_cpu(duration_sec: float, intensity: float) -> int:
        """
        Burn CPU cycles for specified duration.

        Uses busy-wait with optional sleep to control intensity.
        Returns the actual duration in milliseconds.
        """
        start_time = time.perf_counter()
        end_time = start_time + duration_sec
        work_ratio = max(0.0, min(1.0, intensity))
        cycle_ms = 10  # 10ms cycles

        while time.perf_counter() < end_time:
            cycle_start = time.perf_counter()
            work_duration = (cycle_ms / 1000) * work_ratio

            # Busy work - CPU-intensive calculations
            work_end = cycle_start + work_duration
            while time.perf_counter() < work_end:
                # Mix of floating-point and integer operations
                _ = math.sqrt(12345.6789) * math.pi
                _ = math.sin(12345.6789) * math.cos(12345.6789)
                _ = 12345 ** 2 % 67890

            # Sleep for remaining cycle time
            sleep_duration = (cycle_ms / 1000) * (1 - work_ratio)
            if sleep_duration > 0.001:  # Only sleep if > 1ms
                time.sleep(sleep_duration)

        actual_duration = time.perf_counter() - start_time
        return int(actual_duration * 1000)

    @staticmethod
    async def execute(params: CPUOperationParams) -> CPUOperationResult:
        """
        Execute CPU load operation asynchronously.

        Spawns operation in executor to not block event loop.
        """
        duration_sec = params.duration_ms / 1000

        # Run CPU burn in thread pool to not block async
        loop = asyncio.get_event_loop()
        actual_duration_ms = await loop.run_in_executor(
            None,
            CPUOperation._burn_cpu,
            duration_sec,
            params.intensity,
        )

        return CPUOperationResult(
            operation="CPU",
            duration_ms=params.duration_ms,
            intensity=params.intensity,
            status="completed",
            actual_duration_ms=actual_duration_ms,
        )
