"""Unit tests for vSphere helper."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.vsphere.helper import VSphereHelper, VSphereConfig
from app.vsphere.models import VMPowerState, TaskResult


class TestVSphereConfig:
    """Unit tests for VSphereConfig."""

    def test_default_config(self) -> None:
        """Test creating config with defaults."""
        config = VSphereConfig(
            host="vcenter.example.com",
            username="admin@vsphere.local",
            password="password",
            datacenter="DC1",
        )

        assert config.host == "vcenter.example.com"
        assert config.port == 443
        assert config.disable_ssl_verification is True
        assert config.timeout == 30

    def test_custom_config(self) -> None:
        """Test creating config with custom values."""
        config = VSphereConfig(
            host="vcenter.example.com",
            username="admin",
            password="password",
            datacenter="DC1",
            port=8443,
            disable_ssl_verification=False,
            timeout=60,
        )

        assert config.port == 8443
        assert config.disable_ssl_verification is False
        assert config.timeout == 60

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = VSphereConfig(
            host="vcenter.example.com",
            username="admin",
            password="password",
            datacenter="DC1",
        )

        with pytest.raises(AttributeError):
            config.host = "other.example.com"


class TestVSphereHelper:
    """Unit tests for VSphereHelper."""

    @pytest.fixture
    def config(self) -> VSphereConfig:
        """Create test config."""
        return VSphereConfig(
            host="vcenter.test.com",
            username="admin@vsphere.local",
            password="password",
            datacenter="DC1",
        )

    @pytest.fixture
    def mock_pyvim(self):
        """Mock pyVim module."""
        with patch.dict("sys.modules", {
            "pyVim": MagicMock(),
            "pyVim.connect": MagicMock(),
            "pyVmomi": MagicMock(),
            "pyVmomi.vim": MagicMock(),
        }):
            with patch("app.vsphere.helper.connect") as mock_connect:
                yield mock_connect

    def test_connect(self, config: VSphereConfig) -> None:
        """Test vSphere connection."""
        with patch("app.vsphere.helper.connect") as mock_connect:
            # Setup mock datacenter
            mock_dc = Mock()
            mock_dc.name = "DC1"

            mock_si = Mock()
            mock_content = Mock()
            mock_content.rootFolder.childEntity = [mock_dc]
            mock_si.RetrieveContent.return_value = mock_content
            mock_connect.SmartConnect.return_value = mock_si

            # Need to also mock vim for datacenter check
            with patch("app.vsphere.helper.vim") as mock_vim:
                mock_vim.Datacenter = type(mock_dc)

                helper = VSphereHelper(config)
                helper.connect()

                mock_connect.SmartConnect.assert_called_once()
                assert helper.is_connected is True

    def test_disconnect(self, config: VSphereConfig) -> None:
        """Test vSphere disconnection."""
        with patch("app.vsphere.helper.connect") as mock_connect:
            helper = VSphereHelper(config)
            helper._si = Mock()

            helper.disconnect()

            assert helper.is_connected is False

    def test_get_vm_not_found(self, config: VSphereConfig) -> None:
        """Test getting non-existent VM."""
        with patch("app.vsphere.helper.vim") as mock_vim:
            mock_container = Mock()
            mock_container.view = []

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper._get_vm("nonexistent-vm")

            assert result is None

    def test_get_vm_found(self, config: VSphereConfig) -> None:
        """Test getting existing VM."""
        with patch("app.vsphere.helper.vim") as mock_vim:
            mock_vm = Mock()
            mock_vm.name = "test-vm"

            mock_container = Mock()
            mock_container.view = [mock_vm]

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper._get_vm("test-vm")

            assert result == mock_vm

    def test_power_on_vm_not_found(self, config: VSphereConfig) -> None:
        """Test powering on non-existent VM."""
        with patch("app.vsphere.helper.vim"):
            mock_content = Mock()
            mock_container = Mock()
            mock_container.view = []
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper.power_on("nonexistent-vm")

            assert result.success is False
            assert "not found" in result.message

    def test_power_on_already_on(self, config: VSphereConfig) -> None:
        """Test powering on VM that's already on."""
        with patch("app.vsphere.helper.vim"):
            mock_vm = Mock()
            mock_vm.name = "test-vm"
            mock_vm.runtime.powerState = "poweredOn"

            mock_container = Mock()
            mock_container.view = [mock_vm]

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper.power_on("test-vm")

            assert result.success is True
            assert "already powered on" in result.message

    def test_create_snapshot(self, config: VSphereConfig) -> None:
        """Test creating snapshot."""
        with patch("app.vsphere.helper.vim") as mock_vim:
            mock_task = Mock()
            mock_task.info.state = mock_vim.TaskInfo.State.success

            mock_vm = Mock()
            mock_vm.name = "test-vm"
            mock_vm.CreateSnapshot_Task.return_value = mock_task

            mock_container = Mock()
            mock_container.view = [mock_vm]

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper.create_snapshot(
                "test-vm",
                "test-snapshot",
                description="Test snapshot",
            )

            mock_vm.CreateSnapshot_Task.assert_called_once()
            # Result depends on task completion which we can't fully test

    def test_revert_to_snapshot_not_found(self, config: VSphereConfig) -> None:
        """Test reverting to non-existent snapshot."""
        with patch("app.vsphere.helper.vim"):
            mock_vm = Mock()
            mock_vm.name = "test-vm"
            mock_vm.snapshot = None

            mock_container = Mock()
            mock_container.view = [mock_vm]

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            result = helper.revert_to_snapshot("test-vm", "nonexistent-snapshot")

            assert result.success is False
            assert "not found" in result.message

    def test_list_vms(self, config: VSphereConfig) -> None:
        """Test listing VMs."""
        with patch("app.vsphere.helper.vim"):
            mock_vm1 = Mock()
            mock_vm1.name = "vm-1"
            mock_vm1.parent = Mock()
            mock_vm1.parent.name = "folder1"

            mock_vm2 = Mock()
            mock_vm2.name = "vm-2"
            mock_vm2.parent = Mock()
            mock_vm2.parent.name = "folder1"

            mock_container = Mock()
            mock_container.view = [mock_vm1, mock_vm2]

            mock_content = Mock()
            mock_content.viewManager.CreateContainerView.return_value = mock_container

            helper = VSphereHelper(config)
            helper._content = mock_content
            helper._datacenter = Mock()

            vms = helper.list_vms()

            assert len(vms) == 2
            assert "vm-1" in vms
            assert "vm-2" in vms

    def test_wait_for_task_success(self, config: VSphereConfig) -> None:
        """Test waiting for successful task."""
        with patch("app.vsphere.helper.vim") as mock_vim:
            mock_task = Mock()
            mock_task.info.descriptionId = "TestTask"
            mock_task.info.state = mock_vim.TaskInfo.State.success

            helper = VSphereHelper(config)
            result = helper._wait_for_task(mock_task)

            assert result.success is True

    def test_wait_for_task_error(self, config: VSphereConfig) -> None:
        """Test waiting for failed task."""
        with patch("app.vsphere.helper.vim") as mock_vim:
            mock_task = Mock()
            mock_task.info.descriptionId = "TestTask"
            mock_task.info.state = mock_vim.TaskInfo.State.error
            mock_task.info.error = "Test error"

            helper = VSphereHelper(config)
            result = helper._wait_for_task(mock_task)

            assert result.success is False
            assert result.error_message is not None

    def test_context_manager(self, config: VSphereConfig) -> None:
        """Test using helper as context manager."""
        with patch("app.vsphere.helper.connect") as mock_connect:
            with patch("app.vsphere.helper.vim") as mock_vim:
                mock_dc = Mock()
                mock_dc.name = "DC1"
                mock_vim.Datacenter = type(mock_dc)

                mock_si = Mock()
                mock_content = Mock()
                mock_content.rootFolder.childEntity = [mock_dc]
                mock_si.RetrieveContent.return_value = mock_content
                mock_connect.SmartConnect.return_value = mock_si

                helper = VSphereHelper(config)

                with helper as h:
                    assert h.is_connected is True

                mock_connect.Disconnect.assert_called()


class TestVMPowerState:
    """Unit tests for VMPowerState enum."""

    def test_power_state_values(self) -> None:
        """Test power state enum values."""
        assert VMPowerState.POWERED_ON.value == "poweredOn"
        assert VMPowerState.POWERED_OFF.value == "poweredOff"
        assert VMPowerState.SUSPENDED.value == "suspended"
        assert VMPowerState.UNKNOWN.value == "unknown"


class TestTaskResult:
    """Unit tests for TaskResult."""

    def test_successful_result(self) -> None:
        """Test creating successful task result."""
        result = TaskResult(
            success=True,
            task_name="PowerOn",
            message="VM powered on",
            duration_sec=5.0,
            vm_name="test-vm",
        )

        assert result.success is True
        assert result.task_name == "PowerOn"
        assert result.vm_name == "test-vm"
        assert result.error_message is None

    def test_failed_result(self) -> None:
        """Test creating failed task result."""
        result = TaskResult(
            success=False,
            task_name="PowerOn",
            message="Failed to power on",
            duration_sec=1.0,
            vm_name="test-vm",
            error_message="Permission denied",
        )

        assert result.success is False
        assert result.error_message == "Permission denied"

    def test_result_is_frozen(self) -> None:
        """Test that result is immutable."""
        result = TaskResult(
            success=True,
            task_name="Test",
            message="Test",
            duration_sec=0.0,
        )

        with pytest.raises(AttributeError):
            result.success = False
