"""System statistics collector with background collection and file persistence."""

import asyncio
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import statistics


@dataclass
class ProcessStats:
    """Per-process resource usage."""

    name: str
    pid: int
    cpu_percent: float
    memory_percent: float
    memory_rss_mb: float


@dataclass
class StatsSample:
    """A single stats sample with rates."""

    timestamp: str
    elapsed_sec: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_read_bytes: int
    disk_write_bytes: int
    disk_read_rate_mbps: float
    disk_write_rate_mbps: float
    network_sent_bytes: int
    network_recv_bytes: int
    network_sent_rate_mbps: float
    network_recv_rate_mbps: float
    process_stats: List[ProcessStats] = field(default_factory=list)


@dataclass(frozen=True)
class SystemStats:
    """System resource statistics (for backward compatibility)."""

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
class TestMetadata:
    """Metadata for a test run."""

    test_id: str
    test_run_id: str
    scenario_id: str
    mode: str  # "calibration" or "normal"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_sec: float = 0.0
    collect_interval_sec: float = 1.0
    total_samples: int = 0


@dataclass
class StatsCollector:
    """Collects system and iteration statistics with background collection."""

    # Iteration timing (existing)
    _iteration_times: List[float] = field(default_factory=list)

    # Background collection state
    _is_collecting: bool = False
    _collect_task: Optional[asyncio.Task] = None
    _collect_interval_sec: float = 1.0
    _max_samples: int = 10000
    _stats_output_dir: str = "./stats"

    # Test metadata
    _metadata: Optional[TestMetadata] = None

    # Samples buffer (ring buffer using deque)
    _samples: deque = field(default_factory=lambda: deque(maxlen=10000))

    # For rate calculations
    _last_disk_read: int = 0
    _last_disk_write: int = 0
    _last_net_sent: int = 0
    _last_net_recv: int = 0
    _last_sample_time: Optional[float] = None
    _start_time: Optional[float] = None

    # Per-process monitoring
    _service_monitor_patterns: List[str] = field(default_factory=list)
    _compiled_patterns: List = field(default_factory=list)

    def configure(self, output_dir: str = "./stats", max_samples: int = 10000,
                  default_interval_sec: float = 1.0,
                  service_monitor_patterns: Optional[List[str]] = None) -> None:
        """Configure the stats collector."""
        self._stats_output_dir = output_dir
        self._max_samples = max_samples
        self._samples = deque(maxlen=max_samples)
        self._collect_interval_sec = default_interval_sec

        # Compile service monitor patterns
        self._service_monitor_patterns = service_monitor_patterns or []
        self._compiled_patterns = []
        for pattern in self._service_monitor_patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error:
                print(f"Invalid service_monitor_pattern regex: {pattern}")

        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    async def start_collection(
        self,
        test_id: str,
        test_run_id: str,
        scenario_id: str,
        mode: str,
        interval_sec: float = 1.0
    ) -> None:
        """Start background stats collection for a test."""
        if self._is_collecting:
            await self.stop_collection()

        # Initialize metadata
        self._metadata = TestMetadata(
            test_id=test_id,
            test_run_id=test_run_id,
            scenario_id=scenario_id,
            mode=mode,
            started_at=datetime.utcnow().isoformat() + "Z",
            collect_interval_sec=interval_sec
        )

        # Clear previous data
        self._samples.clear()
        self._iteration_times.clear()

        # Initialize rate tracking
        try:
            import psutil
            disk_io = psutil.disk_io_counters()
            net_io = psutil.net_io_counters()
            self._last_disk_read = disk_io.read_bytes if disk_io else 0
            self._last_disk_write = disk_io.write_bytes if disk_io else 0
            self._last_net_sent = net_io.bytes_sent if net_io else 0
            self._last_net_recv = net_io.bytes_recv if net_io else 0
        except ImportError:
            self._last_disk_read = 0
            self._last_disk_write = 0
            self._last_net_sent = 0
            self._last_net_recv = 0

        self._start_time = time.time()
        self._last_sample_time = self._start_time
        self._collect_interval_sec = interval_sec
        self._is_collecting = True

        # Start background collection task
        self._collect_task = asyncio.create_task(self._collection_loop())

    async def stop_collection(self) -> Optional[str]:
        """Stop background stats collection and save to file.

        Returns:
            Path to the saved stats file, or None if no collection was active.
        """
        if not self._is_collecting:
            return None

        self._is_collecting = False

        # Cancel collection task
        if self._collect_task:
            self._collect_task.cancel()
            try:
                await self._collect_task
            except asyncio.CancelledError:
                pass
            self._collect_task = None

        # Update metadata
        if self._metadata:
            self._metadata.ended_at = datetime.utcnow().isoformat() + "Z"
            self._metadata.duration_sec = time.time() - (self._start_time or time.time())
            self._metadata.total_samples = len(self._samples)

        # Save to file
        stats_file = self._save_to_file()

        return stats_file

    async def _collection_loop(self) -> None:
        """Background loop that collects stats at regular intervals."""
        while self._is_collecting:
            try:
                sample = await self._collect_sample()
                if sample:
                    self._samples.append(sample)

                await asyncio.sleep(self._collect_interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue collecting
                print(f"Stats collection error: {e}")
                await asyncio.sleep(self._collect_interval_sec)

    async def _collect_sample(self) -> Optional[StatsSample]:
        """Collect a single stats sample with rate calculations."""
        try:
            import psutil

            current_time = time.time()
            elapsed_sec = current_time - (self._start_time or current_time)
            time_delta = current_time - (self._last_sample_time or current_time)
            if time_delta <= 0:
                time_delta = 1.0  # Avoid division by zero

            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            disk_io = psutil.disk_io_counters()
            net_io = psutil.net_io_counters()

            # Get current values
            disk_read = disk_io.read_bytes if disk_io else 0
            disk_write = disk_io.write_bytes if disk_io else 0
            net_sent = net_io.bytes_sent if net_io else 0
            net_recv = net_io.bytes_recv if net_io else 0

            # Calculate rates (bytes/sec -> MB/sec)
            disk_read_rate = (disk_read - self._last_disk_read) / time_delta / (1024 * 1024)
            disk_write_rate = (disk_write - self._last_disk_write) / time_delta / (1024 * 1024)
            net_sent_rate = (net_sent - self._last_net_sent) / time_delta / (1024 * 1024)
            net_recv_rate = (net_recv - self._last_net_recv) / time_delta / (1024 * 1024)

            # Update last values for next rate calculation
            self._last_disk_read = disk_read
            self._last_disk_write = disk_write
            self._last_net_sent = net_sent
            self._last_net_recv = net_recv
            self._last_sample_time = current_time

            # Collect per-process stats if patterns configured
            proc_stats = self._collect_process_stats() if self._compiled_patterns else []

            return StatsSample(
                timestamp=datetime.utcnow().isoformat() + "Z",
                elapsed_sec=round(elapsed_sec, 2),
                cpu_percent=round(cpu_percent, 2),
                memory_percent=round(memory.percent, 2),
                memory_used_mb=round(memory.used / (1024 * 1024), 2),
                memory_available_mb=round(memory.available / (1024 * 1024), 2),
                disk_read_bytes=disk_read,
                disk_write_bytes=disk_write,
                disk_read_rate_mbps=round(max(0, disk_read_rate), 3),
                disk_write_rate_mbps=round(max(0, disk_write_rate), 3),
                network_sent_bytes=net_sent,
                network_recv_bytes=net_recv,
                network_sent_rate_mbps=round(max(0, net_sent_rate), 3),
                network_recv_rate_mbps=round(max(0, net_recv_rate), 3),
                process_stats=proc_stats,
            )
        except ImportError:
            return None
        except Exception as e:
            print(f"Error collecting sample: {e}")
            return None

    def _collect_process_stats(self) -> List[ProcessStats]:
        """Collect CPU and memory stats for processes matching service_monitor_patterns."""
        results = []
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
                try:
                    pname = proc.info['name'] or ""
                    for pattern in self._compiled_patterns:
                        if pattern.search(pname):
                            mem_info = proc.info.get('memory_info')
                            rss_mb = (mem_info.rss / (1024 * 1024)) if mem_info else 0.0
                            results.append(ProcessStats(
                                name=pname,
                                pid=proc.info['pid'],
                                cpu_percent=round(proc.info.get('cpu_percent', 0.0) or 0.0, 2),
                                memory_percent=round(proc.info.get('memory_percent', 0.0) or 0.0, 2),
                                memory_rss_mb=round(rss_mb, 2),
                            ))
                            break  # One match per process is enough
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass
        return results

    def _save_to_file(self) -> Optional[str]:
        """Save all collected stats to a JSON file."""
        if not self._metadata:
            return None

        # Build filename
        filename = f"{self._metadata.test_run_id}_{self._metadata.scenario_id}_{self._metadata.mode}_stats.json"
        filepath = os.path.join(self._stats_output_dir, filename)

        # Ensure directory exists
        Path(self._stats_output_dir).mkdir(parents=True, exist_ok=True)

        # Build summary statistics
        summary = self._calculate_summary()

        # Build output data
        data = {
            "metadata": {
                "test_id": self._metadata.test_id,
                "test_run_id": self._metadata.test_run_id,
                "scenario_id": self._metadata.scenario_id,
                "mode": self._metadata.mode,
                "started_at": self._metadata.started_at,
                "ended_at": self._metadata.ended_at,
                "duration_sec": round(self._metadata.duration_sec, 2),
                "collect_interval_sec": self._metadata.collect_interval_sec,
                "total_samples": len(self._samples)
            },
            "samples": [asdict(s) for s in self._samples],
            "summary": summary
        }

        # Write to file
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        return filepath

    def _calculate_summary(self) -> Dict[str, Any]:
        """Calculate summary statistics for all metrics including per-process."""
        if not self._samples:
            return {}

        metrics = [
            "cpu_percent", "memory_percent",
            "disk_read_rate_mbps", "disk_write_rate_mbps",
            "network_sent_rate_mbps", "network_recv_rate_mbps"
        ]

        summary: Dict[str, Any] = {}
        for metric in metrics:
            values = [getattr(s, metric) for s in self._samples]
            if values:
                sorted_values = sorted(values)
                summary[metric] = {
                    "avg": round(statistics.mean(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                    "p50": round(self._percentile(sorted_values, 50), 2),
                    "p90": round(self._percentile(sorted_values, 90), 2),
                    "p95": round(self._percentile(sorted_values, 95), 2),
                    "p99": round(self._percentile(sorted_values, 99), 2),
                }

        # Per-process summary (aggregate by process name across all samples)
        if self._compiled_patterns:
            proc_data: Dict[str, Dict[str, List[float]]] = {}
            for sample in self._samples:
                for ps in sample.process_stats:
                    if ps.name not in proc_data:
                        proc_data[ps.name] = {"cpu": [], "mem": [], "rss": []}
                    proc_data[ps.name]["cpu"].append(ps.cpu_percent)
                    proc_data[ps.name]["mem"].append(ps.memory_percent)
                    proc_data[ps.name]["rss"].append(ps.memory_rss_mb)

            if proc_data:
                process_summary = {}
                for pname, metrics_dict in proc_data.items():
                    process_summary[pname] = {}
                    for mkey, values in metrics_dict.items():
                        if values:
                            sorted_vals = sorted(values)
                            process_summary[pname][mkey] = {
                                "avg": round(statistics.mean(values), 2),
                                "min": round(min(values), 2),
                                "max": round(max(values), 2),
                                "p50": round(self._percentile(sorted_vals, 50), 2),
                                "p90": round(self._percentile(sorted_vals, 90), 2),
                                "p95": round(self._percentile(sorted_vals, 95), 2),
                                "p99": round(self._percentile(sorted_vals, 99), 2),
                            }
                summary["process_stats"] = process_summary

        return summary

    def get_recent_samples(self, count: int = 100) -> List[StatsSample]:
        """Get the most recent N samples."""
        count = min(count, len(self._samples), 1000)
        return list(self._samples)[-count:] if self._samples else []

    def get_all_samples(self) -> List[StatsSample]:
        """Get all samples in memory."""
        return list(self._samples)

    def get_collection_status(self) -> Dict[str, Any]:
        """Get current collection status."""
        return {
            "is_collecting": self._is_collecting,
            "test_id": self._metadata.test_id if self._metadata else None,
            "test_run_id": self._metadata.test_run_id if self._metadata else None,
            "scenario_id": self._metadata.scenario_id if self._metadata else None,
            "mode": self._metadata.mode if self._metadata else None,
            "samples_collected": len(self._samples),
            "interval_sec": self._collect_interval_sec,
        }

    def load_stats_file(self, test_run_id: str, scenario_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load stats from a file.

        Args:
            test_run_id: Test run ID to load
            scenario_id: Optional scenario filter

        Returns:
            Stats data dict or None if not found
        """
        # Find matching files
        stats_dir = Path(self._stats_output_dir)
        if not stats_dir.exists():
            return None

        pattern = f"{test_run_id}_*_stats.json"
        if scenario_id:
            pattern = f"{test_run_id}_{scenario_id}_*_stats.json"

        matching_files = list(stats_dir.glob(pattern))
        if not matching_files:
            return None

        # Load the most recent matching file
        latest_file = max(matching_files, key=lambda f: f.stat().st_mtime)

        with open(latest_file, 'r') as f:
            return json.load(f)

    # ========== Existing methods for backward compatibility ==========

    def start(self) -> None:
        """Start collecting statistics (legacy method)."""
        self._start_time = time.time()
        self._iteration_times.clear()

    def stop(self) -> None:
        """Stop collecting statistics (legacy method)."""
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
        """Get current system statistics (legacy method)."""
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
