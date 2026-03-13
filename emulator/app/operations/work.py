"""Combined CPU-burn + memory-touch operation.

Each request does a short CPU burn (5-10 ms) then touches a small
slice of the pre-allocated memory pool.  This produces steady,
spike-free load — no per-request memory allocation, no long CPU burns.
"""

import asyncio
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from . import mem_pool

# Thread pool (not process pool) so workers share the memory pool.
# Short burns (5-10 ms) mean GIL contention is negligible.
_thread_pool: Optional[ThreadPoolExecutor] = None


def _get_thread_pool() -> ThreadPoolExecutor:
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = ThreadPoolExecutor(max_workers=128)
    return _thread_pool


@dataclass(frozen=True)
class WorkParams:
    cpu_ms: int = 10        # CPU burn duration (ms)
    intensity: float = 0.8  # 0.0 – 1.0
    touch_mb: float = 1.0   # pool region to touch (MB)
    touch_pattern: str = "random"  # "random" or "sequential"


@dataclass(frozen=True)
class WorkResult:
    operation: str
    status: str
    cpu_ms_actual: int
    pages_touched: int
    wall_ms: int


def _do_work(cpu_ms: int, intensity: float,
             touch_bytes: int, touch_pattern: str) -> tuple[int, int, int]:
    """Runs in a thread.  Returns (cpu_ms_actual, pages_touched, wall_ms)."""
    wall_start = time.perf_counter()

    # ---- CPU burn (process_time based) ----
    target_cpu = (cpu_ms / 1000.0) * max(0.0, min(1.0, intensity))
    cpu_start = time.process_time()
    while (time.process_time() - cpu_start) < target_cpu:
        _ = math.sqrt(12345.6789) * math.pi
        _ = math.sin(12345.6789) * math.cos(12345.6789)
        _ = 12345 ** 2 % 67890

    # ---- Memory touch (no allocation) ----
    pages = 0
    if touch_bytes > 0 and mem_pool.pool_allocated():
        pages = mem_pool.touch_region(touch_bytes, touch_pattern)

    wall_ms = int((time.perf_counter() - wall_start) * 1000)
    cpu_actual = int((time.process_time() - cpu_start) * 1000)
    return cpu_actual, pages, wall_ms


async def execute(params: WorkParams) -> WorkResult:
    loop = asyncio.get_event_loop()
    touch_bytes = int(params.touch_mb * 1024 * 1024)
    cpu_actual, pages, wall_ms = await loop.run_in_executor(
        _get_thread_pool(),
        _do_work,
        params.cpu_ms,
        params.intensity,
        touch_bytes,
        params.touch_pattern,
    )
    return WorkResult(
        operation="WORK",
        status="completed",
        cpu_ms_actual=cpu_actual,
        pages_touched=pages,
        wall_ms=wall_ms,
    )
