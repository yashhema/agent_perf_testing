"""Unit tests for calibration algorithm."""

import pytest
from unittest.mock import AsyncMock

from app.calibration.algorithm import CalibrationAlgorithm, BinarySearchState
from app.calibration.models import CalibrationConfig, LoadProfile


class TestBinarySearchState:
    """Tests for BinarySearchState dataclass."""

    def test_create_state(self):
        """Test creating BinarySearchState."""
        state = BinarySearchState(
            min_threads=1,
            max_threads=100,
            current_threads=50,
            target_cpu=50.0,
            tolerance=5.0,
            best_threads=1,
            best_cpu=0.0,
            best_diff=float("inf"),
            iterations=0,
            runs=[],
        )

        assert state.min_threads == 1
        assert state.max_threads == 100
        assert state.current_threads == 50
        assert state.target_cpu == 50.0
        assert state.tolerance == 5.0
        assert state.best_threads == 1
        assert state.best_cpu == 0.0
        assert state.best_diff == float("inf")
        assert state.iterations == 0
        assert state.runs == []


class TestCalibrationAlgorithm:
    """Tests for CalibrationAlgorithm."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return CalibrationConfig(
            cpu_target_low=30.0,
            cpu_target_medium=50.0,
            cpu_target_high=70.0,
            tolerance=5.0,
            min_threads=1,
            max_threads=100,
            calibration_duration_sec=60,
            max_iterations=10,
        )

    @pytest.fixture
    def algorithm(self, config):
        """Create algorithm instance."""
        return CalibrationAlgorithm(config)

    def test_get_target_cpu_low(self, algorithm):
        """Test getting target CPU for LOW profile."""
        target = algorithm.get_target_cpu(LoadProfile.LOW)
        assert target == 30.0

    def test_get_target_cpu_medium(self, algorithm):
        """Test getting target CPU for MEDIUM profile."""
        target = algorithm.get_target_cpu(LoadProfile.MEDIUM)
        assert target == 50.0

    def test_get_target_cpu_high(self, algorithm):
        """Test getting target CPU for HIGH profile."""
        target = algorithm.get_target_cpu(LoadProfile.HIGH)
        assert target == 70.0

    @pytest.mark.asyncio
    async def test_calibrate_finds_optimal_threads(self, algorithm):
        """Test calibration finds optimal thread count."""
        # Simulate CPU that increases linearly with threads
        # 50 threads should give 50% CPU
        async def run_test(thread_count: int) -> float:
            return float(thread_count)

        optimal_threads, achieved_cpu, runs = await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # Should find threads close to 50 (target is 50%)
        assert 45 <= optimal_threads <= 55
        assert abs(achieved_cpu - 50.0) <= 5.0
        assert len(runs) > 0

    @pytest.mark.asyncio
    async def test_calibrate_within_tolerance(self, algorithm):
        """Test calibration stops when within tolerance."""
        call_count = 0

        async def run_test(thread_count: int) -> float:
            nonlocal call_count
            call_count += 1
            # First call returns exactly target
            return 50.0

        optimal_threads, achieved_cpu, runs = await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # Should stop after finding within tolerance
        assert call_count == 1
        assert achieved_cpu == 50.0
        assert len(runs) == 1
        assert runs[0].within_tolerance is True

    @pytest.mark.asyncio
    async def test_calibrate_respects_max_iterations(self, config):
        """Test calibration respects max iterations limit."""
        limited_config = CalibrationConfig(
            cpu_target_medium=50.0,
            tolerance=0.1,  # Very tight tolerance
            min_threads=1,
            max_threads=100,
            max_iterations=3,
        )
        algorithm = CalibrationAlgorithm(limited_config)

        call_count = 0

        async def run_test(thread_count: int) -> float:
            nonlocal call_count
            call_count += 1
            # Always return something outside tolerance
            return 40.0

        _, _, runs = await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # Should stop at max iterations
        assert call_count <= 3
        assert len(runs) <= 3

    @pytest.mark.asyncio
    async def test_calibrate_binary_search_adjusts_up(self, algorithm):
        """Test binary search adjusts upward when CPU is too low."""
        thread_counts = []

        async def run_test(thread_count: int) -> float:
            thread_counts.append(thread_count)
            # Always return low CPU to force upward search
            return 20.0

        await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # After finding low CPU, should search in higher range
        # Check that thread counts generally increase
        assert len(thread_counts) > 1
        assert thread_counts[1] > thread_counts[0]

    @pytest.mark.asyncio
    async def test_calibrate_binary_search_adjusts_down(self, algorithm):
        """Test binary search adjusts downward when CPU is too high."""
        thread_counts = []

        async def run_test(thread_count: int) -> float:
            thread_counts.append(thread_count)
            # Always return high CPU to force downward search
            return 80.0

        await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # After finding high CPU, should search in lower range
        # Check that thread counts generally decrease
        assert len(thread_counts) > 1
        assert thread_counts[1] < thread_counts[0]

    @pytest.mark.asyncio
    async def test_calibrate_tracks_best_result(self, algorithm):
        """Test calibration tracks best result."""
        results = [60.0, 45.0, 52.0, 49.0]  # Getting closer to 50
        call_idx = 0

        async def run_test(thread_count: int) -> float:
            nonlocal call_idx
            if call_idx < len(results):
                result = results[call_idx]
                call_idx += 1
                return result
            return 50.0

        optimal_threads, achieved_cpu, runs = await algorithm.calibrate(
            loadprofile=LoadProfile.MEDIUM,
            run_test=run_test,
        )

        # Should return best result (closest to target)
        assert abs(achieved_cpu - 50.0) <= 5.0

    def test_should_continue_respects_max_iterations(self, algorithm):
        """Test _should_continue respects max iterations."""
        state = BinarySearchState(
            min_threads=1,
            max_threads=100,
            current_threads=50,
            target_cpu=50.0,
            tolerance=5.0,
            best_threads=1,
            best_cpu=0.0,
            best_diff=float("inf"),
            iterations=10,  # At max
            runs=[],
        )

        assert algorithm._should_continue(state) is False

    def test_should_continue_stops_when_bounds_cross(self, algorithm):
        """Test _should_continue stops when bounds cross."""
        state = BinarySearchState(
            min_threads=51,  # min > max
            max_threads=50,
            current_threads=50,
            target_cpu=50.0,
            tolerance=5.0,
            best_threads=1,
            best_cpu=0.0,
            best_diff=float("inf"),
            iterations=5,
            runs=[],
        )

        assert algorithm._should_continue(state) is False

    def test_should_continue_continues_normally(self, algorithm):
        """Test _should_continue continues when conditions are met."""
        state = BinarySearchState(
            min_threads=1,
            max_threads=100,
            current_threads=50,
            target_cpu=50.0,
            tolerance=5.0,
            best_threads=1,
            best_cpu=0.0,
            best_diff=float("inf"),
            iterations=5,
            runs=[],
        )

        assert algorithm._should_continue(state) is True

    def test_adjust_search_increases_when_cpu_low(self, algorithm):
        """Test _adjust_search increases threads when CPU is low."""
        state = BinarySearchState(
            min_threads=1,
            max_threads=100,
            current_threads=50,
            target_cpu=70.0,
            tolerance=5.0,
            best_threads=50,
            best_cpu=40.0,
            best_diff=30.0,
            iterations=1,
            runs=[],
        )

        new_state = algorithm._adjust_search(state, achieved_cpu=40.0)

        # Should search in upper half
        assert new_state.min_threads == 51
        assert new_state.max_threads == 100
        assert new_state.current_threads == (51 + 100) // 2

    def test_adjust_search_decreases_when_cpu_high(self, algorithm):
        """Test _adjust_search decreases threads when CPU is high."""
        state = BinarySearchState(
            min_threads=1,
            max_threads=100,
            current_threads=50,
            target_cpu=30.0,
            tolerance=5.0,
            best_threads=50,
            best_cpu=60.0,
            best_diff=30.0,
            iterations=1,
            runs=[],
        )

        new_state = algorithm._adjust_search(state, achieved_cpu=60.0)

        # Should search in lower half
        assert new_state.min_threads == 1
        assert new_state.max_threads == 49
        assert new_state.current_threads == (1 + 49) // 2


class TestIterationStats:
    """Tests for iteration statistics calculation."""

    @pytest.fixture
    def algorithm(self):
        """Create algorithm instance."""
        return CalibrationAlgorithm(CalibrationConfig())

    def test_calculate_iteration_stats_empty_list(self, algorithm):
        """Test with empty list returns None."""
        stats = algorithm.calculate_iteration_stats([])
        assert stats is None

    def test_calculate_iteration_stats_single_value(self, algorithm):
        """Test with single value."""
        stats = algorithm.calculate_iteration_stats([100.0])

        assert stats is not None
        assert stats.sample_count == 1
        assert stats.avg_ms == 100.0
        assert stats.stddev_ms == 0.0
        assert stats.min_ms == 100.0
        assert stats.max_ms == 100.0
        assert stats.p50_ms == 100.0
        assert stats.p90_ms == 100.0
        assert stats.p99_ms == 100.0

    def test_calculate_iteration_stats_multiple_values(self, algorithm):
        """Test with multiple values."""
        timings = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        stats = algorithm.calculate_iteration_stats(timings)

        assert stats is not None
        assert stats.sample_count == 10
        assert stats.avg_ms == 55.0
        assert stats.min_ms == 10.0
        assert stats.max_ms == 100.0
        assert stats.p50_ms == 55.0  # Median

    def test_calculate_iteration_stats_unsorted_input(self, algorithm):
        """Test handles unsorted input correctly."""
        timings = [50.0, 10.0, 90.0, 30.0, 70.0]
        stats = algorithm.calculate_iteration_stats(timings)

        assert stats is not None
        assert stats.min_ms == 10.0
        assert stats.max_ms == 90.0

    def test_percentile_empty_list(self, algorithm):
        """Test percentile with empty list."""
        result = CalibrationAlgorithm._percentile([], 50)
        assert result == 0.0

    def test_percentile_single_value(self, algorithm):
        """Test percentile with single value."""
        result = CalibrationAlgorithm._percentile([100.0], 50)
        assert result == 100.0

    def test_percentile_p50(self, algorithm):
        """Test p50 percentile calculation."""
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = CalibrationAlgorithm._percentile(data, 50)
        assert result == 30.0

    def test_percentile_p90(self, algorithm):
        """Test p90 percentile calculation."""
        data = list(range(1, 101))  # 1 to 100
        data = [float(x) for x in data]
        result = CalibrationAlgorithm._percentile(data, 90)
        assert 89.0 <= result <= 91.0

    def test_percentile_p99(self, algorithm):
        """Test p99 percentile calculation."""
        data = list(range(1, 101))  # 1 to 100
        data = [float(x) for x in data]
        result = CalibrationAlgorithm._percentile(data, 99)
        assert 98.0 <= result <= 100.0


class TestLoopCountEstimation:
    """Tests for loop count estimation."""

    @pytest.fixture
    def algorithm(self):
        """Create algorithm instance."""
        return CalibrationAlgorithm(CalibrationConfig())

    def test_estimate_loop_count_basic(self, algorithm):
        """Test basic loop count estimation."""
        # 60 seconds, 100ms per iteration = 600 iterations
        # With 10% buffer = 660
        result = algorithm.estimate_loop_count(
            duration_sec=60,
            avg_iteration_ms=100.0,
        )

        assert result == 660

    def test_estimate_loop_count_custom_buffer(self, algorithm):
        """Test loop count with custom buffer."""
        # 60 seconds, 100ms per iteration = 600 iterations
        # With 20% buffer = 720
        result = algorithm.estimate_loop_count(
            duration_sec=60,
            avg_iteration_ms=100.0,
            buffer_percent=20.0,
        )

        assert result == 720

    def test_estimate_loop_count_zero_iteration_time(self, algorithm):
        """Test with zero iteration time returns fallback."""
        result = algorithm.estimate_loop_count(
            duration_sec=60,
            avg_iteration_ms=0.0,
        )

        assert result == 1000  # Default fallback

    def test_estimate_loop_count_negative_iteration_time(self, algorithm):
        """Test with negative iteration time returns fallback."""
        result = algorithm.estimate_loop_count(
            duration_sec=60,
            avg_iteration_ms=-10.0,
        )

        assert result == 1000  # Default fallback

    def test_estimate_loop_count_minimum_one(self, algorithm):
        """Test loop count is at least 1."""
        result = algorithm.estimate_loop_count(
            duration_sec=1,
            avg_iteration_ms=10000.0,  # Very slow iterations
        )

        assert result >= 1

    def test_estimate_loop_count_fast_iterations(self, algorithm):
        """Test with fast iterations."""
        # 10 seconds, 10ms per iteration = 1000 iterations
        # With 10% buffer = 1100
        result = algorithm.estimate_loop_count(
            duration_sec=10,
            avg_iteration_ms=10.0,
        )

        assert result == 1100
