"""Package resolution service.

Resolves package group IDs to concrete package lists based on server OS.

Package resolution flow:
1. Get package_group_id (from lab, scenario_case, or test_run_target)
2. Find PackageGroupMemberORM where os_match_regex matches server OS
3. Get PackageORM for matched members
4. Build package list dict with all required fields

OS matching format: '{os_vendor}/{os_major}/{os_minor}[/{kernel}]'
Examples:
- "ubuntu/22/04" matches "ubuntu/22/.*"
- "rhel/8/5/4.18" matches "rhel/8/.*/4\\.18.*"
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.orm import (
    PackageORM,
    PackageGroupORM,
    PackageGroupMemberORM,
    ServerORM,
    LabORM,
    ScenarioCaseORM,
    TestRunTargetORM,
)


logger = logging.getLogger(__name__)


@dataclass
class ResolvedPackage:
    """A resolved package ready for installation."""

    package_id: int
    package_name: str
    version: str
    package_type: str

    # Delivery configuration
    delivery_config: Optional[dict] = None
    con_type: str = "ssh"

    # Execution settings
    install_command: Optional[str] = None
    verify_command: Optional[str] = None
    run_at_load: bool = False
    requires_restart: bool = False

    # Output paths for result collection
    execution_result_path: Optional[str] = None
    test_results_path: Optional[str] = None
    stats_collect_path: Optional[str] = None
    logs_collect_path: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for storage in workflow state."""
        return {
            "package_id": self.package_id,
            "package_name": self.package_name,
            "version": self.version,
            "package_type": self.package_type,
            "delivery_config": self.delivery_config,
            "con_type": self.con_type,
            "install_command": self.install_command,
            "verify_command": self.verify_command,
            "run_at_load": self.run_at_load,
            "requires_restart": self.requires_restart,
            "execution_result_path": self.execution_result_path,
            "test_results_path": self.test_results_path,
            "stats_collect_path": self.stats_collect_path,
            "logs_collect_path": self.logs_collect_path,
        }


class PackageResolver:
    """
    Resolves package groups to concrete packages based on server OS.

    Usage:
        resolver = PackageResolver(session)

        # Resolve a single package group
        packages = await resolver.resolve_package_group(
            package_group_id=123,
            server_os_string="ubuntu/22/04",
        )

        # Resolve all packages for a workflow state
        packages = await resolver.resolve_for_workflow(
            lab_id=1,
            scenario_id=2,
            target_id=3,
            loadgen_id=4,
        )
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def resolve_package_group(
        self,
        package_group_id: int,
        server_os_string: str,
        kernel_version: Optional[str] = None,
    ) -> list[ResolvedPackage]:
        """
        Resolve a package group to concrete packages for a server OS.

        Args:
            package_group_id: Package group ID to resolve
            server_os_string: Server OS string (e.g., "ubuntu/22/04")
            kernel_version: Optional kernel version for kernel-specific packages

        Returns:
            List of ResolvedPackage objects
        """
        # Build full OS string with kernel if provided
        full_os_string = server_os_string
        if kernel_version:
            full_os_string = f"{server_os_string}/{kernel_version}"

        # Get package group members ordered by priority
        stmt = (
            select(PackageGroupMemberORM)
            .where(PackageGroupMemberORM.package_group_id == package_group_id)
            .order_by(PackageGroupMemberORM.priority)
        )
        result = await self._session.execute(stmt)
        members = result.scalars().all()

        resolved = []
        matched_package_ids = set()

        for member in members:
            # Check if OS matches
            if not self._matches_os(member.os_match_regex, full_os_string):
                continue

            # Skip if we already have this package (higher priority already matched)
            if member.package_id in matched_package_ids:
                continue

            # Get package details
            package = await self._get_package(member.package_id)
            if not package:
                logger.warning(f"Package {member.package_id} not found")
                continue

            resolved.append(ResolvedPackage(
                package_id=package.id,
                package_name=package.name,
                version=package.version,
                package_type=package.package_type,
                delivery_config=package.delivery_config,
                con_type=member.con_type,
                install_command=self._get_install_command(package),
                verify_command=self._get_verify_command(package),
                run_at_load=package.run_at_load,
                requires_restart=package.requires_restart,
                execution_result_path=package.execution_result_path,
                test_results_path=package.test_results_path,
                stats_collect_path=package.stats_collect_path,
                logs_collect_path=package.logs_collect_path,
            ))
            matched_package_ids.add(member.package_id)

        logger.debug(
            f"Resolved package group {package_group_id} for OS {full_os_string}: "
            f"{len(resolved)} packages"
        )
        return resolved

    def _matches_os(self, pattern: str, os_string: str) -> bool:
        """Check if OS string matches pattern (regex)."""
        try:
            return bool(re.match(pattern, os_string, re.IGNORECASE))
        except re.error:
            logger.warning(f"Invalid OS match regex: {pattern}")
            return False

    async def _get_package(self, package_id: int) -> Optional[PackageORM]:
        """Get package by ID."""
        stmt = select(PackageORM).where(PackageORM.id == package_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def _get_install_command(self, package: PackageORM) -> Optional[str]:
        """Extract install command from delivery config."""
        if not package.delivery_config:
            return None

        config = package.delivery_config
        delivery_type = config.get("type", "").upper()

        if delivery_type == "SCRIPT":
            return config.get("install_command") or config.get("script_path")

        return None

    def _get_verify_command(self, package: PackageORM) -> Optional[str]:
        """Extract verify command from delivery config."""
        if not package.delivery_config:
            return None

        return package.delivery_config.get("verify_command")

    async def get_baseline_os_string(self, baseline_id: int) -> str:
        """Get OS string from baseline.

        The OS info comes from the baseline because:
        - A baseline represents a specific snapshot state
        - The same server can have multiple baselines with different OS versions
        - Package resolution should match the baseline's OS, not the current server state

        The OS info is populated by OSDiscoveryService when baselines are created
        or when test runs are prepared.

        Returns:
            OS string in format: "vendor/major/minor" (e.g., "rhel/8/4")
        """
        from app.models.orm import BaselineORM

        stmt = select(BaselineORM).where(BaselineORM.id == baseline_id)
        result = await self._session.execute(stmt)
        baseline = result.scalar_one_or_none()

        if not baseline:
            return "unknown/0/0"

        os_vendor = baseline.os_vendor_family or "unknown"
        os_major = baseline.os_major_ver or "0"
        os_minor = baseline.os_minor_ver or "0"

        return f"{os_vendor}/{os_major}/{os_minor}"

    async def get_baseline_kernel(self, baseline_id: int) -> Optional[str]:
        """Get kernel version from baseline."""
        from app.models.orm import BaselineORM

        stmt = select(BaselineORM).where(BaselineORM.id == baseline_id)
        result = await self._session.execute(stmt)
        baseline = result.scalar_one_or_none()

        if not baseline:
            return None

        return baseline.os_kernel_ver

    # Legacy methods for backwards compatibility
    async def get_server_os_string(self, server_id: int) -> str:
        """Get OS string for a server (legacy - use get_baseline_os_string)."""
        # For backwards compatibility, try to get from server's os_family
        stmt = select(ServerORM).where(ServerORM.id == server_id)
        result = await self._session.execute(stmt)
        server = result.scalar_one_or_none()

        if not server:
            return "unknown/0/0"

        # Server only has os_family, not detailed version info
        os_family = server.os_family or "unknown"
        return f"{os_family}/0/0"

    async def get_server_kernel(self, server_id: int) -> Optional[str]:
        """Get kernel version for a server (legacy - use get_baseline_kernel)."""
        # Server doesn't store kernel info, return None
        return None

    # =========================================================================
    # High-level resolution methods
    # =========================================================================

    async def resolve_jmeter_packages(
        self,
        lab_id: int,
        loadgen_baseline_id: int,
    ) -> list[dict]:
        """
        Resolve JMeter packages for a load generator.

        Args:
            lab_id: Lab ID (for jmeter_package_grpid)
            loadgen_baseline_id: Baseline ID for OS matching

        Returns:
            List of package dicts for workflow state
        """
        # Get lab
        stmt = select(LabORM).where(LabORM.id == lab_id)
        result = await self._session.execute(stmt)
        lab = result.scalar_one_or_none()

        if not lab or not lab.jmeter_package_grpid:
            return []

        # Get OS from baseline
        os_string = await self.get_baseline_os_string(loadgen_baseline_id)
        kernel = await self.get_baseline_kernel(loadgen_baseline_id)

        # Resolve packages
        packages = await self.resolve_package_group(
            package_group_id=lab.jmeter_package_grpid,
            server_os_string=os_string,
            kernel_version=kernel,
        )

        return [p.to_dict() for p in packages]

    async def resolve_base_packages(
        self,
        baseline_id: int,
        scenario_id: int,
    ) -> list[dict]:
        """
        Resolve base phase packages (emulator, etc.).

        Base phase packages come from scenario.load_generator_package_grp_id
        which typically includes emulator and other load tools.

        Args:
            baseline_id: Baseline ID for OS matching
            scenario_id: Scenario ID for package group lookup
        """
        from app.models.orm import ScenarioORM

        # Get scenario
        stmt = select(ScenarioORM).where(ScenarioORM.id == scenario_id)
        result = await self._session.execute(stmt)
        scenario = result.scalar_one_or_none()

        if not scenario or not scenario.load_generator_package_grp_id:
            return []

        os_string = await self.get_baseline_os_string(baseline_id)
        kernel = await self.get_baseline_kernel(baseline_id)

        packages = await self.resolve_package_group(
            package_group_id=scenario.load_generator_package_grp_id,
            server_os_string=os_string,
            kernel_version=kernel,
        )

        return [p.to_dict() for p in packages]

    async def resolve_initial_packages(
        self,
        baseline_id: int,
        scenario_id: int,
        agent_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Resolve initial phase packages (agent installation).

        Initial phase packages come from scenario_case.initial_package_grp_id.

        Args:
            baseline_id: Baseline ID for OS matching
            scenario_id: Scenario ID for lookup
            agent_id: Optional agent ID to filter scenario_cases
        """
        # Get scenario case
        stmt = select(ScenarioCaseORM).where(
            ScenarioCaseORM.scenario_id == scenario_id
        )
        if agent_id:
            stmt = stmt.where(ScenarioCaseORM.agent_id == agent_id)

        result = await self._session.execute(stmt)
        scenario_case = result.scalar_one_or_none()

        if not scenario_case:
            return []

        os_string = await self.get_baseline_os_string(baseline_id)
        kernel = await self.get_baseline_kernel(baseline_id)

        packages = await self.resolve_package_group(
            package_group_id=scenario_case.initial_package_grp_id,
            server_os_string=os_string,
            kernel_version=kernel,
        )

        return [p.to_dict() for p in packages]

    async def resolve_upgrade_packages(
        self,
        baseline_id: int,
        scenario_id: int,
        agent_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Resolve upgrade phase packages.

        Upgrade phase packages come from scenario_case.upgrade_package_grp_id.

        Args:
            baseline_id: Baseline ID for OS matching
            scenario_id: Scenario ID for lookup
            agent_id: Optional agent ID to filter scenario_cases
        """
        # Get scenario case
        stmt = select(ScenarioCaseORM).where(
            ScenarioCaseORM.scenario_id == scenario_id
        )
        if agent_id:
            stmt = stmt.where(ScenarioCaseORM.agent_id == agent_id)

        result = await self._session.execute(stmt)
        scenario_case = result.scalar_one_or_none()

        if not scenario_case or not scenario_case.upgrade_package_grp_id:
            return []

        os_string = await self.get_baseline_os_string(baseline_id)
        kernel = await self.get_baseline_kernel(baseline_id)

        packages = await self.resolve_package_group(
            package_group_id=scenario_case.upgrade_package_grp_id,
            server_os_string=os_string,
            kernel_version=kernel,
        )

        return [p.to_dict() for p in packages]

    async def resolve_all_for_target(
        self,
        lab_id: int,
        scenario_id: int,
        base_baseline_id: int,
        initial_baseline_id: Optional[int] = None,
        upgrade_baseline_id: Optional[int] = None,
        loadgen_baseline_id: Optional[int] = None,
        agent_id: Optional[int] = None,
    ) -> dict[str, list[dict]]:
        """
        Resolve all packages for a target across all phases.

        Args:
            lab_id: Lab ID (for jmeter_package_grpid)
            scenario_id: Scenario ID (for load_generator_package_grp_id and scenario_cases)
            base_baseline_id: Baseline ID for base phase OS matching
            initial_baseline_id: Baseline ID for initial phase OS matching
            upgrade_baseline_id: Baseline ID for upgrade phase OS matching
            loadgen_baseline_id: Baseline ID for loadgen OS matching
            agent_id: Optional agent ID to filter scenario_cases

        Returns:
            Dict with keys: jmeter_packages, base_packages, initial_packages, upgrade_packages
        """
        result = {
            "jmeter_packages": [],
            "base_packages": [],
            "initial_packages": [],
            "upgrade_packages": [],
        }

        # Resolve JMeter packages (uses loadgen baseline)
        if loadgen_baseline_id:
            result["jmeter_packages"] = await self.resolve_jmeter_packages(
                lab_id=lab_id,
                loadgen_baseline_id=loadgen_baseline_id,
            )

        # Resolve base packages (emulator, load tools)
        result["base_packages"] = await self.resolve_base_packages(
            baseline_id=base_baseline_id,
            scenario_id=scenario_id,
        )

        # Resolve initial packages (agent installation)
        # Uses initial_baseline_id if provided, otherwise base_baseline_id
        initial_bl = initial_baseline_id or base_baseline_id
        result["initial_packages"] = await self.resolve_initial_packages(
            baseline_id=initial_bl,
            scenario_id=scenario_id,
            agent_id=agent_id,
        )

        # Resolve upgrade packages (agent upgrade)
        # Uses upgrade_baseline_id if provided, otherwise initial baseline
        if upgrade_baseline_id:
            result["upgrade_packages"] = await self.resolve_upgrade_packages(
                baseline_id=upgrade_baseline_id,
                scenario_id=scenario_id,
                agent_id=agent_id,
            )

        return result
