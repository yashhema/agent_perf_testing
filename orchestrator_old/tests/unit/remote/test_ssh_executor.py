"""Unit tests for SSH executor."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.remote.ssh_executor import SSHExecutor, SSHConfig
from app.remote.base import OSFamily


class TestSSHConfig:
    """Unit tests for SSHConfig."""

    def test_default_config(self) -> None:
        """Test creating config with defaults."""
        config = SSHConfig(
            hostname="server.example.com",
            username="testuser",
        )

        assert config.hostname == "server.example.com"
        assert config.username == "testuser"
        assert config.port == 22
        assert config.os_family == OSFamily.LINUX
        assert config.key_path is None
        assert config.password is None

    def test_config_with_key(self) -> None:
        """Test config with SSH key."""
        config = SSHConfig(
            hostname="server.example.com",
            username="testuser",
            key_path="/path/to/key",
            passphrase="secret",
        )

        assert config.key_path == "/path/to/key"
        assert config.passphrase == "secret"

    def test_config_is_frozen(self) -> None:
        """Test that config is immutable."""
        config = SSHConfig(
            hostname="server.example.com",
            username="testuser",
        )

        with pytest.raises(AttributeError):
            config.hostname = "other.example.com"


class TestSSHExecutor:
    """Unit tests for SSHExecutor."""

    @pytest.fixture
    def mock_paramiko(self):
        """Mock paramiko module."""
        with patch("app.remote.ssh_executor.paramiko") as mock:
            yield mock

    @pytest.fixture
    def config(self) -> SSHConfig:
        """Create test config."""
        return SSHConfig(
            hostname="test.server.com",
            username="testuser",
            key_path="/path/to/key",
        )

    def test_connect(self, mock_paramiko, config: SSHConfig) -> None:
        """Test SSH connection."""
        executor = SSHExecutor(config)
        executor.connect()

        mock_paramiko.SSHClient.return_value.connect.assert_called_once_with(
            hostname="test.server.com",
            port=22,
            username="testuser",
            key_filename="/path/to/key",
            timeout=30,
        )
        assert executor.is_connected is True

    def test_connect_with_password(self, mock_paramiko) -> None:
        """Test SSH connection with password."""
        config = SSHConfig(
            hostname="test.server.com",
            username="testuser",
            password="testpass",
        )

        executor = SSHExecutor(config)
        executor.connect()

        mock_paramiko.SSHClient.return_value.connect.assert_called_once()
        call_kwargs = mock_paramiko.SSHClient.return_value.connect.call_args[1]
        assert call_kwargs["password"] == "testpass"

    def test_disconnect(self, mock_paramiko, config: SSHConfig) -> None:
        """Test SSH disconnection."""
        executor = SSHExecutor(config)
        executor.connect()
        executor.disconnect()

        mock_paramiko.SSHClient.return_value.close.assert_called_once()
        assert executor.is_connected is False

    def test_execute_command(self, mock_paramiko, config: SSHConfig) -> None:
        """Test command execution."""
        # Setup mock
        mock_stdout = Mock()
        mock_stdout.read.return_value = b"command output"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""

        mock_paramiko.SSHClient.return_value.exec_command.return_value = (
            None, mock_stdout, mock_stderr
        )

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.execute_command("ls -la")

        assert result.exit_code == 0
        assert result.stdout == "command output"
        assert result.success is True

    def test_execute_command_with_working_dir(
        self, mock_paramiko, config: SSHConfig
    ) -> None:
        """Test command execution with working directory."""
        mock_stdout = Mock()
        mock_stdout.read.return_value = b"output"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""

        mock_paramiko.SSHClient.return_value.exec_command.return_value = (
            None, mock_stdout, mock_stderr
        )

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        executor.execute_command("ls", working_dir="/tmp")

        call_args = mock_paramiko.SSHClient.return_value.exec_command.call_args
        assert "cd /tmp && ls" in call_args[0][0]

    def test_execute_command_failure(self, mock_paramiko, config: SSHConfig) -> None:
        """Test command execution failure."""
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = Mock()
        mock_stderr.read.return_value = b"error message"

        mock_paramiko.SSHClient.return_value.exec_command.return_value = (
            None, mock_stdout, mock_stderr
        )

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.execute_command("invalid_command")

        assert result.exit_code == 1
        assert result.stderr == "error message"
        assert result.success is False

    def test_upload_file(self, mock_paramiko, config: SSHConfig, tmp_path) -> None:
        """Test file upload via SFTP."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_sftp = Mock()
        mock_paramiko.SSHClient.return_value.open_sftp.return_value = mock_sftp

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.upload_file(str(test_file), "/remote/test.txt")

        mock_sftp.put.assert_called_once_with(str(test_file), "/remote/test.txt")
        assert result.success is True

    def test_download_file(self, mock_paramiko, config: SSHConfig, tmp_path) -> None:
        """Test file download via SFTP."""
        local_path = tmp_path / "downloaded.txt"

        mock_sftp = Mock()
        mock_paramiko.SSHClient.return_value.open_sftp.return_value = mock_sftp

        # Mock the get operation to create the file
        def mock_get(remote, local):
            with open(local, "w") as f:
                f.write("downloaded content")

        mock_sftp.get.side_effect = mock_get

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.download_file("/remote/file.txt", str(local_path))

        assert result.success is True
        assert local_path.exists()

    def test_file_exists_true(self, mock_paramiko, config: SSHConfig) -> None:
        """Test file exists check - file exists."""
        mock_sftp = Mock()
        mock_paramiko.SSHClient.return_value.open_sftp.return_value = mock_sftp

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.file_exists("/remote/file.txt")

        assert result is True
        mock_sftp.stat.assert_called_once_with("/remote/file.txt")

    def test_file_exists_false(self, mock_paramiko, config: SSHConfig) -> None:
        """Test file exists check - file does not exist."""
        mock_sftp = Mock()
        mock_sftp.stat.side_effect = FileNotFoundError()
        mock_paramiko.SSHClient.return_value.open_sftp.return_value = mock_sftp

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.file_exists("/remote/nonexistent.txt")

        assert result is False

    def test_mkdir(self, mock_paramiko, config: SSHConfig) -> None:
        """Test directory creation."""
        mock_stdout = Mock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""

        mock_paramiko.SSHClient.return_value.exec_command.return_value = (
            None, mock_stdout, mock_stderr
        )

        executor = SSHExecutor(config)
        executor._client = mock_paramiko.SSHClient.return_value
        executor._connected = True

        result = executor.mkdir("/remote/new/dir")

        assert result is True

    def test_context_manager(self, mock_paramiko, config: SSHConfig) -> None:
        """Test using executor as context manager."""
        executor = SSHExecutor(config)

        with executor as exec:
            assert exec.is_connected is True

        mock_paramiko.SSHClient.return_value.close.assert_called()
