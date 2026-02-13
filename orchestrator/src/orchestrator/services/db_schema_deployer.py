"""DB schema deployment service.

Phase 8.4: Deploys database schema (DDL + seed data) to target servers
that have has_dbtest=True, then creates db-ready snapshots so subsequent
test cycles can restore directly to a seeded database state.

Process:
  1. Check if db_ready_base_snapshot_id / db_ready_initial_snapshot_id are already populated
  2. If not: restore base/initial snapshot → deploy schema → load seed data → create snapshot
  3. Store the new snapshot IDs back on TestRunTargetORM

This service is called during the setup phase (_do_setup) when the scenario
has has_dbtest=True.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.infra.hypervisor import HypervisorProvider
from orchestrator.infra.remote_executor import RemoteExecutor, create_executor
from orchestrator.models.enums import DBType
from orchestrator.models.orm import (
    BaselineORM,
    DBSchemaConfigORM,
    LabORM,
    ScenarioORM,
    ServerORM,
    TestRunORM,
    TestRunTargetORM,
)

# Import db-assets generators
_GENERATOR_ROOT = str(
    Path(__file__).resolve().parents[4] / "db-assets"
)
if _GENERATOR_ROOT not in sys.path:
    sys.path.insert(0, _GENERATOR_ROOT)

from generator.generators.schema_generator import SchemaGenerator
from generator.generators.seed_generator import SeedDataGenerator

logger = logging.getLogger(__name__)


class DBSchemaDeployer:
    """Deploys database schemas to target servers and creates db-ready snapshots."""

    def __init__(
        self,
        config: AppConfig,
        credentials: CredentialsStore,
        hypervisor: HypervisorProvider,
    ):
        self._config = config
        self._credentials = credentials
        self._hypervisor = hypervisor

    def deploy_for_test_run(self, session: Session, test_run: TestRunORM) -> None:
        """Deploy DB schema for all targets in a test run that need it.

        Only operates when the scenario has has_dbtest=True. Skips targets
        that already have db_ready snapshot IDs populated.
        """
        scenario = session.get(ScenarioORM, test_run.scenario_id)
        if not scenario.has_dbtest:
            logger.info("Scenario %s does not have DB test, skipping schema deployment", scenario.name)
            return

        lab = session.get(LabORM, test_run.lab_id)
        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)

            if not server.db_type:
                logger.warning("Server %s has no db_type configured, skipping", server.hostname)
                continue

            db_type = server.db_type.value

            # Generate schema files if they don't exist
            schema_dir = self._ensure_schema_generated(session, db_type)

            # Deploy for base snapshot
            if not target_config.db_ready_base_snapshot_id:
                logger.info("Creating db-ready base snapshot for server %s", server.hostname)
                base_snap_id = self._deploy_and_snapshot(
                    session=session,
                    server=server,
                    source_snapshot_id=target_config.base_snapshot_id,
                    schema_dir=schema_dir,
                    db_type=db_type,
                    snapshot_label=f"dbready_base_{test_run.id}_{server.id}",
                )
                if base_snap_id:
                    target_config.db_ready_base_snapshot_id = base_snap_id

            # Deploy for initial snapshot
            if not target_config.db_ready_initial_snapshot_id:
                logger.info("Creating db-ready initial snapshot for server %s", server.hostname)
                initial_snap_id = self._deploy_and_snapshot(
                    session=session,
                    server=server,
                    source_snapshot_id=target_config.initial_snapshot_id,
                    schema_dir=schema_dir,
                    db_type=db_type,
                    snapshot_label=f"dbready_initial_{test_run.id}_{server.id}",
                )
                if initial_snap_id:
                    target_config.db_ready_initial_snapshot_id = initial_snap_id

            session.commit()

    def _ensure_schema_generated(self, session: Session, db_type: str) -> Path:
        """Ensure DDL and seed data files exist for the given db_type.

        Checks DBSchemaConfigORM first; if paths exist on disk, uses them.
        Otherwise, generates fresh files using the db-assets generators.

        Returns:
            Path to the directory containing schema and seed files.
        """
        db_config = session.query(DBSchemaConfigORM).filter(
            DBSchemaConfigORM.db_type == db_type,
        ).first()

        if db_config:
            schema_path = Path(db_config.schema_path)
            seed_path = Path(db_config.seed_data_path)
            if schema_path.exists() and seed_path.exists():
                logger.info("Using existing schema files from %s", schema_path.parent)
                return schema_path.parent

        # Generate fresh schema files
        output_dir = Path(self._config.generated_dir) / "db_schema" / db_type
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Generating schema files for %s in %s", db_type, output_dir)

        schema_gen = SchemaGenerator()
        schema_gen.generate_all(db_type, str(output_dir / "schema"))

        seed_gen = SeedDataGenerator()
        seed_gen.generate_all_seed_data(db_type, str(output_dir / "seed"))

        return output_dir

    def _deploy_and_snapshot(
        self,
        session: Session,
        server: ServerORM,
        source_snapshot_id: int,
        schema_dir: Path,
        db_type: str,
        snapshot_label: str,
    ) -> Optional[int]:
        """Restore snapshot, deploy schema+seed, create new snapshot.

        Returns:
            The ID of the new BaselineORM record for the db-ready snapshot,
            or None if deployment failed.
        """
        try:
            source_baseline = session.get(BaselineORM, source_snapshot_id)

            # Restore source snapshot
            snap_name = source_baseline.provider_ref.get("snapshot_name", "")
            self._hypervisor.restore_snapshot(server.server_infra_ref, snap_name)
            self._hypervisor.wait_for_vm_ready(
                server.server_infra_ref,
                timeout_sec=self._config.infrastructure.snapshot_restore_timeout_sec,
            )

            # Connect to server
            cred = self._credentials.get_server_credential(server.id, server.os_family.value)
            executor = create_executor(
                os_family=server.os_family.value,
                host=server.ip_address,
                username=cred.username,
                password=cred.password,
            )

            try:
                # Deploy schema
                self._run_sql_files(executor, server, schema_dir / "schema", db_type)

                # Deploy seed data
                self._run_sql_files(executor, server, schema_dir / "seed", db_type)

                # Verify deployment
                self._verify_deployment(executor, server, db_type)

            finally:
                executor.close()

            # Create snapshot
            new_snap_ref = self._hypervisor.create_snapshot(
                server.server_infra_ref, snapshot_label
            )

            # Create BaselineORM record for the new snapshot
            new_baseline = BaselineORM(
                name=snapshot_label,
                os_family=source_baseline.os_family,
                os_vendor_family=source_baseline.os_vendor_family,
                os_major_ver=source_baseline.os_major_ver,
                os_minor_ver=source_baseline.os_minor_ver,
                os_kernel_ver=source_baseline.os_kernel_ver,
                db_type=DBType(db_type) if db_type else None,
                baseline_type=source_baseline.baseline_type,
                provider_ref={"snapshot_name": snapshot_label, **new_snap_ref}
                    if isinstance(new_snap_ref, dict)
                    else {"snapshot_name": snapshot_label},
            )
            session.add(new_baseline)
            session.flush()  # Get the ID

            logger.info("Created db-ready snapshot '%s' (baseline_id=%d)", snapshot_label, new_baseline.id)
            return new_baseline.id

        except Exception as e:
            logger.error("Failed to create db-ready snapshot for server %s: %s", server.hostname, e)
            return None

    def _run_sql_files(
        self,
        executor: RemoteExecutor,
        server: ServerORM,
        sql_dir: Path,
        db_type: str,
    ) -> None:
        """Upload and execute SQL files on the target server.

        Files are executed in sorted order (00_, 01_, 02_, ...).
        """
        if not sql_dir.exists():
            logger.warning("SQL directory does not exist: %s", sql_dir)
            return

        sql_files = sorted(sql_dir.glob("*.sql"))
        if not sql_files:
            logger.warning("No SQL files found in %s", sql_dir)
            return

        for sql_file in sql_files:
            remote_path = f"/tmp/{sql_file.name}"
            executor.upload(str(sql_file), remote_path)

            # Build the execution command based on db_type
            cmd = self._build_sql_exec_command(
                db_type=db_type,
                sql_file_path=remote_path,
                server=server,
            )
            result = executor.execute(cmd)
            logger.info("Executed %s on %s: exit=%s", sql_file.name, server.hostname, result.get("exit_code", "?"))

    def _build_sql_exec_command(
        self,
        db_type: str,
        sql_file_path: str,
        server: ServerORM,
    ) -> str:
        """Build the CLI command to execute a SQL file on the target server."""
        db_name = server.db_name or "perf_test_db"
        db_user = server.db_user or "sa"
        db_port = server.db_port or self._default_port(db_type)

        if db_type == "postgresql":
            return (
                f"PGPASSWORD='{server.db_password}' psql "
                f"-h localhost -p {db_port} -U {db_user} -d {db_name} "
                f"-f {sql_file_path}"
            )
        elif db_type == "mssql":
            return (
                f"sqlcmd -S localhost,{db_port} -U {db_user} "
                f"-P '{server.db_password}' -d {db_name} "
                f"-i {sql_file_path}"
            )
        elif db_type == "oracle":
            return (
                f"sqlplus {db_user}/'{server.db_password}'@localhost:{db_port}/{db_name} "
                f"@{sql_file_path}"
            )
        elif db_type == "db2":
            return (
                f"db2 connect to {db_name} user {db_user} using '{server.db_password}' && "
                f"db2 -tvf {sql_file_path}"
            )
        else:
            raise ValueError(f"Unsupported db_type: {db_type}")

    @staticmethod
    def _default_port(db_type: str) -> int:
        """Return the default port for a given database type."""
        return {
            "postgresql": 5432,
            "mssql": 1433,
            "oracle": 1521,
            "db2": 50000,
        }.get(db_type, 5432)

    def _verify_deployment(
        self,
        executor: RemoteExecutor,
        server: ServerORM,
        db_type: str,
    ) -> None:
        """Run a quick verification query to check tables were created."""
        db_name = server.db_name or "perf_test_db"
        db_user = server.db_user or "sa"
        db_port = server.db_port or self._default_port(db_type)

        if db_type == "postgresql":
            cmd = (
                f"PGPASSWORD='{server.db_password}' psql "
                f"-h localhost -p {db_port} -U {db_user} -d {db_name} "
                f"-c \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';\""
            )
        elif db_type == "mssql":
            cmd = (
                f"sqlcmd -S localhost,{db_port} -U {db_user} "
                f"-P '{server.db_password}' -d {db_name} "
                f"-Q \"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'\""
            )
        else:
            logger.info("Skipping verification for %s (not implemented)", db_type)
            return

        result = executor.execute(cmd)
        logger.info("Schema verification on %s: %s", server.hostname, result.get("stdout", "").strip())
