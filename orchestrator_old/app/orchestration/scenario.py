"""Scenario orchestrator for managing multi-server test scenarios."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Callable, Awaitable

from .models import (
    ServerSetup,
    ServerCalibration,
    ScenarioPhase,
    ScenarioState,
    SetupResult,
    SetupStatus,
    CalibrationData,
    PhaseResult,
)
from ..calibration.models import LoadProfile, CalibrationResult, CalibrationStatus
from ..calibration.service import CalibrationService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioConfig:
    """Configuration for scenario execution."""
    calibration_duration_sec: int = 60
    warmup_sec: int = 10
    tolerance_percent: float = 5.0
    max_retries: int = 2
    retry_delay_sec: int = 30
    profiles: List[str] = field(default_factory=lambda: ["low", "medium", "high"])


@dataclass(frozen=True)
class ScenarioResult:
    """Final result of scenario execution."""
    scenario_id: str
    success: bool
    phase: ScenarioPhase
    servers: List[ServerSetup]
    calibrations: Dict[int, ServerCalibration]
    phase_results: List[PhaseResult]
    started_at: datetime
    completed_at: datetime
    total_duration_sec: float
    error_message: Optional[str] = None


class ScenarioOrchestrator:
    """
    Orchestrates multi-server test scenarios.

    Handles:
    - Parallel setup of all servers
    - Barrier-synchronized calibration (per profile)
    - Validation at each barrier
    """

    def __init__(
        self,
        config: Optional[ScenarioConfig] = None,
        progress_callback: Optional[Callable[[ScenarioState], Awaitable[None]]] = None,
    ):
        self._config = config or ScenarioConfig()
        self._progress_callback = progress_callback
        self._calibration_service = CalibrationService()
        self._state: Optional[ScenarioState] = None

    @property
    def state(self) -> Optional[ScenarioState]:
        """Get current scenario state."""
        return self._state

    async def _report_progress(self) -> None:
        """Report current state to callback."""
        if self._progress_callback and self._state:
            await self._progress_callback(self._state)

    async def setup_scenario(
        self,
        servers: List[ServerSetup],
        scenario_id: Optional[str] = None,
    ) -> ScenarioResult:
        """
        Setup and calibrate a complete scenario.

        This is the main entry point that orchestrates:
        1. Setup phase (parallel package installation)
        2. Calibration phase (per-profile with barriers)

        Args:
            servers: List of servers in the scenario
            scenario_id: Optional scenario ID (generated if not provided)

        Returns:
            ScenarioResult with calibration data for all servers
        """
        # Initialize state
        self._state = ScenarioState(
            scenario_id=scenario_id or str(uuid.uuid4()),
            servers=servers,
            started_at=datetime.utcnow(),
        )

        logger.info(
            f"Starting scenario {self._state.scenario_id} with {len(servers)} servers"
        )

        try:
            # Phase 1: Setup (parallel)
            await self._execute_setup_phase()

            # Phase 2: Calibration (per-profile with barriers)
            await self._execute_calibration_phase()

            # Mark as ready
            self._state.phase = ScenarioPhase.READY
            self._state.completed_at = datetime.utcnow()

            return self._create_result(success=True)

        except Exception as e:
            logger.error(f"Scenario failed: {e}")
            self._state.phase = ScenarioPhase.FAILED
            self._state.error_message = str(e)
            self._state.completed_at = datetime.utcnow()

            return self._create_result(success=False, error_message=str(e))

    async def _execute_setup_phase(self) -> None:
        """
        Execute setup phase for all servers in parallel.

        Installs emulator and required packages on all servers.
        Waits for ALL servers to complete before proceeding.
        """
        self._state.phase = ScenarioPhase.SETUP
        await self._report_progress()

        started_at = datetime.utcnow()

        logger.info(f"Starting setup phase for {len(self._state.servers)} servers")

        # Create setup tasks for all servers
        tasks = [
            self._setup_server(server)
            for server in self._state.servers
        ]

        # Execute all in parallel and wait for all (barrier)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        succeeded = 0
        failed = 0

        for server, result in zip(self._state.servers, results):
            if isinstance(result, Exception):
                self._state.setup_results[server.server_id] = SetupResult(
                    server_id=server.server_id,
                    status=SetupStatus.FAILED,
                    error_message=str(result),
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                )
                failed += 1
            else:
                self._state.setup_results[server.server_id] = result
                if result.status == SetupStatus.COMPLETED:
                    succeeded += 1
                else:
                    failed += 1

        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        # Record phase result
        phase_result = PhaseResult(
            phase=ScenarioPhase.SETUP,
            success=failed == 0,
            started_at=started_at,
            completed_at=completed_at,
            duration_sec=duration,
            servers_succeeded=succeeded,
            servers_failed=failed,
        )
        self._state.phase_results.append(phase_result)

        logger.info(
            f"Setup phase completed: {succeeded} succeeded, {failed} failed"
        )

        if failed > 0:
            raise RuntimeError(
                f"Setup phase failed: {failed} servers failed to setup"
            )

        await self._report_progress()

    async def _setup_server(self, server: ServerSetup) -> SetupResult:
        """
        Setup a single server.

        Installs emulator and verifies it's running.
        """
        started_at = datetime.utcnow()

        logger.info(f"Setting up server {server.server_id} ({server.hostname})")

        try:
            # For Docker E2E, emulator is already running in container
            # Just verify it's healthy
            from ..calibration.emulator_client import EmulatorClient

            client = EmulatorClient(server.ip_address, server.emulator_port)

            # Health check with retries
            for attempt in range(self._config.max_retries + 1):
                if await client.health_check():
                    break
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay_sec)
            else:
                raise RuntimeError("Emulator health check failed")

            return SetupResult(
                server_id=server.server_id,
                status=SetupStatus.COMPLETED,
                emulator_installed=True,
                emulator_version="1.0.0",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Failed to setup server {server.server_id}: {e}")
            return SetupResult(
                server_id=server.server_id,
                status=SetupStatus.FAILED,
                error_message=str(e),
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

    async def _execute_calibration_phase(self) -> None:
        """
        Execute calibration phase with per-profile barriers.

        For each profile (LOW, MEDIUM, HIGH):
        1. Calibrate ALL servers in parallel
        2. Wait for all to complete (barrier)
        3. Validate all results
        4. Only proceed to next profile if all valid
        """
        self._state.phase = ScenarioPhase.CALIBRATION
        await self._report_progress()

        logger.info("Starting calibration phase")

        profiles = [p.upper() for p in self._config.profiles]

        for profile in profiles:
            await self._calibrate_profile(profile)

        logger.info("Calibration phase completed for all profiles")

    async def _calibrate_profile(self, profile: str) -> None:
        """
        Calibrate a single profile for all servers.

        All servers calibrate in parallel, then barrier + validate.
        """
        self._state.current_profile = profile
        await self._report_progress()

        started_at = datetime.utcnow()

        logger.info(f"Calibrating {profile} profile for all servers")

        # Map profile string to enum
        profile_map = {
            "LOW": LoadProfile.LOW,
            "MEDIUM": LoadProfile.MEDIUM,
            "HIGH": LoadProfile.HIGH,
        }
        load_profile = profile_map.get(profile, LoadProfile.MEDIUM)

        # Create calibration tasks for all servers
        tasks = [
            self._calibrate_server(server, load_profile)
            for server in self._state.servers
        ]

        # Execute all in parallel and wait for all (barrier)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process and validate results
        succeeded = 0
        failed = 0
        validation_errors = []

        for server, result in zip(self._state.servers, results):
            if isinstance(result, Exception):
                logger.error(
                    f"Calibration failed for server {server.server_id}: {result}"
                )
                failed += 1
                validation_errors.append(
                    f"Server {server.server_id}: {result}"
                )
            else:
                # Store calibration data
                self._state.set_calibration_data(
                    server_id=server.server_id,
                    profile=profile.lower(),
                    data=result,
                )

                if result.is_valid:
                    succeeded += 1
                else:
                    failed += 1
                    validation_errors.append(
                        f"Server {server.server_id}: {result.validation_message}"
                    )

        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        # Log results
        logger.info(
            f"{profile} calibration: {succeeded} succeeded, {failed} failed"
        )

        # Record phase result
        phase_result = PhaseResult(
            phase=ScenarioPhase.CALIBRATION,
            success=failed == 0,
            started_at=started_at,
            completed_at=completed_at,
            duration_sec=duration,
            servers_succeeded=succeeded,
            servers_failed=failed,
            details={"profile": profile},
            error_message="; ".join(validation_errors) if validation_errors else None,
        )
        self._state.phase_results.append(phase_result)

        # Fail if any server failed validation
        if failed > 0:
            raise RuntimeError(
                f"{profile} calibration failed for {failed} servers: "
                f"{'; '.join(validation_errors)}"
            )

        await self._report_progress()

    async def _calibrate_server(
        self,
        server: ServerSetup,
        load_profile: LoadProfile,
    ) -> CalibrationData:
        """
        Calibrate a single server for a single profile.

        Returns CalibrationData with validation status.
        """
        started_at = datetime.utcnow()

        logger.info(
            f"Calibrating server {server.server_id} for {load_profile.value}"
        )

        try:
            # Run calibration
            result = await self._calibration_service.calibrate_target(
                target_id=server.server_id,
                baseline_id=0,  # Using server's baseline snapshot
                loadprofile=load_profile,
                emulator_host=server.ip_address,
                emulator_port=server.emulator_port,
                cpu_count=server.cpu_count,
                memory_gb=server.memory_gb,
            )

            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()

            # Validate result
            is_valid, validation_message = self._calibration_service.validate_calibration(
                result
            )

            return CalibrationData(
                server_id=server.server_id,
                profile=load_profile.value,
                thread_count=result.thread_count,
                target_cpu_percent=result.cpu_target_percent,
                achieved_cpu_percent=result.achieved_cpu_percent,
                calibrated_at=completed_at,
                duration_sec=duration,
                is_valid=is_valid,
                validation_message=validation_message,
            )

        except Exception as e:
            logger.error(f"Calibration error for server {server.server_id}: {e}")
            raise

    def _create_result(
        self,
        success: bool,
        error_message: Optional[str] = None,
    ) -> ScenarioResult:
        """Create final scenario result."""
        started_at = self._state.started_at or datetime.utcnow()
        completed_at = self._state.completed_at or datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        return ScenarioResult(
            scenario_id=self._state.scenario_id,
            success=success,
            phase=self._state.phase,
            servers=self._state.servers,
            calibrations=self._state.calibrations,
            phase_results=self._state.phase_results,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_sec=duration,
            error_message=error_message,
        )

    def get_thread_count(
        self,
        server_id: int,
        profile: str,
    ) -> Optional[int]:
        """
        Get calibrated thread count for a server and profile.

        Use this during test runs to get the pre-calibrated value.
        """
        if not self._state:
            return None

        calibration = self._state.get_calibration(server_id)
        if not calibration:
            return None

        return calibration.get_thread_count(profile)

    def get_all_calibrations(self) -> Dict[int, ServerCalibration]:
        """Get all calibration data."""
        if not self._state:
            return {}
        return self._state.calibrations
