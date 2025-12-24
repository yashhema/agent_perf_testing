"""Custom exceptions for the application."""

from typing import Optional


class OrchestratorError(Exception):
    """Base exception for all orchestrator errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(OrchestratorError):
    """Base class for validation errors."""

    pass


class InvalidSnapshotCombinationError(ValidationError):
    """Invalid combination of snapshots in test_run_target."""

    pass


class MissingRequiredFieldError(ValidationError):
    """Required field is missing."""

    pass


# =============================================================================
# Package Selection Errors
# =============================================================================


class PackageSelectionError(OrchestratorError):
    """Base class for package selection errors."""

    pass


class NoMatchingPackageError(PackageSelectionError):
    """No package found matching target OS."""

    def __init__(
        self,
        package_group_id: int,
        os_string: str,
        message: Optional[str] = None,
    ):
        self.package_group_id = package_group_id
        self.os_string = os_string
        msg = message or f"No package in group {package_group_id} matches OS: {os_string}"
        super().__init__(
            msg,
            details={
                "package_group_id": package_group_id,
                "os_string": os_string,
            },
        )


class PackageGroupEmptyError(PackageSelectionError):
    """Package group has no members."""

    def __init__(self, package_group_id: int, message: Optional[str] = None):
        self.package_group_id = package_group_id
        msg = message or f"Package group {package_group_id} has no members"
        super().__init__(msg, details={"package_group_id": package_group_id})


class NoLabPreferenceError(PackageSelectionError):
    """Lab has no preference for this package type."""

    def __init__(
        self,
        lab_id: int,
        package_type: str,
        message: Optional[str] = None,
    ):
        self.lab_id = lab_id
        self.package_type = package_type
        msg = message or f"Lab {lab_id} has no preference for package type: {package_type}"
        super().__init__(
            msg,
            details={
                "lab_id": lab_id,
                "package_type": package_type,
            },
        )


# =============================================================================
# Execution Errors
# =============================================================================


class ExecutionError(OrchestratorError):
    """Base class for execution errors."""

    pass


class InvalidStateTransitionError(ExecutionError):
    """Invalid state transition attempted."""

    def __init__(
        self,
        current_state: str,
        action: str,
        message: Optional[str] = None,
    ):
        self.current_state = current_state
        self.action = action
        msg = message or f"Cannot perform '{action}' from state '{current_state}'"
        super().__init__(
            msg,
            details={
                "current_state": current_state,
                "action": action,
            },
        )


class ExecutionAlreadyExistsError(ExecutionError):
    """An active execution already exists for this test run."""

    def __init__(
        self,
        test_run_id: int,
        execution_id: str,
        message: Optional[str] = None,
    ):
        self.test_run_id = test_run_id
        self.execution_id = execution_id
        msg = message or f"Test run {test_run_id} already has active execution: {execution_id}"
        super().__init__(
            msg,
            details={
                "test_run_id": test_run_id,
                "execution_id": execution_id,
            },
        )


class ExecutionNotFoundError(ExecutionError):
    """Execution not found."""

    def __init__(self, execution_id: str, message: Optional[str] = None):
        self.execution_id = execution_id
        msg = message or f"Execution {execution_id} not found"
        super().__init__(msg, details={"execution_id": execution_id})


# =============================================================================
# Infrastructure Errors
# =============================================================================


class InfrastructureError(OrchestratorError):
    """Base class for infrastructure errors."""

    pass


class SnapshotNotFoundError(InfrastructureError):
    """Snapshot not found in provider."""

    def __init__(
        self,
        baseline_id: int,
        provider_ref: str,
        message: Optional[str] = None,
    ):
        self.baseline_id = baseline_id
        self.provider_ref = provider_ref
        msg = message or f"Snapshot {provider_ref} not found for baseline {baseline_id}"
        super().__init__(
            msg,
            details={
                "baseline_id": baseline_id,
                "provider_ref": provider_ref,
            },
        )


class ConnectionError(InfrastructureError):
    """Connection to target failed."""

    def __init__(
        self,
        target_id: int,
        target_hostname: str,
        connection_type: str,
        message: Optional[str] = None,
    ):
        self.target_id = target_id
        self.target_hostname = target_hostname
        self.connection_type = connection_type
        msg = message or f"Failed to connect to {target_hostname} via {connection_type}"
        super().__init__(
            msg,
            details={
                "target_id": target_id,
                "target_hostname": target_hostname,
                "connection_type": connection_type,
            },
        )


# =============================================================================
# Validation Helper Functions
# =============================================================================


def validate_snapshot_combination(
    base_snapshot_id: Optional[int],
    initial_snapshot_id: Optional[int],
    upgrade_snapshot_id: Optional[int],
    has_upgrade_package: bool,
    target_id: Optional[int] = None,
) -> None:
    """
    Validate that snapshot combination is valid.

    Rules:
    1. Cannot have upgrade_snapshot without initial_snapshot
    2. Cannot have upgrade package without initial_snapshot
    3. Must have at least one snapshot (base or initial)

    Args:
        base_snapshot_id: Base phase snapshot ID (may be None)
        initial_snapshot_id: Initial phase snapshot ID (may be None)
        upgrade_snapshot_id: Upgrade phase snapshot ID (may be None)
        has_upgrade_package: Whether any scenario_case has upgrade_package_grp_id
        target_id: Optional target ID for error details

    Raises:
        InvalidSnapshotCombinationError: If combination is invalid
    """
    details = {
        "target_id": target_id,
        "base_snapshot_id": base_snapshot_id,
        "initial_snapshot_id": initial_snapshot_id,
        "upgrade_snapshot_id": upgrade_snapshot_id,
        "has_upgrade_package": has_upgrade_package,
    }

    # Rule 1: Cannot have upgrade_snapshot without initial_snapshot
    if upgrade_snapshot_id is not None and initial_snapshot_id is None:
        raise InvalidSnapshotCombinationError(
            "Cannot have upgrade_snapshot without initial_snapshot",
            details=details,
        )

    # Rule 2: Cannot have upgrade package without initial_snapshot
    if has_upgrade_package and initial_snapshot_id is None:
        raise InvalidSnapshotCombinationError(
            "Cannot have upgrade_package without initial_snapshot (nothing to upgrade from)",
            details=details,
        )

    # Rule 3: Must have at least one snapshot
    if base_snapshot_id is None and initial_snapshot_id is None:
        raise InvalidSnapshotCombinationError(
            "Must have at least one snapshot (base or initial)",
            details=details,
        )


def validate_scenario_cases_for_target(
    scenario_cases: list,
    initial_snapshot_id: Optional[int],
    target_id: Optional[int] = None,
) -> None:
    """
    Validate scenario cases configuration for a target.

    Args:
        scenario_cases: List of ScenarioCase objects
        initial_snapshot_id: Initial snapshot ID for this target
        target_id: Optional target ID for error details

    Raises:
        InvalidSnapshotCombinationError: If configuration is invalid
    """
    has_upgrade_package = any(
        case.upgrade_package_grp_id is not None
        for case in scenario_cases
    )

    if has_upgrade_package and initial_snapshot_id is None:
        raise InvalidSnapshotCombinationError(
            "Scenario has upgrade_package_grp_id but target has no initial_snapshot",
            details={
                "target_id": target_id,
                "has_upgrade_package": True,
                "initial_snapshot_id": None,
            },
        )
