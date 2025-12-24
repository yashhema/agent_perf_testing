"""Unit tests for TestRunExecutionRepository and ExecutionWorkflowStateRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    LoadProfile,
    RunMode,
    ExecutionStatus,
    ExecutionPhase,
    PhaseState,
    OSFamily,
    ServerType,
)
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.execution_repository import (
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
)


class TestTestRunExecutionRepository:
    """Tests for TestRunExecutionRepository CRUD operations."""

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
            req_loadprofile=[LoadProfile.LOW, LoadProfile.MEDIUM],
            loadgenerator_package_grpid_lst=[1],
        )
        return test_run.id

    @pytest.mark.asyncio
    async def test_create_execution(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test creating a new execution."""
        repo = TestRunExecutionRepository(session)

        execution = await repo.create(
            test_run_id=test_run_id,
            run_mode=RunMode.CONTINUOUS,
        )

        assert execution.id is not None
        assert execution.test_run_id == test_run_id
        assert execution.run_mode == RunMode.CONTINUOUS
        assert execution.status == ExecutionStatus.NOT_STARTED
        assert execution.current_repetition == 0
        assert execution.current_loadprofile is None
        assert execution.started_at is None
        assert execution.completed_at is None

    @pytest.mark.asyncio
    async def test_create_execution_stepped_mode(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test creating an execution in stepped mode."""
        repo = TestRunExecutionRepository(session)

        execution = await repo.create(
            test_run_id=test_run_id,
            run_mode=RunMode.STEPPED,
        )

        assert execution.run_mode == RunMode.STEPPED

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test getting an existing execution by ID."""
        repo = TestRunExecutionRepository(session)
        created = await repo.create(test_run_id=test_run_id)

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_test_run_id(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test getting all executions for a test run."""
        repo = TestRunExecutionRepository(session)
        await repo.create(test_run_id=test_run_id)
        await repo.create(test_run_id=test_run_id)

        result = await repo.get_by_test_run_id(test_run_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_active_by_test_run_id(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test getting active execution for a test run."""
        repo = TestRunExecutionRepository(session)

        # Create one active and one ended execution
        active = await repo.create(test_run_id=test_run_id)
        await repo.update_status(active.id, ExecutionStatus.RUNNING)

        ended = await repo.create(test_run_id=test_run_id)
        await repo.update_status(ended.id, ExecutionStatus.ENDED)

        result = await repo.get_active_by_test_run_id(test_run_id)

        assert result is not None
        assert result.status == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_active_by_test_run_id_none_active(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test getting active execution when none exist."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)
        await repo.update_status(execution.id, ExecutionStatus.ENDED)

        result = await repo.get_active_by_test_run_id(test_run_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_active(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test getting all active executions."""
        repo = TestRunExecutionRepository(session)

        # Create executions with different statuses
        running = await repo.create(test_run_id=test_run_id)
        await repo.update_status(running.id, ExecutionStatus.RUNNING)

        calibrating = await repo.create(test_run_id=test_run_id)
        await repo.update_status(calibrating.id, ExecutionStatus.CALIBRATING)

        ended = await repo.create(test_run_id=test_run_id)
        await repo.update_status(ended.id, ExecutionStatus.ENDED)

        result = await repo.get_all_active()

        assert len(result) == 2
        statuses = {r.status for r in result}
        assert ExecutionStatus.RUNNING in statuses
        assert ExecutionStatus.CALIBRATING in statuses
        assert ExecutionStatus.ENDED not in statuses

    @pytest.mark.asyncio
    async def test_update_status_to_running(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test updating status to running sets started_at."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)

        result = await repo.update_status(execution.id, ExecutionStatus.RUNNING)

        assert result is not None
        assert result.status == ExecutionStatus.RUNNING
        assert result.started_at is not None
        assert result.completed_at is None

    @pytest.mark.asyncio
    async def test_update_status_to_ended(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test updating status to ended sets completed_at."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)
        await repo.update_status(execution.id, ExecutionStatus.RUNNING)

        result = await repo.update_status(execution.id, ExecutionStatus.ENDED)

        assert result is not None
        assert result.status == ExecutionStatus.ENDED
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_status_with_error(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test updating status with error message."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)

        result = await repo.update_status(
            execution.id,
            ExecutionStatus.ENDED_ERROR,
            error_message="Test failed",
        )

        assert result is not None
        assert result.status == ExecutionStatus.ENDED_ERROR
        assert result.error_message == "Test failed"

    @pytest.mark.asyncio
    async def test_update_progress(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test updating execution progress."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)

        result = await repo.update_progress(
            execution.id,
            current_loadprofile=LoadProfile.MEDIUM,
            current_repetition=2,
        )

        assert result is not None
        assert result.current_loadprofile == LoadProfile.MEDIUM
        assert result.current_repetition == 2

    @pytest.mark.asyncio
    async def test_delete_execution(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test deleting an execution."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)

        result = await repo.delete_by_id(execution.id)

        assert result is True
        assert await repo.get_by_id(execution.id) is None

    @pytest.mark.asyncio
    async def test_execution_status_is_terminal(
        self,
        session: AsyncSession,
        test_run_id: int,
    ) -> None:
        """Test ExecutionStatus.is_terminal() method."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)

        # Test non-terminal statuses
        await repo.update_status(execution.id, ExecutionStatus.RUNNING)
        result = await repo.get_by_id(execution.id)
        assert not result.status.is_terminal()

        # Test terminal statuses
        await repo.update_status(execution.id, ExecutionStatus.ENDED)
        result = await repo.get_by_id(execution.id)
        assert result.status.is_terminal()


class TestExecutionWorkflowStateRepository:
    """Tests for ExecutionWorkflowStateRepository CRUD operations."""

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
            server_type=ServerType.APP_SERVER,
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

    @pytest.fixture
    async def execution_id(
        self,
        session: AsyncSession,
        test_run_id: int,
    ):
        """Create an execution and return its ID."""
        repo = TestRunExecutionRepository(session)
        execution = await repo.create(test_run_id=test_run_id)
        return execution.id

    @pytest.mark.asyncio
    async def test_create_workflow_state(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test creating a workflow state."""
        repo = ExecutionWorkflowStateRepository(session)

        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        assert state.id is not None
        assert state.test_run_execution_id == execution_id
        assert state.target_id == target_id
        assert state.loadprofile == LoadProfile.LOW
        assert state.runcount == 1
        assert state.current_phase == ExecutionPhase.RESET
        assert state.phase_state == PhaseState.PENDING
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.error_history == []
        assert state.phase_started_at is not None

    @pytest.mark.asyncio
    async def test_get_by_id_existing(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test getting an existing workflow state by ID."""
        repo = ExecutionWorkflowStateRepository(session)
        created = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_get_by_execution_id(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test getting all workflow states for an execution."""
        repo = ExecutionWorkflowStateRepository(session)

        # Create states for different load profiles
        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.COMPLETED,
        )
        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.MEDIUM,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        result = await repo.get_by_execution_id(execution_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_current_for_target(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test getting current workflow state for a target."""
        repo = ExecutionWorkflowStateRepository(session)

        # Create states with different run counts
        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.COMPLETED,
        )
        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=2,
            current_phase=ExecutionPhase.WARMUP,
            phase_state=PhaseState.IN_PROGRESS,
        )

        result = await repo.get_current_for_target(
            execution_id,
            target_id,
            LoadProfile.LOW,
        )

        assert result is not None
        assert result.runcount == 2
        assert result.current_phase == ExecutionPhase.WARMUP

    @pytest.mark.asyncio
    async def test_update_phase(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test updating the current phase."""
        repo = ExecutionWorkflowStateRepository(session)
        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        result = await repo.update_phase(
            state.id,
            current_phase=ExecutionPhase.WARMUP,
            phase_state=PhaseState.IN_PROGRESS,
        )

        assert result is not None
        assert result.current_phase == ExecutionPhase.WARMUP
        assert result.phase_state == PhaseState.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_record_error(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test recording an error."""
        repo = ExecutionWorkflowStateRepository(session)
        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.IN_PROGRESS,
        )

        result = await repo.record_error(state.id, "Connection timeout")

        assert result is not None
        assert result.retry_count == 1
        assert len(result.error_history) == 1
        assert result.error_history[0].error_message == "Connection timeout"
        assert result.error_history[0].retry_count == 1

    @pytest.mark.asyncio
    async def test_record_multiple_errors(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test recording multiple errors."""
        repo = ExecutionWorkflowStateRepository(session)
        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.IN_PROGRESS,
        )

        await repo.record_error(state.id, "Error 1")
        result = await repo.record_error(state.id, "Error 2")

        assert result is not None
        assert result.retry_count == 2
        assert len(result.error_history) == 2

    @pytest.mark.asyncio
    async def test_complete_phase(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test completing a phase."""
        repo = ExecutionWorkflowStateRepository(session)
        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.IN_PROGRESS,
        )

        result = await repo.complete_phase(state.id)

        assert result is not None
        assert result.phase_state == PhaseState.COMPLETED
        assert result.phase_completed_at is not None

    @pytest.mark.asyncio
    async def test_delete_by_execution_id(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test deleting all workflow states for an execution."""
        repo = ExecutionWorkflowStateRepository(session)

        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )
        await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.MEDIUM,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        count = await repo.delete_by_execution_id(execution_id)

        assert count == 2
        assert await repo.get_by_execution_id(execution_id) == []

    @pytest.mark.asyncio
    async def test_workflow_state_model_is_frozen(
        self,
        session: AsyncSession,
        execution_id,
        target_id: int,
    ) -> None:
        """Test that ExecutionWorkflowState model is immutable."""
        repo = ExecutionWorkflowStateRepository(session)
        state = await repo.create(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=LoadProfile.LOW,
            runcount=1,
            current_phase=ExecutionPhase.RESET,
            phase_state=PhaseState.PENDING,
        )

        with pytest.raises(AttributeError):
            state.runcount = 99  # type: ignore
