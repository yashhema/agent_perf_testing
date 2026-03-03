"""Web view routes serving Jinja2 HTML templates.

All pages are HTML shells — data loading is done client-side via JavaScript
calling the existing REST API endpoints with JWT auth.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(tags=["web"])


# ---- Login ----

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# ---- Admin Dashboard ----

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request})


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request})


# ---- Admin CRUD pages ----
# Each passes a config dict to the generic crud.html template

_ENUM_OPTIONS = {
    "hypervisor_type": ["proxmox", "vsphere", "vultr"],
    "os_family": ["linux", "windows"],
    "server_infra_type": ["proxmox_vm", "vsphere_vm", "vultr_instance"],
    "baseline_type": ["proxmox", "vsphere", "vultr"],
    "db_type": ["mssql", "postgresql"],
    "disk_type": ["ssd", "hdd"],
    "template_type": ["server-normal", "server-file-heavy", "db-load"],
    "functional_test_phase": ["base", "initial"],
    "run_mode": ["complete", "step_by_step"],
}


@router.get("/admin/labs", response_class=HTMLResponse)
async def admin_labs(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Labs",
        "entity_name": "Lab",
        "api_path": "/api/admin/labs",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "name", "label": "Name"},
            {"key": "hypervisor_type", "label": "Hypervisor"},
            {"key": "hypervisor_manager_url", "label": "Manager URL"},
            {"key": "hypervisor_manager_port", "label": "Port"},
            {"key": "created_at", "label": "Created", "type": "date"},
        ],
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "description", "label": "Description", "type": "textarea"},
            {"key": "hypervisor_type", "label": "Hypervisor Type", "type": "select",
             "options": _ENUM_OPTIONS["hypervisor_type"], "required": True},
            {"key": "hypervisor_manager_url", "label": "Manager URL", "type": "text", "required": True},
            {"key": "hypervisor_manager_port", "label": "Manager Port", "type": "number", "required": True},
            {"key": "jmeter_package_grpid", "label": "JMeter Package Group ID", "type": "number", "required": True},
            {"key": "loadgen_snapshot_id", "label": "Load Gen Snapshot ID", "type": "number", "required": True},
        ],
    })


@router.get("/admin/hardware-profiles", response_class=HTMLResponse)
async def admin_hardware_profiles(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Hardware Profiles",
        "entity_name": "Hardware Profile",
        "api_path": "/api/admin/hardware-profiles",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "name", "label": "Name"},
            {"key": "vendor", "label": "Vendor"},
            {"key": "cpu_count", "label": "CPUs"},
            {"key": "memory_gb", "label": "Memory (GB)"},
            {"key": "disk_type", "label": "Disk Type"},
            {"key": "disk_size_gb", "label": "Disk (GB)"},
        ],
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "vendor", "label": "Vendor", "type": "text"},
            {"key": "cpu_count", "label": "CPU Count", "type": "number", "required": True},
            {"key": "cpu_model", "label": "CPU Model", "type": "text"},
            {"key": "memory_gb", "label": "Memory (GB)", "type": "number", "step": "0.1", "required": True},
            {"key": "disk_type", "label": "Disk Type", "type": "select",
             "options": _ENUM_OPTIONS["disk_type"], "required": True},
            {"key": "disk_size_gb", "label": "Disk Size (GB)", "type": "number", "step": "0.1", "required": True},
            {"key": "nic_speed_mbps", "label": "NIC Speed (Mbps)", "type": "number"},
        ],
    })


@router.get("/admin/servers", response_class=HTMLResponse)
async def admin_servers(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Servers",
        "entity_name": "Server",
        "api_path": "/api/admin/servers",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "hostname", "label": "Hostname"},
            {"key": "ip_address", "label": "IP Address"},
            {"key": "os_family", "label": "OS"},
            {"key": "lab_id", "label": "Lab ID"},
            {"key": "hardware_profile_id", "label": "HW Profile ID"},
            {"key": "created_at", "label": "Created", "type": "date"},
        ],
        "fields": [
            {"key": "hostname", "label": "Hostname", "type": "text", "required": True},
            {"key": "ip_address", "label": "IP Address", "type": "text", "required": True},
            {"key": "os_family", "label": "OS Family", "type": "select",
             "options": _ENUM_OPTIONS["os_family"], "required": True},
            {"key": "lab_id", "label": "Lab ID", "type": "number", "required": True},
            {"key": "hardware_profile_id", "label": "Hardware Profile ID", "type": "number", "required": True},
            {"key": "server_infra_type", "label": "Infra Type", "type": "select",
             "options": _ENUM_OPTIONS["server_infra_type"], "required": True},
            {"key": "server_infra_ref", "label": "Infra Ref (JSON)", "type": "json", "required": True},
            {"key": "baseline_id", "label": "Baseline ID", "type": "number"},
            {"key": "db_type", "label": "DB Type", "type": "select",
             "options": _ENUM_OPTIONS["db_type"]},
            {"key": "db_port", "label": "DB Port", "type": "number"},
            {"key": "db_name", "label": "DB Name", "type": "text"},
            {"key": "db_user", "label": "DB User", "type": "text"},
            {"key": "db_password", "label": "DB Password", "type": "password"},
        ],
    })


@router.get("/admin/baselines", response_class=HTMLResponse)
async def admin_baselines(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Baselines / Snapshots",
        "entity_name": "Baseline",
        "api_path": "/api/admin/baselines",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "name", "label": "Name"},
            {"key": "os_family", "label": "OS"},
            {"key": "os_vendor_family", "label": "Vendor"},
            {"key": "os_major_ver", "label": "Major Ver"},
            {"key": "baseline_type", "label": "Type"},
            {"key": "created_at", "label": "Created", "type": "date"},
        ],
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "os_family", "label": "OS Family", "type": "select",
             "options": _ENUM_OPTIONS["os_family"], "required": True},
            {"key": "os_vendor_family", "label": "OS Vendor Family", "type": "text", "required": True},
            {"key": "os_major_ver", "label": "OS Major Version", "type": "text", "required": True},
            {"key": "os_minor_ver", "label": "OS Minor Version", "type": "text"},
            {"key": "os_kernel_ver", "label": "OS Kernel Version", "type": "text"},
            {"key": "db_type", "label": "DB Type", "type": "select",
             "options": _ENUM_OPTIONS["db_type"]},
            {"key": "baseline_type", "label": "Baseline Type", "type": "select",
             "options": _ENUM_OPTIONS["baseline_type"], "required": True},
            {"key": "provider_ref", "label": "Provider Ref (JSON)", "type": "json", "required": True},
        ],
    })


@router.get("/admin/packages", response_class=HTMLResponse)
async def admin_packages(request: Request):
    return templates.TemplateResponse("admin/packages.html", {"request": request})


@router.get("/admin/scenarios", response_class=HTMLResponse)
async def admin_scenarios(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Scenarios",
        "entity_name": "Scenario",
        "api_path": "/api/admin/scenarios",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "name", "label": "Name"},
            {"key": "lab_id", "label": "Lab ID"},
            {"key": "template_type", "label": "Template"},
            {"key": "has_base_phase", "label": "Base", "type": "bool"},
            {"key": "has_initial_phase", "label": "Initial", "type": "bool"},
            {"key": "has_dbtest", "label": "DB Test", "type": "bool"},
            {"key": "created_at", "label": "Created", "type": "date"},
        ],
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "description", "label": "Description", "type": "textarea"},
            {"key": "lab_id", "label": "Lab ID", "type": "number", "required": True},
            {"key": "template_type", "label": "Template Type", "type": "select",
             "options": _ENUM_OPTIONS["template_type"], "required": True},
            {"key": "has_base_phase", "label": "Has Base Phase", "type": "checkbox", "default": True},
            {"key": "has_initial_phase", "label": "Has Initial Phase", "type": "checkbox", "default": True},
            {"key": "has_dbtest", "label": "Has DB Test", "type": "checkbox"},
            {"key": "load_generator_package_grp_id", "label": "Load Gen Package Group ID",
             "type": "number", "required": True},
            {"key": "initial_package_grp_id", "label": "Initial Package Group ID", "type": "number"},
            {"key": "other_package_grp_ids", "label": "Other Package Group IDs (JSON array)",
             "type": "json-array"},
            {"key": "functional_package_grp_id", "label": "Functional Package Group ID", "type": "number"},
            {"key": "functional_test_phase", "label": "Functional Test Phase", "type": "select",
             "options": _ENUM_OPTIONS["functional_test_phase"]},
        ],
    })


@router.get("/admin/agents", response_class=HTMLResponse)
async def admin_agents(request: Request):
    return templates.TemplateResponse("admin/agents.html", {"request": request})


@router.get("/admin/load-profiles", response_class=HTMLResponse)
async def admin_load_profiles(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Load Profiles",
        "entity_name": "Load Profile",
        "api_path": "/api/admin/load-profiles",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "name", "label": "Name"},
            {"key": "target_cpu_range_min", "label": "CPU Min %"},
            {"key": "target_cpu_range_max", "label": "CPU Max %"},
            {"key": "duration_sec", "label": "Duration (s)"},
            {"key": "ramp_up_sec", "label": "Ramp-up (s)"},
        ],
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "target_cpu_range_min", "label": "Target CPU Min %", "type": "number",
             "step": "0.1", "required": True},
            {"key": "target_cpu_range_max", "label": "Target CPU Max %", "type": "number",
             "step": "0.1", "required": True},
            {"key": "duration_sec", "label": "Duration (seconds)", "type": "number", "required": True},
            {"key": "ramp_up_sec", "label": "Ramp-up (seconds)", "type": "number", "required": True},
        ],
    })


@router.get("/admin/db-schema-config", response_class=HTMLResponse)
async def admin_db_schema_config(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "DB Schema Config",
        "entity_name": "DB Schema Config",
        "api_path": "/api/admin/db-schema-configs",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "db_type", "label": "DB Type"},
            {"key": "schema_path", "label": "Schema Path"},
            {"key": "seed_data_path", "label": "Seed Data Path"},
            {"key": "param_csv_path", "label": "Param CSV Path"},
        ],
        "fields": [
            {"key": "db_type", "label": "DB Type", "type": "select",
             "options": _ENUM_OPTIONS["db_type"], "required": True},
            {"key": "schema_path", "label": "Schema Path", "type": "text", "required": True},
            {"key": "seed_data_path", "label": "Seed Data Path", "type": "text", "required": True},
            {"key": "param_csv_path", "label": "Param CSV Path", "type": "text"},
        ],
    })


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    return templates.TemplateResponse("admin/crud.html", {
        "request": request,
        "page_title": "Users",
        "entity_name": "User",
        "api_path": "/api/admin/users",
        "columns": [
            {"key": "id", "label": "ID"},
            {"key": "username", "label": "Username"},
            {"key": "email", "label": "Email"},
            {"key": "role", "label": "Role"},
            {"key": "is_active", "label": "Active", "type": "bool"},
            {"key": "created_at", "label": "Created", "type": "date"},
        ],
        "fields": [
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "email", "label": "Email", "type": "text"},
            {"key": "role", "label": "Role", "type": "select", "options": ["user", "admin"], "required": True},
            {"key": "is_active", "label": "Active", "type": "checkbox", "default": True},
        ],
    })


# ---- Test Run Pages ----

@router.get("/test-runs", response_class=HTMLResponse)
async def test_run_list(request: Request):
    return templates.TemplateResponse("test_runs/list.html", {"request": request})


@router.get("/test-runs/create", response_class=HTMLResponse)
async def test_run_create(request: Request):
    return templates.TemplateResponse("test_runs/create.html", {"request": request})


@router.get("/test-runs/{run_id}/dashboard", response_class=HTMLResponse)
async def test_run_dashboard(request: Request, run_id: int):
    return templates.TemplateResponse("test_runs/dashboard.html", {
        "request": request, "run_id": run_id,
    })


@router.get("/test-runs/{run_id}/results", response_class=HTMLResponse)
async def test_run_results(request: Request, run_id: int):
    return templates.TemplateResponse("test_runs/results.html", {
        "request": request, "run_id": run_id,
    })


@router.get("/test-runs/{run_id}/calibration", response_class=HTMLResponse)
async def test_run_calibration(request: Request, run_id: int):
    return templates.TemplateResponse("test_runs/calibration.html", {
        "request": request, "run_id": run_id,
    })


# ---- Analytics ----

@router.get("/trending", response_class=HTMLResponse)
async def trending_page(request: Request):
    return templates.TemplateResponse("trending/index.html", {"request": request})
