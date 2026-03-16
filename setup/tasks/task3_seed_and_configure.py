"""Task 3: Create DB schema, seed data, and generate credentials.json.

Requires PostgreSQL to be running (install it first, or run task4 before this).
Steps:
  1. Create PostgreSQL database and user (if not existing)
  2. Run alembic migrations to create all tables
  3. Seed: lab, hardware_profiles, servers, load_profiles, baselines, admin user
  4. Generate credentials.json for the orchestrator
"""

import json
import logging
import os
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .common import (
    SetupConfig, ServerEntry,
    load_servers, load_credentials, validate_servers,
)

logger = logging.getLogger("setup.task3")


def _build_db_url(config: SetupConfig) -> str:
    return (f"postgresql://{config.postgres_user}:{config.postgres_password}"
            f"@{config.postgres_host}:{config.postgres_port}/{config.postgres_db}")


def _create_postgres_db(config: SetupConfig):
    """Verify PostgreSQL database and user exist and are accessible."""
    logger.info("Checking PostgreSQL database '%s' ...", config.postgres_db)

    # Try connecting as the orchestrator user directly
    db_url = _build_db_url(config)
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        logger.info("  Database '%s' is accessible as user '%s'",
                     config.postgres_db, config.postgres_user)
        return
    except Exception as e:
        logger.warning("  Cannot connect as '%s': %s", config.postgres_user, e)

    # If direct connect fails, tell user to run install_postgres.sh
    logger.error("PostgreSQL database not accessible. Run install_postgres.sh first:")
    logger.error("  bash install_postgres.sh %s %s %s",
                 config.postgres_db, config.postgres_user, config.postgres_password)
    raise RuntimeError(f"Cannot connect to PostgreSQL: {config.postgres_db}")


def _ensure_src_path(config: SetupConfig):
    """Add orchestrator src to sys.path so ORM models can be imported."""
    src_path = os.path.join(config.repo_path, "orchestrator", "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _create_tables(config: SetupConfig):
    """Create all tables from ORM models."""
    _ensure_src_path(config)

    from orchestrator.models.database import Base
    import orchestrator.models.orm  # noqa: F401 — registers all models

    db_url = _build_db_url(config)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    logger.info("  All tables created")


def _load_discovery(config: SetupConfig) -> dict:
    """Load discovery_output.json if it exists."""
    if os.path.exists(config.discovery_file):
        with open(config.discovery_file) as f:
            return json.load(f)
    logger.warning("Discovery file not found at %s — using defaults from servers.csv", config.discovery_file)
    return {}


def _seed_data(config: SetupConfig):
    """Seed the database with lab, servers, load profiles, etc."""
    _ensure_src_path(config)

    from orchestrator.models.orm import (
        UserORM, LabORM, LoadProfileORM, HardwareProfileORM, ServerORM,
    )
    from orchestrator.models.enums import (
        OSFamily, HypervisorType, ServerInfraType, DiskType, ExecutionMode,
    )

    db_url = _build_db_url(config)
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    discovery = _load_discovery(config)

    try:
        # --- 1. Admin user ---
        existing_user = session.query(UserORM).filter_by(username="admin").first()
        if not existing_user:
            import bcrypt
            admin = UserORM(
                username="admin",
                password_hash=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
                email="admin@orchestrator.local",
                role="admin",
                is_active=True,
            )
            session.add(admin)
            logger.info("  Seeded admin user")
        else:
            logger.info("  Admin user already exists")

        # --- 2. Lab ---
        existing_lab = session.query(LabORM).filter_by(name=config.lab_name).first()
        if not existing_lab:
            lab = LabORM(
                name=config.lab_name,
                description=config.lab_description,
                hypervisor_type=HypervisorType.vsphere,
                hypervisor_manager_url=config.vsphere_host,
                hypervisor_manager_port=config.vsphere_port,
                execution_mode=ExecutionMode.baseline_compare,
            )
            session.add(lab)
            session.flush()
            lab_id = lab.id
            logger.info("  Seeded lab: %s (id=%d)", config.lab_name, lab_id)
        else:
            lab_id = existing_lab.id
            logger.info("  Lab '%s' already exists (id=%d)", config.lab_name, lab_id)

        # --- 3. Load profiles ---
        for lp in config.load_profiles:
            existing = session.query(LoadProfileORM).filter_by(name=lp["name"]).first()
            if not existing:
                profile = LoadProfileORM(
                    name=lp["name"],
                    target_cpu_range_min=lp["target_cpu_min"],
                    target_cpu_range_max=lp["target_cpu_max"],
                    duration_sec=lp["duration_sec"],
                    ramp_up_sec=lp["ramp_up_sec"],
                )
                session.add(profile)
                logger.info("  Seeded load profile: %s", lp["name"])
            else:
                logger.info("  Load profile '%s' already exists", lp["name"])

        # --- 4. Hardware profiles + Servers ---
        hw_cache = {}  # (cpu, mem_gb) -> hardware_profile_id

        for server in servers:
            disc = discovery.get(server.hostname, {})
            cpu_count = disc.get("cpu_count", 4)
            memory_gb = disc.get("memory_gb", 8)
            total_disk_gb = disc.get("total_disk_gb", 100)
            disk_type_str = disc.get("disk_type", "ssd")

            # Hardware profile — deduplicate by (cpu, mem)
            hw_key = (cpu_count, memory_gb)
            if hw_key not in hw_cache:
                hw_name = f"{cpu_count}cpu_{memory_gb}gb"
                existing_hw = session.query(HardwareProfileORM).filter_by(name=hw_name).first()
                if not existing_hw:
                    hw = HardwareProfileORM(
                        name=hw_name,
                        cpu_count=cpu_count,
                        memory_gb=memory_gb,
                        disk_type=DiskType.ssd if disk_type_str == "ssd" else DiskType.hdd,
                        disk_size_gb=total_disk_gb,
                    )
                    session.add(hw)
                    session.flush()
                    hw_cache[hw_key] = hw.id
                    logger.info("  Seeded hardware profile: %s (id=%d)", hw_name, hw.id)
                else:
                    hw_cache[hw_key] = existing_hw.id
            hw_profile_id = hw_cache[hw_key]

            # Server
            existing_srv = session.query(ServerORM).filter_by(ip_address=server.ip).first()
            if not existing_srv:
                os_family = OSFamily.linux if server.is_linux else OSFamily.windows

                # Build vsphere provider_ref from discovery
                vm_moref = disc.get("vm_moref")
                provider_ref = {}
                if vm_moref:
                    provider_ref = {
                        "vm_moref": vm_moref,
                        "vm_name": disc.get("vm_name", server.hostname),
                        "datacenter": disc.get("folder", ""),
                        "datastore": disc.get("datastores", [""])[0] if disc.get("datastores") else "",
                    }

                srv = ServerORM(
                    hostname=server.hostname,
                    ip_address=server.ip,
                    os_family=os_family,
                    os_vendor_family=server.os_vendor_family,
                    os_major_ver=server.os_major_ver,
                    lab_id=lab_id,
                    hardware_profile_id=hw_profile_id,
                    server_infra_type=ServerInfraType.vsphere_vm,
                    server_infra_ref=provider_ref,
                )
                session.add(srv)
                session.flush()
                logger.info("  Seeded server: %s (id=%d, role=%s)", server.hostname, srv.id, server.role)
            else:
                logger.info("  Server '%s' already exists (id=%d)", server.hostname, existing_srv.id)

        # --- 5. Set default loadgen assignments for targets ---
        session.flush()
        all_servers = {s.hostname: s for s in session.query(ServerORM).all()}
        loadgens = [s for s in servers if s.role == "loadgen"]

        if loadgens:
            # Get the first loadgen server ID for default assignment
            first_lg_hostname = loadgens[0].hostname
            first_lg = all_servers.get(first_lg_hostname)
            if first_lg:
                for server in servers:
                    if server.role == "target":
                        srv_obj = all_servers.get(server.hostname)
                        if srv_obj and not srv_obj.default_loadgen_id:
                            srv_obj.default_loadgen_id = first_lg.id
                            logger.info("  Assigned default loadgen %s -> target %s",
                                        first_lg_hostname, server.hostname)

        session.commit()
        logger.info("  Database seeded successfully")

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def _generate_credentials_json(config: SetupConfig):
    """Generate orchestrator credentials.json from mycred.txt and servers.csv."""
    creds = load_credentials(config.credentials_file)
    servers = load_servers(config.servers_file)

    # Build per-server credentials using the service account
    by_server_id = {}
    _ensure_src_path(config)

    db_url = _build_db_url(config)
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        from orchestrator.models.orm import ServerORM as SrvORM
        db_servers = {s.hostname: s for s in session.query(SrvORM).all()}

        for server in servers:
            srv_obj = db_servers.get(server.hostname)
            if srv_obj:
                by_server_id[str(srv_obj.id)] = {
                    "username": creds.svc_user,
                    "password": creds.svc_pass,
                }
    finally:
        session.close()
        engine.dispose()

    credentials_data = {
        "servers": {
            "by_server_id": by_server_id,
            "by_os_type": {
                "linux": {
                    "username": creds.svc_user,
                    "password": creds.svc_pass,
                },
                "windows": {
                    "username": creds.svc_user,
                    "password": creds.svc_pass,
                },
            },
        },
        "vsphere": {
            "username": creds.vsphere_user,
            "password": creds.vsphere_pass,
            "verify_ssl": False,
        },
    }

    # Write to orchestrator config dir
    output_path = os.path.join(config.repo_path, "orchestrator", "config", "credentials.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(credentials_data, f, indent=2)

    # Also write a copy to setup output dir
    with open(config.credentials_json_path, "w") as f:
        json.dump(credentials_data, f, indent=2)

    logger.info("  Generated credentials.json at:")
    logger.info("    %s", output_path)
    logger.info("    %s", config.credentials_json_path)


def _update_orchestrator_yaml(config: SetupConfig):
    """Update orchestrator.yaml with the correct database URL."""
    import yaml

    yaml_path = os.path.join(config.repo_path, "orchestrator", "config", "orchestrator.yaml")
    if not os.path.exists(yaml_path):
        logger.warning("orchestrator.yaml not found at %s", yaml_path)
        return

    with open(yaml_path) as f:
        orch_config = yaml.safe_load(f)

    db_url = _build_db_url(config)
    orch_config["database"]["url"] = db_url

    with open(yaml_path, "w") as f:
        yaml.dump(orch_config, f, default_flow_style=False, sort_keys=False)

    logger.info("  Updated orchestrator.yaml database.url")


def run(config: SetupConfig):
    """Run Task 3: create schema, seed DB, generate credentials.json."""
    logger.info("=" * 60)
    logger.info("TASK 3: Create schema, seed database, generate credentials")
    logger.info("  Database: %s@%s:%d/%s",
                config.postgres_user, config.postgres_host, config.postgres_port, config.postgres_db)
    logger.info("=" * 60)

    # Step 1: Create PostgreSQL DB + user
    logger.info("[Step 1/5] Creating PostgreSQL database ...")
    _create_postgres_db(config)

    # Step 2: Create tables
    logger.info("[Step 2/5] Creating table schema ...")
    _create_tables(config)

    # Step 3: Seed data
    logger.info("[Step 3/5] Seeding database ...")
    _seed_data(config)

    # Step 4: Generate credentials.json
    logger.info("[Step 4/5] Generating credentials.json ...")
    _generate_credentials_json(config)

    # Step 5: Update orchestrator.yaml
    logger.info("[Step 5/5] Updating orchestrator.yaml ...")
    _update_orchestrator_yaml(config)

    logger.info("-" * 60)
    logger.info("Task 3 complete.")
    return True
