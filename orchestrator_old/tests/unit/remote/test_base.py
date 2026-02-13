"""Unit tests for base executor classes."""

import pytest

from app.remote.base import (
    CommandResult,
    FileTransferResult,
    ExecutorConfig,
    OSFamily,
)


class TestCommandResult:
    """Unit tests for CommandResult."""

    def test_successful_result(self) -> None:
        """Test creating successful command result."""
        result = CommandResult(
            exit_code=0,
            stdout="output",
            stderr="",
            command="ls",
            duration_ms=100,
        )

        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.success is True

    def test_failed_result(self) -> None:
        """Test creating failed command result."""
        result = CommandResult(
            exit_code=1,
            stdout="",
            stderr="error",
            command="invalid",
            duration_ms=50,
        )

        assert result.exit_code == 1
        assert result.stderr == "error"
        assert result.success is False

    def test_result_is_frozen(self) -> None:
        """Test that result is immutable."""
        result = CommandResult(
            exit_code=0,
            stdout="output",
            stderr="",
            command="ls",
            duration_ms=100,
        )

        with pytest.raises(AttributeError):
            result.exit_code = 1


class TestFileTransferResult:
    """Unit tests for FileTransferResult."""

    def test_successful_transfer(self) -> None:
        """Test creating successful transfer result."""
        result = FileTransferResult(
            success=True,
            source_path="/local/file.txt",
            dest_path="/remote/file.txt",
            bytes_transferred=1024,
        )

        assert result.success is True
        assert result.bytes_transferred == 1024
        assert result.error_message is None

    def test_failed_transfer(self) -> None:
        """Test creating failed transfer result."""
        result = FileTransferResult(
            success=False,
            source_path="/local/file.txt",
            dest_path="/remote/file.txt",
            bytes_transferred=0,
            error_message="Permission denied",
        )

        assert result.success is False
        assert result.error_message == "Permission denied"


class TestExecutorConfig:
    """Unit tests for ExecutorConfig."""

    def test_default_config(self) -> None:
        """Test creating config with defaults."""
        config = ExecutorConfig(
            hostname="server.example.com",
            username="user",
            port=22,
        )

        assert config.hostname == "server.example.com"
        assert config.timeout == 30
        assert config.os_family == OSFamily.LINUX

    def test_custom_config(self) -> None:
        """Test creating config with custom values."""
        config = ExecutorConfig(
            hostname="server.example.com",
            username="user",
            port=2222,
            timeout=60,
            os_family=OSFamily.WINDOWS,
        )

        assert config.port == 2222
        assert config.timeout == 60
        assert config.os_family == OSFamily.WINDOWS


class TestOSFamily:
    """Unit tests for OSFamily enum."""

    def test_os_family_values(self) -> None:
        """Test OS family enum values."""
        assert OSFamily.WINDOWS.value == "windows"
        assert OSFamily.LINUX.value == "linux"
        assert OSFamily.AIX.value == "aix"

    def test_os_family_from_string(self) -> None:
        """Test creating OS family from string."""
        assert OSFamily("windows") == OSFamily.WINDOWS
        assert OSFamily("linux") == OSFamily.LINUX
