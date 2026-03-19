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
from orchestrator.services.jtl_parser import JtlParser
from orchestrator.services.package_manager import PackageDeployer, PackageResolver
from orchestrator.services.stats_parser import StatsParser

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from executing one load profile on one snapshot.

    Used by the orchestrator for per-LP per-cycle results.
    The cycle field tracks which cycle this result belongs to.
    """
    stats_path: str
    jtl_path: str
    stats_summary: dict
    jmx_test_case_data_path: str
    jmeter_log_path: str = ""
    emulator_log_path: str = ""
    jtl_total_requests: int = 0
    jtl_total_errors: int = 0
    jtl_success_rate_pct: float = 0.0
    cycle: int = 1


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
        self._jtl_parser = JtlParser()
        self._orchestrator_url = self._build_orchestrator_url()
        self._trim_start_sec = config.stats.stats_trim_start_sec
        self._trim_end_sec = config.stats.stats_trim_end_sec
        self._jtl_min_success_rate = config.stats.jtl_min_success_rate_pct

    @staticmethod
    def _build_orchestrator_url() -> str:
        """Build orchestrator's own HTTP URL for WinRM file pulls."""
        import socket as _socket
        host = _socket.gethostname()
        try:
            ip = _socket.gethostbyname(host)
        except _socket.gaierror:
            ip = "127.0.0.1"
        return f"http://{ip}:8000"

    def execute(
        self,
        session: Session,
        baseline_test: BaselineTestRunORM,
        target_configs: List[Dict],
        lab: LabORM,
        scenario: ScenarioORM,
        load_profiles: List[LoadProfileORM],
        duration_overrides: Optional[Dict[int, tuple]] = None,
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
            duration_overrides: Dict of lp_id -> (duration_sec, ramp_up_sec).
                NULL/missing = use LP defaults.

        Returns:
            Dict of server_id -> Dict of load_profile_id -> ExecutionResult
        """
        if duration_overrides is None:
            duration_overrides = {}
        emulator_port = self._config.emulator.emulator_api_port
        # results[server_id][lp_id] = ExecutionResult
        results: Dict[int, Dict[int, ExecutionResult]] = {}
        for tc in target_configs:
            results[tc["server"].id] = {}

        for lp in load_profiles:
            # Resolve duration overrides for this load profile
            eff_duration, eff_ramp_up = duration_overrides.get(
                lp.id, (lp.duration_sec, lp.ramp_up_sec),
            )

            logger.info(
                "Executing profile '%s' on %d targets (duration=%ds, ramp_up=%ds)",
                lp.name, len(target_configs), eff_duration, eff_ramp_up,
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
            # Import helper for server_steady extra_properties
            from orchestrator.core.baseline_orchestrator import BaselineOrchestrator

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
                    orchestrator_url=self._orchestrator_url,
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

                # Output folders from target config (comma-separated)
                if target_orm.output_folders:
                    out_folders = [f.strip() for f in target_orm.output_folders.split(",") if f.strip()]
                elif server.os_family.value == "windows":
                    out_folders = ["C:\\emulator\\output"]
                else:
                    out_folders = ["/opt/emulator/output"]

                em_client.set_config(
                    output_folders=out_folders,
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
                    duration_sec=eff_duration,
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

                # For templates using /work: allocate pool on emulator, build extra JMeter props
                extra_props = None
                if tc.get("needs_pool"):
                    BaselineOrchestrator._setup_pool(tr["em_client"], tc["template_type"])
                    extra_props = BaselineOrchestrator._build_work_extra_properties()

                pid = tr["jmeter_ctrl"].start(
                    jmx_path=f"{run_dir}/test.jmx",
                    jtl_path=f"{run_dir}/results_{lp.name}.jtl",
                    log_path=f"{run_dir}/jmeter_{lp.name}.log",
                    thread_count=tc["thread_counts"][lp.id],
                    ramp_up_sec=eff_ramp_up,
                    duration_sec=86400,  # 24h — orchestrator controls end, not JMeter
                    target_host=server.ip_address,
                    target_port=emulator_port,
                    ops_sequence_path=tc["jmx_data_paths"][lp.id],
                    extra_properties=extra_props,
                )
                jmeter_pids.append(pid)
                logger.info("Started JMeter for %s (pid=%s)", server.hostname, pid)
            # ── BARRIER: all JMeter instances running ──

            # ── Phase 4: Single wait for all ──
            # JMeter runs indefinitely (duration_sec=3600); orchestrator controls the end.
            total_wait = eff_ramp_up + eff_duration
            logger.info("Waiting %ds for test (ramp_up=%d + duration=%d), then stopping JMeter",
                        total_wait, eff_ramp_up, eff_duration)
            time.sleep(total_wait)

            # ── Phase 5: Stop + collect from all targets ──
            for i, tr in enumerate(target_resources):
                tc = tr["tc"]
                server = tc["server"]
                loadgen = tc["loadgen"]

                try:
                    # Stop JMeter
                    run_dir = (
                        f"/opt/jmeter/runs/baseline_{baseline_test.id}"
                        f"/lg_{tc['loadgen'].id}/target_{server.id}"
                    )
                    jtl_path = f"{run_dir}/results_{lp.name}.jtl"
                    tr["jmeter_ctrl"].stop(jmeter_pids[i], jtl_path=jtl_path)

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

                    # Validate JTL: check that enough requests succeeded
                    jtl_result = self._jtl_parser.parse(local_jtl)
                    success_rate = 100.0 - jtl_result.error_rate_percent
                    logger.info(
                        "JTL validation for %s / profile '%s': "
                        "%d total requests, %d errors, "
                        "success rate=%.2f%% (threshold=%.1f%%)",
                        server.hostname, lp.name,
                        jtl_result.total_requests, jtl_result.total_errors,
                        success_rate, self._jtl_min_success_rate,
                    )
                    if jtl_result.total_requests == 0:
                        raise RuntimeError(
                            f"JTL validation FAILED for {server.hostname} / "
                            f"profile '{lp.name}': JTL file contains 0 requests. "
                            f"JMeter may not have started or emulator was unreachable."
                        )
                    if success_rate < self._jtl_min_success_rate:
                        # Log per-label breakdown for diagnostics
                        for label, lr in jtl_result.per_label.items():
                            if lr.errors > 0:
                                logger.error(
                                    "  label '%s': %d/%d failed (%.1f%% error rate)",
                                    label, lr.errors, lr.count, lr.error_rate_percent,
                                )
                        raise RuntimeError(
                            f"JTL validation FAILED for {server.hostname} / "
                            f"profile '{lp.name}': success rate {success_rate:.2f}% "
                            f"is below threshold {self._jtl_min_success_rate:.1f}%. "
                            f"({jtl_result.total_errors}/{jtl_result.total_requests} "
                            f"requests failed). Stats data from this run is unreliable."
                        )

                    # Download JMeter log from loadgen
                    logs_dir = results_base / "logs"
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    local_jmeter_log = str(logs_dir / f"lp{lp.id}_jmeter.log")
                    remote_jmeter_log = f"{run_dir}/jmeter_{lp.name}.log"
                    try:
                        tr["loadgen_executor"].download(remote_jmeter_log, local_jmeter_log)
                        logger.info("Downloaded JMeter log: %s", local_jmeter_log)
                    except Exception as e:
                        logger.warning("Failed to download JMeter log (non-fatal): %s", e)
                        local_jmeter_log = ""

                    # Download emulator logs from target
                    local_emulator_log = str(logs_dir / f"lp{lp.id}_emulator_logs.tar.gz")
                    try:
                        tr["em_client"].download_logs(local_emulator_log)
                        logger.info("Downloaded emulator logs: %s", local_emulator_log)
                    except Exception as e:
                        logger.warning("Failed to download emulator logs (non-fatal): %s", e)
                        local_emulator_log = ""

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
                        jmeter_log_path=local_jmeter_log,
                        emulator_log_path=local_emulator_log,
                        jtl_total_requests=jtl_result.total_requests,
                        jtl_total_errors=jtl_result.total_errors,
                        jtl_success_rate_pct=round(success_rate, 2),
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

        # Start the emulator after deployment
        for pkg in emu_packages:
            if pkg.run_command:
                start_cmd = f"sudo {pkg.run_command}" if server.os_family.value != "windows" else pkg.run_command
                logger.info("Starting emulator on %s: %s", server.hostname, start_cmd)
                result = executor.execute(start_cmd, timeout_sec=60)
                if not result.success:
                    raise RuntimeError(
                        f"Emulator start failed on {server.hostname}: {result.stderr}"
                    )

    def _clean_emulator_dirs(
        self, executor: RemoteExecutor, server: ServerORM,
    ) -> None:
        """Clean emulator output/stats directories for a fresh run."""
        if server.os_family.value == "windows":
            cmd = (
                'powershell -Command "'
                "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                '"'
            )
        else:
            cmd = "sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/*"
        try:
            executor.execute(cmd)
        except Exception as e:
            logger.warning("Clean command failed on %s: %s", server.hostname, e)
