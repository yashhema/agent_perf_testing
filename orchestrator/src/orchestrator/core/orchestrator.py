"""Main orchestrator — top-level test run lifecycle coordinator.

Drives a test run through all states:
  validating -> setting_up -> calibrating -> generating_sequences
  -> executing -> comparing -> completed
"""

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.core import state_machine
from orchestrator.core.calibration import CalibrationContext, CalibrationEngine
from orchestrator.core.execution import ExecutionEngine
from orchestrator.core.validation import PreFlightValidator
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.enums import TestRunState
from orchestrator.models.orm import (
    BaselineORM,
    LabORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)
from orchestrator.services.package_manager import PackageDeployer, PackageResolver

logger = logging.getLogger(__name__)


class Orchestrator:
    """Top-level coordinator for test run lifecycle."""

    def __init__(self, config: AppConfig, credentials: CredentialsStore):
        self._config = config
        self._credentials = credentials

    def run(self, session: Session, test_run_id: int) -> None:
        """Run a test from its current state to completion (or failure/pause).

        Entry point: test_run must be in 'validating' state (after start_test_run API).
        """
        test_run = session.get(TestRunORM, test_run_id)
        if not test_run:
            raise ValueError(f"Test run {test_run_id} not found")

        try:
            while test_run.state not in (
                TestRunState.completed, TestRunState.cancelled,
                TestRunState.failed, TestRunState.paused,
            ):
                session.refresh(test_run)
                current = test_run.state

                if current == TestRunState.validating:
                    self._do_validation(session, test_run)
                elif current == TestRunState.setting_up:
                    self._do_setup(session, test_run)
                elif current == TestRunState.calibrating:
                    self._do_calibration(session, test_run)
                elif current == TestRunState.generating_sequences:
                    self._do_sequence_generation(session, test_run)
                elif current == TestRunState.executing:
                    self._do_execution(session, test_run)
                elif current == TestRunState.comparing:
                    self._do_comparison(session, test_run)
                else:
                    break  # Terminal or unexpected state

                # Check for pause (step-by-step mode pauses after each state)
                session.refresh(test_run)
                if test_run.state == TestRunState.paused:
                    logger.info("Test run %d paused", test_run_id)
                    break

        except Exception as e:
            logger.exception("Test run %d failed", test_run_id)
            state_machine.fail(session, test_run, str(e))

    def _do_validation(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: validating", test_run.id)
        validator = PreFlightValidator(
            credentials=self._credentials,
            emulator_port=self._config.emulator.emulator_api_port,
        )
        result = validator.validate(session, test_run)

        if not result.passed:
            errors_text = "; ".join(f"[{e.check}] {e.message}" for e in result.errors)
            state_machine.fail(session, test_run, f"Validation failed: {errors_text}")
            return

        state_machine.transition(session, test_run, TestRunState.setting_up)

    def _do_setup(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: setting up", test_run.id)
        lab = session.get(LabORM, test_run.lab_id)

        # Restore load gen snapshot
        loadgen_baseline = session.get(BaselineORM, lab.loadgen_snapshot_id)
        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        hypervisor = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()

        # Restore and set up each load generator
        seen_loadgens = set()
        for target_config in targets:
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)
            if loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)

            snap_name = loadgen_baseline.provider_ref.get("snapshot_name", "")
            hypervisor.restore_snapshot(loadgen.server_infra_ref, snap_name)
            hypervisor.wait_for_vm_ready(
                loadgen.server_infra_ref,
                timeout_sec=self._config.infrastructure.snapshot_restore_timeout_sec,
            )

            # Deploy JMeter to load gen
            cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            executor = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=cred.username,
                password=cred.password,
            )
            resolver = PackageResolver()
            deployer = PackageDeployer()
            jmeter_packages = resolver.resolve(session, [lab.jmeter_package_grpid], loadgen_baseline)
            deployer.deploy_all(executor, jmeter_packages)
            executor.close()

        # Deploy DB schema if scenario has_dbtest
        from orchestrator.services.db_schema_deployer import DBSchemaDeployer
        db_deployer = DBSchemaDeployer(self._config, self._credentials, hypervisor)
        db_deployer.deploy_for_test_run(session, test_run)

        # Run discovery on targets for base snapshot (snapshot_num=1)
        self._run_discovery(session, test_run, snapshot_num=1)

        state_machine.transition(session, test_run, TestRunState.calibrating)

    def _do_calibration(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: calibrating", test_run.id)
        lab = session.get(LabORM, test_run.lab_id)
        scenario = session.get(ScenarioORM, test_run.scenario_id)

        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        hypervisor = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        calibration_engine = CalibrationEngine(self._config.calibration)
        emulator_port = self._config.emulator.emulator_api_port

        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()
        load_profile_links = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            for lp_link in load_profile_links:
                lp = session.get(LoadProfileORM, lp_link.load_profile_id)

                # Connect to load gen
                loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                loadgen_executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                ctx = CalibrationContext(
                    server=server,
                    load_profile=lp,
                    emulator_client=EmulatorClient(host=server.ip_address, port=emulator_port),
                    jmeter_controller=JMeterController(
                        executor=loadgen_executor,
                        jmeter_bin="/opt/jmeter/bin/jmeter",
                        os_family=loadgen.os_family.value,
                    ),
                    jmx_path=f"/opt/jmeter/test_{test_run.id}.jmx",
                    ops_sequence_path=f"/opt/jmeter/ops_sequence_{lp.name}.csv",
                    emulator_port=emulator_port,
                )

                calibration_engine.calibrate(session, test_run, ctx)
                ctx.emulator_client.close()
                loadgen_executor.close()

        state_machine.transition(session, test_run, TestRunState.generating_sequences)

    def _do_sequence_generation(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: generating sequences", test_run.id)
        from orchestrator.services.sequence_generator import SequenceGenerationService

        seq_service = SequenceGenerationService(self._config, self._credentials)
        seq_service.generate_and_deploy(session, test_run)

        state_machine.transition(session, test_run, TestRunState.executing)

    def _do_execution(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: executing", test_run.id)
        lab = session.get(LabORM, test_run.lab_id)

        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        hypervisor = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        engine = ExecutionEngine(
            config=self._config,
            credentials=self._credentials,
            hypervisor=hypervisor,
        )

        # Run discovery for initial snapshot (snapshot_num=2) before execution
        self._run_discovery(session, test_run, snapshot_num=2)

        engine.execute(session, test_run)

        # Check if we should move to comparing or if we were paused/cancelled
        session.refresh(test_run)
        if test_run.state == TestRunState.executing:
            state_machine.transition(session, test_run, TestRunState.comparing)

    def _run_discovery(self, session: Session, test_run: TestRunORM, snapshot_num: int) -> None:
        """Run discovery on all targets (non-fatal on failure)."""
        from orchestrator.services.discovery import DiscoveryService

        discovery_dir = Path(__file__).resolve().parent.parent.parent.parent / "discovery"
        discovery = DiscoveryService(self._credentials, discovery_dir)
        try:
            discovery.discover_and_store(session, test_run, snapshot_num=snapshot_num)
            logger.info(
                "Test run %d: snapshot %d discovery completed",
                test_run.id, snapshot_num,
            )
        except Exception as e:
            logger.warning(
                "Test run %d: snapshot %d discovery failed (non-fatal): %s",
                test_run.id, snapshot_num, e,
            )

    def _do_comparison(self, session: Session, test_run: TestRunORM) -> None:
        logger.info("Test run %d: comparing results", test_run.id)
        from orchestrator.services.comparison import ComparisonEngine

        comparison_engine = ComparisonEngine(
            trim_start_sec=self._config.stats.stats_trim_start_sec,
            trim_end_sec=self._config.stats.stats_trim_end_sec,
        )
        results_dir = self._config.results_dir
        comparison_engine.run_comparison(session, test_run, results_dir)

        state_machine.transition(session, test_run, TestRunState.completed)
