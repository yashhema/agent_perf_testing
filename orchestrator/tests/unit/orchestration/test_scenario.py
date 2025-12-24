"""Unit tests for scenario orchestrator."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from app.orchestration.models import (
    ServerSetup,
    ScenarioPhase,
    SetupStatus,
    CalibrationData,
    ServerCalibration,
)
from app.orchestration.scenario import (
    ScenarioOrchestrator,
    ScenarioConfig,
    ScenarioResult,
)
from app.calibration.models import (
    CalibrationResult,
    CalibrationStatus,
    LoadProfile,
)


class TestServerSetup:
    """Tests for ServerSetup model."""

    def test_create_server_setup(self):
        """Test creating server setup."""
        server = ServerSetup(
            server_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
        )

        assert server.server_id == 1
        assert server.hostname == "test-server"
        assert server.ip_address == "192.168.1.100"
        assert server.emulator_port == 8080
        assert server.os_type == "linux"

    def test_server_setup_immutable(self):
        """Test ServerSetup is immutable."""
        server = ServerSetup(
            server_id=1,
            hostname="test-server",
            ip_address="192.168.1.100",
        )

        with pytest.raises(Exception):
            server.server_id = 2


class TestServerCalibration:
    """Tests for ServerCalibration model."""

    def test_get_thread_count(self):
        """Test getting thread count for profile."""
        cal = ServerCalibration(server_id=1)
        cal.low = CalibrationData(
            server_id=1,
            profile="low",
            thread_count=8,
            target_cpu_percent=30.0,
            achieved_cpu_percent=29.5,
            calibrated_at=datetime.utcnow(),
            duration_sec=60.0,
            is_valid=True,
            validation_message="Valid",
        )

        assert cal.get_thread_count("low") == 8
        assert cal.get_thread_count("medium") is None

    def test_is_complete(self):
        """Test checking if all profiles calibrated."""
        cal = ServerCalibration(server_id=1)
        assert cal.is_complete() is False

        now = datetime.utcnow()
        cal.low = CalibrationData(
            server_id=1, profile="low", thread_count=8,
            target_cpu_percent=30.0, achieved_cpu_percent=29.5,
            calibrated_at=now, duration_sec=60.0,
            is_valid=True, validation_message="Valid",
        )
        cal.medium = CalibrationData(
            server_id=1, profile="medium", thread_count=16,
            target_cpu_percent=50.0, achieved_cpu_percent=49.5,
            calibrated_at=now, duration_sec=60.0,
            is_valid=True, validation_message="Valid",
        )
        cal.high = CalibrationData(
            server_id=1, profile="high", thread_count=24,
            target_cpu_percent=70.0, achieved_cpu_percent=69.5,
            calibrated_at=now, duration_sec=60.0,
            is_valid=True, validation_message="Valid",
        )

        assert cal.is_complete() is True


class TestScenarioConfig:
    """Tests for ScenarioConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ScenarioConfig()

        assert config.calibration_duration_sec == 60
        assert config.warmup_sec == 10
        assert config.tolerance_percent == 5.0
        assert config.max_retries == 2
        assert config.profiles == ["low", "medium", "high"]


class TestScenarioOrchestrator:
    """Tests for ScenarioOrchestrator."""

    @pytest.fixture
    def servers(self):
        """Create test servers."""
        return [
            ServerSetup(
                server_id=1,
                hostname="server-1",
                ip_address="192.168.1.101",
                cpu_count=8,
                memory_gb=16.0,
            ),
            ServerSetup(
                server_id=2,
                hostname="server-2",
                ip_address="192.168.1.102",
                cpu_count=4,
                memory_gb=8.0,
            ),
        ]

    @pytest.fixture
    def mock_calibration_result(self):
        """Create mock calibration result."""
        def create_result(
            target_id: int,
            loadprofile: LoadProfile,
            thread_count: int,
        ):
            target_cpu = {
                LoadProfile.LOW: 30.0,
                LoadProfile.MEDIUM: 50.0,
                LoadProfile.HIGH: 70.0,
            }[loadprofile]

            return CalibrationResult(
                target_id=target_id,
                baseline_id=0,
                loadprofile=loadprofile,
                status=CalibrationStatus.COMPLETED,
                thread_count=thread_count,
                cpu_target_percent=target_cpu,
                achieved_cpu_percent=target_cpu - 0.5,
            )
        return create_result

    @pytest.mark.asyncio
    async def test_setup_scenario_success(self, servers, mock_calibration_result):
        """Test successful scenario setup."""
        orchestrator = ScenarioOrchestrator()

        # Mock emulator client health check
        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            # Mock calibration service
            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
            ) as mock_calibrate:
                async def calibrate_side_effect(**kwargs):
                    return mock_calibration_result(
                        target_id=kwargs["target_id"],
                        loadprofile=kwargs["loadprofile"],
                        thread_count=kwargs["cpu_count"] * 2,
                    )

                mock_calibrate.side_effect = calibrate_side_effect

                # Mock validation
                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(True, "Valid"),
                ):
                    result = await orchestrator.setup_scenario(servers)

        assert result.success is True
        assert result.phase == ScenarioPhase.READY
        assert len(result.calibrations) == 2

        # Check calibrations for each server
        for server in servers:
            cal = result.calibrations[server.server_id]
            assert cal.is_complete() is True

    @pytest.mark.asyncio
    async def test_setup_phase_parallel(self, servers):
        """Test that setup phase runs in parallel."""
        orchestrator = ScenarioOrchestrator()
        setup_times = []

        async def slow_health_check():
            import asyncio
            setup_times.append(datetime.utcnow())
            await asyncio.sleep(0.1)
            return True

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = slow_health_check
            mock_client_class.return_value = mock_client

            with patch.object(
                orchestrator,
                "_execute_calibration_phase",
                new_callable=AsyncMock,
            ):
                await orchestrator.setup_scenario(servers)

        # Both servers should start setup at nearly the same time
        assert len(setup_times) == 2
        time_diff = abs((setup_times[1] - setup_times[0]).total_seconds())
        assert time_diff < 0.05  # Less than 50ms apart = parallel

    @pytest.mark.asyncio
    async def test_calibration_barrier_per_profile(
        self, servers, mock_calibration_result
    ):
        """Test that calibration waits for all servers per profile."""
        orchestrator = ScenarioOrchestrator()
        profile_completions = []

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            async def track_calibration(**kwargs):
                profile_completions.append(kwargs["loadprofile"])
                return mock_calibration_result(
                    target_id=kwargs["target_id"],
                    loadprofile=kwargs["loadprofile"],
                    thread_count=16,
                )

            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
                side_effect=track_calibration,
            ):
                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(True, "Valid"),
                ):
                    await orchestrator.setup_scenario(servers)

        # Should have 6 calibrations: 2 servers x 3 profiles
        assert len(profile_completions) == 6

        # LOW should complete for both servers before MEDIUM starts
        low_indices = [i for i, p in enumerate(profile_completions) if p == LoadProfile.LOW]
        medium_indices = [i for i, p in enumerate(profile_completions) if p == LoadProfile.MEDIUM]

        assert max(low_indices) < min(medium_indices)

    @pytest.mark.asyncio
    async def test_setup_failure_stops_scenario(self, servers):
        """Test that setup failure stops the scenario."""
        orchestrator = ScenarioOrchestrator(
            config=ScenarioConfig(max_retries=0)
        )

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            result = await orchestrator.setup_scenario(servers)

        assert result.success is False
        assert result.phase == ScenarioPhase.FAILED
        assert "setup" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_calibration_failure_stops_profile(
        self, servers, mock_calibration_result
    ):
        """Test that calibration failure stops at that profile."""
        orchestrator = ScenarioOrchestrator()

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            call_count = 0

            async def fail_on_medium(**kwargs):
                nonlocal call_count
                call_count += 1
                if kwargs["loadprofile"] == LoadProfile.MEDIUM:
                    raise RuntimeError("Calibration failed")
                return mock_calibration_result(
                    target_id=kwargs["target_id"],
                    loadprofile=kwargs["loadprofile"],
                    thread_count=16,
                )

            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
                side_effect=fail_on_medium,
            ):
                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(True, "Valid"),
                ):
                    result = await orchestrator.setup_scenario(servers)

        assert result.success is False
        assert result.phase == ScenarioPhase.FAILED
        # Should have completed LOW but failed on MEDIUM
        assert "MEDIUM" in result.error_message

    @pytest.mark.asyncio
    async def test_get_thread_count_after_calibration(
        self, servers, mock_calibration_result
    ):
        """Test getting thread count after calibration."""
        orchestrator = ScenarioOrchestrator()

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
            ) as mock_calibrate:
                async def calibrate_side_effect(**kwargs):
                    thread_map = {
                        LoadProfile.LOW: 8,
                        LoadProfile.MEDIUM: 16,
                        LoadProfile.HIGH: 24,
                    }
                    return mock_calibration_result(
                        target_id=kwargs["target_id"],
                        loadprofile=kwargs["loadprofile"],
                        thread_count=thread_map[kwargs["loadprofile"]],
                    )

                mock_calibrate.side_effect = calibrate_side_effect

                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(True, "Valid"),
                ):
                    await orchestrator.setup_scenario(servers)

        # Get calibrated thread counts
        assert orchestrator.get_thread_count(1, "low") == 8
        assert orchestrator.get_thread_count(1, "medium") == 16
        assert orchestrator.get_thread_count(1, "high") == 24
        assert orchestrator.get_thread_count(2, "low") == 8

    @pytest.mark.asyncio
    async def test_progress_callback(self, servers, mock_calibration_result):
        """Test that progress callback is called."""
        progress_updates = []

        async def progress_callback(state):
            progress_updates.append(state.phase)

        orchestrator = ScenarioOrchestrator(progress_callback=progress_callback)

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
            ) as mock_calibrate:
                mock_calibrate.side_effect = lambda **kwargs: mock_calibration_result(
                    target_id=kwargs["target_id"],
                    loadprofile=kwargs["loadprofile"],
                    thread_count=16,
                )

                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(True, "Valid"),
                ):
                    await orchestrator.setup_scenario(servers)

        # Should have received progress updates
        assert len(progress_updates) > 0
        assert ScenarioPhase.SETUP in progress_updates
        assert ScenarioPhase.CALIBRATION in progress_updates


class TestScenarioValidation:
    """Tests for scenario validation."""

    @pytest.fixture
    def servers(self):
        """Create test servers."""
        return [
            ServerSetup(
                server_id=1,
                hostname="server-1",
                ip_address="192.168.1.101",
            ),
        ]

    @pytest.mark.asyncio
    async def test_validation_failure_stops_scenario(self, servers):
        """Test that validation failure stops the scenario."""
        orchestrator = ScenarioOrchestrator()

        with patch("app.calibration.emulator_client.EmulatorClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=True)
            mock_client_class.return_value = mock_client

            with patch.object(
                orchestrator._calibration_service,
                "calibrate_target",
            ) as mock_calibrate:
                mock_calibrate.return_value = CalibrationResult(
                    target_id=1,
                    baseline_id=0,
                    loadprofile=LoadProfile.LOW,
                    status=CalibrationStatus.COMPLETED,
                    thread_count=8,
                    cpu_target_percent=30.0,
                    achieved_cpu_percent=29.5,
                )

                # Fail validation
                with patch.object(
                    orchestrator._calibration_service,
                    "validate_calibration",
                    return_value=(False, "CPU outside tolerance"),
                ):
                    result = await orchestrator.setup_scenario(servers)

        assert result.success is False
        assert "tolerance" in result.error_message.lower()
