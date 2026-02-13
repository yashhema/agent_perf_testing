"""Repository for ExecutionWorkflowState CRUD operations."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ExecutionWorkflowStateORM
from app.repositories.base import BaseRepository


class WorkflowStateRepository(BaseRepository[ExecutionWorkflowStateORM, ExecutionWorkflowStateORM]):
    """Repository for ExecutionWorkflowState operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ExecutionWorkflowStateORM)

    async def get_by_execution_and_target(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: str,
        runcount: int = 0,
    ) -> Optional[ExecutionWorkflowStateORM]:
        """Get workflow state by execution, target, loadprofile, and runcount."""
        stmt = select(ExecutionWorkflowStateORM).where(
            and_(
                ExecutionWorkflowStateORM.test_run_execution_id == execution_id,
                ExecutionWorkflowStateORM.target_id == target_id,
                ExecutionWorkflowStateORM.loadprofile == loadprofile,
                ExecutionWorkflowStateORM.runcount == runcount,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_device_identifier(
        self,
        device_ip: Optional[str] = None,
        device_fqdn: Optional[str] = None,
        device_hostname: Optional[str] = None,
    ) -> Optional[ExecutionWorkflowStateORM]:
        """
        Get workflow state by device identifier (for runner queries).

        Joins with targets/servers table to find by IP/FQDN/hostname.
        Returns the most recent active workflow state.
        """
        # This would need to join with ServerORM or TargetORM
        # For now, return None - implementation depends on exact schema
        # In practice, you'd query targets by IP/hostname, then get workflow state
        return None

    async def get_active_for_execution(
        self,
        execution_id: UUID,
    ) -> list[ExecutionWorkflowStateORM]:
        """Get all active workflow states for an execution."""
        stmt = select(ExecutionWorkflowStateORM).where(
            ExecutionWorkflowStateORM.test_run_execution_id == execution_id
        ).order_by(
            ExecutionWorkflowStateORM.loadprofile,
            ExecutionWorkflowStateORM.target_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_workflow_state(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: str,
        runcount: int = 0,
        base_baseline_id: Optional[int] = None,
        initial_baseline_id: Optional[int] = None,
        upgrade_baseline_id: Optional[int] = None,
        upgrade_revert_required: bool = True,
    ) -> ExecutionWorkflowStateORM:
        """Create a new workflow state."""
        workflow_state = ExecutionWorkflowStateORM(
            test_run_execution_id=execution_id,
            target_id=target_id,
            loadprofile=loadprofile,
            runcount=runcount,
            cur_state="norun",
            base_baseline_id=base_baseline_id,
            initial_baseline_id=initial_baseline_id,
            upgrade_baseline_id=upgrade_baseline_id,
            upgrade_revert_required=upgrade_revert_required,
        )
        self.session.add(workflow_state)
        await self.session.flush()
        return workflow_state

    async def update_current_state(
        self,
        workflow_state_id: int,
        cur_state: str,
    ) -> None:
        """Update the current workflow state."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                cur_state=cur_state,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_phase_state(
        self,
        workflow_state_id: int,
        current_phase: str,
        phase_state: str,
    ) -> None:
        """Update current phase and phase state."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                current_phase=current_phase,
                phase_state=phase_state,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_phase_package_list(
        self,
        workflow_state_id: int,
        phase: str,
        package_list: list[dict],
    ) -> None:
        """Update package list for a phase."""
        field_name = f"{phase}_package_lst"
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                **{field_name: package_list},
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_phase_measured_list(
        self,
        workflow_state_id: int,
        phase: str,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update measured package list for a phase."""
        measured_field = f"{phase}_package_lst_measured"
        matched_field = f"{phase}_packages_matched"
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                **{
                    measured_field: measured_list,
                    matched_field: all_matched,
                },
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_phase_result_blobs(
        self,
        workflow_state_id: int,
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
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(**values)
        )
        await self.session.execute(stmt)

    async def update_jmeter_package_list(
        self,
        workflow_state_id: int,
        package_list: list[dict],
    ) -> None:
        """Update JMeter package list."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                jmeter_package_lst=package_list,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_jmeter_measured_list(
        self,
        workflow_state_id: int,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update JMeter measured list."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                jmeter_package_lst_measured=measured_list,
                jmeter_packages_matched=all_matched,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def update_jmeter_result_blobs(
        self,
        workflow_state_id: int,
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
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(**values)
        )
        await self.session.execute(stmt)

    async def increment_retry_count(
        self,
        workflow_state_id: int,
    ) -> int:
        """Increment retry count and return new value."""
        # Get current retry count
        workflow_state = await self.get_by_id(workflow_state_id)
        if not workflow_state:
            return 0

        new_count = workflow_state.retry_count + 1

        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                retry_count=new_count,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

        return new_count

    async def add_error_to_history(
        self,
        workflow_state_id: int,
        error_type: str,
        error_message: str,
        phase: Optional[str] = None,
    ) -> None:
        """Add an error to the error history."""
        workflow_state = await self.get_by_id(workflow_state_id)
        if not workflow_state:
            return

        error_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "error_type": error_type,
            "error_message": error_message,
            "phase": phase,
            "retry_count": workflow_state.retry_count,
        }

        error_history = list(workflow_state.error_history or [])
        error_history.append(error_entry)

        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                error_history=error_history,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def start_phase(
        self,
        workflow_state_id: int,
        phase: str,
    ) -> None:
        """Mark phase as started."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                current_phase=phase,
                phase_started_at=datetime.utcnow(),
                phase_completed_at=None,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def complete_phase(
        self,
        workflow_state_id: int,
    ) -> None:
        """Mark current phase as completed."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                phase_completed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)

    async def reset_for_retry(
        self,
        workflow_state_id: int,
    ) -> None:
        """Reset phase state for retry (keep error history)."""
        stmt = (
            update(ExecutionWorkflowStateORM)
            .where(ExecutionWorkflowStateORM.id == workflow_state_id)
            .values(
                phase_state=None,
                phase_started_at=None,
                phase_completed_at=None,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.execute(stmt)
