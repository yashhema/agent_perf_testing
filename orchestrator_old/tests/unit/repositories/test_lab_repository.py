"""Unit tests for LabRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Lab
from app.repositories.lab_repository import LabRepository


class TestLabRepository:
    """Tests for LabRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_lab(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test creating a new lab."""
        repo = LabRepository(session)

        lab = await repo.create(**sample_lab_data)

        assert lab.id is not None
        assert lab.name == sample_lab_data["name"]
        assert lab.lab_type == sample_lab_data["lab_type"]
        assert lab.description == sample_lab_data["description"]
        assert lab.created_at is not None
        assert lab.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_lab_without_description(
        self,
        session: AsyncSession,
    ) -> None:
        """Test creating a lab without description."""
        repo = LabRepository(session)

        lab = await repo.create(name="Minimal Lab", lab_type="euc")

        assert lab.id is not None
        assert lab.name == "Minimal Lab"
        assert lab.lab_type == "euc"
        assert lab.description is None

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test getting an existing lab by ID."""
        repo = LabRepository(session)
        created = await repo.create(**sample_lab_data)

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent lab by ID."""
        repo = LabRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name_existing(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test getting an existing lab by name."""
        repo = LabRepository(session)
        await repo.create(**sample_lab_data)

        result = await repo.get_by_name(sample_lab_data["name"])

        assert result is not None
        assert result.name == sample_lab_data["name"]

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent lab by name."""
        repo = LabRepository(session)

        result = await repo.get_by_name("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_empty(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting all labs when none exist."""
        repo = LabRepository(session)

        result = await repo.get_all()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_multiple(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting all labs with multiple entries."""
        repo = LabRepository(session)
        await repo.create(name="Lab A", lab_type="server")
        await repo.create(name="Lab B", lab_type="euc")
        await repo.create(name="Lab C", lab_type="server")

        result = await repo.get_all()

        assert len(result) == 3
        # Should be ordered by ID
        assert result[0].name == "Lab A"
        assert result[1].name == "Lab B"
        assert result[2].name == "Lab C"

    @pytest.mark.asyncio
    async def test_update_name(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test updating lab name."""
        repo = LabRepository(session)
        created = await repo.create(**sample_lab_data)

        result = await repo.update(created.id, name="Updated Lab Name")

        assert result is not None
        assert result.name == "Updated Lab Name"
        assert result.description == sample_lab_data["description"]

    @pytest.mark.asyncio
    async def test_update_description(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test updating lab description."""
        repo = LabRepository(session)
        created = await repo.create(**sample_lab_data)

        result = await repo.update(created.id, description="New description")

        assert result is not None
        assert result.name == sample_lab_data["name"]
        assert result.description == "New description"

    @pytest.mark.asyncio
    async def test_update_lab_type(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test updating lab type."""
        repo = LabRepository(session)
        created = await repo.create(**sample_lab_data)

        result = await repo.update(created.id, lab_type="euc")

        assert result is not None
        assert result.lab_type == "euc"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test updating a non-existent lab."""
        repo = LabRepository(session)

        result = await repo.update(9999, name="New Name")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test deleting an existing lab."""
        repo = LabRepository(session)
        created = await repo.create(**sample_lab_data)

        result = await repo.delete_by_id(created.id)

        assert result is True
        assert await repo.get_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test deleting a non-existent lab."""
        repo = LabRepository(session)

        result = await repo.delete_by_id(9999)

        assert result is False

    @pytest.mark.asyncio
    async def test_lab_model_is_frozen(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> None:
        """Test that Lab model is immutable (frozen dataclass)."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)

        with pytest.raises(AttributeError):
            lab.name = "Should not work"  # type: ignore
