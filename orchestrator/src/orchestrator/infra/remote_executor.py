"""Remote execution abstraction (SSH/WinRM).

RemoteExecutor interface with factory based on os_family:
  linux  -> SSHExecutor (paramiko)
  windows -> WinRMExecutor (pywinrm)
"""

import abc
import io
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a remote command execution."""
    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class RemoteExecutor(abc.ABC):
    """Abstract base for remote command execution."""

    @abc.abstractmethod
    def execute(self, command: str, timeout_sec: int = 120) -> CommandResult:
        """Execute a command on the remote host."""

    @abc.abstractmethod
    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload a file to the remote host."""

    @abc.abstractmethod
    def download(self, remote_path: str, local_path: str) -> None:
        """Download a file from the remote host."""

    @abc.abstractmethod
    def close(self) -> None:
        """Close the connection."""


class SSHExecutor(RemoteExecutor):
    """SSH-based remote executor using paramiko."""

    def __init__(self, host: str, username: str, password: str, port: int = 22, timeout_sec: int = 30):
        import paramiko
        self._host = host
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=timeout_sec,
            allow_agent=False,
            look_for_keys=False,
        )
        self._sftp: Optional[paramiko.SFTPClient] = None
        logger.info("SSH connected to %s@%s:%d", username, host, port)

    def _get_sftp(self):
        import paramiko
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    def execute(self, command: str, timeout_sec: int = 120) -> CommandResult:
        logger.debug("SSH exec on %s: %s", self._host, command)
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout_sec)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return CommandResult(exit_code=exit_code, stdout=out, stderr=err)

    def upload(self, local_path: str, remote_path: str) -> None:
        logger.debug("SFTP upload %s -> %s:%s", local_path, self._host, remote_path)
        self._get_sftp().put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> None:
        logger.debug("SFTP download %s:%s -> %s", self._host, remote_path, local_path)
        self._get_sftp().get(remote_path, local_path)

    def close(self) -> None:
        if self._sftp:
            self._sftp.close()
        self._client.close()
        logger.info("SSH disconnected from %s", self._host)


class WinRMExecutor(RemoteExecutor):
    """WinRM-based remote executor using pywinrm."""

    def __init__(self, host: str, username: str, password: str, port: int = 5985, use_ssl: bool = False):
        import winrm
        scheme = "https" if use_ssl else "http"
        self._host = host
        self._endpoint = f"{scheme}://{host}:{port}/wsman"
        self._session = winrm.Session(
            self._endpoint,
            auth=(username, password),
            transport="ntlm",
            server_cert_validation="ignore" if use_ssl else "validate",
        )
        logger.info("WinRM connected to %s@%s:%d", username, host, port)

    def execute(self, command: str, timeout_sec: int = 120) -> CommandResult:
        logger.debug("WinRM exec on %s: %s", self._host, command)
        result = self._session.run_cmd(command)
        return CommandResult(
            exit_code=result.status_code,
            stdout=result.std_out.decode("utf-8", errors="replace"),
            stderr=result.std_err.decode("utf-8", errors="replace"),
        )

    def upload(self, local_path: str, remote_path: str) -> None:
        logger.debug("WinRM upload %s -> %s:%s", local_path, self._host, remote_path)
        with open(local_path, "rb") as f:
            content = f.read()
        # Use PowerShell to write file content
        import base64
        encoded = base64.b64encode(content).decode("ascii")
        ps_script = f'[IO.File]::WriteAllBytes("{remote_path}", [Convert]::FromBase64String("{encoded}"))'
        result = self._session.run_ps(ps_script)
        if result.status_code != 0:
            raise IOError(f"WinRM upload failed: {result.std_err.decode()}")

    def download(self, remote_path: str, local_path: str) -> None:
        logger.debug("WinRM download %s:%s -> %s", self._host, remote_path, local_path)
        ps_script = f'[Convert]::ToBase64String([IO.File]::ReadAllBytes("{remote_path}"))'
        result = self._session.run_ps(ps_script)
        if result.status_code != 0:
            raise IOError(f"WinRM download failed: {result.std_err.decode()}")
        import base64
        content = base64.b64decode(result.std_out.decode().strip())
        with open(local_path, "wb") as f:
            f.write(content)

    def close(self) -> None:
        logger.info("WinRM session to %s closed", self._host)


def create_executor(
    os_family: str,
    host: str,
    username: str,
    password: str,
    ssh_port: int = 22,
    winrm_port: int = 5985,
    winrm_ssl: bool = False,
) -> RemoteExecutor:
    """Factory: create RemoteExecutor based on os_family."""
    if os_family == "linux":
        return SSHExecutor(host=host, username=username, password=password, port=ssh_port)
    elif os_family == "windows":
        return WinRMExecutor(host=host, username=username, password=password, port=winrm_port, use_ssl=winrm_ssl)
    else:
        raise ValueError(f"Unsupported os_family: {os_family}")
