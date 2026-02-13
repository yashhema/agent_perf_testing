"""Integration tests for ScenarioExecutor with Docker test data.

Tests:
- Multi-target orchestration
- LoadGenerator deduplication
- Phase-based execution
- Delta deployment logic in executor
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.executor import (
    ScenarioExecutor,
    ScenarioExecutionRequest,
    ScenarioExecutionResult,
    TargetExecutionInfo,
    TestPhase,
)
from app.execution.models import ExecutionStatus
from tests.integration.fixtures import create_docker_test_data, DockerTestData


@pytest_asyncio.fixture
async def test_data(session: AsyncSession) -> DockerTestData:
    """Create Docker test data."""
    return await create_docker_test_data(session)


class TestScenarioExecutor:
    """Tests for ScenarioExecutor with Docker targets."""

    @pytest.mark.asyncio
    async def test_execute_scenario_all_phases(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test executing all phases for a scenario."""
        # Create target execution info for both targets
        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                initial_baseline_id=test_data.rhel84_baseline.id,
                upgrade_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
            TargetExecutionInfo(
                target_id=test_data.test_run_target2.id,
                server_id=test_data.target2.id,
                loadgenerator_id=test_data.loadgen2.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                initial_baseline_id=test_data.rhel84_baseline.id,
                upgrade_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target2.ip_address,
                emulator_port=test_data.target2.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE, TestPhase.INITIAL, TestPhase.UPGRADE],
            load_profile="medium",
        )

        executor = ScenarioExecutor(request)
        result = await executor.execute()

        # Verify result
        assert result.scenario_id == test_data.scenario.id
        assert result.test_run_id == test_data.test_run.id
        assert result.status == ExecutionStatus.COMPLETED
        assert result.completed_at is not None
        assert len(result.errors) == 0

        # Verify both targets have results for all phases
        assert len(result.target_results) == 2

        for target_id in [test_data.test_run_target1.id, test_data.test_run_target2.id]:
            assert target_id in result.target_results
            target_phases = result.target_results[target_id]
            assert "base" in target_phases
            assert "initial" in target_phases
            assert "upgrade" in target_phases

    @pytest.mark.asyncio
    async def test_execute_scenario_base_initial_only(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test executing only base and initial phases."""
        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                initial_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE, TestPhase.INITIAL],  # No upgrade
            load_profile="low",
        )

        executor = ScenarioExecutor(request)
        result = await executor.execute()

        assert result.status == ExecutionStatus.COMPLETED

        # Verify only base and initial phases
        target_phases = result.target_results[test_data.test_run_target1.id]
        assert "base" in target_phases
        assert "initial" in target_phases
        assert "upgrade" not in target_phases


class TestLoadGeneratorDeduplication:
    """Tests for LoadGenerator deduplication in ScenarioExecutor."""

    @pytest.mark.asyncio
    async def test_unique_loadgens_deployed(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that unique load generators are tracked for deployment."""
        # Two targets with different load generators
        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,  # LoadGen 1
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
            TargetExecutionInfo(
                target_id=test_data.test_run_target2.id,
                server_id=test_data.target2.id,
                loadgenerator_id=test_data.loadgen2.id,  # LoadGen 2 (different)
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target2.ip_address,
                emulator_port=test_data.target2.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE],
            load_profile="low",
        )

        executor = ScenarioExecutor(request)
        await executor.execute()

        # Both load generators should be deployed
        assert test_data.loadgen1.id in executor._deployed_loadgens
        assert test_data.loadgen2.id in executor._deployed_loadgens

    @pytest.mark.asyncio
    async def test_same_loadgen_deployed_once(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that same load generator is only deployed once."""
        # Two targets with SAME load generator
        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,  # Same loadgen
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
            TargetExecutionInfo(
                target_id=test_data.test_run_target2.id,
                server_id=test_data.target2.id,
                loadgenerator_id=test_data.loadgen1.id,  # Same loadgen
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target2.ip_address,
                emulator_port=test_data.target2.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE],
            load_profile="low",
        )

        executor = ScenarioExecutor(request)
        await executor.execute()

        # Only one loadgen should be tracked
        assert len(executor._deployed_loadgens) == 1
        assert test_data.loadgen1.id in executor._deployed_loadgens


class TestDeltaDeploymentInExecutor:
    """Tests for delta deployment logic in executor."""

    @pytest.mark.asyncio
    async def test_delta_when_baseline_same(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test delta deployment when baseline is the same across phases."""
        # All phases use same baseline -> delta deployment
        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                initial_baseline_id=test_data.rhel84_baseline.id,  # Same as base
                upgrade_baseline_id=test_data.rhel84_baseline.id,  # Same as initial
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE, TestPhase.INITIAL, TestPhase.UPGRADE],
            load_profile="medium",
        )

        executor = ScenarioExecutor(request)
        result = await executor.execute()

        assert result.status == ExecutionStatus.COMPLETED

        # All phases should complete (delta is handled internally)
        target_results = result.target_results[test_data.test_run_target1.id]
        assert target_results["base"].status == ExecutionStatus.COMPLETED
        assert target_results["initial"].status == ExecutionStatus.COMPLETED
        assert target_results["upgrade"].status == ExecutionStatus.COMPLETED


class TestParallelExecution:
    """Tests for parallel target execution."""

    @pytest.mark.asyncio
    async def test_targets_execute_in_parallel(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that multiple targets execute in parallel within a phase."""
        import time

        targets = [
            TargetExecutionInfo(
                target_id=test_data.test_run_target1.id,
                server_id=test_data.target1.id,
                loadgenerator_id=test_data.loadgen1.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target1.ip_address,
                emulator_port=test_data.target1.emulator_port,
            ),
            TargetExecutionInfo(
                target_id=test_data.test_run_target2.id,
                server_id=test_data.target2.id,
                loadgenerator_id=test_data.loadgen2.id,
                base_baseline_id=test_data.rhel84_baseline.id,
                emulator_host=test_data.target2.ip_address,
                emulator_port=test_data.target2.emulator_port,
            ),
        ]

        request = ScenarioExecutionRequest(
            scenario_id=test_data.scenario.id,
            lab_id=test_data.lab.id,
            test_run_id=test_data.test_run.id,
            targets=targets,
            phases=[TestPhase.BASE],
            load_profile="low",
        )

        executor = ScenarioExecutor(request)

        start = time.time()
        result = await executor.execute()
        elapsed = time.time() - start

        assert result.status == ExecutionStatus.COMPLETED

        # If parallel, should take ~2-3 seconds (simulated phase time)
        # If sequential, would take ~4-6 seconds
        # Allow some margin for overhead
        assert elapsed < 5.0, f"Execution took {elapsed}s, expected parallel execution"
