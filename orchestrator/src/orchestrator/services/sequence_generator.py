"""Sequence generation service — bridges ops_sequence generators into orchestrator.

Phase 7.5: For each (target × load_profile), generates a deterministic CSV
that defines the exact operation sequence JMeter will follow.

The CSV is generated locally and then uploaded to each load generator via
the RemoteExecutor interface.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.enums import TemplateType
from orchestrator.models.orm import (
    CalibrationResultORM,
    DBSchemaConfigORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)

# Import generators from db-assets
# The db-assets generators are outside the orchestrator package, so we
# add the generator root to sys.path at import time.
_GENERATOR_ROOT = str(
    Path(__file__).resolve().parents[4] / "db-assets"
)
if _GENERATOR_ROOT not in sys.path:
    sys.path.insert(0, _GENERATOR_ROOT)

from generator.generators.ops_sequence_generator import (
    DbLoadOpsGenerator,
    OpsSequenceGenerator,
    ServerFileHeavyOpsGenerator,
    ServerNormalOpsGenerator,
)

logger = logging.getLogger(__name__)


class SequenceGenerationService:
    """Generates and deploys operation sequence CSVs for a test run."""

    def __init__(self, config: AppConfig, credentials: CredentialsStore):
        self._config = config
        self._credentials = credentials

    def generate_and_deploy(self, session: Session, test_run: TestRunORM) -> None:
        """Generate ops sequence CSVs for all (target × load_profile) pairs.

        Steps:
          1. Look up calibrated thread_count per (target, load_profile)
          2. Instantiate the correct generator for the scenario template_type
          3. Generate CSV locally under config.generated_dir
          4. Upload CSV to each load generator at the expected path

        Args:
            session: Database session
            test_run: The TestRunORM being generated for
        """
        scenario = session.get(ScenarioORM, test_run.scenario_id)
        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()
        load_profile_links = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()

        for lp_link in load_profile_links:
            lp = session.get(LoadProfileORM, lp_link.load_profile_id)

            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)
                loadgen = session.get(ServerORM, target_config.loadgenerator_id)

                # Look up calibrated thread count
                cal_result = session.query(CalibrationResultORM).filter(
                    CalibrationResultORM.test_run_id == test_run.id,
                    CalibrationResultORM.server_id == server.id,
                    CalibrationResultORM.load_profile_id == lp.id,
                ).first()

                if not cal_result:
                    logger.warning(
                        "No calibration result for server %s / profile %s, skipping sequence gen",
                        server.hostname, lp.name,
                    )
                    continue

                thread_count = cal_result.thread_count
                seq_count = OpsSequenceGenerator.calculate_sequence_length(
                    thread_count=thread_count,
                    duration_sec=lp.duration_sec,
                )

                # Generate CSV locally
                local_dir = (
                    Path(self._config.generated_dir)
                    / str(test_run.id)
                    / "ops_sequences"
                    / str(server.id)
                )
                local_dir.mkdir(parents=True, exist_ok=True)
                local_path = str(local_dir / f"ops_sequence_{lp.name}.csv")

                generator = self._create_generator(
                    session=session,
                    scenario=scenario,
                    test_run_id=str(test_run.id),
                    load_profile_name=lp.name,
                    server=server,
                )
                ops = self._generate_ops(generator, scenario.template_type, seq_count)
                generator.write_csv(ops, local_path)
                logger.info(
                    "Generated ops sequence: %s (%d rows) for server %s / profile %s",
                    local_path, seq_count, server.hostname, lp.name,
                )

                # Deploy CSV to load generator
                remote_path = f"/opt/jmeter/ops_sequence_{lp.name}.csv"
                self._deploy_csv(loadgen, local_path, remote_path)

    def _create_generator(
        self,
        session: Session,
        scenario: ScenarioORM,
        test_run_id: str,
        load_profile_name: str,
        server: ServerORM,
    ) -> OpsSequenceGenerator:
        """Instantiate the correct generator for the scenario's template_type."""
        template = scenario.template_type

        if template == TemplateType.server_normal:
            return ServerNormalOpsGenerator(test_run_id, load_profile_name)

        elif template == TemplateType.server_file_heavy:
            return ServerFileHeavyOpsGenerator(
                test_run_id=test_run_id,
                load_profile=load_profile_name,
                normal_files=self._get_normal_file_ids(),
                confidential_files=self._get_confidential_file_ids(),
                num_output_folders=4,
            )

        elif template == TemplateType.db_load:
            db_type = server.db_type.value if server.db_type else "postgresql"
            param_pools = self._load_db_param_pools(session, db_type)
            return DbLoadOpsGenerator(
                test_run_id=test_run_id,
                load_profile=load_profile_name,
                customer_ids=param_pools.get("customer_ids", [1, 2, 3]),
                order_params=param_pools.get("order_params", [{"order_id": 1, "status": "PENDING", "amount": 100}]),
                product_ids=param_pools.get("product_ids", [1, 2, 3]),
                patient_ids=param_pools.get("patient_ids", [1, 2, 3]),
                account_ids=param_pools.get("account_ids", [1, 2, 3]),
                ddl_params=param_pools.get("ddl_params", [{"table_name": "t1", "column_name": "c1", "column_type": "VARCHAR(50)"}]),
                grant_params=param_pools.get("grant_params", [{"table_name": "t1", "username": "u1"}]),
                temp_users=param_pools.get("temp_users", [{"username": "tmp1", "password": "pass1"}]),
                config_users=param_pools.get("config_users", ["user1"]),
                db_type=db_type,
            )

        raise ValueError(f"Unknown template type: {template}")

    def _generate_ops(
        self,
        generator: OpsSequenceGenerator,
        template_type: TemplateType,
        count: int,
    ) -> list:
        """Call the generator's generate() method with the correct arguments."""
        if template_type == TemplateType.server_file_heavy:
            return generator.generate(count, confidential_percent=10.0, zip_percent=20.0)
        return generator.generate(count)

    def _get_normal_file_ids(self) -> List[str]:
        """Return list of normal source file IDs available for file-heavy ops.

        These correspond to files deployed by the emulator package under
        /opt/emulator/data/normal/. In a full deployment, this would scan
        the actual file listing; for now we use well-known RFC file IDs.
        """
        return [
            "rfc791", "rfc793", "rfc2616", "rfc7230", "rfc7231",
            "rfc7540", "rfc8446", "rfc9110", "sample_doc_001", "sample_doc_002",
        ]

    def _get_confidential_file_ids(self) -> List[str]:
        """Return list of confidential source file IDs."""
        return ["conf001", "conf002", "conf003"]

    def _load_db_param_pools(self, session: Session, db_type: str) -> Dict:
        """Load parameter pools from seed data CSV files.

        Reads the param CSV directory from DBSchemaConfigORM for the given db_type.
        Falls back to minimal defaults if files are not found.
        """
        db_config = session.query(DBSchemaConfigORM).filter(
            DBSchemaConfigORM.db_type == db_type,
        ).first()

        if not db_config or not db_config.param_csv_path:
            logger.warning("No DB param CSV path configured for %s, using defaults", db_type)
            return {}

        param_dir = Path(db_config.param_csv_path)
        pools: Dict = {}

        # Load customer_ids
        cust_file = param_dir / "customer_ids.csv"
        if cust_file.exists():
            pools["customer_ids"] = self._read_id_csv(str(cust_file))

        # Load order_params
        order_file = param_dir / "order_params.csv"
        if order_file.exists():
            pools["order_params"] = self._read_dict_csv(str(order_file))

        # Load product_ids
        prod_file = param_dir / "product_ids.csv"
        if prod_file.exists():
            pools["product_ids"] = self._read_id_csv(str(prod_file))

        # Load patient_ids
        patient_file = param_dir / "patient_ids.csv"
        if patient_file.exists():
            pools["patient_ids"] = self._read_id_csv(str(patient_file))

        # Load account_ids
        acct_file = param_dir / "account_ids.csv"
        if acct_file.exists():
            pools["account_ids"] = self._read_id_csv(str(acct_file))

        return pools

    @staticmethod
    def _read_id_csv(path: str) -> List[int]:
        """Read a single-column ID CSV and return list of ints."""
        import csv
        ids = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if row:
                    ids.append(int(row[0]))
        return ids

    @staticmethod
    def _read_dict_csv(path: str) -> List[Dict]:
        """Read a multi-column CSV and return list of dicts."""
        import csv
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows

    def _deploy_csv(self, loadgen: ServerORM, local_path: str, remote_path: str) -> None:
        """Upload the generated CSV to the load generator."""
        cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
        executor = create_executor(
            os_family=loadgen.os_family.value,
            host=loadgen.ip_address,
            username=cred.username,
            password=cred.password,
        )
        try:
            executor.upload(local_path, remote_path)
            logger.info("Deployed ops sequence to %s:%s", loadgen.hostname, remote_path)
        finally:
            executor.close()
