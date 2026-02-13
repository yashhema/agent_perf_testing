"""Unit tests for WinRM executor."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.remote.winrm_executor import WinRMExecutor, WinRMConfig
from app.remote.base import OSFamily


class TestWinRMConfig:
    """Unit tests for WinRMConfig."""

    def test_default_config(self) -> None:
        """Test creating config with defaults."""
        config = WinRMConfig(
            hostname="server.example.com",
            username="admin",
            password="password123",
        )

        assert config.hostname == "server.example.com"
        assert config.username == "admin"
        assert config.port == 5985
        assert config.os_family == OSFamily.WINDOWS
        assert config.transport == "ntlm"
        assert config.use_ssl is False

    def test_config_with_ssl(self) -> None:
        """Test config with SSL enabled."""
        config = WinRMConfig(
            hostname="server.example.com",
            username="admin",
            password="password123",
            use_ssl=True,
            port=5986,
        )

        assert config.use_ssl is True
        assert config.port == 5986

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = WinRMConfig(
            hostname="server.example.com",
            username="admin",
            password="password123",
        )

        with pytest.raises(AttributeError):
            config.hostname = "other.example.com"


class TestWinRMExecutor:
    """Unit tests for WinRMExecutor."""

    @pytest.fixture
    def mock_winrm(self):
        """Mock winrm module."""
        with patch("app.remote.winrm_executor.winrm") as mock:
            yield mock

    @pytest.fixture
    def config(self) -> WinRMConfig:
        """Create test config."""
        return WinRMConfig(
            hostname="win.server.com",
            username="admin",
            password="password123",
        )

    def test_connect(self, mock_winrm, config: WinRMConfig) -> None:
        """Test WinRM connection."""
        # Mock successful connection test
        mock_result = Mock()
        mock_result.status_code = 0
        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor.connect()

        mock_winrm.Session.assert_called_once()
        assert executor.is_connected is True

    def test_connect_failure(self, mock_winrm, config: WinRMConfig) -> None:
        """Test WinRM connection failure."""
        mock_result = Mock()
        mock_result.status_code = 1
        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)

        with pytest.raises(ConnectionError):
            executor.connect()

    def test_disconnect(self, mock_winrm, config: WinRMConfig) -> None:
        """Test WinRM disconnection."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor.connect()
        executor.disconnect()

        assert executor.is_connected is False

    def test_execute_command(self, mock_winrm, config: WinRMConfig) -> None:
        """Test PowerShell command execution."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b"output"
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.execute_command("Get-Process")

        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.success is True

    def test_execute_command_with_working_dir(
        self, mock_winrm, config: WinRMConfig
    ) -> None:
        """Test command execution with working directory."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b"output"
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        executor.execute_command("Get-ChildItem", working_dir="C:\\Temp")

        call_args = mock_winrm.Session.return_value.run_ps.call_args
        assert "Set-Location" in call_args[0][0]
        assert "C:\\Temp" in call_args[0][0]

    def test_execute_command_failure(self, mock_winrm, config: WinRMConfig) -> None:
        """Test command execution failure."""
        mock_result = Mock()
        mock_result.status_code = 1
        mock_result.std_out = b""
        mock_result.std_err = b"error message"

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.execute_command("Invalid-Command")

        assert result.exit_code == 1
        assert result.stderr == "error message"
        assert result.success is False

    def test_execute_cmd(self, mock_winrm, config: WinRMConfig) -> None:
        """Test CMD command execution."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b"cmd output"
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_cmd.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.execute_cmd("dir")

        assert result.exit_code == 0
        assert result.stdout == "cmd output"

    def test_file_exists_true(self, mock_winrm, config: WinRMConfig) -> None:
        """Test file exists check - file exists."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b"True"
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.file_exists("C:\\file.txt")

        assert result is True

    def test_file_exists_false(self, mock_winrm, config: WinRMConfig) -> None:
        """Test file exists check - file does not exist."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b"False"
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.file_exists("C:\\nonexistent.txt")

        assert result is False

    def test_mkdir(self, mock_winrm, config: WinRMConfig) -> None:
        """Test directory creation."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b""
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.mkdir("C:\\NewDir")

        assert result is True

    def test_control_service_start(self, mock_winrm, config: WinRMConfig) -> None:
        """Test starting a Windows service."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b""
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.control_service("TestService", "start")

        assert result.success is True

    def test_control_service_stop(self, mock_winrm, config: WinRMConfig) -> None:
        """Test stopping a Windows service."""
        mock_result = Mock()
        mock_result.status_code = 0
        mock_result.std_out = b""
        mock_result.std_err = b""

        mock_winrm.Session.return_value.run_ps.return_value = mock_result

        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.control_service("TestService", "stop")

        assert result.success is True

    def test_control_service_invalid_action(
        self, mock_winrm, config: WinRMConfig
    ) -> None:
        """Test invalid service action."""
        executor = WinRMExecutor(config)
        executor._session = mock_winrm.Session.return_value
        executor._connected = True

        result = executor.control_service("TestService", "invalid")

        assert result.success is False
        assert "Unknown action" in result.stderr
