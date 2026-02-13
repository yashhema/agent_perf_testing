"""Calibration algorithm using binary search."""

from dataclasses import dataclass
from typing import Optional, List, Callable, Awaitable
import statistics

from .models import (
    CalibrationConfig,
    CalibrationRun,
    IterationStats,
    LoadProfile,
)


@dataclass
class BinarySearchState:
    """State of binary search algorithm."""

    min_threads: int
    max_threads: int
    current_threads: int
    target_cpu: float
    tolerance: float
    best_threads: int
    best_cpu: float
    best_diff: float
    iterations: int
    runs: List[CalibrationRun]


class CalibrationAlgorithm:
    """
    Binary search algorithm for finding optimal thread count.

    The algorithm searches for a thread count that achieves a target
    CPU percentage within a specified tolerance.
    """

    def __init__(self, config: CalibrationConfig):
        self._config = config

    def get_target_cpu(self, loadprofile: LoadProfile) -> float:
        """Get target CPU percentage for a load profile."""
        targets = {
            LoadProfile.LOW: self._config.cpu_target_low,
            LoadProfile.MEDIUM: self._config.cpu_target_medium,
            LoadProfile.HIGH: self._config.cpu_target_high,
        }
        return targets[loadprofile]

    async def calibrate(
        self,
        loadprofile: LoadProfile,
        run_test: Callable[[int], Awaitable[float]],
    ) -> tuple[int, float, List[CalibrationRun]]:
        """
        Run calibration using binary search.

        Args:
            loadprofile: Target load profile
            run_test: Async function that runs a test with given thread count
                     and returns achieved CPU percentage

        Returns:
            Tuple of (optimal_thread_count, achieved_cpu, list of runs)
        """
        target_cpu = self.get_target_cpu(loadprofile)

        state = BinarySearchState(
            min_threads=self._config.min_threads,
            max_threads=self._config.max_threads,
            current_threads=(self._config.min_threads + self._config.max_threads) // 2,
            target_cpu=target_cpu,
            tolerance=self._config.tolerance,
            best_threads=self._config.min_threads,
            best_cpu=0.0,
            best_diff=float("inf"),
            iterations=0,
            runs=[],
        )

        while self._should_continue(state):
            state.iterations += 1

            # Run test with current thread count
            achieved_cpu = await run_test(state.current_threads)

            # Record run
            within_tolerance = abs(achieved_cpu - target_cpu) <= self._config.tolerance
            run = CalibrationRun(
                thread_count=state.current_threads,
                target_cpu_percent=target_cpu,
                achieved_cpu_percent=achieved_cpu,
                duration_sec=self._config.calibration_duration_sec,
                within_tolerance=within_tolerance,
            )
            state.runs.append(run)

            # Check if within tolerance
            if within_tolerance:
                state.best_threads = state.current_threads
                state.best_cpu = achieved_cpu
                break

            # Update best result
            diff = abs(achieved_cpu - target_cpu)
            if diff < state.best_diff:
                state.best_threads = state.current_threads
                state.best_cpu = achieved_cpu
                state.best_diff = diff

            # Binary search adjustment
            state = self._adjust_search(state, achieved_cpu)

        return state.best_threads, state.best_cpu, state.runs

    def _should_continue(self, state: BinarySearchState) -> bool:
        """Check if search should continue."""
        if state.iterations >= self._config.max_iterations:
            return False
        if state.min_threads > state.max_threads:
            return False
        return True

    def _adjust_search(
        self, state: BinarySearchState, achieved_cpu: float
    ) -> BinarySearchState:
        """Adjust search bounds based on achieved CPU."""
        if achieved_cpu < state.target_cpu:
            # Need more threads to increase CPU
            new_min = state.current_threads + 1
            new_max = state.max_threads
        else:
            # Need fewer threads to decrease CPU
            new_min = state.min_threads
            new_max = state.current_threads - 1

        new_current = (new_min + new_max) // 2

        return BinarySearchState(
            min_threads=new_min,
            max_threads=new_max,
            current_threads=new_current,
            target_cpu=state.target_cpu,
            tolerance=state.tolerance,
            best_threads=state.best_threads,
            best_cpu=state.best_cpu,
            best_diff=state.best_diff,
            iterations=state.iterations,
            runs=state.runs,
        )

    def calculate_iteration_stats(self, timings: List[float]) -> Optional[IterationStats]:
        """Calculate iteration timing statistics."""
        if not timings:
            return None

        sorted_timings = sorted(timings)
        count = len(sorted_timings)

        if count == 1:
            val = sorted_timings[0]
            return IterationStats(
                sample_count=1,
                avg_ms=val,
                stddev_ms=0.0,
                min_ms=val,
                max_ms=val,
                p50_ms=val,
                p90_ms=val,
                p99_ms=val,
            )

        return IterationStats(
            sample_count=count,
            avg_ms=statistics.mean(sorted_timings),
            stddev_ms=statistics.stdev(sorted_timings),
            min_ms=min(sorted_timings),
            max_ms=max(sorted_timings),
            p50_ms=self._percentile(sorted_timings, 50),
            p90_ms=self._percentile(sorted_timings, 90),
            p99_ms=self._percentile(sorted_timings, 99),
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

    def estimate_loop_count(
        self,
        duration_sec: int,
        avg_iteration_ms: float,
        buffer_percent: float = 10.0,
    ) -> int:
        """
        Estimate loop count for a given duration.

        Args:
            duration_sec: Target duration in seconds
            avg_iteration_ms: Average iteration time in milliseconds
            buffer_percent: Buffer percentage to ensure test doesn't finish early

        Returns:
            Estimated loop count
        """
        if avg_iteration_ms <= 0:
            return 1000  # Default fallback

        duration_ms = duration_sec * 1000
        estimated_loops = duration_ms / avg_iteration_ms

        # Add buffer
        buffer_multiplier = 1 + (buffer_percent / 100)
        loop_count = int(estimated_loops * buffer_multiplier)

        return max(1, loop_count)
