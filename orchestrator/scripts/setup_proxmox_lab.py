"""Setup script for the Proxmox lab environment.

Creates all database tables, seeds default data, and inserts
the 4-server Proxmox lab configuration.

Database: SQL Server 'orchestrator' on localhost (trusted connection).

Usage:
    cd orchestrator
    python scripts/setup_proxmox_lab.py
"""

import json
import sys
import os

# Add src to path so we can import orchestrator modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text
from sqlalchemy.orm import Session

from orchestrator.config.settings import load_config
from orchestrator.models.database import Base, init_db, SessionLocal
from orchestrator.models.enums import (
    BaselineType,
    DiskType,
    ExecutionMode,
    HypervisorType,
    OSFamily,
    ServerInfraType,
    TemplateType,
)
from orchestrator.models.orm import (
    BaselineORM,
    HardwareProfileORM,
    LabORM,
    PackageGroupMemberORM,
    PackageGroupORM,
    ScenarioORM,
    ServerORM,
    SnapshotORM,
)
from orchestrator.seed import seed_all


DB_URL = (
    "mssql+pyodbc://@localhost/orchestrator"
    "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)


def create_tables():
    """Create all tables from ORM models and run pending migrations."""
    print("[1/3] Creating/updating tables...")
    bind = SessionLocal().get_bind()
    Base.metadata.create_all(bind=bind)
    print("      Base tables created (or already exist).")

    # Run migration for snapshot_groups columns on existing snapshots table
    # create_all won't add columns to existing tables, so we do it manually
    with bind.connect() as conn:
        # Add group_id column
        result = conn.execute(text(
            "SELECT 1 FROM sys.columns "
            "WHERE object_id = OBJECT_ID('snapshots') AND name = 'group_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE snapshots ADD group_id INT NULL"))
            conn.execute(text(
                "ALTER TABLE snapshots ADD CONSTRAINT FK_snapshots_group "
                "FOREIGN KEY (group_id) REFERENCES snapshot_groups(id)"
            ))
            conn.commit()
            print("      Added group_id column to snapshots")

        # Add snapshot_tree column
        result = conn.execute(text(
            "SELECT 1 FROM sys.columns "
            "WHERE object_id = OBJECT_ID('snapshots') AND name = 'snapshot_tree'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE snapshots ADD snapshot_tree NVARCHAR(MAX) NULL"))
            conn.commit()
            print("      Added snapshot_tree column to snapshots")

        # Add snapshot_id to snapshot_groups (subgroup's own snapshot)
        result = conn.execute(text(
            "SELECT 1 FROM sys.columns "
            "WHERE object_id = OBJECT_ID('snapshot_groups') AND name = 'snapshot_id'"
        ))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE snapshot_groups ADD snapshot_id INT NULL"))
            conn.execute(text(
                "ALTER TABLE snapshot_groups ADD CONSTRAINT FK_sg_snapshot "
                "FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)"
            ))
            conn.commit()
            print("      Added snapshot_id column to snapshot_groups")

    print("      Schema up to date.")


def run_seeds(session: Session):
    """Run standard seed data: admin user, load profiles, sample agent."""
    print("[2/3] Seeding default data...")
    seed_all(session)
    print("      Seed data ready.")


def _ensure_package_member(session: Session, group: PackageGroupORM, os_regex: str, fields: dict):
    """Create a PackageGroupMemberORM if it doesn't already exist for this group+os."""
    existing = session.query(PackageGroupMemberORM).filter_by(
        package_group_id=group.id, os_match_regex=os_regex,
    ).first()
    if existing:
        return existing
    member = PackageGroupMemberORM(
        package_group_id=group.id,
        os_match_regex=os_regex,
        path=fields["path"],
        root_install_path=fields["root_install_path"],
        extraction_command=fields.get("extraction_command"),
        install_command=fields.get("install_command"),
        run_command=fields.get("run_command"),
        status_command=fields.get("status_command"),
        uninstall_command=fields.get("uninstall_command"),
        prereq_script=fields.get("prereq_script"),
    )
    session.add(member)
    session.flush()
    print("      Created package member: %s [%s]" % (group.name, os_regex))
    return member


def insert_proxmox_lab(session: Session):
    """Insert the Proxmox lab: hardware profiles, baselines, lab, servers, scenario, snapshots."""
    print("[3/3] Inserting Proxmox lab data...")

    # --- Hardware Profiles ---
    hp1 = session.query(HardwareProfileORM).filter_by(name="Proxmox-4c-8g-40g").first()
    if not hp1:
        hp1 = HardwareProfileORM(
            name="Proxmox-4c-8g-40g",
            cpu_count=4, cpu_model="host (QEMU)", memory_gb=8.0,
            disk_type=DiskType.ssd, disk_size_gb=40.0,
            nic_speed_mbps=1000, vendor="Proxmox VE",
        )
        session.add(hp1)
        session.flush()
        print("      Created hardware profile: Proxmox-4c-8g-40g")

    hp2 = session.query(HardwareProfileORM).filter_by(name="Proxmox-4c-8g-60g").first()
    if not hp2:
        hp2 = HardwareProfileORM(
            name="Proxmox-4c-8g-60g",
            cpu_count=4, cpu_model="host (QEMU)", memory_gb=8.0,
            disk_type=DiskType.ssd, disk_size_gb=60.0,
            nic_speed_mbps=1000, vendor="Proxmox VE",
        )
        session.add(hp2)
        session.flush()
        print("      Created hardware profile: Proxmox-4c-8g-60g")

    # --- OS Baselines (provider_ref for snapshot restore) ---
    bl_rocky = session.query(BaselineORM).filter_by(name="Rocky 9.7 Clean").first()
    if not bl_rocky:
        bl_rocky = BaselineORM(
            name="Rocky 9.7 Clean",
            os_family=OSFamily.linux, os_vendor_family="rhel",
            os_major_ver="9", os_minor_ver="7",
            baseline_type=BaselineType.proxmox,
            provider_ref={"snapshot_name": "clean-rocky97"},
        )
        session.add(bl_rocky)
        session.flush()
        print("      Created baseline: Rocky 9.7 Clean")

    bl_win = session.query(BaselineORM).filter_by(name="Win 2022 Clean").first()
    if not bl_win:
        bl_win = BaselineORM(
            name="Win 2022 Clean",
            os_family=OSFamily.windows, os_vendor_family="windows",
            os_major_ver="2022", os_minor_ver=None,
            baseline_type=BaselineType.proxmox,
            provider_ref={"snapshot_name": "clean-win2022"},
        )
        session.add(bl_win)
        session.flush()
        print("      Created baseline: Win 2022 Clean")

    bl_loadgen = session.query(BaselineORM).filter_by(name="Rocky 9.7 LoadGen").first()
    if not bl_loadgen:
        bl_loadgen = BaselineORM(
            name="Rocky 9.7 LoadGen",
            os_family=OSFamily.linux, os_vendor_family="rhel",
            os_major_ver="9", os_minor_ver="7",
            baseline_type=BaselineType.proxmox,
            provider_ref={"snapshot_name": "clean-loadgen"},
        )
        session.add(bl_loadgen)
        session.flush()
        print("      Created baseline: Rocky 9.7 LoadGen")

    # --- Package Groups + Members ---
    pg_jmeter = session.query(PackageGroupORM).filter_by(name="jmeter-5.6.3").first()
    if not pg_jmeter:
        pg_jmeter = PackageGroupORM(
            name="jmeter-5.6.3",
            description="Apache JMeter 5.6.3 load generator",
        )
        session.add(pg_jmeter)
        session.flush()
        print("      Created package group: jmeter-5.6.3")

    pg_emulator = session.query(PackageGroupORM).filter_by(name="emulator-1.0").first()
    if not pg_emulator:
        pg_emulator = PackageGroupORM(
            name="emulator-1.0",
            description="Server workload emulator v1.0",
        )
        session.add(pg_emulator)
        session.flush()
        print("      Created package group: emulator-1.0")

    # --- Package Group Members (OS-specific install instructions) ---
    _ensure_package_member(session, pg_jmeter, "rhel/9/.*", {
        "path": "artifacts/packages/jmeter-5.6.3-linux.tar.gz",
        "root_install_path": "/opt/jmeter-pkg",
        "extraction_command": "tar -xzf /opt/jmeter-pkg/jmeter-5.6.3-linux.tar.gz -C /opt && ln -sfn /opt/apache-jmeter-5.6.3 /opt/jmeter",
        "status_command": "test -x /opt/jmeter/bin/jmeter",
        "prereq_script": "rhel/java_jre.sh",
    })
    _ensure_package_member(session, pg_emulator, "rhel/9/.*", {
        "path": "artifacts/packages/emulator-linux.tar.gz",
        "root_install_path": "/opt/emulator-pkg",
        "extraction_command": "tar -xzf /opt/emulator-pkg/emulator-linux.tar.gz -C /opt/emulator",
        "install_command": "cd /opt/emulator && pip3 install -r requirements.txt",
        "run_command": "cd /opt/emulator && nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 > /var/log/emulator.log 2>&1 &",
        "status_command": "curl -sf http://localhost:8080/health",
        "prereq_script": "rhel/python_emulator.sh",
    })
    _ensure_package_member(session, pg_emulator, "windows/2022", {
        "path": "artifacts/packages/emulator-windows.tar.gz",
        "root_install_path": "C:\\emulator-pkg",
        "extraction_command": "powershell -Command \"Expand-Archive -Path 'C:\\emulator-pkg\\emulator-windows.tar.gz' -DestinationPath 'C:\\emulator' -Force\"",
        "install_command": "cd C:\\emulator && pip install -r requirements.txt",
        "run_command": "powershell -Command \"Start-Process python -ArgumentList '-m uvicorn app.main:app --host 0.0.0.0 --port 8080' -WorkingDirectory 'C:\\emulator' -NoNewWindow\"",
        "status_command": "powershell -Command \"(Invoke-WebRequest -Uri http://localhost:8080/health -UseBasicParsing).StatusCode\"",
        "prereq_script": "windows_server/python_emulator.ps1",
    })

    # --- Lab ---
    lab = session.query(LabORM).filter_by(name="Proxmox Lab").first()
    if not lab:
        lab = LabORM(
            name="Proxmox Lab",
            description="Proxmox VE lab on 10.0.0.72 — 3 Rocky + 1 Windows targets",
            jmeter_package_grpid=pg_jmeter.id,
            emulator_package_grp_id=pg_emulator.id,
            loadgen_snapshot_id=bl_loadgen.id,
            hypervisor_type=HypervisorType.proxmox,
            hypervisor_manager_url="10.0.0.72",
            hypervisor_manager_port=8006,
            execution_mode=ExecutionMode.baseline_compare,
        )
        session.add(lab)
        session.flush()
        print("      Created lab: Proxmox Lab (id=%d)" % lab.id)

    # --- Servers ---
    servers_data = [
        {
            "hostname": "orch-rky-01",
            "ip_address": "10.0.0.82",
            "os_family": OSFamily.linux,
            "os_vendor_family": "rhel",
            "os_major_ver": "9",
            "os_minor_ver": "7",
            "hardware_profile": hp1,
            "server_infra_type": ServerInfraType.proxmox_vm,
            "server_infra_ref": {"node": "pve", "vmid": 400},
            "baseline": bl_rocky,
            "default_loadgen": None,
        },
        {
            "hostname": "loadgen-rky-01",
            "ip_address": "10.0.0.83",
            "os_family": OSFamily.linux,
            "os_vendor_family": "rhel",
            "os_major_ver": "9",
            "os_minor_ver": "7",
            "hardware_profile": hp1,
            "server_infra_type": ServerInfraType.proxmox_vm,
            "server_infra_ref": {"node": "pve", "vmid": 401},
            "baseline": bl_loadgen,
            "default_loadgen": None,
        },
        {
            "hostname": "target-rky-01",
            "ip_address": "10.0.0.92",
            "os_family": OSFamily.linux,
            "os_vendor_family": "rhel",
            "os_major_ver": "9",
            "os_minor_ver": "7",
            "hardware_profile": hp1,
            "server_infra_type": ServerInfraType.proxmox_vm,
            "server_infra_ref": {"node": "pve", "vmid": 410},
            "baseline": bl_rocky,
            "default_loadgen": "loadgen-rky-01",  # resolved below
        },
        {
            "hostname": "TARGET-WIN-01",
            "ip_address": "10.0.0.91",
            "os_family": OSFamily.windows,
            "os_vendor_family": "windows",
            "os_major_ver": "2022",
            "os_minor_ver": None,
            "hardware_profile": hp2,
            "server_infra_type": ServerInfraType.proxmox_vm,
            "server_infra_ref": {"node": "pve", "vmid": 321},
            "baseline": bl_win,
            "default_loadgen": "loadgen-rky-01",  # resolved below
        },
    ]

    created_servers = {}
    for sd in servers_data:
        existing = session.query(ServerORM).filter_by(hostname=sd["hostname"]).first()
        if existing:
            created_servers[sd["hostname"]] = existing
            print("      Server '%s' already exists (id=%d)" % (sd["hostname"], existing.id))
            continue

        srv = ServerORM(
            hostname=sd["hostname"],
            ip_address=sd["ip_address"],
            os_family=sd["os_family"],
            os_vendor_family=sd["os_vendor_family"],
            os_major_ver=sd["os_major_ver"],
            os_minor_ver=sd["os_minor_ver"],
            lab_id=lab.id,
            hardware_profile_id=sd["hardware_profile"].id,
            server_infra_type=sd["server_infra_type"],
            server_infra_ref=sd["server_infra_ref"],
            baseline_id=sd["baseline"].id,
        )
        session.add(srv)
        session.flush()
        created_servers[sd["hostname"]] = srv
        print("      Created server: %s (id=%d, vmid=%d)" % (
            sd["hostname"], srv.id, sd["server_infra_ref"]["vmid"]))

    # Set default_loadgen_id for targets
    loadgen = created_servers.get("loadgen-rky-01")
    if loadgen:
        for name in ["target-rky-01", "TARGET-WIN-01"]:
            srv = created_servers.get(name)
            if srv and not srv.default_loadgen_id:
                srv.default_loadgen_id = loadgen.id
                print("      Set default_loadgen_id=%d for %s" % (loadgen.id, name))

    # --- Scenario ---
    scenario = session.query(ScenarioORM).filter_by(
        name="Normal Server Load", lab_id=lab.id,
    ).first()
    if not scenario:
        scenario = ScenarioORM(
            name="Normal Server Load",
            description="Standard server workload: CPU, memory, disk, file, network ops",
            lab_id=lab.id,
            template_type=TemplateType.server_normal,
            has_base_phase=True,
            has_initial_phase=True,
            has_dbtest=False,
            load_generator_package_grp_id=pg_jmeter.id,
        )
        session.add(scenario)
        session.flush()
        print("      Created scenario: Normal Server Load (id=%d)" % scenario.id)

    # --- Snapshots (one per target VM, matching Proxmox snapshot names) ---
    target_rky = created_servers.get("target-rky-01")
    target_win = created_servers.get("TARGET-WIN-01")

    snap_rky = None
    if target_rky:
        snap_rky = session.query(SnapshotORM).filter_by(
            server_id=target_rky.id, name="clean-rocky97",
        ).first()
        if not snap_rky:
            snap_rky = SnapshotORM(
                name="clean-rocky97",
                description="Clean Rocky 9.7 — no agents installed",
                server_id=target_rky.id,
                provider_snapshot_id="clean-rocky97",
                provider_ref={"snapshot_name": "clean-rocky97"},
                is_baseline=True,
                is_archived=False,
            )
            session.add(snap_rky)
            session.flush()
            print("      Created snapshot: clean-rocky97 for target-rky-01 (id=%d)" % snap_rky.id)

    snap_win = None
    if target_win:
        snap_win = session.query(SnapshotORM).filter_by(
            server_id=target_win.id, name="clean-win2022",
        ).first()
        if not snap_win:
            snap_win = SnapshotORM(
                name="clean-win2022",
                description="Clean Windows Server 2022 — no agents installed",
                server_id=target_win.id,
                provider_snapshot_id="clean-win2022",
                provider_ref={"snapshot_name": "clean-win2022"},
                is_baseline=True,
                is_archived=False,
            )
            session.add(snap_win)
            session.flush()
            print("      Created snapshot: clean-win2022 for TARGET-WIN-01 (id=%d)" % snap_win.id)

    session.commit()

    # --- Print summary for test creation ---
    print()
    print("      Proxmox lab setup complete.")
    print()
    print("      === IDs for creating a baseline test ===")
    if target_rky:
        print("      Linux target server_id  : %d" % target_rky.id)
    if target_win:
        print("      Windows target server_id : %d" % target_win.id)
    if loadgen:
        print("      Loadgen server_id        : %d" % loadgen.id)
    print("      Lab id                   : %d" % lab.id)
    print("      Scenario id              : %d" % scenario.id)
    if snap_rky:
        print("      Linux snapshot_id        : %d" % snap_rky.id)
    if snap_win:
        print("      Windows snapshot_id      : %d" % snap_win.id)
    print()
    print("      Update credentials.json 'by_server_id' keys to match these IDs!")


def main():
    print("=" * 60)
    print("  Proxmox Lab Setup — orchestrator database")
    print("  DB: SQL Server localhost/orchestrator (trusted)")
    print("=" * 60)
    print()

    init_db(DB_URL, echo=False)

    # Step 1: Create all tables
    create_tables()

    # Step 2-3: Seed data + lab data
    session = SessionLocal()
    try:
        run_seeds(session)
        insert_proxmox_lab(session)
    except Exception as e:
        session.rollback()
        print("\nERROR: %s" % e)
        raise
    finally:
        session.close()

    print()
    print("Done! You can now start the orchestrator and access the web UI.")
    print("  Credentials: admin / admin")
    print("  Lab: 'Proxmox Lab' with 4 servers on 10.0.0.x")
    print()
    print("Next steps:")
    print("  1. Take Proxmox snapshots:  qm snapshot 410 clean-rocky97")
    print("                              qm snapshot 321 clean-win2022")
    print("  2. Update credentials.json server IDs to match printed IDs above")
    print("  3. Start orchestrator:  python -m uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000")
    print("  4. Create baseline test via API or Web UI using the IDs above")


if __name__ == "__main__":
    main()
