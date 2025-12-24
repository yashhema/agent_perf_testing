"""Service for handling runner state queries and result processing."""

from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID

from app.runner.models import (
    RunnerState,
    RunnerAction,
    RunnerStateQuery,
    RunnerStateResponse,
    RunnerMeasurementReport,
    RunnerLoadResult,
    RunnerFunctionalResult,
    PackageMeasurement,
)
from app.models.enums import PhaseState, ExecutionPhase


class WorkflowStateRepository(Protocol):
    """Protocol for workflow state repository."""

    async def find_by_device_identifier(
        self,
        device_ip: Optional[str] = None,
        device_fqdn: Optional[str] = None,
        device_hostname: Optional[str] = None,
        active_only: bool = True,
    ) -> Optional[dict]:
        """Find active workflow state for a device."""
        ...

    async def update_phase_state(
        self,
        workflow_state_id: int,
        phase_state: str,
    ) -> None:
        """Update phase state."""
        ...

    async def update_measured_list(
        self,
        workflow_state_id: int,
        phase: str,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        """Update measured package list for a phase."""
        ...

    async def update_results(
        self,
        workflow_state_id: int,
        phase: str,
        results_json: dict,
        stats_json: Optional[dict] = None,
        logs_json: Optional[dict] = None,
    ) -> None:
        """Update results for a phase."""
        ...


class RunnerStateService:
    """
    Service for managing runner state queries and result processing.

    Runners call this service to:
    1. Query their current state (what should I do?)
    2. Report package measurements
    3. Report load test results
    4. Report functional test results
    """

    def __init__(
        self,
        workflow_repo: WorkflowStateRepository,
        default_check_interval_sec: int = 60,
        package_install_poll_sec: int = 30,
    ):
        self.workflow_repo = workflow_repo
        self.default_check_interval_sec = default_check_interval_sec
        self.package_install_poll_sec = package_install_poll_sec

    async def get_runner_state(
        self,
        query: RunnerStateQuery,
    ) -> RunnerStateResponse:
        """
        Get current state for a runner.

        Runner asks "what should I do?" and we look up its
        execution_workflow_state to determine the answer.

        Args:
            query: Runner's state query with device identification

        Returns:
            RunnerStateResponse with action to take
        """
        # Find workflow state for this device
        workflow_state = await self.workflow_repo.find_by_device_identifier(
            device_ip=query.device_ip,
            device_fqdn=query.device_fqdn,
            device_hostname=query.device_hostname,
            active_only=True,
        )

        # No active workflow - runner should idle
        if not workflow_state:
            return RunnerStateResponse(
                state=RunnerState.IDLE,
                action=RunnerAction.WAIT,
                check_back_after_sec=self.default_check_interval_sec,
                message="No active execution for this device",
            )

        # Extract state info
        workflow_state_id = workflow_state.get("id")
        execution_id = workflow_state.get("test_run_execution_id")
        current_phase = workflow_state.get("current_phase")
        phase_state = workflow_state.get("phase_state")
        loadprofile = workflow_state.get("loadprofile")

        # Determine response based on phase_state
        return self._determine_runner_action(
            workflow_state=workflow_state,
            workflow_state_id=workflow_state_id,
            execution_id=str(execution_id) if execution_id else None,
            current_phase=current_phase,
            phase_state=phase_state,
            loadprofile=loadprofile,
        )

    def _determine_runner_action(
        self,
        workflow_state: dict,
        workflow_state_id: int,
        execution_id: Optional[str],
        current_phase: Optional[str],
        phase_state: Optional[str],
        loadprofile: Optional[str],
    ) -> RunnerStateResponse:
        """Determine what action runner should take based on workflow state."""

        # Map phase_state to runner action
        if phase_state == PhaseState.INSTALLING_AGENT.value:
            # MDM install triggered, runner should wait then measure
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.AWAITING_PACKAGE_INSTALL,
                action=RunnerAction.WAIT,
                current_phase=current_phase,
                loadprofile=loadprofile,
                check_back_after_sec=self.package_install_poll_sec,
                message="Package installation in progress via MDM",
            )

        if phase_state == PhaseState.AGENT_INSTALLED.value:
            # Packages installed, runner should measure
            package_list = self._get_package_list_for_phase(workflow_state, current_phase)
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.REPORT_PACKAGE_MEASUREMENT,
                action=RunnerAction.MEASURE_PACKAGES,
                current_phase=current_phase,
                loadprofile=loadprofile,
                packages_to_measure=package_list,
                check_back_after_sec=self.default_check_interval_sec,
                message="Measure installed packages and report versions",
            )

        if phase_state == PhaseState.WARMUP.value:
            # Ready for load test (warmup phase)
            load_config = self._get_load_test_config(workflow_state)
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.EXECUTE_LOAD,
                action=RunnerAction.RUN_LOAD_TEST,
                current_phase=current_phase,
                loadprofile=loadprofile,
                load_test_config=load_config,
                check_back_after_sec=self.default_check_interval_sec,
                message="Execute load test",
            )

        if phase_state == PhaseState.LOAD_TEST_RUNNING.value:
            # Load test should be running - wait for completion
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.EXECUTE_LOAD,
                action=RunnerAction.WAIT,
                current_phase=current_phase,
                loadprofile=loadprofile,
                check_back_after_sec=30,  # Check more frequently during test
                message="Load test in progress",
            )

        if phase_state == PhaseState.LOAD_TEST_COMPLETED.value:
            # Load test done, collect stats
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.COLLECT_STATS,
                action=RunnerAction.COLLECT_STATS,
                current_phase=current_phase,
                loadprofile=loadprofile,
                check_back_after_sec=self.default_check_interval_sec,
                message="Collect performance stats",
            )

        if phase_state == PhaseState.COLLECTING_STATS.value:
            # Check if there are functional tests to run
            functional_config = self._get_next_functional_test(workflow_state)
            if functional_config:
                return RunnerStateResponse(
                    workflow_state_id=workflow_state_id,
                    execution_id=execution_id,
                    state=RunnerState.EXECUTE_FUNCTIONAL,
                    action=RunnerAction.RUN_FUNCTIONAL_TEST,
                    current_phase=current_phase,
                    loadprofile=loadprofile,
                    functional_test_config=functional_config,
                    check_back_after_sec=self.default_check_interval_sec,
                    message="Execute functional test",
                )

        if phase_state == PhaseState.COMPLETED.value:
            return RunnerStateResponse(
                workflow_state_id=workflow_state_id,
                execution_id=execution_id,
                state=RunnerState.COMPLETE,
                action=RunnerAction.SHUTDOWN,
                current_phase=current_phase,
                loadprofile=loadprofile,
                message="Phase complete",
            )

        # Default: wait
        return RunnerStateResponse(
            workflow_state_id=workflow_state_id,
            execution_id=execution_id,
            state=RunnerState.IDLE,
            action=RunnerAction.WAIT,
            current_phase=current_phase,
            loadprofile=loadprofile,
            check_back_after_sec=self.default_check_interval_sec,
            message=f"Current state: {phase_state}",
        )

    def _get_package_list_for_phase(
        self,
        workflow_state: dict,
        phase: Optional[str],
    ) -> Optional[list[dict]]:
        """Get package list for the current phase."""
        if not phase:
            return None

        phase_key = f"{phase}_package_lst"
        return workflow_state.get(phase_key)

    def _get_load_test_config(
        self,
        workflow_state: dict,
    ) -> dict:
        """Get load test configuration for runner."""
        # This would pull from calibration data and test run config
        return {
            "thread_count": workflow_state.get("calibration_thread_count"),
            "warmup_sec": workflow_state.get("warmup_sec", 300),
            "measured_sec": workflow_state.get("measured_sec", 10800),
            "loadprofile": workflow_state.get("loadprofile"),
        }

    def _get_next_functional_test(
        self,
        workflow_state: dict,
    ) -> Optional[dict]:
        """Get next functional test to run, if any."""
        # TODO: Check other_package_grp_ids and which ones are done
        # For now return None
        return None

    async def process_measurement_report(
        self,
        report: RunnerMeasurementReport,
    ) -> dict:
        """
        Process package measurement report from runner.

        Updates workflow state with measured versions.
        Returns status and next action.

        Args:
            report: Measurement report from runner

        Returns:
            Dict with success status and message
        """
        if not report.workflow_state_id:
            return {
                "success": False,
                "message": "workflow_state_id is required",
            }

        # Convert measurements to measured list format
        measured_list = self._convert_measurements_to_measured_list(
            report.measurements
        )

        # Determine phase from workflow state
        workflow_state = await self.workflow_repo.find_by_device_identifier(
            device_ip=report.device_ip,
            device_fqdn=report.device_fqdn,
        )

        if not workflow_state:
            return {
                "success": False,
                "message": "Workflow state not found",
            }

        current_phase = workflow_state.get("current_phase", "initial")

        # Update the measured list
        await self.workflow_repo.update_measured_list(
            workflow_state_id=report.workflow_state_id,
            phase=current_phase,
            measured_list=measured_list,
            all_matched=report.all_matched,
        )

        # Update phase state based on result
        if report.all_matched:
            # All packages matched - ready for load test
            await self.workflow_repo.update_phase_state(
                workflow_state_id=report.workflow_state_id,
                phase_state=PhaseState.WARMUP.value,
            )
            return {
                "success": True,
                "message": "All packages matched, ready for load test",
                "next_action": RunnerAction.RUN_LOAD_TEST.value,
            }
        else:
            # Mismatch - need to handle retry or fail
            return {
                "success": False,
                "message": "Package version mismatch detected",
                "mismatched": [
                    m.to_dict() for m in report.measurements
                    if not m.version_matched
                ],
            }

    def _convert_measurements_to_measured_list(
        self,
        measurements: list[PackageMeasurement],
    ) -> list[dict]:
        """Convert runner measurements to measured list format."""
        measured_list = []
        for m in measurements:
            measured_list.append({
                "package_id": m.package_id,
                "package_name": m.package_name,
                "expected_version": m.expected_version,
                "measured_version": m.measured_version,
                "version_matched": m.version_matched,
                "install_status": "success" if m.is_installed else "failed",
                "verify_status": "matched" if m.version_matched else "mismatch",
                "error_message": m.error_message,
            })
        return measured_list

    async def process_load_result(
        self,
        result: RunnerLoadResult,
    ) -> dict:
        """
        Process load test result from runner.

        Updates workflow state with results.

        Args:
            result: Load test result from runner

        Returns:
            Dict with success status and next action
        """
        if not result.workflow_state_id:
            return {
                "success": False,
                "message": "workflow_state_id is required",
            }

        # Build results JSON
        results_json = result.to_dict()

        # Build stats JSON
        stats_json = {
            "avg_cpu_percent": result.avg_cpu_percent,
            "max_cpu_percent": result.max_cpu_percent,
            "avg_memory_percent": result.avg_memory_percent,
            "max_memory_percent": result.max_memory_percent,
            "avg_iteration_time_ms": result.avg_iteration_time_ms,
            "p50_iteration_time_ms": result.p50_iteration_time_ms,
            "p90_iteration_time_ms": result.p90_iteration_time_ms,
            "p99_iteration_time_ms": result.p99_iteration_time_ms,
        }

        # Update workflow state
        await self.workflow_repo.update_results(
            workflow_state_id=result.workflow_state_id,
            phase=result.phase,
            results_json=results_json,
            stats_json=stats_json,
        )

        # Update phase state
        if result.success:
            await self.workflow_repo.update_phase_state(
                workflow_state_id=result.workflow_state_id,
                phase_state=PhaseState.LOAD_TEST_COMPLETED.value,
            )
            return {
                "success": True,
                "message": "Load test results recorded",
                "next_action": RunnerAction.COLLECT_STATS.value,
            }
        else:
            await self.workflow_repo.update_phase_state(
                workflow_state_id=result.workflow_state_id,
                phase_state=PhaseState.ERROR.value,
            )
            return {
                "success": False,
                "message": f"Load test failed: {result.error_message}",
            }

    async def process_functional_result(
        self,
        result: RunnerFunctionalResult,
    ) -> dict:
        """
        Process functional test result from runner.

        Args:
            result: Functional test result from runner

        Returns:
            Dict with success status and next action
        """
        if not result.workflow_state_id:
            return {
                "success": False,
                "message": "workflow_state_id is required",
            }

        # TODO: Store functional test results
        # TODO: Check if more functional tests to run
        # TODO: Update phase state when all complete

        return {
            "success": True,
            "message": "Functional test result recorded",
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
        }
