"""Baseline-compare execution engine.

Executes a multi-target test with barriers between phases, following the
live_compare execution.py._execute_cycle pattern.

For each load profile:
  1. Restore all targets to snapshot      (BARRIER)
  2. Deploy + configure all targets       (BARRIER)
  3. Start JMeter on all targets          (BARRIER)
  4. Single wait for duration             (BARRIER)
  5. Stop + collect from all targets
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import HypervisorProvider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import RemoteExecutor, create_executor
from orchestrator.models.orm import (
    BaselineTestRunORM,
    LabORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    SnapshotORM,
)
from orchestrator.services.package_manager import PackageDeployer, PackageResolver
from orchestrator.services.stats_parser import StatsParser

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from executing one load profile on one snapshot."""
    stats_path: str
    jtl_path: str
    stats_summary: dict
    jmx_test_case_data_path: str


def wait_for_ssh(host: str, os_family: str = "linux", timeout_sec: int = 120, poll_sec: int = 5) -> None:
    """Wait for SSH (Linux) or WinRM (Windows) to become reachable after snapshot restore."""
    import socket
    port = 5985 if os_family == "windows" else 22
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            return
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(poll_sec)
    raise TimeoutError(f"Port {port} not reachable on {host} after {timeout_sec}s")


class BaselineExecutionEngine:
    """Executes baseline-compare tests with multi-target barrier pattern."""

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
        self._stats_parser = StatsParser()
        self._trim_start_sec = config.stats.stats_trim_start_sec
        self._trim_end_sec = config.stats.stats_trim_end_sec

    def execute(
        self,
        session: Session,
        baseline_test: BaselineTestRunORM,
        target_configs: List[Dict],
        lab: LabORM,
        scenario: ScenarioORM,
        load_profiles: List[LoadProfileORM],
    ) -> Dict[int, Dict[int, ExecutionResult]]:
        """Execute test on all targets for all load profiles with barriers.

        Args:
            session: DB session
            baseline_test: The BaselineTestRunORM
            target_configs: List of dicts with keys:
                target_orm, server, loadgen, test_snapshot, compare_snapshot,
                thread_counts (Dict[lp_id, int]), jmx_data_paths (Dict[lp_id, str])
            lab: Lab configuration
            scenario: Scenario configuration
            load_profiles: Load profiles to execute

        Returns:
            Dict of server_id -> Dict of load_profile_id -> ExecutionResult
        """
        emulator_port = self._config.emulator.emulator_api_port
        # results[server_id][lp_id] = ExecutionResult
        results: Dict[int, Dict[int, ExecutionResult]] = {}
        for tc in target_configs:
            results[tc["server"].id] = {}

        for lp in load_profiles:
            logger.info(
                "Executing profile '%s' on %d targets",
                lp.name, len(target_configs),
            )

            baseline_test.current_load_profile_id = lp.id
            session.commit()

            # ── Phase 1: Restore all targets to snapshot ──
            for tc in target_configs:
                server = tc["server"]
                test_snapshot = tc["test_snapshot"]
                logger.info("Reverting %s to snapshot '%s'", server.hostname, test_snapshot.name)
                new_ip = self._hypervisor.restore_snapshot(
                    server.server_infra_ref, test_snapshot.provider_ref,
                )
                self._hypervisor.wait_for_vm_ready(server.server_infra_ref)
                if new_ip and new_ip != server.ip_address:
                    logger.info("IP changed: %s -> %s", server.ip_address, new_ip)
                    server.ip_address = new_ip
                    session.commit()
                wait_for_ssh(server.ip_address, os_family=server.os_family.value)
            # ── BARRIER: all targets restored ──

            # ── Phase 2: Deploy + configure + start stats on all targets ──
            # Track per-target resources for later phases
            target_resources = []
            for tc in target_configs:
                server = tc["server"]
                loadgen = tc["loadgen"]
                target_orm = tc["target_orm"]

                target_cred = self._credentials.get_server_credential(
                    server.id, server.os_family.value,
                )
                target_executor = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=target_cred.username,
                    password=target_cred.password,
                )

                # Deploy emulator if needed
                self._deploy_emulator_if_needed(session, target_executor, lab, server)

                # Clean emulator dirs
                self._clean_emulator_dirs(target_executor, server)

                # Configure emulator
                em_client = EmulatorClient(
                    host=server.ip_address, port=emulator_port,
                )
                partner_fqdn = "localhost"
                if target_orm.partner_id and target_orm.partner_id != server.id:
                    partner_server = session.get(ServerORM, target_orm.partner_id)
                    partner_fqdn = partner_server.ip_address

                em_client.set_config(
                    input_folders={
                        "normal": "/opt/emulator/data/normal",
                        "confidential": "/opt/emulator/data/confidential",
                    },
                    output_folders=["/opt/emulator/output"],
                    partner={"fqdn": partner_fqdn, "port": emulator_port},
                    stats={
                        "default_interval_sec": self._config.stats.collect_interval_sec,
                    },
                    service_monitor_patterns=target_orm.service_monitor_patterns,
                )

                # Start emulator stats collection
                start_resp = em_client.start_test(
                    test_run_id=str(baseline_test.id),
                    scenario_id=scenario.name,
                    mode="normal",
                    collect_interval_sec=self._config.stats.collect_interval_sec,
                    thread_count=tc["thread_counts"][lp.id],
                    duration_sec=lp.duration_sec,
                )
                test_id = start_resp.get("test_id", f"baseline-{baseline_test.id}-lp{lp.id}-srv{server.id}")

                # Prepare loadgen executor
                loadgen_cred = self._credentials.get_server_credential(
                    loadgen.id, loadgen.os_family.value,
                )
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

                target_resources.append({
                    "tc": tc,
                    "target_executor": target_executor,
                    "em_client": em_client,
                    "test_id": test_id,
                    "loadgen_executor": loadgen_executor,
                    "jmeter_ctrl": jmeter_ctrl,
                })
            # ── BARRIER: all targets configured and collecting stats ──

            # ── Phase 3: Start JMeter on all targets ──
            jmeter_pids = []
            for tr in target_resources:
                tc = tr["tc"]
                server = tc["server"]
                loadgen = tc["loadgen"]
                run_dir = (
                    f"/opt/jmeter/runs/baseline_{baseline_test.id}"
                    f"/lg_{loadgen.id}/target_{server.id}"
                )
                pid = tr["jmeter_ctrl"].start(
                    jmx_path=f"{run_dir}/test.jmx",
                    jtl_path=f"{run_dir}/results_{lp.name}.jtl",
                    log_path=f"{run_dir}/jmeter_{lp.name}.log",
                    thread_count=tc["thread_counts"][lp.id],
                    ramp_up_sec=lp.ramp_up_sec,
                    duration_sec=lp.duration_sec,
                    target_host=server.ip_address,
                    target_port=emulator_port,
                    ops_sequence_path=tc["jmx_data_paths"][lp.id],
                )
                jmeter_pids.append(pid)
                logger.info("Started JMeter for %s (pid=%s)", server.hostname, pid)
            # ── BARRIER: all JMeter instances running ──

            # ── Phase 4: Single wait for all ──
            margin = int(lp.duration_sec * self._config.barrier.barrier_timeout_margin_percent)
            total_wait = lp.duration_sec + lp.ramp_up_sec + margin
            logger.info("Waiting %ds for test completion (all targets)", total_wait)
            time.sleep(total_wait)

            # ── Phase 5: Stop + collect from all targets ──
            for i, tr in enumerate(target_resources):
                tc = tr["tc"]
                server = tc["server"]
                loadgen = tc["loadgen"]

                try:
                    # Stop JMeter
                    tr["jmeter_ctrl"].stop(jmeter_pids[i])

                    # Stop emulator and collect stats
                    tr["em_client"].stop_test(tr["test_id"])
                    stats_json = tr["em_client"].get_all_stats(
                        test_run_id=str(baseline_test.id),
                    )

                    # Save stats to disk
                    results_base = Path(self._config.results_dir) / str(baseline_test.id) / f"server_{server.id}"
                    stats_dir = results_base / "stats"
                    stats_dir.mkdir(parents=True, exist_ok=True)
                    stats_path = str(stats_dir / f"lp{lp.id}_stats.json")

                    with open(stats_path, "w", encoding="utf-8") as f:
                        json.dump(stats_json, f, indent=2)

                    # Download JTL from loadgen
                    jtl_dir = results_base / "jtl"
                    jtl_dir.mkdir(parents=True, exist_ok=True)
                    local_jtl = str(jtl_dir / f"lp{lp.id}.jtl")
                    run_dir = (
                        f"/opt/jmeter/runs/baseline_{baseline_test.id}"
                        f"/lg_{loadgen.id}/target_{server.id}"
                    )
                    remote_jtl = f"{run_dir}/results_{lp.name}.jtl"
                    tr["loadgen_executor"].download(remote_jtl, local_jtl)

                    # Compute stats summary
                    samples = stats_json.get("samples", [])
                    trimmed = self._stats_parser.trim_samples(
                        samples, self._trim_start_sec, self._trim_end_sec,
                    )
                    stats_summary = self._stats_parser.compute_summary(trimmed)

                    # Save JMX test case data path
                    jmx_dir = results_base / "jmx_data"
                    jmx_dir.mkdir(parents=True, exist_ok=True)
                    local_jmx = str(jmx_dir / f"lp{lp.id}_ops_sequence.csv")
                    remote_jmx = tc["jmx_data_paths"][lp.id]
                    tr["loadgen_executor"].download(remote_jmx, local_jmx)

                    results[server.id][lp.id] = ExecutionResult(
                        stats_path=stats_path,
                        jtl_path=local_jtl,
                        stats_summary=stats_summary,
                        jmx_test_case_data_path=local_jmx,
                    )

                    logger.info(
                        "Profile '%s' execution complete for %s. Stats: %s",
                        lp.name, server.hostname, stats_path,
                    )
                finally:
                    tr["target_executor"].close()
                    try:
                        tr["loadgen_executor"].close()
                    except Exception:
                        pass
                    try:
                        tr["em_client"].close()
                    except Exception:
                        pass

        return results

    def _deploy_emulator_if_needed(
        self,
        session: Session,
        executor: RemoteExecutor,
        lab: LabORM,
        server: ServerORM,
    ) -> None:
        """Deploy emulator to target if not already installed."""
        if not lab.emulator_package_grp_id:
            return

        installed = self._deployer.check_status_any(
            session, executor, [lab.emulator_package_grp_id], server,
        )
        if installed:
            logger.info("Emulator already installed on %s, skipping deploy", server.hostname)
            return

        emu_packages = self._resolver.resolve(
            session, [lab.emulator_package_grp_id], server,
        )
        self._deployer.deploy_all(executor, emu_packages)
        logger.info("Deployed emulator to %s", server.hostname)

    def _clean_emulator_dirs(
        self, executor: RemoteExecutor, server: ServerORM,
    ) -> None:
        """Clean emulator output/stats directories for a fresh run."""
        commands = [
            "rm -rf /opt/emulator/output/* /opt/emulator/stats/*",
        ]
        for cmd in commands:
            try:
                executor.execute(cmd)
            except Exception as e:
                logger.warning("Clean command failed on %s: %s", server.hostname, e)
