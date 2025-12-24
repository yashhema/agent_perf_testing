"""Unit tests for JMeter process manager."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.jmeter.manager import JMeterManager, JMeterConfig, ProcessStatus


class TestJMeterManager:
    """Unit tests for JMeter process manager."""

    @pytest.fixture
    def manager(self, tmp_path) -> JMeterManager:
        """Create a manager with temp directories."""
        return JMeterManager(
            jmeter_home=str(tmp_path / "jmeter"),
            output_dir=str(tmp_path / "output"),
        )

    def test_port_allocation(self, manager: JMeterManager) -> None:
        """Test port allocation from pool."""
        port1 = manager._allocate_port()
        port2 = manager._allocate_port()

        assert port1 != port2
        assert port1 in range(4445, 4500)
        assert port2 in range(4445, 4500)

    def test_port_allocation_specific(self, manager: JMeterManager) -> None:
        """Test specific port allocation."""
        port = manager._allocate_port(requested_port=5000)

        assert port == 5000
        assert 5000 in manager._used_ports

    def test_port_allocation_conflict(self, manager: JMeterManager) -> None:
        """Test port allocation conflict."""
        manager._allocate_port(requested_port=5000)

        with pytest.raises(ValueError, match="already in use"):
            manager._allocate_port(requested_port=5000)

    def test_port_release(self, manager: JMeterManager) -> None:
        """Test port release."""
        port = manager._allocate_port()
        manager._release_port(port)

        assert port not in manager._used_ports

    def test_get_status_not_found(self, manager: JMeterManager) -> None:
        """Test get status for non-existent target."""
        status = manager.get_status(target_id=999)

        assert status is None

    def test_get_all_processes_empty(self, manager: JMeterManager) -> None:
        """Test get all processes when none exist."""
        processes = manager.get_all_processes()

        assert processes == []

    def test_get_running_processes_empty(self, manager: JMeterManager) -> None:
        """Test get running processes when none exist."""
        processes = manager.get_running_processes()

        assert processes == []

    def test_is_jmeter_available_not_found(self, manager: JMeterManager) -> None:
        """Test JMeter availability when not installed."""
        assert manager.is_jmeter_available() is False

    def test_get_jmeter_version_not_available(self, manager: JMeterManager) -> None:
        """Test get version when JMeter not available."""
        version = manager.get_jmeter_version()

        assert version is None

    @pytest.mark.asyncio
    async def test_stop_jmeter_not_found(self, manager: JMeterManager) -> None:
        """Test stopping non-existent process."""
        result = await manager.stop_jmeter(target_id=999)

        assert result is False

    def test_cleanup_completed_empty(self, manager: JMeterManager) -> None:
        """Test cleanup when no completed processes."""
        count = manager.cleanup_completed()

        assert count == 0


class TestJMeterConfig:
    """Unit tests for JMeterConfig."""

    def test_config_creation(self) -> None:
        """Test creating JMeter config."""
        config = JMeterConfig(
            target_id=1,
            test_run_id="test-123",
            jmx_file="/path/to/test.jmx",
            thread_count=10,
            ramp_up_sec=60,
            loop_count=-1,
            duration_sec=300,
            emulator_host="localhost",
            emulator_port=8080,
            jmeter_port=4445,
        )

        assert config.target_id == 1
        assert config.thread_count == 10
        assert config.jmeter_port == 4445

    def test_config_with_additional_props(self) -> None:
        """Test config with additional properties."""
        config = JMeterConfig(
            target_id=1,
            test_run_id="test-123",
            jmx_file="/path/to/test.jmx",
            thread_count=10,
            ramp_up_sec=60,
            loop_count=-1,
            duration_sec=None,
            emulator_host="localhost",
            emulator_port=8080,
            jmeter_port=4445,
            additional_props={"custom_prop": "value"},
        )

        assert config.additional_props == {"custom_prop": "value"}

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = JMeterConfig(
            target_id=1,
            test_run_id="test-123",
            jmx_file="/path/to/test.jmx",
            thread_count=10,
            ramp_up_sec=60,
            loop_count=-1,
            duration_sec=None,
            emulator_host="localhost",
            emulator_port=8080,
            jmeter_port=4445,
        )

        with pytest.raises(AttributeError):
            config.target_id = 2


class TestProcessStatus:
    """Unit tests for ProcessStatus enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert ProcessStatus.PENDING.value == "pending"
        assert ProcessStatus.RUNNING.value == "running"
        assert ProcessStatus.STOPPED.value == "stopped"
        assert ProcessStatus.COMPLETED.value == "completed"
        assert ProcessStatus.FAILED.value == "failed"
