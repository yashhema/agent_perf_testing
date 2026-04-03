"""Admin CRUD API routers for all configuration entities.

All endpoints require admin role. Standard pattern:
  POST   /api/admin/{entity}       — create
  GET    /api/admin/{entity}       — list all
  GET    /api/admin/{entity}/{id}  — get by id
  PUT    /api/admin/{entity}/{id}  — update
  DELETE /api/admin/{entity}/{id}  — delete
"""

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
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
    AgentDetectionRuleCreate, AgentDetectionRuleResponse, AgentDetectionRuleUpdate,
    SubgroupDefinitionCreate, SubgroupDefinitionResponse, SubgroupDefinitionUpdate,
    UserCreate, UserResponse, UserUpdate,
)
from orchestrator.models.database import SessionLocal, get_session
from orchestrator.models.orm import (
    AgentORM, AnalysisRuleORM,
    BaselineORM, DBSchemaConfigORM, HardwareProfileORM, LabORM,
    LoadProfileORM, PackageGroupMemberORM, PackageGroupORM,
    AgentDetectionRuleORM,
    ScenarioAgentORM, ScenarioORM, ServerORM,
    SnapshotBaselineORM, SnapshotGroupORM, SnapshotORM,
    SubgroupAgentORM, SubgroupDefinitionORM, UserORM,
)
from orchestrator.models.enums import ServerRole

logger = logging.getLogger(__name__)

# In-memory status tracking for prepare-snapshot operations
_prepare_status: Dict[int, Dict[str, Any]] = {}
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
    servers = q.all()
    return [_enrich_server_response(s, session) for s in servers]


@router.get("/servers/{server_id}", response_model=ServerResponse)
def get_server(server_id: int, session: Session = Depends(get_session)):
    obj = session.get(ServerORM, server_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Server not found")
    return _enrich_server_response(obj, session)


def _enrich_server_response(server: ServerORM, session: Session) -> ServerResponse:
    """Add computed fields (subgroup_count, is_ready) to server response."""
    # Count subgroups across all groups for this server
    sg_count = session.query(SnapshotGroupORM).join(
        SnapshotBaselineORM, SnapshotGroupORM.baseline_id == SnapshotBaselineORM.id,
    ).filter(
        SnapshotBaselineORM.server_id == server.id,
    ).count()

    resp = ServerResponse.model_validate(server)
    resp.subgroup_count = sg_count
    # Server is ready for testing when it has root snapshot + at least 1 subgroup
    resp.is_ready = bool(server.root_snapshot_id and sg_count > 0)
    return resp


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
# Server Prepare & Snapshot — full prep flow with optional cleanup
# ---------------------------------------------------------------------------

class PrepareSnapshotRequest(BaseModel):
    delete_all_snapshots: bool = False


@router.post("/servers/{server_id}/prepare-snapshot")
def prepare_and_snapshot(
    server_id: int,
    data: PrepareSnapshotRequest,
    session: Session = Depends(get_session),
):
    """Start background prepare-and-snapshot flow for a server.

    Steps: (optionally delete snapshots) → detect OS → fix sudo → firewall →
    java 17 → /data disk → take snapshot → create group.
    """
    server = session.get(ServerORM, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Check not already running
    current = _prepare_status.get(server_id, {})
    if current.get("state") == "preparing":
        raise HTTPException(status_code=409, detail="Prepare already in progress for this server")

    _prepare_status[server_id] = {
        "state": "preparing", "step": "0/8", "step_name": "Starting...", "error": None,
    }

    thread = threading.Thread(
        target=_prepare_snapshot_bg,
        args=(server_id, data.delete_all_snapshots),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "server_id": server_id}


@router.get("/servers/{server_id}/prepare-status")
def get_prepare_status(server_id: int):
    """Poll prepare-snapshot progress."""
    return _prepare_status.get(server_id, {"state": "idle", "step": None, "step_name": None, "error": None})


def _update_status(server_id: int, step: str, step_name: str, state: str = "preparing", error: str = None):
    _prepare_status[server_id] = {"state": state, "step": step, "step_name": step_name, "error": error}


def _prepare_snapshot_bg(server_id: int, delete_all: bool):
    """Background thread: full prepare + snapshot flow."""
    TOTAL = 9
    session = SessionLocal()

    try:
        from orchestrator.config.settings import load_config
        from orchestrator.config.credentials import CredentialsStore
        from orchestrator.infra.hypervisor import create_hypervisor_provider
        from orchestrator.infra.remote_executor import create_executor
        from orchestrator.core.baseline_execution import wait_for_ssh
        import os, re, time

        server = session.get(ServerORM, server_id)
        lab = session.get(LabORM, server.lab_id)
        os_family = server.os_family.value

        # Load config and credentials
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))), "config", "orchestrator.yaml")
        config = load_config(config_path)
        cred_path = os.path.join(os.path.dirname(config_path), "credentials.json")
        credentials = CredentialsStore(cred_path)

        # Get sudo user from credentials
        cred = credentials.get_server_credential(server.id, os_family)
        if not cred:
            raise RuntimeError(f"No credentials found for server {server.hostname} (id={server.id})")
        sudo_user = cred.username

        hyp_cred = credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        # --- Step 1: Delete all snapshots (optional) ---
        _update_status(server_id, f"1/{TOTAL}", "Cleaning snapshots..." if delete_all else "Skipping snapshot cleanup")
        if delete_all:
            # Revert to root if exists
            if server.root_snapshot_id:
                root_snap = session.get(SnapshotORM, server.root_snapshot_id)
                if root_snap and not root_snap.is_archived:
                    try:
                        provider.restore_snapshot(server.server_infra_ref, root_snap.provider_ref)
                        provider.wait_for_vm_ready(server.server_infra_ref)
                    except Exception as e:
                        logger.warning("Revert to root failed: %s — continuing", e)

            # Delete all snapshots from hypervisor (leaf-first)
            all_snaps = provider.list_snapshots(server.server_infra_ref)
            # Build leaf-first order
            remaining = {s.id for s in all_snaps}
            snap_by_id = {s.id: s for s in all_snaps}
            children_of = {}
            for s in all_snaps:
                children_of.setdefault(s.parent, []).append(s)

            ordered = []
            for _ in range(len(all_snaps) + 1):
                if not remaining:
                    break
                leaves = [sid for sid in remaining
                          if not any(c.id in remaining for c in children_of.get(sid, []))]
                if not leaves:
                    ordered.extend(remaining)
                    break
                ordered.extend(leaves)
                remaining -= set(leaves)

            for snap_id in ordered:
                snap = snap_by_id.get(snap_id)
                if snap:
                    try:
                        infra_type = server.server_infra_type.value
                        if infra_type == "vsphere_vm":
                            ref = {"snapshot_name": snap.name, "snapshot_moref_id": snap.id}
                        elif infra_type == "proxmox_vm":
                            ref = {"snapshot_name": snap.id}
                        else:
                            ref = {"snapshot_id": snap.id, "snapshot_name": snap.name}
                        provider.delete_snapshot(server.server_infra_ref, ref)
                        time.sleep(1)
                    except Exception as e:
                        logger.warning("Failed to delete snapshot %s: %s", snap.name, e)

            # Clean DB records — delete everything, not just archive
            # First clear FKs on server that reference snapshots
            server.root_snapshot_id = None
            server.clean_snapshot_id = None
            session.flush()

            # Delete groups (cascade deletes subgroups via ORM relationship)
            groups = session.query(SnapshotBaselineORM).filter(
                SnapshotBaselineORM.server_id == server_id,
            ).all()
            for g in groups:
                session.delete(g)
            session.flush()

            # Delete all snapshot records for this server (not archive — full delete)
            from orchestrator.models.orm import SnapshotProfileDataORM
            session.query(SnapshotProfileDataORM).filter(
                SnapshotProfileDataORM.snapshot_id.in_(
                    session.query(SnapshotORM.id).filter(SnapshotORM.server_id == server_id)
                )
            ).delete(synchronize_session='fetch')
            session.query(SnapshotORM).filter(
                SnapshotORM.server_id == server_id,
            ).delete(synchronize_session='fetch')
            session.commit()
            logger.info("Cleaned all DB records for server %d", server_id)

            # Verify hypervisor is clean
            remaining = provider.list_snapshots(server.server_infra_ref)
            if remaining:
                logger.warning("Hypervisor still has %d snapshots after cleanup for server %d",
                               len(remaining), server_id)

        # --- Step 2: Wait for SSH ---
        _update_status(server_id, f"2/{TOTAL}", "Waiting for SSH...")
        wait_for_ssh(server.ip_address, os_family=os_family, timeout_sec=120)

        # Create executor
        cred = credentials.get_server_credential(server.id, os_family)
        executor = create_executor(
            os_family=os_family,
            host=server.ip_address,
            username=cred.username,
            password=cred.password,
        )

        try:
            # --- Step 3: Detect OS info ---
            _update_status(server_id, f"3/{TOTAL}", "Detecting OS info...")
            if os_family == "linux":
                result = executor.execute("cat /etc/os-release 2>/dev/null | grep -E '^(ID|VERSION_ID)='")
                os_info = {}
                for line in result.stdout.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        os_info[k.strip()] = v.strip().strip('"')
                vendor = os_info.get("ID", "").lower()  # rhel, rocky, ubuntu
                version_id = os_info.get("VERSION_ID", "")
                parts = version_id.split(".")
                major = parts[0] if parts else ""
                minor = parts[1] if len(parts) > 1 else ""
            else:
                result = executor.execute(
                    'powershell -Command "'
                    "$os = Get-CimInstance Win32_OperatingSystem; "
                    'Write-Host $os.Caption; Write-Host $os.Version"'
                )
                lines = result.stdout.strip().splitlines()
                caption = lines[0] if lines else ""
                ver = lines[1] if len(lines) > 1 else ""
                # Extract vendor from caption
                vendor = "windows_server"
                if "2022" in caption:
                    major = "2022"
                elif "2019" in caption:
                    major = "2019"
                elif "2016" in caption:
                    major = "2016"
                else:
                    major = ver.split(".")[0] if ver else ""
                minor = ""

            # Update server OS fields
            if vendor:
                server.os_vendor_family = vendor
            if major:
                server.os_major_ver = major
            if minor:
                server.os_minor_ver = minor
            session.commit()
            logger.info("OS detected: vendor=%s major=%s minor=%s", vendor, major, minor)

            # --- Step 4: Fix sudo ---
            _update_status(server_id, f"4/{TOTAL}", "Fixing passwordless sudo...")
            _fix_sudo_inline(executor, cred.password, sudo_user, os_family)

            # --- Step 5: Open firewall ---
            _update_status(server_id, f"5/{TOTAL}", "Opening firewall port 8080...")
            _open_firewall_inline(executor, os_family)

            # --- Step 6: Install prerequisites ---
            _update_status(server_id, f"6/{TOTAL}", "Installing Java 17...")
            _install_prereqs_inline(executor, os_family)

            # --- Step 7: Setup data disk ---
            _update_status(server_id, f"7/{TOTAL}", "Setting up /data disk...")
            _setup_data_disk_inline(executor, os_family, cred.username)

            # --- Step 8: Cleanup (kill processes, clean emulator/jmeter dirs) ---
            _update_status(server_id, f"8/{TOTAL}", "Cleaning up processes and directories...")
            _cleanup_server_inline(executor, os_family, server.role.value)

        finally:
            executor.close()

        # --- Step 9: Take snapshot ---
        _update_status(server_id, f"9/{TOTAL}", "Taking root snapshot...")
        os_label = f"{vendor}{major}" if vendor else os_family
        snap_name = f"root-{server.hostname}-{os_label}-{datetime.utcnow().strftime('%Y%m%d')}"
        description = f"Root snapshot — prepared {datetime.utcnow().strftime('%Y-%m-%d')}"

        result = provider.create_snapshot(
            server.server_infra_ref,
            snapshot_name=snap_name,
            description=description,
        )
        new_provider_id = (
            result.get("snapshot_moref_id")
            or result.get("snapshot_id")
            or result.get("snapshot_name")
        )

        # Create DB records
        snapshot_tree = [s.to_dict() for s in provider.list_snapshots(server.server_infra_ref)]
        snap_orm = SnapshotORM(
            name=snap_name,
            description=description,
            server_id=server.id,
            parent_id=None,
            group_id=None,
            provider_snapshot_id=str(new_provider_id),
            provider_ref=result,
            snapshot_tree=snapshot_tree,
            is_baseline=True,
            is_archived=False,
        )
        session.add(snap_orm)
        session.flush()

        server.root_snapshot_id = snap_orm.id
        server.clean_snapshot_id = snap_orm.id

        # Create group + default subgroup
        group_name = f"Clean OS {server.hostname}"
        group_orm = SnapshotBaselineORM(
            server_id=server.id,
            snapshot_id=snap_orm.id,
            name=group_name,
            description=description,
        )
        session.add(group_orm)
        session.flush()

        default_sg = SnapshotGroupORM(
            baseline_id=group_orm.id,
            snapshot_id=snap_orm.id,
            name="Default",
            description="Auto-created default subgroup",
        )
        session.add(default_sg)
        session.flush()
        snap_orm.group_id = default_sg.id

        session.commit()
        logger.info("Server %s prepared. Snapshot: %s (ID=%d), Group: %s (ID=%d)",
                     server.hostname, snap_name, snap_orm.id, group_name, group_orm.id)

        _update_status(server_id, f"{TOTAL}/{TOTAL}", "Complete", state="completed")

    except Exception as e:
        logger.error("Prepare-snapshot failed for server %d: %s", server_id, e, exc_info=True)
        _update_status(server_id, "", str(e), state="failed", error=str(e))
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Inline helper functions for prepare flow (reuse retake_snapshots logic)
# ---------------------------------------------------------------------------

def _fix_sudo_inline(executor, password, sudo_user, os_family):
    if os_family == "windows":
        return
    sudoers_file = sudo_user.replace("\\", "_").replace("@", "_")
    SUDO_S = f"echo '{password}' | sudo -S"
    executor.execute(f"{SUDO_S} bash -c \"echo '{sudo_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{sudoers_file}\" 2>&1")
    executor.execute(f"{SUDO_S} chmod 440 /etc/sudoers.d/{sudoers_file} 2>&1")
    executor.execute(f"{SUDO_S} visudo -cf /etc/sudoers.d/{sudoers_file} 2>&1")
    result = executor.execute("sudo -n whoami 2>&1")
    if "root" not in result.stdout:
        raise RuntimeError(f"Passwordless sudo not working after fix: {result.stdout}")


def _open_firewall_inline(executor, os_family, port=8080):
    if os_family == "windows":
        executor.execute(
            f'powershell -Command "New-NetFirewallRule -DisplayName \'Emulator {port}\' '
            f'-Direction Inbound -Port {port} -Protocol TCP -Action Allow -ErrorAction SilentlyContinue"'
        )
    else:
        executor.execute(
            f"sudo firewall-cmd --permanent --add-port={port}/tcp 2>/dev/null && "
            f"sudo firewall-cmd --reload 2>/dev/null || "
            f"sudo iptables -C INPUT -p tcp --dport {port} -j ACCEPT 2>/dev/null || "
            f"sudo iptables -I INPUT -p tcp --dport {port} -j ACCEPT"
        )


def _install_prereqs_inline(executor, os_family):
    import re
    if os_family == "windows":
        # Check Java 17 on Windows
        result = executor.execute('powershell -Command "try { java -version 2>&1 | Out-String } catch { Write-Host NOTFOUND }"')
        if result.stdout and "NOTFOUND" not in result.stdout:
            m = re.search(r'"(1[7-9]|[2-9]\d)', result.stdout)
            if m:
                return  # Java 17+ already installed
        logger.warning("Java 17 not found on Windows — manual install may be needed")
        return
    # Linux: install Java 17
    result = executor.execute("java -version 2>&1 | head -1")
    if result.stdout:
        m = re.search(r'"(\d+)', result.stdout)
        if m and int(m.group(1)) >= 17:
            return  # Already have Java 17+
    executor.execute("sudo dnf install -y java-17-openjdk-headless 2>&1 || sudo yum install -y java-17-openjdk-headless 2>&1")
    executor.execute(
        "sudo alternatives --set java $(find /usr/lib/jvm/java-17-openjdk-*/bin/java -maxdepth 0 2>/dev/null | head -1) 2>&1"
    )
    # Python3
    executor.execute("python3 --version 2>&1 || sudo dnf install -y python3 python3-pip 2>&1")


def _cleanup_server_inline(executor, os_family, role):
    """Kill processes and clean emulator/jmeter directories."""
    if os_family == "windows":
        executor.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
        executor.execute('powershell -Command "Stop-Process -Name *jmeter* -Force -ErrorAction SilentlyContinue"')
        executor.execute('powershell -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue \'C:\\emulator\\output\\*\'"')
        executor.execute('powershell -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue \'C:\\emulator\\stats\\*\'"')
        return

    # Linux: kill processes
    executor.execute("pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; echo done")
    executor.execute("pgrep -f '[j]meter' | xargs -r kill -9 2>/dev/null; echo done")

    # Disable emulator service if exists
    executor.execute("sudo systemctl stop emulator 2>/dev/null; sudo systemctl disable emulator 2>/dev/null; echo done")

    # Clean directories
    executor.execute("sudo rm -rf /data/emulator/output/* /data/emulator/stats/* 2>/dev/null; echo done")
    executor.execute("sudo rm -rf /data/jmeter /data/jmeter-pkg 2>/dev/null; echo done")
    executor.execute("sudo rm -rf /data/emulator /data/emulator-pkg 2>/dev/null; echo done")
    executor.execute("sudo rm -rf /tmp/jmeter* /tmp/emulator* 2>/dev/null; echo done")

    import time
    time.sleep(2)

    # Verify clean
    result = executor.execute("ls /data/emulator/output/ 2>/dev/null | head -5; ls /data/emulator/stats/ 2>/dev/null | head -5")
    if result.stdout.strip():
        logger.warning("Cleanup may be incomplete: %s", result.stdout.strip()[:200])


def _setup_data_disk_inline(executor, os_family, ssh_user, disk="/dev/sdc", mount="/data"):
    if os_family == "windows":
        return
    # Check disk exists
    result = executor.execute(f"lsblk {disk} 2>&1 | head -2")
    if not result.success:
        raise RuntimeError(f"{disk} not found — cannot setup data disk")
    # Check if already mounted
    result = executor.execute(f"mountpoint -q {mount} 2>/dev/null && echo MOUNTED || echo NOTMOUNTED")
    if "NOTMOUNTED" in result.stdout:
        # Check filesystem
        result = executor.execute(f"sudo file -s {disk} 2>&1")
        if ": data" in result.stdout:
            executor.execute(f"sudo mkfs.ext4 -F {disk} 2>&1")
        executor.execute(f"sudo mkdir -p {mount}")
        executor.execute(f"sudo mount {disk} {mount} 2>&1")
        executor.execute(f"grep -q '{disk}' /etc/fstab || echo '{disk} {mount} ext4 defaults 0 2' | sudo tee -a /etc/fstab")
    # Create output folders + chown
    for folder in [f"{mount}/output1", f"{mount}/output2", f"{mount}/output3"]:
        executor.execute(f"sudo mkdir -p {folder}")
    executor.execute(f"sudo chown -R {ssh_user} {mount}")
    executor.execute(f"sudo chmod -R 755 {mount}")


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
# Agent Detection Rules
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/detection-rules", response_model=List[AgentDetectionRuleResponse])
def list_detection_rules(agent_id: int, session: Session = Depends(get_session)):
    agent = session.get(AgentORM, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return session.query(AgentDetectionRuleORM).filter(
        AgentDetectionRuleORM.agent_id == agent_id,
    ).all()


@router.post("/agents/{agent_id}/detection-rules", response_model=AgentDetectionRuleResponse, status_code=status.HTTP_201_CREATED)
def create_detection_rule(agent_id: int, data: AgentDetectionRuleCreate, session: Session = Depends(get_session)):
    agent = session.get(AgentORM, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if data.cmd_type not in ("bash", "powershell"):
        raise HTTPException(status_code=400, detail="cmd_type must be 'bash' or 'powershell'")
    rule = AgentDetectionRuleORM(
        agent_id=agent_id,
        os_regex=data.os_regex,
        cmd_type=data.cmd_type,
        service_regex=data.service_regex,
        version_cmd=data.version_cmd,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.put("/agent-detection-rules/{rule_id}", response_model=AgentDetectionRuleResponse)
def update_detection_rule(rule_id: int, data: AgentDetectionRuleUpdate, session: Session = Depends(get_session)):
    rule = session.get(AgentDetectionRuleORM, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Detection rule not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    if rule.cmd_type not in ("bash", "powershell"):
        raise HTTPException(status_code=400, detail="cmd_type must be 'bash' or 'powershell'")
    session.commit()
    session.refresh(rule)
    return rule


@router.delete("/agent-detection-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_detection_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(AgentDetectionRuleORM, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Detection rule not found")
    session.delete(rule)
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


# ---------------------------------------------------------------------------
# Subgroup Definition CRUD
# ---------------------------------------------------------------------------

def _build_subgroup_response(sg_def, session):
    """Build SubgroupDefinitionResponse with agent names."""
    agents = []
    for sa in sg_def.agents:
        agent = session.get(AgentORM, sa.agent_id)
        agents.append({
            "id": sa.id,
            "agent_id": sa.agent_id,
            "agent_name": agent.name if agent else None,
        })
    return {
        "id": sg_def.id,
        "name": sg_def.name,
        "description": sg_def.description,
        "agents": agents,
        "created_at": sg_def.created_at,
    }


@router.post("/subgroup-definitions", response_model=SubgroupDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_subgroup_definition(data: SubgroupDefinitionCreate, session: Session = Depends(get_session)):
    sg_def = SubgroupDefinitionORM(name=data.name, description=data.description)
    session.add(sg_def)
    session.flush()
    for aid in data.agent_ids:
        agent = session.get(AgentORM, aid)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {aid} not found")
        session.add(SubgroupAgentORM(subgroup_def_id=sg_def.id, agent_id=aid))
    session.commit()
    session.refresh(sg_def)
    return _build_subgroup_response(sg_def, session)


@router.get("/subgroup-definitions", response_model=List[SubgroupDefinitionResponse])
def list_subgroup_definitions(session: Session = Depends(get_session)):
    defs = session.query(SubgroupDefinitionORM).order_by(SubgroupDefinitionORM.name).all()
    return [_build_subgroup_response(d, session) for d in defs]


@router.get("/subgroup-definitions/{sg_id}", response_model=SubgroupDefinitionResponse)
def get_subgroup_definition(sg_id: int, session: Session = Depends(get_session)):
    sg_def = session.get(SubgroupDefinitionORM, sg_id)
    if not sg_def:
        raise HTTPException(status_code=404, detail="Subgroup definition not found")
    return _build_subgroup_response(sg_def, session)


@router.put("/subgroup-definitions/{sg_id}", response_model=SubgroupDefinitionResponse)
def update_subgroup_definition(sg_id: int, data: SubgroupDefinitionUpdate, session: Session = Depends(get_session)):
    sg_def = session.get(SubgroupDefinitionORM, sg_id)
    if not sg_def:
        raise HTTPException(status_code=404, detail="Subgroup definition not found")
    if data.name is not None:
        sg_def.name = data.name
    if data.description is not None:
        sg_def.description = data.description
    if data.agent_ids is not None:
        # Replace all agent links
        session.query(SubgroupAgentORM).filter(
            SubgroupAgentORM.subgroup_def_id == sg_id,
        ).delete()
        for aid in data.agent_ids:
            agent = session.get(AgentORM, aid)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent {aid} not found")
            session.add(SubgroupAgentORM(subgroup_def_id=sg_id, agent_id=aid))
    session.commit()
    session.refresh(sg_def)
    return _build_subgroup_response(sg_def, session)


@router.delete("/subgroup-definitions/{sg_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subgroup_definition(sg_id: int, session: Session = Depends(get_session)):
    sg_def = session.get(SubgroupDefinitionORM, sg_id)
    if not sg_def:
        raise HTTPException(status_code=404, detail="Subgroup definition not found")
    session.delete(sg_def)
    session.commit()
