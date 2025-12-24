"""Docker-based E2E tests.

These tests run against real Docker containers:
- 2 emulator containers (simulating target servers)
- 1 loadgen container (JMeter)
- PostgreSQL database with seeded test data

Usage:
    # Start Docker containers
    docker-compose -f tests/e2e/docker/docker-compose.yml up -d

    # Wait for containers to be healthy
    docker-compose -f tests/e2e/docker/docker-compose.yml ps

    # Run E2E tests
    pytest tests/e2e/docker/ --e2e-docker -v

    # Stop containers
    docker-compose -f tests/e2e/docker/docker-compose.yml down
"""

import pytest
import httpx

from app.models.enums import LoadProfile, CalibrationStatus
from app.orchestration import ScenarioOrchestrator, ScenarioConfig, ServerSetup
from tests.e2e.data import SeededData


@pytest.mark.e2e_docker
class TestDockerE2ESetup:
    """Tests for Docker E2E setup and health checks."""

    @pytest.mark.asyncio
    async def test_emulator_1_health(self, emulator_1_url: str):
        """Test emulator 1 container is healthy."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{emulator_1_url}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_emulator_2_health(self, emulator_2_url: str):
        """Test emulator 2 container is healthy."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{emulator_2_url}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_loadgen_health(self, loadgen_url: str):
        """Test load generator container is healthy."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{loadgen_url}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.e2e_docker
class TestDatabaseSeeding:
    """Tests for database seeding with E2E data."""

    @pytest.mark.asyncio
    async def test_seeded_lab_exists(self, seeded_data: SeededData):
        """Test lab was seeded correctly."""
        assert seeded_data.lab is not None
        assert seeded_data.lab.name == "docker-e2e-lab"
        assert seeded_data.lab.lab_type == "docker"

    @pytest.mark.asyncio
    async def test_seeded_servers_exist(self, seeded_data: SeededData):
        """Test servers were seeded correctly."""
        assert len(seeded_data.servers) == 3
        assert len(seeded_data.target_servers) == 2
        assert len(seeded_data.loadgen_servers) == 1

    @pytest.mark.asyncio
    async def test_seeded_scenario_exists(self, seeded_data: SeededData):
        """Test scenario was seeded correctly."""
        assert seeded_data.scenario is not None
        assert seeded_data.scenario.is_calibrated is True
        assert len(seeded_data.scenario.target_server_ids) == 2
        assert len(seeded_data.scenario.loadgen_server_ids) == 1

    @pytest.mark.asyncio
    async def test_seeded_calibration_results(self, seeded_data: SeededData):
        """Test calibration results were pre-seeded."""
        # Should have 6 calibration results: 2 targets x 3 profiles
        assert len(seeded_data.calibration_results) == 6

        # Verify all profiles are represented
        profiles = {cal.loadprofile for cal in seeded_data.calibration_results}
        assert LoadProfile.LOW.value in profiles
        assert LoadProfile.MEDIUM.value in profiles
        assert LoadProfile.HIGH.value in profiles

        # All should be completed
        for cal in seeded_data.calibration_results:
            assert cal.calibration_status == CalibrationStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_seeded_test_run_targets(self, seeded_data: SeededData):
        """Test test run targets were mapped correctly."""
        assert len(seeded_data.test_run_targets) == 2

        # Each target should be mapped to the loadgen
        loadgen_id = seeded_data.loadgen_servers[0].id
        for target in seeded_data.test_run_targets:
            assert target.loadgenerator_id == loadgen_id


@pytest.mark.e2e_docker
class TestEmulatorLoad:
    """Tests for emulator load generation."""

    @pytest.mark.asyncio
    async def test_emulator_start_stop(self, emulator_1_url: str):
        """Test starting and stopping emulator load."""
        async with httpx.AsyncClient() as client:
            # Start emulator with 4 threads
            response = await client.post(
                f"{emulator_1_url}/start",
                json={"thread_count": 4, "duration_sec": 5},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            assert data["thread_count"] == 4

            # Check status
            response = await client.get(f"{emulator_1_url}/status")
            assert response.status_code == 200
            status = response.json()
            assert status["is_running"] is True
            assert status["thread_count"] == 4

            # Wait for completion or stop early
            import asyncio
            await asyncio.sleep(1)

            response = await client.post(f"{emulator_1_url}/stop")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_emulator_calibration_data(self, emulator_1_url: str):
        """Test getting calibration data from emulator."""
        async with httpx.AsyncClient() as client:
            # Start emulator for a short calibration run
            await client.post(
                f"{emulator_1_url}/start",
                json={"thread_count": 8, "duration_sec": 2},
            )

            # Wait for some iterations
            import asyncio
            await asyncio.sleep(2)

            # Get calibration data
            response = await client.get(f"{emulator_1_url}/calibration")
            assert response.status_code == 200
            data = response.json()

            assert data["thread_count"] == 8
            assert data["cpu_percent"] > 0
            assert data["sample_count"] > 0

            # Reset for next test
            await client.post(f"{emulator_1_url}/reset")


@pytest.mark.e2e_docker
class TestLoadGenerator:
    """Tests for load generator functionality."""

    @pytest.mark.asyncio
    async def test_loadgen_start_stop(
        self,
        loadgen_url: str,
        emulator_1_url: str,
    ):
        """Test starting and stopping load test."""
        # Parse emulator host and port from URL
        from urllib.parse import urlparse
        parsed = urlparse(emulator_1_url)

        async with httpx.AsyncClient() as client:
            # Start load test
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
            data = response.json()
            assert data["status"] == "started"

            # Check status
            import asyncio
            await asyncio.sleep(1)

            response = await client.get(f"{loadgen_url}/status/4445")
            assert response.status_code == 200
            status = response.json()
            assert status["is_running"] is True

            # Stop and get result
            response = await client.post(f"{loadgen_url}/stop/4445")
            assert response.status_code == 200
            result = response.json()
            assert result["total_requests"] > 0

            # Cleanup
            await client.delete(f"{loadgen_url}/test/4445")


@pytest.mark.e2e_docker
class TestScenarioOrchestration:
    """Tests for scenario orchestration with Docker containers."""

    @pytest.mark.asyncio
    async def test_scenario_setup_with_containers(
        self,
        seeded_data: SeededData,
        emulator_1_url: str,
        emulator_2_url: str,
    ):
        """Test scenario setup with real emulator containers.

        Uses database config to get server info, then verifies
        emulator containers respond correctly.
        """
        from urllib.parse import urlparse

        # Parse container URLs
        e1_parsed = urlparse(emulator_1_url)
        e2_parsed = urlparse(emulator_2_url)

        # Create ServerSetup from database config
        servers = [
            ServerSetup(
                server_id=seeded_data.target_servers[0].id,
                hostname=seeded_data.target_servers[0].hostname,
                ip_address=e1_parsed.hostname,
                emulator_port=e1_parsed.port,
                cpu_count=4,
                memory_gb=8.0,
            ),
            ServerSetup(
                server_id=seeded_data.target_servers[1].id,
                hostname=seeded_data.target_servers[1].hostname,
                ip_address=e2_parsed.hostname,
                emulator_port=e2_parsed.port,
                cpu_count=4,
                memory_gb=8.0,
            ),
        ]

        # Create orchestrator with short config for testing
        config = ScenarioConfig(
            calibration_duration_sec=2,
            warmup_sec=1,
            max_retries=1,
            retry_delay_sec=1,
        )

        orchestrator = ScenarioOrchestrator(config=config)

        # Verify all emulators are accessible
        async with httpx.AsyncClient() as client:
            for server in servers:
                url = f"http://{server.ip_address}:{server.emulator_port}/health"
                response = await client.get(url)
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_calibration_from_database(self, seeded_data: SeededData):
        """Test retrieving pre-calibrated values from database."""
        # Get calibration for first target, LOW profile
        target_id = seeded_data.target_servers[0].id

        calibrations = [
            cal for cal in seeded_data.calibration_results
            if cal.target_id == target_id and cal.loadprofile == LoadProfile.LOW.value
        ]

        assert len(calibrations) == 1
        cal = calibrations[0]

        assert cal.thread_count == 4  # Pre-seeded value
        assert cal.calibration_status == CalibrationStatus.COMPLETED.value


@pytest.mark.e2e_docker
class TestParallelExecution:
    """Tests for parallel execution across containers."""

    @pytest.mark.asyncio
    async def test_parallel_emulator_start(
        self,
        emulator_1_url: str,
        emulator_2_url: str,
    ):
        """Test starting emulators in parallel."""
        import asyncio

        async with httpx.AsyncClient() as client:
            # Start both emulators concurrently
            results = await asyncio.gather(
                client.post(
                    f"{emulator_1_url}/start",
                    json={"thread_count": 4, "duration_sec": 3},
                ),
                client.post(
                    f"{emulator_2_url}/start",
                    json={"thread_count": 4, "duration_sec": 3},
                ),
                return_exceptions=True,
            )

            # Both should start successfully
            for result in results:
                if isinstance(result, Exception):
                    pytest.fail(f"Failed to start emulator: {result}")
                assert result.status_code == 200

            # Wait briefly
            await asyncio.sleep(1)

            # Check both are running
            status_results = await asyncio.gather(
                client.get(f"{emulator_1_url}/status"),
                client.get(f"{emulator_2_url}/status"),
            )

            for status in status_results:
                data = status.json()
                assert data["is_running"] is True

            # Stop both
            await asyncio.gather(
                client.post(f"{emulator_1_url}/stop"),
                client.post(f"{emulator_2_url}/stop"),
            )

            # Reset both
            await asyncio.gather(
                client.post(f"{emulator_1_url}/reset"),
                client.post(f"{emulator_2_url}/reset"),
            )
