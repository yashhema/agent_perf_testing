"""Unit tests for calibration models."""

import pytest
from datetime import datetime

from app.calibration.models import (
    CalibrationConfig,
    CalibrationResult,
    CalibrationRun,
    CalibrationStatus,
    IterationStats,
    LoadProfile,
)


class TestLoadProfile:
    """Tests for LoadProfile enum."""

    def test_load_profile_values(self):
        """Test LoadProfile enum values."""
        assert LoadProfile.LOW == "low"
        assert LoadProfile.MEDIUM == "medium"
        assert LoadProfile.HIGH == "high"

    def test_load_profile_is_string_enum(self):
        """Test LoadProfile is string enum."""
        assert isinstance(LoadProfile.LOW, str)
        assert isinstance(LoadProfile.MEDIUM, str)
        assert isinstance(LoadProfile.HIGH, str)


class TestCalibrationStatus:
    """Tests for CalibrationStatus enum."""

    def test_calibration_status_values(self):
        """Test CalibrationStatus enum values."""
        assert CalibrationStatus.PENDING == "pending"
        assert CalibrationStatus.RUNNING == "running"
        assert CalibrationStatus.COMPLETED == "completed"
        assert CalibrationStatus.FAILED == "failed"


class TestCalibrationConfig:
    """Tests for CalibrationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CalibrationConfig()

        assert config.cpu_target_low == 30.0
        assert config.cpu_target_medium == 50.0
        assert config.cpu_target_high == 70.0
        assert config.tolerance == 5.0
        assert config.min_threads == 1
        assert config.max_threads == 100
        assert config.calibration_duration_sec == 60
        assert config.max_iterations == 10
        assert config.warmup_sec == 10
        assert config.iteration_sample_count == 100

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CalibrationConfig(
            cpu_target_low=25.0,
            cpu_target_medium=45.0,
            cpu_target_high=65.0,
            tolerance=3.0,
            min_threads=2,
            max_threads=50,
        )

        assert config.cpu_target_low == 25.0
        assert config.cpu_target_medium == 45.0
        assert config.cpu_target_high == 65.0
        assert config.tolerance == 3.0
        assert config.min_threads == 2
        assert config.max_threads == 50

    def test_immutability(self):
        """Test CalibrationConfig is immutable."""
        config = CalibrationConfig()

        with pytest.raises(AttributeError):
            config.cpu_target_low = 40.0


class TestIterationStats:
    """Tests for IterationStats dataclass."""

    def test_create_iteration_stats(self):
        """Test creating IterationStats."""
        stats = IterationStats(
            sample_count=100,
            avg_ms=50.5,
            stddev_ms=5.2,
            min_ms=40.0,
            max_ms=65.0,
            p50_ms=50.0,
            p90_ms=58.0,
            p99_ms=63.0,
        )

        assert stats.sample_count == 100
        assert stats.avg_ms == 50.5
        assert stats.stddev_ms == 5.2
        assert stats.min_ms == 40.0
        assert stats.max_ms == 65.0
        assert stats.p50_ms == 50.0
        assert stats.p90_ms == 58.0
        assert stats.p99_ms == 63.0

    def test_immutability(self):
        """Test IterationStats is immutable."""
        stats = IterationStats(
            sample_count=100,
            avg_ms=50.5,
            stddev_ms=5.2,
            min_ms=40.0,
            max_ms=65.0,
            p50_ms=50.0,
            p90_ms=58.0,
            p99_ms=63.0,
        )

        with pytest.raises(AttributeError):
            stats.avg_ms = 60.0


class TestCalibrationRun:
    """Tests for CalibrationRun dataclass."""

    def test_create_calibration_run(self):
        """Test creating CalibrationRun."""
        run = CalibrationRun(
            thread_count=10,
            target_cpu_percent=50.0,
            achieved_cpu_percent=48.5,
            duration_sec=60,
            within_tolerance=True,
        )

        assert run.thread_count == 10
        assert run.target_cpu_percent == 50.0
        assert run.achieved_cpu_percent == 48.5
        assert run.duration_sec == 60
        assert run.within_tolerance is True
        assert run.iteration_stats is None

    def test_with_iteration_stats(self):
        """Test CalibrationRun with iteration stats."""
        stats = IterationStats(
            sample_count=100,
            avg_ms=50.0,
            stddev_ms=5.0,
            min_ms=40.0,
            max_ms=60.0,
            p50_ms=50.0,
            p90_ms=55.0,
            p99_ms=58.0,
        )

        run = CalibrationRun(
            thread_count=10,
            target_cpu_percent=50.0,
            achieved_cpu_percent=48.5,
            duration_sec=60,
            within_tolerance=True,
            iteration_stats=stats,
        )

        assert run.iteration_stats is not None
        assert run.iteration_stats.sample_count == 100

    def test_immutability(self):
        """Test CalibrationRun is immutable."""
        run = CalibrationRun(
            thread_count=10,
            target_cpu_percent=50.0,
            achieved_cpu_percent=48.5,
            duration_sec=60,
            within_tolerance=True,
        )

        with pytest.raises(AttributeError):
            run.thread_count = 20


class TestCalibrationResult:
    """Tests for CalibrationResult dataclass."""

    def test_create_minimal_result(self):
        """Test creating minimal CalibrationResult."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        assert result.target_id == 1
        assert result.baseline_id == 100
        assert result.loadprofile == LoadProfile.MEDIUM
        assert result.status == CalibrationStatus.COMPLETED
        assert result.thread_count == 15
        assert result.cpu_target_percent == 50.0
        assert result.achieved_cpu_percent == 49.5
        assert result.avg_iteration_time_ms is None
        assert result.calibrated_at is None
        assert result.calibration_runs == []
        assert result.error_message is None

    def test_create_full_result(self):
        """Test creating full CalibrationResult with all fields."""
        now = datetime.utcnow()
        runs = [
            CalibrationRun(
                thread_count=10,
                target_cpu_percent=70.0,
                achieved_cpu_percent=65.0,
                duration_sec=60,
                within_tolerance=False,
            ),
            CalibrationRun(
                thread_count=15,
                target_cpu_percent=70.0,
                achieved_cpu_percent=71.0,
                duration_sec=60,
                within_tolerance=True,
            ),
        ]

        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.HIGH,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=70.0,
            achieved_cpu_percent=71.0,
            avg_iteration_time_ms=50,
            stddev_iteration_time_ms=5,
            min_iteration_time_ms=40,
            max_iteration_time_ms=65,
            iteration_sample_count=100,
            calibrated_at=now,
            calibration_runs=runs,
            cpu_count=8,
            memory_gb=16.0,
        )

        assert result.avg_iteration_time_ms == 50
        assert result.stddev_iteration_time_ms == 5
        assert result.min_iteration_time_ms == 40
        assert result.max_iteration_time_ms == 65
        assert result.iteration_sample_count == 100
        assert result.calibrated_at == now
        assert len(result.calibration_runs) == 2
        assert result.cpu_count == 8
        assert result.memory_gb == 16.0

    def test_failed_result(self):
        """Test creating failed CalibrationResult."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.LOW,
            status=CalibrationStatus.FAILED,
            thread_count=0,
            cpu_target_percent=30.0,
            achieved_cpu_percent=0.0,
            error_message="Emulator is not reachable",
        )

        assert result.status == CalibrationStatus.FAILED
        assert result.thread_count == 0
        assert result.error_message == "Emulator is not reachable"

    def test_immutability(self):
        """Test CalibrationResult is immutable."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=49.5,
        )

        with pytest.raises(AttributeError):
            result.status = CalibrationStatus.FAILED
