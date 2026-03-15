"""Pre-allocated memory pool for steady-state load testing.

Allocates a large contiguous buffer at startup and touches all pages
so the OS commits real RAM.  Per-request operations touch a small
slice of this pool — no alloc/dealloc churn, no RSS oscillation.
"""

import random
import threading
from typing import Optional

_PAGE_SIZE = 4096

_pool: Optional[bytearray] = None
_pool_size: int = 0
_lock = threading.Lock()


def init_pool(size_gb: float) -> int:
    """Allocate the memory pool and touch every page.

    Returns the pool size in bytes.  Safe to call multiple times —
    re-allocates only if the requested size differs.
    """
    global _pool, _pool_size

    size_bytes = int(size_gb * 1024 * 1024 * 1024)
    if size_bytes <= 0:
        raise ValueError(f"pool size must be > 0, got {size_gb} GB")

    with _lock:
        if _pool is not None and _pool_size == size_bytes:
            return _pool_size  # already allocated at this size

        # Allocate
        buf = bytearray(size_bytes)

        # Touch every page to force physical allocation
        for offset in range(0, size_bytes, _PAGE_SIZE):
            buf[offset] = 0xFF

        _pool = buf
        _pool_size = size_bytes

    return _pool_size


def touch_region(size_bytes: int, pattern: str = "random") -> int:
    """Touch a region of the pool.  Returns number of pages touched.

    ``size_bytes`` is clamped to pool size.  Does NOT allocate.
    """
    if _pool is None:
        raise RuntimeError("Memory pool not initialised — call init_pool() first")

    size_bytes = min(size_bytes, _pool_size)
    pages = max(1, size_bytes // _PAGE_SIZE)

    if pattern == "sequential":
        start = random.randint(0, max(0, _pool_size - size_bytes))
        for i in range(pages):
            offset = start + i * _PAGE_SIZE
            if offset < _pool_size:
                _pool[offset] = (_pool[offset] + 1) & 0xFF
    else:
        # Random scatter across entire pool
        for _ in range(pages):
            offset = random.randint(0, _pool_size - 1) & ~(_PAGE_SIZE - 1)
            _pool[offset] = (_pool[offset] + 1) & 0xFF

    return pages


def pool_allocated() -> bool:
    return _pool is not None


def pool_size_bytes() -> int:
    return _pool_size


def destroy_pool() -> None:
    """Release the pool (for testing / shutdown)."""
    global _pool, _pool_size
    with _lock:
        _pool = None
        _pool_size = 0
