"""Deployment service for remote operations."""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from .base import RemoteExecutor, CommandResult, FileTransferResult, OSFamily
from .ssh_executor import SSHExecutor, SSHConfig
from .winrm_executor import WinRMExecutor, WinRMConfig


class DeploymentAction(str, Enum):
    """Deployment actions."""

    DEPLOY_EMULATOR = "deploy_emulator"
    START_EMULATOR = "start_emulator"
    STOP_EMULATOR = "stop_emulator"
    CHECK_EMULATOR = "check_emulator"
    DEPLOY_LOADGEN = "deploy_loadgen"
    START_LOADGEN = "start_loadgen"
    STOP_LOADGEN = "stop_loadgen"


@dataclass(frozen=True)
class DeploymentResult:
    """Result of a deployment operation."""

    success: bool
    action: str
    message: str
    details: Optional[dict] = None


class DeploymentService:
    """Service for deploying and managing remote services."""

    # Default paths for services
    LINUX_EMULATOR_PATH = "/opt/emulator"
    LINUX_LOADGEN_PATH = "/opt/loadgen"
    WINDOWS_EMULATOR_PATH = "C:\\Services\\Emulator"
    WINDOWS_LOADGEN_PATH = "C:\\Services\\LoadGen"

    def __init__(self):
        self._executors: dict[int, RemoteExecutor] = {}

    def create_executor(
        self,
        server_id: int,
        hostname: str,
        os_family: OSFamily,
        username: str,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        port: Optional[int] = None,
    ) -> RemoteExecutor:
        """Create and cache an executor for a server."""
        if os_family == OSFamily.WINDOWS:
            config = WinRMConfig(
                hostname=hostname,
                username=username,
                password=password or "",
                port=port or 5985,
                os_family=os_family,
            )
            executor = WinRMExecutor(config)
        else:
            config = SSHConfig(
                hostname=hostname,
                username=username,
                key_path=key_path,
                password=password,
                port=port or 22,
                os_family=os_family,
            )
            executor = SSHExecutor(config)

        self._executors[server_id] = executor
        return executor

    def get_executor(self, server_id: int) -> Optional[RemoteExecutor]:
        """Get cached executor for a server."""
        return self._executors.get(server_id)

    def remove_executor(self, server_id: int) -> None:
        """Remove and disconnect executor for a server."""
        executor = self._executors.pop(server_id, None)
        if executor and executor.is_connected:
            executor.disconnect()

    async def deploy_emulator(
        self,
        executor: RemoteExecutor,
        package_path: str,
        emulator_port: int = 8080,
    ) -> DeploymentResult:
        """Deploy emulator service to remote host."""
        os_family = executor.config.os_family

        if os_family == OSFamily.WINDOWS:
            return await self._deploy_emulator_windows(executor, package_path, emulator_port)
        else:
            return await self._deploy_emulator_linux(executor, package_path, emulator_port)

    async def _deploy_emulator_linux(
        self,
        executor: RemoteExecutor,
        package_path: str,
        emulator_port: int,
    ) -> DeploymentResult:
        """Deploy emulator to Linux host."""
        try:
            deploy_path = self.LINUX_EMULATOR_PATH

            # Create deployment directory
            executor.mkdir(deploy_path)

            # Upload package
            remote_package = f"{deploy_path}/emulator.tar.gz"
            transfer = executor.upload_file(package_path, remote_package)
            if not transfer.success:
                return DeploymentResult(
                    success=False,
                    action=DeploymentAction.DEPLOY_EMULATOR.value,
                    message=f"Failed to upload package: {transfer.error_message}",
                )

            # Extract package
            result = executor.execute_command(
                f"cd {deploy_path} && tar -xzf emulator.tar.gz"
            )
            if not result.success:
                return DeploymentResult(
                    success=False,
                    action=DeploymentAction.DEPLOY_EMULATOR.value,
                    message=f"Failed to extract package: {result.stderr}",
                )

            # Install dependencies
            result = executor.execute_command(
                f"cd {deploy_path} && pip3 install -r requirements.txt"
            )

            # Create systemd service
            service_content = f"""[Unit]
Description=Agent Performance Emulator Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={deploy_path}
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port {emulator_port}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            result = executor.execute_command(
                f"echo '{service_content}' > /etc/systemd/system/emulator.service"
            )
            if not result.success:
                return DeploymentResult(
                    success=False,
                    action=DeploymentAction.DEPLOY_EMULATOR.value,
                    message=f"Failed to create service file: {result.stderr}",
                )

            # Reload systemd
            executor.execute_command("systemctl daemon-reload")

            return DeploymentResult(
                success=True,
                action=DeploymentAction.DEPLOY_EMULATOR.value,
                message=f"Emulator deployed to {deploy_path}",
                details={"path": deploy_path, "port": emulator_port},
            )

        except Exception as e:
            return DeploymentResult(
                success=False,
                action=DeploymentAction.DEPLOY_EMULATOR.value,
                message=str(e),
            )

    async def _deploy_emulator_windows(
        self,
        executor: RemoteExecutor,
        package_path: str,
        emulator_port: int,
    ) -> DeploymentResult:
        """Deploy emulator to Windows host."""
        try:
            deploy_path = self.WINDOWS_EMULATOR_PATH

            # Create deployment directory
            executor.mkdir(deploy_path)

            # Upload package
            remote_package = f"{deploy_path}\\emulator.zip"
            transfer = executor.upload_file(package_path, remote_package)
            if not transfer.success:
                return DeploymentResult(
                    success=False,
                    action=DeploymentAction.DEPLOY_EMULATOR.value,
                    message=f"Failed to upload package: {transfer.error_message}",
                )

            # Extract package
            result = executor.execute_command(
                f"Expand-Archive -Path '{remote_package}' -DestinationPath '{deploy_path}' -Force"
            )
            if not result.success:
                return DeploymentResult(
                    success=False,
                    action=DeploymentAction.DEPLOY_EMULATOR.value,
                    message=f"Failed to extract package: {result.stderr}",
                )

            # Install as Windows service using NSSM or similar
            # For now, create a scheduled task
            result = executor.execute_command(
                f"schtasks /Create /TN 'EmulatorService' /TR "
                f"'python -m uvicorn app.main:app --host 0.0.0.0 --port {emulator_port}' "
                f"/SC ONSTART /RU SYSTEM /F"
            )

            return DeploymentResult(
                success=True,
                action=DeploymentAction.DEPLOY_EMULATOR.value,
                message=f"Emulator deployed to {deploy_path}",
                details={"path": deploy_path, "port": emulator_port},
            )

        except Exception as e:
            return DeploymentResult(
                success=False,
                action=DeploymentAction.DEPLOY_EMULATOR.value,
                message=str(e),
            )

    async def start_emulator(self, executor: RemoteExecutor) -> DeploymentResult:
        """Start emulator service on remote host."""
        os_family = executor.config.os_family

        if os_family == OSFamily.WINDOWS:
            result = executor.execute_command("schtasks /Run /TN 'EmulatorService'")
        else:
            result = executor.execute_command("systemctl start emulator")

        return DeploymentResult(
            success=result.success,
            action=DeploymentAction.START_EMULATOR.value,
            message="Emulator started" if result.success else result.stderr,
        )

    async def stop_emulator(self, executor: RemoteExecutor) -> DeploymentResult:
        """Stop emulator service on remote host."""
        os_family = executor.config.os_family

        if os_family == OSFamily.WINDOWS:
            result = executor.execute_command("schtasks /End /TN 'EmulatorService'")
        else:
            result = executor.execute_command("systemctl stop emulator")

        return DeploymentResult(
            success=result.success,
            action=DeploymentAction.STOP_EMULATOR.value,
            message="Emulator stopped" if result.success else result.stderr,
        )

    async def check_emulator(
        self, executor: RemoteExecutor, port: int = 8080
    ) -> DeploymentResult:
        """Check if emulator is running and responding."""
        os_family = executor.config.os_family

        # Check process
        if os_family == OSFamily.WINDOWS:
            result = executor.execute_command(
                f"(Invoke-WebRequest -Uri 'http://localhost:{port}/health' "
                f"-UseBasicParsing).StatusCode"
            )
        else:
            result = executor.execute_command(
                f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/health"
            )

        is_healthy = result.success and "200" in result.stdout

        return DeploymentResult(
            success=is_healthy,
            action=DeploymentAction.CHECK_EMULATOR.value,
            message="Emulator is healthy" if is_healthy else "Emulator is not responding",
            details={"port": port, "response": result.stdout.strip()},
        )

    async def get_system_info(self, executor: RemoteExecutor) -> dict:
        """Get system information from remote host."""
        if isinstance(executor, SSHExecutor):
            return executor.get_system_info()
        elif isinstance(executor, WinRMExecutor):
            return executor.get_system_info()
        return {}

    async def install_python_dependencies(
        self,
        executor: RemoteExecutor,
        requirements_path: str,
    ) -> CommandResult:
        """Install Python dependencies on remote host."""
        os_family = executor.config.os_family

        if os_family == OSFamily.WINDOWS:
            return executor.execute_command(
                f"pip install -r {requirements_path}",
                timeout=300,
            )
        else:
            return executor.execute_command(
                f"pip3 install -r {requirements_path}",
                timeout=300,
            )

    async def check_python_available(self, executor: RemoteExecutor) -> bool:
        """Check if Python is available on remote host."""
        os_family = executor.config.os_family

        if os_family == OSFamily.WINDOWS:
            result = executor.execute_command("python --version")
        else:
            result = executor.execute_command("python3 --version")

        return result.success

    async def get_running_processes(
        self,
        executor: RemoteExecutor,
        process_name: str,
    ) -> List[dict]:
        """Get list of running processes matching name."""
        os_family = executor.config.os_family
        processes = []

        if os_family == OSFamily.WINDOWS:
            result = executor.execute_command(
                f"Get-Process -Name '*{process_name}*' -ErrorAction SilentlyContinue | "
                f"Select-Object Id, ProcessName, CPU | ConvertTo-Json"
            )
            if result.success and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        processes = [data]
                    else:
                        processes = data
                except json.JSONDecodeError:
                    pass
        else:
            result = executor.execute_command(
                f"ps aux | grep {process_name} | grep -v grep"
            )
            if result.success:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split()
                        if len(parts) >= 2:
                            processes.append({
                                "pid": parts[1],
                                "name": parts[-1] if len(parts) > 10 else process_name,
                            })

        return processes
