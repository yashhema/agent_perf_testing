"""Repository for TestRunExecution and ExecutionWorkflowState entities."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import (
    TestRunExecution,
    ExecutionWorkflowState,
    ErrorRecord,
)
from app.models.enums import (
    RunMode,
    ExecutionStatus,
    LoadProfile,
    ExecutionPhase,
    PhaseState,
)
from app.models.orm import TestRunExecutionORM, ExecutionWorkflowStateORM


class TestRunExecutionRepository:
    """Repository for TestRunExecution CRUD operations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _orm_to_model(self, orm: TestRunExecutionORM) -> TestRunExecution:
        """Convert TestRunExecutionORM to TestRunExecution application model."""
        return TestRunExecution(
            id=orm.id,
            test_run_id=orm.test_run_id,
            run_mode=RunMode(orm.run_mode),
            status=ExecutionStatus(orm.status),
            current_loadprofile=(
                LoadProfile(orm.current_loadprofile)
                if orm.current_loadprofile
                else None
            ),
            current_repetition=orm.current_repetition,
            error_message=orm.error_message,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        test_run_id: int,
        run_mode: RunMode = RunMode.CONTINUOUS,
    ) -> TestRunExecution:
        """Create a new test run execution."""
        orm = TestRunExecutionORM(
            test_run_id=test_run_id,
            run_mode=run_mode.value,
            status=ExecutionStatus.NOT_STARTED.value,
            current_repetition=0,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_id(self, execution_id: UUID) -> Optional[TestRunExecution]:
        """Get execution by ID."""
        stmt = select(TestRunExecutionORM).where(
            TestRunExecutionORM.id == execution_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_by_test_run_id(self, test_run_id: int) -> list[TestRunExecution]:
        """Get all executions for a test run."""
        stmt = (
            select(TestRunExecutionORM)
            .where(TestRunExecutionORM.test_run_id == test_run_id)
            .order_by(TestRunExecutionORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_active_by_test_run_id(
        self,
        test_run_id: int,
    ) -> Optional[TestRunExecution]:
        """Get active execution for a test run (non-terminal status)."""
        terminal_statuses = [
            ExecutionStatus.ENDED.value,
            ExecutionStatus.ENDED_ERROR.value,
            ExecutionStatus.ABANDONED.value,
        ]

        stmt = (
            select(TestRunExecutionORM)
            .where(
                and_(
                    TestRunExecutionORM.test_run_id == test_run_id,
                    TestRunExecutionORM.status.notin_(terminal_statuses),
                )
            )
            .order_by(TestRunExecutionORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_all_active(self) -> list[TestRunExecution]:
        """Get all active executions (non-terminal status)."""
        terminal_statuses = [
            ExecutionStatus.ENDED.value,
            ExecutionStatus.ENDED_ERROR.value,
            ExecutionStatus.ABANDONED.value,
        ]

        stmt = (
            select(TestRunExecutionORM)
            .where(TestRunExecutionORM.status.notin_(terminal_statuses))
            .order_by(TestRunExecutionORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_with_workflow_states(
        self,
        execution_id: UUID,
    ) -> Optional[TestRunExecution]:
        """Get execution with eager-loaded workflow states."""
        stmt = (
            select(TestRunExecutionORM)
            .where(TestRunExecutionORM.id == execution_id)
            .options(selectinload(TestRunExecutionORM.workflow_states))
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update_status(
        self,
        execution_id: UUID,
        status: ExecutionStatus,
        error_message: Optional[str] = None,
    ) -> Optional[TestRunExecution]:
        """Update execution status."""
        stmt = select(TestRunExecutionORM).where(
            TestRunExecutionORM.id == execution_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        orm.status = status.value
        if error_message is not None:
            orm.error_message = error_message

        # Set timestamps based on status
        if status == ExecutionStatus.RUNNING and orm.started_at is None:
            orm.started_at = datetime.utcnow()
        elif status.is_terminal():
            orm.completed_at = datetime.utcnow()

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def update_progress(
        self,
        execution_id: UUID,
        current_loadprofile: Optional[LoadProfile] = None,
        current_repetition: Optional[int] = None,
    ) -> Optional[TestRunExecution]:
        """Update execution progress."""
        stmt = select(TestRunExecutionORM).where(
            TestRunExecutionORM.id == execution_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if current_loadprofile is not None:
            orm.current_loadprofile = current_loadprofile.value
        if current_repetition is not None:
            orm.current_repetition = current_repetition

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def delete_by_id(self, execution_id: UUID) -> bool:
        """Delete execution by ID. Returns True if deleted."""
        stmt = select(TestRunExecutionORM).where(
            TestRunExecutionORM.id == execution_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return False

        await self._session.delete(orm)
        await self._session.flush()
        return True


class ExecutionWorkflowStateRepository:
    """Repository for ExecutionWorkflowState CRUD operations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _parse_error_history(self, error_history: list) -> list[ErrorRecord]:
        """Parse error history JSON into ErrorRecord list."""
        records = []
        for entry in error_history:
            records.append(
                ErrorRecord(
                    timestamp=datetime.fromisoformat(entry["timestamp"]),
                    phase=ExecutionPhase(entry["phase"]),
                    state=PhaseState(entry["state"]),
                    error_message=entry["error_message"],
                    retry_count=entry["retry_count"],
                )
            )
        return records

    def _orm_to_model(self, orm: ExecutionWorkflowStateORM) -> ExecutionWorkflowState:
        """Convert ExecutionWorkflowStateORM to ExecutionWorkflowState model."""
        return ExecutionWorkflowState(
            id=orm.id,
            test_run_execution_id=orm.test_run_execution_id,
            target_id=orm.target_id,
            loadprofile=LoadProfile(orm.loadprofile),
            runcount=orm.runcount,
            base_baseline_id=orm.base_baseline_id,
            initial_baseline_id=orm.initial_baseline_id,
            upgrade_baseline_id=orm.upgrade_baseline_id,
            current_phase=ExecutionPhase(orm.current_phase),
            phase_state=PhaseState(orm.phase_state),
            retry_count=orm.retry_count,
            max_retries=orm.max_retries,
            error_history=self._parse_error_history(orm.error_history or []),
            phase_started_at=orm.phase_started_at,
            phase_completed_at=orm.phase_completed_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def _error_record_to_dict(self, record: ErrorRecord) -> dict:
        """Convert ErrorRecord to dictionary for JSON storage."""
        return {
            "timestamp": record.timestamp.isoformat(),
            "phase": record.phase.value,
            "state": record.state.value,
            "error_message": record.error_message,
            "retry_count": record.retry_count,
        }

    async def create(
        self,
        test_run_execution_id: UUID,
        target_id: int,
        loadprofile: LoadProfile,
        runcount: int,
        current_phase: ExecutionPhase,
        phase_state: PhaseState,
        base_baseline_id: Optional[int] = None,
        initial_baseline_id: Optional[int] = None,
        upgrade_baseline_id: Optional[int] = None,
        max_retries: int = 3,
    ) -> ExecutionWorkflowState:
        """Create a new execution workflow state."""
        orm = ExecutionWorkflowStateORM(
            test_run_execution_id=test_run_execution_id,
            target_id=target_id,
            loadprofile=loadprofile.value,
            runcount=runcount,
            base_baseline_id=base_baseline_id,
            initial_baseline_id=initial_baseline_id,
            upgrade_baseline_id=upgrade_baseline_id,
            current_phase=current_phase.value,
            phase_state=phase_state.value,
            max_retries=max_retries,
            error_history=[],
            phase_started_at=datetime.utcnow(),
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_id(self, state_id: int) -> Optional[ExecutionWorkflowState]:
        """Get workflow state by ID."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_by_execution_id(
        self,
        execution_id: UUID,
    ) -> list[ExecutionWorkflowState]:
        """Get all workflow states for an execution."""
        stmt = (
            select(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.test_run_execution_id == execution_id)
            .order_by(
                ExecutionWorkflowStateORM.target_id,
                ExecutionWorkflowStateORM.runcount,
            )
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_current_for_target(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: LoadProfile,
    ) -> Optional[ExecutionWorkflowState]:
        """Get current workflow state for a target in an execution."""
        stmt = (
            select(ExecutionWorkflowStateORM)
            .where(
                and_(
                    ExecutionWorkflowStateORM.test_run_execution_id == execution_id,
                    ExecutionWorkflowStateORM.target_id == target_id,
                    ExecutionWorkflowStateORM.loadprofile == loadprofile.value,
                )
            )
            .order_by(ExecutionWorkflowStateORM.runcount.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update_phase(
        self,
        state_id: int,
        current_phase: ExecutionPhase,
        phase_state: PhaseState,
    ) -> Optional[ExecutionWorkflowState]:
        """Update the current phase and state."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        # If phase changed, update timing
        if orm.current_phase != current_phase.value:
            orm.phase_completed_at = datetime.utcnow()
            orm.phase_started_at = datetime.utcnow()

        orm.current_phase = current_phase.value
        orm.phase_state = phase_state.value

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def record_error(
        self,
        state_id: int,
        error_message: str,
    ) -> Optional[ExecutionWorkflowState]:
        """Record an error and increment retry count."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        orm.retry_count += 1

        # Add to error history
        error_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "phase": orm.current_phase,
            "state": orm.phase_state,
            "error_message": error_message,
            "retry_count": orm.retry_count,
        }
        orm.error_history = [*orm.error_history, error_record]

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def complete_phase(
        self,
        state_id: int,
    ) -> Optional[ExecutionWorkflowState]:
        """Mark current phase as completed."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        orm.phase_state = PhaseState.COMPLETED.value
        orm.phase_completed_at = datetime.utcnow()

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def delete_by_execution_id(self, execution_id: UUID) -> int:
        """Delete all workflow states for an execution. Returns count deleted."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.test_run_execution_id == execution_id
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        count = len(orms)
        for orm in orms:
            await self._session.delete(orm)

        await self._session.flush()
        return count

    # =========================================================================
    # Package List Methods
    # =========================================================================

    async def update_package_list(
        self,
        state_id: int,
        phase: str,
        package_list: list[dict],
    ) -> None:
        """Update package list for a phase."""
        field_name = f"{phase}_package_lst"
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(**{field_name: package_list}, updated_at=datetime.utcnow())
        )
        await self._session.execute(stmt)

    async def update_measured_list(
        self,
        state_id: int,
        phase: str,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update measured package list for a phase."""
        measured_field = f"{phase}_package_lst_measured"
        matched_field = f"{phase}_packages_matched"
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(
                **{measured_field: measured_list, matched_field: all_matched},
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)

    async def update_jmeter_package_list(
        self,
        state_id: int,
        package_list: list[dict],
    ) -> None:
        """Update JMeter package list."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(jmeter_package_lst=package_list, updated_at=datetime.utcnow())
        )
        await self._session.execute(stmt)

    async def update_jmeter_measured_list(
        self,
        state_id: int,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update JMeter measured list."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(
                jmeter_package_lst_measured=measured_list,
                jmeter_packages_matched=all_matched,
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)

    # =========================================================================
    # Result Blob Methods
    # =========================================================================

    async def update_phase_result_blobs(
        self,
        state_id: int,
        phase: str,
        result_blob: Optional[bytes] = None,
        stats_blob: Optional[bytes] = None,
        execution_blob: Optional[bytes] = None,
        logs_blob: Optional[bytes] = None,
    ) -> None:
        """Update result blobs for a phase."""
        values = {"updated_at": datetime.utcnow()}

        if result_blob is not None:
            values[f"{phase}_device_result_blob"] = result_blob
        if stats_blob is not None:
            values[f"{phase}_device_stats_blob"] = stats_blob
        if execution_blob is not None:
            values[f"{phase}_device_execution_blob"] = execution_blob
        if logs_blob is not None:
            values[f"{phase}_device_execution_logs_blob"] = logs_blob

        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def update_jmeter_result_blobs(
        self,
        state_id: int,
        result_blob: Optional[bytes] = None,
        stats_blob: Optional[bytes] = None,
        execution_blob: Optional[bytes] = None,
        logs_blob: Optional[bytes] = None,
    ) -> None:
        """Update JMeter result blobs."""
        values = {"updated_at": datetime.utcnow()}

        if result_blob is not None:
            values["jmeter_device_result_blob"] = result_blob
        if stats_blob is not None:
            values["jmeter_device_stats_blob"] = stats_blob
        if execution_blob is not None:
            values["jmeter_device_execution_blob"] = execution_blob
        if logs_blob is not None:
            values["jmeter_device_execution_logs_blob"] = logs_blob

        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == state_id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def increment_retry_count(
        self,
        state_id: int,
    ) -> int:
        """Increment retry count and return new value."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return 0

        new_count = orm.retry_count + 1
        orm.retry_count = new_count
        await self._session.flush()

        return new_count

    async def get_orm_by_id(self, state_id: int) -> Optional[ExecutionWorkflowStateORM]:
        """Get raw ORM object by ID (for direct access to all fields)."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.id == state_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
