"""Shared pytest fixtures for orchestrator tests.

Uses SQLite in-memory database for fast, isolated tests.
Patches PostgreSQL-specific types (JSONB, ARRAY) to SQLite-compatible equivalents.
"""

import pytest
from sqlalchemy import JSON, String, Text, create_engine, event
from sqlalchemy.orm import sessionmaker

from orchestrator.models.database import Base
from orchestrator.models.orm import (
    BaselineORM,
    CalibrationResultORM,
    ComparisonResultORM,
    DBSchemaConfigORM,
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
from orchestrator.models.enums import (
    BaselineType,
    DBType,
    DiskType,
    ExecutionStatus,
    HypervisorType,
    OSFamily,
    RunMode,
    ServerInfraType,
    TemplateType,
    TestRunState,
)


def _patch_pg_types_for_sqlite():
    """Replace PostgreSQL-specific column types with SQLite-compatible ones.

    This patches JSONB -> JSON and ARRAY(Integer) -> Text in the ORM model
    columns so that SQLite can create the tables.
    """
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif isinstance(column.type, ARRAY):
                column.type = Text()


# Patch once at import time
_patch_pg_types_for_sqlite()


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine."""
    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Create a new database session for a test."""
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def sample_hw_profile(session):
    """Create and return a sample hardware profile."""
    hp = HardwareProfileORM(
        name="test-hw-4c8g",
        cpu_count=4,
        cpu_model="Intel Xeon",
        memory_gb=8.0,
        disk_type=DiskType.ssd,
        disk_size_gb=100.0,
        nic_speed_mbps=1000,
    )
    session.add(hp)
    session.commit()
    return hp


@pytest.fixture
def sample_package_group(session):
    """Create and return a sample package group."""
    pg = PackageGroupORM(name="jmeter-pkg", description="JMeter")
    session.add(pg)
    session.commit()
    return pg


@pytest.fixture
def sample_baseline(session):
    """Create and return a sample baseline."""
    bl = BaselineORM(
        name="ubuntu-22-base",
        os_family=OSFamily.linux,
        os_vendor_family="ubuntu",
        os_major_ver="22",
        os_minor_ver="04",
        baseline_type=BaselineType.proxmox,
        provider_ref={"snapshot_name": "base-snap-001"},
    )
    session.add(bl)
    session.commit()
    return bl


@pytest.fixture
def sample_lab(session, sample_package_group, sample_baseline):
    """Create and return a sample lab."""
    lab = LabORM(
        name="test-lab",
        jmeter_package_grpid=sample_package_group.id,
        loadgen_snapshot_id=sample_baseline.id,
        hypervisor_type=HypervisorType.proxmox,
        hypervisor_manager_url="https://pve.test.local",
        hypervisor_manager_port=8006,
    )
    session.add(lab)
    session.commit()
    return lab


@pytest.fixture
def sample_server(session, sample_lab, sample_hw_profile):
    """Create and return a sample server."""
    srv = ServerORM(
        hostname="target-01",
        ip_address="10.0.0.10",
        os_family=OSFamily.linux,
        lab_id=sample_lab.id,
        hardware_profile_id=sample_hw_profile.id,
        server_infra_type=ServerInfraType.proxmox_vm,
        server_infra_ref={"node": "pve1", "vmid": 100},
    )
    session.add(srv)
    session.commit()
    return srv


@pytest.fixture
def sample_load_profile(session):
    """Create and return a sample load profile."""
    lp = LoadProfileORM(
        name="medium",
        target_cpu_range_min=40.0,
        target_cpu_range_max=60.0,
        duration_sec=300,
        ramp_up_sec=30,
    )
    session.add(lp)
    session.commit()
    return lp


@pytest.fixture
def sample_scenario(session, sample_lab, sample_package_group):
    """Create and return a sample scenario."""
    sc = ScenarioORM(
        name="server-normal-test",
        lab_id=sample_lab.id,
        template_type=TemplateType.server_normal,
        has_base_phase=True,
        has_initial_phase=True,
        has_dbtest=False,
        load_generator_package_grp_id=sample_package_group.id,
    )
    session.add(sc)
    session.commit()
    return sc


@pytest.fixture
def sample_test_run(session, sample_scenario, sample_lab):
    """Create and return a sample test run."""
    tr = TestRunORM(
        scenario_id=sample_scenario.id,
        lab_id=sample_lab.id,
        cycles_per_profile=2,
        run_mode=RunMode.complete,
        state=TestRunState.created,
    )
    session.add(tr)
    session.commit()
    return tr
