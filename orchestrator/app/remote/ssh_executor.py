"""SSH executor for Linux/Unix remote operations."""

import os
import time
from dataclasses import dataclass
from typing import Optional

from .base import (
    RemoteExecutor,
    ExecutorConfig,
    CommandResult,
    FileTransferResult,
    OSFamily,
)


@dataclass(frozen=True)
class SSHConfig(ExecutorConfig):
    """Configuration for SSH executor."""

    key_path: Optional[str] = None
    password: Optional[str] = None
    passphrase: Optional[str] = None
    port: int = 22
    os_family: OSFamily = OSFamily.LINUX


class SSHExecutor(RemoteExecutor):
    """SSH-based remote executor for Linux/Unix systems."""

    def __init__(self, config: SSHConfig):
        super().__init__(config)
        self._ssh_config = config
        self._client = None
        self._sftp = None

    def connect(self) -> None:
        """Establish SSH connection."""
        try:
            import paramiko

            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": self._ssh_config.hostname,
                "port": self._ssh_config.port,
                "username": self._ssh_config.username,
                "timeout": self._ssh_config.timeout,
            }

            if self._ssh_config.key_path:
                connect_kwargs["key_filename"] = self._ssh_config.key_path
                if self._ssh_config.passphrase:
                    connect_kwargs["passphrase"] = self._ssh_config.passphrase
            elif self._ssh_config.password:
                connect_kwargs["password"] = self._ssh_config.password

            self._client.connect(**connect_kwargs)
            self._connected = True

        except ImportError:
            raise ImportError("paramiko is required for SSH connections")
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect via SSH: {e}")

    def disconnect(self) -> None:
        """Close SSH connection."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        self._connected = False

    def _get_sftp(self):
        """Get or create SFTP client."""
        if not self._client:
            raise ConnectionError("Not connected")

        if not self._sftp:
            self._sftp = self._client.open_sftp()

        return self._sftp

    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
    ) -> CommandResult:
        """Execute command via SSH."""
        if not self._client:
            raise ConnectionError("Not connected")

        start_time = time.perf_counter()
        timeout = timeout or self._ssh_config.timeout

        try:
            # Prepend cd command if working directory specified
            if working_dir:
                command = f"cd {working_dir} && {command}"

            stdin, stdout, stderr = self._client.exec_command(
                command, timeout=timeout
            )

            # Wait for command to complete
            exit_code = stdout.channel.recv_exit_status()

            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return CommandResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                command=command,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                command=command,
                duration_ms=duration_ms,
            )

    def upload_file(
        self,
        local_path: str,
        remote_path: str,
    ) -> FileTransferResult:
        """Upload file via SFTP."""
        try:
            sftp = self._get_sftp()

            # Get local file size
            file_size = os.path.getsize(local_path)

            sftp.put(local_path, remote_path)

            return FileTransferResult(
                success=True,
                source_path=local_path,
                dest_path=remote_path,
                bytes_transferred=file_size,
            )

        except Exception as e:
            return FileTransferResult(
                success=False,
                source_path=local_path,
                dest_path=remote_path,
                bytes_transferred=0,
                error_message=str(e),
            )

    def download_file(
        self,
        remote_path: str,
        local_path: str,
    ) -> FileTransferResult:
        """Download file via SFTP."""
        try:
            sftp = self._get_sftp()

            sftp.get(remote_path, local_path)

            # Get downloaded file size
            file_size = os.path.getsize(local_path)

            return FileTransferResult(
                success=True,
                source_path=remote_path,
                dest_path=local_path,
                bytes_transferred=file_size,
            )

        except Exception as e:
            return FileTransferResult(
                success=False,
                source_path=remote_path,
                dest_path=local_path,
                bytes_transferred=0,
                error_message=str(e),
            )

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists on remote host."""
        try:
            sftp = self._get_sftp()
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def mkdir(self, remote_path: str, parents: bool = True) -> bool:
        """Create directory on remote host."""
        try:
            if parents:
                # Use mkdir -p for recursive creation
                result = self.execute_command(f"mkdir -p {remote_path}")
                return result.success
            else:
                sftp = self._get_sftp()
                sftp.mkdir(remote_path)
                return True
        except Exception:
            return False

    def get_system_info(self) -> dict:
        """Get system information from remote host."""
        info = {}

        # Get hostname
        result = self.execute_command("hostname")
        if result.success:
            info["hostname"] = result.stdout.strip()

        # Get OS info
        result = self.execute_command("uname -a")
        if result.success:
            info["uname"] = result.stdout.strip()

        # Get CPU count
        result = self.execute_command("nproc")
        if result.success:
            try:
                info["cpu_count"] = int(result.stdout.strip())
            except ValueError:
                pass

        # Get memory info
        result = self.execute_command("free -m | grep Mem | awk '{print $2}'")
        if result.success:
            try:
                info["memory_mb"] = int(result.stdout.strip())
            except ValueError:
                pass

        return info
