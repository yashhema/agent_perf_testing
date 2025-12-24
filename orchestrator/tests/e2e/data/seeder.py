"""E2E test data seeder.

Seeds database with all required data for Docker-based E2E testing.
Creates proper ORM models - NO dictionaries for storing fields.

Uses REAL values:
- Baselines with actual OS info (rhel/8/4)
- Packages with delivery_config and version_check_command
- Package group members with os_match_regex patterns
- Calibration results with realistic thread counts and CPU targets
- JMX file paths pointing to actual test plans

Tables seeded (in order due to FK dependencies):
1. labs (with lab_preferences, jmeter_package_grpid)
2. hardware_profiles
3. servers (with OS info)
4. baseline (with OS vendor/version info)
5. package_groups (emulator, jmeter, security_agent)
6. packages (with delivery_config, version_check_command)
7. package_group_members (with os_match_regex, con_type)
8. lab_preferences (con_type preferences per OS)
9. scenarios
10. test_runs
11. test_run_targets (with jmx_file_path, snapshot IDs)
12. calibration_results (pre-set for Docker E2E)
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import uuid4
import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    LabORM,
    ServerORM,
    BaselineORM,
    HardwareProfileORM,
    ScenarioORM,
    ScenarioCaseORM,
    AgentORM,
    PackageGroupORM,
    PackageORM,
    PackageGroupMemberORM,
    TestRunORM,
    TestRunTargetORM,
    CalibrationResultORM,
    LabPackagePreferencesORM,
)
from app.models.enums import (
    OSFamily,
    ServerType,
    BaselineType,
    LoadProfile,
    CalibrationStatus,
    ConnectionType,
)


@dataclass(frozen=True)
class DockerContainerConfig:
    """Configuration for a Docker container in E2E test."""

    hostname: str
    container_name: str
    ip_address: str
    port: int
    server_type: ServerType
    # OS info for the container
    os_vendor: str = "rhel"
    os_major: int = 8
    os_minor: int = 4
    os_kernel: str = "4.18.0-305"


@dataclass(frozen=True)
class DockerE2EConfig:
    """Configuration for Docker-based E2E testing.

    Default setup:
    - 2 emulator containers (simulating target servers with RHEL 8.4)
    - 1 loadgen container (JMeter with Ubuntu 22.04)

    Uses REAL values for:
    - OS vendor/version (rhel/8/4 for targets, ubuntu/22/04 for loadgen)
    - Calibration thread counts (LOW=4, MEDIUM=8, HIGH=12)
    - CPU target percentages (LOW=30%, MEDIUM=50%, HIGH=70%)
    - JMX file path (/opt/jmeter/plans/e2e-load-test.jmx)
    """

    lab_name: str = "docker-e2e-lab"

    # Hardware profile for Docker containers
    cpu_count: int = 4
    memory_gb: Decimal = field(default_factory=lambda: Decimal("8.00"))

    # Emulator containers (targets) - simulating RHEL 8.4 servers
    emulator_containers: List[DockerContainerConfig] = field(
        default_factory=lambda: [
            DockerContainerConfig(
                hostname="emulator-1",
                container_name="e2e-emulator-1",
                ip_address="172.20.0.10",
                port=8080,
                server_type=ServerType.APP_SERVER,
                os_vendor="rhel",
                os_major=8,
                os_minor=4,
                os_kernel="4.18.0-305",
            ),
            DockerContainerConfig(
                hostname="emulator-2",
                container_name="e2e-emulator-2",
                ip_address="172.20.0.11",
                port=8080,
                server_type=ServerType.APP_SERVER,
                os_vendor="rhel",
                os_major=8,
                os_minor=4,
                os_kernel="4.18.0-305",
            ),
        ]
    )

    # Load generator container - simulating Ubuntu 22.04
    loadgen_containers: List[DockerContainerConfig] = field(
        default_factory=lambda: [
            DockerContainerConfig(
                hostname="loadgen-1",
                container_name="e2e-loadgen-1",
                ip_address="172.20.0.20",
                port=8090,
                server_type=ServerType.LOAD_GENERATOR,
                os_vendor="ubuntu",
                os_major=22,
                os_minor=4,
                os_kernel="5.15.0-generic",
            ),
        ]
    )

    # Pre-calibrated thread counts for Docker E2E
    # Format: {load_profile: thread_count}
    calibration_thread_counts: Dict[LoadProfile, int] = field(
        default_factory=lambda: {
            LoadProfile.LOW: 4,
            LoadProfile.MEDIUM: 8,
            LoadProfile.HIGH: 12,
        }
    )

    # CPU target percentages per load profile
    calibration_cpu_targets: Dict[LoadProfile, Decimal] = field(
        default_factory=lambda: {
            LoadProfile.LOW: Decimal("30.00"),
            LoadProfile.MEDIUM: Decimal("50.00"),
            LoadProfile.HIGH: Decimal("70.00"),
        }
    )

    # JMX file path on loadgen container
    # None = generate dynamically using JMXDeploymentService
    # Set to a path to use pre-existing JMX file
    jmx_file_path: Optional[str] = None

    # Agent package configuration
    agent_package_name: str = "security-agent"
    agent_package_version: str = "6.50.14358"


@dataclass
class SeededData:
    """Container for all seeded data references."""

    lab: Optional[LabORM] = None
    hardware_profile: Optional[HardwareProfileORM] = None
    servers: List[ServerORM] = field(default_factory=list)
    target_servers: List[ServerORM] = field(default_factory=list)
    loadgen_servers: List[ServerORM] = field(default_factory=list)
    baselines: List[BaselineORM] = field(default_factory=list)
    target_baseline: Optional[BaselineORM] = None  # For targets (RHEL)
    loadgen_baseline: Optional[BaselineORM] = None  # For loadgen (Ubuntu)
    scenario: Optional[ScenarioORM] = None
    scenario_cases: List[ScenarioCaseORM] = field(default_factory=list)
    agent: Optional[AgentORM] = None
    package_groups: List[PackageGroupORM] = field(default_factory=list)
    packages: List[PackageORM] = field(default_factory=list)
    package_group_members: List[PackageGroupMemberORM] = field(default_factory=list)
    lab_preferences: List[LabPackagePreferencesORM] = field(default_factory=list)
    test_run: Optional[TestRunORM] = None
    test_run_targets: List[TestRunTargetORM] = field(default_factory=list)
    calibration_results: List[CalibrationResultORM] = field(default_factory=list)

    # Named references for easy access
    emulator_package_group: Optional[PackageGroupORM] = None
    jmeter_package_group: Optional[PackageGroupORM] = None
    agent_package_group: Optional[PackageGroupORM] = None
    agent_package: Optional[PackageORM] = None
    jmeter_package: Optional[PackageORM] = None

    @property
    def baseline(self) -> Optional[BaselineORM]:
        """Backward compatibility: return target baseline."""
        return self.target_baseline


class E2ETestDataSeeder:
    """Seeds database with E2E test data.

    Handles creation of all required entities in correct order
    to satisfy foreign key constraints.
    """

    def __init__(
        self,
        session: AsyncSession,
        config: Optional[DockerE2EConfig] = None,
    ):
        self._session = session
        self._config = config or DockerE2EConfig()
        self._data = SeededData()

    @property
    def data(self) -> SeededData:
        """Get seeded data references."""
        return self._data

    async def seed_all(self) -> SeededData:
        """Seed all required tables for E2E testing.

        Returns SeededData with references to all created entities.

        Seeding order (FK dependencies):
        1. Lab (no deps)
        2. Hardware profile (no deps)
        3. Servers (depends on lab)
        4. Baseline (depends on lab, has OS info)
        5. Package groups (no deps)
        6. Packages (no deps, has delivery_config)
        7. Package group members (depends on groups + packages, has os_match_regex)
        8. Lab preferences (depends on lab)
        9. Agent (no deps, needed for scenario_case)
        10. Scenario + ScenarioCase (depends on lab, profile, servers, baseline, agent)
        11. Test run (depends on lab)
        12. Test run targets (depends on test_run, servers, baseline)
        13. Calibration results (depends on targets, baseline)
        """
        await self._seed_lab()
        await self._seed_hardware_profile()
        await self._seed_servers()
        await self._seed_baseline()
        await self._seed_packages()
        await self._seed_lab_preferences()
        await self._seed_agent()
        await self._seed_scenario()
        await self._seed_test_run()
        await self._seed_calibration_results()

        # Update lab with jmeter_package_grpid
        await self._update_lab_jmeter_grp()

        await self._session.commit()

        return self._data

    async def _seed_lab(self) -> None:
        """Create lab for Docker E2E testing."""
        lab = LabORM(
            name=self._config.lab_name,
            description="Docker-based E2E testing lab",
            lab_type="docker",
        )
        self._session.add(lab)
        await self._session.flush()

        self._data.lab = lab

    async def _seed_hardware_profile(self) -> None:
        """Create hardware profile for Docker containers."""
        profile = HardwareProfileORM(
            name="docker-e2e-profile",
            description="Hardware profile for Docker E2E containers",
            cpu_count=self._config.cpu_count,
            memory_gb=self._config.memory_gb,
            disk_type="ssd",
            disk_size_gb=50,
        )
        self._session.add(profile)
        await self._session.flush()

        self._data.hardware_profile = profile

    async def _seed_servers(self) -> None:
        """Create servers for all Docker containers.

        NOTE: Detailed OS info (vendor, major, minor, kernel) is stored
        in BaselineORM, not ServerORM. ServerORM only has os_family.
        OSDiscoveryService populates baseline OS info dynamically.
        """
        # Create target servers (emulator containers)
        for container in self._config.emulator_containers:
            server = ServerORM(
                hostname=container.hostname,
                ip_address=container.ip_address,
                os_family=OSFamily.LINUX.value,
                server_type=container.server_type.value,
                ssh_username="root",
                emulator_port=container.port,
                loadgen_service_port=8090,
                is_active=True,
                lab_id=self._data.lab.id,
            )
            self._session.add(server)
            await self._session.flush()

            self._data.servers.append(server)
            self._data.target_servers.append(server)

        # Create load generator servers
        for container in self._config.loadgen_containers:
            server = ServerORM(
                hostname=container.hostname,
                ip_address=container.ip_address,
                os_family=OSFamily.LINUX.value,
                server_type=container.server_type.value,
                ssh_username="root",
                emulator_port=8080,
                loadgen_service_port=container.port,
                is_active=True,
                lab_id=self._data.lab.id,
            )
            self._session.add(server)
            await self._session.flush()

            self._data.servers.append(server)
            self._data.loadgen_servers.append(server)

    async def _seed_baseline(self) -> None:
        """Create baselines for Docker E2E testing.

        For Docker E2E, baseline represents container restart (simulating snapshot revert).
        Creates separate baselines for:
        1. Target servers (RHEL 8.4) - used for agent package resolution
        2. Loadgen servers (Ubuntu 22.04) - used for JMeter package resolution

        OS format for matching: {os_vendor}/{os_major}/{os_minor}[/{kernel}]
        Example: rhel/8/4/4.18.0-305
        """
        # Create target baseline (RHEL 8.4)
        target_container = self._config.emulator_containers[0]
        target_baseline = BaselineORM(
            name="docker-e2e-target-baseline",
            description="Docker container restart baseline (RHEL 8.4)",
            baseline_type=BaselineType.VSPHERE.value,
            baseline_conf={
                "type": "docker",
                "restart_policy": "always",
                "health_check_timeout_sec": 30,
                "container_network": "e2e-network",
            },
            # OS information for package selection
            os_vendor_family=target_container.os_vendor,
            os_major_ver=str(target_container.os_major),
            os_minor_ver=str(target_container.os_minor),
            os_kernel_ver=target_container.os_kernel,
            baseline_scope="target",
            lab_id=self._data.lab.id,
        )
        self._session.add(target_baseline)
        await self._session.flush()

        self._data.baselines.append(target_baseline)
        self._data.target_baseline = target_baseline

        # Create loadgen baseline (Ubuntu 22.04)
        loadgen_container = self._config.loadgen_containers[0]
        loadgen_baseline = BaselineORM(
            name="docker-e2e-loadgen-baseline",
            description="Docker container restart baseline (Ubuntu 22.04)",
            baseline_type=BaselineType.VSPHERE.value,
            baseline_conf={
                "type": "docker",
                "restart_policy": "always",
                "health_check_timeout_sec": 30,
                "container_network": "e2e-network",
            },
            # OS information for package selection
            os_vendor_family=loadgen_container.os_vendor,
            os_major_ver=str(loadgen_container.os_major),
            os_minor_ver=str(loadgen_container.os_minor),
            os_kernel_ver=loadgen_container.os_kernel,
            baseline_scope="loadgen",
            lab_id=self._data.lab.id,
        )
        self._session.add(loadgen_baseline)
        await self._session.flush()

        self._data.baselines.append(loadgen_baseline)
        self._data.loadgen_baseline = loadgen_baseline

    async def _seed_packages(self) -> None:
        """Create package groups and packages for E2E testing.

        Creates:
        1. CPU Emulator package group (for emulator on targets)
        2. JMeter package group (for load generator)
        3. Security Agent package group (the agent being tested)

        Each package has:
        - delivery_config: JSONB with installation scripts/commands
        - version_check_command: Command to verify installed version
        - os_match_regex: Pattern to match OS (e.g., "rhel/8/.*")
        - con_type: Connection type (SCRIPT, SSH, etc.)
        """
        # ================================================================
        # 1. Create CPU Emulator package group
        # ================================================================
        emulator_group = PackageGroupORM(
            name="cpu-emulator",
            description="CPU load emulator package for target servers",
            group_type="emulator",
            is_active=True,
        )
        self._session.add(emulator_group)
        await self._session.flush()
        self._data.package_groups.append(emulator_group)
        self._data.emulator_package_group = emulator_group

        # ================================================================
        # 2. Create JMeter package group
        # ================================================================
        jmeter_group = PackageGroupORM(
            name="jmeter-loadgen",
            description="Apache JMeter load generator package",
            group_type="loadgen",
            is_active=True,
        )
        self._session.add(jmeter_group)
        await self._session.flush()
        self._data.package_groups.append(jmeter_group)
        self._data.jmeter_package_group = jmeter_group

        # ================================================================
        # 3. Create Security Agent package group
        # ================================================================
        agent_group = PackageGroupORM(
            name="security-agent",
            description="Security agent package under test",
            group_type="agent",
            is_active=True,
        )
        self._session.add(agent_group)
        await self._session.flush()
        self._data.package_groups.append(agent_group)
        self._data.agent_package_group = agent_group

        # ================================================================
        # Create Packages with delivery_config and version_check_command
        # ================================================================

        # CPU Emulator package
        emulator_pkg = PackageORM(
            name="cpu-emulator",
            version="1.0.0",
            description="CPU load emulator for agent performance testing",
            package_type="emulator",
            download_url="http://packages.internal/cpu-emulator-1.0.0.tar.gz",
            install_command="pip install cpu-emulator",
            verify_command="cpu-emulator --version",
            is_active=True,
            delivery_config={
                "type": "SCRIPT",
                "install_script": "#!/bin/bash\npip install cpu-emulator==1.0.0",
                "uninstall_script": "#!/bin/bash\npip uninstall -y cpu-emulator",
                "timeout_sec": 300,
            },
            version_check_command="cpu-emulator --version 2>&1 | grep -oP '\\d+\\.\\d+\\.\\d+'",
            expected_version_regex=r"^\d+\.\d+\.\d+$",
            execution_result_path="/var/log/cpu-emulator/results.json",
            stats_collect_path="/var/log/cpu-emulator/stats.json",
        )
        self._session.add(emulator_pkg)
        await self._session.flush()
        self._data.packages.append(emulator_pkg)

        # JMeter package
        jmeter_pkg = PackageORM(
            name="apache-jmeter",
            version="5.6.3",
            description="Apache JMeter load testing tool",
            package_type="loadgen",
            download_url="https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.tgz",
            install_command="tar -xzf apache-jmeter-5.6.3.tgz -C /opt",
            verify_command="/opt/apache-jmeter-5.6.3/bin/jmeter --version",
            is_active=True,
            delivery_config={
                "type": "SCRIPT",
                "install_script": """#!/bin/bash
set -e
cd /opt
curl -sL https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.tgz -o jmeter.tgz
tar -xzf jmeter.tgz
rm jmeter.tgz
ln -sf /opt/apache-jmeter-5.6.3/bin/jmeter /usr/local/bin/jmeter
""",
                "uninstall_script": "#!/bin/bash\nrm -rf /opt/apache-jmeter-5.6.3 /usr/local/bin/jmeter",
                "timeout_sec": 600,
            },
            version_check_command="/opt/apache-jmeter-5.6.3/bin/jmeter --version 2>&1 | head -1",
            expected_version_regex=r".*5\.6\.3.*",
            execution_result_path="/var/log/jmeter/results.jtl",
            stats_collect_path="/var/log/jmeter/stats.json",
            logs_collect_path="/var/log/jmeter/jmeter.log",
        )
        self._session.add(jmeter_pkg)
        await self._session.flush()
        self._data.packages.append(jmeter_pkg)
        self._data.jmeter_package = jmeter_pkg

        # Security Agent package (the one being tested)
        agent_pkg = PackageORM(
            name=self._config.agent_package_name,
            version=self._config.agent_package_version,
            description="Security agent package under performance testing",
            package_type="agent",
            download_url=f"http://packages.internal/{self._config.agent_package_name}-{self._config.agent_package_version}.rpm",
            install_command=f"yum install -y {self._config.agent_package_name}",
            verify_command="rpm -q security-agent",
            is_active=True,
            delivery_config={
                "type": "SCRIPT",
                "install_script": f"""#!/bin/bash
set -e
# Download and install security agent
curl -sL http://packages.internal/{self._config.agent_package_name}-{self._config.agent_package_version}.rpm -o /tmp/agent.rpm
yum install -y /tmp/agent.rpm
rm /tmp/agent.rpm
systemctl enable security-agent
systemctl start security-agent
""",
                "uninstall_script": """#!/bin/bash
systemctl stop security-agent || true
systemctl disable security-agent || true
yum remove -y security-agent
""",
                "timeout_sec": 600,
                "requires_reboot": False,
            },
            version_check_command="rpm -q security-agent --queryformat '%{VERSION}'",
            expected_version_regex=r"^\d+\.\d+\.\d+$",
            uninstall_command="yum remove -y security-agent",
            execution_result_path="/var/log/security-agent/execution.json",
            stats_collect_path="/var/log/security-agent/stats.json",
            logs_collect_path="/var/log/security-agent/agent.log",
            restart_timeout_sec=120,
        )
        self._session.add(agent_pkg)
        await self._session.flush()
        self._data.packages.append(agent_pkg)
        self._data.agent_package = agent_pkg

        # ================================================================
        # Create Package Group Members with os_match_regex and con_type
        # ================================================================

        # Emulator member for RHEL 8.x (matches rhel/8/*)
        emulator_member_rhel = PackageGroupMemberORM(
            package_group_id=emulator_group.id,
            package_id=emulator_pkg.id,
            os_match_regex=r"rhel/8/.*",
            con_type=ConnectionType.SCRIPT.value,
            priority=0,
        )
        self._session.add(emulator_member_rhel)

        # Emulator member for Ubuntu 22.x
        emulator_member_ubuntu = PackageGroupMemberORM(
            package_group_id=emulator_group.id,
            package_id=emulator_pkg.id,
            os_match_regex=r"ubuntu/22/.*",
            con_type=ConnectionType.SCRIPT.value,
            priority=0,
        )
        self._session.add(emulator_member_ubuntu)

        # JMeter member for any Linux (loadgen doesn't need strict OS match)
        jmeter_member = PackageGroupMemberORM(
            package_group_id=jmeter_group.id,
            package_id=jmeter_pkg.id,
            os_match_regex=r".*",  # Matches any OS
            con_type=ConnectionType.SCRIPT.value,
            priority=0,
        )
        self._session.add(jmeter_member)

        # Agent member for RHEL 8.x
        agent_member_rhel = PackageGroupMemberORM(
            package_group_id=agent_group.id,
            package_id=agent_pkg.id,
            os_match_regex=r"rhel/8/.*",
            con_type=ConnectionType.SCRIPT.value,
            priority=0,
        )
        self._session.add(agent_member_rhel)

        # Agent member for RHEL 7.x (different package version would be here)
        agent_member_rhel7 = PackageGroupMemberORM(
            package_group_id=agent_group.id,
            package_id=agent_pkg.id,  # Same package for now
            os_match_regex=r"rhel/7/.*",
            con_type=ConnectionType.SCRIPT.value,
            priority=0,
        )
        self._session.add(agent_member_rhel7)

        await self._session.flush()

        self._data.package_group_members.extend([
            emulator_member_rhel,
            emulator_member_ubuntu,
            jmeter_member,
            agent_member_rhel,
            agent_member_rhel7,
        ])

    async def _seed_lab_preferences(self) -> None:
        """Create lab package preferences for connection types.

        Defines preferred_con_type and fallback_con_type per OS family.
        This controls which delivery strategy is used for each OS.
        """
        # RHEL preference for agent packages: SCRIPT preferred, SSM fallback
        rhel_pref = LabPackagePreferencesORM(
            lab_id=self._data.lab.id,
            package_type="agent",
            os_vendor_family="rhel",
            preferred_con_type=ConnectionType.SCRIPT.value,
            fallback_con_type=ConnectionType.SSM.value,
            priority=0,
        )
        self._session.add(rhel_pref)

        # Ubuntu preference for agent packages: SCRIPT preferred, SSM fallback
        ubuntu_pref = LabPackagePreferencesORM(
            lab_id=self._data.lab.id,
            package_type="agent",
            os_vendor_family="ubuntu",
            preferred_con_type=ConnectionType.SCRIPT.value,
            fallback_con_type=ConnectionType.SSM.value,
            priority=0,
        )
        self._session.add(ubuntu_pref)

        # Default preference (any OS, any package type): SCRIPT preferred
        default_pref = LabPackagePreferencesORM(
            lab_id=self._data.lab.id,
            package_type="default",
            os_vendor_family=None,  # Matches any OS
            preferred_con_type=ConnectionType.SCRIPT.value,
            fallback_con_type=None,
            priority=100,  # Lower priority than specific matches
        )
        self._session.add(default_pref)

        await self._session.flush()

        self._data.lab_preferences.extend([rhel_pref, ubuntu_pref, default_pref])

    async def _seed_agent(self) -> None:
        """Create agent record for E2E testing."""
        agent = AgentORM(
            name=self._config.agent_package_name,
            description="Security agent for E2E performance testing",
            is_active=True,
        )
        self._session.add(agent)
        await self._session.flush()

        self._data.agent = agent

    async def _seed_scenario(self) -> None:
        """Create scenario for E2E testing.

        Sets up:
        - ScenarioORM with load_generator_package_grp_id (emulator for base phase)
        - ScenarioCaseORM with initial/upgrade_package_grp_id (agent packages)

        Package resolution mapping:
        - Base phase: scenario.load_generator_package_grp_id -> emulator package
        - Initial phase: scenario_case.initial_package_grp_id -> agent package
        - Upgrade phase: scenario_case.upgrade_package_grp_id -> agent package
        """
        target_ids = [s.id for s in self._data.target_servers]
        loadgen_ids = [s.id for s in self._data.loadgen_servers]

        # Get emulator package group ID for base phase
        emulator_grp_id = (
            self._data.emulator_package_group.id
            if self._data.emulator_package_group else None
        )

        scenario = ScenarioORM(
            name="docker-e2e-scenario",
            description="Docker-based E2E test scenario with 2 RHEL 8.4 targets and 1 Ubuntu loadgen",
            lab_id=self._data.lab.id,
            hardware_profile_id=self._data.hardware_profile.id,
            target_server_ids=target_ids,
            loadgen_server_ids=loadgen_ids,
            baseline_id=self._data.baseline.id,
            is_calibrated=True,  # Pre-calibrated for Docker E2E
            calibrated_at=datetime.utcnow(),
            is_active=True,
            # Emulator package group for base phase (load generator on target)
            load_generator_package_grp_id=emulator_grp_id,
        )
        self._session.add(scenario)
        await self._session.flush()

        self._data.scenario = scenario

        # Create ScenarioCaseORM for initial/upgrade phases
        # ScenarioCase defines which agent packages to install per phase
        agent_grp_id = (
            self._data.agent_package_group.id
            if self._data.agent_package_group else None
        )

        if agent_grp_id and self._data.agent:
            scenario_case = ScenarioCaseORM(
                scenario_id=scenario.id,
                agent_id=self._data.agent.id,
                # Agent package group for initial phase
                initial_package_grp_id=agent_grp_id,
                # Agent package group for upgrade phase (same version for E2E)
                upgrade_package_grp_id=agent_grp_id,
            )
            self._session.add(scenario_case)
            await self._session.flush()

            self._data.scenario_cases.append(scenario_case)

    async def _seed_test_run(self) -> None:
        """Create test run with targets for E2E testing.

        Creates:
        - TestRunORM with load profiles and timing configuration
        - TestRunTargetORM for each target with:
          - jmx_file_path: Path to JMeter test plan
          - base_snapshot_id: Baseline for the base phase
          - All snapshot IDs point to same baseline (Docker restart simulation)
        """
        # Get agent package group ID (package on target server being tested)
        agent_group_id = self._data.agent_package_group.id if self._data.agent_package_group else None

        test_run = TestRunORM(
            name="docker-e2e-test-run",
            description="Docker E2E test run: security-agent performance on RHEL 8.4",
            req_loadprofile=[
                LoadProfile.LOW.value,
                LoadProfile.MEDIUM.value,
                LoadProfile.HIGH.value,
            ],
            warmup_sec=10,  # Short for E2E testing
            measured_sec=60,  # Short for E2E testing
            analysis_trim_sec=5,
            repetitions=1,
            # Agent package on target servers
            loadgenerator_package_grpid_lst=[agent_group_id] if agent_group_id else [],
            lab_id=self._data.lab.id,
        )
        self._session.add(test_run)
        await self._session.flush()

        self._data.test_run = test_run

        # Create test run targets - map each target to loadgen
        loadgen = self._data.loadgen_servers[0]
        jmeter_base_port = 4445

        for idx, target in enumerate(self._data.target_servers):
            test_run_target = TestRunTargetORM(
                test_run_id=test_run.id,
                scenario_id=self._data.scenario.id if self._data.scenario else None,
                target_id=target.id,
                loadgenerator_id=loadgen.id,
                jmeter_port=jmeter_base_port + idx,
                # JMX file path on the loadgen server
                jmx_file_path=self._config.jmx_file_path,
                # Snapshot IDs for each phase (baseline to revert to)
                # In Docker E2E, all phases use the same baseline (container restart)
                base_snapshot_id=self._data.baseline.id,
                initial_snapshot_id=self._data.baseline.id,
                upgrade_snapshot_id=self._data.baseline.id,
            )
            self._session.add(test_run_target)

            self._data.test_run_targets.append(test_run_target)

        await self._session.flush()

    async def _seed_calibration_results(self) -> None:
        """Create pre-calibrated results for Docker E2E testing.

        Calibration is done ONCE per scenario for all targets and profiles.
        For Docker E2E, we pre-seed these values:
        - LOW: 4 threads → 30% CPU
        - MEDIUM: 8 threads → 50% CPU
        - HIGH: 12 threads → 70% CPU

        Achieved CPU is slightly below target (simulating real calibration).
        """
        for target in self._data.target_servers:
            for profile, thread_count in self._config.calibration_thread_counts.items():
                cpu_target_percent = self._config.calibration_cpu_targets[profile]
                # Simulate achieved being slightly below target
                achieved_cpu = cpu_target_percent - Decimal("0.50")

                calibration = CalibrationResultORM(
                    target_id=target.id,
                    baseline_id=self._data.baseline.id,
                    loadprofile=profile.value,
                    thread_count=thread_count,
                    cpu_count=self._config.cpu_count,
                    memory_gb=self._config.memory_gb,
                    cpu_target_percent=cpu_target_percent,
                    achieved_cpu_percent=achieved_cpu,
                    calibration_run_id=uuid4(),
                    calibration_status=CalibrationStatus.COMPLETED.value,
                    calibrated_at=datetime.utcnow(),
                )
                self._session.add(calibration)

                self._data.calibration_results.append(calibration)

        await self._session.flush()

    async def _update_lab_jmeter_grp(self) -> None:
        """Update lab with jmeter_package_grpid.

        This must be called after packages are seeded since we need the group ID.
        """
        if self._data.lab and self._data.jmeter_package_group:
            self._data.lab.jmeter_package_grpid = self._data.jmeter_package_group.id
            await self._session.flush()

    async def cleanup(self) -> None:
        """Remove all seeded test data.

        Deletes in reverse order of creation to respect FK constraints.
        """
        # Delete in reverse order
        for cal in self._data.calibration_results:
            await self._session.delete(cal)

        for target in self._data.test_run_targets:
            await self._session.delete(target)

        if self._data.test_run:
            await self._session.delete(self._data.test_run)

        # Delete scenario cases before scenario
        for scenario_case in self._data.scenario_cases:
            await self._session.delete(scenario_case)
        await self._session.flush()

        if self._data.scenario:
            await self._session.delete(self._data.scenario)
        # Flush scenarios before deleting package_groups they reference
        await self._session.flush()

        # Delete agent after scenario_cases (which reference it)
        if self._data.agent:
            await self._session.delete(self._data.agent)

        for pref in self._data.lab_preferences:
            await self._session.delete(pref)

        for member in self._data.package_group_members:
            await self._session.delete(member)
        await self._session.flush()

        for pkg in self._data.packages:
            await self._session.delete(pkg)
        await self._session.flush()

        # Clear lab's jmeter_package_grpid before deleting package_groups
        if self._data.lab and self._data.lab.jmeter_package_grpid:
            self._data.lab.jmeter_package_grpid = None
            await self._session.flush()

        for group in self._data.package_groups:
            await self._session.delete(group)
        await self._session.flush()

        for baseline in self._data.baselines:
            await self._session.delete(baseline)

        for server in self._data.servers:
            await self._session.delete(server)

        if self._data.hardware_profile:
            await self._session.delete(self._data.hardware_profile)

        if self._data.lab:
            await self._session.delete(self._data.lab)

        await self._session.commit()

        # Reset data container
        self._data = SeededData()
