"""Memory allocation and access operation."""

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Literal

from ._pool import get_process_pool


@dataclass(frozen=True)
class MEMOperationParams:
    """Parameters for memory operation."""

    duration_ms: int
    size_mb: int
    pattern: Literal["sequential", "random"] = "sequential"


@dataclass(frozen=True)
class MEMOperationResult:
    """Result of memory operation."""

    operation: str
    duration_ms: int
    size_mb: int
    pattern: str
    status: str
    actual_duration_ms: int
    access_count: int


class MEMOperation:
    """Memory allocation and access operation."""

    @staticmethod
    def _allocate_and_access(
        duration_sec: float, size_mb: int, pattern: str
    ) -> tuple[int, int]:
        """
        Allocate memory and access it for specified duration.

        Returns (actual_duration_ms, access_count).
        """
        start_time = time.perf_counter()

        # Allocate memory
        size_bytes = size_mb * 1024 * 1024
        buffer = bytearray(size_bytes)

        # Initialize buffer to ensure memory is actually allocated
        for i in range(0, len(buffer), 4096):
            buffer[i] = 0

        end_time = start_time + duration_sec
        access_count = 0

        while time.perf_counter() < end_time:
            if pattern == "sequential":
                # Sequential access - page by page
                for i in range(0, len(buffer), 4096):
                    buffer[i] = (buffer[i] + 1) % 256
                    access_count += 1
            else:
                # Random access
                for _ in range(min(1000, len(buffer) // 4096)):
                    idx = random.randint(0, len(buffer) - 1)
                    buffer[idx] = (buffer[idx] + 1) % 256
                    access_count += 1

        # Release memory explicitly
        del buffer

        actual_duration = time.perf_counter() - start_time
        return int(actual_duration * 1000), access_count

    @staticmethod
    async def execute(params: MEMOperationParams) -> MEMOperationResult:
        """Execute memory operation asynchronously."""
        duration_sec = params.duration_ms / 1000

        loop = asyncio.get_event_loop()
        actual_duration_ms, access_count = await loop.run_in_executor(
            get_process_pool(),
            MEMOperation._allocate_and_access,
            duration_sec,
            params.size_mb,
            params.pattern,
        )

        return MEMOperationResult(
            operation="MEM",
            duration_ms=params.duration_ms,
            size_mb=params.size_mb,
            pattern=params.pattern,
            status="completed",
            actual_duration_ms=actual_duration_ms,
            access_count=access_count,
        )
