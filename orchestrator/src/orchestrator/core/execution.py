"""Execution engine — drives the test run lifecycle.

Implements the outer execution loop per ORCHESTRATOR_INTERFACES.md Section 6.1:
  For each snapshot_num (1=base, 2=initial):
    For each load_profile:
      For each cycle:
        For each target (parallel):
          Restore snapshot, deploy packages, configure emulator, start stats
        BARRIER: all targets ready
        Start JMeter on all
        Wait for duration
        Stop JMeter, collect stats + JTL
        BARRIER: all complete
        [If stress_test_enabled] Run suspicious activities end-test
        [If network_degradation_enabled] Apply tc netem, re-run load, collect
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.core import state_machine
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import HypervisorProvider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import RemoteExecutor, create_executor, wait_for_ssh
from orchestrator.models.enums import ExecutionStatus, TestPhaseType, TestRunState
from orchestrator.models.orm import (
    BaselineORM,
    CalibrationResultORM,
    LabORM,
    LoadProfileORM,
    PhaseExecutionResultORM,
    ScenarioORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)
from orchestrator.services.package_manager import PackageDeployer, PackageResolver

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Drives the executing phase of a test run."""

    def __init__(
        self,
        config: AppConfig,
        credentials: CredentialsStore,
        hypervisor: HypervisorProvider,
    ):
        self._config = config
        self._credentials = credentials
        self._hypervisor = hypervisor
        self._resolver = PackageResolver()
        self._deployer = PackageDeployer()

    def execute(self, session: Session, test_run: TestRunORM) -> None:
        """Run the full execution loop for a test run.

        Assumes test_run.state == TestRunState.executing.
        """
        scenario = session.get(ScenarioORM, test_run.scenario_id)
        lab = session.get(LabORM, test_run.lab_id)
        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()
        load_profile_links = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()
        load_profiles = [
            session.get(LoadProfileORM, lpl.load_profile_id)
            for lpl in load_profile_links
        ]

        # Determine phases: snapshot_num 1=base, 2=initial
        snapshot_nums = []
        if scenario.has_base_phase:
            snapshot_nums.append(1)
        if scenario.has_initial_phase:
            snapshot_nums.append(2)

        for snapshot_num in snapshot_nums:
            for load_profile in load_profiles:
                for cycle in range(1, test_run.cycles_per_profile + 1):
                    # Check for pause/cancel
                    session.refresh(test_run)
                    if test_run.state != TestRunState.executing:
                        logger.info("Test run %d no longer executing (state=%s), stopping",
                                    test_run.id, test_run.state.value)
                        return

                    # Update substates
                    state_machine.update_substates(
                        session, test_run,
                        snapshot_num=snapshot_num,
                        load_profile_id=load_profile.id,
                        cycle_number=cycle,
                    )

                    logger.info(
                        "Executing: snapshot=%d, profile='%s', cycle=%d/%d",
                        snapshot_num, load_profile.name, cycle, test_run.cycles_per_profile,
                    )

                    self._execute_cycle(
                        session=session,
                        test_run=test_run,
                        scenario=scenario,
                        lab=lab,
                        targets=targets,
                        load_profile=load_profile,
                        snapshot_num=snapshot_num,
                        cycle=cycle,
                    )

    def _execute_cycle(
        self,
        session: Session,
        test_run: TestRunORM,
        scenario: ScenarioORM,
        lab: LabORM,
        targets: List[TestRunTargetORM],
        load_profile: LoadProfileORM,
        snapshot_num: int,
        cycle: int,
    ) -> None:
        """Execute one cycle for all targets (load + end-tests)."""
        emulator_port = self._config.emulator.emulator_api_port
        executors: Dict[int, RemoteExecutor] = {}
        emulator_clients: Dict[int, EmulatorClient] = {}
        jmeter_pids: Dict[int, int] = {}
        test_ids: Dict[int, str] = {}
        # Track baselines per server for PhaseExecutionResult
        baselines: Dict[int, BaselineORM] = {}

        try:
            # PHASE 1: Restore snapshots and deploy packages for each target
            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)
                loadgen = session.get(ServerORM, target_config.loadgenerator_id)

                # Determine which snapshot to use
                if snapshot_num == 1:
                    snap_id = target_config.db_ready_base_snapshot_id or target_config.base_snapshot_id
                else:
                    snap_id = target_config.db_ready_initial_snapshot_id or target_config.initial_snapshot_id
                baseline = session.get(BaselineORM, snap_id)
                baselines[server.id] = baseline

                # Create PhaseExecutionResult for LOAD phase
                phase_result = PhaseExecutionResultORM(
                    test_run_id=test_run.id,
                    target_id=server.id,
                    snapshot_num=snapshot_num,
                    load_profile_id=load_profile.id,
                    cycle_number=cycle,
                    test_phase_type=TestPhaseType.load,
                    baseline_id=baseline.id,
                    thread_count=self._get_thread_count(session, test_run.id, server.id, load_profile.id),
                    status=ExecutionStatus.running,
                    started_at=datetime.utcnow(),
                )
                session.add(phase_result)
                session.commit()

                # Restore snapshot
                if not self._config.infrastructure.skip_snapshot_restore:
                    new_ip = self._hypervisor.restore_snapshot(server.server_infra_ref, baseline.provider_ref)
                    self._hypervisor.wait_for_vm_ready(
                        server.server_infra_ref,
                        timeout_sec=self._config.infrastructure.snapshot_restore_timeout_sec,
                    )

                    # Update IP in DB if it changed (Vultr restores may reassign IPs)
                    if new_ip and new_ip != server.ip_address:
                        logger.info("Target %s IP changed: %s -> %s", server.hostname, server.ip_address, new_ip)
                        server.ip_address = new_ip
                        session.commit()

                    # Wait for SSH to be reachable after restore
                    wait_for_ssh(server.ip_address, timeout_sec=120)
                else:
                    logger.info("skip_snapshot_restore=true — skipping restore for %s", server.hostname)

                # Connect to target
                cred = self._credentials.get_server_credential(server.id, server.os_family.value)
                executor = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                executors[server.id] = executor

                # Deploy packages for this phase (agent under test, etc.)
                phase = "base" if snapshot_num == 1 else "initial"
                packages = self._resolver.resolve_for_phase(session, scenario, baseline, phase)
                self._deployer.deploy_all(executor, packages)

                # Deploy emulator to target (snapshot restore wiped it)
                if lab.emulator_package_grp_id:
                    emu_packages = self._resolver.resolve(
                        session, [lab.emulator_package_grp_id], baseline,
                    )
                    self._deployer.deploy_all(executor, emu_packages)

                # Deploy emulator to partner if partner_id is set and different from target
                partner_fqdn = "localhost"
                if target_config.partner_id and target_config.partner_id != server.id:
                    partner_server = session.get(ServerORM, target_config.partner_id)
                    partner_fqdn = partner_server.ip_address
                    if lab.emulator_package_grp_id:
                        try:
                            partner_cred = self._credentials.get_server_credential(
                                partner_server.id, partner_server.os_family.value
                            )
                            partner_exec = create_executor(
                                os_family=partner_server.os_family.value,
                                host=partner_server.ip_address,
                                username=partner_cred.username,
                                password=partner_cred.password,
                            )
                            partner_emu_pkgs = self._resolver.resolve(
                                session, [lab.emulator_package_grp_id], baseline,
                            )
                            self._deployer.deploy_all(partner_exec, partner_emu_pkgs)
                            partner_exec.close()
                            logger.info("Deployed emulator to partner %s", partner_server.hostname)
                        except Exception as e:
                            logger.warning("Failed to deploy emulator to partner %s: %s",
                                           partner_server.hostname, e)

                # Configure emulator
                em_client = EmulatorClient(host=server.ip_address, port=emulator_port)
                emulator_clients[server.id] = em_client

                # Output folders from target config (comma-separated)
                if target_config.output_folders:
                    out_folders = [f.strip() for f in target_config.output_folders.split(",") if f.strip()]
                else:
                    out_folders = ["/opt/emulator/output"]

                em_client.set_config(
                    output_folders=out_folders,
                    partner={"fqdn": partner_fqdn, "port": emulator_port},
                    stats={"default_interval_sec": self._config.stats.collect_interval_sec},
                    service_monitor_patterns=target_config.service_monitor_patterns,
                )

                # Start emulator stats collection
                test_resp = em_client.start_test(
                    test_run_id=str(test_run.id),
                    scenario_id=scenario.name,
                    mode="normal",
                    collect_interval_sec=self._config.stats.collect_interval_sec,
                    thread_count=phase_result.thread_count,
                    duration_sec=load_profile.duration_sec,
                )
                test_ids[server.id] = test_resp.get("test_id", "")

            # BARRIER: all targets set up
            logger.info("All targets set up, starting JMeter on all load generators")

            # PHASE 2: Start JMeter on all load generators
            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)
                loadgen = session.get(ServerORM, target_config.loadgenerator_id)

                loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                loadgen_executor = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )

                thread_count = self._get_thread_count(session, test_run.id, server.id, load_profile.id)
                jmeter_ctrl = JMeterController(
                    executor=loadgen_executor,
                    jmeter_bin="/opt/jmeter/bin/jmeter",  # from package run_command
                    os_family=loadgen.os_family.value,
                )

                run_dir = f"/opt/jmeter/runs/run_{test_run.id}/target_{server.id}"
                pid = jmeter_ctrl.start(
                    jmx_path=f"{run_dir}/test.jmx",
                    jtl_path=f"{run_dir}/results.jtl",
                    log_path=f"{run_dir}/jmeter.log",
                    thread_count=thread_count,
                    ramp_up_sec=load_profile.ramp_up_sec,
                    duration_sec=load_profile.duration_sec,
                    target_host=server.ip_address,
                    target_port=emulator_port,
                    ops_sequence_path=f"{run_dir}/ops_sequence_{load_profile.name}.csv",
                )
                jmeter_pids[server.id] = pid

            # PHASE 3: Wait for test duration
            logger.info("All JMeter instances started, waiting %ds", load_profile.duration_sec)
            barrier_timeout = int(load_profile.duration_sec * (1 + self._config.barrier.barrier_timeout_margin_percent))
            time.sleep(barrier_timeout)

            # PHASE 4: Collect load test results
            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)
                self._collect_results(
                    session=session,
                    test_run=test_run,
                    target_config=target_config,
                    server=server,
                    emulator_clients=emulator_clients,
                    test_ids=test_ids,
                    snapshot_num=snapshot_num,
                    load_profile=load_profile,
                    cycle=cycle,
                    test_phase_type=TestPhaseType.load,
                )

            # PHASE 5: End-tests (after normal load completes)
            # Order: network degradation first (reduced load), then stress (spike load)
            if scenario.network_degradation_enabled:
                self._execute_network_degradation(
                    session=session,
                    test_run=test_run,
                    scenario=scenario,
                    targets=targets,
                    load_profile=load_profile,
                    snapshot_num=snapshot_num,
                    cycle=cycle,
                    baselines=baselines,
                    emulator_port=emulator_port,
                    executors=executors,
                    emulator_clients=emulator_clients,
                )

            if scenario.stress_test_enabled:
                self._execute_stress_test(
                    session=session,
                    test_run=test_run,
                    scenario=scenario,
                    targets=targets,
                    load_profile=load_profile,
                    snapshot_num=snapshot_num,
                    cycle=cycle,
                    baselines=baselines,
                    emulator_port=emulator_port,
                    executors=executors,
                    emulator_clients=emulator_clients,
                )

        finally:
            # Cleanup: close connections
            for executor in executors.values():
                try:
                    executor.close()
                except Exception:
                    pass
            for client in emulator_clients.values():
                try:
                    client.close()
                except Exception:
                    pass

    def _collect_results(
        self,
        session: Session,
        test_run: TestRunORM,
        target_config: TestRunTargetORM,
        server: ServerORM,
        emulator_clients: Dict[int, EmulatorClient],
        test_ids: Dict[int, str],
        snapshot_num: int,
        load_profile: LoadProfileORM,
        cycle: int,
        test_phase_type: TestPhaseType,
        network_degradation_pct: Optional[float] = None,
    ) -> None:
        """Collect stats + JTL results for a single target after test completes."""
        stats_path = None
        jtl_path = None

        try:
            # Stop emulator stats
            em_client = emulator_clients.get(server.id)
            test_id = test_ids.get(server.id)
            if em_client and test_id:
                em_client.stop_test(test_id)

                # Get all stats
                all_stats = em_client.get_all_stats(test_run_id=str(test_run.id))

                # Save stats file — separate dirs per phase type
                phase_label = test_phase_type.value
                stats_dir = (
                    Path(self._config.results_dir) / str(test_run.id) / "stats"
                    / phase_label / str(server.id)
                )
                stats_dir.mkdir(parents=True, exist_ok=True)
                stats_path = stats_dir / f"s{snapshot_num}_p{load_profile.id}_c{cycle}_stats.json"
                with open(stats_path, "w") as f:
                    json.dump(all_stats, f)

            # Download JTL from loadgen
            jtl_dir = (
                Path(self._config.results_dir) / str(test_run.id) / "jtl"
                / test_phase_type.value / str(server.id)
            )
            jtl_dir.mkdir(parents=True, exist_ok=True)
            jtl_local = jtl_dir / f"s{snapshot_num}_p{load_profile.id}_c{cycle}.jtl"

            loadgen = session.get(ServerORM, target_config.loadgenerator_id)
            run_dir = f"/opt/jmeter/runs/run_{test_run.id}/target_{server.id}"
            jtl_suffix = f"_{test_phase_type.value}" if test_phase_type != TestPhaseType.load else ""
            remote_jtl = f"{run_dir}/results{jtl_suffix}.jtl"
            try:
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen.id, loadgen.os_family.value
                )
                loadgen_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )
                loadgen_exec.download(remote_jtl, str(jtl_local))
                loadgen_exec.close()
                jtl_path = jtl_local
                logger.info("Downloaded JTL: %s -> %s", remote_jtl, jtl_local)
            except Exception as e:
                logger.warning("Failed to download JTL from loadgen: %s", e)

            # Update phase result
            phase_result = session.query(PhaseExecutionResultORM).filter(
                PhaseExecutionResultORM.test_run_id == test_run.id,
                PhaseExecutionResultORM.target_id == server.id,
                PhaseExecutionResultORM.snapshot_num == snapshot_num,
                PhaseExecutionResultORM.load_profile_id == load_profile.id,
                PhaseExecutionResultORM.cycle_number == cycle,
                PhaseExecutionResultORM.test_phase_type == test_phase_type,
            ).first()

            if phase_result:
                phase_result.status = ExecutionStatus.completed
                phase_result.completed_at = datetime.utcnow()
                phase_result.stats_file_path = str(stats_path) if stats_path else None
                phase_result.jmeter_jtl_path = str(jtl_path) if jtl_path else None
                session.commit()

        except Exception as e:
            logger.error("Failed collecting results for server %s (%s): %s",
                         server.hostname, test_phase_type.value, e)
            phase_result = session.query(PhaseExecutionResultORM).filter(
                PhaseExecutionResultORM.test_run_id == test_run.id,
                PhaseExecutionResultORM.target_id == server.id,
                PhaseExecutionResultORM.snapshot_num == snapshot_num,
                PhaseExecutionResultORM.load_profile_id == load_profile.id,
                PhaseExecutionResultORM.cycle_number == cycle,
                PhaseExecutionResultORM.test_phase_type == test_phase_type,
            ).first()
            if phase_result:
                phase_result.status = ExecutionStatus.failed
                phase_result.error_message = str(e)
                phase_result.completed_at = datetime.utcnow()
                session.commit()

    def _execute_stress_test(
        self,
        session: Session,
        test_run: TestRunORM,
        scenario: ScenarioORM,
        targets: List[TestRunTargetORM],
        load_profile: LoadProfileORM,
        snapshot_num: int,
        cycle: int,
        baselines: Dict[int, BaselineORM],
        emulator_port: int,
        executors: Dict[int, RemoteExecutor],
        emulator_clients: Dict[int, EmulatorClient],
    ) -> None:
        """Run suspicious activities end-test on all targets.

        Uses server-stress.jmx which reads from a stress_sequence CSV
        containing activity_type + duration_ms columns. The emulator's
        /api/v1/operations/suspicious endpoint performs system-level
        activities that EDR/AV agents would flag.
        """
        stress_duration = scenario.stress_test_duration_sec or 120
        stress_threads = max(1, int(
            self._get_thread_count(session, test_run.id,
                                   targets[0].target_id, load_profile.id)
            * (scenario.stress_test_thread_multiplier or 4.0)
        )) if targets else 4

        logger.info("Starting stress test (suspicious activities): %ds, %d threads",
                     stress_duration, stress_threads)

        stress_test_ids: Dict[int, str] = {}

        # Generate and deploy stress sequence CSV, create PhaseExecutionResult per target
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            baseline = baselines.get(server.id)

            # Create PhaseExecutionResult for stress phase
            phase_result = PhaseExecutionResultORM(
                test_run_id=test_run.id,
                target_id=server.id,
                snapshot_num=snapshot_num,
                load_profile_id=load_profile.id,
                cycle_number=cycle,
                test_phase_type=TestPhaseType.stress,
                baseline_id=baseline.id if baseline else 0,
                thread_count=stress_threads,
                status=ExecutionStatus.running,
                started_at=datetime.utcnow(),
            )
            session.add(phase_result)
            session.commit()

            # Generate stress activity sequence CSV
            self._deploy_stress_sequence(
                session, test_run, server, target_config, load_profile,
                stress_duration, stress_threads,
            )

            # Start emulator stats for stress phase
            em_client = emulator_clients.get(server.id)
            if em_client:
                test_resp = em_client.start_test(
                    test_run_id=f"{test_run.id}-stress",
                    scenario_id=f"{scenario.name}-stress",
                    mode="normal",
                    collect_interval_sec=self._config.stats.collect_interval_sec,
                    thread_count=stress_threads,
                    duration_sec=stress_duration,
                )
                stress_test_ids[server.id] = test_resp.get("test_id", "")

        # Start JMeter stress on all loadgens
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            loadgen_executor = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=loadgen_cred.username,
                password=loadgen_cred.password,
            )

            jmeter_ctrl = JMeterController(
                executor=loadgen_executor,
                jmeter_bin="/opt/jmeter/bin/jmeter",
                os_family=loadgen.os_family.value,
            )

            run_dir = f"/opt/jmeter/runs/run_{test_run.id}/target_{server.id}"
            jmeter_ctrl.start(
                jmx_path=f"{run_dir}/stress.jmx",
                jtl_path=f"{run_dir}/results_stress.jtl",
                log_path=f"{run_dir}/jmeter_stress.log",
                thread_count=stress_threads,
                ramp_up_sec=5,
                duration_sec=stress_duration,
                target_host=server.ip_address,
                target_port=emulator_port,
                extra_properties={"stress_sequence": f"{run_dir}/stress_sequence.csv"},
            )
            loadgen_executor.close()

        # Wait for stress duration
        barrier_timeout = int(stress_duration * (1 + self._config.barrier.barrier_timeout_margin_percent))
        logger.info("Stress test running, waiting %ds", barrier_timeout)
        time.sleep(barrier_timeout)

        # Collect stress results
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            self._collect_results(
                session=session,
                test_run=test_run,
                target_config=target_config,
                server=server,
                emulator_clients=emulator_clients,
                test_ids=stress_test_ids,
                snapshot_num=snapshot_num,
                load_profile=load_profile,
                cycle=cycle,
                test_phase_type=TestPhaseType.stress,
            )

        logger.info("Stress test complete")

    def _execute_network_degradation(
        self,
        session: Session,
        test_run: TestRunORM,
        scenario: ScenarioORM,
        targets: List[TestRunTargetORM],
        load_profile: LoadProfileORM,
        snapshot_num: int,
        cycle: int,
        baselines: Dict[int, BaselineORM],
        emulator_port: int,
        executors: Dict[int, RemoteExecutor],
        emulator_clients: Dict[int, EmulatorClient],
    ) -> None:
        """Apply network degradation on targets and re-run load test.

        Linux: uses `tc netem` to add packet loss/delay
        Windows: uses `netsh` (limited) or clumsy tool
        After the degraded-network test, removes the degradation rules.
        """
        degradation_pct = scenario.network_degradation_pct or 10.0
        degradation_duration = scenario.network_degradation_duration_sec or load_profile.duration_sec

        logger.info("Starting network degradation test: %.0f%% loss for %ds",
                     degradation_pct, degradation_duration)

        nd_test_ids: Dict[int, str] = {}

        # Apply network degradation on each target and create phase results
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            baseline = baselines.get(server.id)
            executor = executors.get(server.id)

            # Create PhaseExecutionResult for network_degradation
            thread_count = self._get_thread_count(session, test_run.id, server.id, load_profile.id)
            phase_result = PhaseExecutionResultORM(
                test_run_id=test_run.id,
                target_id=server.id,
                snapshot_num=snapshot_num,
                load_profile_id=load_profile.id,
                cycle_number=cycle,
                test_phase_type=TestPhaseType.network_degradation,
                baseline_id=baseline.id if baseline else 0,
                thread_count=thread_count,
                network_degradation_pct=degradation_pct,
                status=ExecutionStatus.running,
                started_at=datetime.utcnow(),
            )
            session.add(phase_result)
            session.commit()

            # Apply tc netem on target (Linux)
            if executor and server.os_family.value == "linux":
                try:
                    # Get default network interface
                    iface_result = executor.execute(
                        "ip route | grep default | awk '{print $5}' | head -1"
                    )
                    iface = iface_result.stdout.strip() or "eth0"

                    # Add packet loss via tc netem
                    executor.execute(
                        f"tc qdisc add dev {iface} root netem loss {degradation_pct}% "
                        f"delay 50ms 20ms distribution normal"
                    )
                    logger.info("Applied tc netem on %s: %s%% loss, 50ms delay",
                                server.hostname, degradation_pct)
                except Exception as e:
                    logger.warning("Failed to apply tc netem on %s: %s", server.hostname, e)
            elif executor and server.os_family.value == "windows":
                logger.warning("Windows network degradation not implemented yet for %s",
                               server.hostname)

            # Start emulator stats for degradation phase
            em_client = emulator_clients.get(server.id)
            if em_client:
                test_resp = em_client.start_test(
                    test_run_id=f"{test_run.id}-netdeg",
                    scenario_id=f"{scenario.name}-netdeg",
                    mode="normal",
                    collect_interval_sec=self._config.stats.collect_interval_sec,
                    thread_count=thread_count,
                    duration_sec=degradation_duration,
                )
                nd_test_ids[server.id] = test_resp.get("test_id", "")

        # Start JMeter (same as normal load but with degraded network)
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            loadgen_executor = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=loadgen_cred.username,
                password=loadgen_cred.password,
            )

            thread_count = self._get_thread_count(session, test_run.id, server.id, load_profile.id)
            jmeter_ctrl = JMeterController(
                executor=loadgen_executor,
                jmeter_bin="/opt/jmeter/bin/jmeter",
                os_family=loadgen.os_family.value,
            )

            run_dir = f"/opt/jmeter/runs/run_{test_run.id}/target_{server.id}"
            jmeter_ctrl.start(
                jmx_path=f"{run_dir}/test.jmx",
                jtl_path=f"{run_dir}/results_network_degradation.jtl",
                log_path=f"{run_dir}/jmeter_netdeg.log",
                thread_count=thread_count,
                ramp_up_sec=load_profile.ramp_up_sec,
                duration_sec=degradation_duration,
                target_host=server.ip_address,
                target_port=emulator_port,
                ops_sequence_path=f"{run_dir}/ops_sequence_{load_profile.name}.csv",
            )
            loadgen_executor.close()

        # Wait for degradation duration
        barrier_timeout = int(degradation_duration * (1 + self._config.barrier.barrier_timeout_margin_percent))
        logger.info("Network degradation test running, waiting %ds", barrier_timeout)
        time.sleep(barrier_timeout)

        # Collect results
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            self._collect_results(
                session=session,
                test_run=test_run,
                target_config=target_config,
                server=server,
                emulator_clients=emulator_clients,
                test_ids=nd_test_ids,
                snapshot_num=snapshot_num,
                load_profile=load_profile,
                cycle=cycle,
                test_phase_type=TestPhaseType.network_degradation,
                network_degradation_pct=degradation_pct,
            )

        # Remove network degradation on all targets
        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            executor = executors.get(server.id)
            if executor and server.os_family.value == "linux":
                try:
                    iface_result = executor.execute(
                        "ip route | grep default | awk '{print $5}' | head -1"
                    )
                    iface = iface_result.stdout.strip() or "eth0"
                    executor.execute(f"tc qdisc del dev {iface} root 2>/dev/null || true")
                    logger.info("Removed tc netem from %s", server.hostname)
                except Exception as e:
                    logger.warning("Failed to remove tc netem from %s: %s", server.hostname, e)

        logger.info("Network degradation test complete")

    def _deploy_stress_sequence(
        self,
        session: Session,
        test_run: TestRunORM,
        server: ServerORM,
        target_config: TestRunTargetORM,
        load_profile: LoadProfileORM,
        stress_duration: int,
        stress_threads: int,
    ) -> None:
        """Generate and deploy stress activity sequence CSV to loadgen."""
        gen_root = str(Path(__file__).resolve().parents[4] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import StressActivitySequenceGenerator

        # Calculate row count (each activity takes ~500ms avg, so rows = duration * threads * 2 / 0.5)
        row_count = max(1000, int(stress_duration * stress_threads * 2))

        gen = StressActivitySequenceGenerator(
            test_run_id=f"stress-{test_run.id}",
            load_profile=load_profile.name,
            os_family=server.os_family.value,
        )
        ops = gen.generate(row_count)

        local_dir = (
            Path(self._config.generated_dir) / str(test_run.id)
            / "stress_sequences" / str(server.id)
        )
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(local_dir / "stress_sequence.csv")
        gen.write_csv(ops, local_path)

        # Upload to loadgen
        loadgen = session.get(ServerORM, target_config.loadgenerator_id)
        run_dir = f"/opt/jmeter/runs/run_{test_run.id}/target_{server.id}"
        remote_path = f"{run_dir}/stress_sequence.csv"
        cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
        executor = create_executor(
            os_family=loadgen.os_family.value,
            host=loadgen.ip_address,
            username=cred.username,
            password=cred.password,
        )
        try:
            executor.upload(local_path, remote_path)
            logger.info("Deployed stress sequence CSV (%d rows) to %s:%s",
                         row_count, loadgen.hostname, remote_path)
        finally:
            executor.close()

    def _get_thread_count(self, session: Session, test_run_id: int, server_id: int, load_profile_id: int) -> int:
        """Look up calibrated thread count."""
        result = session.query(CalibrationResultORM).filter(
            CalibrationResultORM.test_run_id == test_run_id,
            CalibrationResultORM.server_id == server_id,
            CalibrationResultORM.load_profile_id == load_profile_id,
        ).first()
        if not result:
            raise ValueError(
                f"No calibration result for test_run={test_run_id}, "
                f"server={server_id}, profile={load_profile_id}"
            )
        return result.thread_count
