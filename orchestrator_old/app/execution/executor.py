"""Test executor for running individual test executions."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable, List, Dict
from uuid import uuid4

from .models import (
    ExecutionConfig,
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionPhase,
    ExecutionProgress,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    ExecutionStatus,
    EmulatorDeployment,
    PhaseResult,
)
from .state_machine import ExecutionStateMachine

from ..calibration import (
    CalibrationService,
    CalibrationConfig,
    LoadProfile,
)


class TestPhase(str, Enum):
    """Test execution phases."""
    BASE = "base"
    INITIAL = "initial"
    UPGRADE = "upgrade"


@dataclass
class TargetExecutionInfo:
    """Info for a single target in multi-target execution."""
    target_id: int
    server_id: int
    loadgenerator_id: int
    base_baseline_id: int
    initial_baseline_id: Optional[int] = None
    upgrade_baseline_id: Optional[int] = None
    emulator_host: Optional[str] = None
    emulator_port: Optional[int] = None


@dataclass
class ScenarioExecutionRequest:
    """Request for executing a complete scenario."""
    scenario_id: int
    lab_id: int
    test_run_id: int
    targets: List[TargetExecutionInfo]
    phases: List[TestPhase] = field(default_factory=lambda: [TestPhase.BASE, TestPhase.INITIAL, TestPhase.UPGRADE])
    load_profile: str = "medium"
    config: Optional[ExecutionConfig] = None


@dataclass
class ScenarioExecutionResult:
    """Result of executing a complete scenario."""
    scenario_id: int
    test_run_id: int
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    target_results: Dict[int, Dict[str, ExecutionResult]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


logger = logging.getLogger(__name__)


class ExecutorError(Exception):
    """Base exception for executor errors."""

    pass


class PhaseExecutor:
    """
    Executes individual phases of test execution.

    Each phase has its own execution logic and error handling.
    """

    def __init__(
        self,
        state_machine: ExecutionStateMachine,
        config: ExecutionConfig,
        event_callback: Optional[Callable[[ExecutionEvent], Awaitable[None]]] = None,
    ):
        self._sm = state_machine
        self._config = config
        self._event_callback = event_callback

    async def _emit_event(
        self,
        event_type: str,
        message: str,
        details: Optional[str] = None,
        is_error: bool = False,
    ) -> None:
        """Emit an execution event."""
        if self._event_callback:
            event = ExecutionEvent(
                execution_id=self._sm.state.execution_id,
                event_type=event_type,
                phase=self._sm.current_phase,
                message=message,
                details=details,
                is_error=is_error,
            )
            await self._event_callback(event)

    async def execute_vm_preparation(
        self,
        vm_name: Optional[str],
        vcenter_host: Optional[str],
        snapshot_name: Optional[str],
    ) -> bool:
        """
        Prepare VM for testing.

        Reverts to snapshot if configured.
        """
        self._sm.start_phase(ExecutionPhase.VM_PREPARATION)

        try:
            if not vm_name or not vcenter_host:
                await self._emit_event(
                    "vm_prep_skipped",
                    "VM preparation skipped - no vCenter config",
                )
                self._sm.complete_phase(
                    ExecutionPhase.VM_PREPARATION,
                    success=True,
                    details="Skipped - no vCenter configuration",
                )
                return True

            await self._emit_event(
                "vm_prep_started",
                f"Preparing VM {vm_name}",
            )

            # VM operations would be performed here
            # For now, simulate preparation
            await asyncio.sleep(1)

            if snapshot_name:
                await self._emit_event(
                    "snapshot_revert",
                    f"Reverting to snapshot {snapshot_name}",
                )
                # Snapshot revert would happen here
                await asyncio.sleep(2)

            await self._emit_event(
                "vm_prep_completed",
                f"VM {vm_name} prepared successfully",
            )

            self._sm.complete_phase(
                ExecutionPhase.VM_PREPARATION,
                success=True,
            )
            return True

        except Exception as e:
            error_msg = f"VM preparation failed: {e}"
            logger.error(error_msg)
            await self._emit_event(
                "vm_prep_failed",
                error_msg,
                is_error=True,
            )
            self._sm.complete_phase(
                ExecutionPhase.VM_PREPARATION,
                success=False,
                error_message=error_msg,
            )
            return False

    async def execute_emulator_deployment(
        self,
        target_host: str,
        target_port: int,
        os_type: str,
    ) -> Optional[EmulatorDeployment]:
        """
        Deploy emulator to target.

        Returns deployment info on success.
        """
        self._sm.start_phase(ExecutionPhase.EMULATOR_DEPLOYMENT)

        try:
            await self._emit_event(
                "deployment_started",
                f"Deploying emulator to {target_host}:{target_port}",
            )

            # Deployment would be performed here using remote executor
            # For now, simulate deployment
            await asyncio.sleep(2)

            deployment = EmulatorDeployment(
                target_id=self._sm.state.target_id,
                host=target_host,
                port=target_port,
                deployed_at=datetime.utcnow(),
                version="1.0.0",
            )

            self._sm.state.emulator_deployment = deployment

            await self._emit_event(
                "deployment_completed",
                f"Emulator deployed successfully to {target_host}:{target_port}",
            )

            self._sm.complete_phase(
                ExecutionPhase.EMULATOR_DEPLOYMENT,
                success=True,
            )
            return deployment

        except Exception as e:
            error_msg = f"Emulator deployment failed: {e}"
            logger.error(error_msg)
            await self._emit_event(
                "deployment_failed",
                error_msg,
                is_error=True,
            )
            self._sm.complete_phase(
                ExecutionPhase.EMULATOR_DEPLOYMENT,
                success=False,
                error_message=error_msg,
            )
            return None

    async def execute_calibration(
        self,
        emulator_host: str,
        emulator_port: int,
        load_profile: str,
        cpu_count: int,
        memory_gb: float,
    ) -> Optional[tuple[int, float]]:
        """
        Run calibration to find optimal thread count.

        Returns (thread_count, achieved_cpu) on success.
        """
        self._sm.start_phase(ExecutionPhase.CALIBRATION)

        try:
            await self._emit_event(
                "calibration_started",
                f"Starting calibration for {load_profile} profile",
            )

            # Create calibration service
            calibration_config = CalibrationConfig(
                calibration_duration_sec=60,
                warmup_sec=10,
            )
            calibration_service = CalibrationService(calibration_config)

            # Map string to LoadProfile
            profile_map = {
                "low": LoadProfile.LOW,
                "medium": LoadProfile.MEDIUM,
                "high": LoadProfile.HIGH,
            }
            profile = profile_map.get(load_profile.lower(), LoadProfile.MEDIUM)

            # Run calibration
            result = await calibration_service.calibrate_target(
                target_id=self._sm.state.target_id,
                baseline_id=self._sm.state.baseline_id,
                loadprofile=profile,
                emulator_host=emulator_host,
                emulator_port=emulator_port,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
            )

            if result.status != CalibrationStatus.COMPLETED:
                raise ExecutorError(
                    f"Calibration failed: {result.error_message}"
                )

            # Validate calibration
            is_valid, message = calibration_service.validate_calibration(result)
            if not is_valid:
                raise ExecutorError(f"Calibration invalid: {message}")

            # Store results
            self._sm.state.calibration_thread_count = result.thread_count
            self._sm.state.calibration_achieved_cpu = result.achieved_cpu_percent

            await self._emit_event(
                "calibration_completed",
                f"Calibration complete: {result.thread_count} threads, "
                f"{result.achieved_cpu_percent:.1f}% CPU",
            )

            self._sm.complete_phase(
                ExecutionPhase.CALIBRATION,
                success=True,
                details=f"Threads: {result.thread_count}, CPU: {result.achieved_cpu_percent:.1f}%",
            )

            return result.thread_count, result.achieved_cpu_percent

        except Exception as e:
            error_msg = f"Calibration failed: {e}"
            logger.error(error_msg)
            await self._emit_event(
                "calibration_failed",
                error_msg,
                is_error=True,
            )
            self._sm.complete_phase(
                ExecutionPhase.CALIBRATION,
                success=False,
                error_message=error_msg,
            )
            return None


# Import here to avoid circular import
from ..calibration.models import CalibrationStatus


class TestExecutor:
    """
    Executes a complete test run for a single target.

    Orchestrates all phases from preparation through result collection.
    """

    def __init__(
        self,
        request: ExecutionRequest,
        progress_callback: Optional[
            Callable[[ExecutionProgress], Awaitable[None]]
        ] = None,
        event_callback: Optional[Callable[[ExecutionEvent], Awaitable[None]]] = None,
    ):
        self._request = request
        self._progress_callback = progress_callback
        self._event_callback = event_callback

        # Create execution state
        self._state = ExecutionState(
            execution_id=str(uuid4()),
            test_run_id=request.test_run_id,
            target_id=request.target_id,
            baseline_id=request.baseline_id,
        )
        self._sm = ExecutionStateMachine(self._state)
        self._phase_executor = PhaseExecutor(
            self._sm,
            request.config,
            event_callback,
        )

    @property
    def execution_id(self) -> str:
        """Get execution ID."""
        return self._state.execution_id

    @property
    def state(self) -> ExecutionState:
        """Get current execution state."""
        return self._state

    async def _report_progress(
        self,
        phase_progress: float,
        overall_progress: float,
        message: str,
    ) -> None:
        """Report execution progress."""
        if self._progress_callback:
            progress = ExecutionProgress(
                execution_id=self._state.execution_id,
                status=self._state.status,
                current_phase=self._state.current_phase,
                phase_progress_percent=phase_progress,
                overall_progress_percent=overall_progress,
                message=message,
            )
            await self._progress_callback(progress)

    async def execute(self) -> ExecutionResult:
        """
        Execute the complete test run.

        Returns ExecutionResult with final status and metrics.
        """
        try:
            # Start execution
            self._sm.transition_to(
                ExecutionStatus.INITIALIZING,
                ExecutionPhase.INIT,
            )

            await self._report_progress(0, 0, "Starting execution")

            # Phase 1: VM Preparation (0-10%)
            await self._report_progress(0, 5, "Preparing VM")
            vm_success = await self._phase_executor.execute_vm_preparation(
                vm_name=self._request.target_info.vm_name,
                vcenter_host=self._request.target_info.vcenter_host,
                snapshot_name=self._request.target_info.snapshot_name,
            )

            if not vm_success:
                return self._create_failed_result()

            # Phase 2: Emulator Deployment (10-25%)
            await self._report_progress(0, 15, "Deploying emulator")
            deployment = await self._phase_executor.execute_emulator_deployment(
                target_host=self._request.target_info.ip_address,
                target_port=8080,
                os_type=self._request.target_info.os_type,
            )

            if not deployment:
                return self._create_failed_result()

            # Phase 3: Calibration (25-50%)
            await self._report_progress(0, 35, "Running calibration")
            calibration_result = await self._phase_executor.execute_calibration(
                emulator_host=deployment.host,
                emulator_port=deployment.port,
                load_profile=self._request.load_profile,
                cpu_count=self._request.target_info.cpu_count,
                memory_gb=self._request.target_info.memory_gb,
            )

            if not calibration_result:
                return self._create_failed_result()

            thread_count, achieved_cpu = calibration_result

            # Phase 4: Load Test (50-85%)
            await self._report_progress(0, 60, "Running load test")
            self._sm.start_phase(ExecutionPhase.LOAD_TEST)

            test_success = await self._execute_load_test(
                thread_count=thread_count,
                emulator_host=deployment.host,
                emulator_port=deployment.port,
            )

            if not test_success:
                return self._create_failed_result()

            self._sm.complete_phase(ExecutionPhase.LOAD_TEST, success=True)

            # Phase 5: Result Collection (85-95%)
            await self._report_progress(0, 90, "Collecting results")
            self._sm.start_phase(ExecutionPhase.RESULT_COLLECTION)

            metrics = await self._collect_results()

            self._sm.complete_phase(ExecutionPhase.RESULT_COLLECTION, success=True)

            # Phase 6: Cleanup (95-100%)
            await self._report_progress(0, 95, "Cleaning up")
            self._sm.start_phase(ExecutionPhase.CLEANUP)

            await self._cleanup()

            self._sm.complete_phase(ExecutionPhase.CLEANUP, success=True)

            # Complete execution
            self._sm.start_phase(ExecutionPhase.DONE)
            self._sm.complete()

            await self._report_progress(100, 100, "Execution completed")

            return self._create_success_result(
                thread_count=thread_count,
                achieved_cpu=achieved_cpu,
                metrics=metrics,
            )

        except Exception as e:
            logger.exception(f"Execution failed: {e}")
            self._sm.fail(str(e))
            return self._create_failed_result()

    async def _execute_load_test(
        self,
        thread_count: int,
        emulator_host: str,
        emulator_port: int,
    ) -> bool:
        """Execute the load test phase."""
        try:
            if self._event_callback:
                await self._event_callback(
                    ExecutionEvent(
                        execution_id=self._state.execution_id,
                        event_type="load_test_started",
                        phase=ExecutionPhase.LOAD_TEST,
                        message=f"Starting load test with {thread_count} threads",
                    )
                )

            # Load test would be executed here using JMeter
            # For now, simulate test
            test_duration = self._request.config.test_duration_sec
            warmup = self._request.config.warmup_sec

            # Simulate warmup
            await asyncio.sleep(min(warmup, 5))

            # Simulate test (shortened for demo)
            await asyncio.sleep(min(test_duration, 10))

            if self._event_callback:
                await self._event_callback(
                    ExecutionEvent(
                        execution_id=self._state.execution_id,
                        event_type="load_test_completed",
                        phase=ExecutionPhase.LOAD_TEST,
                        message="Load test completed successfully",
                    )
                )

            return True

        except Exception as e:
            logger.error(f"Load test failed: {e}")
            return False

    async def _collect_results(self) -> ExecutionMetrics:
        """Collect test results and metrics."""
        # Results would be collected from JMeter and emulator
        # For now, return simulated metrics
        total_duration = self._sm.get_total_duration() or 0.0

        return ExecutionMetrics(
            total_duration_sec=total_duration,
            calibration_duration_sec=self._sm.get_phase_duration(
                ExecutionPhase.CALIBRATION
            ),
            deployment_duration_sec=self._sm.get_phase_duration(
                ExecutionPhase.EMULATOR_DEPLOYMENT
            ),
            test_duration_sec=self._sm.get_phase_duration(ExecutionPhase.LOAD_TEST),
            total_requests=10000,
            successful_requests=9950,
            failed_requests=50,
            avg_response_time_ms=45.5,
            p50_response_time_ms=40.0,
            p90_response_time_ms=75.0,
            p99_response_time_ms=150.0,
            throughput_rps=500.0,
            avg_cpu_percent=self._state.calibration_achieved_cpu,
            max_cpu_percent=(self._state.calibration_achieved_cpu or 0) * 1.1,
        )

    async def _cleanup(self) -> None:
        """Perform cleanup after test execution."""
        if self._event_callback:
            await self._event_callback(
                ExecutionEvent(
                    execution_id=self._state.execution_id,
                    event_type="cleanup_started",
                    phase=ExecutionPhase.CLEANUP,
                    message="Starting cleanup",
                )
            )

        # Cleanup would stop emulator, revert VM, etc.
        await asyncio.sleep(1)

        if self._event_callback:
            await self._event_callback(
                ExecutionEvent(
                    execution_id=self._state.execution_id,
                    event_type="cleanup_completed",
                    phase=ExecutionPhase.CLEANUP,
                    message="Cleanup completed",
                )
            )

    def _create_success_result(
        self,
        thread_count: int,
        achieved_cpu: float,
        metrics: ExecutionMetrics,
    ) -> ExecutionResult:
        """Create successful execution result."""
        # Get target CPU based on profile
        target_cpu_map = {
            "low": 30.0,
            "medium": 50.0,
            "high": 70.0,
        }
        target_cpu = target_cpu_map.get(
            self._request.load_profile.lower(), 50.0
        )

        return ExecutionResult(
            execution_id=self._state.execution_id,
            test_run_id=self._state.test_run_id,
            target_id=self._state.target_id,
            baseline_id=self._state.baseline_id,
            status=ExecutionStatus.COMPLETED,
            load_profile=self._request.load_profile,
            started_at=self._state.started_at or datetime.utcnow(),
            completed_at=self._state.completed_at or datetime.utcnow(),
            total_duration_sec=self._sm.get_total_duration() or 0.0,
            thread_count=thread_count,
            target_cpu_percent=target_cpu,
            achieved_cpu_percent=achieved_cpu,
            metrics=metrics,
            phase_results=self._sm.get_phase_results(),
        )

    def _create_failed_result(self) -> ExecutionResult:
        """Create failed execution result."""
        # Transition to FAILED status if not already terminal
        if not self._sm.is_terminal():
            error_msg = self._state.last_error or "Execution failed"
            self._sm.transition_to(
                ExecutionStatus.FAILED,
                error_message=error_msg,
            )

        target_cpu_map = {
            "low": 30.0,
            "medium": 50.0,
            "high": 70.0,
        }
        target_cpu = target_cpu_map.get(
            self._request.load_profile.lower(), 50.0
        )

        return ExecutionResult(
            execution_id=self._state.execution_id,
            test_run_id=self._state.test_run_id,
            target_id=self._state.target_id,
            baseline_id=self._state.baseline_id,
            status=ExecutionStatus.FAILED,
            load_profile=self._request.load_profile,
            started_at=self._state.started_at or datetime.utcnow(),
            completed_at=self._state.completed_at or datetime.utcnow(),
            total_duration_sec=self._sm.get_total_duration() or 0.0,
            thread_count=self._state.calibration_thread_count or 0,
            target_cpu_percent=target_cpu,
            achieved_cpu_percent=self._state.calibration_achieved_cpu or 0.0,
            phase_results=self._sm.get_phase_results(),
            error_message=self._state.last_error,
            error_phase=self._state.error_phase,
        )

    async def cancel(self) -> None:
        """Cancel execution."""
        self._sm.cancel("Cancelled by user")

        if self._event_callback:
            await self._event_callback(
                ExecutionEvent(
                    execution_id=self._state.execution_id,
                    event_type="execution_cancelled",
                    phase=self._state.current_phase,
                    message="Execution cancelled",
                )
            )


class ScenarioExecutor:
    """
    Orchestrates test execution across multiple targets in a scenario.

    Handles:
    - LoadGenerator deployment (once per unique loadgen)
    - Phase-based execution (Base → Initial → Upgrade)
    - Delta deployment logic per phase
    - Parallel execution of targets within a phase
    """

    def __init__(
        self,
        request: ScenarioExecutionRequest,
        progress_callback: Optional[Callable[[ExecutionProgress], Awaitable[None]]] = None,
        event_callback: Optional[Callable[[ExecutionEvent], Awaitable[None]]] = None,
    ):
        self._request = request
        self._progress_callback = progress_callback
        self._event_callback = event_callback
        self._started_at = datetime.utcnow()
        self._deployed_loadgens: set[int] = set()
        self._target_results: Dict[int, Dict[str, ExecutionResult]] = {}

    async def execute(self) -> ScenarioExecutionResult:
        """
        Execute the complete scenario across all targets.

        Execution Flow:
        1. Deploy LoadGenerators (once per unique loadgen_id)
        2. For each phase (Base, Initial, Upgrade):
           a. Check if baseline changed from previous phase
           b. Restore servers if baseline changed
           c. Deploy packages (complete or delta based on baseline change)
           d. Execute tests for all targets in parallel
           e. Collect results
        3. Return combined results

        Returns:
            ScenarioExecutionResult with all target results
        """
        errors: List[str] = []

        try:
            # Phase 0: Deploy LoadGenerators (deduplicated)
            await self._deploy_loadgenerators()

            # Execute each phase
            for phase in self._request.phases:
                phase_success = await self._execute_phase(phase)
                if not phase_success:
                    errors.append(f"Phase {phase.value} failed")
                    # Continue to next phase or abort based on config

            status = ExecutionStatus.COMPLETED if not errors else ExecutionStatus.FAILED

            return ScenarioExecutionResult(
                scenario_id=self._request.scenario_id,
                test_run_id=self._request.test_run_id,
                status=status,
                started_at=self._started_at,
                completed_at=datetime.utcnow(),
                target_results=self._target_results,
                errors=errors,
            )

        except Exception as e:
            logger.exception(f"Scenario execution failed: {e}")
            return ScenarioExecutionResult(
                scenario_id=self._request.scenario_id,
                test_run_id=self._request.test_run_id,
                status=ExecutionStatus.FAILED,
                started_at=self._started_at,
                completed_at=datetime.utcnow(),
                target_results=self._target_results,
                errors=[str(e)],
            )

    async def _deploy_loadgenerators(self) -> None:
        """Deploy JMeter to unique LoadGenerators (once per loadgen)."""
        unique_loadgens = {t.loadgenerator_id for t in self._request.targets}

        for loadgen_id in unique_loadgens:
            if loadgen_id in self._deployed_loadgens:
                # Already deployed in a previous run
                continue

            # Deploy JMeter packages to this LoadGenerator
            # In real implementation: call package deployment service
            logger.info(f"Deploying JMeter to LoadGenerator {loadgen_id}")
            await asyncio.sleep(1)  # Simulated deployment

            self._deployed_loadgens.add(loadgen_id)

    async def _execute_phase(self, phase: TestPhase) -> bool:
        """
        Execute a single phase for all targets.

        For each target:
        1. Check if baseline changed from previous phase
        2. If changed: restore server, deploy COMPLETE package list
        3. If not changed: deploy DELTA packages only
        4. Run test
        """
        logger.info(f"Executing {phase.value} phase for {len(self._request.targets)} targets")

        # Prepare phase execution for all targets
        phase_tasks = []
        for target in self._request.targets:
            task = self._execute_target_phase(target, phase)
            phase_tasks.append(task)

        # Execute all targets in parallel for this phase
        results = await asyncio.gather(*phase_tasks, return_exceptions=True)

        # Process results
        all_succeeded = True
        for target, result in zip(self._request.targets, results):
            if isinstance(result, Exception):
                logger.error(f"Target {target.target_id} {phase.value} failed: {result}")
                all_succeeded = False
            elif result.status != ExecutionStatus.COMPLETED:
                all_succeeded = False

            # Store result
            if target.target_id not in self._target_results:
                self._target_results[target.target_id] = {}
            self._target_results[target.target_id][phase.value] = result

        return all_succeeded

    async def _execute_target_phase(
        self,
        target: TargetExecutionInfo,
        phase: TestPhase,
    ) -> ExecutionResult:
        """
        Execute a phase for a single target.

        Handles baseline comparison and delta deployment logic.
        """
        # Determine current and previous baseline
        if phase == TestPhase.BASE:
            current_baseline = target.base_baseline_id
            previous_baseline = None  # First phase, no previous
        elif phase == TestPhase.INITIAL:
            current_baseline = target.initial_baseline_id or target.base_baseline_id
            previous_baseline = target.base_baseline_id
        else:  # UPGRADE
            effective_initial = target.initial_baseline_id or target.base_baseline_id
            current_baseline = target.upgrade_baseline_id or effective_initial
            previous_baseline = effective_initial

        baseline_changed = previous_baseline is None or current_baseline != previous_baseline

        if baseline_changed:
            logger.info(
                f"Target {target.target_id} {phase.value}: baseline changed, "
                f"restoring and deploying complete package list"
            )
            # In real implementation:
            # 1. Restore server to current_baseline
            # 2. Deploy complete package list for this phase
        else:
            logger.info(
                f"Target {target.target_id} {phase.value}: baseline unchanged, "
                f"deploying delta packages only"
            )
            # In real implementation:
            # 1. Deploy only new packages for this phase (delta)

        # Execute the test for this phase
        # For now, simulate execution
        await asyncio.sleep(2)

        return ExecutionResult(
            execution_id=str(uuid4()),
            test_run_id=self._request.test_run_id,
            target_id=target.target_id,
            baseline_id=current_baseline,
            status=ExecutionStatus.COMPLETED,
            load_profile=self._request.load_profile,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            total_duration_sec=2.0,
            thread_count=10,
            target_cpu_percent=50.0,
            achieved_cpu_percent=48.5,
            phase_results=[],
        )
