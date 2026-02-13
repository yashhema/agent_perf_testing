"""Take screenshots of all 5 Create Test Run wizard steps.

Reuses the existing take_screenshots.py infrastructure (SQLite DB, sample data, server)
but focuses only on the wizard, filling in data at each step.
"""

import sys
import os
import time
import threading
import uuid as _uuid

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ---- Import ORM models first (registers them with Base.metadata) ----
from orchestrator.models.database import Base
import orchestrator.models.database as db_mod
from orchestrator.models.orm import (
    HardwareProfileORM, LabORM, ServerORM, BaselineORM,
    PackageGroupORM, PackageGroupMemberORM, ScenarioORM,
    LoadProfileORM, TestRunORM, TestRunTargetORM,
    TestRunLoadProfileORM, CalibrationResultORM,
    PhaseExecutionResultORM, ComparisonResultORM, UserORM,
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

# ---- Setup SQLite database ----
DB_PATH = os.path.join(os.path.dirname(__file__), "screenshots", f"_wizard_{_uuid.uuid4().hex[:8]}.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

db_mod.engine = engine
db_mod.SessionLocal.configure(bind=engine)


def seed_data():
    session = Session()

    admin = UserORM(username="admin", password_hash=hash_password("admin"),
                    email="admin@orchestrator.local", role="admin", is_active=True)
    session.add(admin)

    hp1 = HardwareProfileORM(name="Standard VM", cpu_count=4, cpu_model="Xeon E5-2680 v4",
                             memory_gb=16.0, disk_type=DiskType.ssd, disk_size_gb=100.0, nic_speed_mbps=1000)
    hp2 = HardwareProfileORM(name="High-Memory VM", cpu_count=8, cpu_model="Xeon E5-2680 v4",
                             memory_gb=32.0, disk_type=DiskType.ssd, disk_size_gb=200.0, nic_speed_mbps=1000)
    hp3 = HardwareProfileORM(name="Load Gen VM", cpu_count=4, cpu_model="Xeon E5-2680 v4",
                             memory_gb=8.0, disk_type=DiskType.hdd, disk_size_gb=50.0, nic_speed_mbps=1000)
    session.add_all([hp1, hp2, hp3])
    session.flush()

    b1 = BaselineORM(name="Ubuntu 22.04 Base", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref={"node": "pve1", "vmid": 100, "snapshot": "base-clean"})
    b2 = BaselineORM(name="Ubuntu 22.04 Initial", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref={"node": "pve1", "vmid": 100, "snapshot": "initial-agent"})
    b3 = BaselineORM(name="Win Server 2022 Base", os_family=OSFamily.windows,
                     os_vendor_family="windows_server", os_major_ver="2022",
                     baseline_type=BaselineType.vsphere,
                     provider_ref={"datacenter": "DC1", "vm": "win-srv-01", "snapshot": "base"})
    b4 = BaselineORM(name="Load Gen Ubuntu", os_family=OSFamily.linux,
                     os_vendor_family="ubuntu", os_major_ver="22", os_minor_ver="04",
                     baseline_type=BaselineType.proxmox,
                     provider_ref={"node": "pve1", "vmid": 105, "snapshot": "loadgen-ready"})
    session.add_all([b1, b2, b3, b4])
    session.flush()

    pg1 = PackageGroupORM(name="JMeter 5.6.3", description="Apache JMeter load generator")
    pg2 = PackageGroupORM(name="Emulator v2.1", description="Performance emulator agent")
    pg3 = PackageGroupORM(name="Agent v3.5.0", description="Monitoring agent under test")
    session.add_all([pg1, pg2, pg3])
    session.flush()

    session.add_all([
        PackageGroupMemberORM(package_group_id=pg1.id, os_match_regex=".*linux.*",
                              path="/packages/jmeter-5.6.3.tar.gz", root_install_path="/opt/jmeter",
                              extraction_command="tar xzf jmeter-5.6.3.tar.gz",
                              run_command="/opt/jmeter/bin/jmeter.sh",
                              status_command="pgrep -f jmeter"),
        PackageGroupMemberORM(package_group_id=pg2.id, os_match_regex=".*linux.*",
                              path="/packages/emulator-2.1-linux.tar.gz", root_install_path="/opt/emulator"),
        PackageGroupMemberORM(package_group_id=pg3.id, os_match_regex=".*linux.*",
                              path="/packages/agent-3.5.0-linux.deb", root_install_path="/opt/agent"),
    ])
    session.flush()

    lab1 = LabORM(name="Proxmox Lab A", description="Primary test lab - 6 VMs, Proxmox cluster",
                  jmeter_package_grpid=pg1.id, loadgen_snapshot_id=b4.id,
                  hypervisor_type=HypervisorType.proxmox,
                  hypervisor_manager_url="https://pve1.lab.local", hypervisor_manager_port=8006)
    lab2 = LabORM(name="vSphere Lab B", description="Secondary lab - vSphere, Windows servers",
                  jmeter_package_grpid=pg1.id, loadgen_snapshot_id=b4.id,
                  hypervisor_type=HypervisorType.vsphere,
                  hypervisor_manager_url="https://vcenter.lab.local", hypervisor_manager_port=443)
    session.add_all([lab1, lab2])
    session.flush()

    s1 = ServerORM(hostname="target-01", ip_address="10.0.1.101", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp1.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref={"node": "pve1", "vmid": 101}, baseline_id=b1.id)
    s2 = ServerORM(hostname="target-02", ip_address="10.0.1.102", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp2.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref={"node": "pve1", "vmid": 102}, baseline_id=b1.id)
    s3 = ServerORM(hostname="loadgen-01", ip_address="10.0.1.105", os_family=OSFamily.linux,
                   lab_id=lab1.id, hardware_profile_id=hp3.id,
                   server_infra_type=ServerInfraType.proxmox_vm,
                   server_infra_ref={"node": "pve1", "vmid": 105})
    session.add_all([s1, s2, s3])
    session.flush()

    lp1 = LoadProfileORM(name="low", target_cpu_range_min=20.0, target_cpu_range_max=40.0,
                         duration_sec=300, ramp_up_sec=30)
    lp2 = LoadProfileORM(name="medium", target_cpu_range_min=40.0, target_cpu_range_max=60.0,
                         duration_sec=600, ramp_up_sec=60)
    lp3 = LoadProfileORM(name="high", target_cpu_range_min=60.0, target_cpu_range_max=80.0,
                         duration_sec=600, ramp_up_sec=60)
    session.add_all([lp1, lp2, lp3])
    session.flush()

    sc1 = ScenarioORM(name="Server Normal - Agent v3.5", description="Standard server workload with agent monitoring overhead measurement",
                      lab_id=lab1.id, template_type=TemplateType.server_normal,
                      has_base_phase=True, has_initial_phase=True, has_dbtest=False,
                      load_generator_package_grp_id=pg2.id, initial_package_grp_id=pg3.id)
    session.add(sc1)
    session.commit()
    session.close()
    print("Sample data seeded")


def run_server():
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    application = FastAPI(title="Orchestrator", lifespan=noop_lifespan)
    static_dir = Path(__file__).resolve().parent / "src" / "orchestrator" / "static"
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from orchestrator.api.auth import router as auth_router
    from orchestrator.api.admin import router as admin_router
    from orchestrator.api.test_runs import router as test_runs_router
    from orchestrator.web.views import router as web_router
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(test_runs_router)
    application.include_router(web_router)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    uvicorn.run(application, host="127.0.0.1", port=9877, log_level="warning")


def take_wizard_screenshots():
    from playwright.sync_api import sync_playwright

    output_dir = os.path.join(os.path.dirname(__file__), "screenshots")
    base_url = "http://127.0.0.1:9877"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # Login first
        page.goto(f"{base_url}/login")
        page.wait_for_load_state("networkidle")
        page.fill("#username", "admin")
        page.fill("#password", "admin")
        page.click("#btn-login")
        page.wait_for_url("**/admin/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        print("  Logged in")

        # Navigate to Create Test Run
        page.goto(f"{base_url}/test-runs/create")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)  # wait for labs + profiles to load

        # ============================================================
        # STEP 1: Scenario — select lab then scenario
        # ============================================================
        # Select lab "Proxmox Lab A" (id=1)
        page.select_option("#sel-lab", "1")
        time.sleep(1)  # wait for scenarios to load

        # Select scenario (id=1)
        page.select_option("#sel-scenario", "1")
        time.sleep(0.5)  # wait for scenario details to render

        page.screenshot(path=os.path.join(output_dir, "wizard_step1_scenario.png"), full_page=True)
        print("  [1/5] Step 1: Scenario")

        # ============================================================
        # STEP 2: Load Profiles — click Next, then check profiles
        # ============================================================
        page.click("#btn-next-1")
        time.sleep(0.5)

        # Check "low" and "medium" profiles
        page.check("#lp-1")
        page.check("#lp-2")
        time.sleep(0.3)

        page.screenshot(path=os.path.join(output_dir, "wizard_step2_load_profiles.png"), full_page=True)
        print("  [2/5] Step 2: Load Profiles")

        # ============================================================
        # STEP 3: Settings — click Next, set cycles and mode
        # ============================================================
        page.click("#btn-next-2")
        time.sleep(0.5)

        # Set cycles to 2
        page.fill("#inp-cycles", "2")
        # Select "complete" mode (default, but make sure)
        page.select_option("#sel-mode", "complete")
        time.sleep(0.3)

        page.screenshot(path=os.path.join(output_dir, "wizard_step3_settings.png"), full_page=True)
        print("  [3/5] Step 3: Settings")

        # ============================================================
        # STEP 4: Targets — click Next, add two target rows
        # ============================================================
        # Click the "Next" button in step 3 footer
        page.click('div#step-3 .card-footer button.btn-primary')
        time.sleep(0.5)

        # Add first target row
        page.click('button:has-text("Add Target")')
        time.sleep(0.3)

        # Fill first target: target-01, loadgen-01, base snap, initial snap
        page.select_option("#t-target-0", "1")     # target-01
        page.select_option("#t-loadgen-0", "3")     # loadgen-01
        page.select_option("#t-base-snap-0", "1")   # Ubuntu 22.04 Base
        page.select_option("#t-init-snap-0", "2")   # Ubuntu 22.04 Initial
        page.fill("#t-patterns-0", '["agent", "emulator"]')

        # Add second target row
        page.click('button:has-text("Add Target")')
        time.sleep(0.3)

        page.select_option("#t-target-1", "2")     # target-02
        page.select_option("#t-loadgen-1", "3")     # loadgen-01
        page.select_option("#t-base-snap-1", "1")   # Ubuntu 22.04 Base
        page.select_option("#t-init-snap-1", "2")   # Ubuntu 22.04 Initial
        page.fill("#t-patterns-1", '["agent"]')
        time.sleep(0.3)

        page.screenshot(path=os.path.join(output_dir, "wizard_step4_targets.png"), full_page=True)
        print("  [4/5] Step 4: Targets")

        # ============================================================
        # STEP 5: Review — click Review button
        # ============================================================
        page.click('div#step-4 .card-footer button.btn-primary')
        time.sleep(0.8)  # wait for review to build

        page.screenshot(path=os.path.join(output_dir, "wizard_step5_review.png"), full_page=True)
        print("  [5/5] Step 5: Review")

        browser.close()
        print(f"\nAll wizard screenshots saved to: {output_dir}")


if __name__ == "__main__":
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        pass

    print("Seeding sample data...")
    seed_data()

    print("Starting server on http://127.0.0.1:9877 ...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    print("Taking wizard screenshots...")
    take_wizard_screenshots()

    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        print(f"Note: could not remove {DB_PATH}. Delete manually.")
    print("Done!")
