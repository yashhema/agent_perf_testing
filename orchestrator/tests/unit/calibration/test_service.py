"""Unit tests for calibration service."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.calibration.service import CalibrationService
from app.calibration.models import (
    CalibrationConfig,
    CalibrationResult,
    CalibrationRun,
    CalibrationStatus,
    IterationStats,
    LoadProfile,
)


class TestCalibrationServiceInit:
    """Tests for CalibrationService initialization."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        service = CalibrationService()

        assert service.config is not None
        assert isinstance(service.config, CalibrationConfig)
        assert service.config.cpu_target_medium == 50.0

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = CalibrationConfig(
            cpu_target_low=25.0,
            cpu_target_medium=45.0,
            cpu_target_high=65.0,
        )
        service = CalibrationService(config=config)

        assert service.config.cpu_target_low == 25.0
        assert service.config.cpu_target_medium == 45.0
        assert service.config.cpu_target_high == 65.0

    def test_config_property(self):
        """Test config property."""
        config = CalibrationConfig(tolerance=3.0)
        service = CalibrationService(config=config)

        assert service.config.tolerance == 3.0


class TestCalibrateTarget:
    """Tests for calibrate_target method."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return CalibrationService()

    @pytest.mark.asyncio
    async def test_calibrate_target_emulator_unreachable(self, service):
        """Test calibration when emulator is unreachable."""
        with patch(
            "app.calibration.service.EmulatorClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await service.calibrate_target(
                target_id=1,
                baseline_id=100,
                loadprofile=LoadProfile.MEDIUM,
                emulator_host="localhost",
                emulator_port=8080,
            )

            assert result.status == CalibrationStatus.FAILED
            assert result.thread_count == 0
            assert "not reachable" in result.error_message

    @pytest.mark.asyncio
    async def test_calibrate_target_success(self, service):
        """Test successful calibration."""
        mock_iteration_stats = IterationStats(
            sample_count=100,
            avg_ms=50.0,
            stddev_ms=5.0,
            min_ms=40.0,
            max_ms=60.0,
            p50_ms=50.0,
            p90_ms=55.0,
            p99_ms=58.0,
        )

        with patch(
            "app.calibration.service.EmulatorClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client.run_calibration_test = AsyncMock(return_value=(50.0, {}))
            mock_client_class.return_value = mock_client

            with patch.object(
                service._algorithm,
                "calibrate",
                new_callable=AsyncMock,
                return_value=(15, 50.0, []),
            ):
                result = await service.calibrate_target(
                    target_id=1,
                    baseline_id=100,
                    loadprofile=LoadProfile.MEDIUM,
                    emulator_host="localhost",
                    emulator_port=8080,
                    cpu_count=8,
                    memory_gb=16.0,
                )

                assert result.status == CalibrationStatus.COMPLETED
                assert result.thread_count == 15
                assert result.achieved_cpu_percent == 50.0
                assert result.cpu_count == 8
                assert result.memory_gb == 16.0

    @pytest.mark.asyncio
    async def test_calibrate_target_high_profile_with_timing(self, service):
        """Test HIGH profile calibration includes timing data."""
        mock_timings = [45.0, 50.0, 55.0, 48.0, 52.0]

        with patch(
            "app.calibration.service.EmulatorClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client.run_calibration_test = AsyncMock(return_value=(70.0, {}))
            mock_client.run_timing_test = AsyncMock(return_value=mock_timings)
            mock_client_class.return_value = mock_client

            with patch.object(
                service._algorithm,
                "calibrate",
                new_callable=AsyncMock,
                return_value=(20, 70.0, []),
            ):
                result = await service.calibrate_target(
                    target_id=1,
                    baseline_id=100,
                    loadprofile=LoadProfile.HIGH,
                    emulator_host="localhost",
                    emulator_port=8080,
                )

                assert result.status == CalibrationStatus.COMPLETED
                assert result.loadprofile == LoadProfile.HIGH
                assert result.avg_iteration_time_ms is not None
                mock_client.run_timing_test.assert_called_once()

    @pytest.mark.asyncio
    async def test_calibrate_target_exception(self, service):
        """Test calibration handles exceptions."""
        with patch(
            "app.calibration.service.EmulatorClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            with patch.object(
                service._algorithm,
                "calibrate",
                new_callable=AsyncMock,
                side_effect=Exception("Calibration error"),
            ):
                result = await service.calibrate_target(
                    target_id=1,
                    baseline_id=100,
                    loadprofile=LoadProfile.MEDIUM,
                    emulator_host="localhost",
                    emulator_port=8080,
                )

                assert result.status == CalibrationStatus.FAILED
                assert "Calibration error" in result.error_message

    @pytest.mark.asyncio
    async def test_calibrate_target_stores_runs(self, service):
        """Test calibration stores all runs."""
        runs = [
            CalibrationRun(
                thread_count=50,
                target_cpu_percent=50.0,
                achieved_cpu_percent=45.0,
                duration_sec=60,
                within_tolerance=False,
            ),
            CalibrationRun(
                thread_count=60,
                target_cpu_percent=50.0,
                achieved_cpu_percent=52.0,
                duration_sec=60,
                within_tolerance=True,
            ),
        ]

        with patch(
            "app.calibration.service.EmulatorClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client.run_calibration_test = AsyncMock(return_value=(52.0, {}))
            mock_client_class.return_value = mock_client

            with patch.object(
                service._algorithm,
                "calibrate",
                new_callable=AsyncMock,
                return_value=(60, 52.0, runs),
            ):
                result = await service.calibrate_target(
                    target_id=1,
                    baseline_id=100,
                    loadprofile=LoadProfile.MEDIUM,
                    emulator_host="localhost",
                    emulator_port=8080,
                )

                assert len(result.calibration_runs) == 2
                assert result.calibration_runs[0].thread_count == 50
                assert result.calibration_runs[1].thread_count == 60


class TestCalibrateAllProfiles:
    """Tests for calibrate_all_profiles method."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return CalibrationService()

    @pytest.mark.asyncio
    async def test_calibrate_all_profiles_default(self, service):
        """Test calibrating all profiles by default."""
        with patch.object(
            service,
            "calibrate_target",
            new_callable=AsyncMock,
        ) as mock_calibrate:
            mock_calibrate.return_value = CalibrationResult(
                target_id=1,
                baseline_id=100,
                loadprofile=LoadProfile.LOW,
                status=CalibrationStatus.COMPLETED,
                thread_count=10,
                cpu_target_percent=30.0,
                achieved_cpu_percent=30.0,
            )

            results = await service.calibrate_all_profiles(
                target_id=1,
                baseline_id=100,
                emulator_host="localhost",
                emulator_port=8080,
            )

            assert len(results) == 3
            assert mock_calibrate.call_count == 3

    @pytest.mark.asyncio
    async def test_calibrate_specific_profiles(self, service):
        """Test calibrating specific profiles."""
        with patch.object(
            service,
            "calibrate_target",
            new_callable=AsyncMock,
        ) as mock_calibrate:
            mock_calibrate.return_value = CalibrationResult(
                target_id=1,
                baseline_id=100,
                loadprofile=LoadProfile.LOW,
                status=CalibrationStatus.COMPLETED,
                thread_count=10,
                cpu_target_percent=30.0,
                achieved_cpu_percent=30.0,
            )

            results = await service.calibrate_all_profiles(
                target_id=1,
                baseline_id=100,
                emulator_host="localhost",
                emulator_port=8080,
                profiles=[LoadProfile.LOW, LoadProfile.HIGH],
            )

            assert len(results) == 2
            assert mock_calibrate.call_count == 2

    @pytest.mark.asyncio
    async def test_calibrate_all_profiles_passes_hardware_info(self, service):
        """Test that hardware info is passed to calibrate_target."""
        with patch.object(
            service,
            "calibrate_target",
            new_callable=AsyncMock,
        ) as mock_calibrate:
            mock_calibrate.return_value = CalibrationResult(
                target_id=1,
                baseline_id=100,
                loadprofile=LoadProfile.LOW,
                status=CalibrationStatus.COMPLETED,
                thread_count=10,
                cpu_target_percent=30.0,
                achieved_cpu_percent=30.0,
            )

            await service.calibrate_all_profiles(
                target_id=1,
                baseline_id=100,
                emulator_host="localhost",
                emulator_port=8080,
                profiles=[LoadProfile.MEDIUM],
                cpu_count=8,
                memory_gb=16.0,
            )

            mock_calibrate.assert_called_once()
            call_kwargs = mock_calibrate.call_args.kwargs
            assert call_kwargs["cpu_count"] == 8
            assert call_kwargs["memory_gb"] == 16.0


class TestEstimateTestLoops:
    """Tests for estimate_test_loops method."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return CalibrationService()

    def test_estimate_with_timing_data(self, service):
        """Test loop estimation with timing data."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.HIGH,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=70.0,
            achieved_cpu_percent=70.0,
            avg_iteration_time_ms=50,
        )

        loops = service.estimate_test_loops(
            calibration_result=result,
            test_duration_sec=60,
        )

        # 60 seconds / 50ms = 1200 iterations, plus buffer
        assert loops > 1200

    def test_estimate_without_timing_data(self, service):
        """Test loop estimation without timing data uses default."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=50.0,
            avg_iteration_time_ms=None,  # No timing data
        )

        loops = service.estimate_test_loops(
            calibration_result=result,
            test_duration_sec=60,
        )

        # Uses default 100ms assumption
        # 60 seconds / 100ms = 600 iterations, plus buffer
        assert loops > 600


class TestValidateCalibration:
    """Tests for validate_calibration method."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return CalibrationService()

    def test_validate_failed_calibration(self, service):
        """Test validation of failed calibration."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.FAILED,
            thread_count=0,
            cpu_target_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Connection failed",
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is False
        assert "not completed" in message

    def test_validate_invalid_thread_count(self, service):
        """Test validation with invalid thread count."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=0,  # Invalid
            cpu_target_percent=50.0,
            achieved_cpu_percent=50.0,
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is False
        assert "Invalid thread count" in message

    def test_validate_outside_tolerance(self, service):
        """Test validation when outside tolerance."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=60.0,  # 10% off, tolerance is 5%
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is False
        assert "outside tolerance" in message

    def test_validate_high_profile_without_timing(self, service):
        """Test validation of HIGH profile without timing data."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.HIGH,
            status=CalibrationStatus.COMPLETED,
            thread_count=20,
            cpu_target_percent=70.0,
            achieved_cpu_percent=70.0,
            avg_iteration_time_ms=None,  # Missing timing
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is False
        assert "iteration timing" in message

    def test_validate_valid_low_profile(self, service):
        """Test validation of valid LOW profile result."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.LOW,
            status=CalibrationStatus.COMPLETED,
            thread_count=5,
            cpu_target_percent=30.0,
            achieved_cpu_percent=28.0,  # Within tolerance
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is True
        assert "valid" in message.lower()

    def test_validate_valid_medium_profile(self, service):
        """Test validation of valid MEDIUM profile result."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=52.0,  # Within tolerance
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is True
        assert "valid" in message.lower()

    def test_validate_valid_high_profile(self, service):
        """Test validation of valid HIGH profile result."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.HIGH,
            status=CalibrationStatus.COMPLETED,
            thread_count=20,
            cpu_target_percent=70.0,
            achieved_cpu_percent=71.0,  # Within tolerance
            avg_iteration_time_ms=50,  # Has timing
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is True
        assert "valid" in message.lower()

    def test_validate_at_exact_tolerance_boundary(self, service):
        """Test validation at exact tolerance boundary."""
        result = CalibrationResult(
            target_id=1,
            baseline_id=100,
            loadprofile=LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=15,
            cpu_target_percent=50.0,
            achieved_cpu_percent=55.0,  # Exactly at 5% tolerance
        )

        is_valid, message = service.validate_calibration(result)

        assert is_valid is True  # At boundary should still be valid
