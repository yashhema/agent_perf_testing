"""Phase orchestrator for coordinating full phase execution.

Orchestrates the complete flow for a phase:
1. Restore baseline/snapshot
2. Install packages (target + JMeter)
3. Verify packages
4. Start emulator (if applicable)
5. Run JMeter load test
6. Run functional/policy tests
7. Collect results
8. Store results in workflow state
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol
from enum import Enum

from app.models.enums import WorkflowState, PhaseState
from app.models.orm import ExecutionWorkflowStateORM
from app.services.workflow_state_service import WorkflowStateService
from app.packages.orchestrator import PackageInstallOrchestrator, PhaseInstallResult
from app.packages.delivery import DeliveryStrategy
from app.jmeter.service import JMeterService
from app.jmeter.models import JMeterConfig, JMeterStatus
from app.results.collector import ResultCollector
from app.results.models import PhaseResults


logger = logging.getLogger(__name__)


class PhaseStage(str, Enum):
    """Stages within a phase execution."""

    RESTORING = "restoring"
    INSTALLING_TARGET = "installing_target"
    INSTALLING_JMETER = "installing_jmeter"
    VERIFYING = "verifying"
    STARTING_EMULATOR = "starting_emulator"
    RUNNING_LOAD_TEST = "running_load_test"
    RUNNING_FUNCTIONAL = "running_functional"
    COLLECTING_RESULTS = "collecting_results"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseExecutionConfig:
    """Configuration for phase execution."""

    phase: str  # "base", "initial", "upgrade"
    loadprofile: str  # "low", "medium", "high"

    # Target device
    target_id: int
    target_ip: str
    target_hostname: str

    # Load generator
    loadgen_id: int
    loadgen_ip: str

    # Baseline
    baseline_id: Optional[int] = None
    revert_required: bool = True

    # JMeter configuration
    jmeter_config: Optional[JMeterConfig] = None
    jmeter_package_id: Optional[int] = None

    # Package lists
    target_package_list: list[dict] = field(default_factory=list)
    jmeter_package_list: list[dict] = field(default_factory=list)

    # Timeouts
    restore_timeout_sec: int = 600
    install_timeout_sec: int = 1200
    load_test_timeout_sec: int = 14400  # 4 hours


@dataclass
class PhaseExecutionResult:
    """Result of phase execution."""

    phase: str
    loadprofile: str
    success: bool

    # Stage tracking
    stage_reached: PhaseStage
    stages_completed: list[PhaseStage] = field(default_factory=list)

    # Sub-results
    target_install_result: Optional[PhaseInstallResult] = None
    jmeter_install_result: Optional[PhaseInstallResult] = None
    phase_results: Optional[PhaseResults] = None

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: float = 0

    # Error info
    error_stage: Optional[PhaseStage] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None


class SnapshotManager(Protocol):
    """Protocol for snapshot/baseline management."""

    async def restore_snapshot(
        self,
        target_id: int,
        baseline_id: int,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Restore target to baseline snapshot. Returns (success, error_message)."""
        ...

    async def wait_for_target_ready(
        self,
        target_id: int,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for target to be ready after restore."""
        ...


class EmulatorManager(Protocol):
    """Protocol for CPU emulator management."""

    async def start_emulator(
        self,
        target_id: int,
        thread_count: int,
        target_cpu_percent: float,
    ) -> tuple[bool, Optional[str]]:
        """Start CPU emulator. Returns (success, error_message)."""
        ...

    async def stop_emulator(
        self,
        target_id: int,
    ) -> bool:
        """Stop CPU emulator."""
        ...

    async def get_emulator_stats(
        self,
        target_id: int,
    ) -> Optional[dict]:
        """Get emulator statistics."""
        ...


class PhaseOrchestrator:
    """
    Orchestrates complete phase execution.

    Coordinates all components:
    - Snapshot restoration
    - Package installation (target + JMeter)
    - Emulator management
    - JMeter load testing
    - Result collection
    """

    def __init__(
        self,
        workflow_service: WorkflowStateService,
        package_orchestrator: PackageInstallOrchestrator,
        jmeter_service: JMeterService,
        result_collector: ResultCollector,
        snapshot_manager: SnapshotManager,
        emulator_manager: Optional[EmulatorManager] = None,
        target_delivery_strategy: Optional[DeliveryStrategy] = None,
        jmeter_delivery_strategy: Optional[DeliveryStrategy] = None,
    ):
        self.workflow_service = workflow_service
        self.package_orchestrator = package_orchestrator
        self.jmeter_service = jmeter_service
        self.result_collector = result_collector
        self.snapshot_manager = snapshot_manager
        self.emulator_manager = emulator_manager
        self.target_delivery_strategy = target_delivery_strategy
        self.jmeter_delivery_strategy = jmeter_delivery_strategy

        self._cancelled = False

    async def execute_phase(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
    ) -> PhaseExecutionResult:
        """
        Execute a complete phase.

        Args:
            workflow_state: Current workflow state
            config: Phase execution configuration

        Returns:
            PhaseExecutionResult with outcome
        """
        result = PhaseExecutionResult(
            phase=config.phase,
            loadprofile=config.loadprofile,
            success=False,
            stage_reached=PhaseStage.RESTORING,
            started_at=datetime.utcnow(),
        )

        self._cancelled = False

        try:
            # Update workflow state
            await self.workflow_service.start_phase(
                workflow_state_id=workflow_state.id,
                phase=config.phase,
                phase_state=PhaseState.RESTORING_BASELINE,
            )

            # Stage 1: Restore baseline
            if config.revert_required and config.baseline_id:
                success = await self._restore_baseline(workflow_state, config, result)
                if not success:
                    return result

            result.stages_completed.append(PhaseStage.RESTORING)
            result.stage_reached = PhaseStage.INSTALLING_TARGET

            # Check for cancellation
            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 2: Install packages on target
            await self.workflow_service.update_phase_state(
                workflow_state_id=workflow_state.id,
                phase_state=PhaseState.INSTALLING_AGENT.value,
            )

            success = await self._install_target_packages(workflow_state, config, result)
            if not success:
                return result

            result.stages_completed.append(PhaseStage.INSTALLING_TARGET)
            result.stage_reached = PhaseStage.INSTALLING_JMETER

            # Check for cancellation
            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 3: Install JMeter packages on load generator
            success = await self._install_jmeter_packages(workflow_state, config, result)
            if not success:
                return result

            result.stages_completed.append(PhaseStage.INSTALLING_JMETER)
            result.stage_reached = PhaseStage.STARTING_EMULATOR

            # Check for cancellation
            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 4: Start emulator (if applicable)
            if self.emulator_manager:
                await self.workflow_service.update_phase_state(
                    workflow_state_id=workflow_state.id,
                    phase_state=PhaseState.STARTING_EMULATOR.value,
                )

                success = await self._start_emulator(workflow_state, config, result)
                if not success:
                    return result

            result.stages_completed.append(PhaseStage.STARTING_EMULATOR)
            result.stage_reached = PhaseStage.RUNNING_LOAD_TEST

            # Check for cancellation
            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 5: Run JMeter load test
            await self.workflow_service.update_phase_state(
                workflow_state_id=workflow_state.id,
                phase_state=PhaseState.RUNNING_LOAD.value,
            )

            success = await self._run_load_test(workflow_state, config, result)
            if not success:
                return result

            result.stages_completed.append(PhaseStage.RUNNING_LOAD_TEST)
            result.stage_reached = PhaseStage.RUNNING_FUNCTIONAL

            # Check for cancellation
            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 6: Run functional/policy tests
            await self._run_functional_tests(workflow_state, config, result)

            result.stages_completed.append(PhaseStage.RUNNING_FUNCTIONAL)
            result.stage_reached = PhaseStage.COLLECTING_RESULTS

            # Stage 7: Collect all results
            await self.workflow_service.update_phase_state(
                workflow_state_id=workflow_state.id,
                phase_state=PhaseState.COLLECTING_RESULTS.value,
            )

            phase_results = await self._collect_results(workflow_state, config, result)
            result.phase_results = phase_results

            result.stages_completed.append(PhaseStage.COLLECTING_RESULTS)
            result.stage_reached = PhaseStage.COMPLETED

            # Stage 8: Stop emulator
            if self.emulator_manager:
                await self.emulator_manager.stop_emulator(config.target_id)

            # Mark phase complete
            result.success = True
            await self.workflow_service.update_phase_state(
                workflow_state_id=workflow_state.id,
                phase_state=PhaseState.COMPLETED.value,
            )
            await self.workflow_service.complete_phase(workflow_state.id)

        except asyncio.CancelledError:
            return self._handle_cancellation(result)

        except Exception as e:
            logger.error(f"Phase execution failed: {e}")
            result.error_message = str(e)
            result.error_type = type(e).__name__
            result.error_stage = result.stage_reached

            await self.workflow_service.record_error(
                workflow_state_id=workflow_state.id,
                error_type=result.error_type or "unknown",
                error_message=result.error_message or "Unknown error",
                phase=config.phase,
            )

        finally:
            result.completed_at = datetime.utcnow()
            if result.started_at:
                result.duration_sec = (
                    result.completed_at - result.started_at
                ).total_seconds()

        return result

    async def _restore_baseline(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> bool:
        """Restore target to baseline snapshot."""
        logger.info(f"Restoring baseline {config.baseline_id} for target {config.target_id}")

        success, error = await self.snapshot_manager.restore_snapshot(
            target_id=config.target_id,
            baseline_id=config.baseline_id,
            timeout_sec=config.restore_timeout_sec,
        )

        if not success:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.RESTORING
            result.error_message = error or "Baseline restore failed"
            result.error_type = "restore_failed"

            await self.workflow_service.record_error(
                workflow_state_id=workflow_state.id,
                error_type="restore_failed",
                error_message=result.error_message,
                phase=config.phase,
            )
            return False

        # Wait for target to be ready
        ready = await self.snapshot_manager.wait_for_target_ready(
            target_id=config.target_id,
            timeout_sec=300,
        )

        if not ready:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.RESTORING
            result.error_message = "Target not ready after restore"
            result.error_type = "target_not_ready"

            await self.workflow_service.record_error(
                workflow_state_id=workflow_state.id,
                error_type="target_not_ready",
                error_message=result.error_message,
                phase=config.phase,
            )
            return False

        return True

    async def _install_target_packages(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> bool:
        """Install packages on target device."""
        if not config.target_package_list:
            logger.info("No target packages to install")
            return True

        if not self.target_delivery_strategy:
            logger.warning("No target delivery strategy configured")
            return True

        logger.info(f"Installing {len(config.target_package_list)} packages on target")

        install_result = await self.package_orchestrator.install_phase_packages(
            workflow_state_id=workflow_state.id,
            phase=config.phase,
            package_list=config.target_package_list,
            delivery_strategy=self.target_delivery_strategy,
            target_id=str(config.target_id),
        )

        result.target_install_result = install_result

        if not install_result.can_proceed:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.INSTALLING_TARGET
            result.error_message = install_result.error_message or "Package installation failed"
            result.error_type = "install_failed"
            return False

        return True

    async def _install_jmeter_packages(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> bool:
        """Install JMeter packages on load generator."""
        if not config.jmeter_package_list:
            logger.info("No JMeter packages to install")
            return True

        if not self.jmeter_delivery_strategy:
            logger.warning("No JMeter delivery strategy configured")
            return True

        logger.info(f"Installing {len(config.jmeter_package_list)} JMeter packages")

        # Note: JMeter uses its own workflow state fields
        # For now, reuse the same orchestrator with a different target
        install_result = await self.package_orchestrator.install_phase_packages(
            workflow_state_id=workflow_state.id,
            phase="jmeter",  # Special phase for JMeter
            package_list=config.jmeter_package_list,
            delivery_strategy=self.jmeter_delivery_strategy,
            target_id=str(config.loadgen_id),
        )

        result.jmeter_install_result = install_result

        if not install_result.can_proceed:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.INSTALLING_JMETER
            result.error_message = install_result.error_message or "JMeter installation failed"
            result.error_type = "jmeter_install_failed"
            return False

        return True

    async def _start_emulator(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> bool:
        """Start CPU emulator on target."""
        if not self.emulator_manager or not config.jmeter_config:
            return True

        logger.info(f"Starting emulator on target {config.target_id}")

        # Get thread count and target CPU from JMeter config or calibration
        thread_count = config.jmeter_config.thread_count
        target_cpu = 50.0  # Default, should come from calibration

        success, error = await self.emulator_manager.start_emulator(
            target_id=config.target_id,
            thread_count=thread_count,
            target_cpu_percent=target_cpu,
        )

        if not success:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.STARTING_EMULATOR
            result.error_message = error or "Emulator start failed"
            result.error_type = "emulator_failed"

            await self.workflow_service.record_error(
                workflow_state_id=workflow_state.id,
                error_type="emulator_failed",
                error_message=result.error_message,
                phase=config.phase,
            )
            return False

        return True

    async def _run_load_test(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> bool:
        """Run JMeter load test."""
        if not config.jmeter_config:
            logger.info("No JMeter config, skipping load test")
            return True

        logger.info("Starting JMeter load test")

        execution_result, jmeter_result = await self.jmeter_service.run_and_collect(
            config=config.jmeter_config,
        )

        if not execution_result.success:
            result.stage_reached = PhaseStage.FAILED
            result.error_stage = PhaseStage.RUNNING_LOAD_TEST
            result.error_message = execution_result.error_message or "Load test failed"
            result.error_type = "load_test_failed"

            await self.workflow_service.record_error(
                workflow_state_id=workflow_state.id,
                error_type="load_test_failed",
                error_message=result.error_message,
                phase=config.phase,
            )
            return False

        return True

    async def _run_functional_tests(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> None:
        """Run functional/policy tests from other_package_lst."""
        functional_packages = [
            p for p in config.target_package_list
            if p.get("package_type") in ("functional", "policy")
            and p.get("run_at_load", False)
        ]

        if not functional_packages:
            logger.info("No functional tests to run")
            return

        logger.info(f"Running {len(functional_packages)} functional/policy tests")

        # These would be executed via the delivery strategy
        # Results are collected in the result collection phase
        for pkg in functional_packages:
            if self.target_delivery_strategy:
                # Execute the package's run_at_load command
                pass

    async def _collect_results(
        self,
        workflow_state: ExecutionWorkflowStateORM,
        config: PhaseExecutionConfig,
        result: PhaseExecutionResult,
    ) -> PhaseResults:
        """Collect all results for the phase."""
        logger.info("Collecting phase results")

        phase_results = await self.result_collector.collect_phase_results(
            phase=config.phase,
            loadprofile=config.loadprofile,
            package_list=config.target_package_list,
            jmeter_config=config.jmeter_config.__dict__ if config.jmeter_config else None,
            jmeter_package_id=config.jmeter_package_id,
        )

        # Store results in workflow state
        await self.workflow_service.store_phase_results(
            workflow_state_id=workflow_state.id,
            phase_results=phase_results,
        )

        return phase_results

    def _handle_cancellation(
        self,
        result: PhaseExecutionResult,
    ) -> PhaseExecutionResult:
        """Handle execution cancellation."""
        result.stage_reached = PhaseStage.FAILED
        result.error_message = "Execution cancelled"
        result.error_type = "cancelled"
        return result

    async def cancel(self) -> None:
        """Cancel the current phase execution."""
        self._cancelled = True
        await self.jmeter_service.cancel()
