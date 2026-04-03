#!/usr/bin/env python3
"""Seed the database with realistic dummy data for runbook screenshots.

Creates: labs, hardware profiles, load profiles, servers (targets + loadgens),
agents with detection rules, agent sets, snapshot groups.

Usage:
    python seed_dummy_data.py
    python seed_dummy_data.py --clean   # delete all and re-seed
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ORCH_SRC = os.path.join(REPO_ROOT, "orchestrator", "src")
if ORCH_SRC not in sys.path:
    sys.path.insert(0, ORCH_SRC)


def seed(session, clean=False):
    from orchestrator.models.orm import (
        AgentORM, AgentDetectionRuleORM,
        HardwareProfileORM, LabORM, LoadProfileORM,
        ServerORM, SnapshotBaselineORM, SnapshotGroupORM, SnapshotORM,
        SubgroupAgentORM, SubgroupDefinitionORM, UserORM,
    )
    from orchestrator.models.enums import (
        AgentType, DBType, DiskType, ExecutionMode, HypervisorType,
        OSFamily, ServerInfraType, ServerRole,
    )
    from orchestrator.services.auth import hash_password

    if clean:
        print("Cleaning existing data...")
        for model in [
            SubgroupAgentORM, SubgroupDefinitionORM,
            AgentDetectionRuleORM, AgentORM,
            SnapshotGroupORM, SnapshotBaselineORM, SnapshotORM,
            ServerORM, LoadProfileORM, HardwareProfileORM, LabORM,
        ]:
            try:
                session.query(model).delete()
            except Exception:
                session.rollback()
        session.commit()
        print("Done cleaning.")

    # --- Admin user ---
    if not session.query(UserORM).filter(UserORM.username == "admin").first():
        session.add(UserORM(username="admin", password_hash=hash_password("admin"), role="admin"))
        session.flush()
        print("Created admin user (admin/admin)")

    # --- Lab ---
    lab = session.query(LabORM).filter(LabORM.name == "Lab-vSphere-DC1").first()
    if not lab:
        lab = LabORM(
            name="Lab-vSphere-DC1",
            hypervisor_type=HypervisorType.vsphere,
            execution_mode=ExecutionMode.baseline_compare,
            hypervisor_manager_url="vcenter.corp.com",
            hypervisor_manager_port=443,
            jmeter_package_grpid=1,
            loadgen_snapshot_id=1,
        )
        session.add(lab)
        session.flush()
        print(f"Created lab: {lab.name} (ID={lab.id})")

    # --- Hardware profiles ---
    hw_names = [
        ("Standard 8vCPU 16GB", 8, 16, "ssd", 200),
        ("Standard 4vCPU 8GB", 4, 8, "ssd", 100),
    ]
    hw_map = {}
    for name, cores, mem, disk, size in hw_names:
        hw = session.query(HardwareProfileORM).filter(HardwareProfileORM.name == name).first()
        if not hw:
            hw = HardwareProfileORM(
                name=name, cpu_cores=cores, memory_gb=mem,
                disk_type=DiskType(disk), disk_size_gb=size,
            )
            session.add(hw)
            session.flush()
            print(f"Created hardware profile: {name} (ID={hw.id})")
        hw_map[name] = hw

    # --- Load profiles ---
    lp_specs = [
        ("Low", 20.0, 40.0),
        ("Medium", 40.0, 60.0),
        ("High", 60.0, 80.0),
    ]
    for name, cpu_min, cpu_max in lp_specs:
        if not session.query(LoadProfileORM).filter(LoadProfileORM.name == name).first():
            session.add(LoadProfileORM(
                name=name, cpu_target_min=cpu_min, cpu_target_max=cpu_max,
            ))
            session.flush()
            print(f"Created load profile: {name}")

    # --- Servers ---
    servers_spec = [
        # (hostname, ip, role, os_family, os_vendor, os_major, hw_name, infra_ref)
        ("srv-rocky1", "10.200.157.159", "target", "linux", "rocky", "9", "Standard 8vCPU 16GB",
         {"datacenter": "DC1", "vm_name": "srv-rocky1"}),
        ("srv-rocky2", "10.200.157.107", "target", "linux", "rocky", "9", "Standard 8vCPU 16GB",
         {"datacenter": "DC1", "vm_name": "srv-rocky2"}),
        ("srv-win2022", "10.200.157.160", "target", "windows", "windows_server", "2022", "Standard 8vCPU 16GB",
         {"datacenter": "DC1", "vm_name": "srv-win2022"}),
        ("loadgen1", "10.200.157.106", "loadgen", "linux", "rocky", "9", "Standard 4vCPU 8GB",
         {"datacenter": "DC1", "vm_name": "loadgen1"}),
        ("loadgen2", "10.200.157.108", "loadgen", "linux", "rocky", "9", "Standard 4vCPU 8GB",
         {"datacenter": "DC1", "vm_name": "loadgen2"}),
    ]
    srv_map = {}
    for hostname, ip, role, os_fam, os_vendor, os_major, hw_name, infra_ref in servers_spec:
        srv = session.query(ServerORM).filter(ServerORM.hostname == hostname).first()
        if not srv:
            srv = ServerORM(
                hostname=hostname, ip_address=ip,
                role=ServerRole(role), os_family=OSFamily(os_fam),
                os_vendor_family=os_vendor, os_major_ver=os_major,
                lab_id=lab.id,
                hardware_profile_id=hw_map[hw_name].id,
                server_infra_type=ServerInfraType.vsphere_vm,
                server_infra_ref=infra_ref,
            )
            session.add(srv)
            session.flush()
            print(f"Created server: {hostname} (ID={srv.id}, role={role})")
        srv_map[hostname] = srv

    # Set default loadgens
    if srv_map.get("srv-rocky1") and srv_map.get("loadgen1"):
        srv_map["srv-rocky1"].default_loadgen_id = srv_map["loadgen1"].id
    if srv_map.get("srv-rocky2") and srv_map.get("loadgen2"):
        srv_map["srv-rocky2"].default_loadgen_id = srv_map["loadgen2"].id
    session.flush()

    # --- Agents ---
    agents_spec = [
        ("CrowdStrike", "CrowdStrike Inc.", AgentType.edr, [
            ("rhel|rocky|centos", "bash", "falcon-sensor*", "sudo /opt/CrowdStrike/falconctl -g --version"),
            ("windows", "powershell", "CrowdStrike*", "(Get-ItemProperty 'HKLM:\\SOFTWARE\\CrowdStrike\\*').Version"),
        ]),
        ("Tanium", "Tanium Inc.", AgentType.monitoring, [
            ("rhel|rocky|centos", "bash", "TaniumClient*", "rpm -q TaniumClient"),
            ("windows", "powershell", "Tanium*", "(Get-Service TaniumClient).DisplayName"),
        ]),
        ("Thales CTE", "Thales Group", AgentType.dlp, [
            ("rhel|rocky|centos", "bash", "vorvos*", "voradmin -v"),
            ("windows", "powershell", "VorvosAgent*", "voradmin -v"),
        ]),
        ("PkWare", "PKWARE Inc.", AgentType.dlp, [
            ("rhel|rocky|centos", "bash", "pkware*", "pkzip --version"),
            ("windows", "powershell", "PKWARE*", "pkzip --version"),
        ]),
        ("Guardium", "IBM", AgentType.monitoring, [
            ("rhel|rocky|centos", "bash", "guardium*", "/usr/local/guardium/guard_setup -v"),
            ("windows", "powershell", "GuardiumAgent*", "guard_setup -v"),
        ]),
    ]
    agent_map = {}
    for name, vendor, atype, rules in agents_spec:
        agent = session.query(AgentORM).filter(AgentORM.name == name).first()
        if not agent:
            agent = AgentORM(name=name, vendor=vendor, agent_type=atype, is_active=True)
            session.add(agent)
            session.flush()
            for os_regex, cmd_type, service_regex, version_cmd in rules:
                session.add(AgentDetectionRuleORM(
                    agent_id=agent.id, os_regex=os_regex, cmd_type=cmd_type,
                    service_regex=service_regex, version_cmd=version_cmd,
                ))
            session.flush()
            print(f"Created agent: {name} (ID={agent.id}) with {len(rules)} detection rules")
        agent_map[name] = agent

    # --- Agent Sets (Subgroup Definitions) ---
    sets_spec = [
        ("CrowdStrike Only", ["CrowdStrike"]),
        ("Tanium Only", ["Tanium"]),
        ("CrowdStrike + Tanium", ["CrowdStrike", "Tanium"]),
        ("CS + Tanium + PkWare", ["CrowdStrike", "Tanium", "PkWare"]),
        ("CS + Tanium + Thales CTE", ["CrowdStrike", "Tanium", "Thales CTE"]),
        ("CS + Tanium + Guardium", ["CrowdStrike", "Tanium", "Guardium"]),
    ]
    sgdef_map = {}
    for name, agent_names in sets_spec:
        sgdef = session.query(SubgroupDefinitionORM).filter(SubgroupDefinitionORM.name == name).first()
        if not sgdef:
            sgdef = SubgroupDefinitionORM(name=name)
            session.add(sgdef)
            session.flush()
            for aname in agent_names:
                if aname in agent_map:
                    session.add(SubgroupAgentORM(subgroup_def_id=sgdef.id, agent_id=agent_map[aname].id))
            session.flush()
            print(f"Created agent set: {name} (ID={sgdef.id}) — agents: {', '.join(agent_names)}")
        sgdef_map[name] = sgdef

    session.commit()
    print("\nSeed complete!")
    print(f"  Lab: {lab.name}")
    print(f"  Servers: {len(srv_map)} ({sum(1 for s in srv_map.values() if s.role == ServerRole.target)} targets, "
          f"{sum(1 for s in srv_map.values() if s.role == ServerRole.loadgen)} loadgens)")
    print(f"  Agents: {len(agent_map)}")
    print(f"  Agent Sets: {len(sgdef_map)}")
    print(f"  Load Profiles: {len(lp_specs)}")


def main():
    parser = argparse.ArgumentParser(description="Seed database with dummy data for runbook screenshots")
    parser.add_argument("--clean", action="store_true", help="Delete all existing data first")
    args = parser.parse_args()

    from orchestrator.models.database import SessionLocal, init_db
    from orchestrator.config.settings import load_config

    config_path = os.path.join(REPO_ROOT, "orchestrator", "config", "orchestrator.yaml")
    config = load_config(config_path)
    init_db(config.database.url)

    session = SessionLocal()
    try:
        seed(session, clean=args.clean)
    finally:
        session.close()


if __name__ == "__main__":
    main()
