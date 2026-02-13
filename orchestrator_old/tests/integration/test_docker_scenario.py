"""Integration tests for Docker-based scenario execution.

Tests:
- Package resolution for Docker targets and load generators
- Delta deployment logic
- Multi-target orchestration
- Calibration with barrier sync
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.packages.resolver import PackageResolver
from tests.integration.fixtures import create_docker_test_data, DockerTestData


@pytest_asyncio.fixture
async def test_data(session: AsyncSession) -> DockerTestData:
    """Create Docker test data."""
    return await create_docker_test_data(session)


class TestPackageResolver:
    """Tests for PackageResolver with Docker test data."""

    @pytest.mark.asyncio
    async def test_resolve_jmeter_packages_ubuntu(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving JMeter packages for Ubuntu load generator."""
        resolver = PackageResolver(session)

        # LoadGenerator uses server_id + detected OS (not baseline)
        detected_os = {
            "os_vendor_family": "ubuntu",
            "os_major_ver": "22",
            "os_minor_ver": "04",
            "os_kernel_ver": "5.15.0-generic",
        }

        packages = await resolver.resolve_jmeter_packages(
            lab_id=test_data.lab.id,
            loadgen_server_id=test_data.loadgen1.id,
            detected_os_info=detected_os,
        )

        assert len(packages) == 1
        assert packages[0]["package_name"] == "apache-jmeter"
        assert packages[0]["version"] == "5.5"
        assert packages[0]["con_type"] == "docker_exec"

    @pytest.mark.asyncio
    async def test_resolve_base_packages_rhel(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving base phase packages (emulator) for RHEL target."""
        resolver = PackageResolver(session)

        packages = await resolver.resolve_base_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
        )

        assert len(packages) == 1
        assert packages[0]["package_name"] == "cpu-emulator-rhel"
        assert packages[0]["version"] == "1.0.0"
        assert packages[0]["con_type"] == "docker_exec"

    @pytest.mark.asyncio
    async def test_resolve_initial_packages_combined(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving initial phase packages (emulator + agent + functional)."""
        resolver = PackageResolver(session)

        packages = await resolver.resolve_initial_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
            agent_id=test_data.agent.id,
            include_emulator=True,
        )

        # Should have: emulator + agent v1 + functional tests = 3 packages
        assert len(packages) == 3

        package_names = [p["package_name"] for p in packages]
        assert "cpu-emulator-rhel" in package_names
        assert "security-agent-rhel" in package_names
        assert "functional-tests" in package_names

        # Agent should be v1.0.0
        agent_pkg = next(p for p in packages if p["package_name"] == "security-agent-rhel")
        assert agent_pkg["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_resolve_initial_packages_delta(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving initial phase delta (skip emulator, already installed)."""
        resolver = PackageResolver(session)

        packages = await resolver.resolve_initial_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
            agent_id=test_data.agent.id,
            include_emulator=False,  # Delta - skip emulator
        )

        # Should have: agent v1 + functional tests = 2 packages (no emulator)
        assert len(packages) == 2

        package_names = [p["package_name"] for p in packages]
        assert "cpu-emulator-rhel" not in package_names
        assert "security-agent-rhel" in package_names
        assert "functional-tests" in package_names

    @pytest.mark.asyncio
    async def test_resolve_upgrade_packages_combined(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving upgrade phase packages (emulator + upgrade agent + functional)."""
        resolver = PackageResolver(session)

        packages = await resolver.resolve_upgrade_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
            agent_id=test_data.agent.id,
            include_emulator=True,
            include_other_packages=True,
        )

        # Should have: emulator + agent v2 + functional tests = 3 packages
        assert len(packages) == 3

        package_names = [p["package_name"] for p in packages]
        assert "cpu-emulator-rhel" in package_names
        assert "security-agent-rhel" in package_names
        assert "functional-tests" in package_names

        # Agent should be v2.0.0 (upgrade version)
        agent_pkg = next(p for p in packages if p["package_name"] == "security-agent-rhel")
        assert agent_pkg["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_resolve_upgrade_packages_delta(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving upgrade phase delta (only upgrade agent)."""
        resolver = PackageResolver(session)

        packages = await resolver.resolve_upgrade_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
            agent_id=test_data.agent.id,
            include_emulator=False,  # Delta - skip emulator
            include_other_packages=False,  # Delta - skip functional (already installed)
        )

        # Should have: agent v2 only = 1 package
        assert len(packages) == 1
        assert packages[0]["package_name"] == "security-agent-rhel"
        assert packages[0]["version"] == "2.0.0"


class TestDeltaDeployment:
    """Tests for delta deployment logic."""

    @pytest.mark.asyncio
    async def test_delta_with_same_baseline(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test delta deployment when baseline doesn't change."""
        resolver = PackageResolver(session)

        # Same baseline for all phases (delta should be used)
        base_baseline = test_data.rhel84_baseline.id
        initial_baseline = test_data.rhel84_baseline.id  # Same

        # Initial phase with same baseline -> delta
        packages = await resolver.resolve_packages_with_delta(
            phase="initial",
            scenario_id=test_data.scenario.id,
            current_baseline_id=initial_baseline,
            previous_baseline_id=base_baseline,
            agent_id=test_data.agent.id,
        )

        # Delta should skip emulator (already installed in base)
        package_names = [p["package_name"] for p in packages]
        assert "cpu-emulator-rhel" not in package_names
        assert "security-agent-rhel" in package_names
        assert "functional-tests" in package_names

    @pytest.mark.asyncio
    async def test_complete_with_different_baseline(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test complete deployment when baseline changes."""
        resolver = PackageResolver(session)

        # Different baseline -> complete deployment
        base_baseline = test_data.rhel84_baseline.id
        # Simulate different baseline (using different ID)
        different_baseline = test_data.ubuntu2204_baseline.id  # Different!

        # Since baseline is different, should get complete list
        # Note: This will fail OS matching since ubuntu != rhel,
        # but demonstrates the logic flow
        packages = await resolver.resolve_packages_with_delta(
            phase="initial",
            scenario_id=test_data.scenario.id,
            current_baseline_id=base_baseline,  # Use RHEL for packages
            previous_baseline_id=different_baseline,  # Different baseline
            agent_id=test_data.agent.id,
        )

        # Complete list should include emulator
        package_names = [p["package_name"] for p in packages]
        assert "cpu-emulator-rhel" in package_names

    @pytest.mark.asyncio
    async def test_resolve_all_phases_with_delta(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test resolving all phases with proper delta logic."""
        resolver = PackageResolver(session)

        detected_loadgen_os = {
            "os_vendor_family": "ubuntu",
            "os_major_ver": "22",
            "os_minor_ver": "04",
        }

        result = await resolver.resolve_all_phases_with_delta(
            lab_id=test_data.lab.id,
            scenario_id=test_data.scenario.id,
            base_baseline_id=test_data.rhel84_baseline.id,
            initial_baseline_id=test_data.rhel84_baseline.id,  # Same
            upgrade_baseline_id=test_data.rhel84_baseline.id,  # Same
            loadgen_server_id=test_data.loadgen1.id,
            loadgen_detected_os=detected_loadgen_os,
            agent_id=test_data.agent.id,
        )

        # JMeter packages (for load generator)
        assert len(result["jmeter_packages"]) == 1
        assert result["jmeter_packages"][0]["package_name"] == "apache-jmeter"

        # Base packages (emulator only)
        assert len(result["base_packages"]) == 1
        assert result["base_packages"][0]["package_name"] == "cpu-emulator-rhel"

        # Initial packages (delta - no emulator since baseline same)
        initial_pkg_names = [p["package_name"] for p in result["initial_packages"]]
        assert "cpu-emulator-rhel" not in initial_pkg_names
        assert "security-agent-rhel" in initial_pkg_names

        # Upgrade packages (delta - only upgrade agent)
        upgrade_pkg_names = [p["package_name"] for p in result["upgrade_packages"]]
        assert "cpu-emulator-rhel" not in upgrade_pkg_names
        assert "functional-tests" not in upgrade_pkg_names  # Already in initial
        assert "security-agent-rhel" in upgrade_pkg_names

        # Verify upgrade has v2
        upgrade_agent = next(
            p for p in result["upgrade_packages"]
            if p["package_name"] == "security-agent-rhel"
        )
        assert upgrade_agent["version"] == "2.0.0"


class TestMultiTarget:
    """Tests for multi-target scenarios."""

    @pytest.mark.asyncio
    async def test_both_targets_same_packages(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that both targets get same packages (same OS)."""
        resolver = PackageResolver(session)

        # Target 1
        packages1 = await resolver.resolve_base_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
        )

        # Target 2 (same baseline, same OS)
        packages2 = await resolver.resolve_base_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
        )

        # Both should get same packages
        assert len(packages1) == len(packages2)
        assert packages1[0]["package_id"] == packages2[0]["package_id"]

    @pytest.mark.asyncio
    async def test_loadgens_same_jmeter(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that both load generators get same JMeter packages."""
        resolver = PackageResolver(session)

        detected_os = {
            "os_vendor_family": "ubuntu",
            "os_major_ver": "22",
            "os_minor_ver": "04",
        }

        # LoadGen 1
        packages1 = await resolver.resolve_jmeter_packages(
            lab_id=test_data.lab.id,
            loadgen_server_id=test_data.loadgen1.id,
            detected_os_info=detected_os,
        )

        # LoadGen 2
        packages2 = await resolver.resolve_jmeter_packages(
            lab_id=test_data.lab.id,
            loadgen_server_id=test_data.loadgen2.id,
            detected_os_info=detected_os,
        )

        # Both should get same JMeter
        assert len(packages1) == len(packages2) == 1
        assert packages1[0]["package_id"] == packages2[0]["package_id"]


class TestOSMatching:
    """Tests for OS pattern matching."""

    @pytest.mark.asyncio
    async def test_rhel_8_matches_rhel_pattern(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that RHEL 8.4 matches rhel/8/.* pattern."""
        resolver = PackageResolver(session)

        os_string = await resolver.get_baseline_os_string(
            test_data.rhel84_baseline.id
        )

        assert os_string == "rhel/8/4"

        # Verify package resolution works
        packages = await resolver.resolve_base_packages(
            baseline_id=test_data.rhel84_baseline.id,
            scenario_id=test_data.scenario.id,
        )

        assert len(packages) == 1
        assert packages[0]["package_name"] == "cpu-emulator-rhel"

    @pytest.mark.asyncio
    async def test_ubuntu_22_matches_ubuntu_pattern(
        self, session: AsyncSession, test_data: DockerTestData
    ):
        """Test that Ubuntu 22.04 matches ubuntu/22/.* pattern."""
        resolver = PackageResolver(session)

        os_string = await resolver.get_baseline_os_string(
            test_data.ubuntu2204_baseline.id
        )

        assert os_string == "ubuntu/22/04"

        # JMeter should match for Ubuntu
        detected_os = {
            "os_vendor_family": "ubuntu",
            "os_major_ver": "22",
            "os_minor_ver": "04",
        }

        packages = await resolver.resolve_jmeter_packages(
            lab_id=test_data.lab.id,
            loadgen_server_id=test_data.loadgen1.id,
            detected_os_info=detected_os,
        )

        assert len(packages) == 1
        assert packages[0]["package_name"] == "apache-jmeter"
