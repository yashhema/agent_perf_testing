"""Unit tests for stats collector."""

import pytest

from app.stats.collector import StatsCollector, IterationTiming


class TestStatsCollector:
    """Unit tests for StatsCollector."""

    def test_record_single_iteration(self) -> None:
        """Test recording a single iteration."""
        collector = StatsCollector()
        collector.start()

        collector.record_iteration(100.0)
        timing = collector.get_iteration_timing()

        assert timing is not None
        assert timing.sample_count == 1
        assert timing.avg_ms == 100.0
        assert timing.min_ms == 100.0
        assert timing.max_ms == 100.0

    def test_record_multiple_iterations(self) -> None:
        """Test recording multiple iterations."""
        collector = StatsCollector()
        collector.start()

        collector.record_iteration(100.0)
        collector.record_iteration(200.0)
        collector.record_iteration(150.0)

        timing = collector.get_iteration_timing()

        assert timing is not None
        assert timing.sample_count == 3
        assert timing.avg_ms == 150.0
        assert timing.min_ms == 100.0
        assert timing.max_ms == 200.0

    def test_percentile_calculation(self) -> None:
        """Test percentile calculation."""
        collector = StatsCollector()
        collector.start()

        # Add 100 values from 1 to 100
        for i in range(1, 101):
            collector.record_iteration(float(i))

        timing = collector.get_iteration_timing()

        assert timing is not None
        assert timing.sample_count == 100
        assert timing.p50_ms == pytest.approx(50.5, rel=0.1)
        assert timing.p90_ms == pytest.approx(90.1, rel=0.1)
        assert timing.p99_ms == pytest.approx(99.01, rel=0.1)

    def test_clear_iteration_times(self) -> None:
        """Test clearing iteration times."""
        collector = StatsCollector()
        collector.start()

        collector.record_iteration(100.0)
        collector.record_iteration(200.0)

        collector.clear_iteration_times()
        timing = collector.get_iteration_timing()

        assert timing is None

    def test_get_iteration_timing_empty(self) -> None:
        """Test getting timing when no iterations recorded."""
        collector = StatsCollector()
        timing = collector.get_iteration_timing()

        assert timing is None

    @pytest.mark.asyncio
    async def test_get_system_stats(self) -> None:
        """Test getting system stats."""
        collector = StatsCollector()
        stats = await collector.get_system_stats()

        assert stats is not None
        assert stats.timestamp is not None
        # CPU percent should be between 0 and 100
        assert 0 <= stats.cpu_percent <= 100
        # Memory percent should be between 0 and 100
        assert 0 <= stats.memory_percent <= 100

    def test_stddev_single_sample(self) -> None:
        """Test standard deviation with single sample is zero."""
        collector = StatsCollector()
        collector.start()

        collector.record_iteration(100.0)
        timing = collector.get_iteration_timing()

        assert timing is not None
        assert timing.stddev_ms == 0.0

    def test_stddev_multiple_samples(self) -> None:
        """Test standard deviation with multiple samples."""
        collector = StatsCollector()
        collector.start()

        # Values with known stddev
        collector.record_iteration(100.0)
        collector.record_iteration(100.0)
        collector.record_iteration(100.0)

        timing = collector.get_iteration_timing()

        assert timing is not None
        assert timing.stddev_ms == 0.0  # All same values

    def test_start_clears_previous_data(self) -> None:
        """Test that start clears previous iteration data."""
        collector = StatsCollector()

        collector.record_iteration(100.0)
        collector.start()
        timing = collector.get_iteration_timing()

        assert timing is None
