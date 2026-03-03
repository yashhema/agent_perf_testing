"""CPU load generation operation.

Uses process_time()-based CPU burn so that CPU utilization scales
linearly with the number of concurrent requests.  Each worker burns
a fixed amount of *actual CPU time* (duration × intensity).  When
multiple workers share cores, each takes longer wall-time but the
aggregate CPU consumption rises proportionally — exactly what the
calibration binary search needs.
"""

import asyncio
import math
import time
from dataclasses import dataclass

from ._pool import get_process_pool


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
        Burn CPU cycles consuming *actual CPU time* equal to
        ``duration_sec * intensity``.

        Uses ``time.process_time()`` (measures real CPU consumption of
        this process) instead of wall-clock time.  This means:

        * With few concurrent workers each gets a full core → finishes
          fast, total system CPU is low.
        * With many concurrent workers they share cores via OS
          scheduling → each takes longer wall-time, but aggregate
          system CPU rises proportionally.

        Returns the wall-clock duration in milliseconds.
        """
        start_wall = time.perf_counter()
        target_cpu_sec = duration_sec * max(0.0, min(1.0, intensity))
        start_cpu = time.process_time()

        while (time.process_time() - start_cpu) < target_cpu_sec:
            # Mix of floating-point and integer operations
            _ = math.sqrt(12345.6789) * math.pi
            _ = math.sin(12345.6789) * math.cos(12345.6789)
            _ = 12345 ** 2 % 67890

        actual_wall = time.perf_counter() - start_wall
        return int(actual_wall * 1000)

    @staticmethod
    async def execute(params: CPUOperationParams) -> CPUOperationResult:
        """
        Execute CPU load operation asynchronously.

        Spawns operation in executor to not block event loop.
        """
        duration_sec = params.duration_ms / 1000

        # Run CPU burn in process pool so multiple requests can saturate all cores.
        # ThreadPoolExecutor is GIL-limited to 1 core; ProcessPoolExecutor is not.
        loop = asyncio.get_event_loop()
        actual_duration_ms = await loop.run_in_executor(
            get_process_pool(),
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
