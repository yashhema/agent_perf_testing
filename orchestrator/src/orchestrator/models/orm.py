"""SQLAlchemy ORM models for all 15 orchestrator entities.

Matches ORCHESTRATOR_DATABASE_SCHEMA.md exactly.
Uses dialect-agnostic types (JSON instead of JSONB) to support both
PostgreSQL and SQL Server backends.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from orchestrator.models.database import Base
from orchestrator.models.enums import (
    AgentType,
    BaselineTargetState,
    BaselineTestState,
    BaselineTestType,
    BaselineType,
    DBType,
    DiskType,
    ExecutionMode,
    ExecutionStatus,
    FunctionalTestPhase,
    HypervisorType,
    OSFamily,
    RuleSeverity,
    RunMode,
    ServerInfraType,
    TemplateType,
    TestPhaseType,
    TestRunState,
    Verdict,
)


# ---------------------------------------------------------------------------
# 3.1 LabORM
# ---------------------------------------------------------------------------
class LabORM(Base):
    __tablename__ = "labs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    jmeter_package_grpid = Column(Integer, ForeignKey("package_groups.id"), nullable=False)
    emulator_package_grp_id = Column(Integer, ForeignKey("package_groups.id"), nullable=True)
    loadgen_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    hypervisor_type = Column(Enum(HypervisorType), nullable=False)
    hypervisor_manager_url = Column(String(512), nullable=False)
    hypervisor_manager_port = Column(Integer, nullable=False)
    execution_mode = Column(
        Enum(ExecutionMode), nullable=False, default=ExecutionMode.live_compare,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    servers = relationship("ServerORM", back_populates="lab")
    scenarios = relationship("ScenarioORM", back_populates="lab")
    test_runs = relationship("TestRunORM", back_populates="lab")
    jmeter_package_group = relationship("PackageGroupORM", foreign_keys=[jmeter_package_grpid])
    emulator_package_group = relationship("PackageGroupORM", foreign_keys=[emulator_package_grp_id])
    loadgen_snapshot = relationship("BaselineORM", foreign_keys=[loadgen_snapshot_id])


# ---------------------------------------------------------------------------
# 3.2 HardwareProfileORM
# ---------------------------------------------------------------------------
class HardwareProfileORM(Base):
    __tablename__ = "hardware_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    cpu_count = Column(Integer, nullable=False)
    cpu_model = Column(String(255), nullable=True)
    memory_gb = Column(Float, nullable=False)
    disk_type = Column(Enum(DiskType), nullable=False)
    disk_size_gb = Column(Float, nullable=False)
    nic_speed_mbps = Column(Integer, nullable=True)
    vendor = Column(String(255), nullable=True)

    # Relationships
    servers = relationship("ServerORM", back_populates="hardware_profile")


# ---------------------------------------------------------------------------
# 3.3 ServerORM
# ---------------------------------------------------------------------------
class ServerORM(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hostname = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=False, unique=True)
    os_family = Column(Enum(OSFamily), nullable=False)
    os_vendor_family = Column(String(100), nullable=True)   # e.g., "ubuntu", "rhel", "windows"
    os_major_ver = Column(String(20), nullable=True)        # e.g., "22", "9", "2022"
    os_minor_ver = Column(String(20), nullable=True)        # e.g., "04", "3"
    lab_id = Column(Integer, ForeignKey("labs.id"), nullable=False)
    hardware_profile_id = Column(Integer, ForeignKey("hardware_profiles.id"), nullable=False)
    server_infra_type = Column(Enum(ServerInfraType), nullable=False)
    server_infra_ref = Column(JSON, nullable=False)
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True)
    db_type = Column(Enum(DBType), nullable=True)
    db_port = Column(Integer, nullable=True)
    db_name = Column(String(255), nullable=True)
    db_user = Column(String(255), nullable=True)
    db_password = Column(String(255), nullable=True)
    # Baseline-compare defaults (used when no per-test override)
    default_loadgen_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    default_partner_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    service_monitor_patterns = Column(JSON, nullable=True)
    # Clean snapshot for reverting to known-good state (loadgens: pre-JMeter/emulator install)
    clean_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    lab = relationship("LabORM", back_populates="servers")
    hardware_profile = relationship("HardwareProfileORM", back_populates="servers")
    baseline = relationship("BaselineORM", foreign_keys=[baseline_id])
    default_loadgen = relationship("ServerORM", foreign_keys=[default_loadgen_id], remote_side="ServerORM.id")
    default_partner = relationship("ServerORM", foreign_keys=[default_partner_id], remote_side="ServerORM.id")
    clean_snapshot = relationship("SnapshotORM", foreign_keys=[clean_snapshot_id])


# ---------------------------------------------------------------------------
# 3.4 BaselineORM
# ---------------------------------------------------------------------------
class BaselineORM(Base):
    __tablename__ = "baselines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    os_family = Column(Enum(OSFamily), nullable=False)
    os_vendor_family = Column(String(100), nullable=False)
    os_major_ver = Column(String(20), nullable=False)
    os_minor_ver = Column(String(20), nullable=True)
    os_kernel_ver = Column(String(100), nullable=True)
    db_type = Column(Enum(DBType), nullable=True)
    baseline_type = Column(Enum(BaselineType), nullable=False)
    provider_ref = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 3.5 PackageGroupORM
# ---------------------------------------------------------------------------
class PackageGroupORM(Base):
    __tablename__ = "package_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    members = relationship("PackageGroupMemberORM", back_populates="package_group")


# ---------------------------------------------------------------------------
# 3.6 PackageGroupMemberORM
# ---------------------------------------------------------------------------
class PackageGroupMemberORM(Base):
    __tablename__ = "package_group_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_group_id = Column(Integer, ForeignKey("package_groups.id"), nullable=False)
    os_match_regex = Column(String(255), nullable=False)
    path = Column(String(1024), nullable=False)
    root_install_path = Column(String(1024), nullable=False)
    extraction_command = Column(String(1024), nullable=True)
    install_command = Column(String(1024), nullable=True)
    run_command = Column(String(1024), nullable=True)
    output_path = Column(String(1024), nullable=True)
    uninstall_command = Column(String(1024), nullable=True)
    status_command = Column(String(1024), nullable=True)
    prereq_script = Column(String(1024), nullable=True)

    # Relationships
    package_group = relationship("PackageGroupORM", back_populates="members")


# ---------------------------------------------------------------------------
# 3.7 ScenarioORM
# ---------------------------------------------------------------------------
class ScenarioORM(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    lab_id = Column(Integer, ForeignKey("labs.id"), nullable=False)
    template_type = Column(Enum(TemplateType), nullable=False)
    has_base_phase = Column(Boolean, nullable=False, default=True)
    has_initial_phase = Column(Boolean, nullable=False, default=True)
    has_dbtest = Column(Boolean, nullable=False, default=False)
    load_generator_package_grp_id = Column(Integer, ForeignKey("package_groups.id"), nullable=False)
    initial_package_grp_id = Column(Integer, ForeignKey("package_groups.id"), nullable=True)
    other_package_grp_ids = Column(JSON, nullable=True)  # List[int] stored as JSON array
    functional_package_grp_id = Column(Integer, ForeignKey("package_groups.id"), nullable=True)
    functional_test_phase = Column(Enum(FunctionalTestPhase), nullable=True)
    stress_test_enabled = Column(Boolean, nullable=False, default=False)
    stress_test_duration_sec = Column(Integer, nullable=True, default=120)
    stress_test_thread_multiplier = Column(Float, nullable=True, default=4.0)
    network_degradation_enabled = Column(Boolean, nullable=False, default=False)
    network_degradation_pct = Column(Float, nullable=True, default=10.0)
    network_degradation_duration_sec = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    lab = relationship("LabORM", back_populates="scenarios")
    load_generator_package_group = relationship("PackageGroupORM", foreign_keys=[load_generator_package_grp_id])
    initial_package_group = relationship("PackageGroupORM", foreign_keys=[initial_package_grp_id])
    functional_package_group = relationship("PackageGroupORM", foreign_keys=[functional_package_grp_id])
    agents = relationship("AgentORM", secondary="scenario_agents", back_populates="scenarios")


# ---------------------------------------------------------------------------
# 3.8 LoadProfileORM
# ---------------------------------------------------------------------------
class LoadProfileORM(Base):
    __tablename__ = "load_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    target_cpu_range_min = Column(Float, nullable=False)
    target_cpu_range_max = Column(Float, nullable=False)
    duration_sec = Column(Integer, nullable=False)
    ramp_up_sec = Column(Integer, nullable=False)


# ---------------------------------------------------------------------------
# 3.9 TestRunORM
# ---------------------------------------------------------------------------
class TestRunORM(Base):
    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    lab_id = Column(Integer, ForeignKey("labs.id"), nullable=False)
    cycles_per_profile = Column(Integer, nullable=False, default=1)
    run_mode = Column(Enum(RunMode), nullable=False, default=RunMode.complete)
    state = Column(Enum(TestRunState), nullable=False, default=TestRunState.created)
    current_snapshot_num = Column(Integer, nullable=True)
    current_load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=True)
    current_cycle_number = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    overall_verdict = Column(Enum(Verdict), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    scenario = relationship("ScenarioORM")
    lab = relationship("LabORM", back_populates="test_runs")
    current_load_profile = relationship("LoadProfileORM", foreign_keys=[current_load_profile_id])
    targets = relationship("TestRunTargetORM", back_populates="test_run")
    load_profiles = relationship("TestRunLoadProfileORM", back_populates="test_run")
    calibration_results = relationship("CalibrationResultORM", back_populates="test_run")
    phase_results = relationship("PhaseExecutionResultORM", back_populates="test_run")
    comparison_results = relationship("ComparisonResultORM", back_populates="test_run")


# ---------------------------------------------------------------------------
# 3.10 TestRunTargetORM
# ---------------------------------------------------------------------------
class TestRunTargetORM(Base):
    __tablename__ = "test_run_targets"
    __table_args__ = (
        UniqueConstraint("test_run_id", "target_id", name="uq_test_run_target"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    loadgenerator_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    partner_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    base_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    initial_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    db_ready_base_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=True)
    db_ready_initial_snapshot_id = Column(Integer, ForeignKey("baselines.id"), nullable=True)
    service_monitor_patterns = Column(JSON, nullable=True)
    output_folders = Column(String(2000), nullable=True)  # comma-separated folder paths for emulator file output

    # Discovered OS kind (shared — derived from the machine's distro family)
    os_kind = Column(String(100), nullable=True)

    # Base snapshot environment (discovered after base snapshot restore)
    base_os_major_ver = Column(String(20), nullable=True)
    base_os_minor_ver = Column(String(20), nullable=True)
    base_agent_versions = Column(JSON, nullable=True)

    # Initial snapshot environment (discovered after initial snapshot restore)
    initial_os_major_ver = Column(String(20), nullable=True)
    initial_os_minor_ver = Column(String(20), nullable=True)
    initial_agent_versions = Column(JSON, nullable=True)

    # Relationships
    test_run = relationship("TestRunORM", back_populates="targets")
    target = relationship("ServerORM", foreign_keys=[target_id])
    loadgenerator = relationship("ServerORM", foreign_keys=[loadgenerator_id])
    partner = relationship("ServerORM", foreign_keys=[partner_id])
    base_snapshot = relationship("BaselineORM", foreign_keys=[base_snapshot_id])
    initial_snapshot = relationship("BaselineORM", foreign_keys=[initial_snapshot_id])
    db_ready_base_snapshot = relationship("BaselineORM", foreign_keys=[db_ready_base_snapshot_id])
    db_ready_initial_snapshot = relationship("BaselineORM", foreign_keys=[db_ready_initial_snapshot_id])


# ---------------------------------------------------------------------------
# 3.11 TestRunLoadProfileORM
# ---------------------------------------------------------------------------
class TestRunLoadProfileORM(Base):
    __tablename__ = "test_run_load_profiles"
    __table_args__ = (
        UniqueConstraint("test_run_id", "load_profile_id", name="uq_test_run_load_profile"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=False)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)

    # Relationships
    test_run = relationship("TestRunORM", back_populates="load_profiles")
    load_profile = relationship("LoadProfileORM")


# ---------------------------------------------------------------------------
# 3.12 CalibrationResultORM
# ---------------------------------------------------------------------------
class CalibrationResultORM(Base):
    __tablename__ = "calibration_results"
    __table_args__ = (
        UniqueConstraint("test_run_id", "server_id", "load_profile_id", name="uq_calibration"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=True)
    baseline_test_run_id = Column(Integer, ForeignKey("baseline_test_runs.id"), nullable=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    os_type = Column(Enum(OSFamily), nullable=False)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)

    # Final result
    thread_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="in_progress")  # in_progress | completed | failed

    # Live progress fields (updated during calibration)
    phase = Column(String(30), nullable=True)  # binary_search | stability_check
    current_iteration = Column(Integer, nullable=True)
    current_thread_count = Column(Integer, nullable=True)
    last_observed_cpu = Column(Float, nullable=True)
    target_cpu_min = Column(Float, nullable=True)
    target_cpu_max = Column(Float, nullable=True)
    stability_check_num = Column(Integer, nullable=True)
    stability_checks_total = Column(Integer, nullable=True)
    stability_pct_in_range = Column(Float, nullable=True)
    stability_attempt = Column(Integer, nullable=True)  # which decrement attempt
    message = Column(String(500), nullable=True)  # human-readable progress message

    # Error details (for failed calibrations)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    test_run = relationship("TestRunORM", back_populates="calibration_results",
                            foreign_keys=[test_run_id])
    baseline_test_run = relationship("BaselineTestRunORM",
                                     foreign_keys=[baseline_test_run_id])
    server = relationship("ServerORM")
    load_profile = relationship("LoadProfileORM")


# ---------------------------------------------------------------------------
# 3.13 PhaseExecutionResultORM
# ---------------------------------------------------------------------------
class PhaseExecutionResultORM(Base):
    __tablename__ = "phase_execution_results"
    __table_args__ = (
        UniqueConstraint(
            "test_run_id", "target_id", "snapshot_num",
            "load_profile_id", "cycle_number", "test_phase_type",
            name="uq_phase_execution",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    snapshot_num = Column(Integer, nullable=False)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)
    cycle_number = Column(Integer, nullable=False)
    test_phase_type = Column(Enum(TestPhaseType), nullable=False, default=TestPhaseType.load)
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    thread_count = Column(Integer, nullable=False)
    status = Column(Enum(ExecutionStatus), nullable=False, default=ExecutionStatus.pending)
    network_degradation_pct = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    stats_file_path = Column(String(1024), nullable=True)
    jmeter_jtl_path = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    test_run = relationship("TestRunORM", back_populates="phase_results")
    target = relationship("ServerORM")
    load_profile = relationship("LoadProfileORM")
    baseline = relationship("BaselineORM")


# ---------------------------------------------------------------------------
# 3.14 ComparisonResultORM
# ---------------------------------------------------------------------------
class ComparisonResultORM(Base):
    __tablename__ = "comparison_results"
    __table_args__ = (
        UniqueConstraint(
            "baseline_test_run_id", "target_id", "load_profile_id", "cycle",
            name="uq_baseline_comparison_cycle",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=True)
    baseline_test_run_id = Column(Integer, ForeignKey("baseline_test_runs.id"), nullable=True)
    target_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)
    cycle = Column(Integer, nullable=False, default=1)
    comparison_type = Column(String(50), nullable=False)
    result_file_path = Column(String(1024), nullable=True)
    result_data = Column(JSON, nullable=True)
    summary_text = Column(Text, nullable=True)
    verdict = Column(Enum(Verdict), nullable=True)
    violation_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    test_run = relationship("TestRunORM", back_populates="comparison_results")
    baseline_test_run = relationship("BaselineTestRunORM", back_populates="comparison_results")
    target = relationship("ServerORM")
    load_profile = relationship("LoadProfileORM")


# ---------------------------------------------------------------------------
# 3.15 DBSchemaConfigORM
# ---------------------------------------------------------------------------
class DBSchemaConfigORM(Base):
    __tablename__ = "db_schema_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    db_type = Column(Enum(DBType), nullable=False, unique=True)
    schema_path = Column(String(1024), nullable=False)
    seed_data_path = Column(String(1024), nullable=False)
    param_csv_path = Column(String(1024), nullable=True)


# ---------------------------------------------------------------------------
# UserORM (Authentication — Phase 1.3)
# ---------------------------------------------------------------------------
class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="user")  # "admin" or "user"
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# AgentORM (Analysis & Rules)
# ---------------------------------------------------------------------------
class AgentORM(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    vendor = Column(String(255), nullable=True)
    agent_type = Column(Enum(AgentType), nullable=False, default=AgentType.edr)
    version = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    package_group_id = Column(Integer, ForeignKey("package_groups.id"), nullable=True)
    process_patterns = Column(JSON, nullable=True)
    service_patterns = Column(JSON, nullable=True)
    discovery_key = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    package_group = relationship("PackageGroupORM", foreign_keys=[package_group_id])
    analysis_rules = relationship("AnalysisRuleORM", back_populates="agent", cascade="all, delete-orphan")
    scenarios = relationship("ScenarioORM", secondary="scenario_agents", back_populates="agents")


# ---------------------------------------------------------------------------
# ScenarioAgentORM (M2M join table)
# ---------------------------------------------------------------------------
class ScenarioAgentORM(Base):
    __tablename__ = "scenario_agents"
    __table_args__ = (
        UniqueConstraint("scenario_id", "agent_id", name="uq_scenario_agent"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)


# ---------------------------------------------------------------------------
# AnalysisRuleORM
# ---------------------------------------------------------------------------
class AnalysisRuleORM(Base):
    __tablename__ = "analysis_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    rule_template_key = Column(String(100), nullable=False)
    threshold_value = Column(Float, nullable=False)
    threshold_upper = Column(Float, nullable=True)
    severity = Column(Enum(RuleSeverity), nullable=False, default=RuleSeverity.warning)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    agent = relationship("AgentORM", back_populates="analysis_rules")


# ===========================================================================
# Baseline-Compare Mode Tables
# ===========================================================================

# ---------------------------------------------------------------------------
# SnapshotBaselineORM — First-level "Group": clean OS state per target VM
# UI label: "Group"
# ---------------------------------------------------------------------------
class SnapshotBaselineORM(Base):
    __tablename__ = "snapshot_baselines"
    __table_args__ = (
        UniqueConstraint("server_id", "snapshot_id", name="uq_sb_server_snapshot"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    server = relationship("ServerORM", backref="snapshot_baselines")
    snapshot = relationship("SnapshotORM", foreign_keys=[snapshot_id])
    groups = relationship("SnapshotGroupORM", back_populates="baseline", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# SnapshotGroupORM — Second-level "Subgroup": agent/team under a group
# UI label: "Subgroup"
# ---------------------------------------------------------------------------
class SnapshotGroupORM(Base):
    __tablename__ = "snapshot_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    baseline_id = Column(Integer, ForeignKey("snapshot_baselines.id"), nullable=False)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    baseline = relationship("SnapshotBaselineORM", back_populates="groups")
    snapshot = relationship("SnapshotORM", foreign_keys=[snapshot_id])
    snapshots = relationship("SnapshotORM", back_populates="group", foreign_keys="SnapshotORM.group_id")


# ---------------------------------------------------------------------------
# SnapshotORM — Hierarchical snapshot tree tied to a server
# ---------------------------------------------------------------------------
class SnapshotORM(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("server_id", "provider_snapshot_id", name="uq_snapshot_server_provider_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("snapshots.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("snapshot_groups.id"), nullable=True)
    provider_snapshot_id = Column(String(100), nullable=False)
    provider_ref = Column(JSON, nullable=False)
    snapshot_tree = Column(JSON, nullable=True)
    is_baseline = Column(Boolean, nullable=False, default=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    server = relationship("ServerORM", foreign_keys=[server_id], backref="snapshots")
    parent = relationship("SnapshotORM", remote_side=[id], backref="children")
    group = relationship("SnapshotGroupORM", foreign_keys=[group_id], back_populates="snapshots")
    profile_data = relationship(
        "SnapshotProfileDataORM",
        back_populates="snapshot",
        foreign_keys="SnapshotProfileDataORM.snapshot_id",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# SnapshotProfileDataORM — Per-snapshot, per-load-profile stored data
# ---------------------------------------------------------------------------
class SnapshotProfileDataORM(Base):
    __tablename__ = "snapshot_profile_data"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "load_profile_id", "cycle", name="uq_snapshot_profile_cycle"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)
    cycle = Column(Integer, nullable=False, default=1)
    thread_count = Column(Integer, nullable=False)
    jmx_test_case_data = Column(String(500), nullable=True)
    stats_data = Column(String(500), nullable=True)
    stats_summary = Column(JSON, nullable=True)
    jtl_data = Column(String(500), nullable=True)
    source_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    snapshot = relationship(
        "SnapshotORM", foreign_keys=[snapshot_id], back_populates="profile_data",
    )
    load_profile = relationship("LoadProfileORM")
    source_snapshot = relationship("SnapshotORM", foreign_keys=[source_snapshot_id])


# ---------------------------------------------------------------------------
# BaselineTestRunORM — A test run in baseline-compare mode
# ---------------------------------------------------------------------------
class BaselineTestRunORM(Base):
    __tablename__ = "baseline_test_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    lab_id = Column(Integer, ForeignKey("labs.id"), nullable=False)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    test_type = Column(Enum(BaselineTestType), nullable=False)
    parent_run_id = Column(Integer, ForeignKey("baseline_test_runs.id"), nullable=True)
    state = Column(
        Enum(BaselineTestState), nullable=False, default=BaselineTestState.created,
    )
    current_load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=True)
    current_cycle = Column(Integer, nullable=False, default=1)
    cycle_count = Column(Integer, nullable=False, default=1)
    failed_at_state = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    verdict = Column(Enum(Verdict), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    lab = relationship("LabORM")
    scenario = relationship("ScenarioORM")
    parent_run = relationship("BaselineTestRunORM", remote_side=[id], backref="child_runs")
    current_load_profile = relationship("LoadProfileORM", foreign_keys=[current_load_profile_id])
    comparison_results = relationship("ComparisonResultORM", back_populates="baseline_test_run")
    load_profiles = relationship(
        "BaselineTestRunLoadProfileORM", back_populates="baseline_test_run",
        cascade="all, delete-orphan",
    )
    targets = relationship(
        "BaselineTestRunTargetORM", back_populates="baseline_test_run",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# BaselineTestRunTargetORM — Per-target config for baseline test runs
# ---------------------------------------------------------------------------
class BaselineTestRunTargetORM(Base):
    __tablename__ = "baseline_test_run_targets"
    __table_args__ = (
        UniqueConstraint("baseline_test_run_id", "target_id", name="uq_baseline_run_target"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    baseline_test_run_id = Column(Integer, ForeignKey("baseline_test_runs.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    loadgenerator_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    partner_id = Column(Integer, ForeignKey("servers.id"), nullable=True)
    test_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)
    compare_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=True)
    service_monitor_patterns = Column(JSON, nullable=True)
    output_folders = Column(String(2000), nullable=True)  # comma-separated folder paths for emulator file output

    # Per-target state tracking
    state = Column(
        Enum(BaselineTargetState), nullable=False, default=BaselineTargetState.pending,
    )
    error_message = Column(Text, nullable=True)
    current_load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=True)

    # Discovery results (written during deploying_calibration, first LP)
    os_kind = Column(String(100), nullable=True)
    os_major_ver = Column(String(20), nullable=True)
    os_minor_ver = Column(String(20), nullable=True)
    agent_versions = Column(JSON, nullable=True)

    # Relationships
    baseline_test_run = relationship("BaselineTestRunORM", back_populates="targets")
    target = relationship("ServerORM", foreign_keys=[target_id])
    loadgenerator = relationship("ServerORM", foreign_keys=[loadgenerator_id])
    partner = relationship("ServerORM", foreign_keys=[partner_id])
    test_snapshot = relationship("SnapshotORM", foreign_keys=[test_snapshot_id])
    compare_snapshot = relationship("SnapshotORM", foreign_keys=[compare_snapshot_id])
    current_load_profile = relationship("LoadProfileORM", foreign_keys=[current_load_profile_id])


# ---------------------------------------------------------------------------
# BaselineTestRunLoadProfileORM — M2M: baseline test run <-> load profiles
# ---------------------------------------------------------------------------
class BaselineTestRunLoadProfileORM(Base):
    __tablename__ = "baseline_test_run_load_profiles"
    __table_args__ = (
        UniqueConstraint(
            "baseline_test_run_id", "load_profile_id",
            name="uq_baseline_test_run_lp",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    baseline_test_run_id = Column(Integer, ForeignKey("baseline_test_runs.id"), nullable=False)
    load_profile_id = Column(Integer, ForeignKey("load_profiles.id"), nullable=False)
    duration_sec = Column(Integer, nullable=True)   # NULL = use LP default
    ramp_up_sec = Column(Integer, nullable=True)    # NULL = use LP default

    # Relationships
    baseline_test_run = relationship("BaselineTestRunORM", back_populates="load_profiles")
    load_profile = relationship("LoadProfileORM")
