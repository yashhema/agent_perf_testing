"""Take screenshots of all orchestrator web pages.

Spins up a temporary SQLite-backed server with sample data,
then uses Playwright to capture every page.
"""

import sys
import os
import time
import threading
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ---- Import ORM models first (registers them with Base.metadata) ----
from orchestrator.models.database import Base
import orchestrator.models.database as db_mod
from orchestrator.models.orm import (
    AgentORM, HardwareProfileORM, LabORM, ServerORM, BaselineORM,
    PackageGroupORM, PackageGroupMemberORM, ScenarioORM,
    LoadProfileORM, TestRunORM, TestRunTargetORM,
    TestRunLoadProfileORM, CalibrationResultORM,
    PhaseExecutionResultORM, ComparisonResultORM, UserORM,
    ScenarioAgentORM,
)
from orchestrator.models.enums import *
from orchestrator.services.auth import hash_password

# ---- THEN patch PostgreSQL types for SQLite ----
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy import JSON, Text, create_engine, event
from sqlalchemy.orm import sessionmaker

for table in Base.metadata.tables.values():
    for col in table.columns:
        if isinstance(col.type, JSONB):
            col.type = JSON()
        elif isinstance(col.type, ARRAY):
            col.type = Text()

# ---- Setup SQLite database with sample data ----
import uuid as _uuid
DB_PATH = os.path.join(os.path.dirname(__file__), "screenshots", f"_temp_{_uuid.uuid4().hex[:8]}.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Monkey-patch the database module so the app uses our SQLite engine
db_mod.engine = engine
db_mod.SessionLocal.configure(bind=engine)


def seed_data():
    session = Session()

    # Admin user
    admin = UserORM(username="admin", password_hash=hash_password("admin"),
                    email="admin@orchestrator.local", role="admin", is_active=True)
    session.add(admin)

    # Hardware profiles
    hp1 = HardwareProfileORM(name="Standard VM", cpu_count=4, cpu_model="Xeon E5-2680 v4",
                             memory_gb=16.0, disk_type=DiskType.ssd, disk_size_gb=100.0, nic_speed_mbps=1000, vendor="Dell")
    hp2 = HardwareProfileORM(name="High-Memory VM", cpu_count=8, cpu_model="Xeon E5-2680 v4",
                             memory_gb=32.0, disk_type=DiskType.ssd, disk_size_gb=200.0, nic_speed_mbps=1000, vendor="HP")
    hp3 = HardwareProfileORM(name="Load Gen VM", cpu_count=4, cpu_model="Xeon E5-2680 v4",
                             memory_gb=8.0, disk_type=DiskType.hdd, disk_size_gb=50.0, nic_speed_mbps=1000, vendor="VMware")
    session.add_all([hp1, hp2, hp3])
    session.flush()

    # Baselines
    b1 = BaselineORM(name="Ubuntu 22.04 Base", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref=({"node": "pve1", "vmid": 100, "snapshot": "base-clean"}))
    b2 = BaselineORM(name="Ubuntu 22.04 Initial", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref=({"node": "pve1", "vmid": 100, "snapshot": "initial-agent"}))
    b3 = BaselineORM(name="Win Server 2022 Base", os_family=OSFamily.windows,
                     os_vendor_family="windows_server", os_major_ver="2022",
                     baseline_type=BaselineType.vsphere,
                     provider_ref=({"datacenter": "DC1", "vm": "win-srv-01", "snapshot": "base"}))
    b4 = BaselineORM(name="Load Gen Ubuntu", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref=({"node": "pve1", "vmid": 105, "snapshot": "loadgen-ready"}))
    session.add_all([b1, b2, b3, b4])
    session.flush()

    # Package groups
    pg1 = PackageGroupORM(name="JMeter 5.6.3", description="Apache JMeter load generator")
    pg2 = PackageGroupORM(name="Emulator v2.1", description="Performance emulator agent")
    pg3 = PackageGroupORM(name="Agent v3.5.0", description="Monitoring agent under test (initial)")
    session.add_all([pg1, pg2, pg3])
    session.flush()

    # Package group members
    session.add_all([
        PackageGroupMemberORM(package_group_id=pg1.id, os_match_regex=".*linux.*",
                              path="/packages/jmeter-5.6.3.tar.gz", root_install_path="/opt/jmeter",
                              extraction_command="tar xzf jmeter-5.6.3.tar.gz",
                              run_command="/opt/jmeter/bin/jmeter.sh",
                              status_command="pgrep -f jmeter"),
        PackageGroupMemberORM(package_group_id=pg2.id, os_match_regex=".*linux.*",
                              path="/packages/emulator-2.1-linux.tar.gz", root_install_path="/opt/emulator",
                              extraction_command="tar xzf emulator-2.1-linux.tar.gz",
                              install_command="/opt/emulator/install.sh",
                              run_command="/opt/emulator/start.sh",
                              status_command="pgrep -f emulator"),
        PackageGroupMemberORM(package_group_id=pg2.id, os_match_regex=".*windows.*",
                              path="/packages/emulator-2.1-win.zip", root_install_path="C:\\emulator",
                              extraction_command="powershell Expand-Archive emulator-2.1-win.zip",
                              install_command="C:\\emulator\\install.bat",
                              run_command="C:\\emulator\\start.bat"),
        PackageGroupMemberORM(package_group_id=pg3.id, os_match_regex=".*linux.*",
                              path="/packages/agent-3.5.0-linux.deb", root_install_path="/opt/agent",
                              install_command="dpkg -i agent-3.5.0-linux.deb",
                              status_command="systemctl status agent"),
    ])
    session.flush()

    # Labs
    lab1 = LabORM(name="Proxmox Lab A", description="Primary test lab — 6 VMs, Proxmox cluster",
                  jmeter_package_grpid=pg1.id, loadgen_snapshot_id=b4.id,
                  hypervisor_type=HypervisorType.proxmox,
                  hypervisor_manager_url="https://pve1.lab.local", hypervisor_manager_port=8006)
    lab2 = LabORM(name="vSphere Lab B", description="Secondary lab — vSphere, Windows servers",
                  jmeter_package_grpid=pg1.id, loadgen_snapshot_id=b4.id,
                  hypervisor_type=HypervisorType.vsphere,
                  hypervisor_manager_url="https://vcenter.lab.local", hypervisor_manager_port=443)
    session.add_all([lab1, lab2])
    session.flush()

    # Servers
    s1 = ServerORM(hostname="target-01", ip_address="10.0.1.101", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp1.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref=({"node": "pve1", "vmid": 101}),
                   baseline_id=b1.id)
    s2 = ServerORM(hostname="target-02", ip_address="10.0.1.102", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp2.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref=({"node": "pve1", "vmid": 102}),
                   baseline_id=b1.id)
    s3 = ServerORM(hostname="loadgen-01", ip_address="10.0.1.105", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp3.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref=({"node": "pve1", "vmid": 105}))
    s4 = ServerORM(hostname="win-target-01", ip_address="10.0.2.101", os_family=OSFamily.windows,
                   lab_id=lab2.id, hardware_profile_id=hp1.id,
                   server_infra_type=ServerInfraType.vsphere_vm,
                   server_infra_ref=({"datacenter": "DC1", "vm": "win-srv-01"}),
                   baseline_id=b3.id)
    session.add_all([s1, s2, s3, s4])
    session.flush()

    # Load profiles
    lp1 = LoadProfileORM(name="low", target_cpu_range_min=20.0, target_cpu_range_max=40.0,
                         duration_sec=300, ramp_up_sec=30)
    lp2 = LoadProfileORM(name="medium", target_cpu_range_min=40.0, target_cpu_range_max=60.0,
                         duration_sec=600, ramp_up_sec=60)
    lp3 = LoadProfileORM(name="high", target_cpu_range_min=60.0, target_cpu_range_max=80.0,
                         duration_sec=600, ramp_up_sec=60)
    session.add_all([lp1, lp2, lp3])
    session.flush()

    # Agents
    agent1 = AgentORM(name="CrowdStrike Falcon v7.1", vendor="CrowdStrike", agent_type=AgentType.edr,
                      version="7.1", description="CrowdStrike Falcon EDR sensor",
                      process_patterns=["CSFalcon*", "falcon*"], service_patterns=["CSFalconService"],
                      discovery_key="crowdstrike", is_active=True)
    session.add(agent1)
    session.flush()

    # Scenarios
    sc1 = ScenarioORM(name="Server Normal — Agent v3.5", description="Standard server workload with agent monitoring",
                      lab_id=lab1.id, template_type=TemplateType.server_normal,
                      has_base_phase=True, has_initial_phase=True, has_dbtest=False,
                      load_generator_package_grp_id=pg2.id, initial_package_grp_id=pg3.id)
    session.add(sc1)
    session.flush()

    # Link agent to scenario
    session.add(ScenarioAgentORM(scenario_id=sc1.id, agent_id=agent1.id))
    session.flush()

    # Test run (completed with results)
    tr1 = TestRunORM(scenario_id=sc1.id, lab_id=lab1.id, cycles_per_profile=2,
                     run_mode=RunMode.complete, state=TestRunState.completed)
    session.add(tr1)
    session.flush()

    # Load profiles for test run
    session.add_all([
        TestRunLoadProfileORM(test_run_id=tr1.id, load_profile_id=lp1.id),
        TestRunLoadProfileORM(test_run_id=tr1.id, load_profile_id=lp2.id),
    ])

    # Test run targets
    _agent_versions = [{"agent_id": agent1.id, "agent_name": "CrowdStrike Falcon v7.1",
                        "discovered_version": "7.1.0", "status": "running"}]
    trt1 = TestRunTargetORM(test_run_id=tr1.id, target_id=s1.id, loadgenerator_id=s3.id,
                            base_snapshot_id=b1.id, initial_snapshot_id=b2.id,
                            service_monitor_patterns=(["agent", "emulator"]),
                            os_kind="ubuntu", base_os_major_ver="22", base_os_minor_ver="04",
                            initial_os_major_ver="22", initial_os_minor_ver="04",
                            base_agent_versions=_agent_versions, initial_agent_versions=_agent_versions)
    trt2 = TestRunTargetORM(test_run_id=tr1.id, target_id=s2.id, loadgenerator_id=s3.id,
                            base_snapshot_id=b1.id, initial_snapshot_id=b2.id,
                            service_monitor_patterns=(["agent"]),
                            os_kind="ubuntu", base_os_major_ver="22", base_os_minor_ver="04",
                            initial_os_major_ver="22", initial_os_minor_ver="04",
                            base_agent_versions=_agent_versions, initial_agent_versions=_agent_versions)
    session.add_all([trt1, trt2])
    session.flush()

    # Calibration results
    session.add_all([
        CalibrationResultORM(test_run_id=tr1.id, server_id=s1.id, os_type=OSFamily.linux,
                             load_profile_id=lp1.id, thread_count=12),
        CalibrationResultORM(test_run_id=tr1.id, server_id=s1.id, os_type=OSFamily.linux,
                             load_profile_id=lp2.id, thread_count=24),
        CalibrationResultORM(test_run_id=tr1.id, server_id=s2.id, os_type=OSFamily.linux,
                             load_profile_id=lp1.id, thread_count=18),
        CalibrationResultORM(test_run_id=tr1.id, server_id=s2.id, os_type=OSFamily.linux,
                             load_profile_id=lp2.id, thread_count=35),
    ])

    # Phase execution results (some completed, some with data)
    for snap in [1, 2]:
        for lp in [lp1, lp2]:
            for cycle in [1, 2]:
                for trt in [trt1, trt2]:
                    status = ExecutionStatus.completed
                    err = None
                    stats = f"/results/tr{tr1.id}/s{trt.target_id}_snap{snap}_lp{lp.id}_c{cycle}_stats.json"
                    jtl = f"/results/tr{tr1.id}/s{trt.target_id}_snap{snap}_lp{lp.id}_c{cycle}.jtl"
                    session.add(PhaseExecutionResultORM(
                        test_run_id=tr1.id, target_id=trt.target_id,
                        snapshot_num=snap, load_profile_id=lp.id, cycle_number=cycle,
                        baseline_id=b1.id if snap == 1 else b2.id,
                        thread_count=12 if lp.id == lp1.id else 24,
                        status=status, error_message=err,
                        stats_file_path=stats, jmeter_jtl_path=jtl,
                    ))

    # Comparison results — structured format with all analysis layers
    _result_data_1 = {
        "system_deltas": {
            "cpu_percent": {
                "base_avg": 28.5, "initial_avg": 31.2,
                "delta_abs": {"avg": 2.7, "min": 0.5, "max": 8.1, "p50": 2.4, "p90": 5.2, "p95": 6.8, "p99": 7.9},
                "delta_pct": {"avg": 9.5, "min": 1.8, "max": 28.4, "p50": 8.4, "p90": 18.2, "p95": 23.9, "p99": 27.7},
            },
            "memory_used_mb": {
                "base_avg": 4200.0, "initial_avg": 4450.0,
                "delta_abs": {"avg": 250.0, "min": 210.0, "max": 310.0, "p50": 245.0, "p90": 290.0, "p95": 300.0, "p99": 308.0},
                "delta_pct": {"avg": 6.0, "min": 5.0, "max": 7.4, "p50": 5.8, "p90": 6.9, "p95": 7.1, "p99": 7.3},
            },
            "disk_read_rate_mbps": {
                "base_avg": 12.3, "initial_avg": 13.1,
                "delta_abs": {"avg": 0.8, "min": 0.1, "max": 2.5, "p50": 0.6, "p90": 1.8, "p95": 2.1, "p99": 2.4},
                "delta_pct": {"avg": 6.5, "min": 0.8, "max": 20.3, "p50": 4.9, "p90": 14.6, "p95": 17.1, "p99": 19.5},
            },
            "disk_write_rate_mbps": {
                "base_avg": 8.7, "initial_avg": 9.2,
                "delta_abs": {"avg": 0.5, "min": 0.1, "max": 1.8, "p50": 0.4, "p90": 1.1, "p95": 1.5, "p99": 1.7},
                "delta_pct": {"avg": 5.7, "min": 1.1, "max": 20.7, "p50": 4.6, "p90": 12.6, "p95": 17.2, "p99": 19.5},
            },
            "net_sent_rate_mbps": {
                "base_avg": 1.5, "initial_avg": 1.62,
                "delta_abs": {"avg": 0.12, "min": 0.01, "max": 0.35, "p50": 0.10, "p90": 0.25, "p95": 0.30, "p99": 0.34},
                "delta_pct": {"avg": 8.0, "min": 0.7, "max": 23.3, "p50": 6.7, "p90": 16.7, "p95": 20.0, "p99": 22.7},
            },
            "net_recv_rate_mbps": {
                "base_avg": 2.1, "initial_avg": 2.2,
                "delta_abs": {"avg": 0.10, "min": 0.01, "max": 0.30, "p50": 0.08, "p90": 0.22, "p95": 0.26, "p99": 0.29},
                "delta_pct": {"avg": 4.8, "min": 0.5, "max": 14.3, "p50": 3.8, "p90": 10.5, "p95": 12.4, "p99": 13.8},
            },
            "disk_io_percent": {
                "base_avg": 15.2, "initial_avg": 16.8,
                "delta_abs": {"avg": 1.6, "min": 0.2, "max": 4.8, "p50": 1.3, "p90": 3.5, "p95": 4.1, "p99": 4.6},
                "delta_pct": {"avg": 10.5, "min": 1.3, "max": 31.6, "p50": 8.6, "p90": 23.0, "p95": 27.0, "p99": 30.3},
            },
        },
        "agent_overhead": {
            "agent_cpu_percent": {"avg": 3.8, "min": 0.5, "max": 12.1, "p50": 3.2, "p90": 7.8, "p95": 9.5, "p99": 11.4},
            "agent_memory_rss_mb": {"avg": 245.0, "min": 230.0, "max": 280.0, "p50": 242.0, "p90": 268.0, "p95": 274.0, "p99": 278.0},
            "agent_memory_vms_mb": {"avg": 512.0, "min": 500.0, "max": 540.0, "p50": 510.0, "p90": 530.0, "p95": 535.0, "p99": 538.0},
            "agent_thread_count": {"avg": 42.0, "min": 38.0, "max": 52.0, "p50": 41.0, "p90": 48.0, "p95": 50.0, "p99": 51.0},
            "agent_handle_count": {"avg": 320.0, "min": 290.0, "max": 380.0, "p50": 315.0, "p90": 360.0, "p95": 370.0, "p99": 378.0},
            "agent_io_read_rate_mbps": {"avg": 0.8, "min": 0.1, "max": 3.2, "p50": 0.6, "p90": 2.0, "p95": 2.6, "p99": 3.0},
            "agent_io_write_rate_mbps": {"avg": 0.5, "min": 0.05, "max": 2.1, "p50": 0.4, "p90": 1.3, "p95": 1.7, "p99": 2.0},
            "process_count": {"avg": 3.0, "min": 3.0, "max": 4.0, "p50": 3.0, "p90": 3.0, "p95": 4.0, "p99": 4.0},
        },
        "normalized_ratios": {
            "agent_cpu_percent": {
                "normalization_type": "ratio",
                "ratios": {"avg": 0.1333, "min": 1.0, "max": 1.4938, "p50": 0.1333, "p90": 0.15, "p95": 0.1397, "p99": 0.1443},
                "base_values": {"avg": 28.5, "min": 0.5, "max": 8.1, "p50": 24.0, "p90": 52.0, "p95": 68.0, "p99": 79.0},
                "agent_values": {"avg": 3.8, "min": 0.5, "max": 12.1, "p50": 3.2, "p90": 7.8, "p95": 9.5, "p99": 11.4},
            },
            "agent_io_read_rate_mbps": {
                "normalization_type": "ratio",
                "ratios": {"avg": 0.065, "min": 1.0, "max": 1.28, "p50": 0.0566, "p90": 0.1111, "p95": 0.1238, "p99": 0.125},
                "base_values": {"avg": 12.3, "min": 0.1, "max": 2.5, "p50": 10.6, "p90": 18.0, "p95": 21.0, "p99": 24.0},
                "agent_values": {"avg": 0.8, "min": 0.1, "max": 3.2, "p50": 0.6, "p90": 2.0, "p95": 2.6, "p99": 3.0},
            },
            "agent_io_write_rate_mbps": {
                "normalization_type": "ratio",
                "ratios": {"avg": 0.0575, "min": 0.5, "max": 1.1667, "p50": 0.0513, "p90": 0.1182, "p95": 0.1133, "p99": 0.1176},
                "base_values": {"avg": 8.7, "min": 0.1, "max": 1.8, "p50": 7.8, "p90": 11.0, "p95": 15.0, "p99": 17.0},
                "agent_values": {"avg": 0.5, "min": 0.05, "max": 2.1, "p50": 0.4, "p90": 1.3, "p95": 1.7, "p99": 2.0},
            },
            "agent_memory_rss_mb": {
                "normalization_type": "absolute",
                "ratios": {"avg": 245.0, "min": 230.0, "max": 280.0, "p50": 242.0, "p90": 268.0, "p95": 274.0, "p99": 278.0},
                "base_values": {},
                "agent_values": {"avg": 245.0, "min": 230.0, "max": 280.0, "p50": 242.0, "p90": 268.0, "p95": 274.0, "p99": 278.0},
            },
            "agent_memory_vms_mb": {
                "normalization_type": "absolute",
                "ratios": {"avg": 512.0, "min": 500.0, "max": 540.0, "p50": 510.0, "p90": 530.0, "p95": 535.0, "p99": 538.0},
                "base_values": {},
                "agent_values": {"avg": 512.0, "min": 500.0, "max": 540.0, "p50": 510.0, "p90": 530.0, "p95": 535.0, "p99": 538.0},
            },
            "agent_thread_count": {
                "normalization_type": "absolute",
                "ratios": {"avg": 42.0, "min": 38.0, "max": 52.0, "p50": 41.0, "p90": 48.0, "p95": 50.0, "p99": 51.0},
                "base_values": {},
                "agent_values": {"avg": 42.0, "min": 38.0, "max": 52.0, "p50": 41.0, "p90": 48.0, "p95": 50.0, "p99": 51.0},
            },
            "agent_handle_count": {
                "normalization_type": "absolute",
                "ratios": {"avg": 320.0, "min": 290.0, "max": 380.0, "p50": 315.0, "p90": 360.0, "p95": 370.0, "p99": 378.0},
                "base_values": {},
                "agent_values": {"avg": 320.0, "min": 290.0, "max": 380.0, "p50": 315.0, "p90": 360.0, "p95": 370.0, "p99": 378.0},
            },
            "process_count": {
                "normalization_type": "absolute",
                "ratios": {"avg": 3.0, "min": 3.0, "max": 4.0, "p50": 3.0, "p90": 3.0, "p95": 4.0, "p99": 4.0},
                "base_values": {},
                "agent_values": {"avg": 3.0, "min": 3.0, "max": 4.0, "p50": 3.0, "p90": 3.0, "p95": 4.0, "p99": 4.0},
            },
        },
        "rule_evaluations": [
            {"rule_name": "CPU Overhead", "category": "system_impact", "passed": True,
             "actual_value": 9.5, "threshold": 15.0, "unit": "%", "severity": "warning"},
            {"rule_name": "Memory Overhead", "category": "system_impact", "passed": True,
             "actual_value": 6.0, "threshold": 10.0, "unit": "%", "severity": "warning"},
            {"rule_name": "Agent CPU Absolute", "category": "agent_overhead", "passed": True,
             "actual_value": 3.8, "threshold": 10.0, "unit": "%", "severity": "critical"},
            {"rule_name": "Agent Memory RSS", "category": "agent_overhead", "passed": True,
             "actual_value": 245.0, "threshold": 500.0, "unit": "MB", "severity": "critical"},
        ],
        "verdict": "passed",
        "verdict_summary": "All rules passed. Agent impact within acceptable range.",
    }
    session.add(ComparisonResultORM(
        test_run_id=tr1.id, target_id=s1.id, load_profile_id=lp1.id,
        comparison_type="per_target",
        result_data=_result_data_1,
        summary_text="Agent v3.5 on target-01 under low load: CPU increased by 9.5% (28.5% -> 31.2%), "
                     "memory rose 6.0% (+250 MB). Disk and network impact minimal (<8%). "
                     "Overall resource overhead is within acceptable range.",
        verdict=Verdict.passed,
    ))
    session.add(ComparisonResultORM(
        test_run_id=tr1.id, target_id=None, load_profile_id=lp1.id,
        comparison_type="aggregated",
        result_data={
            "system_deltas": {
                "cpu_percent": {
                    "base_avg": 27.8, "initial_avg": 30.6,
                    "delta_abs": {"avg": 2.8, "min": 0.6, "max": 7.5, "p50": 2.5, "p90": 5.0, "p95": 6.5, "p99": 7.2},
                    "delta_pct": {"avg": 10.1, "min": 2.2, "max": 27.0, "p50": 9.0, "p90": 18.0, "p95": 23.4, "p99": 25.9},
                },
                "memory_used_mb": {
                    "base_avg": 4100.0, "initial_avg": 4380.0,
                    "delta_abs": {"avg": 280.0, "min": 220.0, "max": 350.0, "p50": 275.0, "p90": 330.0, "p95": 340.0, "p99": 348.0},
                    "delta_pct": {"avg": 6.8, "min": 5.4, "max": 8.5, "p50": 6.7, "p90": 8.0, "p95": 8.3, "p99": 8.5},
                },
            },
            "verdict": "passed",
            "verdict_summary": "Aggregated results: all rules passed.",
        },
        summary_text="Aggregated results across all targets under low load: CPU overhead ~10%, "
                     "memory overhead ~7%. Agent impact is consistent across servers.",
        verdict=Verdict.passed,
    ))

    # Second test run (in executing state)
    tr2 = TestRunORM(scenario_id=sc1.id, lab_id=lab1.id, cycles_per_profile=1,
                     run_mode=RunMode.step_by_step, state=TestRunState.executing,
                     current_snapshot_num=1, current_load_profile_id=lp2.id, current_cycle_number=1)
    session.add(tr2)
    session.flush()
    session.add(TestRunLoadProfileORM(test_run_id=tr2.id, load_profile_id=lp2.id))
    trt3 = TestRunTargetORM(test_run_id=tr2.id, target_id=s1.id, loadgenerator_id=s3.id,
                            base_snapshot_id=b1.id, initial_snapshot_id=b2.id)
    session.add(trt3)
    session.flush()
    session.add(PhaseExecutionResultORM(
        test_run_id=tr2.id, target_id=s1.id, snapshot_num=1, load_profile_id=lp2.id,
        cycle_number=1, baseline_id=b1.id, thread_count=24,
        status=ExecutionStatus.running,
    ))

    # Third test run (created, not started)
    tr3 = TestRunORM(scenario_id=sc1.id, lab_id=lab1.id, cycles_per_profile=3,
                     run_mode=RunMode.complete, state=TestRunState.created)
    session.add(tr3)

    session.commit()
    session.close()
    print("Sample data seeded successfully")


def run_server():
    """Run FastAPI in a background thread."""
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path

    # Create app with no-op lifespan (DB already configured)
    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    application = FastAPI(title="Orchestrator", lifespan=noop_lifespan)
    static_dir = Path(__file__).resolve().parent / "src" / "orchestrator" / "static"
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from orchestrator.api.auth import router as auth_router
    from orchestrator.api.admin import router as admin_router
    from orchestrator.api.test_runs import router as test_runs_router
    from orchestrator.api.trending import router as trending_router
    from orchestrator.web.views import router as web_router
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(test_runs_router)
    application.include_router(trending_router)
    application.include_router(web_router)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    uvicorn.run(application, host="127.0.0.1", port=9876, log_level="warning")


def take_screenshots():
    """Use Playwright to capture all pages."""
    from playwright.sync_api import sync_playwright

    output_dir = os.path.join(os.path.dirname(__file__), "screenshots")
    base_url = "http://127.0.0.1:9876"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # 1. Login page
        page.goto(f"{base_url}/login")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=os.path.join(output_dir, "01_login.png"), full_page=True)
        print("  [1/15] Login page")

        # Actually log in
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click("#btn-login")
        page.wait_for_url("**/admin/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)  # let JS populate data

        # 2. Admin Dashboard
        page.screenshot(path=os.path.join(output_dir, "02_admin_dashboard.png"), full_page=True)
        print("  [2/15] Admin Dashboard")

        # 3. Labs
        page.goto(f"{base_url}/admin/labs")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "03_admin_labs.png"), full_page=True)
        print("  [3/15] Labs")

        # 4. Servers
        page.goto(f"{base_url}/admin/servers")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "04_admin_servers.png"), full_page=True)
        print("  [4/15] Servers")

        # 5. Hardware Profiles
        page.goto(f"{base_url}/admin/hardware-profiles")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "05_admin_hardware_profiles.png"), full_page=True)
        print("  [5/15] Hardware Profiles")

        # 6. Baselines
        page.goto(f"{base_url}/admin/baselines")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "06_admin_baselines.png"), full_page=True)
        print("  [6/15] Baselines")

        # 7. Package Groups
        page.goto(f"{base_url}/admin/packages")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        # Click first group to show members
        first_group = page.query_selector("#group-list a.list-group-item")
        if first_group:
            first_group.click()
            time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "07_admin_packages.png"), full_page=True)
        print("  [7/15] Package Groups")

        # 8. Scenarios
        page.goto(f"{base_url}/admin/scenarios")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "08_admin_scenarios.png"), full_page=True)
        print("  [8/15] Scenarios")

        # 9. Load Profiles
        page.goto(f"{base_url}/admin/load-profiles")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "09_admin_load_profiles.png"), full_page=True)
        print("  [9/15] Load Profiles")

        # 10. DB Schema Config
        page.goto(f"{base_url}/admin/db-schema-config")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "10_admin_db_schema_config.png"), full_page=True)
        print("  [10/15] DB Schema Config")

        # 11. Users
        page.goto(f"{base_url}/admin/users")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "11_admin_users.png"), full_page=True)
        print("  [11/15] Users")

        # 12. Test Run List
        page.goto(f"{base_url}/test-runs")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "12_test_run_list.png"), full_page=True)
        print("  [12/15] Test Run List")

        # 13. Create Test Run
        page.goto(f"{base_url}/test-runs/create")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "13_test_run_create.png"), full_page=True)
        print("  [13/15] Create Test Run")

        # 14. Test Run Dashboard (completed run #1)
        page.goto(f"{base_url}/test-runs/1/dashboard")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        page.screenshot(path=os.path.join(output_dir, "14_test_run_dashboard.png"), full_page=True)
        print("  [14/15] Test Run Dashboard")

        # 15. Test Run Results
        page.goto(f"{base_url}/test-runs/1/results")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        page.screenshot(path=os.path.join(output_dir, "15_test_run_results.png"), full_page=True)
        print("  [15/18] Test Run Results")

        # 16. Results Detail Modal (click Detail on first comparison)
        detail_btn = page.query_selector('button:has-text("Detail")')
        if detail_btn:
            detail_btn.click()
            time.sleep(1)
            page.screenshot(path=os.path.join(output_dir, "16_results_detail_modal.png"), full_page=True)
            print("  [16/18] Results Detail Modal (with normalized ratios)")
            # Close modal
            close_btn = page.query_selector('#detail-modal .btn-close')
            if close_btn:
                close_btn.click()
                time.sleep(0.5)

        # 17. Calibration Results
        page.goto(f"{base_url}/test-runs/1/calibration")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "17_test_run_calibration.png"), full_page=True)
        print("  [17/18] Calibration Results")

        # 18. Trending Page
        page.goto(f"{base_url}/trending")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        # Select agent in filter
        agent_select = page.query_selector('#filter-agent')
        if agent_select:
            page.select_option('#filter-agent', index=1)
            time.sleep(1)
        page.screenshot(path=os.path.join(output_dir, "18_trending.png"), full_page=True)
        print("  [18/18] Trending Page")

        browser.close()
        print(f"\nAll screenshots saved to: {output_dir}")


if __name__ == "__main__":
    # Remove old DB
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        pass

    print("Seeding sample data...")
    seed_data()

    print("Starting server on http://127.0.0.1:9876 ...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Wait for server to start

    print("Taking screenshots...")
    take_screenshots()

    # Cleanup (ignore errors — server thread may still hold file)
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        print(f"Note: could not remove {DB_PATH} (still in use). Delete manually.")
    print("Done!")
