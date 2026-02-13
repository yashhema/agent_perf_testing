"""Package selection service.

Selects the appropriate package from a package group based on:
1. OS matching (os_vendor_family/os_major/os_minor/kernel)
2. Lab preferences (preferred_con_type, fallback_con_type)
3. Priority ordering
"""

import re
from dataclasses import dataclass
from typing import Optional, Protocol

from app.models.enums import ConnectionType


@dataclass
class OSInfo:
    """OS information for package matching."""

    os_vendor_family: str  # e.g., "rhel", "ubuntu", "windows"
    os_major_ver: Optional[str] = None  # e.g., "8", "22", "10"
    os_minor_ver: Optional[str] = None  # e.g., "4", "04", "0"
    os_kernel_ver: Optional[str] = None  # e.g., "5.4.0-42-generic"

    def to_match_string(self, include_kernel: bool = False) -> str:
        """Build OS string for matching: '{vendor}/{major}/{minor}[/{kernel}]'."""
        parts = [self.os_vendor_family]

        if self.os_major_ver:
            parts.append(self.os_major_ver)
        if self.os_minor_ver:
            parts.append(self.os_minor_ver)
        if include_kernel and self.os_kernel_ver:
            parts.append(self.os_kernel_ver)

        return "/".join(parts)


@dataclass
class LabPreference:
    """Lab package delivery preference."""

    preferred_con_type: str
    fallback_con_type: Optional[str] = None
    priority: int = 0


@dataclass
class SelectedPackage:
    """Result of package selection."""

    package_id: int
    package_name: str
    package_version: str
    package_type: str
    con_type: str

    # Delivery config from package
    delivery_config: Optional[dict] = None

    # Verification config
    version_check_command: Optional[str] = None
    expected_version_regex: Optional[str] = None

    # Execution config
    run_at_load: bool = False
    requires_restart: bool = False
    restart_timeout_sec: Optional[int] = None

    # Output paths
    execution_result_path: Optional[str] = None
    test_results_path: Optional[str] = None
    stats_collect_path: Optional[str] = None
    logs_collect_path: Optional[str] = None

    # Metadata
    package_group_id: int = 0
    package_group_member_id: int = 0
    os_match_regex: str = ""
    match_priority: int = 0


class PackageRepository(Protocol):
    """Protocol for package data access."""

    async def get_package_group_members(
        self,
        package_group_id: int,
    ) -> list[dict]:
        """Get all members of a package group."""
        ...

    async def get_package(
        self,
        package_id: int,
    ) -> Optional[dict]:
        """Get package by ID."""
        ...


class PackageSelectionService:
    """
    Selects packages from package groups based on OS and lab preferences.

    Selection algorithm:
    1. Filter members by OS match regex
    2. Filter by lab preferred/fallback con_type
    3. Sort by priority (lower = higher priority)
    4. Return best match
    """

    def __init__(self, package_repo: PackageRepository):
        self.package_repo = package_repo

    async def select_package(
        self,
        package_group_id: int,
        os_info: OSInfo,
        lab_preferences: Optional[list[LabPreference]] = None,
        require_kernel_match: bool = False,
    ) -> Optional[SelectedPackage]:
        """
        Select the best package from a group for the given OS.

        Args:
            package_group_id: Package group ID
            os_info: Target OS information
            lab_preferences: Lab delivery preferences (preferred_con_type, fallback)
            require_kernel_match: If True, kernel version must match

        Returns:
            SelectedPackage or None if no match found
        """
        # Get all members of the package group
        members = await self.package_repo.get_package_group_members(package_group_id)
        if not members:
            return None

        # Build OS match string
        os_string = os_info.to_match_string(include_kernel=require_kernel_match)
        os_string_with_kernel = os_info.to_match_string(include_kernel=True)

        # Find matching members
        matching_members = []
        for member in members:
            os_regex = member.get("os_match_regex", "")
            if not os_regex:
                continue

            # Try to match OS string
            try:
                if require_kernel_match:
                    if re.match(os_regex, os_string_with_kernel):
                        matching_members.append(member)
                else:
                    # Try both with and without kernel
                    if re.match(os_regex, os_string) or re.match(os_regex, os_string_with_kernel):
                        matching_members.append(member)
            except re.error:
                # Skip invalid regex
                continue

        if not matching_members:
            return None

        # Apply lab preferences if provided
        if lab_preferences:
            matching_members = self._apply_lab_preferences(
                members=matching_members,
                preferences=lab_preferences,
            )

        if not matching_members:
            return None

        # Sort by priority (lower = higher priority)
        matching_members.sort(key=lambda m: m.get("priority", 0))

        # Get the best match
        best_member = matching_members[0]

        # Fetch the package details
        package = await self.package_repo.get_package(best_member["package_id"])
        if not package:
            return None

        return SelectedPackage(
            package_id=package["id"],
            package_name=package["name"],
            package_version=package["version"],
            package_type=package["package_type"],
            con_type=best_member.get("con_type", ""),
            delivery_config=package.get("delivery_config"),
            version_check_command=package.get("version_check_command"),
            expected_version_regex=package.get("expected_version_regex"),
            run_at_load=package.get("run_at_load", False),
            requires_restart=package.get("requires_restart", False),
            restart_timeout_sec=package.get("restart_timeout_sec"),
            execution_result_path=package.get("execution_result_path"),
            test_results_path=package.get("test_results_path"),
            stats_collect_path=package.get("stats_collect_path"),
            logs_collect_path=package.get("logs_collect_path"),
            package_group_id=package_group_id,
            package_group_member_id=best_member.get("id", 0),
            os_match_regex=best_member.get("os_match_regex", ""),
            match_priority=best_member.get("priority", 0),
        )

    async def select_packages_for_phase(
        self,
        package_group_ids: list[int],
        os_info: OSInfo,
        lab_preferences: Optional[list[LabPreference]] = None,
        require_kernel_match: bool = False,
    ) -> list[SelectedPackage]:
        """
        Select packages for all package groups in a phase.

        Args:
            package_group_ids: List of package group IDs
            os_info: Target OS information
            lab_preferences: Lab delivery preferences
            require_kernel_match: If True, kernel version must match

        Returns:
            List of SelectedPackage objects
        """
        selected = []

        for group_id in package_group_ids:
            package = await self.select_package(
                package_group_id=group_id,
                os_info=os_info,
                lab_preferences=lab_preferences,
                require_kernel_match=require_kernel_match,
            )
            if package:
                selected.append(package)

        return selected

    def _apply_lab_preferences(
        self,
        members: list[dict],
        preferences: list[LabPreference],
    ) -> list[dict]:
        """
        Filter and sort members by lab preferences.

        Priority:
        1. Members with preferred_con_type
        2. Members with fallback_con_type
        3. Other members (if no preference matches)
        """
        if not preferences:
            return members

        # Build con_type priority map
        con_type_priority = {}
        for pref in sorted(preferences, key=lambda p: p.priority):
            if pref.preferred_con_type not in con_type_priority:
                con_type_priority[pref.preferred_con_type] = len(con_type_priority)
            if pref.fallback_con_type and pref.fallback_con_type not in con_type_priority:
                con_type_priority[pref.fallback_con_type] = len(con_type_priority)

        # Categorize members
        preferred_members = []
        fallback_members = []
        other_members = []

        for member in members:
            con_type = member.get("con_type", "").upper()

            if con_type in con_type_priority:
                if con_type_priority[con_type] == 0:
                    preferred_members.append(member)
                else:
                    fallback_members.append(member)
            else:
                other_members.append(member)

        # Return in priority order
        if preferred_members:
            return preferred_members
        if fallback_members:
            return fallback_members
        return other_members

    def build_package_list_entry(
        self,
        selected: SelectedPackage,
        agent_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        is_measured: bool = True,
    ) -> dict:
        """
        Build a package list entry for *_package_lst.

        Args:
            selected: Selected package
            agent_id: Optional agent ID (for agent packages)
            agent_name: Optional agent name
            is_measured: Whether to measure this package

        Returns:
            Dictionary for *_package_lst
        """
        return {
            "package_id": selected.package_id,
            "package_name": selected.package_name,
            "package_version": selected.package_version,
            "package_type": selected.package_type,
            "con_type": selected.con_type,
            "delivery_config": selected.delivery_config,
            "version_check_command": selected.version_check_command,
            "expected_version_regex": selected.expected_version_regex,
            "run_at_load": selected.run_at_load,
            "requires_restart": selected.requires_restart,
            "restart_timeout_sec": selected.restart_timeout_sec,
            "execution_result_path": selected.execution_result_path,
            "test_results_path": selected.test_results_path,
            "stats_collect_path": selected.stats_collect_path,
            "logs_collect_path": selected.logs_collect_path,
            "package_group_id": selected.package_group_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "is_measured": is_measured,
        }


async def build_phase_package_list(
    selection_service: PackageSelectionService,
    os_info: OSInfo,
    loadgen_package_grp_ids: list[int],
    agent_package_grp_id: Optional[int] = None,
    other_package_grp_ids: Optional[list[int]] = None,
    agent_id: Optional[int] = None,
    agent_name: Optional[str] = None,
    lab_preferences: Optional[list[LabPreference]] = None,
) -> list[dict]:
    """
    Build complete package list for a phase.

    Args:
        selection_service: Package selection service
        os_info: Target OS information
        loadgen_package_grp_ids: Load generator package group IDs
        agent_package_grp_id: Agent package group ID (optional)
        other_package_grp_ids: Other package group IDs (functional/policy tests)
        agent_id: Agent ID for tracking
        agent_name: Agent name for tracking
        lab_preferences: Lab delivery preferences

    Returns:
        Complete package list for *_package_lst
    """
    package_list = []

    # Select loadgen packages
    for grp_id in loadgen_package_grp_ids:
        selected = await selection_service.select_package(
            package_group_id=grp_id,
            os_info=os_info,
            lab_preferences=lab_preferences,
        )
        if selected:
            entry = selection_service.build_package_list_entry(
                selected=selected,
                is_measured=True,
            )
            package_list.append(entry)

    # Select agent package
    if agent_package_grp_id:
        selected = await selection_service.select_package(
            package_group_id=agent_package_grp_id,
            os_info=os_info,
            lab_preferences=lab_preferences,
        )
        if selected:
            entry = selection_service.build_package_list_entry(
                selected=selected,
                agent_id=agent_id,
                agent_name=agent_name,
                is_measured=True,
            )
            package_list.append(entry)

    # Select other packages (functional, policy tests)
    if other_package_grp_ids:
        for grp_id in other_package_grp_ids:
            selected = await selection_service.select_package(
                package_group_id=grp_id,
                os_info=os_info,
                lab_preferences=lab_preferences,
            )
            if selected:
                entry = selection_service.build_package_list_entry(
                    selected=selected,
                    is_measured=selected.run_at_load,  # Only measure if run at load
                )
                package_list.append(entry)

    return package_list
