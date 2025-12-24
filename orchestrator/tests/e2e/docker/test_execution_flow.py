"""E2E tests using ACTUAL production code with Docker containers.

These tests use the real production services:
- ExecutionService (app/services/execution_service.py)
- WorkflowStateService (app/services/workflow_state_service.py)
- PhaseOrchestrator (app/orchestration/phase_orchestrator.py)
- EmulatorClient (app/calibration/emulator_client.py)
- JMeterService (app/jmeter/service.py)

Docker containers expose the same interfaces as production:
- Emulator: HTTP API for test control
- SSH: For package installation and JMeter execution
- Reset endpoint: For baseline restoration

Usage:
    docker-compose -f tests/e2e/docker/docker-compose.yml up -d
    pytest tests/e2e/docker/test_execution_flow.py --e2e-docker -v
    docker-compose -f tests/e2e/docker/docker-compose.yml down
"""

import pytest
from decimal import Decimal

from app.models.enums import (
    RunMode,
    ExecutionStatus,
    LoadProfile,
)
from app.services.execution_service import ExecutionService
from app.repositories.execution_repository import (
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
)
from app.repositories.test_run_repository import (
    TestRunRepository,
    TestRunTargetRepository,
)
from app.calibration.emulator_client import EmulatorClient, TestConfig
from tests.e2e.data import SeededData
from tests.e2e.docker.docker_adapters import DockerE2EFactory


@pytest.mark.e2e_docker
class TestExecutionServiceE2E:
    """E2E tests for ExecutionService using real code."""

    @pytest.mark.asyncio
    async def test_create_execution_from_test_run(
        self,
        db_session,
        seeded_data: SeededData,
    ):
        """Test creating execution using real ExecutionService."""
        exec_repo = TestRunExecutionRepository(db_session)
        workflow_repo = ExecutionWorkflowStateRepository(db_session)
        test_run_repo = TestRunRepository(db_session)
        target_repo = TestRunTargetRepository(db_session)

        execution_service = ExecutionService(
            execution_repository=exec_repo,
            workflow_state_repository=workflow_repo,
            test_run_repository=test_run_repo,
            test_run_target_repository=target_repo,
        )

        result = await execution_service.create_execution(
            test_run_id=seeded_data.test_run.id,
            run_mode=RunMode.CONTINUOUS,
            immediate_run=True,
        )

        assert result.success is True
        assert result.execution_id is not None
        assert result.calibration_started is True

        execution = await execution_service.get_execution(result.execution_id)
        assert execution is not None
        assert execution.test_run_id == seeded_data.test_run.id

        states = await execution_service.get_workflow_states(result.execution_id)
        # Should have 2 targets x 3 load profiles = 6 states
        assert len(states) == 6

        await db_session.commit()

    @pytest.mark.asyncio
    async def test_execution_action_continue(
        self,
        db_session,
        seeded_data: SeededData,
    ):
        """Test execution actions using real ExecutionService."""
        exec_repo = TestRunExecutionRepository(db_session)
        workflow_repo = ExecutionWorkflowStateRepository(db_session)
        test_run_repo = TestRunRepository(db_session)
        target_repo = TestRunTargetRepository(db_session)

        execution_service = ExecutionService(
            execution_repository=exec_repo,
            workflow_state_repository=workflow_repo,
            test_run_repository=test_run_repo,
            test_run_target_repository=target_repo,
        )

        result = await execution_service.create_execution(
            test_run_id=seeded_data.test_run.id,
            run_mode=RunMode.CONTINUOUS,
            immediate_run=True,
        )

        action_result = await execution_service.execute_action(
            execution_id=result.execution_id,
            action="continue",
        )

        assert action_result.success is True
        assert action_result.new_status == ExecutionStatus.RUNNING

        await db_session.commit()


@pytest.mark.e2e_docker
class TestEmulatorClient:
    """E2E tests for EmulatorClient using production HTTP client."""

    @pytest.mark.asyncio
    async def test_health_check(self, emulator_1_url: str):
        """Test emulator health check using production EmulatorClient."""
        # Parse URL to get host/port
        from urllib.parse import urlparse
        parsed = urlparse(emulator_1_url)

        client = EmulatorClient(
            host=parsed.hostname,
            port=parsed.port,
        )

        is_healthy = await client.health_check()
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_start_stop_test(self, emulator_1_url: str):
        """Test starting and stopping load test via production EmulatorClient."""
        from urllib.parse import urlparse
        parsed = urlparse(emulator_1_url)

        client = EmulatorClient(
            host=parsed.hostname,
            port=parsed.port,
        )

        # Start test
        config = TestConfig(
            thread_count=2,
            duration_sec=10,
            cpu_duration_ms=50,
            cpu_intensity=0.5,
        )

        test_id = await client.start_test(config)
        assert test_id is not None
        assert len(test_id) > 0

        # Check status
        status = await client.get_test_status(test_id)
        assert status.get("status") in ("running", "pending")

        # Stop test
        stopped = await client.stop_test(test_id)
        assert stopped is True

    @pytest.mark.asyncio
    async def test_get_system_stats(self, emulator_1_url: str):
        """Test getting system stats via production EmulatorClient."""
        from urllib.parse import urlparse
        parsed = urlparse(emulator_1_url)

        client = EmulatorClient(
            host=parsed.hostname,
            port=parsed.port,
        )

        stats = await client.get_system_stats()
        assert stats.cpu_percent >= 0
        assert stats.memory_percent >= 0


@pytest.mark.e2e_docker
class TestHTTPEmulatorManager:
    """E2E tests for HTTPEmulatorManager (production implementation)."""

    @pytest.mark.asyncio
    async def test_start_stop_emulator(
        self,
        seeded_data: SeededData,
        docker_factory: DockerE2EFactory,
    ):
        """Test emulator control via production HTTPEmulatorManager."""
        target_id = seeded_data.target_servers[0].id

        # Get production manager from factory
        emulator_manager = docker_factory.create_emulator_manager()

        # Start emulator
        success, error = await emulator_manager.start_emulator(
            target_id=1,  # Use container ID from factory config
            thread_count=2,
            target_cpu_percent=30.0,
        )

        assert success is True, f"Start failed: {error}"
        assert error is None

        # Get stats
        stats = await emulator_manager.get_emulator_stats(target_id=1)
        assert stats is not None
        assert "cpu_percent" in stats

        # Stop emulator
        stopped = await emulator_manager.stop_emulator(target_id=1)
        assert stopped is True


@pytest.mark.e2e_docker
class TestDockerSnapshotManager:
    """E2E tests for snapshot restoration via Docker containers."""

    @pytest.mark.asyncio
    async def test_restore_and_wait(
        self,
        seeded_data: SeededData,
        docker_factory: DockerE2EFactory,
    ):
        """Test snapshot restore using DockerSnapshotManager."""
        snapshot_manager = docker_factory.create_snapshot_manager()

        # Restore (calls /reset on container)
        success, error = await snapshot_manager.restore_snapshot(
            target_id=1,
            baseline_id=seeded_data.baseline.id,
        )

        assert success is True, f"Restore failed: {error}"

        # Wait for ready
        ready = await snapshot_manager.wait_for_target_ready(
            target_id=1,
            timeout_sec=30,
        )
        assert ready is True


@pytest.mark.e2e_docker
class TestSeededDataValidation:
    """Verify seeded data contains real values."""

    @pytest.mark.asyncio
    async def test_baseline_has_os_info(self, seeded_data: SeededData):
        """Verify baseline has real OS information."""
        assert seeded_data.baseline.os_vendor_family == "rhel"
        assert seeded_data.baseline.os_major_ver == "8"
        assert seeded_data.baseline.os_minor_ver == "4"
        assert seeded_data.baseline.os_kernel_ver == "4.18.0-305"

    @pytest.mark.asyncio
    async def test_servers_have_os_info(self, seeded_data: SeededData):
        """Verify servers have real OS information."""
        for server in seeded_data.target_servers:
            assert server.os_vendor == "rhel"
            assert server.os_major == 8
            assert server.os_minor == 4

    @pytest.mark.asyncio
    async def test_packages_have_delivery_config(self, seeded_data: SeededData):
        """Verify packages have real delivery_config."""
        assert seeded_data.agent_package.delivery_config is not None
        assert seeded_data.agent_package.delivery_config["type"] == "SCRIPT"
        assert "install_script" in seeded_data.agent_package.delivery_config

    @pytest.mark.asyncio
    async def test_packages_have_version_check(self, seeded_data: SeededData):
        """Verify packages have version_check_command."""
        assert seeded_data.agent_package.version_check_command is not None
        assert "rpm" in seeded_data.agent_package.version_check_command

    @pytest.mark.asyncio
    async def test_package_members_have_os_regex(self, seeded_data: SeededData):
        """Verify package group members have os_match_regex."""
        rhel_members = [
            m for m in seeded_data.package_group_members
            if "rhel" in m.os_match_regex
        ]
        assert len(rhel_members) > 0

    @pytest.mark.asyncio
    async def test_calibration_has_real_values(self, seeded_data: SeededData):
        """Verify calibration results have realistic values."""
        low_cal = next(
            (c for c in seeded_data.calibration_results
             if c.loadprofile == LoadProfile.LOW.value),
            None,
        )
        assert low_cal is not None
        assert low_cal.thread_count == 4
        assert low_cal.cpu_target_percent == Decimal("30.00")

        medium_cal = next(
            (c for c in seeded_data.calibration_results
             if c.loadprofile == LoadProfile.MEDIUM.value),
            None,
        )
        assert medium_cal is not None
        assert medium_cal.thread_count == 8
        assert medium_cal.cpu_target_percent == Decimal("50.00")

        high_cal = next(
            (c for c in seeded_data.calibration_results
             if c.loadprofile == LoadProfile.HIGH.value),
            None,
        )
        assert high_cal is not None
        assert high_cal.thread_count == 12
        assert high_cal.cpu_target_percent == Decimal("70.00")

    @pytest.mark.asyncio
    async def test_test_run_targets_have_jmx(self, seeded_data: SeededData):
        """Verify test run targets have JMX file path."""
        for target in seeded_data.test_run_targets:
            assert target.jmx_file_path is not None
            assert target.jmx_file_path.endswith(".jmx")

    @pytest.mark.asyncio
    async def test_lab_has_jmeter_package_grp(self, seeded_data: SeededData):
        """Verify lab has jmeter_package_grpid set."""
        assert seeded_data.lab.jmeter_package_grpid is not None
        assert seeded_data.lab.jmeter_package_grpid == seeded_data.jmeter_package_group.id


@pytest.mark.e2e_docker
class TestJMXTemplateManager:
    """E2E tests for JMX template generation using production code."""

    @pytest.mark.asyncio
    async def test_generate_test_plan_produces_valid_xml(self):
        """Test that JMXTemplateManager generates valid XML."""
        from app.jmeter.template import JMXTemplateManager, JMXTestPlanConfig, HTTPSamplerConfig
        import xml.etree.ElementTree as ET

        manager = JMXTemplateManager()
        config = JMXTestPlanConfig(
            name="Test Plan",
            target_host="emulator",
            target_port=8080,
            thread_count=4,
            duration_sec=60,
            warmup_sec=10,
            samplers=[
                HTTPSamplerConfig(name="Health", path="/health"),
                HTTPSamplerConfig(name="Status", path="/status"),
            ],
        )

        jmx_content = manager.generate_test_plan(config)

        root = ET.fromstring(jmx_content)
        assert root.tag == "jmeterTestPlan"
        assert root.get("version") == "1.2"

    @pytest.mark.asyncio
    async def test_generate_test_plan_contains_thread_groups(self):
        """Test that generated JMX contains thread groups."""
        from app.jmeter.template import JMXTemplateManager, JMXTestPlanConfig
        import xml.etree.ElementTree as ET

        manager = JMXTemplateManager()
        config = JMXTestPlanConfig(
            target_host="localhost",
            target_port=8080,
            include_warmup_group=True,
        )

        jmx_content = manager.generate_test_plan(config)
        root = ET.fromstring(jmx_content)

        thread_groups = root.findall(".//ThreadGroup")
        assert len(thread_groups) >= 2

        names = [tg.get("testname") for tg in thread_groups]
        assert "Warmup Thread Group" in names
        assert "Main Test Thread Group" in names

    @pytest.mark.asyncio
    async def test_create_default_test_plan_function(self):
        """Test the create_default_test_plan convenience function."""
        from app.jmeter.template import create_default_test_plan
        import xml.etree.ElementTree as ET

        jmx_content = create_default_test_plan(
            target_host="perf-target",
            target_port=3000,
            thread_count=10,
            duration_sec=600,
            warmup_sec=60,
        )

        root = ET.fromstring(jmx_content)
        assert root.tag == "jmeterTestPlan"

        assert "/health" in jmx_content
        assert "/status" in jmx_content
        assert "/calibration" in jmx_content
