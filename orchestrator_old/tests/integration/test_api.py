"""Integration tests for API endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthAPI:
    """Integration tests for health endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient) -> None:
        """Test basic health check endpoint."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "orchestrator"


class TestLabsAPI:
    """Integration tests for labs API."""

    @pytest.mark.asyncio
    async def test_create_lab(self, client: AsyncClient) -> None:
        """Test creating a lab."""
        response = await client.post(
            "/api/v1/labs/",
            json={
                "name": "Test Lab",
                "lab_type": "server",
                "description": "A test lab",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Lab"
        assert data["lab_type"] == "server"
        assert data["description"] == "A test lab"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_lab_without_description(self, client: AsyncClient) -> None:
        """Test creating a lab without description."""
        response = await client.post(
            "/api/v1/labs/",
            json={
                "name": "Minimal Lab",
                "lab_type": "euc",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Lab"
        assert data["description"] is None

    @pytest.mark.asyncio
    async def test_create_lab_duplicate_name(self, client: AsyncClient) -> None:
        """Test creating a lab with duplicate name fails."""
        await client.post(
            "/api/v1/labs/",
            json={"name": "Duplicate Lab", "lab_type": "server"},
        )

        response = await client.post(
            "/api/v1/labs/",
            json={"name": "Duplicate Lab", "lab_type": "euc"},
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_labs(self, client: AsyncClient) -> None:
        """Test listing labs."""
        await client.post(
            "/api/v1/labs/",
            json={"name": "Lab 1", "lab_type": "server"},
        )
        await client.post(
            "/api/v1/labs/",
            json={"name": "Lab 2", "lab_type": "euc"},
        )

        response = await client.get("/api/v1/labs/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["labs"]) == 2

    @pytest.mark.asyncio
    async def test_get_lab(self, client: AsyncClient) -> None:
        """Test getting a lab by ID."""
        create_response = await client.post(
            "/api/v1/labs/",
            json={"name": "Get Test Lab", "lab_type": "server"},
        )
        lab_id = create_response.json()["id"]

        response = await client.get(f"/api/v1/labs/{lab_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == lab_id
        assert data["name"] == "Get Test Lab"

    @pytest.mark.asyncio
    async def test_get_lab_not_found(self, client: AsyncClient) -> None:
        """Test getting a non-existent lab."""
        response = await client.get("/api/v1/labs/9999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_lab(self, client: AsyncClient) -> None:
        """Test updating a lab."""
        create_response = await client.post(
            "/api/v1/labs/",
            json={"name": "Update Test Lab", "lab_type": "server"},
        )
        lab_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/labs/{lab_id}",
            json={"name": "Updated Lab Name", "description": "New description"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Lab Name"
        assert data["description"] == "New description"

    @pytest.mark.asyncio
    async def test_delete_lab(self, client: AsyncClient) -> None:
        """Test deleting a lab."""
        create_response = await client.post(
            "/api/v1/labs/",
            json={"name": "Delete Test Lab", "lab_type": "server"},
        )
        lab_id = create_response.json()["id"]

        response = await client.delete(f"/api/v1/labs/{lab_id}")

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify it's deleted
        get_response = await client.get(f"/api/v1/labs/{lab_id}")
        assert get_response.status_code == 404


class TestServersAPI:
    """Integration tests for servers API."""

    @pytest.fixture
    async def lab_id(self, client: AsyncClient) -> int:
        """Create a lab and return its ID."""
        response = await client.post(
            "/api/v1/labs/",
            json={"name": "Server Test Lab", "lab_type": "server"},
        )
        return response.json()["id"]

    @pytest.mark.asyncio
    async def test_create_server(self, client: AsyncClient, lab_id: int) -> None:
        """Test creating a server."""
        response = await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "test-server-01",
                "ip_address": "192.168.1.100",
                "os_family": "windows",
                "server_type": "app_server",
                "lab_id": lab_id,
                "winrm_username": "admin",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["hostname"] == "test-server-01"
        assert data["ip_address"] == "192.168.1.100"
        assert data["os_family"] == "windows"
        assert data["server_type"] == "app_server"
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_linux_loadgen(self, client: AsyncClient, lab_id: int) -> None:
        """Test creating a Linux load generator."""
        response = await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "loadgen-01",
                "ip_address": "192.168.1.200",
                "os_family": "linux",
                "server_type": "load_generator",
                "lab_id": lab_id,
                "ssh_username": "ubuntu",
                "ssh_key_path": "/path/to/key",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["os_family"] == "linux"
        assert data["server_type"] == "load_generator"

    @pytest.mark.asyncio
    async def test_list_servers(self, client: AsyncClient, lab_id: int) -> None:
        """Test listing servers in a lab."""
        await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "server-1",
                "ip_address": "10.0.0.1",
                "os_family": "linux",
                "server_type": "app_server",
                "lab_id": lab_id,
            },
        )
        await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "server-2",
                "ip_address": "10.0.0.2",
                "os_family": "linux",
                "server_type": "load_generator",
                "lab_id": lab_id,
            },
        )

        response = await client.get(f"/api/v1/servers/?lab_id={lab_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_servers_by_type(
        self,
        client: AsyncClient,
        lab_id: int,
    ) -> None:
        """Test filtering servers by type."""
        await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "app-server",
                "ip_address": "10.0.0.1",
                "os_family": "linux",
                "server_type": "app_server",
                "lab_id": lab_id,
            },
        )
        await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "loadgen",
                "ip_address": "10.0.0.2",
                "os_family": "linux",
                "server_type": "load_generator",
                "lab_id": lab_id,
            },
        )

        response = await client.get(
            f"/api/v1/servers/?lab_id={lab_id}&server_type=app_server"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["servers"][0]["server_type"] == "app_server"

    @pytest.mark.asyncio
    async def test_deactivate_server(self, client: AsyncClient, lab_id: int) -> None:
        """Test deactivating a server."""
        create_response = await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "deactivate-test",
                "ip_address": "10.0.0.1",
                "os_family": "linux",
                "server_type": "app_server",
                "lab_id": lab_id,
            },
        )
        server_id = create_response.json()["id"]

        response = await client.post(f"/api/v1/servers/{server_id}/deactivate")

        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestTestRunsAPI:
    """Integration tests for test runs API."""

    @pytest.fixture
    async def lab_id(self, client: AsyncClient) -> int:
        """Create a lab and return its ID."""
        response = await client.post(
            "/api/v1/labs/",
            json={"name": "Test Run Lab", "lab_type": "server"},
        )
        return response.json()["id"]

    @pytest.mark.asyncio
    async def test_create_test_run(self, client: AsyncClient, lab_id: int) -> None:
        """Test creating a test run."""
        response = await client.post(
            "/api/v1/test-runs/",
            json={
                "name": "Performance Test 1",
                "description": "First performance test",
                "lab_id": lab_id,
                "req_loadprofile": ["low", "medium", "high"],
                "warmup_sec": 300,
                "measured_sec": 3600,
                "repetitions": 2,
                "loadgenerator_package_grpid_lst": [1, 2],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Performance Test 1"
        assert data["req_loadprofile"] == ["low", "medium", "high"]
        assert data["warmup_sec"] == 300
        assert data["repetitions"] == 2

    @pytest.mark.asyncio
    async def test_create_test_run_defaults(
        self,
        client: AsyncClient,
        lab_id: int,
    ) -> None:
        """Test creating a test run with default values."""
        response = await client.post(
            "/api/v1/test-runs/",
            json={
                "name": "Minimal Test",
                "lab_id": lab_id,
                "req_loadprofile": ["low"],
                "loadgenerator_package_grpid_lst": [1],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["warmup_sec"] == 300
        assert data["measured_sec"] == 10800
        assert data["repetitions"] == 1

    @pytest.mark.asyncio
    async def test_list_test_runs(self, client: AsyncClient, lab_id: int) -> None:
        """Test listing test runs."""
        await client.post(
            "/api/v1/test-runs/",
            json={
                "name": "Test 1",
                "lab_id": lab_id,
                "req_loadprofile": ["low"],
                "loadgenerator_package_grpid_lst": [1],
            },
        )
        await client.post(
            "/api/v1/test-runs/",
            json={
                "name": "Test 2",
                "lab_id": lab_id,
                "req_loadprofile": ["high"],
                "loadgenerator_package_grpid_lst": [2],
            },
        )

        response = await client.get(f"/api/v1/test-runs/?lab_id={lab_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2


class TestExecutionsAPI:
    """Integration tests for executions API."""

    @pytest.fixture
    async def test_run_with_targets(self, client: AsyncClient) -> dict:
        """Create a lab, servers, and test run with targets."""
        # Create lab
        lab_response = await client.post(
            "/api/v1/labs/",
            json={"name": "Execution Test Lab", "lab_type": "server"},
        )
        lab_id = lab_response.json()["id"]

        # Create target server
        target_response = await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "target-01",
                "ip_address": "192.168.1.100",
                "os_family": "windows",
                "server_type": "app_server",
                "lab_id": lab_id,
            },
        )
        target_id = target_response.json()["id"]

        # Create load generator
        loadgen_response = await client.post(
            "/api/v1/servers/",
            json={
                "hostname": "loadgen-01",
                "ip_address": "192.168.1.200",
                "os_family": "linux",
                "server_type": "load_generator",
                "lab_id": lab_id,
            },
        )
        loadgen_id = loadgen_response.json()["id"]

        # Create test run
        test_run_response = await client.post(
            "/api/v1/test-runs/",
            json={
                "name": "Execution Test Run",
                "lab_id": lab_id,
                "req_loadprofile": ["low", "medium"],
                "loadgenerator_package_grpid_lst": [1],
            },
        )
        test_run_id = test_run_response.json()["id"]

        # Add target to test run
        await client.post(
            f"/api/v1/test-runs/{test_run_id}/targets",
            json={
                "target_id": target_id,
                "loadgenerator_id": loadgen_id,
            },
        )

        return {
            "lab_id": lab_id,
            "test_run_id": test_run_id,
            "target_id": target_id,
            "loadgen_id": loadgen_id,
        }

    @pytest.mark.asyncio
    async def test_create_execution(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test creating an execution."""
        test_run_id = test_run_with_targets["test_run_id"]

        response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
                "immediate_run": False,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] is not None
        assert data["calibration_started"] is False

    @pytest.mark.asyncio
    async def test_create_execution_immediate_run(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test creating an execution with immediate run."""
        test_run_id = test_run_with_targets["test_run_id"]

        response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
                "immediate_run": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["calibration_started"] is True

    @pytest.mark.asyncio
    async def test_create_execution_invalid_test_run(
        self,
        client: AsyncClient,
    ) -> None:
        """Test creating an execution with invalid test run."""
        response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": 99999,
                "run_mode": "continuous",
            },
        )

        assert response.status_code == 400
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_active_executions(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test listing active executions."""
        test_run_id = test_run_with_targets["test_run_id"]

        # Create an execution
        await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
            },
        )

        response = await client.get("/api/v1/executions/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_execution(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test getting an execution by ID."""
        test_run_id = test_run_with_targets["test_run_id"]

        create_response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
            },
        )
        execution_id = create_response.json()["id"]

        response = await client.get(f"/api/v1/executions/{execution_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == execution_id
        assert data["test_run_id"] == test_run_id

    @pytest.mark.asyncio
    async def test_abandon_execution(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test abandoning an execution."""
        test_run_id = test_run_with_targets["test_run_id"]

        create_response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
            },
        )
        execution_id = create_response.json()["id"]

        response = await client.post(f"/api/v1/executions/{execution_id}/abandon")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["new_status"] == "abandoned"

    @pytest.mark.asyncio
    async def test_execution_action_status(
        self,
        client: AsyncClient,
        test_run_with_targets: dict,
    ) -> None:
        """Test status action on execution."""
        test_run_id = test_run_with_targets["test_run_id"]

        create_response = await client.post(
            "/api/v1/executions/",
            json={
                "test_run_id": test_run_id,
                "run_mode": "continuous",
            },
        )
        execution_id = create_response.json()["id"]

        response = await client.post(
            f"/api/v1/executions/{execution_id}/action",
            json={"action": "status"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "status" in data["message"].lower()
