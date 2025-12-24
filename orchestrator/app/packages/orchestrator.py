"""Package installation orchestrator.

Orchestrates the full package installation flow:
1. Get expected packages from *_package_lst
2. Trigger installation (direct or MDM)
3. Get measured results (immediate or from runner)
4. Compare measured vs expected
5. Decide: matched → proceed, mismatch → retry or fail
6. Update workflow state with results
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol
from enum import Enum

from app.packages.models import (
    PackageInfo,
    PackageMeasuredRecord,
    InstallStatus,
    VerifyStatus,
)
from app.packages.delivery import (
    DeliveryStrategy,
    DeliveryResult,
    DeliveryMethod,
)
from app.models.enums import PhaseState


class MatchDecision(str, Enum):
    """Decision after comparing measured vs expected."""

    MATCHED = "matched"  # All packages matched
    MISMATCH = "mismatch"  # Version mismatch, may retry
    MISSING = "missing"  # Package not installed
    FAILED = "failed"  # Installation failed
    RETRY = "retry"  # Retry installation
    ABORT = "abort"  # Max retries exceeded, abort


@dataclass
class PackageMatchResult:
    """Result of comparing expected vs measured package."""

    package_id: int
    package_name: str
    expected_version: str
    measured_version: Optional[str]
    decision: MatchDecision
    version_matched: bool = False
    error_message: Optional[str] = None


@dataclass
class PhaseInstallResult:
    """Result of installing all packages for a phase."""

    phase: str
    success: bool
    all_matched: bool

    # Package results
    package_results: list[PackageMatchResult] = field(default_factory=list)
    measured_list: list[dict] = field(default_factory=list)

    # Counts
    total_packages: int = 0
    matched_count: int = 0
    mismatched_count: int = 0
    failed_count: int = 0

    # Retry info
    retry_count: int = 0
    max_retries_exceeded: bool = False

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Error
    error_message: Optional[str] = None

    @property
    def can_proceed(self) -> bool:
        """Check if we can proceed to next step (load test)."""
        return self.success and self.all_matched


class WorkflowStateUpdater(Protocol):
    """Protocol for updating workflow state."""

    async def update_phase_state(
        self,
        workflow_state_id: int,
        phase_state: str,
    ) -> None:
        ...

    async def update_measured_list(
        self,
        workflow_state_id: int,
        phase: str,
        measured_list: list[dict],
        all_matched: bool,
    ) -> None:
        ...

    async def increment_retry_count(
        self,
        workflow_state_id: int,
    ) -> int:
        """Increment retry count and return new value."""
        ...


class PackageInstallOrchestrator:
    """
    Orchestrates package installation for a phase.

    Handles:
    - Different delivery strategies (direct vs MDM)
    - Measurement comparison (expected vs measured)
    - Retry logic with max retry limits
    - Workflow state updates
    """

    def __init__(
        self,
        workflow_updater: WorkflowStateUpdater,
        max_retries: int = 3,
        retry_delay_sec: int = 60,
    ):
        self.workflow_updater = workflow_updater
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec

    async def install_phase_packages(
        self,
        workflow_state_id: int,
        phase: str,
        package_list: list[dict],
        delivery_strategy: DeliveryStrategy,
        target_id: str,
        con_properties: Optional[dict] = None,
    ) -> PhaseInstallResult:
        """
        Install all packages for a phase.

        This is the main entry point for package installation.

        Args:
            workflow_state_id: Workflow state ID for updates
            phase: Phase name ("base", "initial", "upgrade")
            package_list: Packages from *_package_lst
            delivery_strategy: Strategy for package delivery
            target_id: Target device identifier
            con_properties: Connection properties

        Returns:
            PhaseInstallResult with outcomes
        """
        result = PhaseInstallResult(
            phase=phase,
            success=False,
            all_matched=False,
            total_packages=len(package_list),
            started_at=datetime.utcnow(),
        )

        if not package_list:
            result.success = True
            result.all_matched = True
            result.completed_at = datetime.utcnow()
            return result

        # Update phase state to installing
        await self.workflow_updater.update_phase_state(
            workflow_state_id=workflow_state_id,
            phase_state=PhaseState.INSTALLING_AGENT.value,
        )

        # Install packages
        measured_list = []
        for pkg_dict in package_list:
            package_info = PackageInfo.from_dict(pkg_dict)

            # Deliver package
            delivery_result = await delivery_strategy.deliver_package(
                package_info=package_info,
                target_id=target_id,
                con_properties=con_properties,
            )

            if delivery_result.poll_required:
                # MDM delivery - poll for completion
                success, error = await delivery_strategy.poll_delivery_status(
                    delivery_id=delivery_result.delivery_id,
                    timeout_sec=package_info.restart_timeout_sec or 600,
                )
                if not success:
                    delivery_result.success = False
                    delivery_result.error_message = error

            # Build measured record
            measured_record = self._build_measured_record(
                package_info=package_info,
                delivery_result=delivery_result,
            )

            # Verify if delivery succeeded
            if delivery_result.success:
                measured_version = await delivery_strategy.verify_package(
                    package_info=package_info,
                    target_id=target_id,
                )
                if measured_version:
                    measured_record.measured_version = measured_version
                    measured_record.version_matched = self._check_version_match(
                        expected=package_info.package_version,
                        measured=measured_version,
                        regex=package_info.expected_version_regex,
                    )
                    measured_record.verify_status = (
                        VerifyStatus.MATCHED.value
                        if measured_record.version_matched
                        else VerifyStatus.MISMATCH.value
                    )

            measured_list.append(measured_record.to_dict())

        # Analyze results
        result.measured_list = measured_list
        result.package_results = self._analyze_results(package_list, measured_list)
        result.all_matched = all(r.version_matched for r in result.package_results)
        result.matched_count = sum(1 for r in result.package_results if r.version_matched)
        result.mismatched_count = sum(1 for r in result.package_results if not r.version_matched)
        result.success = result.all_matched
        result.completed_at = datetime.utcnow()

        # Update workflow state
        await self.workflow_updater.update_measured_list(
            workflow_state_id=workflow_state_id,
            phase=phase,
            measured_list=measured_list,
            all_matched=result.all_matched,
        )

        # Update phase state based on result
        if result.all_matched:
            await self.workflow_updater.update_phase_state(
                workflow_state_id=workflow_state_id,
                phase_state=PhaseState.AGENT_INSTALLED.value,
            )
        else:
            await self.workflow_updater.update_phase_state(
                workflow_state_id=workflow_state_id,
                phase_state=PhaseState.ERROR.value,
            )

        return result

    async def process_runner_measurement(
        self,
        workflow_state_id: int,
        phase: str,
        package_list: list[dict],
        runner_measurements: list[dict],
        current_retry_count: int = 0,
    ) -> PhaseInstallResult:
        """
        Process measurements reported by runner.

        Called when runner wakes up and reports what's installed.

        Args:
            workflow_state_id: Workflow state ID
            phase: Current phase
            package_list: Expected packages
            runner_measurements: Measurements from runner
            current_retry_count: Current retry count

        Returns:
            PhaseInstallResult with decision
        """
        result = PhaseInstallResult(
            phase=phase,
            success=False,
            all_matched=False,
            total_packages=len(package_list),
            retry_count=current_retry_count,
            started_at=datetime.utcnow(),
        )

        # Convert runner measurements to measured list
        measured_list = self._convert_runner_measurements(
            package_list=package_list,
            runner_measurements=runner_measurements,
        )

        # Analyze results
        result.measured_list = measured_list
        result.package_results = self._analyze_results(package_list, measured_list)
        result.all_matched = all(r.version_matched for r in result.package_results)
        result.matched_count = sum(1 for r in result.package_results if r.version_matched)
        result.mismatched_count = sum(
            1 for r in result.package_results
            if r.decision == MatchDecision.MISMATCH
        )
        result.failed_count = sum(
            1 for r in result.package_results
            if r.decision in (MatchDecision.FAILED, MatchDecision.MISSING)
        )

        # Decide on action
        if result.all_matched:
            result.success = True
            await self.workflow_updater.update_phase_state(
                workflow_state_id=workflow_state_id,
                phase_state=PhaseState.AGENT_INSTALLED.value,
            )
        elif current_retry_count < self.max_retries:
            # Can retry
            new_retry_count = await self.workflow_updater.increment_retry_count(
                workflow_state_id=workflow_state_id,
            )
            result.retry_count = new_retry_count
            result.error_message = f"Retry {new_retry_count}/{self.max_retries}"
        else:
            # Max retries exceeded
            result.max_retries_exceeded = True
            result.error_message = f"Max retries ({self.max_retries}) exceeded"
            await self.workflow_updater.update_phase_state(
                workflow_state_id=workflow_state_id,
                phase_state=PhaseState.ERROR.value,
            )

        # Update measured list
        await self.workflow_updater.update_measured_list(
            workflow_state_id=workflow_state_id,
            phase=phase,
            measured_list=measured_list,
            all_matched=result.all_matched,
        )

        result.completed_at = datetime.utcnow()
        return result

    def _build_measured_record(
        self,
        package_info: PackageInfo,
        delivery_result: DeliveryResult,
    ) -> PackageMeasuredRecord:
        """Build measured record from delivery result."""
        record = PackageMeasuredRecord(
            package_id=package_info.package_id,
            package_name=package_info.package_name,
            package_type=package_info.package_type,
            is_measured=package_info.is_measured,
            expected_version=package_info.package_version,
            restart_required=package_info.requires_restart,
            agent_id=package_info.agent_id,
            agent_name=package_info.agent_name,
        )

        if delivery_result.install_result:
            ir = delivery_result.install_result
            record.install_status = ir.install_status.value
            record.install_timestamp = (
                ir.install_started_at.isoformat()
                if ir.install_started_at else None
            )
            record.install_duration_sec = ir.install_duration_sec
            record.restart_performed = ir.restart_performed
            record.restart_duration_sec = ir.restart_duration_sec
            record.retry_count = ir.retry_count

        if not delivery_result.success:
            record.install_status = InstallStatus.FAILED.value
            record.error_message = delivery_result.error_message

        return record

    def _analyze_results(
        self,
        package_list: list[dict],
        measured_list: list[dict],
    ) -> list[PackageMatchResult]:
        """Analyze measured vs expected and create match results."""
        results = []

        # Create lookup for measured by package_id
        measured_by_id = {m["package_id"]: m for m in measured_list}

        for pkg_dict in package_list:
            pkg_id = pkg_dict["package_id"]
            expected_version = pkg_dict["package_version"]

            measured = measured_by_id.get(pkg_id)
            if not measured:
                results.append(PackageMatchResult(
                    package_id=pkg_id,
                    package_name=pkg_dict["package_name"],
                    expected_version=expected_version,
                    measured_version=None,
                    decision=MatchDecision.MISSING,
                    error_message="Package not found in measurements",
                ))
                continue

            measured_version = measured.get("measured_version")
            version_matched = measured.get("version_matched", False)
            install_status = measured.get("install_status", "")

            if install_status in (InstallStatus.FAILED.value, InstallStatus.TIMEOUT.value):
                decision = MatchDecision.FAILED
            elif not measured_version:
                decision = MatchDecision.MISSING
            elif version_matched:
                decision = MatchDecision.MATCHED
            else:
                decision = MatchDecision.MISMATCH

            results.append(PackageMatchResult(
                package_id=pkg_id,
                package_name=pkg_dict["package_name"],
                expected_version=expected_version,
                measured_version=measured_version,
                decision=decision,
                version_matched=version_matched,
                error_message=measured.get("error_message"),
            ))

        return results

    def _convert_runner_measurements(
        self,
        package_list: list[dict],
        runner_measurements: list[dict],
    ) -> list[dict]:
        """Convert runner measurements to measured list format."""
        # Create lookup by package_id
        runner_by_id = {m["package_id"]: m for m in runner_measurements}

        measured_list = []
        for pkg_dict in package_list:
            pkg_id = pkg_dict["package_id"]
            runner_m = runner_by_id.get(pkg_id, {})

            measured_version = runner_m.get("measured_version")
            version_matched = False

            if measured_version:
                version_matched = self._check_version_match(
                    expected=pkg_dict["package_version"],
                    measured=measured_version,
                    regex=pkg_dict.get("expected_version_regex"),
                )

            measured_list.append({
                "package_id": pkg_id,
                "package_name": pkg_dict["package_name"],
                "package_type": pkg_dict.get("package_type", ""),
                "is_measured": pkg_dict.get("is_measured", False),
                "expected_version": pkg_dict["package_version"],
                "measured_version": measured_version,
                "version_matched": version_matched,
                "install_status": (
                    InstallStatus.SUCCESS.value
                    if runner_m.get("is_installed")
                    else InstallStatus.FAILED.value
                ),
                "verify_status": (
                    VerifyStatus.MATCHED.value
                    if version_matched
                    else VerifyStatus.MISMATCH.value
                ),
                "error_message": runner_m.get("error_message"),
                "agent_id": pkg_dict.get("agent_id"),
                "agent_name": pkg_dict.get("agent_name"),
            })

        return measured_list

    def _check_version_match(
        self,
        expected: str,
        measured: str,
        regex: Optional[str] = None,
    ) -> bool:
        """Check if measured version matches expected."""
        if not expected or not measured:
            return False

        # Exact match
        if expected == measured:
            return True

        # Prefix match (e.g., "6.50" matches "6.50.14358")
        if measured.startswith(expected):
            return True

        # Regex match
        if regex:
            try:
                if re.match(regex, measured):
                    return True
            except re.error:
                pass

        return False
