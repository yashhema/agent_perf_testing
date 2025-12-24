"""OS Discovery Service.

Discovers OS information by attaching servers to baselines and running
detection commands. This populates the baseline's OS fields which are
used for package resolution.

Flow:
1. Get all baselines referenced by a test_run
2. For each baseline, restore it on the associated server
3. Run OS detection commands (cat /etc/os-release, uname -r, etc.)
4. Parse the output and update the baseline with OS info
5. Revert or leave server ready for next operation

The discovered info is stored on BaselineORM:
- os_vendor_family: "rhel", "ubuntu", "centos", "windows", etc.
- os_major_ver: "8", "22", "2019", etc.
- os_minor_ver: "4", "04", etc.
- os_kernel_ver: "4.18.0-305.el8.x86_64", "5.15.0-generic", etc.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    TestRunORM,
    TestRunTargetORM,
    BaselineORM,
    ServerORM,
)
from app.models.enums import OSFamily


logger = logging.getLogger(__name__)


class DiscoveryStatus(str, Enum):
    """Status of OS discovery for a baseline."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OSInfo:
    """Discovered OS information."""
    vendor_family: str  # rhel, ubuntu, centos, debian, windows, etc.
    major_ver: str      # 8, 22, 2019
    minor_ver: str      # 4, 04,
    kernel_ver: Optional[str] = None  # 4.18.0-305.el8.x86_64

    # Raw detection output for debugging
    raw_os_release: Optional[str] = None
    raw_uname: Optional[str] = None

    def to_os_string(self) -> str:
        """Build OS string for package matching: vendor/major/minor[/kernel]."""
        base = f"{self.vendor_family}/{self.major_ver}/{self.minor_ver}"
        if self.kernel_ver:
            return f"{base}/{self.kernel_ver}"
        return base


@dataclass
class BaselineDiscoveryResult:
    """Result of OS discovery for a single baseline."""
    baseline_id: int
    server_id: int
    status: DiscoveryStatus
    os_info: Optional[OSInfo] = None
    error_message: Optional[str] = None


@dataclass
class DiscoveryResult:
    """Result of OS discovery across all baselines."""
    test_run_id: int
    success: bool
    baseline_results: dict[int, BaselineDiscoveryResult] = field(default_factory=dict)
    error_message: Optional[str] = None

    @property
    def completed_count(self) -> int:
        return sum(1 for r in self.baseline_results.values()
                   if r.status == DiscoveryStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.baseline_results.values()
                   if r.status == DiscoveryStatus.FAILED)


class RemoteExecutor(Protocol):
    """Protocol for remote command execution."""

    async def execute(
        self,
        server_id: int,
        command: str,
        timeout_sec: int = 60,
    ) -> tuple[int, str, str]:
        """Execute command on server, return (exit_code, stdout, stderr)."""
        ...


class SnapshotManager(Protocol):
    """Protocol for snapshot/baseline management."""

    async def restore_snapshot(
        self,
        server_id: int,
        baseline_id: int,
        timeout_sec: int = 600,
    ) -> tuple[bool, Optional[str]]:
        """Restore baseline on server."""
        ...

    async def wait_for_ready(
        self,
        server_id: int,
        timeout_sec: int = 300,
    ) -> bool:
        """Wait for server to be ready after restore."""
        ...


class OSDiscoveryService:
    """
    Discovers OS information for baselines in a test run.

    Usage:
        discovery = OSDiscoveryService(
            session=db_session,
            snapshot_manager=snapshot_mgr,
            remote_executor=remote_exec,
        )

        result = await discovery.discover_for_test_run(test_run_id)

        if result.success:
            print(f"Discovered OS for {result.completed_count} baselines")
    """

    def __init__(
        self,
        session: AsyncSession,
        snapshot_manager: SnapshotManager,
        remote_executor: RemoteExecutor,
    ):
        self._session = session
        self._snapshot_manager = snapshot_manager
        self._remote_executor = remote_executor

    async def discover_for_test_run(
        self,
        test_run_id: int,
        skip_if_populated: bool = True,
        parallel: bool = False,
    ) -> DiscoveryResult:
        """
        Discover OS info for all baselines in a test run.

        Args:
            test_run_id: Test run to discover OS for
            skip_if_populated: Skip baselines that already have OS info
            parallel: Run discoveries in parallel (faster but more resource intensive)

        Returns:
            DiscoveryResult with outcomes for all baselines
        """
        result = DiscoveryResult(
            test_run_id=test_run_id,
            success=True,
        )

        try:
            # Get all unique (baseline_id, server_id) pairs from test_run_targets
            baseline_server_pairs = await self._get_baseline_server_pairs(test_run_id)

            if not baseline_server_pairs:
                logger.warning(f"No baselines found for test_run {test_run_id}")
                return result

            logger.info(
                f"Discovering OS for {len(baseline_server_pairs)} baselines "
                f"in test_run {test_run_id}"
            )

            if parallel:
                # Run all discoveries in parallel
                tasks = [
                    self._discover_baseline(baseline_id, server_id, skip_if_populated)
                    for baseline_id, server_id in baseline_server_pairs
                ]
                baseline_results = await asyncio.gather(*tasks, return_exceptions=True)

                for (baseline_id, _), br in zip(baseline_server_pairs, baseline_results):
                    if isinstance(br, Exception):
                        result.baseline_results[baseline_id] = BaselineDiscoveryResult(
                            baseline_id=baseline_id,
                            server_id=0,
                            status=DiscoveryStatus.FAILED,
                            error_message=str(br),
                        )
                        result.success = False
                    else:
                        result.baseline_results[baseline_id] = br
                        if br.status == DiscoveryStatus.FAILED:
                            result.success = False
            else:
                # Run discoveries sequentially
                for baseline_id, server_id in baseline_server_pairs:
                    br = await self._discover_baseline(
                        baseline_id, server_id, skip_if_populated
                    )
                    result.baseline_results[baseline_id] = br

                    if br.status == DiscoveryStatus.FAILED:
                        result.success = False

            logger.info(
                f"OS discovery complete: {result.completed_count} completed, "
                f"{result.failed_count} failed"
            )

        except Exception as e:
            logger.exception(f"OS discovery failed for test_run {test_run_id}")
            result.success = False
            result.error_message = str(e)

        return result

    async def _get_baseline_server_pairs(
        self,
        test_run_id: int,
    ) -> list[tuple[int, int]]:
        """Get unique (baseline_id, server_id) pairs for a test run."""
        stmt = select(TestRunTargetORM).where(
            TestRunTargetORM.test_run_id == test_run_id
        )
        result = await self._session.execute(stmt)
        targets = result.scalars().all()

        # Collect unique baseline-server pairs from all phases
        pairs = set()
        for target in targets:
            if target.base_snapshot_id:
                pairs.add((target.base_snapshot_id, target.target_id))
            if target.initial_snapshot_id:
                pairs.add((target.initial_snapshot_id, target.target_id))
            if target.upgrade_snapshot_id:
                pairs.add((target.upgrade_snapshot_id, target.target_id))

        return list(pairs)

    async def _discover_baseline(
        self,
        baseline_id: int,
        server_id: int,
        skip_if_populated: bool,
    ) -> BaselineDiscoveryResult:
        """Discover OS info for a single baseline."""
        result = BaselineDiscoveryResult(
            baseline_id=baseline_id,
            server_id=server_id,
            status=DiscoveryStatus.PENDING,
        )

        try:
            # Get baseline
            stmt = select(BaselineORM).where(BaselineORM.id == baseline_id)
            baseline_result = await self._session.execute(stmt)
            baseline = baseline_result.scalar_one_or_none()

            if not baseline:
                result.status = DiscoveryStatus.FAILED
                result.error_message = f"Baseline {baseline_id} not found"
                return result

            # Check if already populated
            if skip_if_populated and baseline.os_vendor_family:
                logger.info(
                    f"Skipping baseline {baseline_id}: OS already populated "
                    f"({baseline.os_vendor_family}/{baseline.os_major_ver})"
                )
                result.status = DiscoveryStatus.SKIPPED
                result.os_info = OSInfo(
                    vendor_family=baseline.os_vendor_family,
                    major_ver=baseline.os_major_ver or "",
                    minor_ver=baseline.os_minor_ver or "",
                    kernel_ver=baseline.os_kernel_ver,
                )
                return result

            # Get server for OS family detection
            stmt = select(ServerORM).where(ServerORM.id == server_id)
            server_result = await self._session.execute(stmt)
            server = server_result.scalar_one_or_none()

            if not server:
                result.status = DiscoveryStatus.FAILED
                result.error_message = f"Server {server_id} not found"
                return result

            result.status = DiscoveryStatus.IN_PROGRESS

            # Restore baseline on server
            logger.info(f"Restoring baseline {baseline_id} on server {server_id}")
            success, error = await self._snapshot_manager.restore_snapshot(
                server_id=server_id,
                baseline_id=baseline_id,
                timeout_sec=600,
            )

            if not success:
                result.status = DiscoveryStatus.FAILED
                result.error_message = f"Failed to restore baseline: {error}"
                return result

            # Wait for server to be ready
            ready = await self._snapshot_manager.wait_for_ready(
                server_id=server_id,
                timeout_sec=300,
            )

            if not ready:
                result.status = DiscoveryStatus.FAILED
                result.error_message = "Server not ready after restore"
                return result

            # Detect OS based on server's OS family
            os_family = server.os_family.lower() if server.os_family else "linux"

            if os_family == OSFamily.WINDOWS.value.lower():
                os_info = await self._detect_windows_os(server_id)
            else:
                os_info = await self._detect_linux_os(server_id)

            if not os_info:
                result.status = DiscoveryStatus.FAILED
                result.error_message = "Failed to detect OS info"
                return result

            # Update baseline with discovered OS info
            baseline.os_vendor_family = os_info.vendor_family
            baseline.os_major_ver = os_info.major_ver
            baseline.os_minor_ver = os_info.minor_ver
            baseline.os_kernel_ver = os_info.kernel_ver

            await self._session.flush()

            logger.info(
                f"Discovered OS for baseline {baseline_id}: "
                f"{os_info.to_os_string()}"
            )

            result.status = DiscoveryStatus.COMPLETED
            result.os_info = os_info

        except Exception as e:
            logger.exception(f"Failed to discover OS for baseline {baseline_id}")
            result.status = DiscoveryStatus.FAILED
            result.error_message = str(e)

        return result

    async def _detect_linux_os(self, server_id: int) -> Optional[OSInfo]:
        """Detect Linux OS info using standard commands."""
        os_info = OSInfo(
            vendor_family="unknown",
            major_ver="0",
            minor_ver="0",
        )

        # Get /etc/os-release
        exit_code, stdout, stderr = await self._remote_executor.execute(
            server_id=server_id,
            command="cat /etc/os-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null",
            timeout_sec=30,
        )

        if exit_code == 0 and stdout:
            os_info.raw_os_release = stdout
            os_info = self._parse_os_release(stdout, os_info)

        # Get kernel version
        exit_code, stdout, stderr = await self._remote_executor.execute(
            server_id=server_id,
            command="uname -r",
            timeout_sec=30,
        )

        if exit_code == 0 and stdout:
            os_info.raw_uname = stdout
            os_info.kernel_ver = stdout.strip()

        return os_info

    async def _detect_windows_os(self, server_id: int) -> Optional[OSInfo]:
        """Detect Windows OS info using PowerShell."""
        os_info = OSInfo(
            vendor_family="windows",
            major_ver="0",
            minor_ver="0",
        )

        # Get Windows version info
        cmd = (
            "powershell -Command \""
            "$os = Get-WmiObject Win32_OperatingSystem; "
            "Write-Output \\\"Version=$($os.Version)\\\"; "
            "Write-Output \\\"Caption=$($os.Caption)\\\""
            "\""
        )

        exit_code, stdout, stderr = await self._remote_executor.execute(
            server_id=server_id,
            command=cmd,
            timeout_sec=60,
        )

        if exit_code == 0 and stdout:
            os_info.raw_os_release = stdout
            os_info = self._parse_windows_version(stdout, os_info)

        return os_info

    def _parse_os_release(self, content: str, os_info: OSInfo) -> OSInfo:
        """Parse /etc/os-release or /etc/redhat-release content."""
        # Parse key=value pairs
        values = {}
        for line in content.split('\n'):
            line = line.strip()
            if '=' in line:
                key, _, value = line.partition('=')
                values[key] = value.strip('"\'')

        # Detect vendor family
        id_value = values.get('ID', '').lower()
        id_like = values.get('ID_LIKE', '').lower()

        if id_value in ('rhel', 'redhat'):
            os_info.vendor_family = 'rhel'
        elif id_value == 'centos':
            os_info.vendor_family = 'centos'
        elif id_value == 'fedora':
            os_info.vendor_family = 'fedora'
        elif id_value == 'ubuntu':
            os_info.vendor_family = 'ubuntu'
        elif id_value == 'debian':
            os_info.vendor_family = 'debian'
        elif id_value == 'sles' or id_value == 'suse':
            os_info.vendor_family = 'suse'
        elif id_value == 'amzn':
            os_info.vendor_family = 'amazon'
        elif id_value == 'ol' or id_value == 'oracle':
            os_info.vendor_family = 'oracle'
        elif 'rhel' in id_like or 'fedora' in id_like:
            os_info.vendor_family = 'rhel'
        elif 'debian' in id_like:
            os_info.vendor_family = 'debian'
        else:
            os_info.vendor_family = id_value or 'linux'

        # Parse version
        version_id = values.get('VERSION_ID', '')
        if version_id:
            # Handle formats like "8.4", "22.04", "8"
            parts = version_id.split('.')
            os_info.major_ver = parts[0] if parts else '0'
            os_info.minor_ver = parts[1] if len(parts) > 1 else '0'

        # Fallback: parse VERSION or PRETTY_NAME
        if os_info.major_ver == '0':
            version = values.get('VERSION', '')
            match = re.search(r'(\d+)\.?(\d+)?', version)
            if match:
                os_info.major_ver = match.group(1)
                os_info.minor_ver = match.group(2) or '0'

        # Handle /etc/redhat-release format
        if not values and 'release' in content.lower():
            match = re.search(r'release\s+(\d+)\.?(\d+)?', content, re.IGNORECASE)
            if match:
                os_info.major_ver = match.group(1)
                os_info.minor_ver = match.group(2) or '0'

            if 'red hat' in content.lower() or 'rhel' in content.lower():
                os_info.vendor_family = 'rhel'
            elif 'centos' in content.lower():
                os_info.vendor_family = 'centos'
            elif 'oracle' in content.lower():
                os_info.vendor_family = 'oracle'

        return os_info

    def _parse_windows_version(self, content: str, os_info: OSInfo) -> OSInfo:
        """Parse Windows version output."""
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('Version='):
                version = line.split('=', 1)[1]
                parts = version.split('.')
                if len(parts) >= 2:
                    # Windows version format: 10.0.19041
                    os_info.major_ver = parts[0]
                    os_info.minor_ver = parts[1]
                    if len(parts) >= 3:
                        os_info.kernel_ver = version

            elif line.startswith('Caption='):
                caption = line.split('=', 1)[1]
                # Detect Windows Server versions
                if 'Server 2022' in caption:
                    os_info.major_ver = '2022'
                elif 'Server 2019' in caption:
                    os_info.major_ver = '2019'
                elif 'Server 2016' in caption:
                    os_info.major_ver = '2016'
                elif 'Server 2012 R2' in caption:
                    os_info.major_ver = '2012'
                    os_info.minor_ver = 'R2'

        return os_info

    async def discover_single_baseline(
        self,
        baseline_id: int,
        server_id: int,
    ) -> BaselineDiscoveryResult:
        """
        Discover OS info for a single baseline.

        Convenience method for discovering a single baseline outside
        of a test run context.
        """
        return await self._discover_baseline(
            baseline_id=baseline_id,
            server_id=server_id,
            skip_if_populated=False,
        )
