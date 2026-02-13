"""Production implementations of orchestration protocols.

Implements SnapshotManager and EmulatorManager protocols used by orchestrators.
Includes environment-aware factories for production and Docker E2E modes.
"""

import asyncio
import logging
from typing import Optional, Protocol

from app.calibration.emulator_client import EmulatorClient, TestConfig
from app.orchestration.environment import (
    EnvironmentType,
    EnvironmentConfig,
    ContainerConfig,
    get_environment_config,
)


logger = logging.getLogger(__name__)


class HypervisorClient(Protocol):
    """Protocol for hypervisor operations (vSphere, HyperV, etc.)."""

    async def revert_to_snapshot(
        self,
        vm_id: str,
        snapshot_id: str,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Revert VM to snapshot. Returns (success, error_message)."""
        ...

    async def wait_for_vm_ready(
        self,
        vm_id: str,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for VM to be powered on and tools ready."""
        ...


class HTTPEmulatorManager:
    """
    EmulatorManager implementation using HTTP.

    Wraps EmulatorClient to implement the EmulatorManager protocol.
    Controls emulator load tests via the emulator's REST API.
    """

    def __init__(
        self,
        emulator_clients: dict[int, EmulatorClient],  # target_id -> client
    ):
        """
        Initialize with emulator clients for each target.

        Args:
            emulator_clients: Map of target_id to EmulatorClient instance
        """
        self._clients = emulator_clients
        self._active_tests: dict[int, str] = {}  # target_id -> test_id

    async def start_emulator(
        self,
        target_id: int,
        thread_count: int,
        target_cpu_percent: float,
    ) -> tuple[bool, Optional[str]]:
        """Start CPU emulator load test on target."""
        client = self._clients.get(target_id)
        if not client:
            return False, f"No emulator client for target {target_id}"

        try:
            # Check if emulator is healthy
            if not await client.health_check():
                return False, "Emulator service is not healthy"

            # Calculate intensity based on target CPU
            # This is a simplified mapping - calibration provides better values
            intensity = min(1.0, target_cpu_percent / 100.0 * 1.5)

            config = TestConfig(
                thread_count=thread_count,
                duration_sec=14400,  # 4 hours - will be stopped explicitly
                cpu_duration_ms=100,
                cpu_intensity=intensity,
            )

            test_id = await client.start_test(config)
            self._active_tests[target_id] = test_id

            logger.info(f"Started emulator test {test_id} on target {target_id}")
            return True, None

        except Exception as e:
            logger.error(f"Failed to start emulator on target {target_id}: {e}")
            return False, str(e)

    async def stop_emulator(
        self,
        target_id: int,
    ) -> bool:
        """Stop CPU emulator load test on target."""
        client = self._clients.get(target_id)
        if not client:
            return False

        test_id = self._active_tests.get(target_id)
        if not test_id:
            return True  # No active test

        try:
            success = await client.stop_test(test_id)
            if success:
                del self._active_tests[target_id]
            return success

        except Exception as e:
            logger.error(f"Failed to stop emulator on target {target_id}: {e}")
            return False

    async def get_emulator_stats(
        self,
        target_id: int,
    ) -> Optional[dict]:
        """Get emulator statistics."""
        client = self._clients.get(target_id)
        if not client:
            return None

        try:
            stats = await client.get_system_stats()
            return {
                "cpu_percent": stats.cpu_percent,
                "memory_percent": stats.memory_percent,
                "memory_used_mb": stats.memory_used_mb,
            }

        except Exception as e:
            logger.debug(f"Failed to get emulator stats: {e}")
            return None


class HypervisorSnapshotManager:
    """
    SnapshotManager implementation using hypervisor API.

    Calls vSphere/HyperV to revert VMs, then waits for SSH availability.
    """

    def __init__(
        self,
        hypervisor: HypervisorClient,
        target_vm_mapping: dict[int, str],  # target_id -> vm_id
        baseline_snapshot_mapping: dict[int, str],  # baseline_id -> snapshot_id
        ssh_check_host_mapping: dict[int, str],  # target_id -> hostname/IP
        ssh_check_port: int = 22,
    ):
        """
        Initialize snapshot manager.

        Args:
            hypervisor: Hypervisor client for VM operations
            target_vm_mapping: Map target_id to VM identifier
            baseline_snapshot_mapping: Map baseline_id to snapshot identifier
            ssh_check_host_mapping: Map target_id to SSH host for readiness check
            ssh_check_port: SSH port for readiness check
        """
        self._hypervisor = hypervisor
        self._target_vms = target_vm_mapping
        self._snapshots = baseline_snapshot_mapping
        self._ssh_hosts = ssh_check_host_mapping
        self._ssh_port = ssh_check_port

    async def restore_snapshot(
        self,
        target_id: int,
        baseline_id: int,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Restore target to baseline snapshot."""
        vm_id = self._target_vms.get(target_id)
        if not vm_id:
            return False, f"No VM mapping for target {target_id}"

        snapshot_id = self._snapshots.get(baseline_id)
        if not snapshot_id:
            return False, f"No snapshot mapping for baseline {baseline_id}"

        logger.info(f"Reverting target {target_id} (VM {vm_id}) to snapshot {snapshot_id}")

        success, error = await self._hypervisor.revert_to_snapshot(
            vm_id=vm_id,
            snapshot_id=snapshot_id,
            timeout_sec=timeout_sec,
        )

        if not success:
            return False, error

        # Wait for VM to be ready in hypervisor
        ready = await self._hypervisor.wait_for_vm_ready(
            vm_id=vm_id,
            timeout_sec=min(300, timeout_sec),
        )

        if not ready:
            return False, "VM not ready after snapshot restore"

        return True, None

    async def wait_for_target_ready(
        self,
        target_id: int,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for target to be ready (SSH accessible)."""
        host = self._ssh_hosts.get(target_id)
        if not host:
            return False

        return await self._wait_for_ssh(host, self._ssh_port, timeout_sec)

    async def _wait_for_ssh(
        self,
        host: str,
        port: int,
        timeout_sec: int,
    ) -> bool:
        """Wait for SSH port to be accessible."""
        import socket

        start = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout_sec:
                return False

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((host, port))
                sock.close()

                if result == 0:
                    logger.info(f"SSH available on {host}:{port}")
                    return True

            except Exception:
                pass

            await asyncio.sleep(5)


class DockerSnapshotManager:
    """
    SnapshotManager for Docker containers.

    Instead of calling vSphere/HyperV, calls container reset endpoints
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

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url)
                if response.status_code == 200:
                    logger.info(f"Container {config.name} reset successful")
                    return True, None
                return False, f"Reset failed: {response.status_code}"
        except Exception as e:
            return False, f"Reset HTTP call failed: {e}"

    async def _reset_via_ssh(
        self,
        config: ContainerConfig,
    ) -> tuple[bool, Optional[str]]:
        """Reset container via SSH script."""
        from app.remote.ssh_executor import SSHExecutor, SSHConfig
        from app.remote.base import OSFamily

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
        """Wait for container to be ready via health check."""
        config = self._configs.get(target_id)
        if not config:
            return False

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
                        logger.info(f"Container {config.name} is ready")
                        return True
            except Exception:
                pass

            await asyncio.sleep(2)


class SSHJMeterExecutor:
    """
    RemoteExecutor for JMeterService using SSH.

    Runs JMeter CLI commands on a load generator via SSH.
    """

    def __init__(
        self,
        ssh_executor,  # SSHExecutor instance
    ):
        """
        Initialize with SSH executor connected to load generator.

        Args:
            ssh_executor: Connected SSHExecutor instance
        """
        self._ssh = ssh_executor
        self._background_pids: dict[str, str] = {}

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command and return (exit_code, stdout, stderr)."""
        result = self._ssh.execute_command(command, timeout=timeout_sec)
        return result.exit_code, result.stdout, result.stderr

    async def execute_background(
        self,
        command: str,
    ) -> str:
        """Execute command in background, return process ID."""
        result = self._ssh.execute_command(
            f"nohup {command} > /tmp/jmeter_out.log 2>&1 & echo $!",
            timeout=30,
        )

        if result.success:
            pid = result.stdout.strip()
            self._background_pids[pid] = command
            return pid

        raise RuntimeError(f"Failed to start background process: {result.stderr}")

    async def check_process(self, process_id: str) -> bool:
        """Check if process is still running."""
        result = self._ssh.execute_command(
            f"ps -p {process_id} -o pid= 2>/dev/null",
            timeout=10,
        )
        return result.success and process_id in result.stdout

    async def kill_process(self, process_id: str) -> bool:
        """Kill a background process."""
        self._ssh.execute_command(f"kill -9 {process_id} 2>/dev/null", timeout=10)
        self._background_pids.pop(process_id, None)
        return True

    async def read_file(self, file_path: str) -> Optional[str]:
        """Read file contents."""
        result = self._ssh.execute_command(f"cat {file_path}", timeout=60)
        return result.stdout if result.success else None

    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        result = self._ssh.execute_command(f"test -f {file_path}", timeout=10)
        return result.success

    async def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        result = self._ssh.execute_command(
            f"stat -c%s {file_path} 2>/dev/null || stat -f%z {file_path} 2>/dev/null",
            timeout=10,
        )
        if result.success:
            try:
                return int(result.stdout.strip())
            except ValueError:
                pass
        return 0


class TestExecutorFactory:
    """
    Factory for building TestExecutor with all dependencies.

    Constructs the full dependency graph needed for barrier-based
    test execution across all targets.
    """

    @staticmethod
    def create(
        workflow_service,
        package_orchestrator,
        jmeter_service,
        jmx_deployment_service,
        result_collector,
        snapshot_manager,
        emulator_manager,
        target_delivery_factory,
        loadgen_delivery_factory,
        ssh_transfer_factory,
    ):
        """
        Create a TestExecutor with all dependencies.

        Args:
            workflow_service: WorkflowStateService for state updates
            package_orchestrator: PackageInstallOrchestrator for packages
            jmeter_service: JMeterService for load tests
            jmx_deployment_service: JMXDeploymentService for JMX generation
            result_collector: ResultCollector for collecting results
            snapshot_manager: SnapshotManager protocol implementation
            emulator_manager: EmulatorManager protocol implementation
            target_delivery_factory: Factory(target_id) -> DeliveryStrategy
            loadgen_delivery_factory: Factory(loadgen_id) -> DeliveryStrategy
            ssh_transfer_factory: Factory(loadgen_id) -> SSHFileTransfer

        Returns:
            Configured TestExecutor instance
        """
        from app.orchestration.test_executor import TestExecutor

        return TestExecutor(
            workflow_service=workflow_service,
            package_orchestrator=package_orchestrator,
            jmeter_service=jmeter_service,
            jmx_deployment_service=jmx_deployment_service,
            result_collector=result_collector,
            snapshot_manager=snapshot_manager,
            emulator_manager=emulator_manager,
            target_delivery_factory=target_delivery_factory,
            loadgen_delivery_factory=loadgen_delivery_factory,
            ssh_transfer_factory=ssh_transfer_factory,
        )

    @staticmethod
    def create_for_production(
        db_session,
        hypervisor_client,
        target_configs: list,  # list of TargetConfig
        ssh_executor_factory,  # Factory(host, port) -> SSHExecutor
    ):
        """
        Create a TestExecutor configured for production use.

        This is a convenience method that sets up all production
        implementations of protocols and services.

        Args:
            db_session: Database session for services
            hypervisor_client: vSphere/HyperV client for snapshots
            target_configs: List of TargetConfig objects
            ssh_executor_factory: Factory to create SSH executors

        Returns:
            Configured TestExecutor instance
        """
        from app.services.workflow_state_service import WorkflowStateService
        from app.packages.orchestrator import PackageInstallOrchestrator
        from app.jmeter.service import JMeterService
        from app.jmeter.deployment import (
            JMXDeploymentService,
            SSHFileTransferAdapter,
        )
        from app.results.collector import ResultCollector
        from app.packages.delivery import DirectDeliveryStrategy

        # Build mappings from target configs
        target_vm_mapping = {}
        baseline_snapshot_mapping = {}
        ssh_hosts = {}
        emulator_clients = {}

        for tc in target_configs:
            target_vm_mapping[tc.target_id] = f"vm_{tc.target_id}"
            baseline_snapshot_mapping[tc.baseline_id] = f"snap_{tc.baseline_id}"
            ssh_hosts[tc.target_id] = tc.target_ip

            # Create emulator client for each target
            emulator_clients[tc.target_id] = EmulatorClient(
                base_url=f"http://{tc.target_ip}:8080",
            )

        # Create managers
        snapshot_manager = HypervisorSnapshotManager(
            hypervisor=hypervisor_client,
            target_vm_mapping=target_vm_mapping,
            baseline_snapshot_mapping=baseline_snapshot_mapping,
            ssh_check_host_mapping=ssh_hosts,
        )

        emulator_manager = HTTPEmulatorManager(
            emulator_clients=emulator_clients,
        )

        # SSH executors cache
        ssh_executors = {}

        def get_ssh_executor(target_id: int):
            if target_id not in ssh_executors:
                tc = next((t for t in target_configs if t.target_id == target_id), None)
                if tc:
                    ssh_executors[target_id] = ssh_executor_factory(
                        tc.target_ip, 22
                    )
            return ssh_executors.get(target_id)

        def get_loadgen_ssh(loadgen_id: int):
            if loadgen_id not in ssh_executors:
                tc = next((t for t in target_configs if t.loadgen_id == loadgen_id), None)
                if tc:
                    ssh_executors[loadgen_id] = ssh_executor_factory(
                        tc.loadgen_ip, 22
                    )
            return ssh_executors.get(loadgen_id)

        # Delivery strategies
        def target_delivery_factory(target_id: int):
            executor = get_ssh_executor(target_id)
            return DirectDeliveryStrategy(executor)

        def loadgen_delivery_factory(loadgen_id: int):
            executor = get_loadgen_ssh(loadgen_id)
            return DirectDeliveryStrategy(executor)

        def ssh_transfer_factory(loadgen_id: int):
            executor = get_loadgen_ssh(loadgen_id)
            return SSHFileTransferAdapter(executor)

        # Services
        workflow_service = WorkflowStateService(db_session)
        package_orchestrator = PackageInstallOrchestrator(db_session)
        jmeter_service = JMeterService()
        jmx_deployment_service = JMXDeploymentService()
        result_collector = ResultCollector(db_session)

        return TestExecutorFactory.create(
            workflow_service=workflow_service,
            package_orchestrator=package_orchestrator,
            jmeter_service=jmeter_service,
            jmx_deployment_service=jmx_deployment_service,
            result_collector=result_collector,
            snapshot_manager=snapshot_manager,
            emulator_manager=emulator_manager,
            target_delivery_factory=target_delivery_factory,
            loadgen_delivery_factory=loadgen_delivery_factory,
            ssh_transfer_factory=ssh_transfer_factory,
        )

    @staticmethod
    def create_for_docker(
        db_session,
        target_configs: list,  # list of TargetConfig
        container_configs: dict[int, ContainerConfig],  # target_id -> ContainerConfig
        loadgen_container: ContainerConfig,
    ):
        """
        Create a TestExecutor configured for Docker E2E testing.

        Args:
            db_session: Database session for services
            target_configs: List of TargetConfig objects
            container_configs: Map of target_id to ContainerConfig
            loadgen_container: ContainerConfig for load generator

        Returns:
            Configured TestExecutor instance
        """
        from app.services.workflow_state_service import WorkflowStateService
        from app.packages.orchestrator import PackageInstallOrchestrator
        from app.jmeter.service import JMeterService
        from app.jmeter.deployment import (
            JMXDeploymentService,
            SSHFileTransferAdapter,
        )
        from app.results.collector import ResultCollector
        from app.packages.delivery import DirectDeliveryStrategy
        from app.remote.ssh_executor import SSHExecutor, SSHConfig
        from app.remote.base import OSFamily

        # Create Docker snapshot manager
        snapshot_manager = DockerSnapshotManager(
            container_configs=container_configs,
            reset_via_http=True,
        )

        # Create emulator clients (same HTTP API as production)
        emulator_clients = {}
        for tc in target_configs:
            container = container_configs.get(tc.target_id)
            if container:
                emulator_clients[tc.target_id] = EmulatorClient(
                    base_url=f"http://{container.host}:{container.http_port}",
                )

        emulator_manager = HTTPEmulatorManager(
            emulator_clients=emulator_clients,
        )

        # SSH executors cache
        ssh_executors = {}

        def get_ssh_executor(target_id: int):
            if target_id not in ssh_executors:
                container = container_configs.get(target_id)
                if container:
                    ssh_config = SSHConfig(
                        hostname=container.host,
                        port=container.ssh_port,
                        username=container.ssh_user,
                        password=container.ssh_password,
                        os_family=OSFamily.LINUX,
                    )
                    executor = SSHExecutor(ssh_config)
                    executor.connect()
                    ssh_executors[target_id] = executor
            return ssh_executors.get(target_id)

        def get_loadgen_ssh(loadgen_id: int):
            key = f"loadgen_{loadgen_id}"
            if key not in ssh_executors:
                ssh_config = SSHConfig(
                    hostname=loadgen_container.host,
                    port=loadgen_container.ssh_port,
                    username=loadgen_container.ssh_user,
                    password=loadgen_container.ssh_password,
                    os_family=OSFamily.LINUX,
                )
                executor = SSHExecutor(ssh_config)
                executor.connect()
                ssh_executors[key] = executor
            return ssh_executors.get(key)

        # Delivery strategies
        def target_delivery_factory(target_id: int):
            executor = get_ssh_executor(target_id)
            return DirectDeliveryStrategy(executor)

        def loadgen_delivery_factory(loadgen_id: int):
            executor = get_loadgen_ssh(loadgen_id)
            return DirectDeliveryStrategy(executor)

        def ssh_transfer_factory(loadgen_id: int):
            executor = get_loadgen_ssh(loadgen_id)
            return SSHFileTransferAdapter(executor)

        # Services
        workflow_service = WorkflowStateService(db_session)
        package_orchestrator = PackageInstallOrchestrator(db_session)
        jmeter_service = JMeterService()
        jmx_deployment_service = JMXDeploymentService()
        result_collector = ResultCollector(db_session)

        return TestExecutorFactory.create(
            workflow_service=workflow_service,
            package_orchestrator=package_orchestrator,
            jmeter_service=jmeter_service,
            jmx_deployment_service=jmx_deployment_service,
            result_collector=result_collector,
            snapshot_manager=snapshot_manager,
            emulator_manager=emulator_manager,
            target_delivery_factory=target_delivery_factory,
            loadgen_delivery_factory=loadgen_delivery_factory,
            ssh_transfer_factory=ssh_transfer_factory,
        )

    @staticmethod
    def create_for_environment(
        db_session,
        target_configs: list,
        env_config: Optional[EnvironmentConfig] = None,
        hypervisor_client=None,
        ssh_executor_factory=None,
    ):
        """
        Create TestExecutor based on environment configuration.

        This is the main entry point that automatically switches between
        production and Docker modes based on environment config.

        Args:
            db_session: Database session
            target_configs: List of TargetConfig objects
            env_config: Environment config (uses global if not provided)
            hypervisor_client: Required for production mode
            ssh_executor_factory: Required for production mode

        Returns:
            Configured TestExecutor instance
        """
        if env_config is None:
            env_config = get_environment_config()

        if env_config.is_docker:
            # Build container configs from target configs
            container_configs = {}
            for tc in target_configs:
                container = env_config.containers.get(tc.target_id)
                if container:
                    container_configs[tc.target_id] = container

            # Get loadgen container (use first one or dedicated)
            loadgen_container = env_config.containers.get(
                target_configs[0].loadgen_id if target_configs else 0,
                ContainerConfig(
                    name="loadgen",
                    host=env_config.docker_host,
                    http_port=0,
                    ssh_port=2223,
                ),
            )

            return TestExecutorFactory.create_for_docker(
                db_session=db_session,
                target_configs=target_configs,
                container_configs=container_configs,
                loadgen_container=loadgen_container,
            )
        else:
            if not hypervisor_client or not ssh_executor_factory:
                raise ValueError(
                    "hypervisor_client and ssh_executor_factory required for production"
                )

            return TestExecutorFactory.create_for_production(
                db_session=db_session,
                hypervisor_client=hypervisor_client,
                target_configs=target_configs,
                ssh_executor_factory=ssh_executor_factory,
            )


class CalibrationExecutorFactory:
    """
    Factory for building CalibrationExecutor with all dependencies.

    Constructs the dependency graph needed for barrier-based
    calibration execution across all targets.
    """

    @staticmethod
    def create(
        calibration_service,
        snapshot_manager,
        emulator_client_factory,
    ):
        """
        Create a CalibrationExecutor with all dependencies.

        Args:
            calibration_service: CalibrationService for calibration logic
            snapshot_manager: SnapshotManager protocol implementation
            emulator_client_factory: Factory(target_id, host, port) -> EmulatorClient

        Returns:
            Configured CalibrationExecutor instance
        """
        from app.orchestration.calibration_executor import CalibrationExecutor

        return CalibrationExecutor(
            calibration_service=calibration_service,
            snapshot_manager=snapshot_manager,
            emulator_client_factory=emulator_client_factory,
        )

    @staticmethod
    def create_for_production(
        hypervisor_client,
        target_configs: list,  # list of CalibrationTargetConfig
    ):
        """
        Create a CalibrationExecutor configured for production use.

        Args:
            hypervisor_client: vSphere/HyperV client for snapshots
            target_configs: List of CalibrationTargetConfig objects

        Returns:
            Configured CalibrationExecutor instance
        """
        from app.calibration.service import CalibrationService
        from app.calibration.emulator_client import EmulatorClient

        # Build mappings from target configs
        target_vm_mapping = {}
        baseline_snapshot_mapping = {}
        ssh_hosts = {}

        for tc in target_configs:
            target_vm_mapping[tc.target_id] = f"vm_{tc.target_id}"
            baseline_snapshot_mapping[tc.baseline_id] = f"snap_{tc.baseline_id}"
            ssh_hosts[tc.target_id] = tc.target_ip

        # Create snapshot manager
        snapshot_manager = HypervisorSnapshotManager(
            hypervisor=hypervisor_client,
            target_vm_mapping=target_vm_mapping,
            baseline_snapshot_mapping=baseline_snapshot_mapping,
            ssh_check_host_mapping=ssh_hosts,
        )

        # Emulator client factory
        def emulator_client_factory(target_id: int, host: str, port: int):
            return EmulatorClient(host, port)

        # Calibration service
        calibration_service = CalibrationService()

        return CalibrationExecutorFactory.create(
            calibration_service=calibration_service,
            snapshot_manager=snapshot_manager,
            emulator_client_factory=emulator_client_factory,
        )

    @staticmethod
    def create_for_docker(
        target_configs: list,  # list of CalibrationTargetConfig
        container_configs: dict[int, ContainerConfig],  # target_id -> ContainerConfig
    ):
        """
        Create a CalibrationExecutor configured for Docker E2E testing.

        Args:
            target_configs: List of CalibrationTargetConfig objects
            container_configs: Map of target_id to ContainerConfig

        Returns:
            Configured CalibrationExecutor instance
        """
        from app.calibration.service import CalibrationService
        from app.calibration.emulator_client import EmulatorClient

        # Create Docker snapshot manager
        snapshot_manager = DockerSnapshotManager(
            container_configs=container_configs,
            reset_via_http=True,
        )

        # Emulator client factory
        def emulator_client_factory(target_id: int, host: str, port: int):
            return EmulatorClient(host, port)

        # Calibration service
        calibration_service = CalibrationService()

        return CalibrationExecutorFactory.create(
            calibration_service=calibration_service,
            snapshot_manager=snapshot_manager,
            emulator_client_factory=emulator_client_factory,
        )

    @staticmethod
    def create_for_environment(
        target_configs: list,
        env_config: Optional[EnvironmentConfig] = None,
        hypervisor_client=None,
    ):
        """
        Create CalibrationExecutor based on environment configuration.

        Args:
            target_configs: List of CalibrationTargetConfig objects
            env_config: Environment config (uses global if not provided)
            hypervisor_client: Required for production mode

        Returns:
            Configured CalibrationExecutor instance
        """
        if env_config is None:
            env_config = get_environment_config()

        if env_config.is_docker:
            # Build container configs from target configs
            container_configs = {}
            for tc in target_configs:
                container = env_config.containers.get(tc.target_id)
                if container:
                    container_configs[tc.target_id] = container
                else:
                    # Create default container config
                    container_configs[tc.target_id] = ContainerConfig(
                        name=f"target_{tc.target_id}",
                        host=env_config.docker_host,
                        http_port=tc.emulator_port,
                        ssh_port=2222 + tc.target_id,
                    )

            return CalibrationExecutorFactory.create_for_docker(
                target_configs=target_configs,
                container_configs=container_configs,
            )
        else:
            if not hypervisor_client:
                raise ValueError("hypervisor_client required for production")

            return CalibrationExecutorFactory.create_for_production(
                hypervisor_client=hypervisor_client,
                target_configs=target_configs,
            )
