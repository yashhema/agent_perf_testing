"""Base executor interface for remote operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class OSFamily(str, Enum):
    """Operating system family."""

    WINDOWS = "windows"
    LINUX = "linux"
    AIX = "aix"


@dataclass(frozen=True)
class ExecutorConfig:
    """Base configuration for remote executors."""

    hostname: str
    username: str
    port: int
    timeout: int = 30
    os_family: OSFamily = OSFamily.LINUX


@dataclass(frozen=True)
class CommandResult:
    """Result of a remote command execution."""

    exit_code: int
    stdout: str
    stderr: str
    command: str
    duration_ms: int
    success: bool = field(default=False)

    def __post_init__(self) -> None:
        # Set success based on exit_code if not explicitly set
        object.__setattr__(self, "success", self.exit_code == 0)


@dataclass(frozen=True)
class FileTransferResult:
    """Result of a file transfer operation."""

    success: bool
    source_path: str
    dest_path: str
    bytes_transferred: int
    error_message: Optional[str] = None


class RemoteExecutor(ABC):
    """Abstract base class for remote command execution."""

    def __init__(self, config: ExecutorConfig):
        self._config = config
        self._connected = False

    @property
    def config(self) -> ExecutorConfig:
        """Get executor configuration."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """Check if executor is connected."""
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to remote host."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to remote host."""
        pass

    @abstractmethod
    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
    ) -> CommandResult:
        """
        Execute a command on the remote host.

        Args:
            command: Command to execute
            timeout: Command timeout in seconds (uses default if None)
            working_dir: Working directory for command execution

        Returns:
            CommandResult with exit code, stdout, stderr
        """
        pass

    @abstractmethod
    def upload_file(
        self,
        local_path: str,
        remote_path: str,
    ) -> FileTransferResult:
        """
        Upload a file to the remote host.

        Args:
            local_path: Local file path
            remote_path: Remote destination path

        Returns:
            FileTransferResult with transfer status
        """
        pass

    @abstractmethod
    def download_file(
        self,
        remote_path: str,
        local_path: str,
    ) -> FileTransferResult:
        """
        Download a file from the remote host.

        Args:
            remote_path: Remote file path
            local_path: Local destination path

        Returns:
            FileTransferResult with transfer status
        """
        pass

    @abstractmethod
    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the remote host."""
        pass

    @abstractmethod
    def mkdir(self, remote_path: str, parents: bool = True) -> bool:
        """Create a directory on the remote host."""
        pass

    def execute_script(
        self,
        script_content: str,
        script_name: str = "script",
        timeout: Optional[int] = None,
    ) -> CommandResult:
        """
        Execute a script on the remote host.

        Uploads script content, executes it, then removes it.
        """
        # Determine script extension and execution command based on OS
        if self._config.os_family == OSFamily.WINDOWS:
            script_ext = ".ps1"
            remote_script = f"C:\\Temp\\{script_name}{script_ext}"
            execute_cmd = f"powershell -ExecutionPolicy Bypass -File {remote_script}"
        else:
            script_ext = ".sh"
            remote_script = f"/tmp/{script_name}{script_ext}"
            execute_cmd = f"bash {remote_script}"

        try:
            # Create temp directory if needed
            if self._config.os_family == OSFamily.WINDOWS:
                self.execute_command("mkdir C:\\Temp -Force", timeout=10)
            else:
                self.execute_command("mkdir -p /tmp", timeout=10)

            # Write script content to temp file locally, then upload
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=script_ext, delete=False
            ) as f:
                f.write(script_content)
                local_script = f.name

            try:
                # Upload script
                self.upload_file(local_script, remote_script)

                # Make executable on Linux
                if self._config.os_family != OSFamily.WINDOWS:
                    self.execute_command(f"chmod +x {remote_script}", timeout=10)

                # Execute script
                result = self.execute_command(execute_cmd, timeout=timeout)

                return result

            finally:
                # Clean up local temp file
                os.unlink(local_script)

                # Clean up remote script
                if self._config.os_family == OSFamily.WINDOWS:
                    self.execute_command(f"Remove-Item -Force {remote_script}", timeout=10)
                else:
                    self.execute_command(f"rm -f {remote_script}", timeout=10)

        except Exception as e:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                command=f"execute_script({script_name})",
                duration_ms=0,
            )

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
