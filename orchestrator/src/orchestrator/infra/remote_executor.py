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
        # Keep SSH alive during long test runs (calibration + execution can exceed 25 min)
        transport = self._client.get_transport()
        if transport:
            transport.set_keepalive(30)
        self._sftp: Optional[paramiko.SFTPClient] = None
        logger.info("SSH connected to %s@%s:%d", username, host, port)

    def _get_sftp(self):
        import paramiko
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    # Standard PATH prefix for non-login SSH shells (sshd may not source /etc/profile)
    _PATH_PREFIX = "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH && "

    def execute(self, command: str, timeout_sec: int = 120) -> CommandResult:
        full_command = self._PATH_PREFIX + command
        logger.debug("SSH exec on %s: %s", self._host, full_command)
        stdin, stdout, stderr = self._client.exec_command(full_command, timeout=timeout_sec)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return CommandResult(exit_code=exit_code, stdout=out, stderr=err)

    def execute_background(self, command: str, timeout_sec: int = 10) -> CommandResult:
        """Execute a command that starts a background process.

        Reads stdout line-by-line with a timeout instead of waiting for
        channel close (which blocks when background processes keep the
        channel open).
        """
        import socket
        full_command = self._PATH_PREFIX + command
        logger.debug("SSH exec_background on %s: %s", self._host, full_command)
        stdin, stdout, stderr = self._client.exec_command(full_command)
        stdout.channel.settimeout(timeout_sec)
        lines = []
        try:
            for line in stdout:
                lines.append(line.rstrip("\n"))
        except socket.timeout:
            pass  # expected — background process keeps channel open
        out = "\n".join(lines)
        return CommandResult(exit_code=0, stdout=out, stderr="")

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
    """WinRM-based remote executor using pywinrm.

    File transfers use HTTP pull: the orchestrator serves files via a built-in
    HTTP server, and the target downloads them with Invoke-WebRequest.  This
    avoids WinRM's command-length limits and base64 encoding overhead.
    For small files (< 4KB, e.g. scripts), inline base64 via run_ps is used.
    """

    _INLINE_LIMIT = 4096  # files smaller than this use inline base64

    def __init__(self, host: str, username: str, password: str, port: int = 5985,
                 use_ssl: bool = False, orchestrator_url: str | None = None):
        import winrm
        scheme = "https" if use_ssl else "http"
        self._host = host
        self._endpoint = f"{scheme}://{host}:{port}/wsman"
        self._session = winrm.Session(
            self._endpoint,
            auth=(username, password),
            transport="ntlm",
            server_cert_validation="ignore" if use_ssl else "validate",
            read_timeout_sec=120,
            operation_timeout_sec=110,
        )
        self._orchestrator_url = orchestrator_url  # e.g. "http://10.0.0.11:9090"
        logger.info("WinRM connected to %s@%s:%d", username, host, port)

    def execute(self, command: str, timeout_sec: int = 120) -> CommandResult:
        logger.debug("WinRM exec on %s: %s", self._host, command)
        old_timeout = self._session.protocol.transport.read_timeout_sec
        self._session.protocol.transport.read_timeout_sec = timeout_sec
        try:
            result = self._session.run_cmd(command)
        finally:
            self._session.protocol.transport.read_timeout_sec = old_timeout
        return CommandResult(
            exit_code=result.status_code,
            stdout=result.std_out.decode("utf-8", errors="replace"),
            stderr=result.std_err.decode("utf-8", errors="replace"),
        )

    def upload(self, local_path: str, remote_path: str) -> None:
        logger.debug("WinRM upload %s -> %s:%s", local_path, self._host, remote_path)
        import os, base64
        rp = remote_path.replace("\\", "/")
        parent = rp.rsplit("/", 1)[0]
        # Ensure parent directory exists
        self._session.run_ps(f"New-Item -ItemType Directory -Force -Path '{parent}' | Out-Null")

        file_size = os.path.getsize(local_path)

        if file_size <= self._INLINE_LIMIT:
            # Small file: inline base64 via run_ps
            with open(local_path, "rb") as f:
                content = f.read()
            # Add UTF-8 BOM for .ps1 files so PowerShell 5.1 parses them correctly
            if local_path.endswith(".ps1") and not content.startswith(b"\xef\xbb\xbf"):
                content = b"\xef\xbb\xbf" + content
            encoded = base64.b64encode(content).decode("ascii")
            result = self._session.run_ps(
                f"[IO.File]::WriteAllBytes('{rp}', [Convert]::FromBase64String('{encoded}'))"
            )
            if result.status_code != 0:
                raise IOError(f"WinRM inline upload failed: {result.std_err.decode()}")
            logger.debug("WinRM inline upload complete: %d bytes", len(content))
        else:
            # Large file: target pulls from orchestrator HTTP server
            if not self._orchestrator_url:
                raise IOError(
                    "WinRM upload requires orchestrator_url for files > 4KB. "
                    "Set orchestrator_url when creating WinRMExecutor."
                )
            # Build URL from local_path relative to orchestrator root.
            # FastAPI mounts:
            #   artifacts/packages/*  -> /packages/*
            #   prerequisites/*       -> /prerequisites/*
            # So we map the local path to the correct URL mount.
            from pathlib import Path
            local_p = Path(local_path).resolve()
            parts = local_p.parts
            try:
                orch_idx = parts.index("orchestrator")
                rel_path = "/".join(parts[orch_idx + 1:])
            except ValueError:
                rel_path = local_p.name
            # Map artifacts/packages/X -> /packages/X (FastAPI mount)
            if rel_path.startswith("artifacts/packages/"):
                rel_path = rel_path.replace("artifacts/packages/", "packages/", 1)
            url = f"{self._orchestrator_url}/{rel_path}"
            logger.info("WinRM HTTP pull: %s -> %s", url, rp)
            result = self._session.run_ps(
                f"Invoke-WebRequest -Uri '{url}' -OutFile '{rp}' -UseBasicParsing"
            )
            if result.status_code != 0:
                raise IOError(f"WinRM HTTP download failed: {result.std_err.decode()}")
            # Verify file size
            result = self._session.run_ps(f"(Get-Item '{rp}').Length")
            remote_size = int(result.std_out.decode().strip())
            if remote_size != file_size:
                raise IOError(
                    f"WinRM upload size mismatch: local={file_size}, remote={remote_size}"
                )
            logger.debug("WinRM HTTP upload complete: %d bytes", file_size)

    def download(self, remote_path: str, local_path: str) -> None:
        logger.debug("WinRM download %s:%s -> %s", self._host, remote_path, local_path)
        rp = remote_path.replace("\\", "/")
        ps_script = f"[Convert]::ToBase64String([IO.File]::ReadAllBytes('{rp}'))"
        result = self._session.run_ps(ps_script)
        if result.status_code != 0:
            raise IOError(f"WinRM download failed: {result.std_err.decode()}")
        import base64
        content = base64.b64decode(result.std_out.decode().strip())
        with open(local_path, "wb") as f:
            f.write(content)

    def close(self) -> None:
        logger.info("WinRM session to %s closed", self._host)


def wait_for_ssh(host: str, port: int = 22, timeout_sec: int = 120, poll_sec: int = 5) -> None:
    """Wait until SSH port is accepting connections.

    Useful after snapshot restores where the hypervisor API reports 'running'
    before the OS has fully booted and SSHD is listening.
    """
    import socket
    import time

    elapsed = 0
    while elapsed < timeout_sec:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            logger.info("SSH port %s:%d reachable (waited %ds)", host, port, elapsed)
            return
        except (ConnectionRefusedError, TimeoutError, OSError):
            pass
        time.sleep(poll_sec)
        elapsed += poll_sec
    raise TimeoutError(f"SSH on {host}:{port} not reachable after {timeout_sec}s")


def create_executor(
    os_family: str,
    host: str,
    username: str,
    password: str,
    ssh_port: int = 22,
    winrm_port: int = 5985,
    winrm_ssl: bool = False,
    orchestrator_url: str | None = None,
) -> RemoteExecutor:
    """Factory: create RemoteExecutor based on os_family."""
    if os_family == "linux":
        return SSHExecutor(host=host, username=username, password=password, port=ssh_port)
    elif os_family == "windows":
        return WinRMExecutor(host=host, username=username, password=password, port=winrm_port,
                             use_ssl=winrm_ssl, orchestrator_url=orchestrator_url)
    else:
        raise ValueError(f"Unsupported os_family: {os_family}")
