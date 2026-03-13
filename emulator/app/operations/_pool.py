"""Shared process pool for all operations.

All CPU-intensive operations (cpu, memory, disk) must run in this
ProcessPoolExecutor so they bypass the GIL and can utilise multiple
cores.  Using the default ThreadPoolExecutor (``run_in_executor(None, ...)``)
would serialise Python bytecode on the GIL, capping total CPU at ~1 core
regardless of concurrency.
"""

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

_process_pool: Optional[ProcessPoolExecutor] = None


def get_process_pool() -> ProcessPoolExecutor:
    """Lazily create a shared process pool.

    Pool is sized larger than cpu_count so many concurrent operations can
    coexist.  The OS scheduler distributes them across physical cores;
    more concurrent workers -> higher total CPU utilisation.
    """
    global _process_pool
    if _process_pool is None:
        ctx = multiprocessing.get_context("spawn")
        workers = max((os.cpu_count() or 4) * 16, 64)
        if os.name == "nt":
            workers = min(workers, 60)  # Windows limit is 61
        _process_pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=ctx,
        )
    return _process_pool
