"""Pydantic request/response schemas for all API endpoints.

Each entity has:
  - {Entity}Create: fields for creation (no id, no created_at)
  - {Entity}Update: all fields optional for partial update
  - {Entity}Response: full entity representation returned to client
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

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
    ServerRole,
    TemplateType,
    TestPhaseType,
    TestRunState,
    Verdict,
)


# ---- Lab ----

class LabCreate(BaseModel):
    name: str = Field(max_length=255)
    description: Optional[str] = None
    jmeter_package_grpid: int
    emulator_package_grp_id: Optional[int] = None
    loadgen_snapshot_id: int
    hypervisor_type: HypervisorType
    hypervisor_manager_url: str = Field(max_length=512)
    hypervisor_manager_port: int
    execution_mode: ExecutionMode = ExecutionMode.live_compare


class LabUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    jmeter_package_grpid: Optional[int] = None
    emulator_package_grp_id: Optional[int] = None
    loadgen_snapshot_id: Optional[int] = None
    hypervisor_type: Optional[HypervisorType] = None
    hypervisor_manager_url: Optional[str] = Field(default=None, max_length=512)
    hypervisor_manager_port: Optional[int] = None
    execution_mode: Optional[ExecutionMode] = None


class LabResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    jmeter_package_grpid: int
    emulator_package_grp_id: Optional[int]
    loadgen_snapshot_id: int
    hypervisor_type: HypervisorType
    hypervisor_manager_url: str
    hypervisor_manager_port: int
    execution_mode: ExecutionMode
    created_at: datetime


# ---- HardwareProfile ----

class HardwareProfileCreate(BaseModel):
    name: str = Field(max_length=255)
    cpu_count: int
    cpu_model: Optional[str] = Field(default=None, max_length=255)
    memory_gb: float
    disk_type: DiskType
    disk_size_gb: float
    nic_speed_mbps: Optional[int] = None
    vendor: Optional[str] = Field(default=None, max_length=255)


class HardwareProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    cpu_count: Optional[int] = None
    cpu_model: Optional[str] = Field(default=None, max_length=255)
    memory_gb: Optional[float] = None
    disk_type: Optional[DiskType] = None
    disk_size_gb: Optional[float] = None
    nic_speed_mbps: Optional[int] = None
    vendor: Optional[str] = Field(default=None, max_length=255)


class HardwareProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    cpu_count: int
    cpu_model: Optional[str]
    memory_gb: float
    disk_type: DiskType
    disk_size_gb: float
    nic_speed_mbps: Optional[int]
    vendor: Optional[str] = None


# ---- Server ----

class ServerCreate(BaseModel):
    hostname: str = Field(max_length=255)
    ip_address: str = Field(max_length=45)
    os_family: OSFamily
    role: ServerRole
    os_vendor_family: Optional[str] = Field(default=None, max_length=100)
    os_major_ver: Optional[str] = Field(default=None, max_length=20)
    os_minor_ver: Optional[str] = Field(default=None, max_length=20)
    lab_id: int
    hardware_profile_id: int
    server_infra_type: ServerInfraType
    server_infra_ref: Dict[str, Any]
    baseline_id: Optional[int] = None
    db_type: Optional[DBType] = None
    db_port: Optional[int] = None
    db_name: Optional[str] = Field(default=None, max_length=255)
    db_user: Optional[str] = Field(default=None, max_length=255)
    db_password: Optional[str] = Field(default=None, max_length=255)


class ServerUpdate(BaseModel):
    hostname: Optional[str] = Field(default=None, max_length=255)
    ip_address: Optional[str] = Field(default=None, max_length=45)
    os_family: Optional[OSFamily] = None
    role: Optional[ServerRole] = None
    os_vendor_family: Optional[str] = Field(default=None, max_length=100)
    os_major_ver: Optional[str] = Field(default=None, max_length=20)
    os_minor_ver: Optional[str] = Field(default=None, max_length=20)
    lab_id: Optional[int] = None
    hardware_profile_id: Optional[int] = None
    server_infra_type: Optional[ServerInfraType] = None
    server_infra_ref: Optional[Dict[str, Any]] = None
    baseline_id: Optional[int] = None
    db_type: Optional[DBType] = None
    db_port: Optional[int] = None
    db_name: Optional[str] = Field(default=None, max_length=255)
    db_user: Optional[str] = Field(default=None, max_length=255)
    db_password: Optional[str] = Field(default=None, max_length=255)
    root_snapshot_id: Optional[int] = None


class ServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hostname: str
    ip_address: str
    os_family: OSFamily
    os_vendor_family: Optional[str] = None
    os_major_ver: Optional[str] = None
    os_minor_ver: Optional[str] = None
    lab_id: int
    hardware_profile_id: int
    role: ServerRole
    server_infra_type: ServerInfraType
    server_infra_ref: Dict[str, Any]
    baseline_id: Optional[int]
    db_type: Optional[DBType]
    db_port: Optional[int]
    db_name: Optional[str]
    db_user: Optional[str]
    db_password: Optional[str]
    default_loadgen_id: Optional[int] = None
    default_partner_id: Optional[int] = None
    service_monitor_patterns: Optional[List[str]] = None
    root_snapshot_id: Optional[int] = None
    subgroup_count: int = 0
    is_ready: bool = False
    created_at: datetime


# ---- Server Snapshot ----

class CreateSnapshotRequest(BaseModel):
    """Request to create a snapshot from a running server."""
    baseline_name: str = Field(max_length=255, description="Name for the new baseline record")
    description: Optional[str] = Field(default=None, description="Snapshot description")


# ---- Baseline ----

class BaselineCreate(BaseModel):
    name: str = Field(max_length=255)
    os_family: OSFamily
    os_vendor_family: str = Field(max_length=100)
    os_major_ver: str = Field(max_length=20)
    os_minor_ver: Optional[str] = Field(default=None, max_length=20)
    os_kernel_ver: Optional[str] = Field(default=None, max_length=100)
    db_type: Optional[DBType] = None
    baseline_type: BaselineType
    provider_ref: Dict[str, Any]


class BaselineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    os_family: Optional[OSFamily] = None
    os_vendor_family: Optional[str] = Field(default=None, max_length=100)
    os_major_ver: Optional[str] = Field(default=None, max_length=20)
    os_minor_ver: Optional[str] = Field(default=None, max_length=20)
    os_kernel_ver: Optional[str] = Field(default=None, max_length=100)
    db_type: Optional[DBType] = None
    baseline_type: Optional[BaselineType] = None
    provider_ref: Optional[Dict[str, Any]] = None


class BaselineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    os_family: OSFamily
    os_vendor_family: str
    os_major_ver: str
    os_minor_ver: Optional[str]
    os_kernel_ver: Optional[str]
    db_type: Optional[DBType]
    baseline_type: BaselineType
    provider_ref: Dict[str, Any]
    created_at: datetime


# ---- PackageGroup ----

class PackageGroupCreate(BaseModel):
    name: str = Field(max_length=255)
    description: Optional[str] = None


class PackageGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None


class PackageGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    created_at: datetime


# ---- PackageGroupMember ----

class PackageGroupMemberCreate(BaseModel):
    package_group_id: int
    os_match_regex: str = Field(max_length=255)
    path: str = Field(max_length=1024)
    root_install_path: str = Field(max_length=1024)
    extraction_command: Optional[str] = Field(default=None, max_length=1024)
    install_command: Optional[str] = Field(default=None, max_length=1024)
    run_command: Optional[str] = Field(default=None, max_length=1024)
    output_path: Optional[str] = Field(default=None, max_length=1024)
    uninstall_command: Optional[str] = Field(default=None, max_length=1024)
    status_command: Optional[str] = Field(default=None, max_length=1024)
    prereq_script: Optional[str] = Field(default=None, max_length=1024, description="Path to prerequisite script relative to prerequisites/ dir (e.g. ubuntu/java_jre.sh)")


class PackageGroupMemberUpdate(BaseModel):
    os_match_regex: Optional[str] = Field(default=None, max_length=255)
    path: Optional[str] = Field(default=None, max_length=1024)
    root_install_path: Optional[str] = Field(default=None, max_length=1024)
    extraction_command: Optional[str] = Field(default=None, max_length=1024)
    install_command: Optional[str] = Field(default=None, max_length=1024)
    run_command: Optional[str] = Field(default=None, max_length=1024)
    output_path: Optional[str] = Field(default=None, max_length=1024)
    uninstall_command: Optional[str] = Field(default=None, max_length=1024)
    status_command: Optional[str] = Field(default=None, max_length=1024)
    prereq_script: Optional[str] = Field(default=None, max_length=1024)


class PackageGroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    package_group_id: int
    os_match_regex: str
    path: str
    root_install_path: str
    extraction_command: Optional[str]
    install_command: Optional[str]
    run_command: Optional[str]
    output_path: Optional[str]
    uninstall_command: Optional[str]
    status_command: Optional[str]
    prereq_script: Optional[str]


# ---- Scenario ----

class ScenarioCreate(BaseModel):
    name: str = Field(max_length=255)
    description: Optional[str] = None
    lab_id: int
    template_type: TemplateType
    has_base_phase: bool = True
    has_initial_phase: bool = True
    has_dbtest: bool = False
    load_generator_package_grp_id: int
    initial_package_grp_id: Optional[int] = None
    other_package_grp_ids: Optional[List[int]] = None
    functional_package_grp_id: Optional[int] = None
    functional_test_phase: Optional[FunctionalTestPhase] = None
    stress_test_enabled: bool = False
    stress_test_duration_sec: Optional[int] = 120
    stress_test_thread_multiplier: Optional[float] = 4.0
    network_degradation_enabled: bool = False
    network_degradation_pct: Optional[float] = 10.0
    network_degradation_duration_sec: Optional[int] = None


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    lab_id: Optional[int] = None
    template_type: Optional[TemplateType] = None
    has_base_phase: Optional[bool] = None
    has_initial_phase: Optional[bool] = None
    has_dbtest: Optional[bool] = None
    load_generator_package_grp_id: Optional[int] = None
    initial_package_grp_id: Optional[int] = None
    other_package_grp_ids: Optional[List[int]] = None
    functional_package_grp_id: Optional[int] = None
    functional_test_phase: Optional[FunctionalTestPhase] = None
    stress_test_enabled: Optional[bool] = None
    stress_test_duration_sec: Optional[int] = None
    stress_test_thread_multiplier: Optional[float] = None
    network_degradation_enabled: Optional[bool] = None
    network_degradation_pct: Optional[float] = None
    network_degradation_duration_sec: Optional[int] = None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    lab_id: int
    template_type: TemplateType
    has_base_phase: bool
    has_initial_phase: bool
    has_dbtest: bool
    load_generator_package_grp_id: int
    initial_package_grp_id: Optional[int]
    other_package_grp_ids: Optional[List[int]]
    functional_package_grp_id: Optional[int]
    functional_test_phase: Optional[FunctionalTestPhase]
    stress_test_enabled: bool
    stress_test_duration_sec: Optional[int]
    stress_test_thread_multiplier: Optional[float]
    network_degradation_enabled: bool
    network_degradation_pct: Optional[float]
    network_degradation_duration_sec: Optional[int]
    created_at: datetime


# ---- LoadProfile ----

class LoadProfileCreate(BaseModel):
    name: str = Field(max_length=100)
    target_cpu_range_min: float
    target_cpu_range_max: float
    duration_sec: int = Field(gt=0)
    ramp_up_sec: int = Field(ge=0)


class LoadProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    target_cpu_range_min: Optional[float] = None
    target_cpu_range_max: Optional[float] = None
    duration_sec: Optional[int] = Field(default=None, gt=0)
    ramp_up_sec: Optional[int] = Field(default=None, ge=0)


class LoadProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    target_cpu_range_min: float
    target_cpu_range_max: float
    duration_sec: int
    ramp_up_sec: int


# ---- DBSchemaConfig ----

class DBSchemaConfigCreate(BaseModel):
    db_type: DBType
    schema_path: str = Field(max_length=1024)
    seed_data_path: str = Field(max_length=1024)
    param_csv_path: Optional[str] = Field(default=None, max_length=1024)


class DBSchemaConfigUpdate(BaseModel):
    schema_path: Optional[str] = Field(default=None, max_length=1024)
    seed_data_path: Optional[str] = Field(default=None, max_length=1024)
    param_csv_path: Optional[str] = Field(default=None, max_length=1024)


class DBSchemaConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    db_type: DBType
    schema_path: str
    seed_data_path: str
    param_csv_path: Optional[str]


# ---- User (admin management) ----

class UserCreate(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(min_length=8)
    email: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class UserUpdate(BaseModel):
    email: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = Field(default=None, pattern=r"^(admin|user)$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    created_at: datetime


# ---- Agent ----

class AgentCreate(BaseModel):
    name: str = Field(max_length=255)
    vendor: Optional[str] = Field(default=None, max_length=255)
    agent_type: AgentType = AgentType.edr
    version: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    package_group_id: Optional[int] = None
    process_patterns: Optional[List[str]] = None
    service_patterns: Optional[List[str]] = None
    discovery_key: Optional[str] = Field(default=None, max_length=100)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    vendor: Optional[str] = Field(default=None, max_length=255)
    agent_type: Optional[AgentType] = None
    version: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    package_group_id: Optional[int] = None
    process_patterns: Optional[List[str]] = None
    service_patterns: Optional[List[str]] = None
    discovery_key: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    vendor: Optional[str]
    agent_type: AgentType
    version: Optional[str]
    description: Optional[str]
    package_group_id: Optional[int]
    process_patterns: Optional[List[str]]
    service_patterns: Optional[List[str]]
    discovery_key: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]


# ---- AnalysisRule ----

class AnalysisRuleCreate(BaseModel):
    rule_template_key: str = Field(max_length=100)
    threshold_value: float
    threshold_upper: Optional[float] = None
    severity: RuleSeverity = RuleSeverity.warning
    is_active: bool = True


class AnalysisRuleUpdate(BaseModel):
    threshold_value: Optional[float] = None
    threshold_upper: Optional[float] = None
    severity: Optional[RuleSeverity] = None
    is_active: Optional[bool] = None


class AnalysisRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: int
    rule_template_key: str
    threshold_value: float
    threshold_upper: Optional[float]
    severity: RuleSeverity
    is_active: bool
    created_at: datetime


# ---- RuleTemplate & Preset ----

class RuleTemplateResponse(BaseModel):
    key: str
    name: str
    category: str
    description: str
    data_source: str
    metric: str
    statistic: str
    comparison_mode: str
    operator: str
    unit: str
    default_threshold: float


class PresetRuleResponse(BaseModel):
    template_key: str
    threshold: float
    severity: str


class RulePresetResponse(BaseModel):
    key: str
    name: str
    description: str
    rules: List[PresetRuleResponse]


class ApplyPresetRequest(BaseModel):
    preset_key: str = Field(pattern=r"^(standard|strict|lenient)$")


# ---- TestRun ----

class TestRunCreate(BaseModel):
    scenario_id: int
    lab_id: int
    cycles_per_profile: int = Field(default=1, ge=1)
    run_mode: RunMode = RunMode.complete
    load_profile_ids: List[int] = Field(min_length=1)


class TestRunTargetCreate(BaseModel):
    target_id: int
    loadgenerator_id: int
    partner_id: Optional[int] = None
    base_snapshot_id: int
    initial_snapshot_id: int
    db_ready_base_snapshot_id: Optional[int] = None
    db_ready_initial_snapshot_id: Optional[int] = None
    service_monitor_patterns: Optional[List[str]] = None


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scenario_id: int
    lab_id: int
    cycles_per_profile: int
    run_mode: RunMode
    state: TestRunState
    current_snapshot_num: Optional[int]
    current_load_profile_id: Optional[int]
    current_cycle_number: Optional[int]
    error_message: Optional[str]
    overall_verdict: Optional[Verdict] = None
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TestRunTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    test_run_id: int
    target_id: int
    loadgenerator_id: int
    partner_id: Optional[int]
    base_snapshot_id: int
    initial_snapshot_id: int
    db_ready_base_snapshot_id: Optional[int]
    db_ready_initial_snapshot_id: Optional[int]
    service_monitor_patterns: Optional[List[str]]
    os_kind: Optional[str] = None
    base_os_major_ver: Optional[str] = None
    base_os_minor_ver: Optional[str] = None
    base_agent_versions: Optional[List[Dict[str, Any]]] = None
    initial_os_major_ver: Optional[str] = None
    initial_os_minor_ver: Optional[str] = None
    initial_agent_versions: Optional[List[Dict[str, Any]]] = None


class CalibrationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    test_run_id: int
    server_id: int
    os_type: OSFamily
    load_profile_id: int
    thread_count: int
    status: str
    phase: Optional[str] = None
    current_iteration: Optional[int] = None
    current_thread_count: Optional[int] = None
    last_observed_cpu: Optional[float] = None
    target_cpu_min: Optional[float] = None
    target_cpu_max: Optional[float] = None
    stability_check_num: Optional[int] = None
    stability_checks_total: Optional[int] = None
    stability_pct_in_range: Optional[float] = None
    stability_attempt: Optional[int] = None
    message: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PhaseExecutionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    test_run_id: int
    target_id: int
    snapshot_num: int
    load_profile_id: int
    cycle_number: int
    test_phase_type: TestPhaseType
    baseline_id: int
    thread_count: int
    status: ExecutionStatus
    network_degradation_pct: Optional[float]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    stats_file_path: Optional[str]
    jmeter_jtl_path: Optional[str]
    error_message: Optional[str]


class ComparisonResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    test_run_id: Optional[int] = None
    baseline_test_run_id: Optional[int] = None
    target_id: Optional[int] = None
    load_profile_id: int
    cycle: int = 1
    comparison_type: str
    result_file_path: Optional[str]
    result_data: Optional[Dict[str, Any]]
    summary_text: Optional[str]
    verdict: Optional[Verdict] = None
    violation_count: int = 0
    created_at: datetime


class BaselineExecutionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    baseline_test_run_id: int
    server_id: int
    load_profile_id: int
    cycle: int
    status: str
    thread_count: Optional[int] = None
    cpu_avg: Optional[float] = None
    cpu_p50: Optional[float] = None
    cpu_p95: Optional[float] = None
    cpu_min: Optional[float] = None
    cpu_max: Optional[float] = None
    mem_avg: Optional[float] = None
    jtl_total_requests: Optional[int] = None
    jtl_total_errors: Optional[int] = None
    jtl_success_rate_pct: Optional[float] = None
    stats_path: Optional[str] = None
    jtl_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---- Trending ----

class TrendDataPoint(BaseModel):
    test_run_id: int
    agent_version: Optional[str] = None
    os_kind: Optional[str] = None
    os_major_ver: Optional[str] = None
    os_minor_ver: Optional[str] = None
    hardware_profile_name: Optional[str] = None
    load_profile_name: Optional[str] = None
    value: Optional[float] = None
    is_ratio: bool = False
    base_value: Optional[float] = None
    run_date: datetime
    verdict: Optional[Verdict] = None


class TrendResponse(BaseModel):
    agent_name: str
    metric: str
    statistic: str
    data_points: List[TrendDataPoint]
    filters_applied: Dict[str, Any]


class TrendFiltersResponse(BaseModel):
    os_kinds: List[str]
    os_major_vers: List[str]
    hardware_profiles: List[Dict[str, Any]]
    load_profiles: List[Dict[str, Any]]


# ===========================================================================
# Baseline-Compare Mode Schemas
# ===========================================================================

# ---- Snapshot Baseline ----

class SnapshotBaselineCreate(BaseModel):
    name: str = Field(max_length=200)
    description: Optional[str] = None
    snapshot_name: Optional[str] = Field(
        default=None, max_length=200,
        description="Name for new hypervisor snapshot. Required if existing_snapshot_id is not set.",
    )
    existing_snapshot_id: Optional[int] = Field(
        default=None,
        description="Link to an existing DB snapshot instead of creating a new one.",
    )


class SnapshotBaselineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    server_id: int
    snapshot_id: int
    name: str
    description: Optional[str]
    created_at: datetime


# ---- Snapshot Group (UI: "Subgroup") ----

class SnapshotGroupCreate(BaseModel):
    baseline_id: int
    name: str = Field(max_length=200)
    description: Optional[str] = None
    snapshot_name: Optional[str] = Field(
        default=None, max_length=200,
        description="Hypervisor snapshot name. Auto-generated if omitted.",
    )
    existing_snapshot_id: Optional[int] = Field(
        default=None,
        description="Link to an existing snapshot instead of creating a new one.",
    )


class SnapshotGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    baseline_id: int
    snapshot_id: Optional[int]
    name: str
    description: Optional[str]
    created_at: datetime


# ---- Hypervisor Snapshot (common structure from all providers) ----

class HypervisorSnapshotSchema(BaseModel):
    """Common snapshot structure returned by all hypervisor providers."""
    name: str
    description: str
    id: str
    parent: Optional[str]
    created: Optional[int]


class HypervisorSnapshotListItem(HypervisorSnapshotSchema):
    """Hypervisor snapshot with DB linkage annotations (for picker UI)."""
    linked_in_db: bool = False
    db_snapshot_id: Optional[int] = None


# ---- Snapshot ----

class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    server_id: int
    parent_id: Optional[int]
    group_id: Optional[int]
    provider_snapshot_id: str
    provider_ref: Dict[str, Any]
    snapshot_tree: Optional[List[HypervisorSnapshotSchema]]
    is_baseline: bool
    is_archived: bool
    created_at: datetime


class SnapshotProfileDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    snapshot_id: int
    load_profile_id: int
    cycle: int = 1
    thread_count: int
    jmx_test_case_data: Optional[str]
    stats_data: Optional[str]
    stats_summary: Optional[Dict[str, Any]]
    jtl_data: Optional[str]
    source_snapshot_id: Optional[int]
    created_at: datetime


class SnapshotTreeNode(BaseModel):
    """Recursive tree representation of a snapshot and its children."""
    id: int
    name: str
    description: Optional[str]
    is_baseline: bool
    is_archived: bool
    has_data: bool
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    children: List["SnapshotTreeNode"] = []


class TakeSnapshotRequest(BaseModel):
    name: str = Field(max_length=200)
    description: Optional[str] = None
    group_id: Optional[int] = None


class DeleteSnapshotRequest(BaseModel):
    snapshot_id: int


class ValidateSnapshotResponse(BaseModel):
    snapshot_id: int
    provider_snapshot_id: str
    exists_on_hypervisor: bool


# ---- Baseline Test Run ----

class BaselineTestRunTargetEntry(BaseModel):
    """One target server entry in a baseline test run create request."""
    server_id: int
    test_snapshot_id: int
    compare_snapshot_id: Optional[int] = None
    # Optional per-target overrides (defaults taken from ServerORM)
    loadgenerator_id: Optional[int] = None
    partner_id: Optional[int] = None
    service_monitor_patterns: Optional[List[str]] = None


class BaselineTestRunCreate(BaseModel):
    scenario_id: int
    test_type: BaselineTestType
    load_profile_ids: List[int] = Field(min_length=1)
    targets: List[BaselineTestRunTargetEntry] = Field(min_length=1)
    cycle_count: int = Field(default=1, ge=1)


class BaselineTestRunTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    baseline_test_run_id: int
    target_id: int
    loadgenerator_id: int
    partner_id: Optional[int]
    test_snapshot_id: int
    compare_snapshot_id: Optional[int]
    service_monitor_patterns: Optional[List[str]]
    state: BaselineTargetState = BaselineTargetState.pending
    error_message: Optional[str] = None
    current_load_profile_id: Optional[int] = None
    os_kind: Optional[str] = None
    os_major_ver: Optional[str] = None
    os_minor_ver: Optional[str] = None
    agent_versions: Optional[Dict[str, Any]] = None


class BaselineTestRunLoadProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    baseline_test_run_id: int
    load_profile_id: int
    duration_sec: Optional[int] = None
    ramp_up_sec: Optional[int] = None


class BaselineTestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    lab_id: int
    scenario_id: int
    test_type: BaselineTestType
    parent_run_id: Optional[int] = None
    state: BaselineTestState
    current_load_profile_id: Optional[int]
    current_cycle: int = 1
    cycle_count: int = 1
    failed_at_state: Optional[str] = None
    error_message: Optional[str]
    verdict: Optional[Verdict] = None
    targets: List[BaselineTestRunTargetResponse] = []
    load_profiles: List[BaselineTestRunLoadProfileResponse] = []
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# ---- Baseline Test Run V2 (test case = test run) ----

class BaselineTestRunLoadProfileEntry(BaseModel):
    """Load profile entry with optional duration overrides."""
    load_profile_id: int
    duration_sec: Optional[int] = Field(default=None, gt=0)
    ramp_up_sec: Optional[int] = Field(default=None, ge=0)


class BaselineTestRunTargetEntryV2(BaseModel):
    """Target entry for V2 create — simplified (loadgen=partner)."""
    server_id: int
    test_snapshot_id: int
    compare_snapshot_id: Optional[int] = None
    loadgenerator_id: Optional[int] = None
    service_monitor_patterns: Optional[List[str]] = None


class BaselineTestRunCreateV2(BaseModel):
    """V2 create request — test run IS the test case. Scenario auto-created."""
    name: str = Field(max_length=255)
    description: Optional[str] = None
    template_type: TemplateType
    test_type: BaselineTestType
    parent_run_id: Optional[int] = None
    targets: List[BaselineTestRunTargetEntryV2] = Field(min_length=1)
    load_profiles: List[BaselineTestRunLoadProfileEntry] = Field(min_length=1)
    stress_test_enabled: bool = False
    network_degradation_enabled: bool = False
    cycle_count: int = Field(default=1, ge=1)


class BaselineTestRunUpdate(BaseModel):
    """Update request — only name/description editable, only when state=created."""
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
