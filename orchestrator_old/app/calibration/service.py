"""Calibration service for managing calibration workflows."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Callable, Awaitable

from .models import (
    CalibrationConfig,
    CalibrationResult,
    CalibrationRun,
    CalibrationStatus,
    IterationStats,
    LoadProfile,
)
from .algorithm import CalibrationAlgorithm
from .emulator_client import EmulatorClient


@dataclass
class TargetDeployment:
    """Deployment info for a target server."""
    target_id: int
    server_id: int
    loadgenerator_id: int
    emulator_host: str
    emulator_port: int
    deployed: bool = False
    error: Optional[str] = None


@dataclass
class ScenarioCalibrationResult:
    """Result of calibrating all targets in a scenario."""
    scenario_id: int
    deployments: List[TargetDeployment]
    results: List[CalibrationResult]
    all_succeeded: bool
    errors: List[str]


class CalibrationService:
    """
    Service for calibrating thread counts.

    Orchestrates the calibration process:
    1. Connects to emulator
    2. Runs binary search to find optimal threads
    3. Measures iteration timing for HIGH profile
    4. Stores results
    """

    def __init__(
        self,
        config: Optional[CalibrationConfig] = None,
    ):
        self._config = config or CalibrationConfig()
        self._algorithm = CalibrationAlgorithm(self._config)

    @property
    def config(self) -> CalibrationConfig:
        """Get calibration configuration."""
        return self._config

    async def calibrate_target(
        self,
        target_id: int,
        baseline_id: int,
        loadprofile: LoadProfile,
        emulator_host: str,
        emulator_port: int,
        cpu_count: Optional[int] = None,
        memory_gb: Optional[float] = None,
    ) -> CalibrationResult:
        """
        Calibrate thread count for a specific target and load profile.

        Args:
            target_id: Target server ID
            baseline_id: Baseline configuration ID
            loadprofile: Target load profile (LOW, MEDIUM, HIGH)
            emulator_host: Emulator service host
            emulator_port: Emulator service port
            cpu_count: CPU count (for metadata)
            memory_gb: Memory in GB (for metadata)

        Returns:
            CalibrationResult with optimal thread count
        """
        client = EmulatorClient(emulator_host, emulator_port)

        # Check emulator health
        if not await client.health_check():
            return CalibrationResult(
                target_id=target_id,
                baseline_id=baseline_id,
                loadprofile=loadprofile,
                status=CalibrationStatus.FAILED,
                thread_count=0,
                cpu_target_percent=self._algorithm.get_target_cpu(loadprofile),
                achieved_cpu_percent=0.0,
                error_message="Emulator is not reachable",
            )

        try:
            # Define test runner function for algorithm
            async def run_test(thread_count: int) -> float:
                avg_cpu, _ = await client.run_calibration_test(
                    thread_count=thread_count,
                    duration_sec=self._config.calibration_duration_sec,
                    warmup_sec=self._config.warmup_sec,
                )
                return avg_cpu

            # Run calibration
            optimal_threads, achieved_cpu, runs = await self._algorithm.calibrate(
                loadprofile=loadprofile,
                run_test=run_test,
            )

            # For HIGH profile, also measure iteration timing
            iteration_stats: Optional[IterationStats] = None
            if loadprofile == LoadProfile.HIGH:
                timings = await client.run_timing_test(
                    thread_count=optimal_threads,
                    iterations=self._config.iteration_sample_count,
                )
                iteration_stats = self._algorithm.calculate_iteration_stats(timings)

            return CalibrationResult(
                target_id=target_id,
                baseline_id=baseline_id,
                loadprofile=loadprofile,
                status=CalibrationStatus.COMPLETED,
                thread_count=optimal_threads,
                cpu_target_percent=self._algorithm.get_target_cpu(loadprofile),
                achieved_cpu_percent=achieved_cpu,
                avg_iteration_time_ms=int(iteration_stats.avg_ms) if iteration_stats else None,
                stddev_iteration_time_ms=int(iteration_stats.stddev_ms) if iteration_stats else None,
                min_iteration_time_ms=int(iteration_stats.min_ms) if iteration_stats else None,
                max_iteration_time_ms=int(iteration_stats.max_ms) if iteration_stats else None,
                iteration_sample_count=iteration_stats.sample_count if iteration_stats else None,
                calibrated_at=datetime.utcnow(),
                calibration_runs=runs,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
            )

        except Exception as e:
            return CalibrationResult(
                target_id=target_id,
                baseline_id=baseline_id,
                loadprofile=loadprofile,
                status=CalibrationStatus.FAILED,
                thread_count=0,
                cpu_target_percent=self._algorithm.get_target_cpu(loadprofile),
                achieved_cpu_percent=0.0,
                error_message=str(e),
            )

    async def calibrate_all_profiles(
        self,
        target_id: int,
        baseline_id: int,
        emulator_host: str,
        emulator_port: int,
        profiles: Optional[List[LoadProfile]] = None,
        cpu_count: Optional[int] = None,
        memory_gb: Optional[float] = None,
    ) -> List[CalibrationResult]:
        """
        Calibrate all specified load profiles for a target.

        Args:
            target_id: Target server ID
            baseline_id: Baseline configuration ID
            emulator_host: Emulator service host
            emulator_port: Emulator service port
            profiles: List of profiles to calibrate (default: all)
            cpu_count: CPU count (for metadata)
            memory_gb: Memory in GB (for metadata)

        Returns:
            List of CalibrationResult for each profile
        """
        if profiles is None:
            profiles = [LoadProfile.LOW, LoadProfile.MEDIUM, LoadProfile.HIGH]

        results = []
        for profile in profiles:
            result = await self.calibrate_target(
                target_id=target_id,
                baseline_id=baseline_id,
                loadprofile=profile,
                emulator_host=emulator_host,
                emulator_port=emulator_port,
                cpu_count=cpu_count,
                memory_gb=memory_gb,
            )
            results.append(result)

        return results

    def estimate_test_loops(
        self,
        calibration_result: CalibrationResult,
        test_duration_sec: int,
    ) -> int:
        """
        Estimate loop count for a test based on calibration results.

        Args:
            calibration_result: Calibration result with iteration timing
            test_duration_sec: Target test duration in seconds

        Returns:
            Estimated loop count
        """
        if not calibration_result.avg_iteration_time_ms:
            # No timing data, use default estimate
            return self._algorithm.estimate_loop_count(
                duration_sec=test_duration_sec,
                avg_iteration_ms=100.0,  # Default assumption
            )

        return self._algorithm.estimate_loop_count(
            duration_sec=test_duration_sec,
            avg_iteration_ms=float(calibration_result.avg_iteration_time_ms),
        )

    def validate_calibration(
        self,
        result: CalibrationResult,
    ) -> tuple[bool, str]:
        """
        Validate a calibration result.

        Returns:
            Tuple of (is_valid, message)
        """
        if result.status != CalibrationStatus.COMPLETED:
            return False, f"Calibration not completed: {result.error_message}"

        if result.thread_count <= 0:
            return False, "Invalid thread count"

        target_cpu = self._algorithm.get_target_cpu(result.loadprofile)
        diff = abs(result.achieved_cpu_percent - target_cpu)

        if diff > self._config.tolerance:
            return False, (
                f"Achieved CPU {result.achieved_cpu_percent:.1f}% "
                f"is outside tolerance of target {target_cpu:.1f}% "
                f"(±{self._config.tolerance}%)"
            )

        # For HIGH profile, check iteration timing is available
        if result.loadprofile == LoadProfile.HIGH:
            if not result.avg_iteration_time_ms:
                return False, "HIGH profile requires iteration timing data"

        return True, "Calibration is valid"

    # =========================================================================
    # Multi-Target Calibration with Barrier Synchronization
    # =========================================================================

    async def deploy_single_target(
        self,
        target: TargetDeployment,
        deploy_func: Callable[[int, int], Awaitable[bool]],
    ) -> TargetDeployment:
        """
        Deploy packages to a single target (used in parallel deployment).

        Args:
            target: Target deployment info
            deploy_func: Async function(server_id, loadgen_id) -> success

        Returns:
            Updated TargetDeployment with result
        """
        try:
            success = await deploy_func(target.server_id, target.loadgenerator_id)
            target.deployed = success
            if not success:
                target.error = "Deployment returned False"
        except Exception as e:
            target.deployed = False
            target.error = str(e)
        return target

    async def deploy_all_targets(
        self,
        targets: List[TargetDeployment],
        deploy_func: Callable[[int, int], Awaitable[bool]],
    ) -> List[TargetDeployment]:
        """
        Deploy to ALL targets in parallel, then wait at barrier.

        This implements the calibration deployment model:
        1. Deploy packages to all targets in parallel
        2. BARRIER: Wait for all deployments to complete
        3. Return results for calibration phase

        Args:
            targets: List of targets to deploy to
            deploy_func: Async function(server_id, loadgen_id) -> success

        Returns:
            List of TargetDeployment with deployment results
        """
        # Deploy all targets in parallel
        tasks = [
            self.deploy_single_target(target, deploy_func)
            for target in targets
        ]

        # BARRIER: Wait for all deployments to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        deployed_targets = []
        for result in results:
            if isinstance(result, Exception):
                # Create failed deployment for exceptions
                failed = TargetDeployment(
                    target_id=0,
                    server_id=0,
                    loadgenerator_id=0,
                    emulator_host="",
                    emulator_port=0,
                    deployed=False,
                    error=str(result),
                )
                deployed_targets.append(failed)
            else:
                deployed_targets.append(result)

        return deployed_targets

    async def calibrate_scenario(
        self,
        scenario_id: int,
        targets: List[TargetDeployment],
        deploy_func: Callable[[int, int], Awaitable[bool]],
        profiles: Optional[List[LoadProfile]] = None,
    ) -> ScenarioCalibrationResult:
        """
        Calibrate all targets in a scenario with proper barrier sync.

        Calibration Flow:
        1. Deploy to ALL targets in parallel (emulator + JMeter)
        2. ════════ BARRIER ════════ (wait for all deployments)
        3. For each loadprofile:
           a. Calibrate all targets for that profile
        4. Return combined results

        Args:
            scenario_id: Scenario ID
            targets: List of targets to calibrate
            deploy_func: Async function for deployment
            profiles: Load profiles to calibrate (default: all)

        Returns:
            ScenarioCalibrationResult with all results
        """
        if profiles is None:
            profiles = [LoadProfile.LOW, LoadProfile.MEDIUM, LoadProfile.HIGH]

        all_results: List[CalibrationResult] = []
        errors: List[str] = []

        # Phase 1: Deploy to ALL targets in parallel
        deployed_targets = await self.deploy_all_targets(targets, deploy_func)

        # Check for deployment failures
        failed_deployments = [t for t in deployed_targets if not t.deployed]
        if failed_deployments:
            for t in failed_deployments:
                errors.append(f"Target {t.target_id} deployment failed: {t.error}")

            # Return early if any deployment failed
            return ScenarioCalibrationResult(
                scenario_id=scenario_id,
                deployments=deployed_targets,
                results=[],
                all_succeeded=False,
                errors=errors,
            )

        # ════════ BARRIER PASSED ════════
        # All deployments succeeded, proceed to calibration

        # Phase 2: Calibrate each loadprofile
        for profile in profiles:
            # Calibrate all targets for this profile (can be parallel too)
            profile_tasks = [
                self.calibrate_target(
                    target_id=t.target_id,
                    baseline_id=0,  # Will be determined by caller
                    loadprofile=profile,
                    emulator_host=t.emulator_host,
                    emulator_port=t.emulator_port,
                )
                for t in deployed_targets
            ]

            profile_results = await asyncio.gather(*profile_tasks)

            for result in profile_results:
                all_results.append(result)
                if result.status != CalibrationStatus.COMPLETED:
                    errors.append(
                        f"Target {result.target_id} {profile.value} calibration failed: "
                        f"{result.error_message}"
                    )

        return ScenarioCalibrationResult(
            scenario_id=scenario_id,
            deployments=deployed_targets,
            results=all_results,
            all_succeeded=len(errors) == 0,
            errors=errors,
        )
