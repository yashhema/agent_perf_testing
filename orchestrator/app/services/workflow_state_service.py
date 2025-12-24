"""Service for managing workflow state transitions and updates."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.repositories.workflow_state_repository import WorkflowStateRepository
from app.models.orm import ExecutionWorkflowStateORM
from app.models.enums import WorkflowState, PhaseState
from app.results.models import PhaseResults


@dataclass
class PhaseConfig:
    """Configuration for a phase."""

    phase: str  # "base", "initial", "upgrade"
    baseline_id: Optional[int]
    package_list: list[dict]
    revert_required: bool = True


class WorkflowStateService:
    """
    Service for managing execution workflow state.

    Handles:
    - State transitions (following WorkflowState enum)
    - Phase tracking (base → initial → upgrade)
    - Package list management
    - Result storage
    - Error handling and retry logic
    """

    def __init__(
        self,
        workflow_repo: WorkflowStateRepository,
        max_retries: int = 3,
    ):
        self.workflow_repo = workflow_repo
        self.max_retries = max_retries

    # =========================================================================
    # State Transitions
    # =========================================================================

    async def transition_to_state(
        self,
        workflow_state_id: int,
        new_state: WorkflowState,
    ) -> None:
        """
        Transition to a new workflow state.

        Args:
            workflow_state_id: Workflow state ID
            new_state: New WorkflowState
        """
        await self.workflow_repo.update_current_state(
            workflow_state_id=workflow_state_id,
            cur_state=new_state.value,
        )

    async def start_phase(
        self,
        workflow_state_id: int,
        phase: str,
        phase_state: PhaseState,
    ) -> None:
        """
        Start a new phase.

        Args:
            workflow_state_id: Workflow state ID
            phase: Phase name ("base", "initial", "upgrade")
            phase_state: Initial phase state
        """
        await self.workflow_repo.start_phase(
            workflow_state_id=workflow_state_id,
            phase=phase,
        )
        await self.workflow_repo.update_phase_state(
            workflow_state_id=workflow_state_id,
            current_phase=phase,
            phase_state=phase_state.value,
        )

    async def update_phase_state(
        self,
        workflow_state_id: int,
        phase_state: str,
    ) -> None:
        """Update phase state without changing current phase."""
        workflow_state = await self.workflow_repo.get_by_id(workflow_state_id)
        if workflow_state:
            await self.workflow_repo.update_phase_state(
                workflow_state_id=workflow_state_id,
                current_phase=workflow_state.current_phase or "",
                phase_state=phase_state,
            )

    async def complete_phase(
        self,
        workflow_state_id: int,
    ) -> None:
        """Mark current phase as completed."""
        await self.workflow_repo.complete_phase(workflow_state_id=workflow_state_id)

    # =========================================================================
    # Package List Management
    # =========================================================================

    async def set_phase_package_list(
        self,
        workflow_state_id: int,
        phase: str,
        package_list: list[dict],
    ) -> None:
        """
        Set the package list for a phase.

        Args:
            workflow_state_id: Workflow state ID
            phase: Phase name
            package_list: Package list for the phase
        """
        await self.workflow_repo.update_phase_package_list(
            workflow_state_id=workflow_state_id,
            phase=phase,
            package_list=package_list,
        )

    async def set_jmeter_package_list(
        self,
        workflow_state_id: int,
        package_list: list[dict],
    ) -> None:
        """Set the JMeter package list."""
        await self.workflow_repo.update_jmeter_package_list(
            workflow_state_id=workflow_state_id,
            package_list=package_list,
        )

    async def update_measured_list(
        self,
        workflow_state_id: int,
        phase: str,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """
        Update the measured package list for a phase.

        Args:
            workflow_state_id: Workflow state ID
            phase: Phase name
            measured_list: Measured package list
            all_matched: Whether all packages matched
        """
        await self.workflow_repo.update_phase_measured_list(
            workflow_state_id=workflow_state_id,
            phase=phase,
            measured_list=measured_list,
            all_matched=all_matched,
        )

    async def update_jmeter_measured_list(
        self,
        workflow_state_id: int,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update the JMeter measured list."""
        await self.workflow_repo.update_jmeter_measured_list(
            workflow_state_id=workflow_state_id,
            measured_list=measured_list,
            all_matched=all_matched,
        )

    # =========================================================================
    # Result Storage
    # =========================================================================

    async def store_phase_results(
        self,
        workflow_state_id: int,
        phase_results: PhaseResults,
    ) -> None:
        """
        Store phase results (compressed blobs).

        Args:
            workflow_state_id: Workflow state ID
            phase_results: PhaseResults with compressed blobs
        """
        # Store target device results
        await self.workflow_repo.update_phase_result_blobs(
            workflow_state_id=workflow_state_id,
            phase=phase_results.phase,
            result_blob=phase_results.result_blob,
            stats_blob=phase_results.stats_blob,
            execution_blob=phase_results.execution_blob,
            logs_blob=phase_results.logs_blob,
        )

        # Store JMeter results
        await self.workflow_repo.update_jmeter_result_blobs(
            workflow_state_id=workflow_state_id,
            result_blob=phase_results.jmeter_result_blob,
            stats_blob=phase_results.jmeter_stats_blob,
            execution_blob=phase_results.jmeter_execution_blob,
            logs_blob=phase_results.jmeter_logs_blob,
        )

    # =========================================================================
    # Error Handling
    # =========================================================================

    async def record_error(
        self,
        workflow_state_id: int,
        error_type: str,
        error_message: str,
        phase: Optional[str] = None,
    ) -> None:
        """
        Record an error in the error history.

        Args:
            workflow_state_id: Workflow state ID
            error_type: Type of error
            error_message: Error message
            phase: Phase where error occurred
        """
        await self.workflow_repo.add_error_to_history(
            workflow_state_id=workflow_state_id,
            error_type=error_type,
            error_message=error_message,
            phase=phase,
        )

        # Also update phase state to error
        await self.update_phase_state(
            workflow_state_id=workflow_state_id,
            phase_state=PhaseState.ERROR.value,
        )

    async def increment_retry_count(
        self,
        workflow_state_id: int,
    ) -> int:
        """Increment retry count and return new value."""
        return await self.workflow_repo.increment_retry_count(
            workflow_state_id=workflow_state_id,
        )

    async def can_retry(
        self,
        workflow_state_id: int,
    ) -> bool:
        """Check if retry is allowed."""
        workflow_state = await self.workflow_repo.get_by_id(workflow_state_id)
        if not workflow_state:
            return False

        return workflow_state.retry_count < workflow_state.max_retries

    async def prepare_for_retry(
        self,
        workflow_state_id: int,
    ) -> bool:
        """
        Prepare workflow state for retry.

        Returns:
            True if retry is allowed, False if max retries exceeded
        """
        can_retry = await self.can_retry(workflow_state_id)
        if not can_retry:
            return False

        await self.workflow_repo.reset_for_retry(workflow_state_id)
        return True

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_workflow_state(
        self,
        workflow_state_id: int,
    ) -> Optional[ExecutionWorkflowStateORM]:
        """Get workflow state by ID."""
        return await self.workflow_repo.get_by_id(workflow_state_id)

    async def get_by_execution_and_target(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: str,
        runcount: int = 0,
    ) -> Optional[ExecutionWorkflowStateORM]:
        """Get workflow state by execution, target, and loadprofile."""
        return await self.workflow_repo.get_by_execution_and_target(
            execution_id=execution_id,
            target_id=target_id,
            loadprofile=loadprofile,
            runcount=runcount,
        )

    async def get_active_for_execution(
        self,
        execution_id: UUID,
    ) -> list[ExecutionWorkflowStateORM]:
        """Get all workflow states for an execution."""
        return await self.workflow_repo.get_active_for_execution(execution_id)

    # =========================================================================
    # Workflow State Creation
    # =========================================================================

    async def create_workflow_state(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: str,
        runcount: int = 0,
        base_config: Optional[PhaseConfig] = None,
        initial_config: Optional[PhaseConfig] = None,
        upgrade_config: Optional[PhaseConfig] = None,
    ) -> ExecutionWorkflowStateORM:
        """
        Create a new workflow state with phase configurations.

        Args:
            execution_id: Test run execution ID
            target_id: Target device ID
            loadprofile: Load profile (low, medium, high)
            runcount: Run count (for repetitions)
            base_config: Base phase configuration
            initial_config: Initial phase configuration
            upgrade_config: Upgrade phase configuration

        Returns:
            Created ExecutionWorkflowStateORM
        """
        # Determine if upgrade needs revert
        upgrade_revert_required = True
        if upgrade_config and not upgrade_config.revert_required:
            upgrade_revert_required = False

        workflow_state = await self.workflow_repo.create_workflow_state(
            execution_id=execution_id,
            target_id=target_id,
            loadprofile=loadprofile,
            runcount=runcount,
            base_baseline_id=base_config.baseline_id if base_config else None,
            initial_baseline_id=initial_config.baseline_id if initial_config else None,
            upgrade_baseline_id=upgrade_config.baseline_id if upgrade_config else None,
            upgrade_revert_required=upgrade_revert_required,
        )

        # Set package lists
        if base_config and base_config.package_list:
            await self.set_phase_package_list(
                workflow_state_id=workflow_state.id,
                phase="base",
                package_list=base_config.package_list,
            )

        if initial_config and initial_config.package_list:
            await self.set_phase_package_list(
                workflow_state_id=workflow_state.id,
                phase="initial",
                package_list=initial_config.package_list,
            )

        if upgrade_config and upgrade_config.package_list:
            await self.set_phase_package_list(
                workflow_state_id=workflow_state.id,
                phase="upgrade",
                package_list=upgrade_config.package_list,
            )

        return workflow_state

    # =========================================================================
    # Phase Helpers
    # =========================================================================

    def get_next_phase(
        self,
        current_phase: Optional[str],
        has_initial: bool = True,
        has_upgrade: bool = False,
    ) -> Optional[str]:
        """
        Get the next phase after current.

        Args:
            current_phase: Current phase or None
            has_initial: Whether initial phase is configured
            has_upgrade: Whether upgrade phase is configured

        Returns:
            Next phase name or None if complete
        """
        if current_phase is None:
            return "base"

        if current_phase == "base":
            if has_initial:
                return "initial"
            elif has_upgrade:
                return "upgrade"
            return None

        if current_phase == "initial":
            if has_upgrade:
                return "upgrade"
            return None

        if current_phase == "upgrade":
            return None

        return None

    def get_phase_baseline_id(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        phase: str,
    ) -> Optional[int]:
        """Get baseline ID for a phase."""
        if phase == "base":
            return workflow_state.base_baseline_id
        elif phase == "initial":
            return workflow_state.initial_baseline_id
        elif phase == "upgrade":
            return workflow_state.upgrade_baseline_id
        return None

    def get_phase_package_list(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        phase: str,
    ) -> list[dict]:
        """Get package list for a phase."""
        if phase == "base":
            return workflow_state.base_package_lst or []
        elif phase == "initial":
            return workflow_state.initial_package_lst or []
        elif phase == "upgrade":
            return workflow_state.upgrade_package_lst or []
        return []
