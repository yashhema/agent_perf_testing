"""Test executor for running tests across all servers in a scenario.

Handles the TEST EXECUTION phase (after setup/calibration is complete).
Implements barrier-based execution where each stage must complete
for ALL servers before the next stage begins.

Stages:
1. Restore baseline (all servers)
2. Install target packages (all servers)
3. Install JMeter packages (all servers)
4. Deploy JMX test plans (all servers)
-- BARRIER --
5. Start emulator (all servers)
-- BARRIER --
6. Run load test (all servers)
-- BARRIER --
7. Run functional tests (all servers)
-- BARRIER --
8. Collect results & stop emulator (all servers)

This runs AFTER ScenarioOrchestrator has completed setup and calibration.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, Callable, Awaitable
from enum import Enum

from app.models.enums import WorkflowState, PhaseState, LoadProfile
from app.models.orm import ExecutionWorkflowStateORM, TestRunTargetORM
from app.services.workflow_state_service import WorkflowStateService
from app.packages.orchestrator import PackageInstallOrchestrator
from app.packages.delivery import DeliveryStrategy
from app.jmeter.service import JMeterService
from app.jmeter.models import JMeterConfig
from app.jmeter.deployment import JMXDeploymentService, TestPlanSpec, SSHFileTransfer
from app.results.collector import ResultCollector
from app.results.models import PhaseResults
from app.calibration.emulator_client import EmulatorClient


logger = logging.getLogger(__name__)


class ExecutionStage(str, Enum):
    """Stages in test execution."""

    INITIALIZING = "initializing"
    RESTORING = "restoring"
    INSTALLING_TARGET = "installing_target"
    INSTALLING_JMETER = "installing_jmeter"
    DEPLOYING_JMX = "deploying_jmx"
    STARTING_EMULATOR = "starting_emulator"
    RUNNING_LOAD_TEST = "running_load_test"
    RUNNING_FUNCTIONAL = "running_functional"
    COLLECTING_RESULTS = "collecting_results"
    COMPLETED = "completed"
    FAILED = "failed"


class SnapshotManager(Protocol):
    """Protocol for snapshot/baseline management."""

    async def restore_snapshot(
        self,
        target_id: int,
        baseline_id: int,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        ...

    async def wait_for_target_ready(
        self,
        target_id: int,
        timeout_sec: int = 300,
    ) -> bool:
        ...


class EmulatorManager(Protocol):
    """Protocol for CPU emulator management."""

    async def start_emulator(
        self,
        target_id: int,
        thread_count: int,
        target_cpu_percent: float,
    ) -> tuple[bool, Optional[str]]:
        ...

    async def stop_emulator(
        self,
        target_id: int,
    ) -> bool:
        ...

    async def get_emulator_stats(
        self,
        target_id: int,
    ) -> Optional[dict]:
        ...


@dataclass
class TargetConfig:
    """Configuration for a single target in the scenario."""

    target_id: int
    target_ip: str
    target_hostname: str
    target_port: int

    loadgen_id: int
    loadgen_ip: str
    jmeter_port: int

    baseline_id: int

    # Calibration data per load profile
    calibration: dict[str, dict]  # {loadprofile: {thread_count, cpu_target}}

    # Package lists
    target_packages: list[dict] = field(default_factory=list)
    jmeter_packages: list[dict] = field(default_factory=list)

    # JMX path (None = generate dynamically)
    jmx_file_path: Optional[str] = None


@dataclass
class TestExecutionConfig:
    """Configuration for scenario execution."""

    test_run_id: int
    scenario_id: int
    phase: str  # "base", "initial", "upgrade"
    loadprofile: str  # "low", "medium", "high"

    # All targets in this scenario
    targets: list[TargetConfig] = field(default_factory=list)

    # Timing
    warmup_sec: int = 60
    measured_sec: int = 600

    # Timeouts
    restore_timeout_sec: int = 600
    install_timeout_sec: int = 1200
    load_test_timeout_sec: int = 14400


@dataclass
class TargetResult:
    """Result for a single target."""

    target_id: int
    success: bool
    stage_reached: ExecutionStage
    error_message: Optional[str] = None
    phase_results: Optional[PhaseResults] = None


@dataclass
class TestExecutionResult:
    """Result of test execution across all targets."""

    phase: str
    loadprofile: str
    success: bool
    stage_reached: ExecutionStage

    target_results: dict[int, TargetResult] = field(default_factory=dict)

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: float = 0

    error_message: Optional[str] = None


class TestExecutor:
    """
    Orchestrates execution across all servers in a scenario.

    Uses barrier synchronization to ensure all servers complete
    each stage before moving to the next.
    """

    def __init__(
        self,
        workflow_service: WorkflowStateService,
        package_orchestrator: PackageInstallOrchestrator,
        jmeter_service: JMeterService,
        jmx_deployment_service: JMXDeploymentService,
        result_collector: ResultCollector,
        snapshot_manager: SnapshotManager,
        emulator_manager: EmulatorManager,
        # Per-target factories
        target_delivery_factory: Callable[[int], DeliveryStrategy],
        loadgen_delivery_factory: Callable[[int], DeliveryStrategy],
        ssh_transfer_factory: Callable[[int], SSHFileTransfer],
    ):
        self.workflow_service = workflow_service
        self.package_orchestrator = package_orchestrator
        self.jmeter_service = jmeter_service
        self.jmx_deployment_service = jmx_deployment_service
        self.result_collector = result_collector
        self.snapshot_manager = snapshot_manager
        self.emulator_manager = emulator_manager
        self.target_delivery_factory = target_delivery_factory
        self.loadgen_delivery_factory = loadgen_delivery_factory
        self.ssh_transfer_factory = ssh_transfer_factory

        self._cancelled = False
        self._jmeter_configs: dict[int, JMeterConfig] = {}  # target_id -> config

    async def execute_scenario(
        self,
        config: TestExecutionConfig,
        workflow_states: dict[int, ExecutionWorkflowStateORM],  # target_id -> state
    ) -> TestExecutionResult:
        """
        Execute scenario across all targets with barrier synchronization.

        Args:
            config: Scenario configuration
            workflow_states: Workflow state per target

        Returns:
            TestExecutionResult with outcomes for all targets
        """
        result = TestExecutionResult(
            phase=config.phase,
            loadprofile=config.loadprofile,
            success=False,
            stage_reached=ExecutionStage.INITIALIZING,
            started_at=datetime.utcnow(),
        )

        self._cancelled = False
        self._jmeter_configs = {}

        try:
            # ============================================================
            # STAGE GROUP 1-4: Preparation (parallel, then barrier)
            # ============================================================

            # Stage 1: Restore baseline for ALL servers
            result.stage_reached = ExecutionStage.RESTORING
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.RESTORING,
                stage_func=self._restore_baseline,
            )
            if not success:
                return result

            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 2: Install target packages for ALL servers
            result.stage_reached = ExecutionStage.INSTALLING_TARGET
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.INSTALLING_TARGET,
                stage_func=self._install_target_packages,
            )
            if not success:
                return result

            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 3: Install JMeter packages for ALL servers
            result.stage_reached = ExecutionStage.INSTALLING_JMETER
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.INSTALLING_JMETER,
                stage_func=self._install_jmeter_packages,
            )
            if not success:
                return result

            if self._cancelled:
                return self._handle_cancellation(result)

            # Stage 3.5: Deploy JMX for ALL servers
            result.stage_reached = ExecutionStage.DEPLOYING_JMX
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.DEPLOYING_JMX,
                stage_func=self._deploy_jmx,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All servers completed preparation ===")

            if self._cancelled:
                return self._handle_cancellation(result)

            # ============================================================
            # STAGE 5: Start emulator (parallel, then barrier)
            # ============================================================

            result.stage_reached = ExecutionStage.STARTING_EMULATOR
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.STARTING_EMULATOR,
                stage_func=self._start_emulator,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All emulators started ===")

            if self._cancelled:
                return self._handle_cancellation(result)

            # ============================================================
            # STAGE 6: Run load test (parallel, then barrier)
            # ============================================================

            result.stage_reached = ExecutionStage.RUNNING_LOAD_TEST
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.RUNNING_LOAD_TEST,
                stage_func=self._run_load_test,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All load tests completed ===")

            if self._cancelled:
                return self._handle_cancellation(result)

            # ============================================================
            # STAGE 7: Run functional tests (parallel, then barrier)
            # ============================================================

            result.stage_reached = ExecutionStage.RUNNING_FUNCTIONAL
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.RUNNING_FUNCTIONAL,
                stage_func=self._run_functional_tests,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All functional tests completed ===")

            # ============================================================
            # STAGE 8: Collect results & cleanup (parallel, then barrier)
            # ============================================================

            result.stage_reached = ExecutionStage.COLLECTING_RESULTS
            success = await self._execute_stage_for_all(
                config, workflow_states, result,
                stage=ExecutionStage.COLLECTING_RESULTS,
                stage_func=self._collect_results_and_cleanup,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All results collected ===")

            # ============================================================
            # SUCCESS
            # ============================================================

            result.stage_reached = ExecutionStage.COMPLETED
            result.success = True

        except asyncio.CancelledError:
            return self._handle_cancellation(result)

        except Exception as e:
            logger.error(f"Scenario execution failed: {e}")
            result.error_message = str(e)
            result.stage_reached = ExecutionStage.FAILED

        finally:
            result.completed_at = datetime.utcnow()
            if result.started_at:
                result.duration_sec = (
                    result.completed_at - result.started_at
                ).total_seconds()

        return result

    async def _execute_stage_for_all(
        self,
        config: TestExecutionConfig,
        workflow_states: dict[int, ExecutionWorkflowStateORM],
        result: TestExecutionResult,
        stage: ExecutionStage,
        stage_func: Callable,
    ) -> bool:
        """
        Execute a stage for all targets in parallel, wait for all to complete.

        Returns True if all succeeded, False if any failed.
        """
        logger.info(f"Starting stage {stage.value} for {len(config.targets)} targets")

        # Create tasks for all targets
        tasks = []
        for target_config in config.targets:
            workflow_state = workflow_states.get(target_config.target_id)
            if not workflow_state:
                logger.warning(f"No workflow state for target {target_config.target_id}")
                continue

            task = asyncio.create_task(
                stage_func(config, target_config, workflow_state),
                name=f"{stage.value}_{target_config.target_id}",
            )
            tasks.append((target_config.target_id, task))

        # Wait for all tasks to complete
        all_success = True
        for target_id, task in tasks:
            try:
                success, error = await task

                if success:
                    logger.info(f"Target {target_id} completed stage {stage.value}")
                else:
                    logger.error(f"Target {target_id} failed stage {stage.value}: {error}")
                    all_success = False

                    # Update target result
                    if target_id not in result.target_results:
                        result.target_results[target_id] = TargetResult(
                            target_id=target_id,
                            success=False,
                            stage_reached=stage,
                        )
                    result.target_results[target_id].success = False
                    result.target_results[target_id].error_message = error

            except Exception as e:
                logger.error(f"Target {target_id} exception in stage {stage.value}: {e}")
                all_success = False

                if target_id not in result.target_results:
                    result.target_results[target_id] = TargetResult(
                        target_id=target_id,
                        success=False,
                        stage_reached=stage,
                    )
                result.target_results[target_id].error_message = str(e)

        if not all_success:
            result.stage_reached = ExecutionStage.FAILED
            result.error_message = f"One or more targets failed at stage {stage.value}"

        return all_success

    # ================================================================
    # Individual stage implementations
    # ================================================================

    async def _restore_baseline(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Restore baseline for a single target."""
        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.RESTORING_BASELINE.value,
        )

        success, error = await self.snapshot_manager.restore_snapshot(
            target_id=target.target_id,
            baseline_id=target.baseline_id,
            timeout_sec=config.restore_timeout_sec,
        )

        if not success:
            return False, error

        ready = await self.snapshot_manager.wait_for_target_ready(
            target_id=target.target_id,
            timeout_sec=300,
        )

        if not ready:
            return False, "Target not ready after restore"

        return True, None

    async def _install_target_packages(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Install packages on target."""
        if not target.target_packages:
            return True, None

        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.INSTALLING_AGENT.value,
        )

        delivery_strategy = self.target_delivery_factory(target.target_id)

        install_result = await self.package_orchestrator.install_phase_packages(
            workflow_state_id=workflow_state.id,
            phase=config.phase,
            package_list=target.target_packages,
            delivery_strategy=delivery_strategy,
            target_id=str(target.target_id),
        )

        if not install_result.can_proceed:
            return False, install_result.error_message

        return True, None

    async def _install_jmeter_packages(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Install JMeter packages on load generator."""
        if not target.jmeter_packages:
            return True, None

        delivery_strategy = self.loadgen_delivery_factory(target.loadgen_id)

        install_result = await self.package_orchestrator.install_phase_packages(
            workflow_state_id=workflow_state.id,
            phase="jmeter",
            package_list=target.jmeter_packages,
            delivery_strategy=delivery_strategy,
            target_id=str(target.loadgen_id),
        )

        if not install_result.can_proceed:
            return False, install_result.error_message

        return True, None

    async def _deploy_jmx(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Generate and deploy JMX test plan."""
        # Get calibration data for this load profile
        calibration = target.calibration.get(config.loadprofile, {})
        thread_count = calibration.get("thread_count", 10)

        # If JMX path is provided, use it; otherwise generate
        if target.jmx_file_path:
            jmx_path = target.jmx_file_path
        else:
            # Generate JMX
            spec = TestPlanSpec(
                target_host=target.target_ip,
                target_port=target.target_port,
                thread_count=thread_count,
                warmup_sec=config.warmup_sec,
                measured_sec=config.measured_sec,
                test_run_id=config.test_run_id,
                target_id=target.target_id,
                load_profile=config.loadprofile,
            )

            ssh_transfer = self.ssh_transfer_factory(target.loadgen_id)

            success, jmx_path, error = await self.jmx_deployment_service.deploy_jmx(
                ssh_transfer=ssh_transfer,
                spec=spec,
            )

            if not success:
                return False, error

        # Create JMeterConfig and store for later use
        spec = TestPlanSpec(
            target_host=target.target_ip,
            target_port=target.target_port,
            thread_count=thread_count,
            warmup_sec=config.warmup_sec,
            measured_sec=config.measured_sec,
            test_run_id=config.test_run_id,
            target_id=target.target_id,
            load_profile=config.loadprofile,
        )

        jmeter_config = self.jmx_deployment_service.create_jmeter_config(
            spec=spec,
            jmx_path=jmx_path,
        )

        self._jmeter_configs[target.target_id] = jmeter_config

        return True, None

    async def _start_emulator(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Start emulator on target."""
        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.STARTING_EMULATOR.value,
        )

        calibration = target.calibration.get(config.loadprofile, {})
        thread_count = calibration.get("thread_count", 10)
        cpu_target = calibration.get("cpu_target", 50.0)

        success, error = await self.emulator_manager.start_emulator(
            target_id=target.target_id,
            thread_count=thread_count,
            target_cpu_percent=cpu_target,
        )

        return success, error

    async def _run_load_test(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Run JMeter load test."""
        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.RUNNING_LOAD.value,
        )

        jmeter_config = self._jmeter_configs.get(target.target_id)
        if not jmeter_config:
            return False, "No JMeter config available"

        execution_result, jmeter_result = await self.jmeter_service.run_and_collect(
            config=jmeter_config,
        )

        if not execution_result.success:
            return False, execution_result.error_message

        return True, None

    async def _run_functional_tests(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Run functional/policy tests."""
        functional_packages = [
            p for p in target.target_packages
            if p.get("package_type") in ("functional", "policy")
            and p.get("run_at_load", False)
        ]

        if not functional_packages:
            return True, None

        # Execute functional tests via delivery strategy
        delivery_strategy = self.target_delivery_factory(target.target_id)

        for pkg in functional_packages:
            # Run the package's execution command
            # Results are collected in the next stage
            pass

        return True, None

    async def _collect_results_and_cleanup(
        self,
        config: TestExecutionConfig,
        target: TargetConfig,
        workflow_state: ExecutionWorkflowStateORM,
    ) -> tuple[bool, Optional[str]]:
        """Collect results and stop emulator."""
        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.COLLECTING_RESULTS.value,
        )

        jmeter_config = self._jmeter_configs.get(target.target_id)

        # Collect results
        phase_results = await self.result_collector.collect_phase_results(
            phase=config.phase,
            loadprofile=config.loadprofile,
            package_list=target.target_packages,
            jmeter_config=jmeter_config.__dict__ if jmeter_config else None,
            jmeter_package_id=None,
        )

        # Store results
        await self.workflow_service.store_phase_results(
            workflow_state_id=workflow_state.id,
            phase_results=phase_results,
        )

        # Stop emulator
        await self.emulator_manager.stop_emulator(target.target_id)

        # Mark complete
        await self.workflow_service.update_phase_state(
            workflow_state_id=workflow_state.id,
            phase_state=PhaseState.COMPLETED.value,
        )

        return True, None

    def _handle_cancellation(
        self,
        result: TestExecutionResult,
    ) -> TestExecutionResult:
        """Handle execution cancellation."""
        result.stage_reached = ExecutionStage.FAILED
        result.error_message = "Execution cancelled"
        return result

    async def cancel(self) -> None:
        """Cancel scenario execution."""
        self._cancelled = True
        await self.jmeter_service.cancel()
