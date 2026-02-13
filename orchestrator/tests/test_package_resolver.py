"""Tests for the package resolver."""

import pytest
from unittest.mock import MagicMock

from orchestrator.services.package_manager import PackageResolver
from orchestrator.models.enums import BaselineType, OSFamily
from orchestrator.models.orm import (
    BaselineORM,
    PackageGroupMemberORM,
    PackageGroupORM,
)


@pytest.fixture
def resolver():
    return PackageResolver()


class TestOSStringBuilding:
    def test_linux_os_string(self, resolver):
        baseline = MagicMock(spec=BaselineORM)
        baseline.os_vendor_family = "ubuntu"
        baseline.os_major_ver = "22"
        baseline.os_minor_ver = "04"
        os_str = f"{baseline.os_vendor_family}/{baseline.os_major_ver}/{baseline.os_minor_ver}"
        assert os_str == "ubuntu/22/04"

    def test_windows_os_string(self):
        baseline = MagicMock(spec=BaselineORM)
        baseline.os_vendor_family = "windows"
        baseline.os_major_ver = "2022"
        baseline.os_minor_ver = ""
        os_str = f"{baseline.os_vendor_family}/{baseline.os_major_ver}/{baseline.os_minor_ver}"
        assert os_str == "windows/2022/"


class TestResolve:
    def test_resolve_single_match(self, session, sample_package_group, sample_baseline, resolver):
        """Resolve a package group with one matching member."""
        member = PackageGroupMemberORM(
            package_group_id=sample_package_group.id,
            os_match_regex="ubuntu/22/.*",
            path="/packages/jmeter-linux.tar.gz",
            root_install_path="/opt/jmeter",
            extraction_command="tar xzf {package} -C {root}",
            install_command="{root}/bin/install.sh",
        )
        session.add(member)
        session.commit()

        results = resolver.resolve(
            session,
            [sample_package_group.id],
            sample_baseline,
        )
        assert len(results) == 1
        assert results[0].path == "/packages/jmeter-linux.tar.gz"

    def test_resolve_no_match(self, session, sample_package_group, resolver):
        """Resolve fails when no member matches the OS string."""
        member = PackageGroupMemberORM(
            package_group_id=sample_package_group.id,
            os_match_regex="windows/.*",
            path="/packages/jmeter-win.zip",
            root_install_path="C:\\jmeter",
        )
        session.add(member)
        session.commit()

        # Create a Linux baseline that won't match the windows regex
        baseline = BaselineORM(
            name="centos-9",
            os_family=OSFamily.linux,
            os_vendor_family="centos",
            os_major_ver="9",
            os_minor_ver="0",
            baseline_type=BaselineType.proxmox,
            provider_ref={"snapshot_name": "snap"},
        )
        session.add(baseline)
        session.commit()

        with pytest.raises(ValueError, match="No package matches OS"):
            resolver.resolve(session, [sample_package_group.id], baseline)
