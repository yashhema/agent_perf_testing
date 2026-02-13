"""SQLAlchemy ORM models.

These models map directly to database tables.
They are separate from Application models to maintain clean architecture.

STRICT RULES:
- NO dictionaries for storing fields
- All relationships must be explicitly typed
- Use proper SQLAlchemy types
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.db_types import JsonType, ArrayOfStrings, ArrayOfIntegers, GuidType


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class LabORM(Base):
    """ORM model for labs table."""

    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lab_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # JMeter package group - installed on load generator machines in this lab
    jmeter_package_grpid: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=True
    )

    # Secret management configuration
    secret_management: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Lab capabilities - what infrastructure/systems are available
    # e.g., ["vsphere", "intune", "jamf", "ssm", "tanium", "mfoo"]
    # Used as lookup keys in credentials JSON
    capabilities: Mapped[Optional[list[str]]] = mapped_column(
        ArrayOfStrings(), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    servers: Mapped[list["ServerORM"]] = relationship(
        "ServerORM", back_populates="lab", lazy="selectin"
    )
    baselines: Mapped[list["BaselineORM"]] = relationship(
        "BaselineORM", back_populates="lab", lazy="selectin"
    )
    test_runs: Mapped[list["TestRunORM"]] = relationship(
        "TestRunORM", back_populates="lab", lazy="selectin"
    )
    scenarios: Mapped[list["ScenarioORM"]] = relationship(
        "ScenarioORM", back_populates="lab", lazy="selectin"
    )
    environments: Mapped[list["EnvironmentORM"]] = relationship(
        "EnvironmentORM", back_populates="lab", lazy="selectin"
    )


class ServerORM(Base):
    """ORM model for servers table.

    Each server has a baseline_id (image to create from if non-existent).
    server_infra_type must be compatible with baseline_type:
      - docker → docker
      - vsphere_vm → vsphere
      - ec2 → aws
    """

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)

    # Infrastructure type - how server is hosted (ServerInfraType enum)
    # Values: docker, ec2, vsphere_vm, azure_vm, gcp_vm, physical
    server_infra_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Infrastructure-specific reference (JSON)
    # docker: {"container_id": "abc123", "container_name": "emulator-1", "network": "e2e-network"}
    # ec2: {"instance_id": "i-1234567890", "region": "us-east-1"}
    # vsphere_vm: {"vm_moid": "vm-456", "vcenter": "vcenter.example.com"}
    server_infra_ref: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    # Baseline image - used to CREATE server if non-existent
    # Must be compatible with server_infra_type
    baseline_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )

    # Hardware profile - specs for server creation
    hardware_profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("hardware_profiles.id"), nullable=True
    )

    # OS family for SSH/WinRM credential lookup (fallback if baseline not available)
    os_family: Mapped[str] = mapped_column(String(50), nullable=False)

    # Deployment type - how to deploy packages (DeploymentType enum)
    # Values: ssh, winrm, docker_exec, ssm, intune, jamf
    # Cascade: PackageGroupMember.con_type → Baseline.deployment_type → Server.deployment_type
    deployment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # DB type for database connection string lookup (DatabaseType enum)
    # Values: postgres, mysql, oracle, mssql
    # Only set if this server is a database server
    db_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Service ports
    emulator_port: Mapped[int] = mapped_column(Integer, default=8080, nullable=False)
    loadgen_service_port: Mapped[int] = mapped_column(
        Integer, default=8090, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lab_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labs.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lab: Mapped["LabORM"] = relationship("LabORM", back_populates="servers")
    baseline: Mapped[Optional["BaselineORM"]] = relationship(
        "BaselineORM", back_populates="servers"
    )
    hardware_profile: Mapped[Optional["HardwareProfileORM"]] = relationship(
        "HardwareProfileORM", back_populates="servers"
    )
    targets_as_target: Mapped[list["TestRunTargetORM"]] = relationship(
        "TestRunTargetORM",
        foreign_keys="TestRunTargetORM.target_id",
        back_populates="target",
    )
    targets_as_loadgen: Mapped[list["TestRunTargetORM"]] = relationship(
        "TestRunTargetORM",
        foreign_keys="TestRunTargetORM.loadgenerator_id",
        back_populates="loadgenerator",
    )
    calibration_results: Mapped[list["CalibrationResultORM"]] = relationship(
        "CalibrationResultORM", back_populates="target"
    )

    __table_args__ = (
        Index("idx_servers_lab", "lab_id"),
        Index("idx_servers_baseline", "baseline_id"),
    )


class BaselineORM(Base):
    """ORM model for baseline table.

    Represents a snapshot/image that can be restored for testing.
    baseline_type determines HOW to restore (BaselineType enum):
    - docker: Pull image, recreate container
    - vsphere: Revert to vSphere snapshot
    - aws: Create from AMI or restore EBS snapshot
    - azure/gcp: Restore from cloud snapshot
    - intune/jamf: Re-apply MDM policy
    """

    __tablename__ = "baseline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Baseline type - how to restore (BaselineType enum)
    # Values: docker, vsphere, aws, azure, gcp, intune, jamf
    baseline_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Provider-specific reference (JSON) - structure depends on baseline_type
    # docker: {"image": "rhel:8.4", "registry": "registry.example.com"}
    # vsphere: {"snapshot_id": "snapshot-123", "vm_moid": "vm-456", "datacenter": "DC1"}
    # aws: {"ami_id": "ami-12345678", "region": "us-east-1"}
    # azure: {"snapshot_id": "...", "resource_group": "..."}
    # intune/jamf: {"policy_id": "...", "policy_name": "..."}
    provider_ref: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    # OS family for credential lookup (redhat, microsoft, ubuntu, etc.)
    # MANDATORY - used for: lab_id + os_family -> credentials
    os_family: Mapped[str] = mapped_column(String(50), nullable=False)

    # DB type for database connection string lookup (DatabaseType enum)
    # Values: postgres, mysql, oracle, mssql
    # Only set if this baseline is for a database server
    db_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Deployment type - how to deploy packages (DeploymentType enum)
    # Values: ssh, winrm, docker_exec, ssm, intune, jamf
    # Cascade: PackageGroupMember.con_type → Baseline.deployment_type → Server.deployment_type
    deployment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # OS information for package matching
    os_vendor_family: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    os_major_ver: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    os_minor_ver: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    os_kernel_ver: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Scope
    baseline_scope: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Legacy configuration (for backwards compatibility)
    baseline_conf: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    lab_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labs.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lab: Mapped["LabORM"] = relationship("LabORM", back_populates="baselines")
    servers: Mapped[list["ServerORM"]] = relationship(
        "ServerORM", back_populates="baseline"
    )
    calibration_results: Mapped[list["CalibrationResultORM"]] = relationship(
        "CalibrationResultORM", back_populates="baseline"
    )

    __table_args__ = (
        Index("idx_baseline_lab", "lab_id"),
        Index("idx_baseline_type", "baseline_type"),
    )


class TestRunORM(Base):
    """ORM model for test_runs table."""

    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Foreign keys
    lab_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labs.id"), nullable=False
    )
    trace_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("trace_ids.id"), nullable=True
    )
    env_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("environments.id"), nullable=True
    )

    # Load profile configuration
    req_loadprofile: Mapped[list[str]] = mapped_column(
        ArrayOfStrings(), nullable=False
    )
    warmup_sec: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    measured_sec: Mapped[int] = mapped_column(Integer, default=10800, nullable=False)
    analysis_trim_sec: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Load generator packages
    loadgenerator_package_grpid_lst: Mapped[list[int]] = mapped_column(
        ArrayOfIntegers(), nullable=False
    )
    runner_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lab: Mapped["LabORM"] = relationship("LabORM", back_populates="test_runs")
    trace: Mapped[Optional["TraceIdORM"]] = relationship(
        "TraceIdORM", back_populates="test_runs"
    )
    targets: Mapped[list["TestRunTargetORM"]] = relationship(
        "TestRunTargetORM", back_populates="test_run", lazy="selectin"
    )
    executions: Mapped[list["TestRunExecutionORM"]] = relationship(
        "TestRunExecutionORM", back_populates="test_run", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_test_runs_lab", "lab_id"),
        Index("idx_test_runs_trace", "trace_id"),
    )


class TestRunTargetORM(Base):
    """ORM model for test_run_targets table."""

    __tablename__ = "test_run_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_runs.id"), nullable=False
    )
    scenario_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("scenarios.id"), nullable=True
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )
    loadgenerator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )

    # OS family for credential lookup (derived from effective baseline)
    # MANDATORY - populated from baseline cascade during test run creation
    os_family: Mapped[str] = mapped_column(String(50), nullable=False)

    # Role and pairing
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    partner_target_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=True
    )

    # Calibration result (stored after calibration completes)
    calibration_json: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    # JMeter configuration
    jmeter_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jmx_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Baseline snapshots
    base_snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )
    initial_snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )
    upgrade_snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    test_run: Mapped["TestRunORM"] = relationship(
        "TestRunORM", back_populates="targets"
    )
    target: Mapped["ServerORM"] = relationship(
        "ServerORM",
        foreign_keys=[target_id],
        back_populates="targets_as_target",
    )
    loadgenerator: Mapped["ServerORM"] = relationship(
        "ServerORM",
        foreign_keys=[loadgenerator_id],
        back_populates="targets_as_loadgen",
    )

    __table_args__ = (
        UniqueConstraint("test_run_id", "target_id", name="uq_test_run_target"),
        UniqueConstraint(
            "test_run_id", "loadgenerator_id", "jmeter_port",
            name="uq_test_run_loadgen_port"
        ),
        Index("idx_test_run_targets_test_run", "test_run_id"),
        Index("idx_test_run_targets_loadgen", "loadgenerator_id"),
        Index("idx_test_run_targets_scenario", "scenario_id"),
    )


class TestRunExecutionORM(Base):
    """ORM model for test_run_execution table.

    This is the SOURCE OF TRUTH for execution state.
    All actions must READ status from here before proceeding.
    """

    __tablename__ = "test_run_execution"

    id: Mapped[uuid.UUID] = mapped_column(
        GuidType(), primary_key=True, default=uuid4
    )
    test_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_runs.id"), nullable=False
    )

    run_mode: Mapped[str] = mapped_column(
        String(20), default="continuous", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="notstarted", nullable=False
    )

    # Pause handling
    pause_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    pause_after_scenario: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Current progress tracking
    current_scenario_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("scenarios.id"), nullable=True
    )
    current_loadprofile: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    current_repetition: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_phase: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    test_run: Mapped["TestRunORM"] = relationship(
        "TestRunORM", back_populates="executions"
    )
    workflow_states: Mapped[list["ExecutionWorkflowStateORM"]] = relationship(
        "ExecutionWorkflowStateORM", back_populates="execution", lazy="selectin"
    )
    scenario_statuses: Mapped[list["TestRunExecutionScenarioStatusORM"]] = relationship(
        "TestRunExecutionScenarioStatusORM", back_populates="execution", lazy="selectin"
    )

    __table_args__ = (
        # Note: Conditional/filtered index removed for cross-database compatibility
        # PostgreSQL and SQL Server have different syntaxes for filtered indexes
        Index("idx_test_run_execution_test_run", "test_run_id"),
        Index("idx_test_run_execution_status", "status"),
    )


class CalibrationResultORM(Base):
    """ORM model for calibration_results table."""

    __tablename__ = "calibration_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("test_runs.id"), nullable=True
    )    
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )
    baseline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=False
    )
        # Only set if this server is a database server
    db_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    loadprofile: Mapped[str] = mapped_column(String(20), nullable=False)

    # Calibration output
    thread_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_gb: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cpu_target_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    achieved_cpu_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    # Iteration timing stats (HIGH load profile only)
    avg_iteration_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    stddev_iteration_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    min_iteration_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    max_iteration_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    iteration_sample_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    calibration_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GuidType(), nullable=True
    )
    calibration_status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )
    calibrated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    target: Mapped["ServerORM"] = relationship(
        "ServerORM", back_populates="calibration_results"
    )
    baseline: Mapped["BaselineORM"] = relationship(
        "BaselineORM", back_populates="calibration_results"
    )

    __table_args__ = (
        UniqueConstraint(
            "test_run_id", "target_id", "baseline_id", "loadprofile", "db_type",
            name="uq_calibration_testrun_target_baseline_profile_dbtype"
        ),
        Index("idx_calibration_lookup", "test_run_id", "target_id", "baseline_id", "loadprofile", "db_type"),
    )


class ExecutionWorkflowStateORM(Base):
    """ORM model for execution_workflow_state table.

    Tracks workflow state per target during test execution.
    Uses list-based package tracking for each phase (base, initial, upgrade).

    Package lists contain all packages to install (loadgen, agent, other).
    Measured lists contain installation results and version verification.

    Note: Upgrade phase can run ON TOP of initial_snapshot (no revert)
    if upgrade_snapshot_id is NULL but upgrade_package_grp_id is defined.
    """

    __tablename__ = "execution_workflow_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_execution_id: Mapped[uuid.UUID] = mapped_column(
        GuidType(), ForeignKey("test_run_execution.id"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=False
    )

    loadprofile: Mapped[str] = mapped_column(String(20), nullable=False)
    runcount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Current state (using WorkflowState enum values)
    cur_state: Mapped[str] = mapped_column(String(50), default="norun", nullable=False)

    # Current phase tracking
    current_phase: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phase_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Baseline/Snapshot references (from test_run_target)
    base_baseline_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )
    initial_baseline_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )
    upgrade_baseline_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("baseline.id"), nullable=True
    )

    # Flag: Does upgrade phase revert or run on top of initial?
    upgrade_revert_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # =========================================================================
    # BASE PHASE - Package tracking (loadgen only, no agents)
    # =========================================================================
    # List of packages to install: [{package_id, package_name, version, type, ...}]
    base_package_lst: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    # Measured results: [{package_id, install_status, measured_version, matched, ...}]
    base_package_lst_measured: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    # All packages matched?
    base_packages_matched: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # BASE PHASE - Results (compressed binary blobs)
    # All test results from Load Generator; base snapshot doesn't have agents
    # Dictionary: {package_id: {results...}, "jmeter": {...}}
    base_device_result_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # All stats collected during execution (CPU, memory, disk, network time series)
    # Dictionary: {package_id: {stats...}, "system": {...}}
    base_device_stats_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution result - was command successful? exit codes, stdout/stderr
    # Dictionary: {package_id: {command, exit_code, success, ...}}
    base_device_execution_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution logs (optional, collected on error)
    base_device_execution_logs_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )

    # =========================================================================
    # INITIAL PHASE - Package tracking (loadgen + agent + other)
    # =========================================================================
    initial_package_lst: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    initial_package_lst_measured: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    initial_packages_matched: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # INITIAL PHASE - Results (compressed binary blobs)
    # All test results from policy, Load Generator, dictionary by package_id
    # Dictionary: {package_id: {results...}, "jmeter": {...}, "functional": {...}}
    initial_device_result_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # All stats collected during execution
    initial_device_stats_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution result - command success/failure for jmeter, policy execution
    initial_device_execution_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution logs (optional, collected on error)
    initial_device_execution_logs_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )

    # =========================================================================
    # UPGRADE PHASE - Package tracking (loadgen + upgrade_agent + other)
    # Note: May use different OS than initial if upgrade_snapshot is different
    # =========================================================================
    upgrade_package_lst: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    upgrade_package_lst_measured: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    upgrade_packages_matched: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # UPGRADE PHASE - Results (compressed binary blobs)
    # All test results from policy, Load Generator, dictionary by package_id
    upgrade_device_result_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # All stats collected during execution
    upgrade_device_stats_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution result - command success/failure
    upgrade_device_execution_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution logs (optional, collected on error)
    upgrade_device_execution_logs_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )

    # =========================================================================
    # JMETER - Package tracking (installed on load generator machine)
    # JMeter package group is defined at lab level (lab.jmeter_package_grpid)
    # =========================================================================
    # List of JMeter packages to install: [{package_id, package_name, version, ...}]
    jmeter_package_lst: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    # Measured results: [{package_id, install_status, measured_version, matched, ...}]
    jmeter_package_lst_measured: Mapped[Optional[list]] = mapped_column(JsonType(), nullable=True)
    # All JMeter packages matched?
    jmeter_packages_matched: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # JMETER - Results (compressed binary blobs)
    # JMeter load test results (throughput, latency, response times, etc.)
    # Dictionary: {"jmeter": {results...}}
    jmeter_device_result_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Stats collected during JMeter execution (CPU/memory of load generator)
    jmeter_device_stats_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # Execution result - was JMeter command successful?
    jmeter_device_execution_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    # JMeter execution logs (optional, collected on error)
    jmeter_device_execution_logs_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )

    # =========================================================================
    # Error tracking
    # =========================================================================
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_history: Mapped[list] = mapped_column(JsonType(), default=list, nullable=False)

    phase_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    phase_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    execution: Mapped["TestRunExecutionORM"] = relationship(
        "TestRunExecutionORM", back_populates="workflow_states"
    )

    __table_args__ = (
        UniqueConstraint(
            "test_run_execution_id", "target_id", "loadprofile", "runcount",
            name="uq_workflow_state"
        ),
        Index("idx_workflow_state_cur_state", "cur_state"),
    )


class HardwareProfileORM(Base):
    """ORM model for hardware_profiles table.

    Stores hardware specifications for servers.
    Used for calibration calculations and capacity planning.
    Immutable per TraceId.
    """

    __tablename__ = "hardware_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    memory_gb: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    disk_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    disk_size_gb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # EUC-specific fields
    device_make: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    traces: Mapped[list["TraceIdORM"]] = relationship(
        "TraceIdORM", back_populates="hardware_profile"
    )
    servers: Mapped[list["ServerORM"]] = relationship(
        "ServerORM", back_populates="hardware_profile"
    )


class ScenarioORM(Base):
    """ORM model for scenarios table.

    Represents a test scenario - a fixed combination of:
    - Target servers (with their snapshots)
    - Load generators
    - Agent configurations (via scenario_cases)
    - Phase flags (has_base_phase, has_initial_phase, has_upgrade_phase)
    - Load type (has_dbtest)

    Calibration is done ONCE per scenario and reused for all test runs.
    """

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    lab_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labs.id"), nullable=False
    )
    test_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("test_runs.id"), nullable=True
    )
    

    # Scenario configuration
    target_server_ids: Mapped[list[int]] = mapped_column(
        ArrayOfIntegers(), nullable=False
    )
    loadgen_server_ids: Mapped[list[int]] = mapped_column(
        ArrayOfIntegers(), nullable=False
    )
 

    # Load generator package group
    load_generator_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=True
    )

    has_dbtest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


    # Phase control flags - which phases are active for this scenario
    # At least 2 phases required for meaningful comparison
    has_base_phase: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    has_initial_phase: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    has_upgrade_phase: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Execution order (lower = first)
    execution_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Calibration status
    is_calibrated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    calibrated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lab: Mapped["LabORM"] = relationship("LabORM", back_populates="scenarios")
    scenario_cases: Mapped[list["ScenarioCaseORM"]] = relationship(
        "ScenarioCaseORM", back_populates="scenario", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_scenarios_lab", "lab_id"),
        Index("idx_scenarios_active", "is_active"),
        Index("idx_scenarios_test_run", "test_run_id"),
    )


class PackageGroupORM(Base):
    """ORM model for package_groups table.

    Groups related packages together (e.g., "JMeter Load Generator", "CPU Emulator").
    Maps to OS-specific packages via package_group_members.
    """

    __tablename__ = "package_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    group_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Agent-specific package group (for agent installers)
    agent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("agents.id", name="fk_package_groups_agent", use_alter=True),
        nullable=True
    )
    agent_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Kernel version matching required
    req_kernel_version: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    members: Mapped[list["PackageGroupMemberORM"]] = relationship(
        "PackageGroupMemberORM", back_populates="package_group", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_package_groups_type", "group_type"),
        Index("idx_package_groups_agent", "agent_id"),
    )


class PackageORM(Base):
    """ORM model for packages table.

    Stores package definitions with version, download, and execution information.
    Supports multiple delivery methods via delivery_config JSONB.
    """

    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    package_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Execution control
    run_at_load: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_restart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    restart_timeout_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Delivery configuration (typed JSON - supports SCRIPT, INTUNE, JAMF, WORKFLOW)
    delivery_config: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    # Output paths
    execution_result_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    test_results_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stats_collect_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logs_collect_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Verification
    version_check_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_version_regex: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uninstall_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Legacy fields (for backwards compatibility)
    download_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    checksum_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    install_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verify_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    group_members: Mapped[list["PackageGroupMemberORM"]] = relationship(
        "PackageGroupMemberORM", back_populates="package"
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_package_name_version"),
        Index("idx_packages_type", "package_type"),
    )


class PackageGroupMemberORM(Base):
    """ORM model for package_group_members table.

    Maps packages to groups with OS-specific configuration.
    Uses os_match_regex to match '{os_vendor}/{os_major}/{os_minor}[/{kernel}]'.
    """

    __tablename__ = "package_group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=False
    )
    package_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("packages.id"), nullable=False
    )

    # OS matching pattern (regex)
    os_match_regex: Mapped[str] = mapped_column(String(255), nullable=False)

    # Connection/delivery type for this member
    con_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Priority (lower = first match)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Legacy field (for backwards compatibility)
    os_family: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    install_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    config_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    package_group: Mapped["PackageGroupORM"] = relationship(
        "PackageGroupORM", back_populates="members"
    )
    package: Mapped["PackageORM"] = relationship(
        "PackageORM", back_populates="group_members"
    )

    __table_args__ = (
        UniqueConstraint(
            "package_group_id", "package_id", "os_match_regex", "con_type",
            name="uq_package_group_member"
        ),
        Index("idx_package_group_members_group", "package_group_id"),
        Index("idx_package_group_members_con_type", "con_type"),
    )


# =============================================================================
# NEW ORMS - Added to match documentation
# =============================================================================


class AgentORM(Base):
    """ORM model for agents table.

    Defines security agents being tested (CrowdStrike, Tanium, PKWare, etc.).
    Each agent has associated package groups for install, uninstall, and testing.
    """

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Package groups for this agent
    uninstall_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("package_groups.id", name="fk_agents_uninstall_pkg_grp"),
        nullable=True
    )
    troubleshoot_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("package_groups.id", name="fk_agents_troubleshoot_pkg_grp"),
        nullable=True
    )
    functional_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("package_groups.id", name="fk_agents_functional_pkg_grp"),
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    scenario_cases: Mapped[list["ScenarioCaseORM"]] = relationship(
        "ScenarioCaseORM", back_populates="agent"
    )


class LoadProfileORM(Base):
    """ORM model for load_profiles table.

    Defines CPU bounds for each load profile level (low, medium, high).
    Calibration aims to hit the midpoint of cpu_low and cpu_high.
    """

    __tablename__ = "load_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cpu_low: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    cpu_high: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class EnvironmentORM(Base):
    """ORM model for environments table.

    Groups targets together for a test run.
    Referenced by targets and test_runs.
    """

    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    lab_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labs.id"), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lab: Mapped["LabORM"] = relationship("LabORM", back_populates="environments")

    __table_args__ = (
        Index("idx_environments_lab", "lab_id"),
    )


class TraceIdORM(Base):
    """ORM model for trace_ids table.

    Tracks agent performance trends across an OS vendor family.
    Hardware profile is immutable within a trace.
    """

    __tablename__ = "trace_ids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    os_family: Mapped[str] = mapped_column(String(20), nullable=False)
    hardware_profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hardware_profiles.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    hardware_profile: Mapped["HardwareProfileORM"] = relationship(
        "HardwareProfileORM", back_populates="traces"
    )
    test_runs: Mapped[list["TestRunORM"]] = relationship(
        "TestRunORM", back_populates="trace"
    )

    __table_args__ = (
        Index("idx_traces_os_family", "os_family"),
        Index("idx_traces_status", "status"),
    )


class ScenarioCaseORM(Base):
    """ORM model for scenario_cases table.

    Per-agent configuration within a scenario.
    One scenario_case per agent in the scenario.
    """

    __tablename__ = "scenario_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scenarios.id"), nullable=False
    )
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False
    )

    # Package groups for this agent in this scenario
    initial_package_grp_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=False
    )
    upgrade_package_grp_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("package_groups.id"), nullable=True
    )

    # List of additional package group IDs (functional/policy tests)
    other_package_grp_ids: Mapped[Optional[list[int]]] = mapped_column(
        ArrayOfIntegers(), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    scenario: Mapped["ScenarioORM"] = relationship(
        "ScenarioORM", back_populates="scenario_cases"
    )
    agent: Mapped["AgentORM"] = relationship(
        "AgentORM", back_populates="scenario_cases"
    )

    __table_args__ = (
        UniqueConstraint("scenario_id", "agent_id", name="uq_scenario_case_agent"),
        Index("idx_scenario_cases_scenario", "scenario_id"),
    )


class TestRunExecutionScenarioStatusORM(Base):
    """ORM model for test_run_execution_scenario_status table.

    Tracks execution status per scenario per loadprofile per repetition.
    A scenario executes load on ALL targets in parallel.
    This table tracks when a loadprofile is complete/failed for the entire scenario.

    Execution order: scenario.execution_order → loadprofile (low→med→high) → repetition
    """

    __tablename__ = "test_run_execution_scenario_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_run_execution_id: Mapped[uuid.UUID] = mapped_column(
        GuidType(), ForeignKey("test_run_execution.id"), nullable=False
    )
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scenarios.id"), nullable=False
    )

    # Execution ordering
    loadprofile: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False)
    repetition: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Status tracking
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    phase: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Aggregated results from all targets in this scenario
    result_summary_json: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    # Calibration data (if this is calibration phase)
    calibration_data_json: Mapped[Optional[dict]] = mapped_column(JsonType(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    execution: Mapped["TestRunExecutionORM"] = relationship(
        "TestRunExecutionORM", back_populates="scenario_statuses"
    )
    scenario: Mapped["ScenarioORM"] = relationship("ScenarioORM")

    __table_args__ = (
        UniqueConstraint(
            "test_run_execution_id", "scenario_id", "loadprofile", "repetition",
            name="uq_execution_scenario_status"
        ),
        Index("idx_exec_scenario_status_execution", "test_run_execution_id"),
        Index("idx_exec_scenario_status_pending", "test_run_execution_id", "status"),
        Index(
            "idx_exec_scenario_status_order",
            "test_run_execution_id", "execution_order", "loadprofile", "repetition"
        ),
    )
