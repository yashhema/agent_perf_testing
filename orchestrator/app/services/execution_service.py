"""Service layer for TestRunExecution operations."""

from typing import Optional
from uuid import UUID

from app.models.application import (
    TestRunExecution,
    ExecutionWorkflowState,
    CreateExecutionResult,
    ActionResult,
    ActiveExecutionInfo,
)
from app.models.enums import (
    RunMode,
    ExecutionStatus,
    LoadProfile,
    ExecutionPhase,
    PhaseState,
)
from app.models.exceptions import (
    InvalidSnapshotCombinationError,
    validate_snapshot_combination,
)
from app.repositories.execution_repository import (
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
)
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository
from app.services.state_machine import ExecutionStateMachine


class ExecutionService:
    """Service for TestRunExecution business logic."""

    def __init__(
        self,
        execution_repository: TestRunExecutionRepository,
        workflow_state_repository: ExecutionWorkflowStateRepository,
        test_run_repository: TestRunRepository,
        test_run_target_repository: TestRunTargetRepository,
    ):
        self._exec_repo = execution_repository
        self._workflow_repo = workflow_state_repository
        self._test_run_repo = test_run_repository
        self._target_repo = test_run_target_repository

    async def create_execution(
        self,
        test_run_id: int,
        run_mode: RunMode = RunMode.CONTINUOUS,
        immediate_run: bool = False,
    ) -> CreateExecutionResult:
        """
        Create a new test run execution.

        Args:
            test_run_id: The test run ID to execute.
            run_mode: The run mode (continuous or stepped).
            immediate_run: Whether to start calibration immediately.

        Returns:
            CreateExecutionResult with execution ID and status.
        """
        # Verify test run exists
        test_run = await self._test_run_repo.get_by_id(test_run_id)
        if test_run is None:
            return CreateExecutionResult(
                success=False,
                execution_id=None,
                message=f"Test run with ID {test_run_id} not found",
            )

        # Check for existing active execution
        active = await self._exec_repo.get_active_by_test_run_id(test_run_id)
        if active is not None:
            return CreateExecutionResult(
                success=False,
                execution_id=None,
                message=f"Test run {test_run_id} already has an active execution: {active.id}",
            )

        # Get targets for this test run
        targets = await self._target_repo.get_by_test_run_id(test_run_id)
        if not targets:
            return CreateExecutionResult(
                success=False,
                execution_id=None,
                message=f"Test run {test_run_id} has no targets configured",
            )

        # Validate snapshot combinations for each target
        # TODO: Also need to check scenario_cases for upgrade_package_grp_id
        for target in targets:
            try:
                validate_snapshot_combination(
                    base_snapshot_id=target.base_snapshot_id,
                    initial_snapshot_id=target.initial_snapshot_id,
                    upgrade_snapshot_id=target.upgrade_snapshot_id,
                    has_upgrade_package=False,  # TODO: Get from scenario_cases
                    target_id=target.target_id,
                )
            except InvalidSnapshotCombinationError as e:
                return CreateExecutionResult(
                    success=False,
                    execution_id=None,
                    message=f"Invalid snapshot configuration for target {target.target_id}: {e.message}",
                )

        # Create the execution
        execution = await self._exec_repo.create(
            test_run_id=test_run_id,
            run_mode=run_mode,
        )

        # If immediate run, start calibration
        calibration_started = False
        if immediate_run:
            await self._exec_repo.update_status(
                execution.id,
                ExecutionStatus.CALIBRATING,
            )
            calibration_started = True

            # Create initial workflow states for each target and load profile
            for target in targets:
                for loadprofile in test_run.req_loadprofile:
                    await self._workflow_repo.create(
                        test_run_execution_id=execution.id,
                        target_id=target.target_id,
                        loadprofile=loadprofile,
                        runcount=1,
                        current_phase=ExecutionPhase.CALIBRATION,
                        phase_state=PhaseState.PENDING,
                        base_baseline_id=target.base_baseline_id,
                        initial_baseline_id=target.initial_baseline_id,
                        upgrade_baseline_id=target.upgrade_baseline_id,
                    )

        return CreateExecutionResult(
            success=True,
            execution_id=execution.id,
            message="Execution created successfully",
            calibration_started=calibration_started,
        )

    async def get_execution(self, execution_id: UUID) -> Optional[TestRunExecution]:
        """Get an execution by ID."""
        return await self._exec_repo.get_by_id(execution_id)

    async def get_execution_with_states(
        self,
        execution_id: UUID,
    ) -> Optional[TestRunExecution]:
        """Get an execution with workflow states."""
        return await self._exec_repo.get_with_workflow_states(execution_id)

    async def list_executions(self, test_run_id: int) -> list[TestRunExecution]:
        """List all executions for a test run."""
        return await self._exec_repo.get_by_test_run_id(test_run_id)

    async def list_active_executions(self) -> list[TestRunExecution]:
        """List all active executions."""
        return await self._exec_repo.get_all_active()

    async def get_active_execution_info(self) -> list[ActiveExecutionInfo]:
        """Get summary info for all active executions."""
        executions = await self._exec_repo.get_all_active()
        info_list = []

        for execution in executions:
            test_run = await self._test_run_repo.get_by_id(execution.test_run_id)
            test_run_name = test_run.name if test_run else "Unknown"

            info_list.append(
                ActiveExecutionInfo(
                    execution_id=execution.id,
                    test_run_id=execution.test_run_id,
                    test_run_name=test_run_name,
                    status=execution.status,
                    run_mode=execution.run_mode,
                    current_loadprofile=execution.current_loadprofile,
                    current_repetition=execution.current_repetition,
                    started_at=execution.started_at,
                )
            )

        return info_list

    async def execute_action(
        self,
        execution_id: UUID,
        action: str,
    ) -> ActionResult:
        """
        Execute an action on a test run execution.

        Args:
            execution_id: The execution ID.
            action: The action to perform (continue, pause, abandon, status).

        Returns:
            ActionResult with success status and new state.
        """
        # Get the execution
        execution = await self._exec_repo.get_by_id(execution_id)
        if execution is None:
            return ActionResult(
                success=False,
                message=f"Execution with ID {execution_id} not found",
            )

        # Validate the action using state machine
        transition = ExecutionStateMachine.validate_transition(
            execution.status,
            action,
        )

        if not transition.success:
            return ActionResult(
                success=False,
                message=transition.message,
            )

        # Status action doesn't change state
        if action == "status":
            return ActionResult(
                success=True,
                message=f"Status: {execution.status.value}",
                new_status=execution.status,
            )

        # Update the status
        updated = await self._exec_repo.update_status(
            execution_id,
            transition.new_status,
        )

        if updated is None:
            return ActionResult(
                success=False,
                message="Failed to update execution status",
            )

        return ActionResult(
            success=True,
            message=transition.message,
            new_status=updated.status,
        )

    async def update_progress(
        self,
        execution_id: UUID,
        current_loadprofile: Optional[LoadProfile] = None,
        current_repetition: Optional[int] = None,
    ) -> Optional[TestRunExecution]:
        """Update execution progress."""
        return await self._exec_repo.update_progress(
            execution_id,
            current_loadprofile,
            current_repetition,
        )

    async def complete_execution(
        self,
        execution_id: UUID,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> Optional[TestRunExecution]:
        """
        Mark an execution as complete.

        Args:
            execution_id: The execution ID.
            success: Whether the execution completed successfully.
            error_message: Optional error message if not successful.

        Returns:
            The updated execution.
        """
        status = ExecutionStatus.ENDED if success else ExecutionStatus.ENDED_ERROR
        return await self._exec_repo.update_status(
            execution_id,
            status,
            error_message,
        )

    async def abandon_execution(
        self,
        execution_id: UUID,
        reason: Optional[str] = None,
    ) -> Optional[TestRunExecution]:
        """
        Abandon an execution.

        Args:
            execution_id: The execution ID.
            reason: Optional reason for abandoning.

        Returns:
            The updated execution.
        """
        return await self._exec_repo.update_status(
            execution_id,
            ExecutionStatus.ABANDONED,
            reason,
        )

    # ============================================================
    # Workflow State Operations
    # ============================================================

    async def get_workflow_states(
        self,
        execution_id: UUID,
    ) -> list[ExecutionWorkflowState]:
        """Get all workflow states for an execution."""
        return await self._workflow_repo.get_by_execution_id(execution_id)

    async def get_current_workflow_state(
        self,
        execution_id: UUID,
        target_id: int,
        loadprofile: LoadProfile,
    ) -> Optional[ExecutionWorkflowState]:
        """Get current workflow state for a target."""
        return await self._workflow_repo.get_current_for_target(
            execution_id,
            target_id,
            loadprofile,
        )

    async def update_workflow_phase(
        self,
        state_id: int,
        current_phase: ExecutionPhase,
        phase_state: PhaseState,
    ) -> Optional[ExecutionWorkflowState]:
        """Update workflow phase and state."""
        return await self._workflow_repo.update_phase(
            state_id,
            current_phase,
            phase_state,
        )

    async def record_workflow_error(
        self,
        state_id: int,
        error_message: str,
    ) -> Optional[ExecutionWorkflowState]:
        """Record an error in the workflow state."""
        return await self._workflow_repo.record_error(state_id, error_message)

    async def complete_workflow_phase(
        self,
        state_id: int,
    ) -> Optional[ExecutionWorkflowState]:
        """Mark a workflow phase as complete."""
        return await self._workflow_repo.complete_phase(state_id)
