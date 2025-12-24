"""System statistics collector."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import statistics


@dataclass(frozen=True)
class SystemStats:
    """System resource statistics."""

    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_read_bytes: int
    disk_write_bytes: int
    network_sent_bytes: int
    network_recv_bytes: int


@dataclass(frozen=True)
class IterationTiming:
    """Statistics for iteration timing."""

    sample_count: int
    avg_ms: float
    stddev_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p90_ms: float
    p99_ms: float


@dataclass
class StatsCollector:
    """Collects system and iteration statistics."""

    _iteration_times: List[float] = field(default_factory=list)
    _last_disk_read: int = 0
    _last_disk_write: int = 0
    _last_net_sent: int = 0
    _last_net_recv: int = 0
    _start_time: Optional[float] = None

    def start(self) -> None:
        """Start collecting statistics."""
        self._start_time = time.time()
        self._iteration_times.clear()

    def stop(self) -> None:
        """Stop collecting statistics."""
        self._start_time = None

    def record_iteration(self, duration_ms: float) -> None:
        """Record an iteration timing."""
        self._iteration_times.append(duration_ms)

    def get_iteration_timing(self) -> Optional[IterationTiming]:
        """Get iteration timing statistics."""
        if not self._iteration_times:
            return None

        times = sorted(self._iteration_times)
        count = len(times)

        if count == 1:
            val = times[0]
            return IterationTiming(
                sample_count=1,
                avg_ms=val,
                stddev_ms=0.0,
                min_ms=val,
                max_ms=val,
                p50_ms=val,
                p90_ms=val,
                p99_ms=val,
            )

        return IterationTiming(
            sample_count=count,
            avg_ms=statistics.mean(times),
            stddev_ms=statistics.stdev(times),
            min_ms=min(times),
            max_ms=max(times),
            p50_ms=self._percentile(times, 50),
            p90_ms=self._percentile(times, 90),
            p99_ms=self._percentile(times, 99),
        )

    @staticmethod
    def _percentile(sorted_data: List[float], percent: int) -> float:
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * percent / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        if f == c:
            return sorted_data[f]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    async def get_system_stats(self) -> SystemStats:
        """Get current system statistics."""
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk_io = psutil.disk_io_counters()
            net_io = psutil.net_io_counters()

            return SystemStats(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / (1024 * 1024),
                memory_available_mb=memory.available / (1024 * 1024),
                disk_read_bytes=disk_io.read_bytes if disk_io else 0,
                disk_write_bytes=disk_io.write_bytes if disk_io else 0,
                network_sent_bytes=net_io.bytes_sent if net_io else 0,
                network_recv_bytes=net_io.bytes_recv if net_io else 0,
            )
        except ImportError:
            # psutil not available, return mock data
            return SystemStats(
                timestamp=datetime.utcnow(),
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_used_mb=0.0,
                memory_available_mb=0.0,
                disk_read_bytes=0,
                disk_write_bytes=0,
                network_sent_bytes=0,
                network_recv_bytes=0,
            )

    def clear_iteration_times(self) -> None:
        """Clear recorded iteration times."""
        self._iteration_times.clear()


# Global stats collector instance
_stats_collector: Optional[StatsCollector] = None


def get_stats_collector() -> StatsCollector:
    """Get the global stats collector instance."""
    global _stats_collector
    if _stats_collector is None:
        _stats_collector = StatsCollector()
    return _stats_collector
