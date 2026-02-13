"""Unit tests for BaselineRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import BaselineConfig
from app.models.enums import BaselineType
from app.repositories.lab_repository import LabRepository
from app.repositories.baseline_repository import BaselineRepository


class TestBaselineRepository:
    """Tests for BaselineRepository CRUD operations."""

    @pytest.fixture
    async def lab_id(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> int:
        """Create a lab and return its ID for baseline tests."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)
        return lab.id

    @pytest.fixture
    def vsphere_config(self) -> BaselineConfig:
        """Create a vSphere baseline config."""
        return BaselineConfig(
            vcenter_host="vcenter.example.com",
            datacenter="DC1",
            snapshot_name="clean-snapshot",
        )

    @pytest.fixture
    def aws_config(self) -> BaselineConfig:
        """Create an AWS baseline config."""
        return BaselineConfig(
            ami_id="ami-12345678",
            instance_type="t3.medium",
            region="us-east-1",
        )

    @pytest.mark.asyncio
    async def test_create_vsphere_baseline(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test creating a vSphere baseline."""
        repo = BaselineRepository(session)

        baseline = await repo.create(
            name="Windows 10 Base",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
            description="Base Windows 10 snapshot",
        )

        assert baseline.id is not None
        assert baseline.name == "Windows 10 Base"
        assert baseline.baseline_type == BaselineType.VSPHERE
        assert baseline.baseline_conf.vcenter_host == "vcenter.example.com"
        assert baseline.baseline_conf.datacenter == "DC1"
        assert baseline.baseline_conf.snapshot_name == "clean-snapshot"
        assert baseline.lab_id == lab_id

    @pytest.mark.asyncio
    async def test_create_aws_baseline(
        self,
        session: AsyncSession,
        lab_id: int,
        aws_config: BaselineConfig,
    ) -> None:
        """Test creating an AWS baseline."""
        repo = BaselineRepository(session)

        baseline = await repo.create(
            name="AWS Linux Base",
            baseline_type=BaselineType.AWS,
            baseline_conf=aws_config,
            lab_id=lab_id,
        )

        assert baseline.baseline_type == BaselineType.AWS
        assert baseline.baseline_conf.ami_id == "ami-12345678"
        assert baseline.baseline_conf.instance_type == "t3.medium"
        assert baseline.baseline_conf.region == "us-east-1"

    @pytest.mark.asyncio
    async def test_create_intune_baseline(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test creating an Intune baseline."""
        repo = BaselineRepository(session)
        config = BaselineConfig(
            policy_id="policy-123",
            group_id="group-456",
        )

        baseline = await repo.create(
            name="Intune Policy",
            baseline_type=BaselineType.INTUNE,
            baseline_conf=config,
            lab_id=lab_id,
        )

        assert baseline.baseline_type == BaselineType.INTUNE
        assert baseline.baseline_conf.policy_id == "policy-123"
        assert baseline.baseline_conf.group_id == "group-456"

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test getting an existing baseline by ID."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Test Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent baseline by ID."""
        repo = BaselineRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_lab_id(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
        aws_config: BaselineConfig,
    ) -> None:
        """Test getting all baselines in a lab."""
        repo = BaselineRepository(session)
        await repo.create(
            name="Baseline A",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )
        await repo.create(
            name="Baseline B",
            baseline_type=BaselineType.AWS,
            baseline_conf=aws_config,
            lab_id=lab_id,
        )

        result = await repo.get_by_lab_id(lab_id)

        assert len(result) == 2
        # Should be ordered by name
        assert result[0].name == "Baseline A"
        assert result[1].name == "Baseline B"

    @pytest.mark.asyncio
    async def test_get_by_type(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
        aws_config: BaselineConfig,
    ) -> None:
        """Test getting baselines by type."""
        repo = BaselineRepository(session)
        await repo.create(
            name="vSphere Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )
        await repo.create(
            name="AWS Baseline",
            baseline_type=BaselineType.AWS,
            baseline_conf=aws_config,
            lab_id=lab_id,
        )

        result = await repo.get_by_type(lab_id, BaselineType.VSPHERE)

        assert len(result) == 1
        assert result[0].baseline_type == BaselineType.VSPHERE

    @pytest.mark.asyncio
    async def test_get_by_name_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test getting baseline by name."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Unique Name",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        result = await repo.get_by_name("Unique Name", lab_id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test getting non-existent baseline by name."""
        repo = BaselineRepository(session)

        result = await repo.get_by_name("nonexistent", lab_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_name(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test updating baseline name."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Original Name",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        result = await repo.update(created.id, name="Updated Name")

        assert result is not None
        assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_description(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test updating baseline description."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Test Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        result = await repo.update(created.id, description="New description")

        assert result is not None
        assert result.description == "New description"

    @pytest.mark.asyncio
    async def test_update_config(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test updating baseline configuration."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Test Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        new_config = BaselineConfig(
            vcenter_host="new-vcenter.example.com",
            datacenter="DC2",
            snapshot_name="new-snapshot",
        )
        result = await repo.update(created.id, baseline_conf=new_config)

        assert result is not None
        assert result.baseline_conf.vcenter_host == "new-vcenter.example.com"
        assert result.baseline_conf.datacenter == "DC2"
        assert result.baseline_conf.snapshot_name == "new-snapshot"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test updating a non-existent baseline."""
        repo = BaselineRepository(session)

        result = await repo.update(9999, name="New Name")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test deleting an existing baseline."""
        repo = BaselineRepository(session)
        created = await repo.create(
            name="Test Baseline",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        result = await repo.delete_by_id(created.id)

        assert result is True
        assert await repo.get_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test deleting a non-existent baseline."""
        repo = BaselineRepository(session)

        result = await repo.delete_by_id(9999)

        assert result is False

    @pytest.mark.asyncio
    async def test_baseline_config_preserves_optional_fields(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test that BaselineConfig properly preserves optional fields as None."""
        repo = BaselineRepository(session)
        config = BaselineConfig(
            vcenter_host="vcenter.example.com",
            # Only set vcenter_host, others should be None
        )

        baseline = await repo.create(
            name="Partial Config",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=config,
            lab_id=lab_id,
        )

        assert baseline.baseline_conf.vcenter_host == "vcenter.example.com"
        assert baseline.baseline_conf.datacenter is None
        assert baseline.baseline_conf.snapshot_name is None
        assert baseline.baseline_conf.ami_id is None

    @pytest.mark.asyncio
    async def test_baseline_model_is_frozen(
        self,
        session: AsyncSession,
        lab_id: int,
        vsphere_config: BaselineConfig,
    ) -> None:
        """Test that Baseline model is immutable (frozen dataclass)."""
        repo = BaselineRepository(session)
        baseline = await repo.create(
            name="Test",
            baseline_type=BaselineType.VSPHERE,
            baseline_conf=vsphere_config,
            lab_id=lab_id,
        )

        with pytest.raises(AttributeError):
            baseline.name = "Should not work"  # type: ignore
