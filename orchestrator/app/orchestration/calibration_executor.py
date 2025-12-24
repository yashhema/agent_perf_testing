"""Calibration executor for running calibration across all servers in a scenario.

Handles the CALIBRATION phase with barrier synchronization.
All servers must complete each calibration stage before proceeding.

Stages:
1. Restore baseline (all servers)
-- BARRIER --
2. Start emulator (all servers)
-- BARRIER --
3. Calibrate LOW profile (all servers)
-- BARRIER --
4. Calibrate MEDIUM profile (all servers)
-- BARRIER --
5. Calibrate HIGH profile (all servers)
-- BARRIER --
6. Store results (all servers)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, Callable
from enum import Enum

from app.calibration.models import LoadProfile, CalibrationResult, CalibrationStatus
from app.calibration.service import CalibrationService
from app.calibration.emulator_client import EmulatorClient


logger = logging.getLogger(__name__)


class CalibrationStage(str, Enum):
    """Stages in calibration execution."""

    INITIALIZING = "initializing"
    RESTORING = "restoring"
    STARTING_EMULATOR = "starting_emulator"
    CALIBRATING_LOW = "calibrating_low"
    CALIBRATING_MEDIUM = "calibrating_medium"
    CALIBRATING_HIGH = "calibrating_high"
    STORING_RESULTS = "storing_results"
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


@dataclass
class CalibrationTargetConfig:
    """Configuration for a single target in calibration."""

    target_id: int
    target_ip: str
    target_hostname: str
    emulator_port: int

    baseline_id: int

    cpu_count: int = 4
    memory_gb: float = 8.0


@dataclass
class CalibrationExecutionConfig:
    """Configuration for calibration execution."""

    test_run_id: int
    scenario_id: int

    # All targets to calibrate
    targets: list[CalibrationTargetConfig] = field(default_factory=list)

    # Profiles to calibrate
    profiles: list[str] = field(default_factory=lambda: ["low", "medium", "high"])

    # Calibration settings
    calibration_duration_sec: int = 60
    warmup_sec: int = 10
    tolerance_percent: float = 5.0

    # Timeouts
    restore_timeout_sec: int = 600


@dataclass
class TargetCalibrationResult:
    """Calibration result for a single target."""

    target_id: int
    success: bool
    stage_reached: CalibrationStage

    # Results per profile
    profile_results: dict[str, CalibrationResult] = field(default_factory=dict)

    error_message: Optional[str] = None


@dataclass
class CalibrationExecutionResult:
    """Result of calibration execution across all targets."""

    scenario_id: int
    success: bool
    stage_reached: CalibrationStage

    target_results: dict[int, TargetCalibrationResult] = field(default_factory=dict)

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: float = 0

    error_message: Optional[str] = None

    def get_thread_count(self, target_id: int, profile: str) -> Optional[int]:
        """Get calibrated thread count for a target and profile."""
        target_result = self.target_results.get(target_id)
        if not target_result:
            return None

        profile_result = target_result.profile_results.get(profile.lower())
        if not profile_result:
            return None

        return profile_result.thread_count

    def get_all_calibrations(self) -> dict[int, dict[str, CalibrationResult]]:
        """Get all calibration results organized by target and profile."""
        result = {}
        for target_id, target_result in self.target_results.items():
            result[target_id] = target_result.profile_results
        return result


class CalibrationExecutor:
    """
    Executes calibration across all servers in a scenario.

    Uses barrier synchronization to ensure all servers complete
    each stage before moving to the next.
    """

    def __init__(
        self,
        calibration_service: CalibrationService,
        snapshot_manager: SnapshotManager,
        # Per-target emulator client factory
        emulator_client_factory: Callable[[int, str, int], EmulatorClient],
    ):
        self.calibration_service = calibration_service
        self.snapshot_manager = snapshot_manager
        self.emulator_client_factory = emulator_client_factory

        self._cancelled = False
        self._emulator_clients: dict[int, EmulatorClient] = {}

    async def execute_calibration(
        self,
        config: CalibrationExecutionConfig,
    ) -> CalibrationExecutionResult:
        """
        Execute calibration across all targets with barrier synchronization.

        Args:
            config: Calibration configuration

        Returns:
            CalibrationExecutionResult with outcomes for all targets
        """
        result = CalibrationExecutionResult(
            scenario_id=config.scenario_id,
            success=False,
            stage_reached=CalibrationStage.INITIALIZING,
            started_at=datetime.utcnow(),
        )

        self._cancelled = False
        self._emulator_clients = {}

        # Initialize target results
        for target in config.targets:
            result.target_results[target.target_id] = TargetCalibrationResult(
                target_id=target.target_id,
                success=False,
                stage_reached=CalibrationStage.INITIALIZING,
            )

        try:
            # ============================================================
            # STAGE 1: Restore baseline (all servers)
            # ============================================================

            result.stage_reached = CalibrationStage.RESTORING
            success = await self._execute_stage_for_all(
                config, result,
                stage=CalibrationStage.RESTORING,
                stage_func=self._restore_baseline,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All servers restored ===")

            if self._cancelled:
                return self._handle_cancellation(result)

            # ============================================================
            # STAGE 2: Start emulator (all servers)
            # ============================================================

            result.stage_reached = CalibrationStage.STARTING_EMULATOR
            success = await self._execute_stage_for_all(
                config, result,
                stage=CalibrationStage.STARTING_EMULATOR,
                stage_func=self._start_emulator,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All emulators started ===")

            if self._cancelled:
                return self._handle_cancellation(result)

            # ============================================================
            # STAGE 3-5: Calibrate each profile (with barriers)
            # ============================================================

            profile_stages = {
                "low": CalibrationStage.CALIBRATING_LOW,
                "medium": CalibrationStage.CALIBRATING_MEDIUM,
                "high": CalibrationStage.CALIBRATING_HIGH,
            }

            for profile in config.profiles:
                stage = profile_stages.get(profile.lower(), CalibrationStage.CALIBRATING_MEDIUM)
                result.stage_reached = stage

                success = await self._execute_stage_for_all(
                    config, result,
                    stage=stage,
                    stage_func=lambda cfg, tgt, res: self._calibrate_profile(cfg, tgt, res, profile),
                )
                if not success:
                    return result

                logger.info(f"=== BARRIER: All servers completed {profile.upper()} calibration ===")

                if self._cancelled:
                    return self._handle_cancellation(result)

            # ============================================================
            # STAGE 6: Store results (all servers)
            # ============================================================

            result.stage_reached = CalibrationStage.STORING_RESULTS
            success = await self._execute_stage_for_all(
                config, result,
                stage=CalibrationStage.STORING_RESULTS,
                stage_func=self._store_results,
            )
            if not success:
                return result

            logger.info("=== BARRIER: All results stored ===")

            # ============================================================
            # SUCCESS
            # ============================================================

            result.stage_reached = CalibrationStage.COMPLETED
            result.success = True

            # Mark all targets as successful
            for target_result in result.target_results.values():
                target_result.success = True
                target_result.stage_reached = CalibrationStage.COMPLETED

        except asyncio.CancelledError:
            return self._handle_cancellation(result)

        except Exception as e:
            logger.error(f"Calibration execution failed: {e}")
            result.error_message = str(e)
            result.stage_reached = CalibrationStage.FAILED

        finally:
            result.completed_at = datetime.utcnow()
            if result.started_at:
                result.duration_sec = (
                    result.completed_at - result.started_at
                ).total_seconds()

        return result

    async def _execute_stage_for_all(
        self,
        config: CalibrationExecutionConfig,
        result: CalibrationExecutionResult,
        stage: CalibrationStage,
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
            task = asyncio.create_task(
                stage_func(config, target_config, result),
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
                    target_result = result.target_results.get(target_id)
                    if target_result:
                        target_result.success = False
                        target_result.stage_reached = stage
                        target_result.error_message = error

            except Exception as e:
                logger.error(f"Target {target_id} exception in stage {stage.value}: {e}")
                all_success = False

                target_result = result.target_results.get(target_id)
                if target_result:
                    target_result.success = False
                    target_result.stage_reached = stage
                    target_result.error_message = str(e)

        if not all_success:
            result.stage_reached = CalibrationStage.FAILED
            result.error_message = f"One or more targets failed at stage {stage.value}"

        return all_success

    # ================================================================
    # Individual stage implementations
    # ================================================================

    async def _restore_baseline(
        self,
        config: CalibrationExecutionConfig,
        target: CalibrationTargetConfig,
        result: CalibrationExecutionResult,
    ) -> tuple[bool, Optional[str]]:
        """Restore baseline for a single target."""
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

    async def _start_emulator(
        self,
        config: CalibrationExecutionConfig,
        target: CalibrationTargetConfig,
        result: CalibrationExecutionResult,
    ) -> tuple[bool, Optional[str]]:
        """Start and verify emulator on target."""
        try:
            # Create emulator client
            client = self.emulator_client_factory(
                target.target_id,
                target.target_ip,
                target.emulator_port,
            )
            self._emulator_clients[target.target_id] = client

            # Health check with retries
            for attempt in range(3):
                if await client.health_check():
                    logger.info(f"Emulator healthy on target {target.target_id}")
                    return True, None

                if attempt < 2:
                    await asyncio.sleep(5)

            return False, "Emulator health check failed after retries"

        except Exception as e:
            return False, str(e)

    async def _calibrate_profile(
        self,
        config: CalibrationExecutionConfig,
        target: CalibrationTargetConfig,
        result: CalibrationExecutionResult,
        profile: str,
    ) -> tuple[bool, Optional[str]]:
        """Calibrate a single profile for a single target."""
        try:
            # Map profile string to enum
            profile_map = {
                "low": LoadProfile.LOW,
                "medium": LoadProfile.MEDIUM,
                "high": LoadProfile.HIGH,
            }
            load_profile = profile_map.get(profile.lower(), LoadProfile.MEDIUM)

            # Run calibration
            calibration_result = await self.calibration_service.calibrate_target(
                target_id=target.target_id,
                baseline_id=target.baseline_id,
                loadprofile=load_profile,
                emulator_host=target.target_ip,
                emulator_port=target.emulator_port,
                cpu_count=target.cpu_count,
                memory_gb=target.memory_gb,
            )

            # Store result
            target_result = result.target_results.get(target.target_id)
            if target_result:
                target_result.profile_results[profile.lower()] = calibration_result

            # Validate
            if calibration_result.status != CalibrationStatus.COMPLETED:
                return False, calibration_result.error_message

            is_valid, validation_msg = self.calibration_service.validate_calibration(
                calibration_result
            )

            if not is_valid:
                return False, validation_msg

            logger.info(
                f"Target {target.target_id} {profile.upper()} calibration: "
                f"{calibration_result.thread_count} threads, "
                f"{calibration_result.achieved_cpu_percent:.1f}% CPU"
            )

            return True, None

        except Exception as e:
            return False, str(e)

    async def _store_results(
        self,
        config: CalibrationExecutionConfig,
        target: CalibrationTargetConfig,
        result: CalibrationExecutionResult,
    ) -> tuple[bool, Optional[str]]:
        """Store calibration results for a single target."""
        # Results are already stored in target_result.profile_results
        # This stage is for any additional persistence (database, etc.)

        target_result = result.target_results.get(target.target_id)
        if not target_result:
            return False, "No target result found"

        logger.info(
            f"Stored calibration for target {target.target_id}: "
            f"{len(target_result.profile_results)} profiles"
        )

        return True, None

    def _handle_cancellation(
        self,
        result: CalibrationExecutionResult,
    ) -> CalibrationExecutionResult:
        """Handle execution cancellation."""
        result.stage_reached = CalibrationStage.FAILED
        result.error_message = "Calibration cancelled"
        return result

    async def cancel(self) -> None:
        """Cancel calibration execution."""
        self._cancelled = True
