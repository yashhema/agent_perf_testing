"""Admin CRUD API routers for all configuration entities.

All endpoints require admin role. Standard pattern:
  POST   /api/admin/{entity}       — create
  GET    /api/admin/{entity}       — list all
  GET    /api/admin/{entity}/{id}  — get by id
  PUT    /api/admin/{entity}/{id}  — update
  DELETE /api/admin/{entity}/{id}  — delete
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from orchestrator.api.schemas import (
    AgentCreate, AgentResponse, AgentUpdate,
    AnalysisRuleCreate, AnalysisRuleResponse, AnalysisRuleUpdate,
    ApplyPresetRequest,
    BaselineCreate, BaselineResponse, BaselineUpdate,
    CreateSnapshotRequest,
    DBSchemaConfigCreate, DBSchemaConfigResponse, DBSchemaConfigUpdate,
    HardwareProfileCreate, HardwareProfileResponse, HardwareProfileUpdate,
    LabCreate, LabResponse, LabUpdate,
    LoadProfileCreate, LoadProfileResponse, LoadProfileUpdate,
    PackageGroupCreate, PackageGroupMemberCreate,
    PackageGroupMemberResponse, PackageGroupMemberUpdate,
    PackageGroupResponse, PackageGroupUpdate,
    RulePresetResponse, RuleTemplateResponse,
    ScenarioCreate, ScenarioResponse, ScenarioUpdate,
    ServerCreate, ServerResponse, ServerUpdate,
    UserCreate, UserResponse, UserUpdate,
)
from orchestrator.models.database import get_session
from orchestrator.models.orm import (
    AgentORM, AnalysisRuleORM,
    BaselineORM, DBSchemaConfigORM, HardwareProfileORM, LabORM,
    LoadProfileORM, PackageGroupMemberORM, PackageGroupORM,
    ScenarioAgentORM, ScenarioORM, ServerORM, SnapshotORM, UserORM,
)
from orchestrator.models.enums import ServerRole
from orchestrator.services.auth import hash_password, require_admin
from orchestrator.services.rule_engine import apply_preset
from orchestrator.services.rule_templates import RULE_PRESETS, RULE_TEMPLATES

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# Helper: apply partial update from Pydantic model to ORM instance
# ---------------------------------------------------------------------------
def _apply_update(orm_obj, update_schema):
    """Set non-None fields from update_schema onto orm_obj."""
    for field_name, value in update_schema.model_dump(exclude_unset=True).items():
        setattr(orm_obj, field_name, value)


# ---------------------------------------------------------------------------
# Lab CRUD
# ---------------------------------------------------------------------------

@router.post("/labs", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
def create_lab(data: LabCreate, session: Session = Depends(get_session)):
    lab = LabORM(**data.model_dump())
    session.add(lab)
    session.commit()
    session.refresh(lab)
    return lab


@router.get("/labs", response_model=List[LabResponse])
def list_labs(session: Session = Depends(get_session)):
    return session.query(LabORM).all()


@router.get("/labs/{lab_id}", response_model=LabResponse)
def get_lab(lab_id: int, session: Session = Depends(get_session)):
    lab = session.get(LabORM, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    return lab


@router.put("/labs/{lab_id}", response_model=LabResponse)
def update_lab(lab_id: int, data: LabUpdate, session: Session = Depends(get_session)):
    lab = session.get(LabORM, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    _apply_update(lab, data)
    session.commit()
    session.refresh(lab)
    return lab


@router.delete("/labs/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lab(lab_id: int, session: Session = Depends(get_session)):
    lab = session.get(LabORM, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    session.delete(lab)
    session.commit()


# ---------------------------------------------------------------------------
# HardwareProfile CRUD
# ---------------------------------------------------------------------------

@router.post("/hardware-profiles", response_model=HardwareProfileResponse, status_code=status.HTTP_201_CREATED)
def create_hardware_profile(data: HardwareProfileCreate, session: Session = Depends(get_session)):
    obj = HardwareProfileORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/hardware-profiles", response_model=List[HardwareProfileResponse])
def list_hardware_profiles(session: Session = Depends(get_session)):
    return session.query(HardwareProfileORM).all()


@router.get("/hardware-profiles/{profile_id}", response_model=HardwareProfileResponse)
def get_hardware_profile(profile_id: int, session: Session = Depends(get_session)):
    obj = session.get(HardwareProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Hardware profile not found")
    return obj


@router.put("/hardware-profiles/{profile_id}", response_model=HardwareProfileResponse)
def update_hardware_profile(profile_id: int, data: HardwareProfileUpdate, session: Session = Depends(get_session)):
    obj = session.get(HardwareProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Hardware profile not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/hardware-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hardware_profile(profile_id: int, session: Session = Depends(get_session)):
    obj = session.get(HardwareProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Hardware profile not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Server CRUD
# ---------------------------------------------------------------------------

@router.post("/servers", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
def create_server(data: ServerCreate, session: Session = Depends(get_session)):
    obj = ServerORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/servers", response_model=List[ServerResponse])
def list_servers(
    lab_id: int = None,
    role: Optional[ServerRole] = None,
    session: Session = Depends(get_session),
):
    q = session.query(ServerORM)
    if lab_id is not None:
        q = q.filter(ServerORM.lab_id == lab_id)
    if role is not None:
        q = q.filter(ServerORM.role == role)
    return q.all()


@router.get("/servers/{server_id}", response_model=ServerResponse)
def get_server(server_id: int, session: Session = Depends(get_session)):
    obj = session.get(ServerORM, server_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Server not found")
    return obj


@router.put("/servers/{server_id}", response_model=ServerResponse)
def update_server(server_id: int, data: ServerUpdate, session: Session = Depends(get_session)):
    obj = session.get(ServerORM, server_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Server not found")
    # Validate root_snapshot_id: only for target servers, snapshot must belong to this server
    if data.root_snapshot_id is not None:
        effective_role = data.role or obj.role
        if effective_role != ServerRole.target:
            raise HTTPException(status_code=400, detail="root_snapshot_id only applies to target servers")
        snap = session.get(SnapshotORM, data.root_snapshot_id)
        if not snap or snap.server_id != server_id:
            raise HTTPException(status_code=400, detail="Snapshot not found for this server")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: int, session: Session = Depends(get_session)):
    obj = session.get(ServerORM, server_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Server not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Server Snapshot — create a hypervisor snapshot and store as a Baseline
# ---------------------------------------------------------------------------

@router.post("/servers/{server_id}/snapshots", response_model=BaselineResponse, status_code=status.HTTP_201_CREATED)
def create_server_snapshot(server_id: int, data: CreateSnapshotRequest, session: Session = Depends(get_session)):
    """Create a snapshot of a running server and store it as a BaselineORM record.

    Uses the server's lab hypervisor provider to create the snapshot,
    then stores the provider-returned snapshot_ref in baseline.provider_ref.
    """
    import logging
    logger = logging.getLogger(__name__)

    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    lab = session.get(LabORM, server.lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail=f"Lab {server.lab_id} not found")

    # Build hypervisor provider from lab config
    from orchestrator.app import credentials as cred_store
    from orchestrator.infra.hypervisor import create_hypervisor_provider

    try:
        hyp_cred = cred_store.get_hypervisor_credential(lab.hypervisor_type.value)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot load hypervisor credentials: {e}")

    provider = create_hypervisor_provider(
        hypervisor_type=lab.hypervisor_type.value,
        url=lab.hypervisor_manager_url,
        port=lab.hypervisor_manager_port,
        credential=hyp_cred,
    )

    # Create the snapshot via the provider
    try:
        snapshot_ref = provider.create_snapshot(
            server.server_infra_ref,
            data.baseline_name,
            description=data.description or f"Snapshot of {server.hostname}",
        )
    except Exception as e:
        logger.exception("Snapshot creation failed for server %s", server.hostname)
        raise HTTPException(status_code=500, detail=f"Snapshot creation failed: {e}")

    # Determine OS info from server's existing baseline or sensible defaults
    source_baseline = session.get(BaselineORM, server.baseline_id) if server.baseline_id else None

    baseline = BaselineORM(
        name=data.baseline_name,
        os_family=server.os_family,
        os_vendor_family=source_baseline.os_vendor_family if source_baseline else ("ubuntu" if server.os_family.value == "linux" else "windows_server"),
        os_major_ver=source_baseline.os_major_ver if source_baseline else "0",
        os_minor_ver=source_baseline.os_minor_ver if source_baseline else None,
        os_kernel_ver=source_baseline.os_kernel_ver if source_baseline else None,
        baseline_type=lab.hypervisor_type,
        provider_ref=snapshot_ref,
    )
    session.add(baseline)
    session.commit()
    session.refresh(baseline)

    logger.info("Created baseline %d (%s) from server %s snapshot, provider_ref=%s",
                baseline.id, baseline.name, server.hostname, snapshot_ref)
    return baseline


# ---------------------------------------------------------------------------
# Baseline CRUD
# ---------------------------------------------------------------------------

@router.post("/baselines", response_model=BaselineResponse, status_code=status.HTTP_201_CREATED)
def create_baseline(data: BaselineCreate, session: Session = Depends(get_session)):
    obj = BaselineORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/baselines", response_model=List[BaselineResponse])
def list_baselines(session: Session = Depends(get_session)):
    return session.query(BaselineORM).all()


@router.get("/baselines/{baseline_id}", response_model=BaselineResponse)
def get_baseline(baseline_id: int, session: Session = Depends(get_session)):
    obj = session.get(BaselineORM, baseline_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return obj


@router.put("/baselines/{baseline_id}", response_model=BaselineResponse)
def update_baseline(baseline_id: int, data: BaselineUpdate, session: Session = Depends(get_session)):
    obj = session.get(BaselineORM, baseline_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Baseline not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_baseline(baseline_id: int, session: Session = Depends(get_session)):
    obj = session.get(BaselineORM, baseline_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Baseline not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# PackageGroup CRUD
# ---------------------------------------------------------------------------

@router.post("/package-groups", response_model=PackageGroupResponse, status_code=status.HTTP_201_CREATED)
def create_package_group(data: PackageGroupCreate, session: Session = Depends(get_session)):
    obj = PackageGroupORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/package-groups", response_model=List[PackageGroupResponse])
def list_package_groups(session: Session = Depends(get_session)):
    return session.query(PackageGroupORM).all()


@router.get("/package-groups/{group_id}", response_model=PackageGroupResponse)
def get_package_group(group_id: int, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupORM, group_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group not found")
    return obj


@router.put("/package-groups/{group_id}", response_model=PackageGroupResponse)
def update_package_group(group_id: int, data: PackageGroupUpdate, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupORM, group_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/package-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_package_group(group_id: int, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupORM, group_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# PackageGroupMember CRUD (nested under package group)
# ---------------------------------------------------------------------------

@router.post("/package-groups/{group_id}/members", response_model=PackageGroupMemberResponse, status_code=status.HTTP_201_CREATED)
def create_package_group_member(group_id: int, data: PackageGroupMemberCreate, session: Session = Depends(get_session)):
    if not session.get(PackageGroupORM, group_id):
        raise HTTPException(status_code=404, detail="Package group not found")
    obj = PackageGroupMemberORM(**data.model_dump())
    obj.package_group_id = group_id
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/package-groups/{group_id}/members", response_model=List[PackageGroupMemberResponse])
def list_package_group_members(group_id: int, session: Session = Depends(get_session)):
    return session.query(PackageGroupMemberORM).filter(
        PackageGroupMemberORM.package_group_id == group_id
    ).all()


@router.get("/package-group-members/{member_id}", response_model=PackageGroupMemberResponse)
def get_package_group_member(member_id: int, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupMemberORM, member_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group member not found")
    return obj


@router.put("/package-group-members/{member_id}", response_model=PackageGroupMemberResponse)
def update_package_group_member(member_id: int, data: PackageGroupMemberUpdate, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupMemberORM, member_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group member not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/package-group-members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_package_group_member(member_id: int, session: Session = Depends(get_session)):
    obj = session.get(PackageGroupMemberORM, member_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Package group member not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Scenario CRUD
# ---------------------------------------------------------------------------

@router.post("/scenarios", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
def create_scenario(data: ScenarioCreate, session: Session = Depends(get_session)):
    obj = ScenarioORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/scenarios", response_model=List[ScenarioResponse])
def list_scenarios(lab_id: int = None, session: Session = Depends(get_session)):
    q = session.query(ScenarioORM)
    if lab_id is not None:
        q = q.filter(ScenarioORM.lab_id == lab_id)
    return q.all()


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: int, session: Session = Depends(get_session)):
    obj = session.get(ScenarioORM, scenario_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return obj


@router.put("/scenarios/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(scenario_id: int, data: ScenarioUpdate, session: Session = Depends(get_session)):
    obj = session.get(ScenarioORM, scenario_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Scenario not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(scenario_id: int, session: Session = Depends(get_session)):
    obj = session.get(ScenarioORM, scenario_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Scenario not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# LoadProfile CRUD
# ---------------------------------------------------------------------------

@router.post("/load-profiles", response_model=LoadProfileResponse, status_code=status.HTTP_201_CREATED)
def create_load_profile(data: LoadProfileCreate, session: Session = Depends(get_session)):
    obj = LoadProfileORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/load-profiles", response_model=List[LoadProfileResponse])
def list_load_profiles(session: Session = Depends(get_session)):
    return session.query(LoadProfileORM).all()


@router.get("/load-profiles/{profile_id}", response_model=LoadProfileResponse)
def get_load_profile(profile_id: int, session: Session = Depends(get_session)):
    obj = session.get(LoadProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Load profile not found")
    return obj


@router.put("/load-profiles/{profile_id}", response_model=LoadProfileResponse)
def update_load_profile(profile_id: int, data: LoadProfileUpdate, session: Session = Depends(get_session)):
    obj = session.get(LoadProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Load profile not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/load-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_load_profile(profile_id: int, session: Session = Depends(get_session)):
    obj = session.get(LoadProfileORM, profile_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Load profile not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# DBSchemaConfig CRUD
# ---------------------------------------------------------------------------

@router.post("/db-schema-configs", response_model=DBSchemaConfigResponse, status_code=status.HTTP_201_CREATED)
def create_db_schema_config(data: DBSchemaConfigCreate, session: Session = Depends(get_session)):
    obj = DBSchemaConfigORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/db-schema-configs", response_model=List[DBSchemaConfigResponse])
def list_db_schema_configs(session: Session = Depends(get_session)):
    return session.query(DBSchemaConfigORM).all()


@router.get("/db-schema-configs/{config_id}", response_model=DBSchemaConfigResponse)
def get_db_schema_config(config_id: int, session: Session = Depends(get_session)):
    obj = session.get(DBSchemaConfigORM, config_id)
    if not obj:
        raise HTTPException(status_code=404, detail="DB schema config not found")
    return obj


@router.put("/db-schema-configs/{config_id}", response_model=DBSchemaConfigResponse)
def update_db_schema_config(config_id: int, data: DBSchemaConfigUpdate, session: Session = Depends(get_session)):
    obj = session.get(DBSchemaConfigORM, config_id)
    if not obj:
        raise HTTPException(status_code=404, detail="DB schema config not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/db-schema-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_db_schema_config(config_id: int, session: Session = Depends(get_session)):
    obj = session.get(DBSchemaConfigORM, config_id)
    if not obj:
        raise HTTPException(status_code=404, detail="DB schema config not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# User Management CRUD (admin manages users)
# ---------------------------------------------------------------------------

@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, session: Session = Depends(get_session)):
    obj = UserORM(
        username=data.username,
        password_hash=hash_password(data.password),
        email=data.email,
        role=data.role,
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/users", response_model=List[UserResponse])
def list_users(session: Session = Depends(get_session)):
    return session.query(UserORM).all()


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, session: Session = Depends(get_session)):
    obj = session.get(UserORM, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="User not found")
    return obj


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, data: UserUpdate, session: Session = Depends(get_session)):
    obj = session.get(UserORM, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = data.model_dump(exclude_unset=True)
    if "password" in update_data:
        obj.password_hash = hash_password(update_data.pop("password"))
    for field_name, value in update_data.items():
        setattr(obj, field_name, value)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, session: Session = Depends(get_session)):
    obj = session.get(UserORM, user_id)
    if not obj:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(data: AgentCreate, session: Session = Depends(get_session)):
    obj = AgentORM(**data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.get("/agents", response_model=List[AgentResponse])
def list_agents(session: Session = Depends(get_session)):
    return session.query(AgentORM).all()


@router.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int, session: Session = Depends(get_session)):
    obj = session.get(AgentORM, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    return obj


@router.put("/agents/{agent_id}", response_model=AgentResponse)
def update_agent(agent_id: int, data: AgentUpdate, session: Session = Depends(get_session)):
    obj = session.get(AgentORM, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, session: Session = Depends(get_session)):
    obj = session.get(AgentORM, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Analysis Rules (nested under agent)
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/rules", response_model=List[AnalysisRuleResponse])
def list_agent_rules(agent_id: int, session: Session = Depends(get_session)):
    if not session.get(AgentORM, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return session.query(AnalysisRuleORM).filter(
        AnalysisRuleORM.agent_id == agent_id
    ).all()


@router.post("/agents/{agent_id}/rules", response_model=AnalysisRuleResponse, status_code=status.HTTP_201_CREATED)
def create_agent_rule(agent_id: int, data: AnalysisRuleCreate, session: Session = Depends(get_session)):
    if not session.get(AgentORM, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    if data.rule_template_key not in RULE_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown rule template: {data.rule_template_key}")
    obj = AnalysisRuleORM(agent_id=agent_id, **data.model_dump())
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


@router.put("/agent-rules/{rule_id}", response_model=AnalysisRuleResponse)
def update_agent_rule(rule_id: int, data: AnalysisRuleUpdate, session: Session = Depends(get_session)):
    obj = session.get(AnalysisRuleORM, rule_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Analysis rule not found")
    _apply_update(obj, data)
    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/agent-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_rule(rule_id: int, session: Session = Depends(get_session)):
    obj = session.get(AnalysisRuleORM, rule_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Analysis rule not found")
    session.delete(obj)
    session.commit()


# ---------------------------------------------------------------------------
# Preset Application
# ---------------------------------------------------------------------------

@router.post("/agents/{agent_id}/apply-preset", response_model=dict)
def apply_agent_preset(agent_id: int, data: ApplyPresetRequest, session: Session = Depends(get_session)):
    if not session.get(AgentORM, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    count = apply_preset(session, agent_id, data.preset_key)
    return {"message": f"Applied {data.preset_key} preset: {count} rules created"}


# ---------------------------------------------------------------------------
# Rule Templates & Presets (read-only catalog)
# ---------------------------------------------------------------------------

@router.get("/rule-templates", response_model=List[RuleTemplateResponse])
def list_rule_templates():
    return [
        RuleTemplateResponse(
            key=t.key, name=t.name, category=t.category,
            description=t.description, data_source=t.data_source,
            metric=t.metric, statistic=t.statistic,
            comparison_mode=t.comparison_mode, operator=t.operator,
            unit=t.unit, default_threshold=t.default_threshold,
        )
        for t in RULE_TEMPLATES.values()
    ]


@router.get("/rule-presets", response_model=List[RulePresetResponse])
def list_rule_presets():
    return [
        RulePresetResponse(
            key=p.key, name=p.name, description=p.description,
            rules=[{"template_key": r.template_key, "threshold": r.threshold, "severity": r.severity}
                   for r in p.rules],
        )
        for p in RULE_PRESETS.values()
    ]


# ---------------------------------------------------------------------------
# Scenario-Agent Linkage
# ---------------------------------------------------------------------------

@router.get("/scenarios/{scenario_id}/agents", response_model=List[AgentResponse])
def list_scenario_agents(scenario_id: int, session: Session = Depends(get_session)):
    scenario = session.get(ScenarioORM, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    links = session.query(ScenarioAgentORM).filter(
        ScenarioAgentORM.scenario_id == scenario_id
    ).all()
    agent_ids = [link.agent_id for link in links]
    if not agent_ids:
        return []
    return session.query(AgentORM).filter(AgentORM.id.in_(agent_ids)).all()


@router.post("/scenarios/{scenario_id}/agents/{agent_id}", status_code=status.HTTP_201_CREATED)
def link_scenario_agent(scenario_id: int, agent_id: int, session: Session = Depends(get_session)):
    if not session.get(ScenarioORM, scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    if not session.get(AgentORM, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    existing = session.query(ScenarioAgentORM).filter(
        ScenarioAgentORM.scenario_id == scenario_id,
        ScenarioAgentORM.agent_id == agent_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Agent already linked to scenario")
    session.add(ScenarioAgentORM(scenario_id=scenario_id, agent_id=agent_id))
    session.commit()
    return {"message": "Agent linked to scenario"}


@router.delete("/scenarios/{scenario_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_scenario_agent(scenario_id: int, agent_id: int, session: Session = Depends(get_session)):
    link = session.query(ScenarioAgentORM).filter(
        ScenarioAgentORM.scenario_id == scenario_id,
        ScenarioAgentORM.agent_id == agent_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Agent-scenario link not found")
    session.delete(link)
    session.commit()
