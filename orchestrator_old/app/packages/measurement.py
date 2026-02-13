"""Helper functions for building package measured records."""

from datetime import datetime
from typing import Optional

from app.packages.models import (
    PackageInfo,
    PackageInstallResult,
    PackageVerifyResult,
    PackageMeasuredRecord,
    PhasePackageResult,
    InstallStatus,
    VerifyStatus,
)


def build_package_measured_record(
    package_info: PackageInfo,
    install_result: Optional[PackageInstallResult] = None,
    verify_result: Optional[PackageVerifyResult] = None,
) -> PackageMeasuredRecord:
    """
    Build a measured record from package info and results.

    Args:
        package_info: The original package information from *_package_lst
        install_result: Result of installation (if installation was attempted)
        verify_result: Result of verification (if verification was attempted)

    Returns:
        PackageMeasuredRecord ready for storage in *_package_lst_measured
    """
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

    # Populate from install result
    if install_result:
        record.install_status = install_result.install_status.value
        record.install_timestamp = (
            install_result.install_started_at.isoformat()
            if install_result.install_started_at
            else None
        )
        record.install_duration_sec = install_result.install_duration_sec
        record.restart_performed = install_result.restart_performed
        record.restart_duration_sec = install_result.restart_duration_sec
        record.retry_count = install_result.retry_count

        if install_result.error_message:
            record.error_message = install_result.error_message
            record.error_type = install_result.error_type

    # Populate from verify result
    if verify_result:
        record.verify_status = verify_result.verify_status.value
        record.verify_timestamp = (
            verify_result.verified_at.isoformat()
            if verify_result.verified_at
            else None
        )
        record.measured_version = verify_result.measured_version
        record.version_matched = verify_result.version_matched

        # Override error if verification failed
        if verify_result.error_message and not record.error_message:
            record.error_message = verify_result.error_message

    return record


def build_pending_measured_record(package_info: PackageInfo) -> PackageMeasuredRecord:
    """
    Build a pending measured record before installation starts.

    Used to initialize the measured list with pending status.
    """
    return PackageMeasuredRecord(
        package_id=package_info.package_id,
        package_name=package_info.package_name,
        package_type=package_info.package_type,
        is_measured=package_info.is_measured,
        expected_version=package_info.package_version,
        restart_required=package_info.requires_restart,
        install_status=InstallStatus.PENDING.value,
        verify_status=VerifyStatus.PENDING.value,
        agent_id=package_info.agent_id,
        agent_name=package_info.agent_name,
    )


def build_skipped_measured_record(
    package_info: PackageInfo,
    reason: str,
) -> PackageMeasuredRecord:
    """
    Build a skipped measured record.

    Used when a package is skipped due to earlier failure or configuration.
    """
    return PackageMeasuredRecord(
        package_id=package_info.package_id,
        package_name=package_info.package_name,
        package_type=package_info.package_type,
        is_measured=package_info.is_measured,
        expected_version=package_info.package_version,
        restart_required=package_info.requires_restart,
        install_status=InstallStatus.SKIPPED.value,
        verify_status=VerifyStatus.SKIPPED.value,
        error_message=reason,
        agent_id=package_info.agent_id,
        agent_name=package_info.agent_name,
    )


def build_failed_measured_record(
    package_info: PackageInfo,
    error_message: str,
    error_type: Optional[str] = None,
    install_result: Optional[PackageInstallResult] = None,
) -> PackageMeasuredRecord:
    """
    Build a failed measured record.

    Used when installation or verification fails.
    """
    record = PackageMeasuredRecord(
        package_id=package_info.package_id,
        package_name=package_info.package_name,
        package_type=package_info.package_type,
        is_measured=package_info.is_measured,
        expected_version=package_info.package_version,
        restart_required=package_info.requires_restart,
        install_status=InstallStatus.FAILED.value,
        verify_status=VerifyStatus.FAILED.value,
        error_message=error_message,
        error_type=error_type,
        agent_id=package_info.agent_id,
        agent_name=package_info.agent_name,
    )

    if install_result:
        record.install_timestamp = (
            install_result.install_started_at.isoformat()
            if install_result.install_started_at
            else None
        )
        record.install_duration_sec = install_result.install_duration_sec
        record.retry_count = install_result.retry_count

    return record


def build_phase_measured_list(
    package_list: list[dict],
    install_results: dict[int, PackageInstallResult],
    verify_results: dict[int, PackageVerifyResult],
) -> list[dict]:
    """
    Build the complete measured list for a phase.

    Args:
        package_list: Original *_package_lst (list of dicts)
        install_results: Map of package_id -> PackageInstallResult
        verify_results: Map of package_id -> PackageVerifyResult

    Returns:
        List of measured record dicts for *_package_lst_measured
    """
    measured_list = []

    for pkg_dict in package_list:
        package_info = PackageInfo.from_dict(pkg_dict)
        pkg_id = package_info.package_id

        install_result = install_results.get(pkg_id)
        verify_result = verify_results.get(pkg_id)

        measured_record = build_package_measured_record(
            package_info=package_info,
            install_result=install_result,
            verify_result=verify_result,
        )

        measured_list.append(measured_record.to_dict())

    return measured_list


def check_all_packages_matched(measured_list: list[dict]) -> bool:
    """
    Check if all packages in the measured list matched.

    Used to set *_packages_matched field.

    Args:
        measured_list: The *_package_lst_measured list

    Returns:
        True if all packages installed successfully and versions matched
    """
    if not measured_list:
        return True  # Empty list is considered matched

    for record in measured_list:
        install_status = record.get("install_status", "")
        verify_status = record.get("verify_status", "")

        # Skip packages that were intentionally skipped
        if install_status == InstallStatus.SKIPPED.value:
            continue

        # Check for success
        if install_status != InstallStatus.SUCCESS.value:
            return False

        # For verified packages, check version match
        if verify_status not in (VerifyStatus.MATCHED.value, VerifyStatus.SKIPPED.value):
            return False

    return True


def check_measured_packages_matched(measured_list: list[dict]) -> bool:
    """
    Check if all MEASURED packages (is_measured=True) matched.

    Only considers packages where is_measured=True (typically agents).
    Used for determining if agent impact measurement is valid.

    Args:
        measured_list: The *_package_lst_measured list

    Returns:
        True if all measured packages matched their expected versions
    """
    if not measured_list:
        return True

    for record in measured_list:
        # Only check packages marked for measurement
        if not record.get("is_measured", False):
            continue

        if not record.get("version_matched", False):
            return False

    return True


def aggregate_phase_result(
    phase: str,
    package_list: list[dict],
    measured_list: list[dict],
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> PhasePackageResult:
    """
    Aggregate package installation results for a phase.

    Args:
        phase: Phase name ("base", "initial", "upgrade")
        package_list: Original package list
        measured_list: Measured results list
        started_at: When phase started
        completed_at: When phase completed

    Returns:
        PhasePackageResult with aggregated statistics
    """
    total = len(package_list)
    installed = 0
    failed = 0
    skipped = 0

    measured_records = []
    for record_dict in measured_list:
        record = PackageMeasuredRecord.from_dict(record_dict)
        measured_records.append(record)

        install_status = record.install_status
        if install_status == InstallStatus.SUCCESS.value:
            installed += 1
        elif install_status == InstallStatus.SKIPPED.value:
            skipped += 1
        elif install_status in (InstallStatus.FAILED.value, InstallStatus.TIMEOUT.value):
            failed += 1

    all_matched = check_all_packages_matched(measured_list)

    return PhasePackageResult(
        phase=phase,
        total_packages=total,
        installed_count=installed,
        failed_count=failed,
        skipped_count=skipped,
        all_matched=all_matched,
        measured_records=measured_records,
        started_at=started_at,
        completed_at=completed_at,
    )


def update_measured_record_in_list(
    measured_list: list[dict],
    package_id: int,
    updated_record: PackageMeasuredRecord,
) -> list[dict]:
    """
    Update a specific package record in the measured list.

    Args:
        measured_list: Current measured list
        package_id: ID of package to update
        updated_record: New record data

    Returns:
        Updated measured list (new list, original not modified)
    """
    new_list = []
    for record in measured_list:
        if record.get("package_id") == package_id:
            new_list.append(updated_record.to_dict())
        else:
            new_list.append(record)
    return new_list


def get_failed_packages(measured_list: list[dict]) -> list[dict]:
    """
    Get list of failed packages from measured list.

    Args:
        measured_list: The *_package_lst_measured list

    Returns:
        List of failed package records
    """
    failed = []
    for record in measured_list:
        install_status = record.get("install_status", "")
        verify_status = record.get("verify_status", "")

        if install_status in (InstallStatus.FAILED.value, InstallStatus.TIMEOUT.value):
            failed.append(record)
        elif verify_status == VerifyStatus.FAILED.value:
            failed.append(record)

    return failed


def get_mismatched_versions(measured_list: list[dict]) -> list[dict]:
    """
    Get list of packages with version mismatch.

    Args:
        measured_list: The *_package_lst_measured list

    Returns:
        List of packages where expected != measured version
    """
    mismatched = []
    for record in measured_list:
        if record.get("verify_status") == VerifyStatus.MISMATCH.value:
            mismatched.append(record)
        elif not record.get("version_matched", True):
            # Also catch cases where version_matched is explicitly False
            if record.get("measured_version") is not None:
                mismatched.append(record)

    return mismatched
