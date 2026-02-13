"""Package management: resolver and deployer.

Phase 6: Resolve package groups to OS-specific members, deploy packages
to target servers via SSH/WinRM.

Package resolution per phase (D23 — always complete deployment):
  - Base phase: load_generator_package_grp_id
  - Initial phase: load_generator_package_grp_id + initial_package_grp_id + other_package_grp_ids
  - Functional: functional_package_grp_id during specified phase
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.infra.remote_executor import RemoteExecutor
from orchestrator.models.orm import (
    BaselineORM,
    PackageGroupMemberORM,
    PackageGroupORM,
    ScenarioORM,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPackage:
    """A specific package member resolved for a target OS."""
    group_id: int
    group_name: str
    member_id: int
    os_match_regex: str
    path: str
    root_install_path: str
    extraction_command: Optional[str]
    install_command: Optional[str]
    run_command: Optional[str]
    output_path: Optional[str]
    uninstall_command: Optional[str]
    status_command: Optional[str]


class PackageResolver:
    """Resolves package groups to OS-specific members.

    OS match string format: "{os_vendor_family}/{os_major_ver}/{os_minor_ver}"
    Exactly one member must match per group per OS. Multiple or zero = error.
    """

    def resolve(
        self,
        session: Session,
        package_group_ids: List[int],
        baseline: BaselineORM,
    ) -> List[ResolvedPackage]:
        """Resolve multiple package groups for a specific target OS.

        Args:
            session: DB session
            package_group_ids: list of PackageGroupORM.id to resolve
            baseline: BaselineORM with OS info for matching

        Returns:
            List of ResolvedPackage, one per group

        Raises:
            ValueError: if zero or multiple members match for any group
        """
        os_string = self._build_os_string(baseline)
        resolved = []

        for group_id in package_group_ids:
            group = session.get(PackageGroupORM, group_id)
            if not group:
                raise ValueError(f"Package group {group_id} not found")

            members = session.query(PackageGroupMemberORM).filter(
                PackageGroupMemberORM.package_group_id == group_id
            ).all()

            matches = []
            for member in members:
                if re.match(member.os_match_regex, os_string):
                    matches.append(member)

            if len(matches) == 0:
                raise ValueError(
                    f"No package matches OS '{os_string}' in group '{group.name}' (id={group_id})"
                )
            if len(matches) > 1:
                raise ValueError(
                    f"Multiple packages match OS '{os_string}' in group '{group.name}' "
                    f"(id={group_id}): {[m.id for m in matches]}"
                )

            member = matches[0]
            resolved.append(ResolvedPackage(
                group_id=group_id,
                group_name=group.name,
                member_id=member.id,
                os_match_regex=member.os_match_regex,
                path=member.path,
                root_install_path=member.root_install_path,
                extraction_command=member.extraction_command,
                install_command=member.install_command,
                run_command=member.run_command,
                output_path=member.output_path,
                uninstall_command=member.uninstall_command,
                status_command=member.status_command,
            ))

        return resolved

    def resolve_for_phase(
        self,
        session: Session,
        scenario: ScenarioORM,
        baseline: BaselineORM,
        phase: str,  # "base" or "initial"
    ) -> List[ResolvedPackage]:
        """Resolve packages for a specific execution phase.

        Base: load_generator_package_grp_id only
        Initial: load_generator + initial + other
        """
        group_ids = [scenario.load_generator_package_grp_id]

        if phase == "initial":
            if scenario.initial_package_grp_id:
                group_ids.append(scenario.initial_package_grp_id)
            if scenario.other_package_grp_ids:
                group_ids.extend(scenario.other_package_grp_ids)

        return self.resolve(session, group_ids, baseline)

    @staticmethod
    def _build_os_string(baseline: BaselineORM) -> str:
        """Build OS match string: '{vendor}/{major}/{minor}'."""
        parts = [baseline.os_vendor_family, baseline.os_major_ver]
        if baseline.os_minor_ver:
            parts.append(baseline.os_minor_ver)
        return "/".join(parts)


class PackageDeployer:
    """Deploy resolved packages to target servers via SSH/WinRM."""

    def deploy(self, executor: RemoteExecutor, package: ResolvedPackage) -> None:
        """Deploy a single resolved package to a target server.

        Steps:
          1. Upload package from orchestrator path to target root_install_path
          2. Extract (extraction_command) if defined
          3. Install (install_command) if defined
        """
        logger.info(
            "Deploying package '%s' (member %d) to %s",
            package.group_name, package.member_id, package.root_install_path,
        )

        # Step 1: Upload
        executor.upload(package.path, package.root_install_path)

        # Step 2: Extract
        if package.extraction_command:
            logger.info("Extracting: %s", package.extraction_command)
            result = executor.execute(package.extraction_command)
            if not result.success:
                raise RuntimeError(
                    f"Package extraction failed for '{package.group_name}': {result.stderr}"
                )

        # Step 3: Install
        if package.install_command:
            logger.info("Installing: %s", package.install_command)
            result = executor.execute(package.install_command)
            if not result.success:
                raise RuntimeError(
                    f"Package install failed for '{package.group_name}': {result.stderr}"
                )

    def check_status(self, executor: RemoteExecutor, package: ResolvedPackage) -> bool:
        """Check if a deployed package is running/healthy."""
        if not package.status_command:
            return True  # No status check defined, assume OK
        result = executor.execute(package.status_command)
        return result.success

    def uninstall(self, executor: RemoteExecutor, package: ResolvedPackage) -> None:
        """Uninstall a package from the target."""
        if not package.uninstall_command:
            logger.warning("No uninstall command for '%s'", package.group_name)
            return
        logger.info("Uninstalling: %s", package.uninstall_command)
        result = executor.execute(package.uninstall_command)
        if not result.success:
            logger.warning("Uninstall warning for '%s': %s", package.group_name, result.stderr)

    def deploy_all(self, executor: RemoteExecutor, packages: List[ResolvedPackage]) -> None:
        """Deploy multiple packages to a target server."""
        for package in packages:
            self.deploy(executor, package)
