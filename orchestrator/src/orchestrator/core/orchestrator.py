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
from orchestrator.core.calibration import CalibrationContext, CalibrationEngine, CalibrationError
from orchestrator.core.execution import ExecutionEngine
from orchestrator.core.validation import PreFlightValidator
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import create_executor, wait_for_ssh
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
        scenario = session.get(ScenarioORM, test_run.scenario_id)

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

        resolver = PackageResolver()
        deployer = PackageDeployer()

        # ------------------------------------------------------------------
        # 1. Restore and set up each load generator (JMeter + JMX templates)
        # ------------------------------------------------------------------
        skip_restore = self._config.infrastructure.skip_snapshot_restore
        if skip_restore:
            logger.info("skip_snapshot_restore=true — skipping all snapshot restores")

        seen_loadgens = set()
        for target_config in targets:
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)
            if loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)

            if not skip_restore:
                new_ip = hypervisor.restore_snapshot(loadgen.server_infra_ref, loadgen_baseline.provider_ref)
                hypervisor.wait_for_vm_ready(
                    loadgen.server_infra_ref,
                    timeout_sec=self._config.infrastructure.snapshot_restore_timeout_sec,
                )

                # Update IP in DB if it changed (Vultr restores may reassign IPs)
                if new_ip and new_ip != loadgen.ip_address:
                    logger.info("Loadgen %s IP changed: %s -> %s", loadgen.hostname, loadgen.ip_address, new_ip)
                    loadgen.ip_address = new_ip
                    session.commit()

                # Wait for SSH to be reachable after restore
                wait_for_ssh(loadgen.ip_address, timeout_sec=120)

            # Deploy JMeter to load gen (prereq_script installs Java if missing)
            cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            executor = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=cred.username,
                password=cred.password,
            )
            jmeter_packages = resolver.resolve(session, [lab.jmeter_package_grpid], loadgen_baseline)
            deployer.deploy_all(executor, jmeter_packages)

            # Deploy JMX template(s) to loadgen — one per target, in per-target dirs
            jmx_filename = self._resolve_jmx_filename(scenario)
            jmx_source = Path(self._config.artifacts_dir) / "jmx" / jmx_filename
            if not jmx_source.exists():
                raise FileNotFoundError(
                    f"JMX template not found: {jmx_source}. "
                    f"Copy from db-assets/output/jmx/ to {self._config.artifacts_dir}/jmx/"
                )
            jmeter_ctrl = JMeterController(
                executor=executor,
                jmeter_bin="/opt/jmeter/bin/jmeter",
                os_family=loadgen.os_family.value,
            )
            for tc in targets:
                if tc.loadgenerator_id != loadgen.id:
                    continue
                server = session.get(ServerORM, tc.target_id)
                run_dir = self._target_run_dir(test_run.id, server.id)
                executor.execute(f"mkdir -p {run_dir}")
                jmx_remote = f"{run_dir}/test.jmx"
                jmeter_ctrl.deploy_files({jmx_remote: str(jmx_source)})
                logger.info("Deployed JMX template to %s:%s", loadgen.hostname, jmx_remote)

            executor.close()

        # ------------------------------------------------------------------
        # 2. Deploy emulator to all servers that need it
        #    (every target + every partner that isn't already a target)
        # ------------------------------------------------------------------
        if lab.emulator_package_grp_id:
            servers_needing_emulator: set[int] = set()
            for tc in targets:
                servers_needing_emulator.add(tc.target_id)
                if tc.partner_id:
                    servers_needing_emulator.add(tc.partner_id)

            for server_id in servers_needing_emulator:
                server = session.get(ServerORM, server_id)
                baseline = session.get(BaselineORM, server.baseline_id)
                cred = self._credentials.get_server_credential(server.id, server.os_family.value)
                executor = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                try:
                    emu_packages = resolver.resolve(session, [lab.emulator_package_grp_id], baseline)
                    deployer.deploy_all(executor, emu_packages)
                    logger.info("Deployed emulator to %s (%s)", server.hostname, server.ip_address)
                finally:
                    executor.close()

        # ------------------------------------------------------------------
        # 3. Deploy DB schema if scenario has_dbtest
        # ------------------------------------------------------------------
        from orchestrator.services.db_schema_deployer import DBSchemaDeployer
        db_deployer = DBSchemaDeployer(self._config, self._credentials, hypervisor)
        db_deployer.deploy_for_test_run(session, test_run)

        # ------------------------------------------------------------------
        # 4. Generate calibration CSV and deploy to loadgen
        #    This ensures the ops_sequence CSV exists BEFORE calibration.
        #    Sequence generation phase will later overwrite with the real
        #    calibrated-length deterministic sequence.
        # ------------------------------------------------------------------
        self._deploy_calibration_csv(session, test_run, scenario, targets)

        # ------------------------------------------------------------------
        # 5. Deploy stress JMX to loadgen (for end-test stress phase)
        # ------------------------------------------------------------------
        stress_jmx_source = Path(self._config.artifacts_dir) / "jmx" / "server-stress.jmx"
        if stress_jmx_source.exists():
            for target_config in targets:
                loadgen = session.get(ServerORM, target_config.loadgenerator_id)
                server = session.get(ServerORM, target_config.target_id)
                cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                run_dir = self._target_run_dir(test_run.id, server.id)
                stress_remote = f"{run_dir}/stress.jmx"
                jmeter_ctrl = JMeterController(
                    executor=executor,
                    jmeter_bin="/opt/jmeter/bin/jmeter",
                    os_family=loadgen.os_family.value,
                )
                jmeter_ctrl.deploy_files({stress_remote: str(stress_jmx_source)})
                logger.info("Deployed stress JMX to %s:%s", loadgen.hostname, stress_remote)
                executor.close()

        # Run discovery on targets for base snapshot (snapshot_num=1)
        self._run_discovery(session, test_run, snapshot_num=1)

        logger.info("Test run %d: setup complete, current state=%s, transitioning to calibrating",
                     test_run.id, test_run.state.value)
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

        failed_profiles = []

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            for lp_link in load_profile_links:
                lp = session.get(LoadProfileORM, lp_link.load_profile_id)

                # Update substate so dashboard shows which profile is being calibrated
                test_run.current_load_profile_id = lp.id
                session.commit()

                # Connect to load gen
                loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                loadgen_executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                run_dir = self._target_run_dir(test_run.id, server.id)
                ctx = CalibrationContext(
                    server=server,
                    load_profile=lp,
                    emulator_client=EmulatorClient(host=server.ip_address, port=emulator_port),
                    jmeter_controller=JMeterController(
                        executor=loadgen_executor,
                        jmeter_bin="/opt/jmeter/bin/jmeter",
                        os_family=loadgen.os_family.value,
                    ),
                    jmx_path=f"{run_dir}/test.jmx",
                    ops_sequence_path=f"{run_dir}/ops_sequence_{lp.name}.csv",
                    emulator_port=emulator_port,
                    test_run_id=test_run.id,
                )

                try:
                    calibration_engine.calibrate(session, test_run, ctx)
                except CalibrationError as e:
                    logger.error("Calibration failed for %s / %s: %s",
                                 server.hostname, lp.name, e)
                    failed_profiles.append(f"{server.hostname}/{lp.name}")
                finally:
                    ctx.emulator_client.close()
                    loadgen_executor.close()

        # Clear substate
        test_run.current_load_profile_id = None
        session.commit()

        if failed_profiles:
            error_msg = (
                f"Calibration failed for {len(failed_profiles)} profile(s): "
                + ", ".join(failed_profiles)
                + ". Check calibration results for details."
            )
            state_machine.fail(session, test_run, error_msg)
            return

        logger.info("Test run %d: calibration complete, current state=%s, transitioning to generating_sequences",
                     test_run.id, test_run.state.value)
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

    @staticmethod
    def _target_run_dir(test_run_id: int, target_server_id: int) -> str:
        """Per-target working directory on the loadgen."""
        return f"/opt/jmeter/runs/run_{test_run_id}/target_{target_server_id}"

    @staticmethod
    def _resolve_jmx_filename(scenario: ScenarioORM) -> str:
        """Map scenario.template_type to the JMX filename in artifacts/jmx/.

        All server templates (server-normal, server-steady, server-file-heavy)
        use the unified server-steady.jmx — the CSV determines the op mix.
        """
        template_val = scenario.template_type.value if hasattr(scenario.template_type, "value") else str(scenario.template_type)

        if template_val == "db-load":
            db_type = getattr(scenario, "db_type", None)
            db_suffix = db_type.value if db_type and hasattr(db_type, "value") else (db_type or "postgresql")
            return f"db-load-{db_suffix}.jmx"

        return "server-steady.jmx"

    def _deploy_calibration_csv(
        self,
        session: Session,
        test_run: TestRunORM,
        scenario: ScenarioORM,
        targets: list,
    ) -> None:
        """Generate and deploy a temporary ops_sequence CSV for calibration.

        The CSV uses the same op distribution as the final sequence but with
        a generous row count (500K) so calibration iterations never run out.
        The sequence generation phase will overwrite this with the real
        calibrated-length deterministic sequence.
        """
        import sys
        gen_root = str(Path(__file__).resolve().parents[4] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import ServerNormalOpsGenerator

        CALIBRATION_ROW_COUNT = 500_000

        load_profile_links = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            for lp_link in load_profile_links:
                lp = session.get(LoadProfileORM, lp_link.load_profile_id)

                # Generate calibration CSV locally
                gen = ServerNormalOpsGenerator(
                    test_run_id=f"calibration-{test_run.id}",
                    load_profile=lp.name,
                )
                ops = gen.generate(CALIBRATION_ROW_COUNT)
                local_dir = (
                    Path(self._config.generated_dir)
                    / str(test_run.id)
                    / "calibration_sequences"
                    / str(server.id)
                )
                local_dir.mkdir(parents=True, exist_ok=True)
                local_path = str(local_dir / f"ops_sequence_{lp.name}.csv")
                gen.write_csv(ops, local_path)

                # Upload to loadgen
                run_dir = self._target_run_dir(test_run.id, server.id)
                remote_path = f"{run_dir}/ops_sequence_{lp.name}.csv"
                cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                try:
                    executor.upload(local_path, remote_path)
                    logger.info(
                        "Deployed calibration CSV (%d rows) to %s:%s",
                        CALIBRATION_ROW_COUNT, loadgen.hostname, remote_path,
                    )
                finally:
                    executor.close()

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
