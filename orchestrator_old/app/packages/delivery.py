"""Package delivery strategies for different lab types.

Lab1/Lab2 (Server): Direct execution via SSH/PowerShell
Lab3 (EUC): MDM delivery via Intune/JAMF, runner reports results
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol
import asyncio

from app.packages.models import (
    PackageInfo,
    PackageInstallResult,
    PackageMeasuredRecord,
    InstallStatus,
)
from app.models.enums import LabType, ConnectionType, OSFamily


class DeliveryMethod(str, Enum):
    """Package delivery method."""

    DIRECT = "direct"  # SSH/PowerShell/Script
    INTUNE = "intune"  # Windows MDM
    JAMF = "jamf"  # macOS MDM
    SSM = "ssm"  # AWS Systems Manager
    TANIUM = "tanium"  # Tanium


@dataclass
class DeliveryResult:
    """Result of package delivery (not installation)."""

    success: bool
    delivery_method: DeliveryMethod
    delivery_id: Optional[str] = None  # MDM deployment ID, etc.

    # Timing
    delivered_at: Optional[datetime] = None

    # For direct delivery, we have install result immediately
    install_result: Optional[PackageInstallResult] = None

    # For MDM delivery, we poll for status
    poll_required: bool = False
    poll_endpoint: Optional[str] = None
    estimated_duration_sec: Optional[int] = None

    # Error
    error_message: Optional[str] = None


class RemoteExecutor(Protocol):
    """Protocol for remote command execution."""

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command, return (exit_code, stdout, stderr)."""
        ...

    async def wait_for_ready(
        self,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for system to be ready after restart."""
        ...


class MDMClient(Protocol):
    """Protocol for MDM (Intune/JAMF) operations."""

    async def trigger_app_install(
        self,
        device_id: str,
        app_id: str,
    ) -> tuple[bool, Optional[str]]:
        """Trigger app install, return (success, deployment_id)."""
        ...

    async def get_install_status(
        self,
        deployment_id: str,
    ) -> tuple[str, Optional[str]]:
        """Get install status, return (status, error_message)."""
        ...

    async def get_installed_apps(
        self,
        device_id: str,
    ) -> list[dict]:
        """Get list of installed apps with versions."""
        ...


class DeliveryStrategy(ABC):
    """Abstract base class for package delivery strategies."""

    @abstractmethod
    async def deliver_package(
        self,
        package_info: PackageInfo,
        target_id: str,
        con_properties: Optional[dict] = None,
    ) -> DeliveryResult:
        """
        Deliver package to target.

        For direct delivery: executes install and returns result.
        For MDM delivery: triggers install and returns delivery ID for polling.
        """
        pass

    @abstractmethod
    async def verify_package(
        self,
        package_info: PackageInfo,
        target_id: str,
    ) -> Optional[str]:
        """
        Verify package installation.

        Returns measured version or None if not installed.
        """
        pass

    @abstractmethod
    async def poll_delivery_status(
        self,
        delivery_id: str,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """
        Poll for delivery completion (MDM only).

        Returns (success, error_message).
        """
        pass


class DirectDeliveryStrategy(DeliveryStrategy):
    """
    Direct package delivery via SSH/PowerShell.

    Used for Lab1/Lab2 (Server) environments.
    Executes install command directly and returns result.
    """

    def __init__(
        self,
        executor: RemoteExecutor,
        max_retries: int = 3,
        retry_delay_sec: int = 30,
        install_timeout_sec: int = 600,
    ):
        self.executor = executor
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec
        self.install_timeout_sec = install_timeout_sec

    async def deliver_package(
        self,
        package_info: PackageInfo,
        target_id: str,
        con_properties: Optional[dict] = None,
    ) -> DeliveryResult:
        """Execute install command directly."""
        started_at = datetime.utcnow()

        # Get install command
        install_command = self._get_install_command(package_info, con_properties)
        if not install_command:
            return DeliveryResult(
                success=False,
                delivery_method=DeliveryMethod.DIRECT,
                error_message=f"No install command for package {package_info.package_name}",
            )

        install_result = PackageInstallResult(
            package_id=package_info.package_id,
            package_name=package_info.package_name,
            install_status=InstallStatus.INSTALLING,
            install_started_at=started_at,
            install_command_used=install_command,
        )

        # Execute with retries
        for attempt in range(self.max_retries):
            install_result.retry_count = attempt

            try:
                exit_code, stdout, stderr = await self.executor.execute(
                    command=install_command,
                    timeout_sec=self.install_timeout_sec,
                )

                install_result.install_exit_code = exit_code
                install_result.install_stdout = stdout
                install_result.install_stderr = stderr

                if exit_code == 0:
                    install_result.install_status = InstallStatus.SUCCESS
                    install_result.install_completed_at = datetime.utcnow()

                    # Handle restart if required
                    if package_info.requires_restart:
                        await self._handle_restart(package_info, install_result)

                    return DeliveryResult(
                        success=True,
                        delivery_method=DeliveryMethod.DIRECT,
                        delivered_at=datetime.utcnow(),
                        install_result=install_result,
                        poll_required=False,
                    )

                # Retry on failure
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay_sec)

            except asyncio.TimeoutError:
                install_result.install_status = InstallStatus.TIMEOUT
                install_result.error_message = "Install command timed out"

            except Exception as e:
                install_result.error_message = str(e)

        # All retries failed
        install_result.install_status = InstallStatus.FAILED
        install_result.install_completed_at = datetime.utcnow()

        return DeliveryResult(
            success=False,
            delivery_method=DeliveryMethod.DIRECT,
            delivered_at=datetime.utcnow(),
            install_result=install_result,
            error_message=install_result.error_message,
        )

    async def verify_package(
        self,
        package_info: PackageInfo,
        target_id: str,
    ) -> Optional[str]:
        """Run version check command and extract version."""
        if not package_info.version_check_command:
            return None

        try:
            exit_code, stdout, stderr = await self.executor.execute(
                command=package_info.version_check_command,
                timeout_sec=60,
            )

            if exit_code == 0:
                return self._extract_version(stdout, package_info.expected_version_regex)

        except Exception:
            pass

        return None

    async def poll_delivery_status(
        self,
        delivery_id: str,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Not used for direct delivery."""
        return (True, None)

    async def _handle_restart(
        self,
        package_info: PackageInfo,
        install_result: PackageInstallResult,
    ) -> None:
        """Wait for system to come back after restart."""
        install_result.restart_started_at = datetime.utcnow()
        timeout = package_info.restart_timeout_sec or 300

        try:
            ready = await self.executor.wait_for_ready(timeout_sec=timeout)
            install_result.restart_completed_at = datetime.utcnow()
            install_result.restart_performed = True
            install_result.restart_duration_sec = (
                install_result.restart_completed_at - install_result.restart_started_at
            ).total_seconds()

            if not ready:
                install_result.install_status = InstallStatus.FAILED
                install_result.error_message = "System did not come back after restart"

        except Exception as e:
            install_result.install_status = InstallStatus.FAILED
            install_result.error_message = f"Restart failed: {e}"

    def _get_install_command(
        self,
        package_info: PackageInfo,
        con_properties: Optional[dict] = None,
    ) -> Optional[str]:
        """Get install command from delivery config."""
        if not package_info.delivery_config:
            return None
        return package_info.delivery_config.get("install_command")

    def _extract_version(
        self,
        output: str,
        regex: Optional[str] = None,
    ) -> Optional[str]:
        """Extract version from command output."""
        import re

        if not output:
            return None

        if regex:
            match = re.search(regex, output)
            if match:
                return match.group(1) if match.groups() else match.group(0)

        # Try common patterns
        patterns = [
            r'(\d+\.\d+\.\d+[-.\w]*)',
            r'[vV]?(\d+\.\d+[-.\w]*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1)

        return output.strip().split('\n')[0].strip()


class MDMDeliveryStrategy(DeliveryStrategy):
    """
    MDM-based package delivery via Intune or JAMF.

    Used for Lab3 (EUC/Endpoint) environments.
    Triggers install via MDM and waits for runner to report results.
    """

    def __init__(
        self,
        mdm_client: MDMClient,
        mdm_type: str,  # "intune" or "jamf"
        poll_interval_sec: int = 30,
        max_poll_time_sec: int = 1800,
    ):
        self.mdm_client = mdm_client
        self.mdm_type = mdm_type
        self.poll_interval_sec = poll_interval_sec
        self.max_poll_time_sec = max_poll_time_sec

    async def deliver_package(
        self,
        package_info: PackageInfo,
        target_id: str,
        con_properties: Optional[dict] = None,
    ) -> DeliveryResult:
        """Trigger install via MDM."""
        # Get app ID from delivery config
        if not package_info.delivery_config:
            return DeliveryResult(
                success=False,
                delivery_method=self._get_delivery_method(),
                error_message="No delivery config for MDM package",
            )

        app_id = package_info.delivery_config.get("app_id")
        if not app_id:
            return DeliveryResult(
                success=False,
                delivery_method=self._get_delivery_method(),
                error_message="No app_id in delivery config",
            )

        # Trigger install
        try:
            success, deployment_id = await self.mdm_client.trigger_app_install(
                device_id=target_id,
                app_id=app_id,
            )

            if success and deployment_id:
                return DeliveryResult(
                    success=True,
                    delivery_method=self._get_delivery_method(),
                    delivery_id=deployment_id,
                    delivered_at=datetime.utcnow(),
                    poll_required=True,
                    estimated_duration_sec=package_info.restart_timeout_sec or 300,
                )
            else:
                return DeliveryResult(
                    success=False,
                    delivery_method=self._get_delivery_method(),
                    error_message="Failed to trigger MDM install",
                )

        except Exception as e:
            return DeliveryResult(
                success=False,
                delivery_method=self._get_delivery_method(),
                error_message=str(e),
            )

    async def verify_package(
        self,
        package_info: PackageInfo,
        target_id: str,
    ) -> Optional[str]:
        """Get installed version from MDM."""
        try:
            apps = await self.mdm_client.get_installed_apps(device_id=target_id)
            for app in apps:
                if app.get("app_id") == package_info.delivery_config.get("app_id"):
                    return app.get("version")
        except Exception:
            pass
        return None

    async def poll_delivery_status(
        self,
        delivery_id: str,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Poll MDM for install completion."""
        start_time = datetime.utcnow()
        timeout = min(timeout_sec, self.max_poll_time_sec)

        while True:
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > timeout:
                return (False, "MDM install polling timed out")

            try:
                status, error = await self.mdm_client.get_install_status(deployment_id)

                if status == "completed":
                    return (True, None)
                elif status == "failed":
                    return (False, error or "MDM install failed")
                elif status in ("pending", "in_progress"):
                    await asyncio.sleep(self.poll_interval_sec)
                else:
                    return (False, f"Unknown MDM status: {status}")

            except Exception as e:
                return (False, str(e))

    def _get_delivery_method(self) -> DeliveryMethod:
        """Get delivery method enum."""
        if self.mdm_type == "intune":
            return DeliveryMethod.INTUNE
        elif self.mdm_type == "jamf":
            return DeliveryMethod.JAMF
        return DeliveryMethod.DIRECT


class DeliveryStrategyFactory:
    """Factory for creating appropriate delivery strategy."""

    @staticmethod
    def create_strategy(
        lab_type: LabType,
        os_family: OSFamily,
        con_type: ConnectionType,
        executor: Optional[RemoteExecutor] = None,
        mdm_client: Optional[MDMClient] = None,
    ) -> DeliveryStrategy:
        """
        Create appropriate delivery strategy based on lab/OS/connection type.

        Args:
            lab_type: Type of lab (ONPREM_VSPHERE, AWS, ENDPOINT_MDM, etc.)
            os_family: Target OS (WINDOWS, LINUX, MACOS)
            con_type: Connection type (SCRIPT, INTUNE, JAMF, SSM, etc.)
            executor: Remote executor for direct delivery
            mdm_client: MDM client for Intune/JAMF delivery

        Returns:
            Appropriate DeliveryStrategy instance
        """
        # MDM-based delivery for endpoints
        if lab_type == LabType.ENDPOINT_MDM:
            if con_type == ConnectionType.INTUNE and mdm_client:
                return MDMDeliveryStrategy(
                    mdm_client=mdm_client,
                    mdm_type="intune",
                )
            elif con_type == ConnectionType.JAMF and mdm_client:
                return MDMDeliveryStrategy(
                    mdm_client=mdm_client,
                    mdm_type="jamf",
                )

        # Direct delivery for servers
        if executor:
            return DirectDeliveryStrategy(executor=executor)

        raise ValueError(
            f"Cannot create delivery strategy for lab_type={lab_type}, "
            f"con_type={con_type}"
        )

    @staticmethod
    def get_delivery_method(
        lab_type: LabType,
        con_type: ConnectionType,
    ) -> DeliveryMethod:
        """Determine delivery method without creating strategy."""
        if con_type == ConnectionType.INTUNE:
            return DeliveryMethod.INTUNE
        elif con_type == ConnectionType.JAMF:
            return DeliveryMethod.JAMF
        elif con_type == ConnectionType.SSM:
            return DeliveryMethod.SSM
        else:
            return DeliveryMethod.DIRECT
