"""Docker E2E test setup using production code.

Configures production implementations to work with Docker containers.
Containers expose the same interfaces as production VMs:
- Emulator: HTTP API on configured port
- SSH: For package installation and JMeter execution
- Reset endpoint: For snapshot-like state restoration

The only Docker-specific code is the SnapshotManager that calls
container reset endpoints instead of vSphere API.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.calibration.emulator_client import EmulatorClient
from app.orchestration.managers import (
    HTTPEmulatorManager,
    SSHJMeterExecutor,
)
from app.remote.ssh_executor import SSHExecutor, SSHConfig
from app.remote.base import OSFamily
from app.packages.delivery import DirectDeliveryStrategy


logger = logging.getLogger(__name__)


@dataclass
class ContainerConfig:
    """Configuration for a Docker container."""

    name: str
    host: str  # Usually "localhost" for local Docker
    http_port: int  # For emulator API
    ssh_port: int  # For SSH access
    ssh_user: str = "root"
    ssh_password: str = "testpass"


class DockerSnapshotManager:
    """
    SnapshotManager for Docker containers.

    Instead of calling vSphere, calls container reset endpoints
    or runs reset scripts via SSH.
    """

    def __init__(
        self,
        container_configs: dict[int, ContainerConfig],  # target_id -> config
        reset_via_http: bool = True,  # Use HTTP /reset or SSH script
    ):
        self._configs = container_configs
        self._reset_via_http = reset_via_http

    async def restore_snapshot(
        self,
        target_id: int,
        baseline_id: int,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Restore container to baseline state."""
        config = self._configs.get(target_id)
        if not config:
            return False, f"No config for target {target_id}"

        try:
            if self._reset_via_http:
                return await self._reset_via_http_endpoint(config)
            else:
                return await self._reset_via_ssh(config)

        except Exception as e:
            logger.error(f"Container reset failed: {e}")
            return False, str(e)

    async def _reset_via_http_endpoint(
        self,
        config: ContainerConfig,
    ) -> tuple[bool, Optional[str]]:
        """Reset container via HTTP /reset endpoint."""
        import httpx

        url = f"http://{config.host}:{config.http_port}/reset"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url)
            if response.status_code == 200:
                return True, None
            return False, f"Reset failed: {response.status_code}"

    async def _reset_via_ssh(
        self,
        config: ContainerConfig,
    ) -> tuple[bool, Optional[str]]:
        """Reset container via SSH script."""
        ssh_config = SSHConfig(
            hostname=config.host,
            port=config.ssh_port,
            username=config.ssh_user,
            password=config.ssh_password,
            os_family=OSFamily.LINUX,
        )

        executor = SSHExecutor(ssh_config)
        try:
            executor.connect()
            result = executor.execute_command(
                "/opt/scripts/reset-state.sh",
                timeout=60,
            )
            return result.success, result.stderr if not result.success else None
        finally:
            executor.disconnect()

    async def wait_for_target_ready(
        self,
        target_id: int,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for container to be ready."""
        config = self._configs.get(target_id)
        if not config:
            return False

        # Check HTTP health endpoint
        import httpx

        url = f"http://{config.host}:{config.http_port}/health"
        start = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout_sec:
                return False

            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return True
            except Exception:
                pass

            await asyncio.sleep(2)


class DockerE2EFactory:
    """
    Factory for creating production managers configured for Docker.

    Creates the same production implementations used in real deployments,
    but configured to talk to Docker containers.
    """

    def __init__(
        self,
        emulator_config: ContainerConfig,
        loadgen_config: ContainerConfig,
        target_configs: Optional[dict[int, ContainerConfig]] = None,
    ):
        """
        Initialize factory with container configurations.

        Args:
            emulator_config: Config for emulator container
            loadgen_config: Config for load generator container
            target_configs: Optional map of target_id -> ContainerConfig
        """
        self.emulator_config = emulator_config
        self.loadgen_config = loadgen_config
        self.target_configs = target_configs or {1: emulator_config}

    def create_emulator_manager(self) -> HTTPEmulatorManager:
        """Create production EmulatorManager for Docker containers."""
        clients = {}
        for target_id, config in self.target_configs.items():
            clients[target_id] = EmulatorClient(
                host=config.host,
                port=config.http_port,
            )

        return HTTPEmulatorManager(emulator_clients=clients)

    def create_snapshot_manager(self) -> DockerSnapshotManager:
        """Create SnapshotManager for Docker containers."""
        return DockerSnapshotManager(
            container_configs=self.target_configs,
            reset_via_http=True,
        )

    def create_jmeter_executor(self) -> SSHJMeterExecutor:
        """Create JMeter executor for load generator container."""
        ssh_config = SSHConfig(
            hostname=self.loadgen_config.host,
            port=self.loadgen_config.ssh_port,
            username=self.loadgen_config.ssh_user,
            password=self.loadgen_config.ssh_password,
            os_family=OSFamily.LINUX,
        )

        executor = SSHExecutor(ssh_config)
        executor.connect()

        return SSHJMeterExecutor(ssh_executor=executor)

    def create_delivery_strategy(
        self,
        target_id: int,
    ) -> DirectDeliveryStrategy:
        """Create delivery strategy for a target container."""
        config = self.target_configs.get(target_id)
        if not config:
            raise ValueError(f"No config for target {target_id}")

        ssh_config = SSHConfig(
            hostname=config.host,
            port=config.ssh_port,
            username=config.ssh_user,
            password=config.ssh_password,
            os_family=OSFamily.LINUX,
        )

        executor = SSHExecutor(ssh_config)
        executor.connect()

        return DirectDeliveryStrategy(
            executor=AsyncSSHExecutorAdapter(executor),
        )


class AsyncSSHExecutorAdapter:
    """Adapts sync SSHExecutor to async RemoteExecutor protocol."""

    def __init__(self, ssh_executor: SSHExecutor):
        self._ssh = ssh_executor

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command."""
        result = self._ssh.execute_command(command, timeout=timeout_sec)
        return result.exit_code, result.stdout, result.stderr

    async def wait_for_ready(
        self,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for system to be ready."""
        start = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout_sec:
                return False

            try:
                result = self._ssh.execute_command("echo ready", timeout=10)
                if result.success:
                    return True
            except Exception:
                pass

            await asyncio.sleep(5)


# Default configuration matching docker-compose.yml
def create_default_factory(
    host: str = "localhost",
    emulator_http_port: int = 8080,
    emulator_ssh_port: int = 2222,
    loadgen_ssh_port: int = 2223,
) -> DockerE2EFactory:
    """Create factory with default Docker Compose port mappings."""
    return DockerE2EFactory(
        emulator_config=ContainerConfig(
            name="emulator",
            host=host,
            http_port=emulator_http_port,
            ssh_port=emulator_ssh_port,
        ),
        loadgen_config=ContainerConfig(
            name="loadgen",
            host=host,
            http_port=0,  # Load generator doesn't need HTTP
            ssh_port=loadgen_ssh_port,
        ),
    )
