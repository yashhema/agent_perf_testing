"""Execution controller for managing test runs with proper state handling.

This is the main entry point for running tests. It:
1. Creates/resumes TestRunExecution records
2. Creates ExecutionWorkflowState records for each target/loadprofile
3. Respects pause_requested and run_mode
4. Updates calibration results in DB
5. Tracks progress and handles errors properly
6. Coordinates CalibrationExecutor and TestExecutor

The executors (CalibrationExecutor, TestExecutor) handle the actual work.
This controller handles the state management around them.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Awaitable
from uuid import UUID
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    TestRunExecutionORM,
    ExecutionWorkflowStateORM,
    CalibrationResultORM,
    TestRunORM,
    TestRunTargetORM,
)
from app.models.enums import (
    ExecutionStatus,
    RunMode,
    LoadProfile,
    PhaseState,
    WorkflowState,
    CalibrationStatus,
)
from app.services.execution_service import ExecutionService
from app.services.workflow_state_service import WorkflowStateService, PhaseConfig
from app.repositories.execution_repository import (
    TestRunExecutionRepository,
    ExecutionWorkflowStateRepository,
)
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository
from app.repositories.calibration_repository import CalibrationRepository
from app.repositories.server_repository import ServerRepository
from app.packages.resolver import PackageResolver

from app.orchestration.calibration_executor import (
    CalibrationExecutor,
    CalibrationExecutionConfig,
    CalibrationTargetConfig,
    CalibrationExecutionResult,
)
from app.orchestration.test_executor import (
    TestExecutor,
    TestExecutionConfig,
    TargetConfig,
    TestExecutionResult,
)
from app.orchestration.environment import (
    EnvironmentConfig,
    get_environment_config,
)
from app.orchestration.managers import (
    TestExecutorFactory,
    CalibrationExecutorFactory,
)


logger = logging.getLogger(__name__)


class ControllerState(str, Enum):
    """Controller state."""
    IDLE = "idle"
    CALIBRATING = "calibrating"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ControllerProgress:
    """Progress information for UI/API."""
    state: ControllerState
    current_phase: Optional[str] = None
    current_loadprofile: Optional[str] = None
    current_repetition: int = 0
    total_targets: int = 0
    completed_targets: int = 0
    error_message: Optional[str] = None


class ExecutionController:
    """
    Controls test execution with proper state management.

    Responsibilities:
    1. Create/resume TestRunExecution
    2. Create ExecutionWorkflowState for each target/loadprofile
    3. Check pause_requested before each stage
    4. Respect run_mode (continuous vs step)
    5. Update calibration results in DB
    6. Track progress in TestRunExecution
    7. Handle errors and retries
    8. Coordinate calibration and test execution
    """

    def __init__(
        self,
        db_session: AsyncSession,
        env_config: Optional[EnvironmentConfig] = None,
    ):
        self._session = db_session
        self._env_config = env_config or get_environment_config()

        # Repositories
        self._exec_repo = TestRunExecutionRepository(db_session)
        self._workflow_repo = ExecutionWorkflowStateRepository(db_session)
        self._test_run_repo = TestRunRepository(db_session)
        self._target_repo = TestRunTargetRepository(db_session)
        self._calibration_repo = CalibrationRepository(db_session)
        self._server_repo = ServerRepository(db_session)
        self._package_resolver = PackageResolver(db_session)

        # Services
        self._exec_service = ExecutionService(
            execution_repository=self._exec_repo,
            workflow_state_repository=self._workflow_repo,
            test_run_repository=self._test_run_repo,
            test_run_target_repository=self._target_repo,
        )

        # State
        self._execution: Optional[TestRunExecutionORM] = None
        self._test_run: Optional[TestRunORM] = None
        self._targets: list[TestRunTargetORM] = []
        self._workflow_states: dict[tuple[int, str], ExecutionWorkflowStateORM] = {}

        # Executors (created lazily)
        self._calibration_executor: Optional[CalibrationExecutor] = None
        self._test_executor: Optional[TestExecutor] = None

        # Control
        self._state = ControllerState.IDLE
        self._cancelled = False
        self._progress_callback: Optional[Callable[[ControllerProgress], Awaitable[None]]] = None

    @property
    def execution_id(self) -> Optional[UUID]:
        """Get current execution ID."""
        return self._execution.id if self._execution else None

    @property
    def state(self) -> ControllerState:
        """Get current controller state."""
        return self._state

    def set_progress_callback(
        self,
        callback: Callable[[ControllerProgress], Awaitable[None]],
    ) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    async def _report_progress(
        self,
        phase: Optional[str] = None,
        loadprofile: Optional[str] = None,
    ) -> None:
        """Report progress to callback."""
        if self._progress_callback:
            progress = ControllerProgress(
                state=self._state,
                current_phase=phase,
                current_loadprofile=loadprofile,
                current_repetition=self._execution.current_repetition if self._execution else 0,
                total_targets=len(self._targets),
            )
            await self._progress_callback(progress)

    # =========================================================================
    # Execution Lifecycle
    # =========================================================================

    async def start_execution(
        self,
        test_run_id: int,
        run_mode: RunMode = RunMode.CONTINUOUS,
        skip_calibration: bool = False,
    ) -> UUID:
        """
        Start a new test run execution.

        Args:
            test_run_id: Test run to execute
            run_mode: Continuous or step mode
            skip_calibration: Skip calibration (use existing)

        Returns:
            Execution ID
        """
        # Load test run and targets
        self._test_run = await self._test_run_repo.get_by_id(test_run_id)
        if not self._test_run:
            raise ValueError(f"Test run {test_run_id} not found")

        self._targets = await self._target_repo.get_by_test_run_id(test_run_id)
        if not self._targets:
            raise ValueError(f"Test run {test_run_id} has no targets")

        # Create execution via service
        result = await self._exec_service.create_execution(
            test_run_id=test_run_id,
            run_mode=run_mode,
            immediate_run=True,
        )

        if not result.success:
            raise RuntimeError(result.message)

        self._execution = await self._exec_repo.get_by_id(result.execution_id)

        # Create workflow states for each target and loadprofile
        await self._create_workflow_states()

        logger.info(f"Created execution {self._execution.id} for test run {test_run_id}")

        # Run execution
        if not skip_calibration:
            await self._run_calibration()

        await self._run_test_phases()

        return self._execution.id

    async def resume_execution(
        self,
        execution_id: UUID,
    ) -> None:
        """
        Resume a paused or interrupted execution.

        Queries current state from DB and continues from where left off.
        """
        self._execution = await self._exec_repo.get_by_id(execution_id)
        if not self._execution:
            raise ValueError(f"Execution {execution_id} not found")

        self._test_run = await self._test_run_repo.get_by_id(self._execution.test_run_id)
        self._targets = await self._target_repo.get_by_test_run_id(self._execution.test_run_id)

        # Load existing workflow states
        states = await self._workflow_repo.get_by_execution_id(execution_id)
        for state in states:
            key = (state.target_id, state.loadprofile)
            self._workflow_states[key] = state

        logger.info(f"Resuming execution {execution_id} from state {self._execution.status}")

        # Determine where to resume based on current state
        if self._execution.status == ExecutionStatus.CALIBRATING:
            await self._run_calibration()
            await self._run_test_phases()
        elif self._execution.status == ExecutionStatus.RUNNING:
            await self._run_test_phases()
        elif self._execution.status == ExecutionStatus.PAUSED:
            # Clear pause and continue
            await self._exec_repo.update_status(execution_id, ExecutionStatus.RUNNING)
            self._execution = await self._exec_repo.get_by_id(execution_id)
            await self._run_test_phases()

    async def _create_workflow_states(self) -> None:
        """Create workflow states for all target/loadprofile combinations with packages."""
        loadprofiles = self._test_run.req_loadprofile or ["low", "medium", "high"]

        for target in self._targets:
            # Resolve packages for this target (once per target, shared across loadprofiles)
            packages = await self._package_resolver.resolve_all_for_target(
                lab_id=self._test_run.lab_id,
                scenario_id=self._test_run.scenario_id,
                target_server_id=target.target_id,
                loadgen_server_id=target.loadgenerator_id,
                agent_id=None,  # TODO: Get from scenario_case if needed
            )

            for loadprofile in loadprofiles:
                # Check if state already exists
                existing = await self._workflow_repo.get_current_for_target(
                    self._execution.id,
                    target.target_id,
                    LoadProfile(loadprofile),
                )
                if existing:
                    self._workflow_states[(target.target_id, loadprofile)] = existing
                    continue

                # Create new state with package lists
                # Map from TestRunTarget's snapshot_id to WorkflowState's baseline_id
                state = await self._workflow_repo.create(
                    test_run_execution_id=self._execution.id,
                    target_id=target.target_id,
                    loadprofile=loadprofile,
                    runcount=1,
                    base_baseline_id=target.base_snapshot_id,
                    initial_baseline_id=target.initial_snapshot_id,
                    upgrade_baseline_id=target.upgrade_snapshot_id,
                )

                # Update with resolved packages
                state.jmeter_package_lst = packages["jmeter_packages"]
                state.base_package_lst = packages["base_packages"]
                state.initial_package_lst = packages["initial_packages"]
                state.upgrade_package_lst = packages["upgrade_packages"]

                self._workflow_states[(target.target_id, loadprofile)] = state

        await self._session.commit()
        logger.info(f"Created {len(self._workflow_states)} workflow states with packages")

    # =========================================================================
    # Pause/Cancel Handling
    # =========================================================================

    async def _check_pause_requested(self) -> bool:
        """
        Check if pause was requested.

        Returns True if should pause.
        """
        # Refresh execution from DB
        self._execution = await self._exec_repo.get_by_id(self._execution.id)

        if self._execution.pause_requested:
            logger.info("Pause requested - pausing execution")
            await self._exec_repo.update_status(
                self._execution.id,
                ExecutionStatus.PAUSED,
            )
            self._state = ControllerState.PAUSED
            return True

        return False

    async def _check_step_mode_pause(self, loadprofile: str) -> bool:
        """
        Check if should pause for step mode after completing a loadprofile.

        Returns True if should wait for continue.
        """
        if self._execution.run_mode != RunMode.STEPPED.value:
            return False

        logger.info(f"Step mode - pausing after {loadprofile}")
        await self._exec_repo.update_status(
            self._execution.id,
            ExecutionStatus.PAUSED,
        )
        self._state = ControllerState.PAUSED

        # Wait for continue or abandon
        while True:
            await asyncio.sleep(5)

            self._execution = await self._exec_repo.get_by_id(self._execution.id)

            if self._execution.status == ExecutionStatus.RUNNING:
                self._state = ControllerState.EXECUTING
                return False
            elif self._execution.status == ExecutionStatus.ABANDONED:
                return True

    async def request_pause(self) -> None:
        """Request execution to pause at next safe point."""
        if self._execution:
            self._execution.pause_requested = True
            await self._session.commit()

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._calibration_executor:
            await self._calibration_executor.cancel()
        if self._test_executor:
            await self._test_executor.cancel()

    # =========================================================================
    # Calibration
    # =========================================================================

    async def _run_calibration(self) -> None:
        """Run calibration for all targets."""
        self._state = ControllerState.CALIBRATING
        await self._report_progress()

        # Check for existing calibration results
        has_calibration = await self._check_existing_calibration()
        if has_calibration:
            logger.info("Using existing calibration results")
            await self._exec_repo.update_status(
                self._execution.id,
                ExecutionStatus.RUNNING,
            )
            return

        # Build calibration configs
        target_configs = await self._build_calibration_configs()

        # Create executor
        self._calibration_executor = CalibrationExecutorFactory.create_for_environment(
            target_configs=target_configs,
            env_config=self._env_config,
        )

        # Build execution config
        config = CalibrationExecutionConfig(
            test_run_id=self._test_run.id,
            scenario_id=self._test_run.scenario_id,
            targets=target_configs,
            profiles=self._test_run.req_loadprofile or ["low", "medium", "high"],
        )

        # Run calibration
        result = await self._calibration_executor.execute_calibration(config)

        if result.success:
            # Store calibration results in DB
            await self._store_calibration_results(result)

            await self._exec_repo.update_status(
                self._execution.id,
                ExecutionStatus.RUNNING,
            )
        else:
            await self._handle_calibration_error(result)

    async def _check_existing_calibration(self) -> bool:
        """Check if calibration results exist for all targets and profiles."""
        loadprofiles = self._test_run.req_loadprofile or ["low", "medium", "high"]

        for target in self._targets:
            for loadprofile in loadprofiles:
                # Use repository method
                result = await self._calibration_repo.get_for_target(
                    target_id=target.target_id,
                    baseline_id=target.base_snapshot_id,
                    loadprofile=LoadProfile(loadprofile),
                )
                if not result or result.calibration_status != CalibrationStatus.COMPLETED:
                    return False

        return True

    async def _store_calibration_results(
        self,
        result: CalibrationExecutionResult,
    ) -> None:
        """Store calibration results in CalibrationResultORM using repository."""
        from decimal import Decimal

        for target_id, target_result in result.target_results.items():
            target = next((t for t in self._targets if t.target_id == target_id), None)
            if not target:
                continue

            # Get hardware profile for CPU/memory info
            server = await self._server_repo.get_by_id(target_id)
            cpu_count = 4
            memory_gb = Decimal("8.00")
            if server and server.hardware_profile_id:
                # Get hardware profile
                from sqlalchemy import select
                from app.models.orm import HardwareProfileORM
                stmt = select(HardwareProfileORM).where(
                    HardwareProfileORM.id == server.hardware_profile_id
                )
                hw_result = await self._session.execute(stmt)
                hw_profile = hw_result.scalar_one_or_none()
                if hw_profile:
                    cpu_count = hw_profile.cpu_count
                    memory_gb = hw_profile.memory_gb

            for profile, cal_result in target_result.profile_results.items():
                # Use repository upsert method
                await self._calibration_repo.upsert(
                    target_id=target_id,
                    baseline_id=target.base_snapshot_id,
                    loadprofile=LoadProfile(profile),
                    thread_count=cal_result.thread_count,
                    cpu_count=cpu_count,
                    memory_gb=memory_gb,
                    cpu_target_percent=Decimal(str(cal_result.cpu_target_percent)) if cal_result.cpu_target_percent else None,
                    achieved_cpu_percent=Decimal(str(cal_result.achieved_cpu_percent)) if cal_result.achieved_cpu_percent else None,
                    calibration_status=CalibrationStatus.COMPLETED,
                )

        await self._session.commit()
        logger.info("Stored calibration results in database")

    async def _handle_calibration_error(
        self,
        result: CalibrationExecutionResult,
    ) -> None:
        """Handle calibration failure."""
        self._state = ControllerState.ERROR

        await self._exec_repo.update_status(
            self._execution.id,
            ExecutionStatus.ENDED_ERROR,
            result.error_message,
        )

        logger.error(f"Calibration failed: {result.error_message}")
        raise RuntimeError(f"Calibration failed: {result.error_message}")

    async def _build_calibration_configs(self) -> list[CalibrationTargetConfig]:
        """Build CalibrationTargetConfig list from targets with hardware info."""
        from decimal import Decimal
        from sqlalchemy import select
        from app.models.orm import HardwareProfileORM

        configs = []
        for target in self._targets:
            # Get CPU/memory from hardware profile
            cpu_count = 4
            memory_gb = 8.0

            server = target.target
            if server and server.hardware_profile_id:
                stmt = select(HardwareProfileORM).where(
                    HardwareProfileORM.id == server.hardware_profile_id
                )
                result = await self._session.execute(stmt)
                hw_profile = result.scalar_one_or_none()
                if hw_profile:
                    cpu_count = hw_profile.cpu_count
                    memory_gb = float(hw_profile.memory_gb)

            configs.append(CalibrationTargetConfig(
                target_id=target.target_id,
                target_ip=server.ip_address,
                target_hostname=server.hostname,
                emulator_port=server.emulator_port,
                baseline_id=target.base_snapshot_id,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
            ))
        return configs

    # =========================================================================
    # Test Execution
    # =========================================================================

    async def _determine_phases(self) -> list[str]:
        """
        Determine which phases to run based on target configuration.

        - base: Always runs (base_baseline_id is required)
        - initial: Runs if any target has initial_baseline_id
        - upgrade: Runs if any target has upgrade_baseline_id or upgrade in scenario_cases
        """
        phases = ["base"]

        # Check if any target has initial/upgrade configured
        has_initial = any(t.initial_snapshot_id for t in self._targets)
        has_upgrade = any(t.upgrade_snapshot_id for t in self._targets)

        # Also check workflow states for upgrade_package_grp_id (upgrade on top of initial)
        for state in self._workflow_states.values():
            if hasattr(state, 'upgrade_package_grp_id') and state.upgrade_package_grp_id:
                has_upgrade = True
                break

        if has_initial:
            phases.append("initial")
        if has_upgrade:
            phases.append("upgrade")

        logger.info(f"Phases to execute: {phases}")
        return phases

    async def _run_test_phases(self) -> None:
        """Run test execution for all phases and loadprofiles."""
        self._state = ControllerState.EXECUTING

        # Determine phases based on target configuration
        phases = await self._determine_phases()
        loadprofiles = self._test_run.req_loadprofile or ["low", "medium", "high"]
        repetitions = self._test_run.repetitions or 1

        # Determine starting point from current execution state
        start_phase = self._execution.current_phase or "base"
        start_loadprofile = self._execution.current_loadprofile or loadprofiles[0]
        start_repetition = self._execution.current_repetition or 1

        started = False

        for rep in range(start_repetition, repetitions + 1):
            for phase in phases:
                if not started and phase != start_phase:
                    continue

                for loadprofile in loadprofiles:
                    if not started:
                        if phase == start_phase and loadprofile == start_loadprofile:
                            started = True
                        else:
                            continue

                    # Check for pause
                    if await self._check_pause_requested():
                        return

                    # Update progress
                    await self._exec_repo.update_progress(
                        self._execution.id,
                        LoadProfile(loadprofile),
                        rep,
                    )
                    self._execution.current_phase = phase
                    await self._session.commit()

                    await self._report_progress(phase, loadprofile)

                    # Run this phase/loadprofile
                    await self._run_single_execution(phase, loadprofile, rep)

                    # Check step mode
                    if await self._check_step_mode_pause(loadprofile):
                        return

        # Complete execution
        self._state = ControllerState.COMPLETED
        await self._exec_service.complete_execution(self._execution.id, success=True)
        logger.info(f"Execution {self._execution.id} completed successfully")

    async def _run_single_execution(
        self,
        phase: str,
        loadprofile: str,
        repetition: int,
    ) -> None:
        """Run a single phase/loadprofile combination."""
        logger.info(f"Running {phase}/{loadprofile} (rep {repetition})")

        # Build target configs
        target_configs = await self._build_target_configs(phase, loadprofile)

        # Get workflow states for this loadprofile
        workflow_states = {
            tc.target_id: self._workflow_states[(tc.target_id, loadprofile)]
            for tc in target_configs
        }

        # Update workflow states to running
        for state in workflow_states.values():
            state.current_phase = phase
            state.phase_state = PhaseState.RUNNING.value
            state.cur_state = WorkflowState.RUNNING.value
        await self._session.commit()

        # Create executor
        self._test_executor = TestExecutorFactory.create_for_environment(
            db_session=self._session,
            target_configs=target_configs,
            env_config=self._env_config,
        )

        # Build execution config
        config = TestExecutionConfig(
            test_run_id=self._test_run.id,
            scenario_id=self._test_run.scenario_id,
            phase=phase,
            loadprofile=loadprofile,
            targets=target_configs,
            warmup_sec=self._test_run.warmup_sec or 60,
            measured_sec=self._test_run.measured_sec or 600,
        )

        # Run execution
        result = await self._test_executor.execute_scenario(config, workflow_states)

        if result.success:
            # Update workflow states to completed
            for state in workflow_states.values():
                state.phase_state = PhaseState.COMPLETED.value
            await self._session.commit()
        else:
            await self._handle_execution_error(result, workflow_states)

    async def _build_target_configs(
        self,
        phase: str,
        loadprofile: str,
    ) -> list[TargetConfig]:
        """Build TargetConfig list for a phase/loadprofile."""
        configs = []

        for target in self._targets:
            # Get calibration data using repository
            calibration = {}
            cal_results = await self._calibration_repo.get_by_target_id(target.target_id)
            for cal in cal_results:
                if cal.baseline_id == target.base_snapshot_id:
                    calibration[cal.loadprofile.value] = {
                        "thread_count": cal.thread_count,
                        "cpu_target": float(cal.cpu_target_percent) if cal.cpu_target_percent else 50.0,
                    }

            # Get loadgen info
            loadgen = target.loadgenerator

            # Get package lists from workflow state
            workflow_state = self._workflow_states.get((target.target_id, loadprofile))
            target_packages = []
            jmeter_packages = []

            if workflow_state:
                # Get phase-specific package list
                if phase == "base":
                    target_packages = workflow_state.base_package_lst or []
                elif phase == "initial":
                    target_packages = workflow_state.initial_package_lst or []
                elif phase == "upgrade":
                    target_packages = workflow_state.upgrade_package_lst or []

                # JMeter packages are shared across phases
                jmeter_packages = workflow_state.jmeter_package_lst or []

            # Determine which baseline to use for this phase
            baseline_id = target.base_snapshot_id
            if phase == "initial" and target.initial_snapshot_id:
                baseline_id = target.initial_snapshot_id
            elif phase == "upgrade" and target.upgrade_snapshot_id:
                baseline_id = target.upgrade_snapshot_id

            configs.append(TargetConfig(
                target_id=target.target_id,
                target_ip=target.target.ip_address,
                target_hostname=target.target.hostname,
                target_port=target.target.emulator_port,
                loadgen_id=loadgen.id,
                loadgen_ip=loadgen.ip_address,
                jmeter_port=target.jmeter_port,
                baseline_id=baseline_id,
                calibration=calibration,
                target_packages=target_packages,
                jmeter_packages=jmeter_packages,
                jmx_file_path=target.jmx_file_path,
            ))

        return configs

    async def _handle_execution_error(
        self,
        result: TestExecutionResult,
        workflow_states: dict[int, ExecutionWorkflowStateORM],
    ) -> None:
        """Handle execution error."""
        # Update workflow states with error
        for target_id, target_result in result.target_results.items():
            if not target_result.success:
                state = workflow_states.get(target_id)
                if state:
                    state.phase_state = PhaseState.ERROR.value
                    state.error_message = target_result.error_message

        await self._session.commit()

        # Record in execution
        self._execution.error_message = result.error_message
        self._execution.last_error_type = "execution_error"
        await self._session.commit()

        logger.error(f"Execution error: {result.error_message}")

        # Don't fail completely - let it continue to next loadprofile
        # unless all targets failed
        all_failed = all(not tr.success for tr in result.target_results.values())
        if all_failed:
            self._state = ControllerState.ERROR
            await self._exec_service.complete_execution(
                self._execution.id,
                success=False,
                error_message=result.error_message,
            )
            raise RuntimeError(f"All targets failed: {result.error_message}")
