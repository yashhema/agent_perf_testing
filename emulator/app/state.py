"""Application state management."""

import time

# Track startup time for uptime calculation
_startup_time: float = 0.0


def set_startup_time() -> None:
    """Set the startup time."""
    global _startup_time
    _startup_time = time.time()


def get_uptime() -> float:
    """Get service uptime in seconds."""
    if _startup_time == 0.0:
        return 0.0
    return time.time() - _startup_time
