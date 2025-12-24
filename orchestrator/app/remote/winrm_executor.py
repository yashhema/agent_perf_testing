"""WinRM executor for Windows remote operations."""

import base64
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
class WinRMConfig(ExecutorConfig):
    """Configuration for WinRM executor."""

    password: str = ""
    transport: str = "ntlm"  # ntlm, kerberos, basic, credssp
    server_cert_validation: str = "ignore"  # ignore, validate
    port: int = 5985  # 5985 for HTTP, 5986 for HTTPS
    use_ssl: bool = False
    os_family: OSFamily = OSFamily.WINDOWS


class WinRMExecutor(RemoteExecutor):
    """WinRM-based remote executor for Windows systems."""

    def __init__(self, config: WinRMConfig):
        super().__init__(config)
        self._winrm_config = config
        self._session = None

    def connect(self) -> None:
        """Establish WinRM connection."""
        try:
            import winrm

            protocol = "https" if self._winrm_config.use_ssl else "http"
            endpoint = (
                f"{protocol}://{self._winrm_config.hostname}:"
                f"{self._winrm_config.port}/wsman"
            )

            self._session = winrm.Session(
                endpoint,
                auth=(self._winrm_config.username, self._winrm_config.password),
                transport=self._winrm_config.transport,
                server_cert_validation=self._winrm_config.server_cert_validation,
                read_timeout_sec=self._winrm_config.timeout,
                operation_timeout_sec=self._winrm_config.timeout,
            )

            # Test connection
            result = self._session.run_ps("$env:COMPUTERNAME")
            if result.status_code != 0:
                raise ConnectionError("WinRM connection test failed")

            self._connected = True

        except ImportError:
            raise ImportError("pywinrm is required for WinRM connections")
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect via WinRM: {e}")

    def disconnect(self) -> None:
        """Close WinRM connection."""
        self._session = None
        self._connected = False

    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
    ) -> CommandResult:
        """Execute PowerShell command via WinRM."""
        if not self._session:
            raise ConnectionError("Not connected")

        start_time = time.perf_counter()

        try:
            # Wrap command with working directory if specified
            if working_dir:
                command = f"Set-Location '{working_dir}'; {command}"

            result = self._session.run_ps(command)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            stdout = result.std_out.decode("utf-8", errors="replace") if result.std_out else ""
            stderr = result.std_err.decode("utf-8", errors="replace") if result.std_err else ""

            return CommandResult(
                exit_code=result.status_code,
                stdout=stdout,
                stderr=stderr,
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

    def execute_cmd(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> CommandResult:
        """Execute CMD command via WinRM (not PowerShell)."""
        if not self._session:
            raise ConnectionError("Not connected")

        start_time = time.perf_counter()

        try:
            result = self._session.run_cmd(command)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            stdout = result.std_out.decode("utf-8", errors="replace") if result.std_out else ""
            stderr = result.std_err.decode("utf-8", errors="replace") if result.std_err else ""

            return CommandResult(
                exit_code=result.status_code,
                stdout=stdout,
                stderr=stderr,
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
        """Upload file via WinRM (using Base64 encoding)."""
        try:
            # Read local file
            with open(local_path, "rb") as f:
                content = f.read()

            file_size = len(content)

            # Encode as base64
            encoded = base64.b64encode(content).decode("ascii")

            # Write to remote using PowerShell
            # Split into chunks to avoid command line length limits
            chunk_size = 50000  # Characters per chunk
            chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]

            # Ensure parent directory exists
            parent_dir = os.path.dirname(remote_path).replace("/", "\\")
            if parent_dir:
                self.execute_command(
                    f"New-Item -ItemType Directory -Force -Path '{parent_dir}' | Out-Null"
                )

            # Write first chunk (create file)
            if chunks:
                ps_cmd = (
                    f"[IO.File]::WriteAllBytes('{remote_path}', "
                    f"[Convert]::FromBase64String('{chunks[0]}'))"
                )
                result = self.execute_command(ps_cmd)
                if not result.success:
                    return FileTransferResult(
                        success=False,
                        source_path=local_path,
                        dest_path=remote_path,
                        bytes_transferred=0,
                        error_message=result.stderr,
                    )

            # Append remaining chunks
            for chunk in chunks[1:]:
                ps_cmd = (
                    f"$bytes = [Convert]::FromBase64String('{chunk}'); "
                    f"$stream = [IO.File]::Open('{remote_path}', 'Append'); "
                    f"$stream.Write($bytes, 0, $bytes.Length); "
                    f"$stream.Close()"
                )
                result = self.execute_command(ps_cmd)
                if not result.success:
                    return FileTransferResult(
                        success=False,
                        source_path=local_path,
                        dest_path=remote_path,
                        bytes_transferred=0,
                        error_message=result.stderr,
                    )

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
        """Download file via WinRM (using Base64 encoding)."""
        try:
            # Read remote file as base64
            ps_cmd = f"[Convert]::ToBase64String([IO.File]::ReadAllBytes('{remote_path}'))"
            result = self.execute_command(ps_cmd)

            if not result.success:
                return FileTransferResult(
                    success=False,
                    source_path=remote_path,
                    dest_path=local_path,
                    bytes_transferred=0,
                    error_message=result.stderr,
                )

            # Decode and write locally
            encoded = result.stdout.strip()
            content = base64.b64decode(encoded)

            # Ensure parent directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            with open(local_path, "wb") as f:
                f.write(content)

            return FileTransferResult(
                success=True,
                source_path=remote_path,
                dest_path=local_path,
                bytes_transferred=len(content),
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
        result = self.execute_command(f"Test-Path '{remote_path}'")
        return result.success and "True" in result.stdout

    def mkdir(self, remote_path: str, parents: bool = True) -> bool:
        """Create directory on remote host."""
        force = "-Force" if parents else ""
        result = self.execute_command(
            f"New-Item -ItemType Directory {force} -Path '{remote_path}' | Out-Null"
        )
        return result.success

    def get_system_info(self) -> dict:
        """Get system information from remote Windows host."""
        info = {}

        # Get hostname
        result = self.execute_command("$env:COMPUTERNAME")
        if result.success:
            info["hostname"] = result.stdout.strip()

        # Get OS version
        result = self.execute_command(
            "(Get-CimInstance Win32_OperatingSystem).Caption"
        )
        if result.success:
            info["os_version"] = result.stdout.strip()

        # Get CPU count
        result = self.execute_command(
            "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
        )
        if result.success:
            try:
                info["cpu_count"] = int(result.stdout.strip())
            except ValueError:
                pass

        # Get memory
        result = self.execute_command(
            "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)"
        )
        if result.success:
            try:
                info["memory_mb"] = int(result.stdout.strip())
            except ValueError:
                pass

        return info

    def install_service(
        self,
        service_name: str,
        executable_path: str,
        display_name: Optional[str] = None,
        start_type: str = "auto",
    ) -> CommandResult:
        """Install a Windows service."""
        display = display_name or service_name
        ps_cmd = (
            f"New-Service -Name '{service_name}' "
            f"-BinaryPathName '{executable_path}' "
            f"-DisplayName '{display}' "
            f"-StartupType {start_type}"
        )
        return self.execute_command(ps_cmd)

    def control_service(
        self,
        service_name: str,
        action: str,  # start, stop, restart
    ) -> CommandResult:
        """Control a Windows service."""
        if action == "restart":
            return self.execute_command(f"Restart-Service -Name '{service_name}' -Force")
        elif action == "start":
            return self.execute_command(f"Start-Service -Name '{service_name}'")
        elif action == "stop":
            return self.execute_command(f"Stop-Service -Name '{service_name}' -Force")
        else:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Unknown action: {action}",
                command=f"control_service({service_name}, {action})",
                duration_ms=0,
            )
