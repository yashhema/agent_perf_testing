"""E2E tests for ExecutionController with Docker containers.

Tests the complete orchestration flow:
1. Seed database with test data
2. Create test execution via ExecutionController
3. Run calibration (or skip using pre-seeded)
4. Execute test phases (base, initial, upgrade)
5. Verify workflow states and results

Usage:
    docker-compose -f tests/e2e/docker/docker-compose.yml up -d
    pytest tests/e2e/docker/test_execution_controller.py --e2e-docker -v
    docker-compose -f tests/e2e/docker/docker-compose.yml down
"""

import asyncio
import pytest
import httpx
from datetime import datetime
from decimal import Decimal

from app.models.enums import (
    LoadProfile,
    WorkflowState,
    PhaseState,
    ExecutionStatus,
    RunMode,
)
from app.orchestration import (
    EnvironmentConfig,
    EnvironmentType,
    ContainerConfig,
    set_environment_config,
)
from app.orchestration.execution_controller import ExecutionController
from tests.e2e.data import SeededData, E2ETestDataSeeder, DockerE2EConfig
from tests.e2e.docker.conftest import (
    EMULATOR_1_HOST,
    EMULATOR_1_PORT,
    EMULATOR_2_HOST,
    EMULATOR_2_PORT,
    LOADGEN_HOST,
    LOADGEN_PORT,
)


def build_environment_config(seeded_data: SeededData) -> EnvironmentConfig:
    """Build environment config from seeded data for Docker E2E."""
    containers = {}

    # Add target server containers
    for i, server in enumerate(seeded_data.target_servers):
        host = EMULATOR_1_HOST if i == 0 else EMULATOR_2_HOST
        port = EMULATOR_1_PORT if i == 0 else EMULATOR_2_PORT

        containers[server.id] = ContainerConfig(
            name=f"emulator-{i+1}",
            host=host,
            http_port=port,
            ssh_port=2222 + i,
            ssh_user="root",
            ssh_password="testpass",
        )

    # Add loadgen container
    for server in seeded_data.loadgen_servers:
        containers[server.id] = ContainerConfig(
            name="loadgen-1",
            host=LOADGEN_HOST,
            http_port=LOADGEN_PORT,
            ssh_port=2223,
            ssh_user="root",
            ssh_password="testpass",
        )

    return EnvironmentConfig(
        env_type=EnvironmentType.DOCKER_E2E,
        docker_host="localhost",
        containers=containers,
    )


@pytest.mark.e2e_docker
class TestExecutionControllerSetup:
    """Tests for ExecutionController setup and initialization."""

    @pytest.mark.asyncio
    async def test_controller_creation(self, e2e_session, seeded_data: SeededData):
        """Test creating ExecutionController with seeded data."""
        # Build environment config
        env_config = build_environment_config(seeded_data)

        # Create controller
        controller = ExecutionController(
            db_session=e2e_session,
            env_config=env_config,
        )

        assert controller is not None
        assert controller.state.value == "idle"
        assert controller.execution_id is None

    @pytest.mark.asyncio
    async def test_seeded_data_has_scenario_cases(self, seeded_data: SeededData):
        """Verify seeder creates ScenarioCaseORM for package resolution."""
        assert len(seeded_data.scenario_cases) > 0

        scenario_case = seeded_data.scenario_cases[0]
        assert scenario_case.agent_id is not None
        assert scenario_case.agent_id == seeded_data.agent.id
        assert scenario_case.initial_package_grp_id is not None
        assert scenario_case.initial_package_grp_id == seeded_data.agent_package_group.id

    @pytest.mark.asyncio
    async def test_scenario_has_load_generator_package(self, seeded_data: SeededData):
        """Verify scenario has load_generator_package_grp_id set."""
        assert seeded_data.scenario.load_generator_package_grp_id is not None
        assert seeded_data.scenario.load_generator_package_grp_id == seeded_data.emulator_package_group.id


@pytest.mark.e2e_docker
class TestPackageResolution:
    """Tests for package resolution with seeded data."""

    @pytest.mark.asyncio
    async def test_resolve_jmeter_packages(self, e2e_session, seeded_data: SeededData):
        """Test resolving JMeter packages for loadgen."""
        from app.packages.resolver import PackageResolver

        resolver = PackageResolver(e2e_session)

        packages = await resolver.resolve_jmeter_packages(
            lab_id=seeded_data.lab.id,
            loadgen_server_id=seeded_data.loadgen_servers[0].id,
        )

        assert len(packages) > 0
        assert packages[0]["package_name"] == "apache-jmeter"

    @pytest.mark.asyncio
    async def test_resolve_base_packages(self, e2e_session, seeded_data: SeededData):
        """Test resolving base phase packages (emulator)."""
        from app.packages.resolver import PackageResolver

        resolver = PackageResolver(e2e_session)

        packages = await resolver.resolve_base_packages(
            target_server_id=seeded_data.target_servers[0].id,
            scenario_id=seeded_data.scenario.id,
        )

        assert len(packages) > 0
        assert packages[0]["package_name"] == "cpu-emulator"

    @pytest.mark.asyncio
    async def test_resolve_initial_packages(self, e2e_session, seeded_data: SeededData):
        """Test resolving initial phase packages (agent)."""
        from app.packages.resolver import PackageResolver

        resolver = PackageResolver(e2e_session)

        packages = await resolver.resolve_initial_packages(
            target_server_id=seeded_data.target_servers[0].id,
            scenario_id=seeded_data.scenario.id,
        )

        assert len(packages) > 0
        assert packages[0]["package_name"] == "security-agent"

    @pytest.mark.asyncio
    async def test_resolve_all_for_target(self, e2e_session, seeded_data: SeededData):
        """Test resolving all packages for a target."""
        from app.packages.resolver import PackageResolver

        resolver = PackageResolver(e2e_session)

        all_packages = await resolver.resolve_all_for_target(
            lab_id=seeded_data.lab.id,
            scenario_id=seeded_data.scenario.id,
            target_server_id=seeded_data.target_servers[0].id,
            loadgen_server_id=seeded_data.loadgen_servers[0].id,
        )

        assert "jmeter_packages" in all_packages
        assert "base_packages" in all_packages
        assert "initial_packages" in all_packages
        assert "upgrade_packages" in all_packages

        assert len(all_packages["jmeter_packages"]) > 0
        assert len(all_packages["base_packages"]) > 0
        assert len(all_packages["initial_packages"]) > 0


@pytest.mark.e2e_docker
class TestContainerHealthChecks:
    """Verify Docker containers are healthy before running tests."""

    @pytest.mark.asyncio
    async def test_all_containers_healthy(
        self,
        emulator_1_url: str,
        emulator_2_url: str,
        loadgen_url: str,
    ):
        """Verify all Docker containers respond to health checks."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check emulator 1
            r1 = await client.get(f"{emulator_1_url}/health")
            assert r1.status_code == 200
            assert r1.json()["status"] == "healthy"

            # Check emulator 2
            r2 = await client.get(f"{emulator_2_url}/health")
            assert r2.status_code == 200
            assert r2.json()["status"] == "healthy"

            # Check loadgen
            r3 = await client.get(f"{loadgen_url}/health")
            assert r3.status_code == 200
            assert r3.json()["status"] == "healthy"


@pytest.mark.e2e_docker
class TestExecutionControllerFlow:
    """Integration tests for ExecutionController execution flow."""

    @pytest.mark.asyncio
    async def test_create_workflow_states(self, e2e_session, seeded_data: SeededData):
        """Test ExecutionController creates workflow states with packages."""
        from app.repositories.execution_repository import (
            TestRunExecutionRepository,
            ExecutionWorkflowStateRepository,
        )

        env_config = build_environment_config(seeded_data)
        controller = ExecutionController(
            db_session=e2e_session,
            env_config=env_config,
        )

        # Manually load test run and targets (simulating start_execution)
        controller._test_run = seeded_data.test_run
        controller._targets = seeded_data.test_run_targets

        # Create a test execution record
        from app.models.orm import TestRunExecutionORM
        execution = TestRunExecutionORM(
            test_run_id=seeded_data.test_run.id,
            run_mode=RunMode.CONTINUOUS.value,
            status=ExecutionStatus.RUNNING.value,
            started_at=datetime.utcnow(),
        )
        e2e_session.add(execution)
        await e2e_session.flush()

        controller._execution = execution

        # Create workflow states
        await controller._create_workflow_states()

        # Verify workflow states created
        assert len(controller._workflow_states) > 0

        # Get one workflow state and check packages
        key = list(controller._workflow_states.keys())[0]
        state = controller._workflow_states[key]

        assert state.jmeter_package_lst is not None
        assert state.base_package_lst is not None
        assert state.initial_package_lst is not None

        # Verify package content
        assert len(state.jmeter_package_lst) > 0
        assert state.jmeter_package_lst[0]["package_name"] == "apache-jmeter"

        assert len(state.base_package_lst) > 0
        assert state.base_package_lst[0]["package_name"] == "cpu-emulator"


@pytest.mark.e2e_docker
class TestCalibrationWithContainers:
    """Tests for calibration with real Docker containers."""

    @pytest.mark.asyncio
    async def test_calibration_results_preseeded(self, seeded_data: SeededData):
        """Verify calibration results are pre-seeded."""
        # Should have 6 results: 2 targets x 3 profiles
        assert len(seeded_data.calibration_results) == 6

        # Check LOW profile for first target
        target_id = seeded_data.target_servers[0].id
        low_cal = next(
            (c for c in seeded_data.calibration_results
             if c.target_id == target_id and c.loadprofile == LoadProfile.LOW.value),
            None
        )

        assert low_cal is not None
        assert low_cal.thread_count == 4
        assert low_cal.cpu_target_percent == Decimal("30.00")

    @pytest.mark.asyncio
    async def test_existing_calibration_check(
        self,
        e2e_session,
        seeded_data: SeededData,
    ):
        """Test ExecutionController can check for existing calibration."""
        env_config = build_environment_config(seeded_data)
        controller = ExecutionController(
            db_session=e2e_session,
            env_config=env_config,
        )

        # Set up controller state
        controller._test_run = seeded_data.test_run
        controller._targets = seeded_data.test_run_targets

        # Check existing calibration
        has_calibration = await controller._check_existing_calibration()

        assert has_calibration is True


@pytest.mark.e2e_docker
class TestEmulatorIntegration:
    """Tests for emulator integration during execution."""

    @pytest.mark.asyncio
    async def test_emulator_start_stop_cycle(
        self,
        emulator_1_url: str,
        emulator_2_url: str,
    ):
        """Test emulator start/stop cycle simulating test execution."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Reset both emulators (simulate baseline restore)
            await asyncio.gather(
                client.post(f"{emulator_1_url}/reset"),
                client.post(f"{emulator_2_url}/reset"),
            )

            # Start emulators with calibrated thread counts
            results = await asyncio.gather(
                client.post(
                    f"{emulator_1_url}/start",
                    json={"thread_count": 4, "duration_sec": 5},
                ),
                client.post(
                    f"{emulator_2_url}/start",
                    json={"thread_count": 4, "duration_sec": 5},
                ),
            )

            for r in results:
                assert r.status_code == 200
                assert r.json()["status"] == "started"

            # Simulate warmup
            await asyncio.sleep(2)

            # Check status
            status_results = await asyncio.gather(
                client.get(f"{emulator_1_url}/status"),
                client.get(f"{emulator_2_url}/status"),
            )

            for s in status_results:
                assert s.json()["is_running"] is True

            # Stop emulators
            await asyncio.gather(
                client.post(f"{emulator_1_url}/stop"),
                client.post(f"{emulator_2_url}/stop"),
            )

            # Get final calibration data
            cal_results = await asyncio.gather(
                client.get(f"{emulator_1_url}/calibration"),
                client.get(f"{emulator_2_url}/calibration"),
            )

            for cal in cal_results:
                data = cal.json()
                assert data["thread_count"] == 4
                assert data["sample_count"] > 0


@pytest.mark.e2e_docker
class TestLoadgenIntegration:
    """Tests for load generator integration."""

    @pytest.mark.asyncio
    async def test_loadgen_jmeter_cycle(
        self,
        loadgen_url: str,
        emulator_1_url: str,
    ):
        """Test load generator JMeter cycle."""
        from urllib.parse import urlparse

        parsed = urlparse(emulator_1_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Start emulator
            await client.post(
                f"{emulator_1_url}/start",
                json={"thread_count": 4, "duration_sec": 10},
            )

            # Start JMeter load test
            response = await client.post(
                f"{loadgen_url}/start",
                json={
                    "target_host": parsed.hostname,
                    "target_port": parsed.port,
                    "jmeter_port": 4445,
                    "thread_count": 2,
                    "duration_sec": 5,
                    "warmup_sec": 1,
                },
            )

            assert response.status_code == 200
            assert response.json()["status"] == "started"

            # Wait for test completion
            await asyncio.sleep(7)

            # Get results
            result = await client.get(f"{loadgen_url}/result/4445")
            data = result.json()

            assert data["total_requests"] > 0
            assert data["successful_requests"] > 0

            # Cleanup
            await client.delete(f"{loadgen_url}/test/4445")
            await client.post(f"{emulator_1_url}/stop")
            await client.post(f"{emulator_1_url}/reset")


@pytest.mark.e2e_docker
class TestE2ETestRunner:
    """Tests for E2ETestRunner integration."""

    @pytest.mark.asyncio
    async def test_runner_build_configs(
        self,
        e2e_session,
        seeded_data: SeededData,
    ):
        """Test E2ETestRunner builds configs correctly."""
        from tests.e2e.docker.e2e_runner import E2ETestRunner

        docker_config = DockerE2EConfig()
        runner = E2ETestRunner(
            db_session=e2e_session,
            seeded_data=seeded_data,
            docker_config=docker_config,
        )

        # Test calibration config building
        cal_configs = runner.build_calibration_configs()
        assert len(cal_configs) == 2  # 2 target servers

        for config in cal_configs:
            assert config.cpu_count == 4
            assert config.memory_gb == 8.0

        # Test target config building
        target_configs = runner.build_target_configs("base", "low")
        assert len(target_configs) == 2

        for config in target_configs:
            assert len(config.calibration) > 0
            assert "low" in config.calibration

    @pytest.mark.asyncio
    async def test_runner_setup_environment(
        self,
        e2e_session,
        seeded_data: SeededData,
    ):
        """Test E2ETestRunner sets up environment correctly."""
        from tests.e2e.docker.e2e_runner import E2ETestRunner

        docker_config = DockerE2EConfig()
        runner = E2ETestRunner(
            db_session=e2e_session,
            seeded_data=seeded_data,
            docker_config=docker_config,
        )

        env_config = runner.setup_environment()

        assert env_config.env_type == EnvironmentType.DOCKER_E2E
        assert env_config.is_docker is True
        assert len(env_config.containers) > 0
