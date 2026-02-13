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
"""

import json
import logging
import os
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
from orchestrator.infra.remote_executor import RemoteExecutor, create_executor
from orchestrator.models.enums import ExecutionStatus, TestRunState
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
        """Execute one cycle for all targets."""
        emulator_port = self._config.emulator.emulator_api_port
        executors: Dict[int, RemoteExecutor] = {}
        emulator_clients: Dict[int, EmulatorClient] = {}
        jmeter_pids: Dict[int, int] = {}
        test_ids: Dict[int, str] = {}

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

                # Create PhaseExecutionResult
                phase_result = PhaseExecutionResultORM(
                    test_run_id=test_run.id,
                    target_id=server.id,
                    snapshot_num=snapshot_num,
                    load_profile_id=load_profile.id,
                    cycle_number=cycle,
                    baseline_id=baseline.id,
                    thread_count=self._get_thread_count(session, test_run.id, server.id, load_profile.id),
                    status=ExecutionStatus.running,
                    started_at=datetime.utcnow(),
                )
                session.add(phase_result)
                session.commit()

                # Restore snapshot
                snap_name = baseline.provider_ref.get("snapshot_name", "")
                self._hypervisor.restore_snapshot(server.server_infra_ref, snap_name)
                self._hypervisor.wait_for_vm_ready(
                    server.server_infra_ref,
                    timeout_sec=self._config.infrastructure.snapshot_restore_timeout_sec,
                )

                # Connect to target
                cred = self._credentials.get_server_credential(server.id, server.os_family.value)
                executor = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=cred.username,
                    password=cred.password,
                )
                executors[server.id] = executor

                # Deploy packages
                phase = "base" if snapshot_num == 1 else "initial"
                packages = self._resolver.resolve_for_phase(session, scenario, baseline, phase)
                self._deployer.deploy_all(executor, packages)

                # Configure emulator
                em_client = EmulatorClient(host=server.ip_address, port=emulator_port)
                emulator_clients[server.id] = em_client

                em_client.set_config(
                    input_folders={"normal": "/opt/emulator/data/normal", "confidential": "/opt/emulator/data/confidential"},
                    output_folders=["/opt/emulator/output"],
                    partner={"fqdn": session.get(ServerORM, target_config.partner_id).ip_address, "port": emulator_port}
                        if target_config.partner_id else {"fqdn": "localhost", "port": emulator_port},
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

                pid = jmeter_ctrl.start(
                    jmx_path=f"/opt/jmeter/test_{test_run.id}.jmx",
                    jtl_path=f"/opt/jmeter/results_{test_run.id}_{server.id}.jtl",
                    log_path=f"/opt/jmeter/log_{test_run.id}_{server.id}.log",
                    thread_count=thread_count,
                    ramp_up_sec=load_profile.ramp_up_sec,
                    duration_sec=load_profile.duration_sec,
                    target_host=server.ip_address,
                    target_port=emulator_port,
                    ops_sequence_path=f"/opt/jmeter/ops_sequence_{load_profile.name}.csv",
                )
                jmeter_pids[server.id] = pid

            # PHASE 3: Wait for test duration
            logger.info("All JMeter instances started, waiting %ds", load_profile.duration_sec)
            barrier_timeout = int(load_profile.duration_sec * (1 + self._config.barrier.barrier_timeout_margin_percent))
            time.sleep(barrier_timeout)

            # PHASE 4: Collect results
            for target_config in targets:
                server = session.get(ServerORM, target_config.target_id)

                try:
                    # Stop emulator stats
                    em_client = emulator_clients.get(server.id)
                    test_id = test_ids.get(server.id)
                    if em_client and test_id:
                        em_client.stop_test(test_id)

                        # Get all stats
                        all_stats = em_client.get_all_stats(test_run_id=str(test_run.id))

                        # Save stats file
                        stats_dir = Path(self._config.results_dir) / str(test_run.id) / "stats" / str(server.id)
                        stats_dir.mkdir(parents=True, exist_ok=True)
                        stats_path = stats_dir / f"s{snapshot_num}_p{load_profile.id}_c{cycle}_stats.json"
                        with open(stats_path, "w") as f:
                            json.dump(all_stats, f)

                    # Collect JTL
                    jtl_dir = Path(self._config.results_dir) / str(test_run.id) / "jtl" / str(server.id)
                    jtl_dir.mkdir(parents=True, exist_ok=True)
                    jtl_path = jtl_dir / f"s{snapshot_num}_p{load_profile.id}_c{cycle}.jtl"

                    # Update phase result
                    phase_result = session.query(PhaseExecutionResultORM).filter(
                        PhaseExecutionResultORM.test_run_id == test_run.id,
                        PhaseExecutionResultORM.target_id == server.id,
                        PhaseExecutionResultORM.snapshot_num == snapshot_num,
                        PhaseExecutionResultORM.load_profile_id == load_profile.id,
                        PhaseExecutionResultORM.cycle_number == cycle,
                    ).first()

                    if phase_result:
                        phase_result.status = ExecutionStatus.completed
                        phase_result.completed_at = datetime.utcnow()
                        phase_result.stats_file_path = str(stats_path) if em_client else None
                        phase_result.jmeter_jtl_path = str(jtl_path)
                        session.commit()

                except Exception as e:
                    logger.error("Failed collecting results for server %s: %s", server.hostname, e)
                    phase_result = session.query(PhaseExecutionResultORM).filter(
                        PhaseExecutionResultORM.test_run_id == test_run.id,
                        PhaseExecutionResultORM.target_id == server.id,
                        PhaseExecutionResultORM.snapshot_num == snapshot_num,
                        PhaseExecutionResultORM.load_profile_id == load_profile.id,
                        PhaseExecutionResultORM.cycle_number == cycle,
                    ).first()
                    if phase_result:
                        phase_result.status = ExecutionStatus.failed
                        phase_result.error_message = str(e)
                        phase_result.completed_at = datetime.utcnow()
                        session.commit()

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
