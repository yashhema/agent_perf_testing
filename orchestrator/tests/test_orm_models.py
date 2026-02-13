"""Tests for ORM models — CRUD operations, relationships, constraints."""

import pytest
from sqlalchemy.exc import IntegrityError

from orchestrator.models.enums import (
    BaselineType,
    DiskType,
    ExecutionStatus,
    HypervisorType,
    OSFamily,
    RunMode,
    ServerInfraType,
    TemplateType,
    TestRunState,
)
from orchestrator.models.orm import (
    BaselineORM,
    CalibrationResultORM,
    ComparisonResultORM,
    HardwareProfileORM,
    LabORM,
    LoadProfileORM,
    PackageGroupMemberORM,
    PackageGroupORM,
    PhaseExecutionResultORM,
    ScenarioORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
    UserORM,
)


class TestHardwareProfile:
    def test_create(self, session):
        hp = HardwareProfileORM(
            name="hp-test", cpu_count=4, memory_gb=8.0,
            disk_type=DiskType.ssd, disk_size_gb=100.0,
        )
        session.add(hp)
        session.commit()
        assert hp.id is not None
        assert hp.name == "hp-test"

    def test_unique_name(self, session):
        hp1 = HardwareProfileORM(name="hp-dup", cpu_count=2, memory_gb=4.0, disk_type=DiskType.hdd, disk_size_gb=50.0)
        hp2 = HardwareProfileORM(name="hp-dup", cpu_count=4, memory_gb=8.0, disk_type=DiskType.ssd, disk_size_gb=100.0)
        session.add(hp1)
        session.commit()
        session.add(hp2)
        with pytest.raises(IntegrityError):
            session.commit()


class TestLab:
    def test_create(self, session, sample_lab):
        assert sample_lab.id is not None
        assert sample_lab.name == "test-lab"
        assert sample_lab.hypervisor_type == HypervisorType.proxmox

    def test_relationships(self, session, sample_lab, sample_package_group, sample_baseline):
        assert sample_lab.jmeter_package_grpid == sample_package_group.id
        assert sample_lab.loadgen_snapshot_id == sample_baseline.id


class TestServer:
    def test_create(self, session, sample_server):
        assert sample_server.id is not None
        assert sample_server.hostname == "target-01"
        assert sample_server.os_family == OSFamily.linux

    def test_unique_ip(self, session, sample_lab, sample_hw_profile):
        s1 = ServerORM(
            hostname="s1", ip_address="10.0.0.99",
            os_family=OSFamily.linux, lab_id=sample_lab.id,
            hardware_profile_id=sample_hw_profile.id,
            server_infra_type=ServerInfraType.proxmox_vm,
            server_infra_ref={"node": "pve1", "vmid": 200},
        )
        s2 = ServerORM(
            hostname="s2", ip_address="10.0.0.99",
            os_family=OSFamily.windows, lab_id=sample_lab.id,
            hardware_profile_id=sample_hw_profile.id,
            server_infra_type=ServerInfraType.proxmox_vm,
            server_infra_ref={"node": "pve1", "vmid": 201},
        )
        session.add(s1)
        session.commit()
        session.add(s2)
        with pytest.raises(IntegrityError):
            session.commit()


class TestBaseline:
    def test_create(self, session, sample_baseline):
        assert sample_baseline.id is not None
        assert sample_baseline.os_family == OSFamily.linux
        assert sample_baseline.baseline_type == BaselineType.proxmox


class TestPackageGroup:
    def test_create_with_members(self, session, sample_package_group):
        member = PackageGroupMemberORM(
            package_group_id=sample_package_group.id,
            os_match_regex="ubuntu/22/.*",
            path="/packages/jmeter-5.6.tar.gz",
            root_install_path="/opt/jmeter",
        )
        session.add(member)
        session.commit()
        assert member.id is not None
        assert len(sample_package_group.members) == 1


class TestLoadProfile:
    def test_create(self, session, sample_load_profile):
        assert sample_load_profile.id is not None
        assert sample_load_profile.name == "medium"
        assert sample_load_profile.duration_sec == 300


class TestScenario:
    def test_create(self, session, sample_scenario):
        assert sample_scenario.id is not None
        assert sample_scenario.template_type == TemplateType.server_normal
        assert sample_scenario.has_base_phase is True


class TestTestRun:
    def test_create(self, session, sample_test_run):
        assert sample_test_run.id is not None
        assert sample_test_run.state == TestRunState.created
        assert sample_test_run.run_mode == RunMode.complete
        assert sample_test_run.cycles_per_profile == 2

    def test_add_target(self, session, sample_test_run, sample_server, sample_baseline):
        # Need a loadgen server
        from orchestrator.models.orm import LabORM
        lab = session.get(LabORM, sample_test_run.lab_id)
        loadgen = ServerORM(
            hostname="loadgen-01", ip_address="10.0.0.20",
            os_family=OSFamily.linux, lab_id=lab.id,
            hardware_profile_id=sample_server.hardware_profile_id,
            server_infra_type=ServerInfraType.proxmox_vm,
            server_infra_ref={"node": "pve1", "vmid": 200},
        )
        session.add(loadgen)
        session.commit()

        target = TestRunTargetORM(
            test_run_id=sample_test_run.id,
            target_id=sample_server.id,
            loadgenerator_id=loadgen.id,
            base_snapshot_id=sample_baseline.id,
            initial_snapshot_id=sample_baseline.id,
        )
        session.add(target)
        session.commit()
        assert target.id is not None
        assert len(sample_test_run.targets) == 1

    def test_add_load_profile(self, session, sample_test_run, sample_load_profile):
        link = TestRunLoadProfileORM(
            test_run_id=sample_test_run.id,
            load_profile_id=sample_load_profile.id,
        )
        session.add(link)
        session.commit()
        assert link.id is not None
        assert len(sample_test_run.load_profiles) == 1


class TestCalibrationResult:
    def test_create(self, session, sample_test_run, sample_server, sample_load_profile):
        cal = CalibrationResultORM(
            test_run_id=sample_test_run.id,
            server_id=sample_server.id,
            os_type=OSFamily.linux,
            load_profile_id=sample_load_profile.id,
            thread_count=15,
        )
        session.add(cal)
        session.commit()
        assert cal.id is not None
        assert cal.thread_count == 15


class TestPhaseExecutionResult:
    def test_create(self, session, sample_test_run, sample_server, sample_load_profile, sample_baseline):
        per = PhaseExecutionResultORM(
            test_run_id=sample_test_run.id,
            target_id=sample_server.id,
            snapshot_num=1,
            load_profile_id=sample_load_profile.id,
            cycle_number=1,
            baseline_id=sample_baseline.id,
            thread_count=10,
            status=ExecutionStatus.running,
        )
        session.add(per)
        session.commit()
        assert per.id is not None
        assert per.status == ExecutionStatus.running


class TestUser:
    def test_create(self, session):
        user = UserORM(
            username="testadmin",
            password_hash="$2b$12$fakehash",
            email="admin@test.com",
            role="admin",
        )
        session.add(user)
        session.commit()
        assert user.id is not None
        assert user.is_active is True

    def test_unique_username(self, session):
        u1 = UserORM(username="dup-user", password_hash="h1", role="user")
        u2 = UserORM(username="dup-user", password_hash="h2", role="user")
        session.add(u1)
        session.commit()
        session.add(u2)
        with pytest.raises(IntegrityError):
            session.commit()
