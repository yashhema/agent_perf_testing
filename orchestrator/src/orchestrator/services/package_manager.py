"""Package management: resolver and deployer.

Phase 6: Resolve package groups to OS-specific members, deploy packages
to target servers via SSH/WinRM.

Package resolution per phase (D23 — always complete deployment):
  - Base phase: load_generator_package_grp_id
  - Initial phase: load_generator_package_grp_id + initial_package_grp_id + other_package_grp_ids
  - Functional: functional_package_grp_id during specified phase

Prerequisite scripts:
  Each PackageGroupMember can specify a prereq_script — a path relative to
  the ``prerequisites/`` directory (e.g. ``ubuntu/java_jre.sh``).  Scripts
  are organised by OS vendor, mirroring the ``discovery/`` layout.  The
  deployer uploads the script to the target VM and executes it *before*
  uploading the package itself.  Scripts must be idempotent (check first,
  install only if missing).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
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

# prerequisites/ sits alongside src/ and discovery/ in the orchestrator root
_PREREQ_DIR = Path(__file__).resolve().parents[3] / "prerequisites"


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
    prereq_script: Optional[str] = None


class PackageResolver:
    """Resolves package groups to OS-specific members.

    OS match string format: "{os_vendor_family}/{os_major_ver}/{os_minor_ver}"
    Exactly one member must match per group per OS. Multiple or zero = error.
    """

    def resolve(
        self,
        session: Session,
        package_group_ids: List[int],
        os_info,
    ) -> List[ResolvedPackage]:
        """Resolve multiple package groups for a specific target OS.

        Args:
            session: DB session
            package_group_ids: list of PackageGroupORM.id to resolve
            os_info: Any object with os_vendor_family, os_major_ver, os_minor_ver
                     attributes (BaselineORM for live-compare, ServerORM for
                     baseline-compare).

        Returns:
            List of ResolvedPackage, one per group

        Raises:
            ValueError: if zero or multiple members match for any group
        """
        os_string = self._build_os_string(os_info)
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
                prereq_script=member.prereq_script,
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
    def _build_os_string(os_info) -> str:
        """Build OS match string: '{vendor}/{major}/{minor}'.

        Accepts any object with os_vendor_family and os_major_ver attributes.
        Works with both BaselineORM (live-compare) and ServerORM (baseline-compare).
        """
        parts = [os_info.os_vendor_family, os_info.os_major_ver]
        if os_info.os_minor_ver:
            parts.append(os_info.os_minor_ver)
        return "/".join(parts)


class PackageDeployer:
    """Deploy resolved packages to target servers via SSH/WinRM.

    Args:
        use_sudo: If True (default), prefix Linux commands with sudo and
                  upload via /tmp + sudo mv (SFTP can't write to /opt as
                  non-root). Set False if SSH user is root or target dirs
                  are user-writable.
    """

    def __init__(self, use_sudo: bool = True):
        self._use_sudo = use_sudo

    def _sudo(self, cmd: str) -> str:
        """Prefix a command with sudo if use_sudo is enabled."""
        if self._use_sudo:
            return f"sudo {cmd}"
        return cmd

    def deploy(self, executor: RemoteExecutor, package: ResolvedPackage) -> None:
        """Deploy a single resolved package to a target server.

        Steps:
          1. Upload package from orchestrator path to target root_install_path
          2. Extract (extraction_command) if defined
          3. Run prerequisite script (prereq_script) if defined
             (runs after extract so bundled installers are available)
          4. Install (install_command) if defined
        """
        logger.info(
            "Deploying package '%s' (member %d) to %s",
            package.group_name, package.member_id, package.root_install_path,
        )

        # Step 1: Ensure parent directory exists, then upload
        rip = package.root_install_path
        if rip.startswith("/"):
            remote_parent = rip.rsplit("/", 1)[0]
            executor.execute(self._sudo(f"mkdir -p {remote_parent}"))
            if self._use_sudo:
                # SFTP runs as SSH user — upload to /tmp first, then sudo mv
                remote_filename = rip.rsplit("/", 1)[1]
                tmp_path = f"/tmp/_pkg_upload_{remote_filename}"
                executor.upload(package.path, tmp_path)
                result = executor.execute(f"sudo mv {tmp_path} {rip} && sudo chmod 644 {rip}")
                if not result.success:
                    raise RuntimeError(
                        f"Failed to move uploaded package to {rip}: {result.stderr}"
                    )
            else:
                executor.upload(package.path, package.root_install_path)
        elif "\\" in rip:
            remote_parent = rip.rsplit("\\", 1)[0]
            executor.execute(f'powershell -Command "New-Item -ItemType Directory -Force -Path \'{remote_parent}\'"')
            executor.upload(package.path, package.root_install_path)

        # Step 2: Extract
        if package.extraction_command:
            extract_cmd = self._sudo(package.extraction_command) if rip.startswith("/") else package.extraction_command

            # Force clean: remove any dirs/symlinks that extraction will create,
            # so mkdir/ln/tar never hit "file exists" errors
            if rip.startswith("/"):
                import re
                dirs_to_clean = set()
                # mkdir -p /some/dir
                for m in re.finditer(r"mkdir\s+-p\s+(\S+)", package.extraction_command):
                    dirs_to_clean.add(m.group(1))
                # ln -sfn /source /target — clean the target
                for m in re.finditer(r"ln\s+-\S*\s+\S+\s+(\S+)", package.extraction_command):
                    dirs_to_clean.add(m.group(1))
                for d in dirs_to_clean:
                    logger.info("Pre-cleaning: sudo rm -rf %s", d)
                    executor.execute(f"sudo rm -rf {d}")

            logger.info("Extracting: %s", extract_cmd)
            result = executor.execute(extract_cmd)
            if not result.success:
                raise RuntimeError(
                    f"Package extraction failed for '{package.group_name}': {result.stderr}"
                )

        # Step 3: Run prerequisite script (after extract so bundled deps are available)
        if package.prereq_script:
            self._run_prereq_script(executor, package)

        # Step 4: Install
        if package.install_command:
            install_cmd = self._sudo(package.install_command) if rip.startswith("/") else package.install_command
            logger.info("Installing: %s", install_cmd)
            result = executor.execute(install_cmd)
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
        rip = package.root_install_path
        uninstall_cmd = self._sudo(package.uninstall_command) if rip.startswith("/") else package.uninstall_command
        logger.info("Uninstalling: %s", uninstall_cmd)
        result = executor.execute(uninstall_cmd)
        if not result.success:
            logger.warning("Uninstall warning for '%s': %s", package.group_name, result.stderr)

    def _run_prereq_script(self, executor: RemoteExecutor, package: ResolvedPackage) -> None:
        """Upload and execute a prerequisite script on the target VM.

        The script path is relative to the ``prerequisites/`` directory.
        Scripts must be idempotent — they check if the prerequisite is
        already present and install only if missing.
        """
        script_rel = package.prereq_script
        local_path = _PREREQ_DIR / script_rel
        if not local_path.exists():
            raise FileNotFoundError(
                f"Prerequisite script not found: {local_path} "
                f"(prereq_script='{script_rel}' for package '{package.group_name}')"
            )

        # Determine remote temp path and execution command based on script type
        script_name = local_path.name
        if script_name.endswith(".ps1"):
            remote_path = f"C:\\Windows\\Temp\\prereq_{script_name}"
            run_cmd = f"powershell -ExecutionPolicy Bypass -File \"{remote_path}\""
        else:
            remote_path = f"/tmp/prereq_{script_name}"
            run_cmd = self._sudo(f"chmod +x {remote_path} && {remote_path}")

        logger.info(
            "Running prerequisite script '%s' for package '%s'",
            script_rel, package.group_name,
        )
        executor.upload(str(local_path), remote_path)
        result = executor.execute(run_cmd, timeout_sec=300)
        if not result.success:
            raise RuntimeError(
                f"Prerequisite script '{script_rel}' failed for "
                f"'{package.group_name}' (exit={result.exit_code}): {result.stderr}"
            )
        logger.info("Prerequisite script '%s' completed: %s", script_rel, result.stdout.strip()[-200:])

    def deploy_all(self, executor: RemoteExecutor, packages: List[ResolvedPackage]) -> None:
        """Deploy multiple packages to a target server."""
        for package in packages:
            self.deploy(executor, package)

    def deploy_if_needed(self, executor: RemoteExecutor, package: ResolvedPackage) -> bool:
        """Deploy a package only if not already installed.

        Checks status_command first. If the package is already installed
        (status_command succeeds), skips deployment.

        Returns:
            True if package was deployed, False if already present.
        """
        if package.status_command:
            installed = self.check_status(executor, package)
            if installed:
                logger.info(
                    "Package '%s' already installed, skipping deploy",
                    package.group_name,
                )
                return False
        self.deploy(executor, package)
        return True

    def check_status_any(
        self,
        session,
        executor: RemoteExecutor,
        package_group_ids: List[int],
        server,
    ) -> bool:
        """Check if any package from the given groups is installed on the server.

        Resolves packages and checks status_command for each. Returns True
        if at least one package's status check succeeds.
        """
        resolver = PackageResolver()
        packages = resolver.resolve(session, package_group_ids, server)
        for pkg in packages:
            if self.check_status(executor, pkg):
                return True
        return False
