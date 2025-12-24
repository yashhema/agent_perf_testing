"""Full orchestration E2E tests.

Tests the complete execution flow:
1. Create workflow state with package lists
2. Simulate snapshot restore (Docker container restart)
3. Install agent package
4. Verify agent installation
5. Start emulator and agent load
6. Run JMeter load test
7. Collect results
8. Verify results stored in DB

Usage:
    docker-compose -f tests/e2e/docker/docker-compose.yml up -d
    pytest tests/e2e/docker/test_full_orchestration.py --e2e-docker -v
    docker-compose -f tests/e2e/docker/docker-compose.yml down
"""

import asyncio
import pytest
import httpx
from datetime import datetime
from uuid import uuid4

from app.models.enums import (
    LoadProfile,
    WorkflowState,
    PhaseState,
    ExecutionStatus,
)
from app.models.orm import (
    ExecutionWorkflowStateORM,
    TestRunExecutionORM,
)
from app.results.compression import decompress_dict
from tests.e2e.data import SeededData


@pytest.mark.e2e_docker
class TestAgentInstallation:
    """Tests for agent installation flow."""

    @pytest.mark.asyncio
    async def test_agent_install_verify(self, agent_1_url: str):
        """Test agent installation and verification."""
        async with httpx.AsyncClient() as client:
            # Install agent
            response = await client.post(
                f"{agent_1_url}/install",
                json={
                    "version": "6.50.14358",
                    "agent_id": 101,
                    "agent_name": "TestSecurityAgent",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["version"] == "6.50.14358"

            # Verify installation
            response = await client.get(f"{agent_1_url}/verify")
            assert response.status_code == 200
            verify = response.json()
            assert verify["is_installed"] is True
            assert verify["version"] == "6.50.14358"

            # Cleanup
            await client.post(f"{agent_1_url}/uninstall")

    @pytest.mark.asyncio
    async def test_agent_load_simulation(self, agent_1_url: str):
        """Test agent load simulation during test."""
        async with httpx.AsyncClient() as client:
            # Install agent
            await client.post(
                f"{agent_1_url}/install",
                json={"version": "1.0.0", "agent_id": 1, "agent_name": "TestAgent"},
            )

            # Start agent load
            response = await client.post(
                f"{agent_1_url}/start",
                json={
                    "thread_count": 4,
                    "cpu_target_percent": 30.0,
                    "duration_sec": 3,
                },
            )
            assert response.status_code == 200
            assert response.json()["status"] == "started"

            # Wait for some iterations
            await asyncio.sleep(2)

            # Get metrics
            response = await client.get(f"{agent_1_url}/metrics")
            assert response.status_code == 200
            metrics = response.json()
            assert metrics["total_iterations"] > 0

            # Stop and cleanup
            await client.post(f"{agent_1_url}/stop")
            await client.post(f"{agent_1_url}/uninstall")


@pytest.mark.e2e_docker
class TestSnapshotSimulation:
    """Tests for snapshot restore simulation."""

    @pytest.mark.asyncio
    async def test_container_reset_simulates_snapshot(
        self,
        agent_1_url: str,
        emulator_1_url: str,
    ):
        """Test that container reset simulates snapshot restore.

        In Docker E2E, we simulate snapshot restore by:
        1. Calling /reset on emulator (clears load state)
        2. Calling /reset on agent (clears state but preserves install)

        For full snapshot simulation, we could restart the container,
        but /reset is faster and sufficient for E2E testing.
        """
        async with httpx.AsyncClient() as client:
            # Install agent
            await client.post(
                f"{agent_1_url}/install",
                json={"version": "1.0.0", "agent_id": 1, "agent_name": "TestAgent"},
            )

            # Start some load
            await client.post(
                f"{emulator_1_url}/start",
                json={"thread_count": 4, "duration_sec": 2},
            )
            await client.post(
                f"{agent_1_url}/start",
                json={"thread_count": 2, "cpu_target_percent": 20.0, "duration_sec": 2},
            )

            await asyncio.sleep(1)

            # "Restore snapshot" by resetting both
            await client.post(f"{emulator_1_url}/reset")
            await client.post(f"{agent_1_url}/reset")

            # Verify state is cleared
            emulator_status = await client.get(f"{emulator_1_url}/status")
            assert emulator_status.json()["is_running"] is False

            agent_status = await client.get(f"{agent_1_url}/status")
            assert agent_status.json()["is_running"] is False

            # Agent should still be installed (simulating baseline with agent)
            verify = await client.get(f"{agent_1_url}/verify")
            assert verify.json()["is_installed"] is True

            # Cleanup
            await client.post(f"{agent_1_url}/uninstall")


@pytest.mark.e2e_docker
class TestFullPhaseExecution:
    """Tests for complete phase execution flow."""

    @pytest.mark.asyncio
    async def test_base_phase_execution(
        self,
        db_session,
        seeded_data: SeededData,
        emulator_1_url: str,
        agent_1_url: str,
        loadgen_url: str,
    ):
        """Test complete base phase execution.

        Flow:
        1. Create execution and workflow state
        2. Set package list
        3. Restore baseline (reset containers)
        4. Install packages (agent)
        5. Verify packages
        6. Start emulator + agent load
        7. Run load test
        8. Collect results
        9. Store in workflow state
        """
        from urllib.parse import urlparse

        # Parse URLs
        emulator_parsed = urlparse(emulator_1_url)
        loadgen_parsed = urlparse(loadgen_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # ================================================================
            # Step 1: Create execution and workflow state
            # ================================================================
            execution = TestRunExecutionORM(
                test_run_id=seeded_data.test_run.id,
                run_mode="continuous",
                status=ExecutionStatus.RUNNING.value,
                started_at=datetime.utcnow(),
            )
            db_session.add(execution)
            await db_session.flush()

            workflow_state = ExecutionWorkflowStateORM(
                test_run_execution_id=execution.id,
                target_id=seeded_data.target_servers[0].id,
                loadprofile=LoadProfile.LOW.value,
                runcount=0,
                cur_state=WorkflowState.SCHEDULED.value,
                current_phase="base",
                phase_state=PhaseState.NOT_STARTED.value,
                base_baseline_id=seeded_data.baseline.id,
                retry_count=0,
                max_retries=3,
                error_history=[],
            )
            db_session.add(workflow_state)
            await db_session.flush()

            # ================================================================
            # Step 2: Set package list
            # ================================================================
            package_list = [
                {
                    "package_id": 1001,
                    "package_name": "TestSecurityAgent",
                    "package_version": "6.50.14358",
                    "package_type": "agent",
                    "is_measured": True,
                    "agent_id": 101,
                    "agent_name": "TestAgent",
                },
            ]
            workflow_state.base_package_lst = package_list
            await db_session.flush()

            # ================================================================
            # Step 3: Restore baseline (reset containers)
            # ================================================================
            workflow_state.phase_state = PhaseState.RESTORING_BASELINE.value
            await db_session.flush()

            await client.post(f"{emulator_1_url}/reset")
            await client.post(f"{agent_1_url}/reset")

            # ================================================================
            # Step 4: Install packages
            # ================================================================
            workflow_state.phase_state = PhaseState.INSTALLING_AGENT.value
            await db_session.flush()

            response = await client.post(
                f"{agent_1_url}/install",
                json={
                    "version": "6.50.14358",
                    "agent_id": 101,
                    "agent_name": "TestSecurityAgent",
                },
            )
            install_result = response.json()
            assert install_result["success"] is True

            # ================================================================
            # Step 5: Verify packages
            # ================================================================
            response = await client.get(f"{agent_1_url}/verify")
            verify_result = response.json()

            measured_list = [
                {
                    "package_id": 1001,
                    "package_name": "TestSecurityAgent",
                    "expected_version": "6.50.14358",
                    "measured_version": verify_result["version"],
                    "version_matched": verify_result["version"] == "6.50.14358",
                    "install_status": "success",
                    "verify_status": "matched",
                },
            ]
            workflow_state.base_package_lst_measured = measured_list
            workflow_state.base_packages_matched = True
            workflow_state.phase_state = PhaseState.AGENT_INSTALLED.value
            await db_session.flush()

            # ================================================================
            # Step 6: Start emulator + agent load
            # ================================================================
            workflow_state.phase_state = PhaseState.STARTING_EMULATOR.value
            await db_session.flush()

            # Start CPU emulator on target
            await client.post(
                f"{emulator_1_url}/start",
                json={"thread_count": 4, "duration_sec": 10},
            )

            # Start agent load simulation
            await client.post(
                f"{agent_1_url}/start",
                json={"thread_count": 2, "cpu_target_percent": 20.0, "duration_sec": 10},
            )

            # ================================================================
            # Step 7: Run load test
            # ================================================================
            workflow_state.phase_state = PhaseState.RUNNING_LOAD.value
            await db_session.flush()

            # Start load test against emulator
            await client.post(
                f"{loadgen_url}/start",
                json={
                    "target_host": emulator_parsed.hostname,
                    "target_port": emulator_parsed.port,
                    "jmeter_port": 4445,
                    "thread_count": 2,
                    "duration_sec": 5,
                    "warmup_sec": 1,
                },
            )

            # Wait for load test to complete
            await asyncio.sleep(7)

            # Get load test results
            response = await client.get(f"{loadgen_url}/result/4445")
            load_result = response.json()

            # ================================================================
            # Step 8: Collect results
            # ================================================================
            workflow_state.phase_state = PhaseState.COLLECTING_RESULTS.value
            await db_session.flush()

            # Get emulator calibration data
            emulator_response = await client.get(f"{emulator_1_url}/calibration")
            emulator_data = emulator_response.json()

            # Get agent metrics
            agent_response = await client.get(f"{agent_1_url}/metrics")
            agent_data = agent_response.json()

            # Stop emulator and agent
            await client.post(f"{emulator_1_url}/stop")
            await client.post(f"{agent_1_url}/stop")

            # Build result data
            from app.results.compression import compress_dict

            result_data = {
                "phase": "base",
                "loadprofile": "low",
                "collected_at": datetime.utcnow().isoformat(),
                "pkg_1001": {
                    "package_id": 1001,
                    "package_name": "TestSecurityAgent",
                    "success": True,
                    "tests_total": 1,
                    "tests_passed": 1,
                },
            }

            stats_data = {
                "phase": "base",
                "loadprofile": "low",
                "emulator": {
                    "thread_count": emulator_data["thread_count"],
                    "cpu_percent": emulator_data["cpu_percent"],
                    "avg_iteration_time_ms": emulator_data["avg_iteration_time_ms"],
                },
                "agent": {
                    "total_iterations": agent_data["total_iterations"],
                    "avg_iteration_time_ms": agent_data["avg_iteration_time_ms"],
                },
            }

            jmeter_result = {
                "phase": "base",
                "loadprofile": "low",
                "jmeter": {
                    "success": True,
                    "total_requests": load_result["total_requests"],
                    "successful_requests": load_result["successful_requests"],
                    "failed_requests": load_result["failed_requests"],
                    "avg_response_time_ms": load_result["avg_response_time_ms"],
                    "throughput_rps": load_result["throughput_per_sec"],
                },
            }

            # ================================================================
            # Step 9: Store in workflow state
            # ================================================================
            workflow_state.base_device_result_blob = compress_dict(result_data)
            workflow_state.base_device_stats_blob = compress_dict(stats_data)
            workflow_state.jmeter_device_result_blob = compress_dict(jmeter_result)
            workflow_state.phase_state = PhaseState.COMPLETED.value
            workflow_state.cur_state = WorkflowState.PHASE_COMPLETE.value
            await db_session.flush()

            # ================================================================
            # Verify results
            # ================================================================
            # Reload workflow state
            await db_session.refresh(workflow_state)

            # Verify package list stored
            assert workflow_state.base_package_lst is not None
            assert len(workflow_state.base_package_lst) == 1

            # Verify measured list stored
            assert workflow_state.base_package_lst_measured is not None
            assert workflow_state.base_packages_matched is True

            # Verify result blobs stored
            assert workflow_state.base_device_result_blob is not None
            assert workflow_state.base_device_stats_blob is not None
            assert workflow_state.jmeter_device_result_blob is not None

            # Decompress and verify
            result = decompress_dict(workflow_state.base_device_result_blob)
            assert result["phase"] == "base"
            assert "pkg_1001" in result

            stats = decompress_dict(workflow_state.base_device_stats_blob)
            assert "emulator" in stats
            assert "agent" in stats

            jmeter = decompress_dict(workflow_state.jmeter_device_result_blob)
            assert jmeter["jmeter"]["total_requests"] > 0

            # Verify phase completed
            assert workflow_state.phase_state == PhaseState.COMPLETED.value

            # Cleanup
            await client.delete(f"{loadgen_url}/test/4445")
            await client.post(f"{agent_1_url}/uninstall")

            await db_session.commit()


@pytest.mark.e2e_docker
class TestMultiTargetExecution:
    """Tests for execution across multiple targets."""

    @pytest.mark.asyncio
    async def test_parallel_target_execution(
        self,
        emulator_1_url: str,
        emulator_2_url: str,
        agent_1_url: str,
        agent_2_url: str,
    ):
        """Test parallel execution across multiple targets."""
        async with httpx.AsyncClient() as client:
            # Install agents on both targets in parallel
            results = await asyncio.gather(
                client.post(
                    f"{agent_1_url}/install",
                    json={"version": "1.0.0", "agent_id": 1, "agent_name": "Agent1"},
                ),
                client.post(
                    f"{agent_2_url}/install",
                    json={"version": "1.0.0", "agent_id": 2, "agent_name": "Agent2"},
                ),
            )

            for r in results:
                assert r.status_code == 200
                assert r.json()["success"] is True

            # Start load on both targets in parallel
            await asyncio.gather(
                client.post(
                    f"{emulator_1_url}/start",
                    json={"thread_count": 4, "duration_sec": 3},
                ),
                client.post(
                    f"{emulator_2_url}/start",
                    json={"thread_count": 4, "duration_sec": 3},
                ),
                client.post(
                    f"{agent_1_url}/start",
                    json={"thread_count": 2, "cpu_target_percent": 20.0, "duration_sec": 3},
                ),
                client.post(
                    f"{agent_2_url}/start",
                    json={"thread_count": 2, "cpu_target_percent": 20.0, "duration_sec": 3},
                ),
            )

            # Wait for completion
            await asyncio.sleep(4)

            # Verify both completed
            status_1 = await client.get(f"{emulator_1_url}/status")
            status_2 = await client.get(f"{emulator_2_url}/status")

            # Both should have completed (not running, but have iteration data)
            assert status_1.json()["iteration_count"] > 0
            assert status_2.json()["iteration_count"] > 0

            # Cleanup
            await asyncio.gather(
                client.post(f"{emulator_1_url}/reset"),
                client.post(f"{emulator_2_url}/reset"),
                client.post(f"{agent_1_url}/uninstall"),
                client.post(f"{agent_2_url}/uninstall"),
            )
