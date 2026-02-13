"""Unit tests for TestRunRepository and TestRunTargetRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LoadProfile, OSFamily, ServerRole
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository


class TestTestRunRepository:
    """Tests for TestRunRepository CRUD operations."""

    @pytest.fixture
    async def lab_id(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> int:
        """Create a lab and return its ID."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)
        return lab.id

    @pytest.mark.asyncio
    async def test_create_test_run(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test creating a new test run."""
        repo = TestRunRepository(session)

        test_run = await repo.create(lab_id=lab_id, **sample_test_run_data)

        assert test_run.id is not None
        assert test_run.name == sample_test_run_data["name"]
        assert test_run.description == sample_test_run_data["description"]
        assert test_run.lab_id == lab_id
        assert test_run.req_loadprofile == sample_test_run_data["req_loadprofile"]
        assert test_run.warmup_sec == sample_test_run_data["warmup_sec"]
        assert test_run.measured_sec == sample_test_run_data["measured_sec"]
        assert test_run.repetitions == sample_test_run_data["repetitions"]
        assert (
            test_run.loadgenerator_package_grpid_lst
            == sample_test_run_data["loadgenerator_package_grpid_lst"]
        )

    @pytest.mark.asyncio
    async def test_create_test_run_with_defaults(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test creating a test run with default values."""
        repo = TestRunRepository(session)

        test_run = await repo.create(
            name="Minimal Test Run",
            lab_id=lab_id,
            req_loadprofile=[LoadProfile.LOW],
            loadgenerator_package_grpid_lst=[1],
        )

        assert test_run.warmup_sec == 300
        assert test_run.measured_sec == 10800
        assert test_run.analysis_trim_sec == 300
        assert test_run.repetitions == 1

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test getting an existing test run by ID."""
        repo = TestRunRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_test_run_data)

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent test run by ID."""
        repo = TestRunRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_lab_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test getting all test runs in a lab."""
        repo = TestRunRepository(session)
        await repo.create(
            name="Test Run 1",
            lab_id=lab_id,
            req_loadprofile=[LoadProfile.LOW],
            loadgenerator_package_grpid_lst=[1],
        )
        await repo.create(
            name="Test Run 2",
            lab_id=lab_id,
            req_loadprofile=[LoadProfile.MEDIUM],
            loadgenerator_package_grpid_lst=[2],
        )

        result = await repo.get_by_lab_id(lab_id)

        assert len(result) == 2
        # Should be ordered by created_at desc (newest first)
        assert result[0].name == "Test Run 2"
        assert result[1].name == "Test Run 1"

    @pytest.mark.asyncio
    async def test_update_name(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test updating test run name."""
        repo = TestRunRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_test_run_data)

        result = await repo.update(created.id, name="Updated Name")

        assert result is not None
        assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_loadprofile(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test updating test run load profile."""
        repo = TestRunRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_test_run_data)

        result = await repo.update(
            created.id,
            req_loadprofile=[LoadProfile.MEDIUM, LoadProfile.HIGH],
        )

        assert result is not None
        assert result.req_loadprofile == [LoadProfile.MEDIUM, LoadProfile.HIGH]

    @pytest.mark.asyncio
    async def test_update_timing_parameters(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test updating test run timing parameters."""
        repo = TestRunRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_test_run_data)

        result = await repo.update(
            created.id,
            warmup_sec=600,
            measured_sec=7200,
            analysis_trim_sec=120,
        )

        assert result is not None
        assert result.warmup_sec == 600
        assert result.measured_sec == 7200
        assert result.analysis_trim_sec == 120

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test updating a non-existent test run."""
        repo = TestRunRepository(session)

        result = await repo.update(9999, name="New Name")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(
        self,
        session: AsyncSession,
        lab_id: int,
        sample_test_run_data: dict,
    ) -> None:
        """Test deleting an existing test run."""
        repo = TestRunRepository(session)
        created = await repo.create(lab_id=lab_id, **sample_test_run_data)

        result = await repo.delete_by_id(created.id)

        assert result is True
        assert await repo.get_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test deleting a non-existent test run."""
        repo = TestRunRepository(session)

        result = await repo.delete_by_id(9999)

        assert result is False

    @pytest.mark.asyncio
    async def test_loadprofile_conversion(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> None:
        """Test that LoadProfile enums are properly converted."""
        repo = TestRunRepository(session)

        test_run = await repo.create(
            name="Profile Test",
            lab_id=lab_id,
            req_loadprofile=[LoadProfile.LOW, LoadProfile.MEDIUM, LoadProfile.HIGH],
            loadgenerator_package_grpid_lst=[1],
        )

        assert all(isinstance(lp, LoadProfile) for lp in test_run.req_loadprofile)
        assert LoadProfile.LOW in test_run.req_loadprofile
        assert LoadProfile.MEDIUM in test_run.req_loadprofile
        assert LoadProfile.HIGH in test_run.req_loadprofile


class TestTestRunTargetRepository:
    """Tests for TestRunTargetRepository CRUD operations."""

    @pytest.fixture
    async def lab_id(
        self,
        session: AsyncSession,
        sample_lab_data: dict,
    ) -> int:
        """Create a lab and return its ID."""
        repo = LabRepository(session)
        lab = await repo.create(**sample_lab_data)
        return lab.id

    @pytest.fixture
    async def target_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> int:
        """Create a target server and return its ID."""
        repo = ServerRepository(session)
        server = await repo.create(
            hostname="target-01",
            ip_address="192.168.1.100",
            os_family=OSFamily.WINDOWS,
            server_type=ServerRole.APP_SERVER,
            lab_id=lab_id,
        )
        return server.id

    @pytest.fixture
    async def loadgen_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> int:
        """Create a load generator server and return its ID."""
        repo = ServerRepository(session)
        server = await repo.create(
            hostname="loadgen-01",
            ip_address="192.168.1.200",
            os_family=OSFamily.LINUX,
            server_type=ServerRole.LOAD_GENERATOR,
            lab_id=lab_id,
        )
        return server.id

    @pytest.fixture
    async def test_run_id(
        self,
        session: AsyncSession,
        lab_id: int,
    ) -> int:
        """Create a test run and return its ID."""
        repo = TestRunRepository(session)
        test_run = await repo.create(
            name="Test Run",
            lab_id=lab_id,
            req_loadprofile=[LoadProfile.LOW],
            loadgenerator_package_grpid_lst=[1],
        )
        return test_run.id

    @pytest.mark.asyncio
    async def test_create_target(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
    ) -> None:
        """Test creating a test run target."""
        repo = TestRunTargetRepository(session)

        target = await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
            jmeter_port=1099,
            jmx_file_path="/path/to/test.jmx",
        )

        assert target.id is not None
        assert target.test_run_id == test_run_id
        assert target.target_id == target_id
        assert target.loadgenerator_id == loadgen_id
        assert target.jmeter_port == 1099
        assert target.jmx_file_path == "/path/to/test.jmx"

    @pytest.mark.asyncio
    async def test_create_target_minimal(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
    ) -> None:
        """Test creating a test run target with minimal data."""
        repo = TestRunTargetRepository(session)

        target = await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )

        assert target.id is not None
        assert target.jmeter_port is None
        assert target.jmx_file_path is None
        assert target.base_baseline_id is None
        assert target.initial_baseline_id is None
        assert target.upgrade_baseline_id is None

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
    ) -> None:
        """Test getting an existing target by ID."""
        repo = TestRunTargetRepository(session)
        created = await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        session: AsyncSession,
    ) -> None:
        """Test getting a non-existent target by ID."""
        repo = TestRunTargetRepository(session)

        result = await repo.get_by_id(9999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_test_run_id(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
        lab_id: int,
    ) -> None:
        """Test getting all targets for a test run."""
        repo = TestRunTargetRepository(session)
        server_repo = ServerRepository(session)

        # Create another target server
        target2 = await server_repo.create(
            hostname="target-02",
            ip_address="192.168.1.101",
            os_family=OSFamily.WINDOWS,
            server_type=ServerRole.APP_SERVER,
            lab_id=lab_id,
        )

        await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )
        await repo.create(
            test_run_id=test_run_id,
            target_id=target2.id,
            loadgenerator_id=loadgen_id,
        )

        result = await repo.get_by_test_run_id(test_run_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_by_target_id(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
    ) -> None:
        """Test getting all test run associations for a target."""
        repo = TestRunTargetRepository(session)
        await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )

        result = await repo.get_by_target_id(target_id)

        assert len(result) == 1
        assert result[0].target_id == target_id

    @pytest.mark.asyncio
    async def test_delete_by_test_run_id(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
        lab_id: int,
    ) -> None:
        """Test deleting all targets for a test run."""
        repo = TestRunTargetRepository(session)
        server_repo = ServerRepository(session)

        # Create another target server
        target2 = await server_repo.create(
            hostname="target-02",
            ip_address="192.168.1.101",
            os_family=OSFamily.WINDOWS,
            server_type=ServerRole.APP_SERVER,
            lab_id=lab_id,
        )

        await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )
        await repo.create(
            test_run_id=test_run_id,
            target_id=target2.id,
            loadgenerator_id=loadgen_id,
        )

        count = await repo.delete_by_test_run_id(test_run_id)

        assert count == 2
        assert await repo.get_by_test_run_id(test_run_id) == []

    @pytest.mark.asyncio
    async def test_delete_by_test_run_id_no_targets(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test deleting targets when none exist."""
        repo = TestRunTargetRepository(session)

        count = await repo.delete_by_test_run_id(test_run_id)

        assert count == 0

    @pytest.mark.asyncio
    async def test_target_model_is_frozen(
        self,
        session: AsyncSession,
        test_run_id: int,
        target_id: int,
        loadgen_id: int,
    ) -> None:
        """Test that TestRunTarget model is immutable (frozen dataclass)."""
        repo = TestRunTargetRepository(session)
        target = await repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgen_id,
        )

        with pytest.raises(AttributeError):
            target.jmeter_port = 9999  # type: ignore
