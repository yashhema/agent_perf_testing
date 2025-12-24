"""Unit tests for ServerRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OSFamily, ServerType
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository


class TestServerRepository:
    """Tests for ServerRepository CRUD operations."""

    @pytest.fixture
    async def lab_id(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> int:
        """Create a lab and return its ID for server tests."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)
        return lab.id

    @pytest.mark.asyncio
    async def test_create_server(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test creating a new server."""
        repo = ServerRepository(session)

        server = await repo.create(lab_id=lab_id, **sample_server_data)

        assert server.id is not None
        assert server.hostname == sample_server_data["hostname"]
        assert server.ip_address == sample_server_data["ip_address"]
        assert server.os_family == sample_server_data["os_family"]
        assert server.server_type == sample_server_data["server_type"]
        assert server.lab_id == lab_id
        assert server.winrm_username == sample_server_data["winrm_username"]
        assert server.is_active is True

    @pytest.mark.asyncio
    async def test_create_linux_loadgen(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_loadgen_data: dict,
    ) -> None:
        """Test creating a Linux load generator server."""
        repo = ServerRepository(session)

        server = await repo.create(lab_id=lab_id, **sample_loadgen_data)

        assert server.os_family == OSFamily.LINUX
        assert server.server_type == ServerType.LOAD_GENERATOR
        assert server.ssh_username == sample_loadgen_data["ssh_username"]
        assert server.ssh_key_path == sample_loadgen_data["ssh_key_path"]

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test getting an existing server by ID."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.hostname == created.hostname

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent server by ID."""
        repo = ServerRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_lab_id(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
        sample_loadgen_data: dict,
    ) -> None:
        """Test getting all servers in a lab."""
        repo = ServerRepository(session)
        await repo.create(lab_id=lab_id, **sample_server_data)
        await repo.create(lab_id=lab_id, **sample_loadgen_data)

        result = await repo.get_by_lab_id(lab_id)

        assert len(result) == 2
        # Should be ordered by hostname
        hostnames = [s.hostname for s in result]
        assert sorted(hostnames) == hostnames

    @pytest.mark.asyncio
    async def test_get_by_type_app_server(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
        sample_loadgen_data: dict,
    ) -> None:
        """Test getting servers by type."""
        repo = ServerRepository(session)
        await repo.create(lab_id=lab_id, **sample_server_data)
        await repo.create(lab_id=lab_id, **sample_loadgen_data)

        result = await repo.get_by_type(lab_id, ServerType.APP_SERVER)

        assert len(result) == 1
        assert result[0].server_type == ServerType.APP_SERVER

    @pytest.mark.asyncio
    async def test_get_by_type_load_generator(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_loadgen_data: dict,
    ) -> None:
        """Test getting load generator servers."""
        repo = ServerRepository(session)
        await repo.create(lab_id=lab_id, **sample_loadgen_data)

        result = await repo.get_by_type(lab_id, ServerType.LOAD_GENERATOR)

        assert len(result) == 1
        assert result[0].server_type == ServerType.LOAD_GENERATOR

    @pytest.mark.asyncio
    async def test_get_by_type_active_only(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test getting only active servers by type."""
        repo = ServerRepository(session)
        server1 = await repo.create(lab_id=lab_id, **sample_server_data)
        inactive_data = {**sample_server_data, "hostname": "inactive-server"}
        inactive_data["is_active"] = False
        await repo.create(lab_id=lab_id, **inactive_data)

        result = await repo.get_by_type(lab_id, ServerType.APP_SERVER, active_only=True)

        assert len(result) == 1
        assert result[0].id == server1.id

    @pytest.mark.asyncio
    async def test_get_by_type_include_inactive(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test getting all servers including inactive."""
        repo = ServerRepository(session)
        await repo.create(lab_id=lab_id, **sample_server_data)
        inactive_data = {**sample_server_data, "hostname": "inactive-server"}
        inactive_data["is_active"] = False
        await repo.create(lab_id=lab_id, **inactive_data)

        result = await repo.get_by_type(
            lab_id, ServerType.APP_SERVER, active_only=False
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_by_hostname_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test getting server by hostname."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.get_by_hostname(sample_server_data["hostname"])

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_hostname_with_lab_id(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test getting server by hostname with lab filter."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.get_by_hostname(
            sample_server_data["hostname"],
            lab_id=lab_id,
        )

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_hostname_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting non-existent server by hostname."""
        repo = ServerRepository(session)

        result = await repo.get_by_hostname("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_hostname(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test updating server hostname."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.update(created.id, hostname="new-hostname")

        assert result is not None
        assert result.hostname == "new-hostname"
        assert result.ip_address == sample_server_data["ip_address"]

    @pytest.mark.asyncio
    async def test_update_ip_address(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test updating server IP address."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.update(created.id, ip_address="10.0.0.1")

        assert result is not None
        assert result.ip_address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_update_os_family(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test updating server OS family."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.update(created.id, os_family=OSFamily.LINUX)

        assert result is not None
        assert result.os_family == OSFamily.LINUX

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test updating a non-existent server."""
        repo = ServerRepository(session)

        result = await repo.update(9999, hostname="new-name")

        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test deactivating a server."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.deactivate(created.id)

        assert result is not None
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_activate(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test activating a deactivated server."""
        repo = ServerRepository(session)
        inactive_data = {**sample_server_data, "is_active": False}
        created = await repo.create(lab_id=lab_id, **inactive_data)

        result = await repo.activate(created.id)

        assert result is not None
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_delete_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test deleting an existing server."""
        repo = ServerRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_server_data)

        result = await repo.delete_by_id(created.id)

        assert result is True
        assert await repo.get_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test deleting a non-existent server."""
        repo = ServerRepository(session)

        result = await repo.delete_by_id(9999)

        assert result is False

    @pytest.mark.asyncio
    async def test_server_model_is_frozen(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_server_data: dict,
    ) -> None:
        """Test that Server model is immutable (frozen dataclass)."""
        repo = ServerRepository(session)
        server = await repo.create(lab_id=lab_id, **sample_server_data)

        with pytest.raises(AttributeError):
            server.hostname = "Should not work"  # type: ignore
