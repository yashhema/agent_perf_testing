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
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from orchestrator.models.enums import BaselineTargetState, BaselineTestState, BaselineTestType, TemplateType, Verdict
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
from orchestrator.models.database import SessionLocal
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
            # Session may be in a rolled-back state after a DB error (e.g.
            # IntegrityError).  Roll back so sm.fail() can use the session.
            try:
                session.rollback()
            except Exception:
                pass
            sm.fail(session, test_run, str(e))
        finally:
            self._cleanup_pools(session, test_run)

    # ------------------------------------------------------------------
    # Helper: load common entities
    # ------------------------------------------------------------------
    def _load_context(self, session: Session, test_run: BaselineTestRunORM):
        """Load all related entities for a test run.

        Returns:
            (lab, scenario, targets, load_profiles, duration_overrides) where:
            - targets is a list of (target_orm, server, loadgen, test_snapshot, compare_snapshot) tuples
            - duration_overrides is Dict[lp_id, (duration_sec, ramp_up_sec)] with resolved values
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

        # Resolve duration overrides: NULL = use LP default
        duration_overrides: Dict[int, Tuple[int, int]] = {}
        for lpl in lp_links:
            lp = session.get(LoadProfileORM, lpl.load_profile_id)
            duration_overrides[lp.id] = (
                lpl.duration_sec if lpl.duration_sec is not None else lp.duration_sec,
                lpl.ramp_up_sec if lpl.ramp_up_sec is not None else lp.ramp_up_sec,
            )

        return lab, scenario, targets, load_profiles, duration_overrides

    # ------------------------------------------------------------------
    # Helper: per-target state tracking
    # ------------------------------------------------------------------
    @staticmethod
    def _set_target_state(
        session: Session,
        target_orm: BaselineTestRunTargetORM,
        state: BaselineTargetState,
        error_message: str = None,
        load_profile_id: int = None,
    ) -> None:
        """Update per-target state, error_message, and current_load_profile_id."""
        target_orm.state = state
        if error_message is not None:
            target_orm.error_message = error_message
        if load_profile_id is not None:
            target_orm.current_load_profile_id = load_profile_id
        session.commit()

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
    def _get_orchestrator_url(self) -> str:
        """Build the orchestrator's own HTTP URL for WinRM file pulls.

        The FastAPI app mounts package artifacts at /packages/ and prereqs
        at /prerequisites/.  WinRMExecutor.upload() uses this URL as a base
        for HTTP-pull transfers of files > 4 KB.
        """
        import socket
        host = socket.gethostname()
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            ip = "127.0.0.1"
        # Default FastAPI port — matches cli.py serve default
        return f"http://{ip}:8000"

    def _do_setup(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        resolver = PackageResolver()
        deployer = PackageDeployer()
        orchestrator_url = self._get_orchestrator_url()

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
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT
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

                    # Deploy emulator on loadgen too (needed as /networkclient partner)
                    if needs_pool and lab.emulator_package_grp_id:
                        emu_packages = resolver.resolve(
                            session, [lab.emulator_package_grp_id], loadgen,
                        )
                        emu_installed = deployer.check_status_any(
                            session, loadgen_exec, [lab.emulator_package_grp_id], loadgen,
                        )
                        if emu_installed:
                            logger.info("Emulator already installed on loadgen %s", loadgen.hostname)
                        else:
                            deployer.deploy_all(loadgen_exec, emu_packages)
                            logger.info("Deployed emulator to loadgen %s", loadgen.hostname)

                        # Start emulator on loadgen (for /networkserver endpoint)
                        for pkg in emu_packages:
                            if pkg.run_command:
                                logger.info("Starting emulator on loadgen %s: %s", loadgen.hostname, pkg.run_command)
                                result = loadgen_exec.execute(pkg.run_command, timeout_sec=60)
                                if not result.success:
                                    logger.warning(
                                        "Emulator start on loadgen %s failed (non-fatal): %s",
                                        loadgen.hostname, result.stderr,
                                    )
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

                # Deploy kill script (once — shared location for all targets)
                local_kill_script = str(artifacts_dir / "scripts" / "jmeter_kill.py")
                loadgen_exec.upload(local_kill_script, "/opt/jmeter/bin/jmeter_kill.py")
                loadgen_exec.execute("chmod +x /opt/jmeter/bin/jmeter_kill.py")

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

        # --- Set all target states to setting_up ---
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.setting_up)

        # --- Target setup (all targets — PARALLEL) ---
        def _setup_one_target(target_tuple):
            """Set up one target: restore snapshot, deploy emulator, run discovery.

            Runs in its own thread with its own DB session.
            Returns (server_hostname, None) on success or (server_hostname, error_str) on failure.
            """
            target_orm_id, server_id, server_hostname, server_ip, server_os_family, \
                server_infra_ref, test_snapshot_provider_ref, scenario_id = target_tuple

            thread_session = SessionLocal()
            try:
                # Revert VM to test_snapshot
                new_ip = provider.restore_snapshot(
                    server_infra_ref, test_snapshot_provider_ref,
                )
                provider.wait_for_vm_ready(server_infra_ref)

                actual_ip = server_ip
                if new_ip and new_ip != server_ip:
                    actual_ip = new_ip
                    srv = thread_session.get(ServerORM, server_id)
                    srv.ip_address = new_ip
                    thread_session.commit()

                wait_for_ssh(actual_ip, os_family=server_os_family)

                # Deploy emulator
                target_cred = self._credentials.get_server_credential(
                    server_id, server_os_family,
                )
                target_exec = create_executor(
                    os_family=server_os_family,
                    host=actual_ip,
                    username=target_cred.username,
                    password=target_cred.password,
                    orchestrator_url=orchestrator_url,
                )
                try:
                    if lab.emulator_package_grp_id:
                        srv = thread_session.get(ServerORM, server_id)
                        emu_packages = resolver.resolve(
                            thread_session, [lab.emulator_package_grp_id], srv,
                        )
                        deployer.deploy_all(target_exec, emu_packages)

                        # Start the emulator on each target
                        for pkg in emu_packages:
                            if pkg.run_command:
                                logger.info("Starting emulator on %s: %s", server_hostname, pkg.run_command)
                                result = target_exec.execute(pkg.run_command, timeout_sec=60)
                                if not result.success:
                                    raise RuntimeError(
                                        f"Emulator start failed on {server_hostname}: {result.stderr}"
                                    )

                    # Clean emulator output/stats dirs (OS-aware)
                    if server_os_family == "windows":
                        target_exec.execute(
                            'powershell -Command "'
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                            '"'
                        )
                    else:
                        target_exec.execute("rm -rf /opt/emulator/output/* /opt/emulator/stats/*")

                    # Run discovery -> write to target ORM
                    discovery_dir = Path(__file__).resolve().parent.parent.parent.parent / "discovery"
                    discovery = DiscoveryService(self._credentials, discovery_dir)
                    try:
                        scenario_obj = thread_session.get(ScenarioORM, scenario_id)
                        agents = list(scenario_obj.agents) if scenario_obj else []
                        srv = thread_session.get(ServerORM, server_id)
                        disc_result = discovery._discover_target(srv, agents)
                        t_orm = thread_session.get(BaselineTestRunTargetORM, target_orm_id)
                        if disc_result.os_discovery:
                            t_orm.os_kind = disc_result.os_discovery.os_kind
                            t_orm.os_major_ver = disc_result.os_discovery.os_major_ver
                            t_orm.os_minor_ver = disc_result.os_discovery.os_minor_ver
                        if disc_result.agent_discoveries:
                            t_orm.agent_versions = {
                                d.agent_name: d.discovered_version
                                for d in disc_result.agent_discoveries
                            }
                    except Exception as e:
                        logger.warning("Discovery failed for %s (non-fatal): %s", server_hostname, e)
                    thread_session.commit()
                finally:
                    target_exec.close()

                return (server_hostname, None)
            except Exception as e:
                logger.error(
                    "Setup failed for %s: %s\n%s",
                    server_hostname, e, traceback.format_exc(),
                )
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        # Prepare plain data tuples (no ORM objects across threads)
        setup_tasks = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            setup_tasks.append((
                target_orm.id,
                server.id,
                server.hostname,
                server.ip_address,
                server.os_family.value,
                server.server_infra_ref,
                test_snapshot.provider_ref,
                test_run.scenario_id,
            ))

        # Run all target setups in parallel
        errors = []
        # Build hostname -> target_orm mapping for per-target failure tracking
        hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets
        }
        with ThreadPoolExecutor(max_workers=len(setup_tasks)) as pool:
            futures = {pool.submit(_setup_one_target, t): t for t in setup_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    # Mark this target as failed (per-target, don't abort)
                    t_orm = hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=err,
                        )
                else:
                    logger.info("Setup complete for %s", hostname)

        if len(errors) == len(setup_tasks):
            raise RuntimeError(
                f"Setup failed for ALL {len(setup_tasks)} target(s):\n"
                + "\n".join(errors)
            )
        elif errors:
            logger.warning(
                "Setup failed for %d/%d target(s) — continuing with remaining:\n%s",
                len(errors), len(setup_tasks), "\n".join(errors),
            )

        # Refresh ORM objects after parallel threads committed changes
        session.expire_all()

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
    # Helper: build extra_properties for server_steady template
    # ------------------------------------------------------------------
    # Pool percentages per template type (as fraction of JVM heap).
    # The emulator calculates the actual size from its own Runtime.maxMemory().
    _POOL_HEAP_PERCENT = {
        TemplateType.server_steady: 0.5,       # 50% of heap
        TemplateType.server_file_heavy: 0.3,   # 30% of heap
    }

    @staticmethod
    def _setup_pool(em_client: 'EmulatorClient', template_type: 'TemplateType') -> None:
        """Tell the emulator to allocate a memory pool as a % of its JVM heap.

        The emulator knows its own heap size — the orchestrator just sends
        the percentage. This avoids coupling to the target's RAM or JVM config.
        """
        pct = BaselineOrchestrator._POOL_HEAP_PERCENT.get(template_type, 0.5)

        logger.info("%s: requesting pool allocation at %.0f%% of JVM heap",
                    template_type.value, pct * 100)
        result = em_client.allocate_pool_by_heap_percent(pct)
        logger.info("%s: pool allocated — %s", template_type.value, result)

    @staticmethod
    def _destroy_pool(em_client: 'EmulatorClient') -> None:
        """Release the memory pool on the emulator."""
        try:
            result = em_client.destroy_pool()
            logger.info("Pool destroyed — %s", result)
        except Exception as e:
            logger.warning("Pool destroy failed (non-fatal): %s", e)

    def _cleanup_pools(self, session: Session, test_run: 'BaselineTestRunORM') -> None:
        """Destroy memory pools on all targets. Called from finally block in run()."""
        try:
            lab, scenario, targets, _, _ = self._load_context(session, test_run)
            if scenario.template_type not in self._POOL_HEAP_PERCENT:
                return
            emulator_port = self._config.emulator.emulator_api_port
            for _, server, _, _, _ in targets:
                try:
                    em_client = EmulatorClient(host=server.ip_address, port=emulator_port)
                    self._destroy_pool(em_client)
                except Exception as e:
                    logger.debug("Pool cleanup for %s skipped: %s", server.hostname, e)
        except Exception as e:
            logger.debug("Pool cleanup skipped (context unavailable): %s", e)

    @staticmethod
    def _build_work_extra_properties() -> Dict:
        """Build JMeter extra_properties for templates that use /work endpoint.

        Pool allocation is handled separately via _setup_pool().
        """
        return {
            "cpu_ms": "10",
            "intensity": "0.8",
            "touch_mb": "1.0",
        }

    # ------------------------------------------------------------------
    # State: CALIBRATING (all targets, all profiles — PARALLEL per target)
    # ------------------------------------------------------------------
    def _do_calibration(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        emulator_port = self._config.emulator.emulator_api_port
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT
        cal_config = self._config.calibration
        stats_interval = self._config.stats.collect_interval_sec
        results_dir = self._config.results_dir
        test_run_id = test_run.id
        scenario_template = scenario.template_type

        def _calibrate_one_target(target_info):
            """Calibrate all load profiles for one target.

            Runs in its own thread with its own DB session.
            Returns (server_hostname, None) on success or (server_hostname, error_str) on failure.
            """
            (target_orm_id, server_id, server_hostname, server_ip,
             server_os_family, loadgen_id, loadgen_ip, loadgen_os_family,
             partner_id, output_folders, service_monitor_patterns,
             lp_ids_names) = target_info

            thread_session = SessionLocal()
            calibration_engine = CalibrationEngine(cal_config)
            try:
                target_cred = self._credentials.get_server_credential(
                    server_id, server_os_family,
                )
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen_id, loadgen_os_family,
                )
                loadgen_exec = create_executor(
                    os_family=loadgen_os_family,
                    host=loadgen_ip,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                try:
                    em_client = EmulatorClient(host=server_ip, port=emulator_port)

                    # Configure emulator
                    partner_fqdn = "localhost"
                    if partner_id and partner_id != server_id:
                        partner_server = thread_session.get(ServerORM, partner_id)
                        partner_fqdn = partner_server.ip_address
                    if output_folders:
                        out_folders = [f.strip() for f in output_folders.split(",") if f.strip()]
                    elif server_os_family == "windows":
                        out_folders = ["C:\\emulator\\output"]
                    else:
                        out_folders = ["/opt/emulator/output"]
                    em_client.set_config(
                        output_folders=out_folders,
                        partner={"fqdn": partner_fqdn, "port": emulator_port},
                        stats={"default_interval_sec": stats_interval},
                        service_monitor_patterns=service_monitor_patterns,
                    )

                    jmeter_ctrl = JMeterController(
                        executor=loadgen_exec,
                        jmeter_bin="/opt/jmeter/bin/jmeter",
                        os_family=loadgen_os_family,
                    )

                    # Kill stale JMeter from previous failed runs
                    jmeter_ctrl.kill_for_target(server_ip)

                    # Pool setup for /work templates
                    extra_props = None
                    if needs_pool:
                        self._setup_pool(em_client, scenario_template)
                        extra_props = self._build_work_extra_properties()

                    run_dir = f"/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}"

                    for lp_id, lp_name, lp_cpu_min, lp_cpu_max, lp_ramp, lp_duration in lp_ids_names:
                        lp = thread_session.get(LoadProfileORM, lp_id)
                        server_orm = thread_session.get(ServerORM, server_id)
                        test_run_orm = thread_session.get(BaselineTestRunORM, test_run_id)

                        ctx = CalibrationContext(
                            server=server_orm,
                            load_profile=lp,
                            emulator_client=em_client,
                            jmeter_controller=jmeter_ctrl,
                            jmx_path=f"{run_dir}/test.jmx",
                            ops_sequence_path=f"{run_dir}/calibration_ops.csv",
                            emulator_port=emulator_port,
                            test_run_id=test_run_id,
                            results_dir=results_dir,
                            extra_properties=extra_props,
                        )

                        thread_count = calibration_engine.calibrate(
                            thread_session, test_run_orm, ctx,
                        )
                        logger.info(
                            "Calibrated: server=%s, profile='%s', thread_count=%d",
                            server_hostname, lp_name, thread_count,
                        )
                finally:
                    loadgen_exec.close()
                    try:
                        em_client.close()
                    except Exception:
                        pass

                return (server_hostname, None)
            except Exception as e:
                logger.error(
                    "Calibration failed for %s: %s\n%s",
                    server_hostname, e, traceback.format_exc(),
                )
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        # Prepare plain data tuples for each target (skip already-failed)
        cal_tasks = []
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            if target_orm.state == BaselineTargetState.failed:
                logger.info("Skipping failed target %s in calibration", server.hostname)
                continue
            lp_data = []
            for lp in load_profiles:
                dur, ramp = duration_overrides.get(lp.id, (lp.duration_sec, lp.ramp_up_sec))
                lp_data.append(
                    (lp.id, lp.name, lp.target_cpu_range_min, lp.target_cpu_range_max,
                     ramp, dur)
                )
            cal_tasks.append((
                target_orm.id,
                server.id,
                server.hostname,
                server.ip_address,
                server.os_family.value,
                loadgen.id,
                loadgen.ip_address,
                loadgen.os_family.value,
                target_orm.partner_id,
                target_orm.output_folders,
                target_orm.service_monitor_patterns,
                lp_data,
            ))

        if not cal_tasks:
            raise RuntimeError("All targets failed before calibration — nothing to calibrate")

        # Set target states to calibrating
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            if target_orm.state != BaselineTargetState.failed:
                self._set_target_state(session, target_orm, BaselineTargetState.calibrating)

        # Build hostname -> target_orm mapping for per-target failure tracking
        cal_hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, _ in targets
        }

        # Run calibration for all targets in parallel
        errors = []
        with ThreadPoolExecutor(max_workers=len(cal_tasks)) as pool:
            futures = {pool.submit(_calibrate_one_target, t): t for t in cal_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = cal_hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=err,
                        )
                else:
                    logger.info("Calibration complete for %s", hostname)

        if len(errors) == len(cal_tasks):
            raise RuntimeError(
                f"Calibration failed for ALL {len(cal_tasks)} target(s):\n"
                + "\n".join(errors)
            )
        elif errors:
            logger.warning(
                "Calibration failed for %d/%d target(s) — continuing with remaining:\n%s",
                len(errors), len(cal_tasks), "\n".join(errors),
            )

        # Refresh main session after parallel threads committed
        session.expire_all()

        # ── BARRIER: all targets calibrated for all profiles ──
        sm.transition(session, test_run, BaselineTestState.generating)

    # ------------------------------------------------------------------
    # State: GENERATING (JMX Test Case Data — all targets — PARALLEL)
    # ------------------------------------------------------------------
    def _do_generation(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        import sys
        gen_root = str(Path(__file__).resolve().parents[4] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import OpsSequenceGenerator

        test_run_id = test_run.id
        generated_dir = self._config.generated_dir

        def _generate_one_target(target_info):
            """Generate and upload ops sequences for one target.

            Returns (server_hostname, None) on success or (server_hostname, error_str) on failure.
            """
            (server_id, server_hostname, loadgen_id, loadgen_ip,
             loadgen_os_family, lp_data) = target_info

            thread_session = SessionLocal()
            try:
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen_id, loadgen_os_family,
                )
                loadgen_exec = create_executor(
                    os_family=loadgen_os_family,
                    host=loadgen_ip,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                try:
                    run_dir = f"/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}"

                    for lp_id, lp_name, lp_duration in lp_data:
                        cal = thread_session.query(CalibrationResultORM).filter(
                            CalibrationResultORM.baseline_test_run_id == test_run_id,
                            CalibrationResultORM.server_id == server_id,
                            CalibrationResultORM.load_profile_id == lp_id,
                        ).first()
                        if not cal:
                            raise RuntimeError(
                                f"No calibration result for server {server_id} / profile {lp_id}"
                            )
                        thread_count = cal.thread_count

                        seq_count = OpsSequenceGenerator.calculate_sequence_length(
                            thread_count=thread_count,
                            duration_sec=lp_duration,
                        )

                        gen = self._create_generator_for_template(
                            scenario, str(test_run_id), lp_name,
                        )
                        ops = gen.generate(seq_count)

                        local_dir = (
                            Path(generated_dir)
                            / str(test_run_id)
                            / "ops_sequences"
                            / str(server_id)
                        )
                        local_dir.mkdir(parents=True, exist_ok=True)
                        local_path = str(local_dir / f"ops_sequence_{lp_name}.csv")
                        gen.write_csv(ops, local_path)

                        remote_path = f"{run_dir}/ops_sequence_{lp_name}.csv"
                        loadgen_exec.upload(local_path, remote_path)

                        logger.info(
                            "Generated ops sequence for server %s: %s (%d rows, threads=%d) profile '%s'",
                            server_hostname, local_path, seq_count, thread_count, lp_name,
                        )
                finally:
                    loadgen_exec.close()

                return (server_hostname, None)
            except Exception as e:
                logger.error(
                    "Generation failed for %s: %s\n%s",
                    server_hostname, e, traceback.format_exc(),
                )
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        # Prepare plain data tuples (skip already-failed targets)
        gen_tasks = []
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            if target_orm.state == BaselineTargetState.failed:
                logger.info("Skipping failed target %s in generation", server.hostname)
                continue
            lp_data = []
            for lp in load_profiles:
                dur, _ = duration_overrides.get(lp.id, (lp.duration_sec, lp.ramp_up_sec))
                lp_data.append((lp.id, lp.name, dur))
            gen_tasks.append((
                server.id,
                server.hostname,
                loadgen.id,
                loadgen.ip_address,
                loadgen.os_family.value,
                lp_data,
            ))

        if not gen_tasks:
            raise RuntimeError("All targets failed before generation — nothing to generate")

        # Set target states to generating
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            if target_orm.state != BaselineTargetState.failed:
                self._set_target_state(session, target_orm, BaselineTargetState.generating)

        gen_hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, _ in targets
        }

        # Run generation for all targets in parallel
        errors = []
        with ThreadPoolExecutor(max_workers=len(gen_tasks)) as pool:
            futures = {pool.submit(_generate_one_target, t): t for t in gen_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = gen_hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=err,
                        )
                else:
                    logger.info("Generation complete for %s", hostname)

        if len(errors) == len(gen_tasks):
            raise RuntimeError(
                f"Generation failed for ALL {len(gen_tasks)} target(s):\n"
                + "\n".join(errors)
            )
        elif errors:
            logger.warning(
                "Generation failed for %d/%d target(s) — continuing with remaining:\n%s",
                len(errors), len(gen_tasks), "\n".join(errors),
            )

        # ── BARRIER: all sequences generated and uploaded ──
        sm.transition(session, test_run, BaselineTestState.executing)

    # ------------------------------------------------------------------
    # State: EXECUTING (coordinated — barriers per load profile)
    # ------------------------------------------------------------------
    def _do_execution(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT

        # Set target states to executing (skip already-failed targets)
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if target_orm.state != BaselineTargetState.failed:
                self._set_target_state(session, target_orm, BaselineTargetState.executing)

        # Build per-target thread_counts and jmx_data_paths (skip failed targets)
        target_configs = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if target_orm.state == BaselineTargetState.failed:
                logger.info("Skipping failed target %s in execution", server.hostname)
                continue
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
                "needs_pool": needs_pool,
                "template_type": scenario.template_type,
            })

        if not target_configs:
            raise RuntimeError("All targets failed before execution — nothing to execute")

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
            duration_overrides=duration_overrides,
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
        lab, scenario, targets, load_profiles, _duration_overrides = self._load_context(session, test_run)

        from orchestrator.services.comparison import ComparisonEngine
        comparison_engine = ComparisonEngine(self._config)

        is_option_b = (
            test_run.test_type == BaselineTestType.compare_with_new_calibration
        )

        overall_verdict = Verdict.passed

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if target_orm.state == BaselineTargetState.failed:
                logger.info("Skipping failed target %s in comparison", server.hostname)
                continue
            self._set_target_state(session, target_orm, BaselineTargetState.comparing)

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
        lab, scenario, targets, load_profiles, _duration_overrides = self._load_context(session, test_run)

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if target_orm.state == BaselineTargetState.failed:
                logger.info("Skipping failed target %s in storing", server.hostname)
                continue
            self._set_target_state(session, target_orm, BaselineTargetState.storing)

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

            # Mark target as completed
            self._set_target_state(session, target_orm, BaselineTargetState.completed)

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
        gen_root = str(Path(__file__).resolve().parents[4] / "db-assets")
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
                "jtl_total_requests": er.jtl_total_requests,
                "jtl_total_errors": er.jtl_total_errors,
                "jtl_success_rate_pct": er.jtl_success_rate_pct,
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
                jtl_total_requests=data.get("jtl_total_requests", 0),
                jtl_total_errors=data.get("jtl_total_errors", 0),
                jtl_success_rate_pct=data.get("jtl_success_rate_pct", 0.0),
            )
        return results
