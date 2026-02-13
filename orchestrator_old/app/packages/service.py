"""Service for package installation and verification."""

import re
import asyncio
from datetime import datetime
from typing import Optional, Protocol

from app.packages.models import (
    PackageInfo,
    PackageInstallResult,
    PackageVerifyResult,
    PackageMeasuredRecord,
    InstallStatus,
    VerifyStatus,
)
from app.packages.measurement import (
    build_package_measured_record,
    build_failed_measured_record,
    build_skipped_measured_record,
    build_phase_measured_list,
    check_all_packages_matched,
    aggregate_phase_result,
)
from app.models.enums import ConnectionType


class RemoteExecutor(Protocol):
    """Protocol for remote command execution."""

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command and return (exit_code, stdout, stderr)."""
        ...

    async def wait_for_ready(
        self,
        timeout_sec: int = 300,
        check_interval_sec: int = 10,
    ) -> bool:
        """Wait for target to be ready after restart."""
        ...


class PackageInstallationService:
    """
    Service for installing and verifying packages on targets.

    Handles:
    - Package installation via different delivery methods
    - Version verification
    - Restart handling
    - Building measured records
    """

    def __init__(
        self,
        default_install_timeout_sec: int = 600,
        default_verify_timeout_sec: int = 60,
        default_restart_timeout_sec: int = 300,
        max_retries: int = 3,
        retry_delay_sec: int = 30,
    ):
        self.default_install_timeout_sec = default_install_timeout_sec
        self.default_verify_timeout_sec = default_verify_timeout_sec
        self.default_restart_timeout_sec = default_restart_timeout_sec
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec

    async def install_package(
        self,
        executor: RemoteExecutor,
        package_info: PackageInfo,
        con_properties: Optional[dict] = None,
    ) -> PackageInstallResult:
        """
        Install a single package on the target.

        Args:
            executor: Remote executor for the target
            package_info: Package to install
            con_properties: Connection properties for the delivery method

        Returns:
            PackageInstallResult with installation outcome
        """
        started_at = datetime.utcnow()
        result = PackageInstallResult(
            package_id=package_info.package_id,
            package_name=package_info.package_name,
            install_status=InstallStatus.INSTALLING,
            install_started_at=started_at,
        )

        try:
            # Get install command based on delivery type
            install_command = self._get_install_command(
                package_info=package_info,
                con_properties=con_properties,
            )

            if not install_command:
                result.install_status = InstallStatus.FAILED
                result.error_message = f"No install command for con_type: {package_info.con_type}"
                result.error_type = "missing_install_command"
                result.install_completed_at = datetime.utcnow()
                return result

            result.install_command_used = install_command

            # Execute installation with retries
            for attempt in range(self.max_retries):
                result.retry_count = attempt

                exit_code, stdout, stderr = await executor.execute(
                    command=install_command,
                    timeout_sec=self.default_install_timeout_sec,
                )

                result.install_exit_code = exit_code
                result.install_stdout = stdout
                result.install_stderr = stderr

                if exit_code == 0:
                    result.install_status = InstallStatus.SUCCESS
                    break
                else:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay_sec)
                    else:
                        result.install_status = InstallStatus.FAILED
                        result.error_message = f"Install failed with exit code {exit_code}: {stderr}"
                        result.error_type = "install_failed"

            result.install_completed_at = datetime.utcnow()

            # Handle restart if required and install succeeded
            if (
                result.install_status == InstallStatus.SUCCESS
                and package_info.requires_restart
            ):
                await self._handle_restart(executor, package_info, result)

        except asyncio.TimeoutError:
            result.install_status = InstallStatus.TIMEOUT
            result.error_message = "Installation timed out"
            result.error_type = "timeout"
            result.install_completed_at = datetime.utcnow()

        except Exception as e:
            result.install_status = InstallStatus.FAILED
            result.error_message = str(e)
            result.error_type = "exception"
            result.install_completed_at = datetime.utcnow()

        return result

    async def verify_package(
        self,
        executor: RemoteExecutor,
        package_info: PackageInfo,
    ) -> PackageVerifyResult:
        """
        Verify package installation by checking version.

        Args:
            executor: Remote executor for the target
            package_info: Package to verify

        Returns:
            PackageVerifyResult with verification outcome
        """
        verified_at = datetime.utcnow()

        # Skip verification if no version check command
        if not package_info.version_check_command:
            return PackageVerifyResult(
                package_id=package_info.package_id,
                verify_status=VerifyStatus.SKIPPED,
                verified_at=verified_at,
                expected_version=package_info.package_version,
                version_matched=True,  # Assume matched if no check
            )

        try:
            exit_code, stdout, stderr = await executor.execute(
                command=package_info.version_check_command,
                timeout_sec=self.default_verify_timeout_sec,
            )

            result = PackageVerifyResult(
                package_id=package_info.package_id,
                verify_status=VerifyStatus.PENDING,
                verified_at=verified_at,
                expected_version=package_info.package_version,
                version_check_command=package_info.version_check_command,
                version_check_exit_code=exit_code,
                version_check_stdout=stdout,
                version_check_stderr=stderr,
                expected_version_regex=package_info.expected_version_regex,
            )

            if exit_code != 0:
                result.verify_status = VerifyStatus.FAILED
                result.error_message = f"Version check failed with exit code {exit_code}"
                return result

            # Extract version from output
            measured_version = self._extract_version(
                stdout=stdout,
                expected_regex=package_info.expected_version_regex,
            )
            result.measured_version = measured_version
            result.regex_match_result = measured_version

            # Check if version matches
            if measured_version:
                version_matched = self._check_version_match(
                    expected=package_info.package_version,
                    measured=measured_version,
                    regex=package_info.expected_version_regex,
                )
                result.version_matched = version_matched
                result.verify_status = (
                    VerifyStatus.MATCHED if version_matched else VerifyStatus.MISMATCH
                )
            else:
                result.verify_status = VerifyStatus.FAILED
                result.error_message = "Could not extract version from output"

        except asyncio.TimeoutError:
            result = PackageVerifyResult(
                package_id=package_info.package_id,
                verify_status=VerifyStatus.FAILED,
                verified_at=verified_at,
                expected_version=package_info.package_version,
                error_message="Version check timed out",
            )

        except Exception as e:
            result = PackageVerifyResult(
                package_id=package_info.package_id,
                verify_status=VerifyStatus.FAILED,
                verified_at=verified_at,
                expected_version=package_info.package_version,
                error_message=str(e),
            )

        return result

    async def install_and_verify_package(
        self,
        executor: RemoteExecutor,
        package_info: PackageInfo,
        con_properties: Optional[dict] = None,
    ) -> PackageMeasuredRecord:
        """
        Install and verify a package, returning the measured record.

        Args:
            executor: Remote executor for the target
            package_info: Package to install and verify
            con_properties: Connection properties for delivery

        Returns:
            PackageMeasuredRecord with complete results
        """
        # Install the package
        install_result = await self.install_package(
            executor=executor,
            package_info=package_info,
            con_properties=con_properties,
        )

        # Only verify if installation succeeded
        verify_result = None
        if install_result.install_status == InstallStatus.SUCCESS:
            verify_result = await self.verify_package(
                executor=executor,
                package_info=package_info,
            )

        # Build the measured record
        return build_package_measured_record(
            package_info=package_info,
            install_result=install_result,
            verify_result=verify_result,
        )

    async def install_phase_packages(
        self,
        executor: RemoteExecutor,
        package_list: list[dict],
        con_properties: Optional[dict] = None,
        stop_on_failure: bool = False,
    ) -> tuple[list[dict], bool]:
        """
        Install all packages for a phase.

        Args:
            executor: Remote executor for the target
            package_list: List of package dicts from *_package_lst
            con_properties: Connection properties for delivery
            stop_on_failure: If True, stop on first failure

        Returns:
            Tuple of (measured_list, all_matched)
        """
        if not package_list:
            return [], True

        install_results: dict[int, PackageInstallResult] = {}
        verify_results: dict[int, PackageVerifyResult] = {}
        failed = False

        for pkg_dict in package_list:
            package_info = PackageInfo.from_dict(pkg_dict)

            # Skip remaining packages if earlier failure and stop_on_failure
            if failed and stop_on_failure:
                # Mark as skipped
                install_results[package_info.package_id] = PackageInstallResult(
                    package_id=package_info.package_id,
                    package_name=package_info.package_name,
                    install_status=InstallStatus.SKIPPED,
                    install_started_at=datetime.utcnow(),
                    error_message="Skipped due to earlier failure",
                )
                continue

            # Install package
            install_result = await self.install_package(
                executor=executor,
                package_info=package_info,
                con_properties=con_properties,
            )
            install_results[package_info.package_id] = install_result

            # Check for failure
            if install_result.install_status != InstallStatus.SUCCESS:
                failed = True
                if stop_on_failure:
                    continue

            # Verify if installation succeeded
            if install_result.install_status == InstallStatus.SUCCESS:
                verify_result = await self.verify_package(
                    executor=executor,
                    package_info=package_info,
                )
                verify_results[package_info.package_id] = verify_result

        # Build measured list
        measured_list = build_phase_measured_list(
            package_list=package_list,
            install_results=install_results,
            verify_results=verify_results,
        )

        all_matched = check_all_packages_matched(measured_list)

        return measured_list, all_matched

    async def _handle_restart(
        self,
        executor: RemoteExecutor,
        package_info: PackageInfo,
        result: PackageInstallResult,
    ) -> None:
        """Handle system restart after package installation."""
        result.restart_started_at = datetime.utcnow()

        timeout = (
            package_info.restart_timeout_sec
            or self.default_restart_timeout_sec
        )

        try:
            # Wait for system to come back up
            ready = await executor.wait_for_ready(
                timeout_sec=timeout,
                check_interval_sec=10,
            )

            result.restart_completed_at = datetime.utcnow()
            result.restart_performed = True
            result.restart_duration_sec = (
                result.restart_completed_at - result.restart_started_at
            ).total_seconds()

            if not ready:
                result.install_status = InstallStatus.FAILED
                result.error_message = "System did not come back up after restart"
                result.error_type = "restart_timeout"

        except Exception as e:
            result.restart_completed_at = datetime.utcnow()
            result.install_status = InstallStatus.FAILED
            result.error_message = f"Restart handling failed: {e}"
            result.error_type = "restart_failed"

    def _get_install_command(
        self,
        package_info: PackageInfo,
        con_properties: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Get the install command based on delivery type.

        Looks in delivery_config for the install command.
        """
        if not package_info.delivery_config:
            return None

        con_type = package_info.con_type.upper()

        # Script-based installation
        if con_type == ConnectionType.SCRIPT.value.upper():
            return package_info.delivery_config.get("install_command")

        # Intune-based (Windows MDM)
        if con_type == ConnectionType.INTUNE.value.upper():
            # Intune uses app deployment, return trigger command
            app_id = package_info.delivery_config.get("app_id")
            if app_id:
                return f"# Intune deployment for app_id: {app_id}"
            return None

        # JAMF-based (macOS MDM)
        if con_type == ConnectionType.JAMF.value.upper():
            policy_id = package_info.delivery_config.get("policy_id")
            if policy_id:
                return f"sudo jamf policy -id {policy_id}"
            return None

        # SSM-based (AWS)
        if con_type == ConnectionType.SSM.value.upper():
            return package_info.delivery_config.get("command")

        # Default: try install_command from delivery_config
        return package_info.delivery_config.get("install_command")

    def _extract_version(
        self,
        stdout: str,
        expected_regex: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract version string from command output.

        Args:
            stdout: Command output
            expected_regex: Optional regex pattern to match version

        Returns:
            Extracted version string or None
        """
        if not stdout:
            return None

        # If regex provided, use it to extract version
        if expected_regex:
            try:
                match = re.search(expected_regex, stdout)
                if match:
                    # Return full match or first group
                    return match.group(1) if match.groups() else match.group(0)
            except re.error:
                pass

        # Try common version patterns
        version_patterns = [
            r'(\d+\.\d+\.\d+[-.\w]*)',  # 1.2.3 or 1.2.3-beta
            r'[vV]?(\d+\.\d+[-.\w]*)',  # 1.2 or v1.2
            r'version[:\s]+(\S+)',  # version: 1.2.3
        ]

        for pattern in version_patterns:
            match = re.search(pattern, stdout, re.IGNORECASE)
            if match:
                return match.group(1)

        # Return first line as fallback
        first_line = stdout.strip().split('\n')[0].strip()
        return first_line if first_line else None

    def _check_version_match(
        self,
        expected: str,
        measured: str,
        regex: Optional[str] = None,
    ) -> bool:
        """
        Check if measured version matches expected.

        Args:
            expected: Expected version string
            measured: Measured version string
            regex: Optional regex for flexible matching

        Returns:
            True if versions match
        """
        if not expected or not measured:
            return False

        # Exact match
        if expected == measured:
            return True

        # Prefix match (e.g., "6.50" matches "6.50.14358")
        if measured.startswith(expected):
            return True

        # Regex match if provided
        if regex:
            try:
                if re.match(regex, measured):
                    return True
            except re.error:
                pass

        return False
