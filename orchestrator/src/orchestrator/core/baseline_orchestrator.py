"""Baseline-compare orchestrator.

Drives the full lifecycle of a baseline-compare test run through states:
  new_baseline:       validating -> setting_up -> calibrating -> generating
                      -> executing -> storing -> completed
  compare:            validating -> setting_up -> executing -> comparing
                      -> storing -> completed
  compare_with_new_calibration:
                      validating -> setting_up -> calibrating -> generating
                      -> executing -> comparing -> storing -> completed

Supports multiple targets per test run with barriers between phases.
"""

import dataclasses
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.core import baseline_state_machine as sm
from orchestrator.core.baseline_execution import BaselineExecutionEngine, wait_for_ssh
from orchestrator.core.baseline_validation import BaselinePreFlightValidator
from orchestrator.core.calibration import CalibrationContext, CalibrationEngine
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.enums import BaselineTestState, BaselineTestType, Verdict
from orchestrator.models.orm import (
    BaselineTestRunLoadProfileORM,
    BaselineTestRunORM,
    BaselineTestRunTargetORM,
    CalibrationResultORM,
    LabORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    SnapshotORM,
    SnapshotProfileDataORM,
)
from orchestrator.services.discovery import DiscoveryService
from orchestrator.services.package_manager import PackageDeployer, PackageResolver

logger = logging.getLogger(__name__)


class BaselineOrchestrator:
    """Orchestrates baseline-compare test runs with multi-target support."""

    def __init__(self, config: AppConfig, credentials: CredentialsStore):
        self._config = config
        self._credentials = credentials

    def run(self, session: Session, baseline_test_id: int) -> None:
        """Execute a baseline-compare test run through all states until terminal."""
        test_run = session.get(BaselineTestRunORM, baseline_test_id)
        if not test_run:
            raise ValueError(f"BaselineTestRun {baseline_test_id} not found")

        targets = session.query(BaselineTestRunTargetORM).filter(
            BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
        ).all()
        target_count = len(targets)

        logger.info(
            "Starting baseline test run %d (type=%s, targets=%d)",
            test_run.id, test_run.test_type.value, target_count,
        )

        try:
            while test_run.state not in (
                BaselineTestState.completed,
                BaselineTestState.failed,
                BaselineTestState.cancelled,
            ):
                session.refresh(test_run)
                state = test_run.state

                if state == BaselineTestState.created:
                    sm.transition(session, test_run, BaselineTestState.validating)

                elif state == BaselineTestState.validating:
                    self._do_validation(session, test_run)

                elif state == BaselineTestState.setting_up:
                    self._do_setup(session, test_run)

                elif state == BaselineTestState.calibrating:
                    self._do_calibration(session, test_run)

                elif state == BaselineTestState.generating:
                    self._do_generation(session, test_run)

                elif state == BaselineTestState.executing:
                    self._do_execution(session, test_run)

                elif state == BaselineTestState.comparing:
                    self._do_comparison(session, test_run)

                elif state == BaselineTestState.storing:
                    self._do_storing(session, test_run)

        except Exception as e:
            logger.exception("Baseline test run %d failed: %s", test_run.id, e)
            sm.fail(session, test_run, str(e))

    # ------------------------------------------------------------------
    # Helper: load common entities
    # ------------------------------------------------------------------
    def _load_context(self, session: Session, test_run: BaselineTestRunORM):
        """Load all related entities for a test run.

        Returns:
            (lab, scenario, targets, load_profiles) where targets is a list of
            (target_orm, server, loadgen, test_snapshot, compare_snapshot) tuples.
        """
        lab = session.get(LabORM, test_run.lab_id)
        scenario = session.get(ScenarioORM, test_run.scenario_id)

        target_orms = session.query(BaselineTestRunTargetORM).filter(
            BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
        ).all()

        targets = []
        for t in target_orms:
            server = session.get(ServerORM, t.target_id)
            loadgen = session.get(ServerORM, t.loadgenerator_id)
            test_snapshot = session.get(SnapshotORM, t.test_snapshot_id)
            compare_snapshot = (
                session.get(SnapshotORM, t.compare_snapshot_id)
                if t.compare_snapshot_id else None
            )
            targets.append((t, server, loadgen, test_snapshot, compare_snapshot))

        lp_links = session.query(BaselineTestRunLoadProfileORM).filter(
            BaselineTestRunLoadProfileORM.baseline_test_run_id == test_run.id,
        ).all()
        load_profiles = [
            session.get(LoadProfileORM, lpl.load_profile_id)
            for lpl in lp_links
        ]
        return lab, scenario, targets, load_profiles

    # ------------------------------------------------------------------
    # State: VALIDATING
    # ------------------------------------------------------------------
    def _do_validation(self, session: Session, test_run: BaselineTestRunORM) -> None:
        validator = BaselinePreFlightValidator(
            credentials=self._credentials,
            emulator_port=self._config.emulator.emulator_api_port,
        )
        result = validator.validate(session, test_run)

        if not result.passed:
            error_msgs = "; ".join(f"[{e.check}] {e.message}" for e in result.errors)
            sm.fail(session, test_run, f"Validation failed: {error_msgs}")
            return

        sm.transition(session, test_run, BaselineTestState.setting_up)

    # ------------------------------------------------------------------
    # State: SETTING_UP (all targets)
    # ------------------------------------------------------------------
    def _do_setup(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        resolver = PackageResolver()
        deployer = PackageDeployer()

        hyp_cred = self._credentials.get_hypervisor_credential(
            lab.hypervisor_type.value,
        )
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        # --- Loadgen setup (deduplicated — shared loadgen only set up once) ---
        seen_loadgens = set()
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if loadgen.id not in seen_loadgens:
                seen_loadgens.add(loadgen.id)
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen.id, loadgen.os_family.value,
                )
                loadgen_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )
                try:
                    jmeter_packages = resolver.resolve(
                        session, [lab.jmeter_package_grpid], loadgen,
                    )
                    for pkg in jmeter_packages:
                        if pkg.status_command:
                            installed = deployer.check_status(loadgen_exec, pkg)
                            if installed:
                                logger.info("JMeter already installed on %s", loadgen.hostname)
                                continue
                        deployer.deploy(loadgen_exec, pkg)
                        logger.info("Deployed JMeter to %s", loadgen.hostname)
                finally:
                    loadgen_exec.close()

            # Per-target loadgen dirs
            loadgen_cred = self._credentials.get_server_credential(
                loadgen.id, loadgen.os_family.value,
            )
            loadgen_exec = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=loadgen_cred.username,
                password=loadgen_cred.password,
            )
            try:
                run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"
                loadgen_exec.execute(f"mkdir -p {run_dir}")

                # Deploy JMX template
                jmx_template_name = f"{scenario.template_type.value}.jmx"
                artifacts_dir = Path(self._config.artifacts_dir)
                local_jmx = str(artifacts_dir / "jmx" / jmx_template_name)
                loadgen_exec.upload(local_jmx, f"{run_dir}/test.jmx")

                # For new_baseline / compare_with_new_calibration: deploy calibration CSV
                if test_run.test_type in (
                    BaselineTestType.new_baseline,
                    BaselineTestType.compare_with_new_calibration,
                ):
                    self._deploy_calibration_csv(
                        loadgen_exec, run_dir, scenario, test_run.id, server.id,
                    )

                # For compare: deploy stored JMX test case data from compare_snapshot
                if test_run.test_type == BaselineTestType.compare and compare_snapshot:
                    self._deploy_stored_jmx_data(
                        session, loadgen_exec, run_dir, compare_snapshot, load_profiles,
                    )
            finally:
                loadgen_exec.close()

        # --- Target setup (all targets) ---
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            # Revert VM to test_snapshot
            new_ip = provider.restore_snapshot(
                server.server_infra_ref, test_snapshot.provider_ref,
            )
            provider.wait_for_vm_ready(server.server_infra_ref)
            if new_ip and new_ip != server.ip_address:
                server.ip_address = new_ip
                session.commit()
            wait_for_ssh(server.ip_address, os_family=server.os_family.value)

            # Deploy emulator
            target_cred = self._credentials.get_server_credential(
                server.id, server.os_family.value,
            )
            target_exec = create_executor(
                os_family=server.os_family.value,
                host=server.ip_address,
                username=target_cred.username,
                password=target_cred.password,
            )
            try:
                if lab.emulator_package_grp_id:
                    emu_packages = resolver.resolve(
                        session, [lab.emulator_package_grp_id], server,
                    )
                    deployer.deploy_all(target_exec, emu_packages)

                target_exec.execute("rm -rf /opt/emulator/output/* /opt/emulator/stats/*")

                # Run discovery -> write to target ORM
                discovery_dir = Path(__file__).resolve().parent.parent.parent.parent / "discovery"
                discovery = DiscoveryService(self._credentials, discovery_dir)
                try:
                    scenario_obj = session.get(ScenarioORM, test_run.scenario_id)
                    agents = list(scenario_obj.agents) if scenario_obj else []
                    disc_result = discovery._discover_target(server, agents)
                    if disc_result.os_discovery:
                        target_orm.os_kind = disc_result.os_discovery.os_kind
                        target_orm.os_major_ver = disc_result.os_discovery.os_major_ver
                        target_orm.os_minor_ver = disc_result.os_discovery.os_minor_ver
                    if disc_result.agent_discoveries:
                        target_orm.agent_versions = {
                            d.agent_name: d.discovered_version
                            for d in disc_result.agent_discoveries
                        }
                except Exception as e:
                    logger.warning("Discovery failed for %s (non-fatal): %s", server.hostname, e)
                session.commit()
            finally:
                target_exec.close()

        # ── BARRIER: all targets set up ──

        # Transition to next state based on test type
        if test_run.test_type in (
            BaselineTestType.new_baseline,
            BaselineTestType.compare_with_new_calibration,
        ):
            sm.transition(session, test_run, BaselineTestState.calibrating)
        else:
            sm.transition(session, test_run, BaselineTestState.executing)

    def _deploy_calibration_csv(
        self, loadgen_exec, run_dir: str, scenario: ScenarioORM,
        test_run_id: int, server_id: int,
    ) -> None:
        """Generate and upload a large calibration CSV (500K rows) for binary search."""
        cal_gen = self._create_generator_for_template(scenario, "calibration", "calibration")
        cal_ops = cal_gen.generate(500000)
        local_cal = str(
            Path(self._config.generated_dir) / str(test_run_id)
            / "calibration" / f"server_{server_id}" / "calibration_ops.csv"
        )
        Path(local_cal).parent.mkdir(parents=True, exist_ok=True)
        cal_gen.write_csv(cal_ops, local_cal)
        loadgen_exec.upload(local_cal, f"{run_dir}/calibration_ops.csv")

    def _deploy_stored_jmx_data(
        self,
        session: Session,
        loadgen_exec,
        run_dir: str,
        compare_snapshot: SnapshotORM,
        load_profiles: List[LoadProfileORM],
    ) -> None:
        """Upload stored JMX test case CSVs from compare_snapshot to loadgen."""
        for lp in load_profiles:
            profile_data = session.query(SnapshotProfileDataORM).filter(
                SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                SnapshotProfileDataORM.load_profile_id == lp.id,
            ).first()
            if profile_data and profile_data.jmx_test_case_data:
                remote_path = f"{run_dir}/ops_sequence_{lp.name}.csv"
                loadgen_exec.upload(profile_data.jmx_test_case_data, remote_path)
                logger.info(
                    "Deployed stored JMX data for profile '%s' from snapshot '%s'",
                    lp.name, compare_snapshot.name,
                )

    # ------------------------------------------------------------------
    # State: CALIBRATING (all targets, all profiles)
    # ------------------------------------------------------------------
    def _do_calibration(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        emulator_port = self._config.emulator.emulator_api_port
        calibration_engine = CalibrationEngine(self._config.calibration)

        for target_orm, server, loadgen, test_snapshot, _ in targets:
            for lp in load_profiles:
                sm.update_current_profile(session, test_run, lp.id)

                target_cred = self._credentials.get_server_credential(
                    server.id, server.os_family.value,
                )
                target_exec = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=target_cred.username,
                    password=target_cred.password,
                )
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen.id, loadgen.os_family.value,
                )
                loadgen_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                try:
                    em_client = EmulatorClient(host=server.ip_address, port=emulator_port)
                    jmeter_ctrl = JMeterController(
                        executor=loadgen_exec,
                        jmeter_bin="/opt/jmeter/bin/jmeter",
                        os_family=loadgen.os_family.value,
                    )

                    run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"
                    ctx = CalibrationContext(
                        server=server,
                        load_profile=lp,
                        emulator_client=em_client,
                        jmeter_controller=jmeter_ctrl,
                        jmx_path=f"{run_dir}/test.jmx",
                        ops_sequence_path=f"{run_dir}/calibration_ops.csv",
                        emulator_port=emulator_port,
                        test_run_id=test_run.id,
                    )

                    thread_count = calibration_engine.calibrate(session, test_run, ctx)
                    logger.info(
                        "Calibrated: server=%s, profile='%s', thread_count=%d",
                        server.hostname, lp.name, thread_count,
                    )
                finally:
                    target_exec.close()
                    loadgen_exec.close()
                    try:
                        em_client.close()
                    except Exception:
                        pass

        # ── BARRIER: all targets calibrated for all profiles ──
        sm.transition(session, test_run, BaselineTestState.generating)

    # ------------------------------------------------------------------
    # State: GENERATING (JMX Test Case Data — all targets)
    # ------------------------------------------------------------------
    def _do_generation(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        import sys
        gen_root = str(Path(__file__).resolve().parents[3] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import OpsSequenceGenerator

        for target_orm, server, loadgen, test_snapshot, _ in targets:
            loadgen_cred = self._credentials.get_server_credential(
                loadgen.id, loadgen.os_family.value,
            )
            loadgen_exec = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=loadgen_cred.username,
                password=loadgen_cred.password,
            )

            try:
                run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

                for lp in load_profiles:
                    cal = session.query(CalibrationResultORM).filter(
                        CalibrationResultORM.baseline_test_run_id == test_run.id,
                        CalibrationResultORM.server_id == server.id,
                        CalibrationResultORM.load_profile_id == lp.id,
                    ).first()
                    if not cal:
                        raise RuntimeError(
                            f"No calibration result for server {server.id} / profile {lp.id}"
                        )
                    thread_count = cal.thread_count

                    seq_count = OpsSequenceGenerator.calculate_sequence_length(
                        thread_count=thread_count,
                        duration_sec=lp.duration_sec,
                    )

                    gen = self._create_generator_for_template(scenario, str(test_run.id), lp.name)
                    ops = gen.generate(seq_count)

                    local_dir = (
                        Path(self._config.generated_dir)
                        / str(test_run.id)
                        / "ops_sequences"
                        / str(server.id)
                    )
                    local_dir.mkdir(parents=True, exist_ok=True)
                    local_path = str(local_dir / f"ops_sequence_{lp.name}.csv")
                    gen.write_csv(ops, local_path)

                    remote_path = f"{run_dir}/ops_sequence_{lp.name}.csv"
                    loadgen_exec.upload(local_path, remote_path)

                    logger.info(
                        "Generated ops sequence for server %s: %s (%d rows, threads=%d) profile '%s'",
                        server.hostname, local_path, seq_count, thread_count, lp.name,
                    )
            finally:
                loadgen_exec.close()

        # ── BARRIER: all sequences generated and uploaded ──
        sm.transition(session, test_run, BaselineTestState.executing)

    # ------------------------------------------------------------------
    # State: EXECUTING (coordinated — barriers per load profile)
    # ------------------------------------------------------------------
    def _do_execution(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        # Build per-target thread_counts and jmx_data_paths
        target_configs = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            thread_counts: Dict[int, int] = {}
            jmx_data_paths: Dict[int, str] = {}
            run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

            if test_run.test_type == BaselineTestType.compare:
                for lp in load_profiles:
                    profile_data = session.query(SnapshotProfileDataORM).filter(
                        SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                        SnapshotProfileDataORM.load_profile_id == lp.id,
                    ).first()
                    if not profile_data:
                        raise RuntimeError(
                            f"No stored profile data for compare snapshot {compare_snapshot.id} "
                            f"/ profile {lp.id} (server {server.hostname})"
                        )
                    thread_counts[lp.id] = profile_data.thread_count
                    jmx_data_paths[lp.id] = f"{run_dir}/ops_sequence_{lp.name}.csv"
            else:
                for lp in load_profiles:
                    cal = session.query(CalibrationResultORM).filter(
                        CalibrationResultORM.baseline_test_run_id == test_run.id,
                        CalibrationResultORM.server_id == server.id,
                        CalibrationResultORM.load_profile_id == lp.id,
                    ).first()
                    if not cal:
                        raise RuntimeError(
                            f"No calibration result for server {server.id} / profile {lp.id}"
                        )
                    thread_counts[lp.id] = cal.thread_count
                    jmx_data_paths[lp.id] = f"{run_dir}/ops_sequence_{lp.name}.csv"

            target_configs.append({
                "target_orm": target_orm,
                "server": server,
                "loadgen": loadgen,
                "test_snapshot": test_snapshot,
                "compare_snapshot": compare_snapshot,
                "thread_counts": thread_counts,
                "jmx_data_paths": jmx_data_paths,
            })

        # Create hypervisor provider
        hyp_cred = self._credentials.get_hypervisor_credential(
            lab.hypervisor_type.value,
        )
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        engine = BaselineExecutionEngine(self._config, self._credentials, provider)
        # execution_results: Dict[server_id, Dict[lp_id, ExecutionResult]]
        self._execution_results = engine.execute(
            session=session,
            baseline_test=test_run,
            target_configs=target_configs,
            lab=lab,
            scenario=scenario,
            load_profiles=load_profiles,
        )

        # Persist execution results per target
        for tc in target_configs:
            server = tc["server"]
            server_results = self._execution_results.get(server.id, {})
            if server_results:
                self._save_execution_results(test_run.id, server.id, server_results)

        # Transition based on test type
        if test_run.test_type == BaselineTestType.new_baseline:
            sm.transition(session, test_run, BaselineTestState.storing)
        else:
            sm.transition(session, test_run, BaselineTestState.comparing)

    # ------------------------------------------------------------------
    # State: COMPARING (per-target, independent — no barrier needed)
    # ------------------------------------------------------------------
    def _do_comparison(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        from orchestrator.services.comparison import ComparisonEngine
        comparison_engine = ComparisonEngine(self._config)

        is_option_b = (
            test_run.test_type == BaselineTestType.compare_with_new_calibration
        )

        overall_verdict = Verdict.passed

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            # Reload execution results from disk if not in memory
            if not hasattr(self, '_execution_results') or server.id not in self._execution_results:
                if not hasattr(self, '_execution_results'):
                    self._execution_results = {}
                self._execution_results[server.id] = self._load_execution_results(
                    test_run.id, server.id,
                )

            server_results = self._execution_results.get(server.id, {})

            for lp in load_profiles:
                compare_data = session.query(SnapshotProfileDataORM).filter(
                    SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                    SnapshotProfileDataORM.load_profile_id == lp.id,
                ).first()
                if not compare_data:
                    logger.warning(
                        "No stored profile data for snapshot '%s' / profile '%s' "
                        "(server %s), skipping comparison",
                        compare_snapshot.name, lp.name, server.hostname,
                    )
                    continue

                exec_result = server_results.get(lp.id)
                if not exec_result:
                    logger.warning(
                        "No execution result for server %s / profile '%s'",
                        server.hostname, lp.name,
                    )
                    continue

                comparison_mode = "option_b" if is_option_b else "option_a"
                results_dir = str(
                    Path(self._config.results_dir) / str(test_run.id)
                    / f"server_{server.id}" / "comparison"
                )
                Path(results_dir).mkdir(parents=True, exist_ok=True)

                verdict = comparison_engine.run_baseline_comparison(
                    session=session,
                    baseline_test=test_run,
                    server_id=server.id,
                    load_profile_id=lp.id,
                    test_stats_path=exec_result.stats_path,
                    test_jtl_path=exec_result.jtl_path,
                    baseline_stats_path=compare_data.stats_data,
                    baseline_jtl_path=compare_data.jtl_data,
                    comparison_mode=comparison_mode,
                    results_dir=results_dir,
                )

                if verdict == Verdict.failed:
                    overall_verdict = Verdict.failed
                elif verdict == Verdict.warning and overall_verdict != Verdict.failed:
                    overall_verdict = Verdict.warning

        test_run.verdict = overall_verdict
        session.commit()

        sm.transition(session, test_run, BaselineTestState.storing)

    # ------------------------------------------------------------------
    # State: STORING (per-target, independent — no barrier needed)
    # ------------------------------------------------------------------
    def _do_storing(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles = self._load_context(session, test_run)

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            # Reload execution results from disk if not in memory
            if not hasattr(self, '_execution_results') or server.id not in self._execution_results:
                if not hasattr(self, '_execution_results'):
                    self._execution_results = {}
                self._execution_results[server.id] = self._load_execution_results(
                    test_run.id, server.id,
                )

            server_results = self._execution_results.get(server.id, {})

            for lp in load_profiles:
                exec_result = server_results.get(lp.id)
                if not exec_result:
                    continue

                # Determine source_snapshot_id and data origin
                if test_run.test_type == BaselineTestType.compare:
                    source_snapshot_id = compare_snapshot.id
                    compare_data = session.query(SnapshotProfileDataORM).filter(
                        SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                        SnapshotProfileDataORM.load_profile_id == lp.id,
                    ).first()
                    if not compare_data:
                        logger.warning(
                            "No stored profile data for compare snapshot / profile %d "
                            "(server %s), skipping",
                            lp.id, server.hostname,
                        )
                        continue
                    thread_count = compare_data.thread_count
                    jmx_path = compare_data.jmx_test_case_data
                else:
                    source_snapshot_id = None
                    cal = session.query(CalibrationResultORM).filter(
                        CalibrationResultORM.baseline_test_run_id == test_run.id,
                        CalibrationResultORM.server_id == server.id,
                        CalibrationResultORM.load_profile_id == lp.id,
                    ).first()
                    if not cal:
                        logger.warning(
                            "No calibration result for server %d / profile %d, skipping",
                            server.id, lp.id,
                        )
                        continue
                    thread_count = cal.thread_count
                    jmx_path = exec_result.jmx_test_case_data_path

                existing = session.query(SnapshotProfileDataORM).filter(
                    SnapshotProfileDataORM.snapshot_id == test_snapshot.id,
                    SnapshotProfileDataORM.load_profile_id == lp.id,
                ).first()

                summary_dict = (
                    dataclasses.asdict(exec_result.stats_summary)
                    if dataclasses.is_dataclass(exec_result.stats_summary)
                    else exec_result.stats_summary
                )

                if existing:
                    existing.thread_count = thread_count
                    existing.jmx_test_case_data = jmx_path
                    existing.stats_data = exec_result.stats_path
                    existing.stats_summary = summary_dict
                    existing.jtl_data = exec_result.jtl_path
                    existing.source_snapshot_id = source_snapshot_id
                else:
                    profile_data = SnapshotProfileDataORM(
                        snapshot_id=test_snapshot.id,
                        load_profile_id=lp.id,
                        thread_count=thread_count,
                        jmx_test_case_data=jmx_path,
                        stats_data=exec_result.stats_path,
                        stats_summary=summary_dict,
                        jtl_data=exec_result.jtl_path,
                        source_snapshot_id=source_snapshot_id,
                    )
                    session.add(profile_data)

            # Mark snapshot as baseline if new_baseline
            if test_run.test_type == BaselineTestType.new_baseline:
                test_snapshot.is_baseline = True

            logger.info(
                "Stored profile data for server %s, snapshot '%s' (id=%d)",
                server.hostname, test_snapshot.name, test_snapshot.id,
            )

        session.commit()
        sm.transition(session, test_run, BaselineTestState.completed)

    # ------------------------------------------------------------------
    # Helper: create generator based on template_type
    # ------------------------------------------------------------------
    @staticmethod
    def _create_generator_for_template(
        scenario: ScenarioORM, test_run_id: str, load_profile_name: str,
    ):
        """Instantiate the correct ops sequence generator based on template_type."""
        import sys
        gen_root = str(Path(__file__).resolve().parents[3] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import (
            ServerNormalOpsGenerator,
            ServerFileHeavyOpsGenerator,
            DbLoadOpsGenerator,
        )
        from orchestrator.models.enums import TemplateType

        template = scenario.template_type
        if template == TemplateType.server_file_heavy:
            return ServerFileHeavyOpsGenerator(
                test_run_id=test_run_id,
                load_profile=load_profile_name,
            )
        elif template == TemplateType.db_load:
            return DbLoadOpsGenerator(
                test_run_id=test_run_id,
                load_profile=load_profile_name,
            )
        else:
            return ServerNormalOpsGenerator(test_run_id, load_profile_name)

    def _save_execution_results(self, test_run_id: int, server_id: int, results: Dict) -> None:
        """Persist execution results to disk as JSON for crash recovery."""
        import json
        from orchestrator.core.baseline_execution import ExecutionResult

        results_base = Path(self._config.results_dir) / str(test_run_id) / f"server_{server_id}"
        results_base.mkdir(parents=True, exist_ok=True)
        manifest_path = results_base / "execution_manifest.json"

        manifest = {}
        for lp_id, er in results.items():
            manifest[str(lp_id)] = {
                "stats_path": er.stats_path,
                "jtl_path": er.jtl_path,
                "stats_summary": (
                    dataclasses.asdict(er.stats_summary)
                    if dataclasses.is_dataclass(er.stats_summary)
                    else er.stats_summary
                ),
                "jmx_test_case_data_path": er.jmx_test_case_data_path,
            }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _load_execution_results(self, test_run_id: int, server_id: int) -> Dict:
        """Load execution results from disk manifest."""
        import json
        from orchestrator.core.baseline_execution import ExecutionResult

        results_base = Path(self._config.results_dir) / str(test_run_id) / f"server_{server_id}"
        manifest_path = results_base / "execution_manifest.json"

        if not manifest_path.exists():
            logger.warning("No execution manifest found at %s", manifest_path)
            return {}

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        results = {}
        for lp_id_str, data in manifest.items():
            results[int(lp_id_str)] = ExecutionResult(
                stats_path=data["stats_path"],
                jtl_path=data["jtl_path"],
                stats_summary=data["stats_summary"],
                jmx_test_case_data_path=data["jmx_test_case_data_path"],
            )
        return results
