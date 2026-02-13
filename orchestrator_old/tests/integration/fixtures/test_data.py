"""Test data fixtures for Docker-based testing.

Creates test data for:
- 2 Docker target servers (RHEL 8.4)
- 2 Load Generator servers (Ubuntu 22.04)
- Package groups: JMeter, Emulator, Agent
- Scenario with 2 targets + 2 loadgens
- Test run with test run targets
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    AgentORM,
    BaselineORM,
    HardwareProfileORM,
    LabORM,
    PackageGroupMemberORM,
    PackageGroupORM,
    PackageORM,
    ScenarioCaseORM,
    ScenarioORM,
    ServerORM,
    TestRunORM,
    TestRunTargetORM,
)


@dataclass
class DockerTestData:
    """Container for all test data objects."""
    # Lab
    lab: LabORM

    # Hardware profiles
    target_hw_profile: HardwareProfileORM
    loadgen_hw_profile: HardwareProfileORM

    # Baselines (Docker images)
    rhel84_baseline: BaselineORM
    ubuntu2204_baseline: BaselineORM

    # Servers (2 targets + 2 loadgens = 4 total)
    target1: ServerORM
    target2: ServerORM
    loadgen1: ServerORM
    loadgen2: ServerORM

    # Package groups
    jmeter_pkg_group: PackageGroupORM
    emulator_pkg_group: PackageGroupORM
    agent_initial_pkg_group: PackageGroupORM
    agent_upgrade_pkg_group: PackageGroupORM
    functional_pkg_group: PackageGroupORM

    # Packages
    jmeter_pkg: PackageORM
    emulator_rhel_pkg: PackageORM
    emulator_ubuntu_pkg: PackageORM
    agent_v1_rhel_pkg: PackageORM
    agent_v2_rhel_pkg: PackageORM
    functional_test_pkg: PackageORM

    # Agent
    agent: AgentORM

    # Scenario
    scenario: ScenarioORM
    scenario_case: ScenarioCaseORM

    # Test run
    test_run: TestRunORM
    test_run_target1: TestRunTargetORM
    test_run_target2: TestRunTargetORM


async def create_docker_test_data(session: AsyncSession) -> DockerTestData:
    """
    Create complete test data for Docker-based testing.

    Setup:
    - Lab with docker capability
    - 2 RHEL 8.4 Docker targets (target1, target2)
    - 2 Ubuntu 22.04 Docker loadgens (loadgen1, loadgen2)
    - JMeter packages for Ubuntu
    - Emulator packages for RHEL
    - Agent packages v1 (initial) and v2 (upgrade) for RHEL
    - Scenario with base, initial, upgrade phases
    - Test run with 2 test_run_targets
    """

    # =========================================================================
    # 1. LAB with Docker capability
    # =========================================================================
    lab = LabORM(
        name="Docker Test Lab",
        description="Lab for Docker-based performance testing",
        lab_type="docker",
        capabilities=["docker"],
        secret_management="vault",
    )
    session.add(lab)
    await session.flush()

    # =========================================================================
    # 2. HARDWARE PROFILES
    # =========================================================================
    target_hw_profile = HardwareProfileORM(
        name="Docker Target Profile",
        description="4 vCPU, 8GB RAM for target containers",
        cpu_count=4,
        cpu_model="Docker vCPU",
        memory_gb=Decimal("8.0"),
        disk_type="overlay2",
        disk_size_gb=50,
    )
    session.add(target_hw_profile)

    loadgen_hw_profile = HardwareProfileORM(
        name="Docker LoadGen Profile",
        description="2 vCPU, 4GB RAM for load generator containers",
        cpu_count=2,
        cpu_model="Docker vCPU",
        memory_gb=Decimal("4.0"),
        disk_type="overlay2",
        disk_size_gb=20,
    )
    session.add(loadgen_hw_profile)
    await session.flush()

    # =========================================================================
    # 3. BASELINES (Docker images)
    # =========================================================================
    rhel84_baseline = BaselineORM(
        name="RHEL 8.4 Docker Image",
        description="Red Hat Enterprise Linux 8.4 base image",
        baseline_type="docker",
        provider_ref={
            "image": "registry.example.com/rhel:8.4",
            "registry": "registry.example.com",
            "tag": "8.4",
        },
        os_family="redhat",
        os_vendor_family="rhel",
        os_major_ver="8",
        os_minor_ver="4",
        os_kernel_ver="4.18.0-305.el8.x86_64",
        deployment_type="docker_exec",
        lab_id=lab.id,
    )
    session.add(rhel84_baseline)

    ubuntu2204_baseline = BaselineORM(
        name="Ubuntu 22.04 Docker Image",
        description="Ubuntu 22.04 LTS base image for load generators",
        baseline_type="docker",
        provider_ref={
            "image": "registry.example.com/ubuntu:22.04",
            "registry": "registry.example.com",
            "tag": "22.04",
        },
        os_family="ubuntu",
        os_vendor_family="ubuntu",
        os_major_ver="22",
        os_minor_ver="04",
        os_kernel_ver="5.15.0-generic",
        deployment_type="docker_exec",
        lab_id=lab.id,
    )
    session.add(ubuntu2204_baseline)
    await session.flush()

    # =========================================================================
    # 4. SERVERS (2 Docker targets + 2 Docker loadgens)
    # =========================================================================
    target1 = ServerORM(
        hostname="docker-target-1",
        ip_address="172.20.0.10",
        server_infra_type="docker",
        server_infra_ref={
            "container_id": "target1_container_id",
            "container_name": "docker-target-1",
            "network": "perf-test-network",
        },
        baseline_id=rhel84_baseline.id,
        hardware_profile_id=target_hw_profile.id,
        os_family="redhat",
        deployment_type="docker_exec",
        emulator_port=8080,
        loadgen_service_port=8090,
        is_active=True,
        lab_id=lab.id,
    )
    session.add(target1)

    target2 = ServerORM(
        hostname="docker-target-2",
        ip_address="172.20.0.11",
        server_infra_type="docker",
        server_infra_ref={
            "container_id": "target2_container_id",
            "container_name": "docker-target-2",
            "network": "perf-test-network",
        },
        baseline_id=rhel84_baseline.id,
        hardware_profile_id=target_hw_profile.id,
        os_family="redhat",
        deployment_type="docker_exec",
        emulator_port=8080,
        loadgen_service_port=8090,
        is_active=True,
        lab_id=lab.id,
    )
    session.add(target2)

    loadgen1 = ServerORM(
        hostname="docker-loadgen-1",
        ip_address="172.20.0.20",
        server_infra_type="docker",
        server_infra_ref={
            "container_id": "loadgen1_container_id",
            "container_name": "docker-loadgen-1",
            "network": "perf-test-network",
        },
        baseline_id=ubuntu2204_baseline.id,
        hardware_profile_id=loadgen_hw_profile.id,
        os_family="ubuntu",
        deployment_type="docker_exec",
        emulator_port=8080,
        loadgen_service_port=8090,
        is_active=True,
        lab_id=lab.id,
    )
    session.add(loadgen1)

    loadgen2 = ServerORM(
        hostname="docker-loadgen-2",
        ip_address="172.20.0.21",
        server_infra_type="docker",
        server_infra_ref={
            "container_id": "loadgen2_container_id",
            "container_name": "docker-loadgen-2",
            "network": "perf-test-network",
        },
        baseline_id=ubuntu2204_baseline.id,
        hardware_profile_id=loadgen_hw_profile.id,
        os_family="ubuntu",
        deployment_type="docker_exec",
        emulator_port=8080,
        loadgen_service_port=8090,
        is_active=True,
        lab_id=lab.id,
    )
    session.add(loadgen2)
    await session.flush()

    # =========================================================================
    # 5. PACKAGES
    # =========================================================================

    # JMeter package (for Ubuntu load generators)
    jmeter_pkg = PackageORM(
        name="apache-jmeter",
        version="5.5",
        description="Apache JMeter load testing tool",
        package_type="jmeter",
        run_at_load=False,
        requires_restart=False,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "apt-get install -y openjdk-11-jre && wget https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.5.tgz",
            "verify_command": "/opt/jmeter/bin/jmeter --version",
        },
        execution_result_path="/var/log/jmeter/results",
        test_results_path="/var/log/jmeter/jtl",
        stats_collect_path="/var/log/jmeter/stats",
        is_active=True,
    )
    session.add(jmeter_pkg)

    # Emulator package for RHEL
    emulator_rhel_pkg = PackageORM(
        name="cpu-emulator-rhel",
        version="1.0.0",
        description="CPU emulator for RHEL targets",
        package_type="emulator",
        run_at_load=True,
        requires_restart=False,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "/opt/emulator/install.sh",
            "verify_command": "/opt/emulator/emulator --version",
        },
        execution_result_path="/var/log/emulator/results.json",
        stats_collect_path="/var/log/emulator/stats",
        is_active=True,
    )
    session.add(emulator_rhel_pkg)

    # Emulator package for Ubuntu (for future use)
    emulator_ubuntu_pkg = PackageORM(
        name="cpu-emulator-ubuntu",
        version="1.0.0",
        description="CPU emulator for Ubuntu targets",
        package_type="emulator",
        run_at_load=True,
        requires_restart=False,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "/opt/emulator/install.sh",
            "verify_command": "/opt/emulator/emulator --version",
        },
        execution_result_path="/var/log/emulator/results.json",
        stats_collect_path="/var/log/emulator/stats",
        is_active=True,
    )
    session.add(emulator_ubuntu_pkg)

    # Agent v1 package for RHEL (initial install)
    agent_v1_rhel_pkg = PackageORM(
        name="security-agent-rhel",
        version="1.0.0",
        description="Security agent v1.0 for RHEL",
        package_type="agent",
        run_at_load=False,
        requires_restart=True,
        restart_timeout_sec=120,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "rpm -i /tmp/security-agent-1.0.0.rpm",
            "verify_command": "systemctl status security-agent",
        },
        version_check_command="rpm -q security-agent",
        expected_version_regex=r"security-agent-1\.0\.0.*",
        is_active=True,
    )
    session.add(agent_v1_rhel_pkg)

    # Agent v2 package for RHEL (upgrade)
    agent_v2_rhel_pkg = PackageORM(
        name="security-agent-rhel",
        version="2.0.0",
        description="Security agent v2.0 for RHEL (upgrade)",
        package_type="agent",
        run_at_load=False,
        requires_restart=True,
        restart_timeout_sec=120,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "rpm -U /tmp/security-agent-2.0.0.rpm",
            "verify_command": "systemctl status security-agent",
        },
        version_check_command="rpm -q security-agent",
        expected_version_regex=r"security-agent-2\.0\.0.*",
        is_active=True,
    )
    session.add(agent_v2_rhel_pkg)

    # Functional test package
    functional_test_pkg = PackageORM(
        name="functional-tests",
        version="1.0.0",
        description="Functional tests for agent validation",
        package_type="functional",
        run_at_load=False,
        requires_restart=False,
        delivery_config={
            "type": "SCRIPT",
            "install_command": "/opt/tests/install.sh",
            "verify_command": "/opt/tests/run_tests.sh --check",
        },
        test_results_path="/var/log/functional-tests/results.xml",
        is_active=True,
    )
    session.add(functional_test_pkg)
    await session.flush()

    # =========================================================================
    # 6. PACKAGE GROUPS
    # =========================================================================

    # JMeter package group (for Lab.jmeter_package_grpid)
    jmeter_pkg_group = PackageGroupORM(
        name="JMeter Load Generator",
        description="JMeter packages for load generators",
        group_type="jmeter",
        req_kernel_version=False,
        is_active=True,
    )
    session.add(jmeter_pkg_group)

    # Emulator package group (for Scenario.load_generator_package_grp_id)
    emulator_pkg_group = PackageGroupORM(
        name="CPU Emulator",
        description="CPU emulator packages for targets",
        group_type="emulator",
        req_kernel_version=False,
        is_active=True,
    )
    session.add(emulator_pkg_group)

    # Agent initial package group (for ScenarioCase.initial_package_grp_id)
    agent_initial_pkg_group = PackageGroupORM(
        name="Security Agent v1.0",
        description="Security agent initial install packages",
        group_type="agent",
        req_kernel_version=False,
        is_active=True,
    )
    session.add(agent_initial_pkg_group)

    # Agent upgrade package group (for ScenarioCase.upgrade_package_grp_id)
    agent_upgrade_pkg_group = PackageGroupORM(
        name="Security Agent v2.0",
        description="Security agent upgrade packages",
        group_type="agent",
        req_kernel_version=False,
        is_active=True,
    )
    session.add(agent_upgrade_pkg_group)

    # Functional test package group (for ScenarioCase.other_package_grp_ids)
    functional_pkg_group = PackageGroupORM(
        name="Functional Tests",
        description="Functional test packages",
        group_type="functional",
        req_kernel_version=False,
        is_active=True,
    )
    session.add(functional_pkg_group)
    await session.flush()

    # Update lab with JMeter package group
    lab.jmeter_package_grpid = jmeter_pkg_group.id
    await session.flush()

    # =========================================================================
    # 7. PACKAGE GROUP MEMBERS (OS matching)
    # =========================================================================

    # JMeter -> Ubuntu (load generators)
    jmeter_member = PackageGroupMemberORM(
        package_group_id=jmeter_pkg_group.id,
        package_id=jmeter_pkg.id,
        os_match_regex=r"ubuntu/22/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(jmeter_member)

    # Emulator -> RHEL (targets)
    emulator_rhel_member = PackageGroupMemberORM(
        package_group_id=emulator_pkg_group.id,
        package_id=emulator_rhel_pkg.id,
        os_match_regex=r"rhel/8/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(emulator_rhel_member)

    # Emulator -> Ubuntu (fallback)
    emulator_ubuntu_member = PackageGroupMemberORM(
        package_group_id=emulator_pkg_group.id,
        package_id=emulator_ubuntu_pkg.id,
        os_match_regex=r"ubuntu/22/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(emulator_ubuntu_member)

    # Agent v1 -> RHEL (initial)
    agent_v1_member = PackageGroupMemberORM(
        package_group_id=agent_initial_pkg_group.id,
        package_id=agent_v1_rhel_pkg.id,
        os_match_regex=r"rhel/8/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(agent_v1_member)

    # Agent v2 -> RHEL (upgrade)
    agent_v2_member = PackageGroupMemberORM(
        package_group_id=agent_upgrade_pkg_group.id,
        package_id=agent_v2_rhel_pkg.id,
        os_match_regex=r"rhel/8/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(agent_v2_member)

    # Functional tests -> RHEL
    functional_member = PackageGroupMemberORM(
        package_group_id=functional_pkg_group.id,
        package_id=functional_test_pkg.id,
        os_match_regex=r"rhel/8/.*",
        con_type="docker_exec",
        priority=0,
    )
    session.add(functional_member)
    await session.flush()

    # =========================================================================
    # 8. AGENT
    # =========================================================================
    agent = AgentORM(
        name="Security Agent",
        description="Enterprise security agent for testing",
        functional_package_grp_id=functional_pkg_group.id,
        is_active=True,
    )
    session.add(agent)
    await session.flush()

    # Update agent package groups with agent_id
    agent_initial_pkg_group.agent_id = agent.id
    agent_upgrade_pkg_group.agent_id = agent.id
    await session.flush()

    # =========================================================================
    # 9. SCENARIO
    # =========================================================================
    scenario = ScenarioORM(
        name="Docker Performance Test Scenario",
        description="Test scenario with 2 Docker targets and 2 load generators",
        lab_id=lab.id,
        target_server_ids=[target1.id, target2.id],
        loadgen_server_ids=[loadgen1.id, loadgen2.id],
        load_generator_package_grp_id=emulator_pkg_group.id,
        has_base_phase=True,
        has_initial_phase=True,
        has_upgrade_phase=True,
        has_dbtest=False,
        execution_order=1,
        is_calibrated=False,
        is_active=True,
    )
    session.add(scenario)
    await session.flush()

    # =========================================================================
    # 10. SCENARIO CASE (per-agent config)
    # =========================================================================
    scenario_case = ScenarioCaseORM(
        scenario_id=scenario.id,
        agent_id=agent.id,
        initial_package_grp_id=agent_initial_pkg_group.id,
        upgrade_package_grp_id=agent_upgrade_pkg_group.id,
        other_package_grp_ids=[functional_pkg_group.id],
    )
    session.add(scenario_case)
    await session.flush()

    # =========================================================================
    # 11. TEST RUN
    # =========================================================================
    test_run = TestRunORM(
        name="Docker Performance Test Run",
        description="Performance test with Docker targets",
        lab_id=lab.id,
        req_loadprofile=["low", "medium", "high"],
        warmup_sec=60,
        measured_sec=300,
        analysis_trim_sec=30,
        repetitions=1,
        loadgenerator_package_grpid_lst=[emulator_pkg_group.id],
    )
    session.add(test_run)
    await session.flush()

    # Update scenario with test_run_id
    scenario.test_run_id = test_run.id
    await session.flush()

    # =========================================================================
    # 12. TEST RUN TARGETS (2 targets with their loadgens)
    # =========================================================================
    test_run_target1 = TestRunTargetORM(
        test_run_id=test_run.id,
        scenario_id=scenario.id,
        target_id=target1.id,
        loadgenerator_id=loadgen1.id,
        os_family="redhat",
        jmeter_port=1099,
        base_snapshot_id=rhel84_baseline.id,
        initial_snapshot_id=rhel84_baseline.id,  # Same baseline, delta deployment
        upgrade_snapshot_id=rhel84_baseline.id,  # Same baseline, delta deployment
    )
    session.add(test_run_target1)

    test_run_target2 = TestRunTargetORM(
        test_run_id=test_run.id,
        scenario_id=scenario.id,
        target_id=target2.id,
        loadgenerator_id=loadgen2.id,
        os_family="redhat",
        jmeter_port=1099,
        base_snapshot_id=rhel84_baseline.id,
        initial_snapshot_id=rhel84_baseline.id,  # Same baseline, delta deployment
        upgrade_snapshot_id=rhel84_baseline.id,  # Same baseline, delta deployment
    )
    session.add(test_run_target2)
    await session.flush()

    await session.commit()

    return DockerTestData(
        lab=lab,
        target_hw_profile=target_hw_profile,
        loadgen_hw_profile=loadgen_hw_profile,
        rhel84_baseline=rhel84_baseline,
        ubuntu2204_baseline=ubuntu2204_baseline,
        target1=target1,
        target2=target2,
        loadgen1=loadgen1,
        loadgen2=loadgen2,
        jmeter_pkg_group=jmeter_pkg_group,
        emulator_pkg_group=emulator_pkg_group,
        agent_initial_pkg_group=agent_initial_pkg_group,
        agent_upgrade_pkg_group=agent_upgrade_pkg_group,
        functional_pkg_group=functional_pkg_group,
        jmeter_pkg=jmeter_pkg,
        emulator_rhel_pkg=emulator_rhel_pkg,
        emulator_ubuntu_pkg=emulator_ubuntu_pkg,
        agent_v1_rhel_pkg=agent_v1_rhel_pkg,
        agent_v2_rhel_pkg=agent_v2_rhel_pkg,
        functional_test_pkg=functional_test_pkg,
        agent=agent,
        scenario=scenario,
        scenario_case=scenario_case,
        test_run=test_run,
        test_run_target1=test_run_target1,
        test_run_target2=test_run_target2,
    )
