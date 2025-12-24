"""E2E test runner for Docker-based testing.

Bridges the gap between:
- Seeded test data (from seeder.py)
- Executor configs (TargetConfig, CalibrationTargetConfig)
- Environment configuration

Provides a complete E2E test flow:
1. Setup environment (Docker mode)
2. Run calibration (or skip if pre-calibrated)
3. Run test execution with barriers
4. Collect and return results
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration import (
    # Executors
    TestExecutor,
    CalibrationExecutor,
    # Configs
    TestExecutionConfig,
    TargetConfig,
    CalibrationExecutionConfig,
    CalibrationTargetConfig,
    # Results
    TestExecutionResult,
    CalibrationExecutionResult,
    # Factories
    TestExecutorFactory,
    CalibrationExecutorFactory,
    # Environment
    EnvironmentType,
    EnvironmentConfig,
    ContainerConfig,
    set_environment_config,
)
from app.models.orm import ExecutionWorkflowStateORM
from app.models.enums import WorkflowState, PhaseState

from tests.e2e.data.seeder import (
    E2ETestDataSeeder,
    SeededData,
    DockerE2EConfig,
    DockerContainerConfig,
)


logger = logging.getLogger(__name__)


@dataclass
class E2ETestResult:
    """Complete E2E test result."""

    success: bool
    calibration_result: Optional[CalibrationExecutionResult] = None
    execution_results: dict[str, TestExecutionResult] = field(default_factory=dict)
    error_message: Optional[str] = None


class E2ETestRunner:
    """
    Runs complete E2E tests using Docker containers.

    Handles the full flow:
    1. Configure environment for Docker
    2. Create executor configs from seeded data
    3. Run calibration (if needed)
    4. Run test execution for each phase/loadprofile
    5. Collect results
    """

    def __init__(
        self,
        db_session: AsyncSession,
        seeded_data: SeededData,
        docker_config: DockerE2EConfig,
    ):
        self._session = db_session
        self._data = seeded_data
        self._docker_config = docker_config
        self._env_config: Optional[EnvironmentConfig] = None

    def setup_environment(self) -> EnvironmentConfig:
        """Configure environment for Docker E2E testing."""
        # Build container configs from Docker E2E config
        containers = {}

        for container in self._docker_config.emulator_containers:
            # Find matching server ID
            server = next(
                (s for s in self._data.target_servers
                 if s.hostname == container.hostname),
                None
            )
            if server:
                containers[server.id] = ContainerConfig(
                    name=container.container_name,
                    host=container.ip_address,
                    http_port=container.port,
                    ssh_port=2222,  # Default SSH port in container
                    ssh_user="root",
                    ssh_password="testpass",
                )

        # Add loadgen container
        for container in self._docker_config.loadgen_containers:
            server = next(
                (s for s in self._data.loadgen_servers
                 if s.hostname == container.hostname),
                None
            )
            if server:
                containers[server.id] = ContainerConfig(
                    name=container.container_name,
                    host=container.ip_address,
                    http_port=container.port,
                    ssh_port=2223,  # Different SSH port for loadgen
                    ssh_user="root",
                    ssh_password="testpass",
                )

        self._env_config = EnvironmentConfig.for_docker_e2e(
            host="localhost",
            containers=containers,
        )

        # Set as global config
        set_environment_config(self._env_config)

        logger.info(f"Environment configured for Docker E2E with {len(containers)} containers")
        return self._env_config

    def build_calibration_configs(self) -> list[CalibrationTargetConfig]:
        """Build CalibrationTargetConfig list from seeded data."""
        configs = []

        for server in self._data.target_servers:
            configs.append(CalibrationTargetConfig(
                target_id=server.id,
                target_ip=server.ip_address,
                target_hostname=server.hostname,
                emulator_port=server.emulator_port,
                baseline_id=self._data.baseline.id,
                cpu_count=self._docker_config.cpu_count,
                memory_gb=float(self._docker_config.memory_gb),
            ))

        return configs

    def build_target_configs(self, phase: str, loadprofile: str) -> list[TargetConfig]:
        """
        Build TargetConfig list from seeded data.

        Args:
            phase: Test phase (base, initial, upgrade)
            loadprofile: Load profile (low, medium, high)

        Returns:
            List of TargetConfig for all targets
        """
        configs = []
        loadgen = self._data.loadgen_servers[0]

        for test_run_target in self._data.test_run_targets:
            server = next(
                (s for s in self._data.target_servers
                 if s.id == test_run_target.target_id),
                None
            )
            if not server:
                continue

            # Get calibration data for this target
            calibration = {}
            for cal in self._data.calibration_results:
                if cal.target_id == server.id:
                    profile_name = cal.loadprofile.lower()
                    calibration[profile_name] = {
                        "thread_count": cal.thread_count,
                        "cpu_target": float(cal.cpu_target_percent),
                    }

            # Build package lists
            target_packages = self._get_target_packages(phase)
            jmeter_packages = self._get_jmeter_packages()

            configs.append(TargetConfig(
                target_id=server.id,
                target_ip=server.ip_address,
                target_hostname=server.hostname,
                target_port=server.emulator_port,
                loadgen_id=loadgen.id,
                loadgen_ip=loadgen.ip_address,
                jmeter_port=test_run_target.jmeter_port,
                baseline_id=self._data.baseline.id,
                calibration=calibration,
                target_packages=target_packages,
                jmeter_packages=jmeter_packages,
                jmx_file_path=test_run_target.jmx_file_path,
            ))

        return configs

    def _get_target_packages(self, phase: str) -> list[dict]:
        """Get package list for target server based on phase."""
        packages = []

        # Base phase: emulator only
        # Initial phase: emulator + agent
        # Upgrade phase: emulator + upgraded agent

        # Always include emulator
        for pkg in self._data.packages:
            if pkg.package_type == "emulator":
                packages.append({
                    "package_id": pkg.id,
                    "name": pkg.name,
                    "version": pkg.version,
                    "package_type": pkg.package_type,
                    "delivery_config": pkg.delivery_config,
                    "install_command": pkg.install_command,
                    "verify_command": pkg.verify_command,
                })

        # Include agent for initial/upgrade phases
        if phase in ("initial", "upgrade"):
            if self._data.agent_package:
                pkg = self._data.agent_package
                packages.append({
                    "package_id": pkg.id,
                    "name": pkg.name,
                    "version": pkg.version,
                    "package_type": pkg.package_type,
                    "delivery_config": pkg.delivery_config,
                    "install_command": pkg.install_command,
                    "verify_command": pkg.verify_command,
                })

        return packages

    def _get_jmeter_packages(self) -> list[dict]:
        """Get JMeter package list for load generator."""
        packages = []

        if self._data.jmeter_package:
            pkg = self._data.jmeter_package
            packages.append({
                "package_id": pkg.id,
                "name": pkg.name,
                "version": pkg.version,
                "package_type": pkg.package_type,
                "delivery_config": pkg.delivery_config,
                "install_command": pkg.install_command,
                "verify_command": pkg.verify_command,
            })

        return packages

    async def create_workflow_states(
        self,
        phase: str,
        loadprofile: str,
    ) -> dict[int, ExecutionWorkflowStateORM]:
        """Create workflow state records for each target."""
        workflow_states = {}

        for target in self._data.target_servers:
            workflow_state = ExecutionWorkflowStateORM(
                test_run_id=self._data.test_run.id,
                target_id=target.id,
                workflow_state=WorkflowState.PENDING.value,
                phase_state=PhaseState.PENDING.value,
                current_phase=phase,
                current_loadprofile=loadprofile,
            )
            self._session.add(workflow_state)
            await self._session.flush()

            workflow_states[target.id] = workflow_state

        return workflow_states

    async def run_calibration(
        self,
        skip_if_calibrated: bool = True,
    ) -> Optional[CalibrationExecutionResult]:
        """
        Run calibration for all targets.

        Args:
            skip_if_calibrated: Skip if calibration results exist

        Returns:
            CalibrationExecutionResult or None if skipped
        """
        if skip_if_calibrated and self._data.calibration_results:
            logger.info("Skipping calibration - using pre-seeded results")
            return None

        # Build configs
        target_configs = self.build_calibration_configs()

        # Create executor
        executor = CalibrationExecutorFactory.create_for_environment(
            target_configs=target_configs,
            env_config=self._env_config,
        )

        # Build execution config
        config = CalibrationExecutionConfig(
            test_run_id=self._data.test_run.id,
            scenario_id=self._data.scenario.id,
            targets=target_configs,
            profiles=["low", "medium", "high"],
        )

        # Run calibration
        logger.info("Starting calibration execution")
        result = await executor.execute_calibration(config)

        if result.success:
            logger.info("Calibration completed successfully")
        else:
            logger.error(f"Calibration failed: {result.error_message}")

        return result

    async def run_test_execution(
        self,
        phase: str,
        loadprofile: str,
    ) -> TestExecutionResult:
        """
        Run test execution for a specific phase and load profile.

        Args:
            phase: Test phase (base, initial, upgrade)
            loadprofile: Load profile (low, medium, high)

        Returns:
            TestExecutionResult
        """
        # Build configs
        target_configs = self.build_target_configs(phase, loadprofile)

        # Create workflow states
        workflow_states = await self.create_workflow_states(phase, loadprofile)

        # Create executor
        executor = TestExecutorFactory.create_for_environment(
            db_session=self._session,
            target_configs=target_configs,
            env_config=self._env_config,
        )

        # Build execution config
        config = TestExecutionConfig(
            test_run_id=self._data.test_run.id,
            scenario_id=self._data.scenario.id,
            phase=phase,
            loadprofile=loadprofile,
            targets=target_configs,
            warmup_sec=self._data.test_run.warmup_sec,
            measured_sec=self._data.test_run.measured_sec,
        )

        # Run execution
        logger.info(f"Starting test execution: phase={phase}, loadprofile={loadprofile}")
        result = await executor.execute_scenario(config, workflow_states)

        if result.success:
            logger.info(f"Test execution completed: {phase}/{loadprofile}")
        else:
            logger.error(f"Test execution failed: {result.error_message}")

        return result

    async def run_full_test(
        self,
        phases: Optional[list[str]] = None,
        loadprofiles: Optional[list[str]] = None,
        run_calibration: bool = False,
    ) -> E2ETestResult:
        """
        Run complete E2E test across all phases and load profiles.

        Args:
            phases: Phases to run (default: base, initial, upgrade)
            loadprofiles: Load profiles to run (default: low, medium, high)
            run_calibration: Whether to run calibration first

        Returns:
            E2ETestResult with all results
        """
        if phases is None:
            phases = ["base", "initial", "upgrade"]
        if loadprofiles is None:
            loadprofiles = ["low", "medium", "high"]

        result = E2ETestResult(success=True)

        try:
            # Setup environment
            self.setup_environment()

            # Run calibration if requested
            if run_calibration:
                calibration_result = await self.run_calibration(skip_if_calibrated=False)
                result.calibration_result = calibration_result
                if calibration_result and not calibration_result.success:
                    result.success = False
                    result.error_message = f"Calibration failed: {calibration_result.error_message}"
                    return result

            # Run test execution for each phase/loadprofile combination
            for phase in phases:
                for loadprofile in loadprofiles:
                    key = f"{phase}_{loadprofile}"
                    execution_result = await self.run_test_execution(phase, loadprofile)
                    result.execution_results[key] = execution_result

                    if not execution_result.success:
                        result.success = False
                        result.error_message = (
                            f"Execution failed for {phase}/{loadprofile}: "
                            f"{execution_result.error_message}"
                        )
                        # Continue running other combinations or stop?
                        # For now, continue to collect all results

        except Exception as e:
            logger.exception("E2E test failed with exception")
            result.success = False
            result.error_message = str(e)

        return result


async def run_docker_e2e_test(
    db_session: AsyncSession,
    phases: Optional[list[str]] = None,
    loadprofiles: Optional[list[str]] = None,
) -> E2ETestResult:
    """
    Convenience function to run complete Docker E2E test.

    Seeds data, configures environment, runs tests.
    """
    # Seed test data
    docker_config = DockerE2EConfig()
    seeder = E2ETestDataSeeder(db_session, docker_config)
    seeded_data = await seeder.seed_all()

    # Create runner
    runner = E2ETestRunner(db_session, seeded_data, docker_config)

    # Run full test
    result = await runner.run_full_test(
        phases=phases,
        loadprofiles=loadprofiles,
        run_calibration=False,  # Use pre-seeded calibration
    )

    return result
