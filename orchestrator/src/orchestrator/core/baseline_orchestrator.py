"""Baseline-compare orchestrator.

Drives the full lifecycle of a baseline-compare test run through states:
  new_baseline:       validating -> deploying_loadgen -> deploying_calibration
                      -> calibrating -> generating -> deploying_testing -> executing
                      -> storing -> completed
  compare:            validating -> deploying_loadgen -> deploying_testing
                      -> executing -> comparing -> storing -> completed
  compare_with_new_calibration:
                      validating -> deploying_loadgen -> deploying_calibration
                      -> calibrating -> generating -> deploying_testing -> executing
                      -> comparing -> storing -> completed

Per-LP per-cycle state transitions with snapshot revert on every cycle.
Strict barriers: any target fails -> test fails immediately.
"""

import dataclasses
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.config.settings import AppConfig
from orchestrator.core import baseline_state_machine as sm
from orchestrator.core.baseline_execution import ExecutionResult, wait_for_ssh
from orchestrator.core.baseline_validation import BaselinePreFlightValidator
from orchestrator.core.calibration import CalibrationContext, CalibrationEngine
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.enums import (
    BaselineTargetState, BaselineTestState, BaselineTestType, TemplateType, Verdict,
)
from orchestrator.models.orm import (
    BaselineTestRunLoadProfileORM,
    BaselineTestRunORM,
    BaselineTestRunTargetORM,
    CalibrationResultORM,
    ComparisonResultORM,
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
from orchestrator.services.jtl_parser import JtlParser
from orchestrator.services.stats_parser import StatsParser

logger = logging.getLogger(__name__)


class BaselineOrchestrator:
    """Orchestrates baseline-compare test runs with multi-target support.

    Uses per-LP per-cycle state transitions with strict barriers.
    """

    def __init__(self, config: AppConfig, credentials: CredentialsStore):
        self._config = config
        self._credentials = credentials
        self._stats_parser = StatsParser()
        self._jtl_parser = JtlParser()

    @staticmethod
    def _sudo_upload(executor, local_path: str, remote_path: str) -> None:
        """Upload a file via SFTP to /tmp, then sudo mv to final path.
        For Windows paths (backslash), uploads directly (no sudo needed).
        """
        if remote_path.startswith("/"):
            import os
            filename = os.path.basename(remote_path)
            tmp = f"/tmp/_upload_{filename}"
            remote_dir = remote_path.rsplit("/", 1)[0]
            executor.execute(f"sudo mkdir -p {remote_dir}")
            executor.upload(local_path, tmp)
            result = executor.execute(f"sudo mv {tmp} {remote_path} && sudo chmod 644 {remote_path}")
            if not result.success:
                raise RuntimeError(f"sudo mv failed for {remote_path}: {result.stderr}")
        else:
            executor.upload(local_path, remote_path)

    # ------------------------------------------------------------------
    # Iteration helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _next_test_iteration(test_run, load_profiles):
        """Determine next LP + cycle for testing phase.

        Returns (next_lp_id, next_cycle) or None if done.
        """
        current_lp = test_run.current_load_profile_id
        current_cycle = test_run.current_cycle
        cycle_count = test_run.cycle_count
        lp_ids = [lp.id for lp in load_profiles]

        if current_cycle < cycle_count:
            return (current_lp, current_cycle + 1)

        current_idx = lp_ids.index(current_lp)
        if current_idx + 1 < len(lp_ids):
            return (lp_ids[current_idx + 1], 1)

        return None  # all done

    @staticmethod
    def _next_cal_iteration(test_run, load_profiles):
        """Determine next LP for calibration phase (always 1 cycle).

        Returns next_lp_id or None if done.
        """
        current_lp = test_run.current_load_profile_id
        lp_ids = [lp.id for lp in load_profiles]

        current_idx = lp_ids.index(current_lp)
        if current_idx + 1 < len(lp_ids):
            return lp_ids[current_idx + 1]

        return None  # all done

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------
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
            "Starting baseline test run %d (type=%s, targets=%d, cycle_count=%d)",
            test_run.id, test_run.test_type.value, target_count, test_run.cycle_count,
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

                elif state == BaselineTestState.deploying_loadgen:
                    self._do_deploying_loadgen(session, test_run)

                elif state == BaselineTestState.deploying_calibration:
                    self._do_deploying_calibration(session, test_run)

                elif state == BaselineTestState.calibrating:
                    self._do_calibration(session, test_run)

                elif state == BaselineTestState.generating:
                    self._do_generation(session, test_run)

                elif state == BaselineTestState.deploying_testing:
                    self._do_deploying_testing(session, test_run)

                elif state == BaselineTestState.executing:
                    self._do_execution(session, test_run)

                elif state == BaselineTestState.comparing:
                    self._do_comparison(session, test_run)

                elif state == BaselineTestState.storing:
                    self._do_storing(session, test_run)

        except Exception as e:
            logger.exception("Baseline test run %d failed: %s", test_run.id, e)
            # Kill JMeter on all loadgens if we were executing
            try:
                if test_run.state in (BaselineTestState.executing,):
                    self._kill_jmeter_all_loadgens(session, test_run)
            except Exception as kill_err:
                logger.warning("JMeter cleanup failed: %s", kill_err)
            # Session may be in a rolled-back state after a DB error
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
    # Helper: kill JMeter on all loadgens
    # ------------------------------------------------------------------
    def _kill_jmeter_all_loadgens(self, session: Session, test_run: BaselineTestRunORM) -> None:
        """Kill JMeter processes on ALL unique loadgens used by this test."""
        lab, scenario, targets, _, _ = self._load_context(session, test_run)
        seen_loadgens = set()
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)
            try:
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
                    loadgen_exec.execute("pkill -f jmeter || true")
                    logger.info("Killed JMeter on loadgen %s", loadgen.hostname)
                finally:
                    loadgen_exec.close()
            except Exception as e:
                logger.warning("Failed to kill JMeter on %s: %s", loadgen.hostname, e)

    # ------------------------------------------------------------------
    # Helper: dirty snapshot check
    # ------------------------------------------------------------------
    def _check_dirty_snapshot(self, executor, server: ServerORM, snapshot_name: str) -> None:
        """Check for pre-existing artifacts after snapshot revert. Raises if dirty."""
        if server.os_family.value == "windows":
            dirs_to_check = [r"C:\emulator\output", r"C:\emulator\stats"]
            proc_cmd = 'powershell -Command "Get-Process -Name *emulator* -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.Id }"'
        else:
            dirs_to_check = ["/opt/emulator/output", "/opt/emulator/stats"]
            # Use [e]mulator trick to avoid matching the grep/pgrep command itself.
            # Use -c to get a count instead of PIDs (cleaner check).
            proc_cmd = "pgrep -f '[e]mulator' -c 2>/dev/null || echo 0"

        dirty_details = []

        for d in dirs_to_check:
            if server.os_family.value == "windows":
                result = executor.execute(
                    f'powershell -Command "if (Test-Path \'{d}\') {{ (Get-ChildItem \'{d}\' -Recurse | Measure-Object).Count }} else {{ 0 }}"'
                )
            else:
                result = executor.execute(
                    f"find {d} -type f 2>/dev/null | head -1 | wc -l"
                )
            stdout_val = result.stdout.strip()
            if stdout_val not in ("0", ""):
                try:
                    count = int(stdout_val)
                    if count > 0:
                        dirty_details.append(f"files in {d} (count={count})")
                        logger.warning("Dirty check %s: %d files in %s", server.hostname, count, d)
                except ValueError:
                    dirty_details.append(f"files in {d} (raw={stdout_val!r})")

        # Check for running emulator process
        result = executor.execute(proc_cmd)
        proc_stdout = result.stdout.strip()
        # Parse count from last line
        lines = [l.strip() for l in proc_stdout.splitlines() if l.strip()]
        proc_count_str = lines[-1] if lines else "0"
        try:
            proc_count = int(proc_count_str)
        except ValueError:
            proc_count = 0
            logger.warning("Dirty check %s: unexpected pgrep output: %r", server.hostname, proc_stdout)

        if proc_count > 0:
            # Log the actual process details for debugging
            ps_result = executor.execute("ps -eo pid,cmd | grep '[e]mulator' 2>/dev/null || true")
            logger.warning("Dirty check %s: %d emulator process(es) found. ps output: %s",
                           server.hostname, proc_count, ps_result.stdout.strip())
            dirty_details.append(f"emulator process running (count={proc_count}, ps={ps_result.stdout.strip()!r})")

        if dirty_details:
            details = ", ".join(dirty_details)
            raise RuntimeError(
                f"Dirty snapshot detected on {server.hostname} after revert to '{snapshot_name}'. "
                f"Pre-existing artifacts found: {details}. "
                f"Run retake_snapshots.py to fix."
            )

    # ------------------------------------------------------------------
    # Helper: dirty loadgen check
    # ------------------------------------------------------------------
    def _check_dirty_loadgen(self, executor, loadgen: ServerORM, test_run_id: int) -> List[str]:
        """Check for stale artifacts on a loadgen. Returns list of issues found (empty = clean)."""
        issues = []

        # Check for running JMeter processes (use [j]meter to avoid matching grep itself)
        result = executor.execute("pgrep -f '[j]meter' -c 2>/dev/null || echo 0")
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        count_str = lines[-1] if lines else "0"
        try:
            count = int(count_str)
            if count > 0:
                issues.append(f"{count} stale JMeter process(es) running")
        except ValueError:
            pass

        # Check for stale run dirs from previous tests
        result = executor.execute("ls -d /opt/jmeter/runs/baseline_* 2>/dev/null | head -5")
        if result.success and result.stdout.strip():
            dirs = result.stdout.strip().split("\n")
            # Filter out the current test's dir
            stale = [d for d in dirs if f"baseline_{test_run_id}" not in d]
            if stale:
                issues.append(f"stale run dirs from previous tests: {', '.join(stale)}")

        # Check for running emulator processes on loadgen
        result = executor.execute("pgrep -f '[e]mulator' -c 2>/dev/null || echo 0")
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        emu_count_str = lines[-1] if lines else "0"
        try:
            emu_count = int(emu_count_str)
            if emu_count > 0:
                # Emulator on loadgen is expected for pool templates — just note it
                issues.append(f"emulator process running ({emu_count} process(es)) — expected for pool templates")
        except ValueError:
            pass

        return issues

    # ------------------------------------------------------------------
    # Sanity check (pre-flight + connectivity + dirty checks)
    # ------------------------------------------------------------------
    def sanity_check(self, session: Session, test_run_id: int) -> Dict:
        """Run all pre-flight, connectivity, and dirty state checks without starting the test.

        Returns a dict with:
            passed: bool
            checks: list of {target, check, status, detail}
        """
        test_run = session.get(BaselineTestRunORM, test_run_id)
        if not test_run:
            return {"passed": False, "checks": [{"target": "system", "check": "test_run", "status": "fail", "detail": f"Test run {test_run_id} not found"}]}

        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)
        checks = []
        all_passed = True

        # 1. Pre-flight validation
        try:
            validator = BaselinePreFlightValidator(
                credentials=self._credentials,
                emulator_port=self._config.emulator.emulator_api_port,
            )
            result = validator.validate(session, test_run)
            if result.passed:
                checks.append({"target": "system", "check": "pre_flight_validation", "status": "pass", "detail": "All pre-flight checks passed"})
            else:
                all_passed = False
                error_msgs = "; ".join(f"[{e.check}] {e.message}" for e in result.errors)
                checks.append({"target": "system", "check": "pre_flight_validation", "status": "fail", "detail": error_msgs})
        except Exception as e:
            all_passed = False
            checks.append({"target": "system", "check": "pre_flight_validation", "status": "fail", "detail": str(e)})

        # 2. cycle_count validation
        if test_run.cycle_count < 1:
            all_passed = False
            checks.append({"target": "system", "check": "cycle_count", "status": "fail", "detail": f"cycle_count={test_run.cycle_count} (must be >= 1)"})
        else:
            checks.append({"target": "system", "check": "cycle_count", "status": "pass", "detail": f"cycle_count={test_run.cycle_count}"})

        # 3. Hypervisor connectivity
        try:
            hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
            provider = create_hypervisor_provider(
                hypervisor_type=lab.hypervisor_type.value,
                url=lab.hypervisor_manager_url,
                port=lab.hypervisor_manager_port,
                credential=hyp_cred,
            )
            checks.append({"target": "hypervisor", "check": "connectivity", "status": "pass", "detail": f"{lab.hypervisor_type.value} at {lab.hypervisor_manager_url}"})
        except Exception as e:
            all_passed = False
            checks.append({"target": "hypervisor", "check": "connectivity", "status": "fail", "detail": str(e)})

        # 4. Loadgen checks (per unique loadgen)
        #    If clean_snapshot_id exists: revert to it first, then check SSH only
        #    (JMeter/emulator will be installed during deploying_loadgen)
        #    If no clean snapshot: check current state as-is
        seen_loadgens = set()
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)
            lg_label = f"loadgen:{loadgen.hostname}"

            # Revert loadgen to clean snapshot if available
            if loadgen.clean_snapshot_id:
                clean_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                if clean_snap:
                    try:
                        logger.info("Sanity check: reverting loadgen %s to clean snapshot '%s'",
                                    loadgen.hostname, clean_snap.name)
                        new_ip = provider.restore_snapshot(loadgen.server_infra_ref, clean_snap.provider_ref)
                        provider.wait_for_vm_ready(loadgen.server_infra_ref)
                        if new_ip and new_ip != loadgen.ip_address:
                            loadgen.ip_address = new_ip
                            session.commit()
                        wait_for_ssh(loadgen.ip_address, os_family=loadgen.os_family.value, timeout_sec=120)
                        checks.append({"target": lg_label, "check": "clean_snapshot_revert", "status": "pass",
                                       "detail": f"Reverted to '{clean_snap.name}', SSH OK"})
                        # After revert to clean snapshot: JMeter/emulator are gone (expected).
                        # They will be installed during deploying_loadgen. No further checks needed.
                        checks.append({"target": lg_label, "check": "jmeter_binary", "status": "info",
                                       "detail": "Will be installed during deploying_loadgen"})
                        checks.append({"target": lg_label, "check": "dirty_state", "status": "pass",
                                       "detail": "Clean (reverted to clean snapshot)"})
                        continue
                    except Exception as e:
                        all_passed = False
                        checks.append({"target": lg_label, "check": "clean_snapshot_revert", "status": "fail",
                                       "detail": str(e)})
                        continue
                else:
                    checks.append({"target": lg_label, "check": "clean_snapshot_revert", "status": "warn",
                                   "detail": f"clean_snapshot_id={loadgen.clean_snapshot_id} but DB record not found"})

            # No clean snapshot — check current state as-is
            try:
                loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
                loadgen_exec = create_executor(
                    os_family=loadgen.os_family.value,
                    host=loadgen.ip_address,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )
                try:
                    # SSH connectivity
                    checks.append({"target": lg_label, "check": "ssh_connectivity", "status": "pass",
                                   "detail": f"SSH to {loadgen.ip_address} OK"})

                    # JMeter binary
                    jmeter_check = loadgen_exec.execute("/opt/jmeter/bin/jmeter --version")
                    if jmeter_check.success:
                        checks.append({"target": lg_label, "check": "jmeter_binary", "status": "pass",
                                       "detail": "jmeter --version OK"})
                    else:
                        checks.append({"target": lg_label, "check": "jmeter_binary", "status": "info",
                                       "detail": "JMeter not installed (will be deployed during deploying_loadgen)"})

                    # Dirty state check
                    issues = self._check_dirty_loadgen(loadgen_exec, loadgen, test_run.id)
                    if issues:
                        for issue in issues:
                            if "stale JMeter" in issue:
                                checks.append({"target": lg_label, "check": "dirty_state", "status": "warn",
                                               "detail": f"{issue} (will be killed on start)"})
                            elif "stale run dirs" in issue:
                                checks.append({"target": lg_label, "check": "dirty_state", "status": "warn",
                                               "detail": issue})
                            else:
                                checks.append({"target": lg_label, "check": "dirty_state", "status": "info",
                                               "detail": issue})
                    else:
                        checks.append({"target": lg_label, "check": "dirty_state", "status": "pass",
                                       "detail": "Clean"})
                finally:
                    loadgen_exec.close()
            except Exception as e:
                all_passed = False
                checks.append({"target": lg_label, "check": "ssh_connectivity", "status": "fail",
                               "detail": str(e)})

        # 5. Target checks (per target): revert to snapshot FIRST, then check
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            target_label = f"target:{server.hostname}"

            # 5a. Snapshot exists on hypervisor
            try:
                provider.snapshot_exists(server.server_infra_ref, test_snapshot.provider_ref)
                checks.append({"target": target_label, "check": "snapshot_exists", "status": "pass", "detail": f"Snapshot '{test_snapshot.name}' found on hypervisor"})
            except Exception as e:
                all_passed = False
                checks.append({"target": target_label, "check": "snapshot_exists", "status": "fail", "detail": f"Snapshot check failed: {e}"})
                continue  # Can't revert if snapshot doesn't exist

            # 5b. Revert to test snapshot
            try:
                checks.append({"target": target_label, "check": "snapshot_revert", "status": "info", "detail": f"Reverting to '{test_snapshot.name}'..."})
                new_ip = provider.restore_snapshot(server.server_infra_ref, test_snapshot.provider_ref)
                provider.wait_for_vm_ready(server.server_infra_ref)
                actual_ip = server.ip_address
                if new_ip and new_ip != server.ip_address:
                    actual_ip = new_ip
                    server.ip_address = new_ip
                    session.commit()
                checks.append({"target": target_label, "check": "snapshot_revert", "status": "pass", "detail": f"Reverted to '{test_snapshot.name}'"})
            except Exception as e:
                all_passed = False
                checks.append({"target": target_label, "check": "snapshot_revert", "status": "fail", "detail": f"Revert failed: {e}"})
                continue

            # 5c. Wait for SSH/WinRM after revert
            try:
                actual_ip = server.ip_address
                wait_for_ssh(actual_ip, os_family=server.os_family.value, timeout_sec=120)
                checks.append({"target": target_label, "check": "connectivity", "status": "pass", "detail": f"{'WinRM' if server.os_family.value == 'windows' else 'SSH'} to {actual_ip} OK after revert"})
            except Exception as e:
                all_passed = False
                checks.append({"target": target_label, "check": "connectivity", "status": "fail", "detail": f"Not reachable after revert: {e}"})
                continue

            # 5d. Dirty snapshot check (on the REVERTED snapshot state)
            try:
                target_cred = self._credentials.get_server_credential(server.id, server.os_family.value)
                target_exec = create_executor(
                    os_family=server.os_family.value,
                    host=server.ip_address,
                    username=target_cred.username,
                    password=target_cred.password,
                )
                try:
                    self._check_dirty_snapshot(target_exec, server, test_snapshot.name)
                    checks.append({"target": target_label, "check": "dirty_state", "status": "pass", "detail": "Snapshot is clean (no stale emulator artifacts after revert)"})
                except RuntimeError as e:
                    all_passed = False
                    checks.append({"target": target_label, "check": "dirty_state", "status": "fail", "detail": str(e)})
                finally:
                    target_exec.close()
            except Exception as e:
                all_passed = False
                checks.append({"target": target_label, "check": "dirty_state", "status": "fail", "detail": str(e)})

        return {"passed": all_passed, "checks": checks}

    # ------------------------------------------------------------------
    # Helper: validate file exists on remote
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_remote_file(executor, path: str, description: str) -> None:
        """Check that a file exists on the remote and has size > 0."""
        result = executor.execute(f"test -f {path} && stat --printf='%s' {path}")
        if not result.success:
            raise RuntimeError(f"Validation failed: {description} not found at {path}")
        try:
            size = int(result.stdout.strip())
            if size == 0:
                raise RuntimeError(f"Validation failed: {description} at {path} is empty (0 bytes)")
        except ValueError:
            pass  # Some systems don't support --printf, file exists if test -f passed

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

        # Validate cycle_count
        if test_run.cycle_count < 1:
            sm.fail(session, test_run, f"Invalid cycle_count: {test_run.cycle_count} (must be >= 1)")
            return

        sm.transition(session, test_run, BaselineTestState.deploying_loadgen)

    # ------------------------------------------------------------------
    # State: DEPLOYING_LOADGEN (one-time gate)
    # ------------------------------------------------------------------
    def _get_orchestrator_url(self) -> str:
        """Build the orchestrator's own HTTP URL for WinRM file pulls."""
        import socket
        host = socket.gethostname()
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            ip = "127.0.0.1"
        return f"http://{ip}:8000"

    def _do_deploying_loadgen(self, session: Session, test_run: BaselineTestRunORM) -> None:
        """Revert loadgens to clean snapshot, then install JMeter (and emulator if needed)."""
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        resolver = PackageResolver()
        deployer = PackageDeployer()
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT

        # Create hypervisor provider for loadgen revert
        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        seen_loadgens = set()
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            if loadgen.id in seen_loadgens:
                continue
            seen_loadgens.add(loadgen.id)

            # Revert loadgen to clean snapshot (if one exists)
            if loadgen.clean_snapshot_id:
                clean_snap = session.get(SnapshotORM, loadgen.clean_snapshot_id)
                if clean_snap:
                    logger.info("Reverting loadgen %s to clean snapshot '%s'",
                                loadgen.hostname, clean_snap.name)
                    new_ip = provider.restore_snapshot(loadgen.server_infra_ref, clean_snap.provider_ref)
                    provider.wait_for_vm_ready(loadgen.server_infra_ref)
                    if new_ip and new_ip != loadgen.ip_address:
                        logger.info("Loadgen %s IP changed: %s -> %s",
                                    loadgen.hostname, loadgen.ip_address, new_ip)
                        loadgen.ip_address = new_ip
                        session.commit()
                    wait_for_ssh(loadgen.ip_address, os_family=loadgen.os_family.value, timeout_sec=120)
                    logger.info("Loadgen %s reverted and reachable", loadgen.hostname)
                else:
                    logger.warning("Loadgen %s has clean_snapshot_id=%d but record not found, skipping revert",
                                   loadgen.hostname, loadgen.clean_snapshot_id)
            else:
                logger.info("Loadgen %s has no clean snapshot, skipping revert (kill stale processes only)",
                            loadgen.hostname)

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
                # Clean slate: kill stale processes and remove old installations
                loadgen_exec.execute("pgrep -f '[j]meter' | xargs -r kill -9 2>/dev/null; true")
                loadgen_exec.execute("pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; true")

                # Remove old dirs — try multiple approaches
                for d in ["/opt/jmeter", "/opt/emulator"]:
                    loadgen_exec.execute(f"sudo rm -rf {d} 2>&1 || rm -rf {d} 2>&1 || true")
                    # Verify it's actually gone
                    check = loadgen_exec.execute(f"test -e {d} && echo EXISTS || echo GONE")
                    status = check.stdout.strip().split('\n')[-1].strip()
                    if status == "EXISTS":
                        # Last resort: try removing contents and the dir separately
                        loadgen_exec.execute(f"sudo rm -rf {d}/* 2>&1; sudo rmdir {d} 2>&1 || true")
                        check2 = loadgen_exec.execute(f"test -e {d} && echo EXISTS || echo GONE")
                        status2 = check2.stdout.strip().split('\n')[-1].strip()
                        if status2 == "EXISTS":
                            logger.warning("Could not remove %s on %s — will attempt deploy anyway", d, loadgen.hostname)
                        else:
                            logger.info("Removed %s on %s (second attempt)", d, loadgen.hostname)
                    else:
                        logger.info("Removed %s on %s", d, loadgen.hostname)

                # Install JMeter
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

                # Validate JMeter binary
                jmeter_check = loadgen_exec.execute("/opt/jmeter/bin/jmeter --version")
                if not jmeter_check.success:
                    raise RuntimeError(f"JMeter validation failed on {loadgen.hostname}: {jmeter_check.stderr}")

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

                    # Start emulator on loadgen
                    for pkg in emu_packages:
                        if pkg.run_command:
                            lg_start_cmd = f"sudo {pkg.run_command}" if loadgen.os_family.value != "windows" else pkg.run_command
                            logger.info("Starting emulator on loadgen %s: %s", loadgen.hostname, lg_start_cmd)
                            result = loadgen_exec.execute(lg_start_cmd, timeout_sec=60)
                            if not result.success:
                                raise RuntimeError(
                                    f"Emulator start on loadgen {loadgen.hostname} failed: {result.stderr}"
                                )

                    # Validate emulator responding on loadgen
                    lg_em_client = EmulatorClient(
                        host=loadgen.ip_address, port=self._config.emulator.emulator_api_port,
                    )
                    try:
                        lg_em_client.health_check()
                        logger.info("Emulator health check passed on loadgen %s", loadgen.hostname)
                    except Exception as e:
                        raise RuntimeError(
                            f"Emulator health check failed on loadgen {loadgen.hostname}: {e}"
                        )
                    finally:
                        try:
                            lg_em_client.close()
                        except Exception:
                            pass
            finally:
                loadgen_exec.close()

        # Transition based on test type
        if test_run.test_type in (
            BaselineTestType.new_baseline,
            BaselineTestType.compare_with_new_calibration,
        ):
            # Set current LP to first
            sm.update_current_profile(session, test_run, load_profiles[0].id)
            sm.transition(session, test_run, BaselineTestState.deploying_calibration)
        else:
            # compare: skip calibration, go to testing
            sm.update_current_profile(session, test_run, load_profiles[0].id)
            sm.update_current_cycle(session, test_run, 1)
            sm.transition(session, test_run, BaselineTestState.deploying_testing)

    # ------------------------------------------------------------------
    # State: DEPLOYING_CALIBRATION (per LP)
    # ------------------------------------------------------------------
    def _do_deploying_calibration(self, session: Session, test_run: BaselineTestRunORM) -> None:
        """Set up targets and loadgen for one calibration LP."""
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        current_lp_id = test_run.current_load_profile_id
        current_lp = session.get(LoadProfileORM, current_lp_id)

        resolver = PackageResolver()
        deployer = PackageDeployer()
        orchestrator_url = self._get_orchestrator_url()

        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        # Set all target states
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(
                session, target_orm, BaselineTargetState.deploying_calibration,
                load_profile_id=current_lp_id,
            )

        # ── LP-level setup (loadgen, per target) ──
        artifacts_dir = Path(self._config.artifacts_dir)

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
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
                # Kill stale JMeter for this target's IP (every target, not just first per loadgen)
                jmeter_ctrl = JMeterController(
                    executor=loadgen_exec,
                    jmeter_bin="/opt/jmeter/bin/jmeter",
                    os_family=loadgen.os_family.value,
                )
                jmeter_ctrl.kill_for_target(server.ip_address)

                run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

                # Create/clean run dir
                loadgen_exec.execute(f"sudo rm -rf {run_dir}")
                loadgen_exec.execute(f"sudo mkdir -p {run_dir}")
                loadgen_exec.execute(f"sudo chown -R {loadgen_cred.username} /opt/jmeter/runs/baseline_{test_run.id}")

                # Upload JMX template
                jmx_template_name = f"{scenario.template_type.value}.jmx"
                local_jmx = str(artifacts_dir / "jmx" / jmx_template_name)
                loadgen_exec.upload(local_jmx, f"{run_dir}/test.jmx")

                # Upload kill script
                local_kill_script = str(artifacts_dir / "scripts" / "jmeter_kill.py")
                self._sudo_upload(loadgen_exec, local_kill_script, "/opt/jmeter/bin/jmeter_kill.py")
                loadgen_exec.execute("sudo chmod +x /opt/jmeter/bin/jmeter_kill.py")

                # Upload calibration CSV
                self._deploy_calibration_csv(
                    loadgen_exec, run_dir, scenario, test_run.id, server.id,
                )

                # Validate files
                self._validate_remote_file(loadgen_exec, f"{run_dir}/test.jmx", "JMX template")
                self._validate_remote_file(loadgen_exec, f"{run_dir}/calibration_ops.csv", "Calibration CSV")
                self._validate_remote_file(loadgen_exec, "/opt/jmeter/bin/jmeter_kill.py", "Kill script")
            finally:
                loadgen_exec.close()

        # ── Per-cycle setup (target): revert + deploy emulator — PARALLEL ──
        # Calibration is always 1 cycle per LP
        is_first_lp = (load_profiles[0].id == current_lp_id)
        emulator_port = self._config.emulator.emulator_api_port
        emu_grp_id = lab.emulator_package_grp_id
        scenario_id = test_run.scenario_id

        def _deploy_one_cal_target(target_info):
            """Revert snapshot + deploy emulator on one target. Own DB session for discovery."""
            (target_orm_id, server_id, server_hostname, server_ip,
             server_os_family, server_infra_ref, snap_provider_ref, snap_name) = target_info

            thread_session = SessionLocal()
            try:
                # Revert snapshot
                new_ip = provider.restore_snapshot(server_infra_ref, snap_provider_ref)
                provider.wait_for_vm_ready(server_infra_ref)
                actual_ip = server_ip
                if new_ip and new_ip != server_ip:
                    actual_ip = new_ip
                    srv = thread_session.get(ServerORM, server_id)
                    srv.ip_address = new_ip
                    thread_session.commit()

                wait_for_ssh(actual_ip, os_family=server_os_family)

                # Discovery (first LP only)
                if is_first_lp:
                    try:
                        discovery_dir = Path(__file__).resolve().parent.parent.parent.parent / "discovery"
                        discovery = DiscoveryService(self._credentials, discovery_dir)
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
                        thread_session.commit()
                    except Exception as e:
                        logger.warning("Discovery failed for %s (non-fatal): %s", server_hostname, e)

                # Clean slate + emulator deploy
                target_cred = self._credentials.get_server_credential(server_id, server_os_family)
                target_exec = create_executor(
                    os_family=server_os_family,
                    host=actual_ip,
                    username=target_cred.username,
                    password=target_cred.password,
                    orchestrator_url=orchestrator_url,
                )
                try:
                    # Safety: kill stale emulator + clean dirs before dirty check
                    if server_os_family == "windows":
                        target_exec.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
                        target_exec.execute(
                            'powershell -Command "'
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                            '"'
                        )
                    else:
                        target_exec.execute("pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; true")
                        target_exec.execute("rm -rf /opt/emulator/output/* /opt/emulator/stats/* 2>/dev/null; "
                                            "sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/* 2>/dev/null; true")

                    self._check_dirty_snapshot(target_exec, thread_session.get(ServerORM, server_id), snap_name)

                    if emu_grp_id:
                        emu_packages = resolver.resolve(
                            thread_session, [emu_grp_id], thread_session.get(ServerORM, server_id),
                        )
                        deployer.deploy_all(target_exec, emu_packages)
                        for pkg in emu_packages:
                            if pkg.run_command:
                                start_cmd = f"sudo {pkg.run_command}" if server_os_family != "windows" else pkg.run_command
                                result = target_exec.execute(start_cmd, timeout_sec=60)
                                if not result.success:
                                    raise RuntimeError(f"Emulator start failed on {server_hostname}: {result.stderr}")

                    # Validate emulator responding
                    em_client = EmulatorClient(host=actual_ip, port=emulator_port)
                    try:
                        em_client.health_check()
                    except Exception as e:
                        raise RuntimeError(f"Emulator health check failed on {server_hostname}: {e}")
                    finally:
                        try:
                            em_client.close()
                        except Exception:
                            pass
                finally:
                    target_exec.close()

                return (server_hostname, None)
            except Exception as e:
                logger.error("Deploy calibration failed for %s: %s\n%s", server_hostname, e, traceback.format_exc())
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        # Build plain data tuples for thread function
        deploy_tasks = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            deploy_tasks.append((
                target_orm.id, server.id, server.hostname, server.ip_address,
                server.os_family.value, server.server_infra_ref,
                test_snapshot.provider_ref, test_snapshot.name,
            ))

        # Run all target deploys in parallel
        errors = []
        hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets
        }
        with ThreadPoolExecutor(max_workers=len(deploy_tasks)) as pool:
            futures = {pool.submit(_deploy_one_cal_target, t): t for t in deploy_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=f"[LP={current_lp.name}] {err}",
                        )

        # Strict barrier: any failure -> test fails
        if errors:
            raise RuntimeError(
                f"Deploy calibration failed for {len(errors)}/{len(deploy_tasks)} target(s) "
                f"[LP={current_lp.name}]:\n" + "\n".join(errors)
            )

        # Refresh main session after parallel threads committed changes
        session.expire_all()

        # ── BARRIER: all targets deployed for calibration ──
        sm.transition(session, test_run, BaselineTestState.calibrating)

    # ------------------------------------------------------------------
    # State: CALIBRATING (single LP, parallel per target)
    # ------------------------------------------------------------------
    def _do_calibration(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        current_lp_id = test_run.current_load_profile_id
        current_lp = session.get(LoadProfileORM, current_lp_id)

        emulator_port = self._config.emulator.emulator_api_port
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT
        cal_config = self._config.calibration
        stats_interval = self._config.stats.collect_interval_sec
        results_dir = self._config.results_dir
        test_run_id = test_run.id
        scenario_template = scenario.template_type

        def _calibrate_one_target(target_info):
            (target_orm_id, server_id, server_hostname, server_ip,
             server_os_family, loadgen_id, loadgen_ip, loadgen_os_family,
             partner_id, output_folders, service_monitor_patterns,
             lp_id, lp_name, lp_cpu_min, lp_cpu_max, lp_ramp, lp_duration) = target_info

            thread_session = SessionLocal()
            calibration_engine = CalibrationEngine(cal_config)
            try:
                target_cred = self._credentials.get_server_credential(server_id, server_os_family)
                loadgen_cred = self._credentials.get_server_credential(loadgen_id, loadgen_os_family)
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
                    jmeter_ctrl.kill_for_target(server_ip)

                    extra_props = None
                    if needs_pool:
                        BaselineOrchestrator._setup_pool(em_client, scenario_template)
                        extra_props = BaselineOrchestrator._build_work_extra_properties()

                    run_dir = f"/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}"

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

        # Prepare tasks — single LP only
        dur, ramp = duration_overrides.get(current_lp.id, (current_lp.duration_sec, current_lp.ramp_up_sec))
        cal_tasks = []
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.calibrating)
            cal_tasks.append((
                target_orm.id, server.id, server.hostname, server.ip_address,
                server.os_family.value, loadgen.id, loadgen.ip_address,
                loadgen.os_family.value, target_orm.partner_id,
                target_orm.output_folders, target_orm.service_monitor_patterns,
                current_lp.id, current_lp.name, current_lp.target_cpu_range_min,
                current_lp.target_cpu_range_max, ramp, dur,
            ))

        hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, _ in targets
        }

        # Run calibration in parallel — strict barrier
        errors = []
        with ThreadPoolExecutor(max_workers=len(cal_tasks)) as pool:
            futures = {pool.submit(_calibrate_one_target, t): t for t in cal_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=f"[LP={current_lp.name}] {err}",
                        )

        # Strict barrier: any failure -> test fails
        if errors:
            raise RuntimeError(
                f"Calibration failed for {len(errors)}/{len(cal_tasks)} target(s) "
                f"[LP={current_lp.name}]:\n" + "\n".join(errors)
            )

        session.expire_all()
        sm.transition(session, test_run, BaselineTestState.generating)

    # ------------------------------------------------------------------
    # State: GENERATING (single LP, parallel per target)
    # ------------------------------------------------------------------
    def _do_generation(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        current_lp_id = test_run.current_load_profile_id
        current_lp = session.get(LoadProfileORM, current_lp_id)

        import sys
        gen_root = str(Path(__file__).resolve().parents[4] / "db-assets")
        if gen_root not in sys.path:
            sys.path.insert(0, gen_root)
        from generator.generators.ops_sequence_generator import OpsSequenceGenerator

        test_run_id = test_run.id
        generated_dir = self._config.generated_dir

        def _generate_one_target(target_info):
            (server_id, server_hostname, loadgen_id, loadgen_ip,
             loadgen_os_family, lp_id, lp_name, lp_duration) = target_info

            thread_session = SessionLocal()
            try:
                loadgen_cred = self._credentials.get_server_credential(loadgen_id, loadgen_os_family)
                loadgen_exec = create_executor(
                    os_family=loadgen_os_family,
                    host=loadgen_ip,
                    username=loadgen_cred.username,
                    password=loadgen_cred.password,
                )
                try:
                    run_dir = f"/opt/jmeter/runs/baseline_{test_run_id}/lg_{loadgen_id}/target_{server_id}"

                    cal = thread_session.query(CalibrationResultORM).filter(
                        CalibrationResultORM.baseline_test_run_id == test_run_id,
                        CalibrationResultORM.server_id == server_id,
                        CalibrationResultORM.load_profile_id == lp_id,
                    ).first()
                    if not cal:
                        raise RuntimeError(f"No calibration result for server {server_id} / profile {lp_id}")
                    thread_count = cal.thread_count

                    seq_count = OpsSequenceGenerator.calculate_sequence_length(
                        thread_count=thread_count, duration_sec=lp_duration,
                    )

                    gen = self._create_generator_for_template(scenario, str(test_run_id), lp_name)
                    ops = gen.generate(seq_count)

                    local_dir = Path(generated_dir) / str(test_run_id) / "ops_sequences" / str(server_id)
                    local_dir.mkdir(parents=True, exist_ok=True)
                    local_path = str(local_dir / f"ops_sequence_{lp_name}.csv")
                    gen.write_csv(ops, local_path)

                    remote_path = f"{run_dir}/ops_sequence_{lp_name}.csv"
                    loadgen_exec.upload(local_path, remote_path)

                    # Validate
                    self._validate_remote_file(loadgen_exec, remote_path, f"Ops sequence for {lp_name}")

                    logger.info(
                        "Generated ops sequence for server %s: %s (%d rows, threads=%d) profile '%s'",
                        server_hostname, local_path, seq_count, thread_count, lp_name,
                    )
                finally:
                    loadgen_exec.close()
                return (server_hostname, None)
            except Exception as e:
                logger.error("Generation failed for %s: %s\n%s", server_hostname, e, traceback.format_exc())
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        # Prepare tasks — single LP
        dur, _ = duration_overrides.get(current_lp.id, (current_lp.duration_sec, current_lp.ramp_up_sec))
        gen_tasks = []
        for target_orm, server, loadgen, test_snapshot, _ in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.generating)
            gen_tasks.append((
                server.id, server.hostname, loadgen.id, loadgen.ip_address,
                loadgen.os_family.value, current_lp.id, current_lp.name, dur,
            ))

        hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, _ in targets
        }

        # Run generation in parallel — strict barrier
        errors = []
        with ThreadPoolExecutor(max_workers=len(gen_tasks)) as pool:
            futures = {pool.submit(_generate_one_target, t): t for t in gen_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=f"[LP={current_lp.name}] {err}",
                        )

        if errors:
            raise RuntimeError(
                f"Generation failed for {len(errors)}/{len(gen_tasks)} target(s) "
                f"[LP={current_lp.name}]:\n" + "\n".join(errors)
            )

        # Determine next state
        next_cal_lp = self._next_cal_iteration(test_run, load_profiles)
        if next_cal_lp is not None:
            # More calibration LPs
            sm.update_current_profile(session, test_run, next_cal_lp)
            sm.transition(session, test_run, BaselineTestState.deploying_calibration)
        else:
            # All cal done -> first test LP, cycle 1
            sm.update_current_profile(session, test_run, load_profiles[0].id)
            sm.update_current_cycle(session, test_run, 1)
            sm.transition(session, test_run, BaselineTestState.deploying_testing)

    # ------------------------------------------------------------------
    # State: DEPLOYING_TESTING (per LP x cycle)
    # ------------------------------------------------------------------
    def _do_deploying_testing(self, session: Session, test_run: BaselineTestRunORM) -> None:
        """Set up targets and loadgen for one test cycle."""
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        current_lp_id = test_run.current_load_profile_id
        current_lp = session.get(LoadProfileORM, current_lp_id)
        current_cycle = test_run.current_cycle

        resolver = PackageResolver()
        deployer = PackageDeployer()
        orchestrator_url = self._get_orchestrator_url()
        artifacts_dir = Path(self._config.artifacts_dir)

        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        provider = create_hypervisor_provider(
            hypervisor_type=lab.hypervisor_type.value,
            url=lab.hypervisor_manager_url,
            port=lab.hypervisor_manager_port,
            credential=hyp_cred,
        )

        # Set all target states
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(
                session, target_orm, BaselineTargetState.deploying_testing,
                load_profile_id=current_lp_id,
            )

        is_first_cycle = (current_cycle == 1)

        # ── LP-level setup (first cycle of each LP only) ──
        if is_first_cycle:
            for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
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

                    # Clean run dir (remove previous LP's artifacts)
                    loadgen_exec.execute(f"sudo rm -rf {run_dir}")
                    loadgen_exec.execute(f"sudo mkdir -p {run_dir}")
                    loadgen_exec.execute(f"sudo chown -R {loadgen_cred.username} /opt/jmeter/runs/baseline_{test_run.id}")

                    # Upload JMX template
                    jmx_template_name = f"{scenario.template_type.value}.jmx"
                    local_jmx = str(artifacts_dir / "jmx" / jmx_template_name)
                    loadgen_exec.upload(local_jmx, f"{run_dir}/test.jmx")

                    # Upload kill script
                    local_kill_script = str(artifacts_dir / "scripts" / "jmeter_kill.py")
                    self._sudo_upload(loadgen_exec, local_kill_script, "/opt/jmeter/bin/jmeter_kill.py")
                    loadgen_exec.execute("sudo chmod +x /opt/jmeter/bin/jmeter_kill.py")

                    # Upload ops sequence CSV from local copy (or stored data for compare)
                    if test_run.test_type == BaselineTestType.compare and compare_snapshot:
                        self._deploy_stored_jmx_data(
                            session, loadgen_exec, run_dir, compare_snapshot, [current_lp],
                        )
                    else:
                        local_ops = str(
                            Path(self._config.generated_dir) / str(test_run.id)
                            / "ops_sequences" / str(server.id) / f"ops_sequence_{current_lp.name}.csv"
                        )
                        loadgen_exec.upload(local_ops, f"{run_dir}/ops_sequence_{current_lp.name}.csv")

                    # Validate files
                    self._validate_remote_file(loadgen_exec, f"{run_dir}/test.jmx", "JMX template")
                    self._validate_remote_file(
                        loadgen_exec, f"{run_dir}/ops_sequence_{current_lp.name}.csv",
                        f"Ops sequence for {current_lp.name}",
                    )
                    self._validate_remote_file(loadgen_exec, "/opt/jmeter/bin/jmeter_kill.py", "Kill script")
                finally:
                    loadgen_exec.close()

        # ── Per-cycle setup (every cycle) ──

        # Kill stale JMeter + clean previous cycle artifacts on loadgens
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
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

                # Kill stale JMeter for this target's IP
                jmeter_ctrl = JMeterController(
                    executor=loadgen_exec,
                    jmeter_bin="/opt/jmeter/bin/jmeter",
                    os_family=loadgen.os_family.value,
                )
                jmeter_ctrl.kill_for_target(server.ip_address)

                # Clean previous cycle artifacts (fixed names on loadgen)
                loadgen_exec.execute(f"rm -f {run_dir}/results.jtl {run_dir}/jmeter.log")
            finally:
                loadgen_exec.close()

        # Revert + deploy emulator on each target — PARALLEL
        emulator_port = self._config.emulator.emulator_api_port
        emu_grp_id = lab.emulator_package_grp_id

        def _deploy_one_test_target(target_info):
            """Revert snapshot + deploy emulator on one target for testing."""
            (server_id, server_hostname, server_ip, server_os_family,
             server_infra_ref, snap_provider_ref, snap_name) = target_info

            thread_session = SessionLocal()
            try:
                new_ip = provider.restore_snapshot(server_infra_ref, snap_provider_ref)
                provider.wait_for_vm_ready(server_infra_ref)
                actual_ip = server_ip
                if new_ip and new_ip != server_ip:
                    actual_ip = new_ip
                    srv = thread_session.get(ServerORM, server_id)
                    srv.ip_address = new_ip
                    thread_session.commit()

                wait_for_ssh(actual_ip, os_family=server_os_family)

                target_cred = self._credentials.get_server_credential(server_id, server_os_family)
                target_exec = create_executor(
                    os_family=server_os_family,
                    host=actual_ip,
                    username=target_cred.username,
                    password=target_cred.password,
                    orchestrator_url=orchestrator_url,
                )
                try:
                    # Safety: kill stale emulator + clean dirs before dirty check
                    if server_os_family == "windows":
                        target_exec.execute('powershell -Command "Stop-Process -Name *emulator* -Force -ErrorAction SilentlyContinue"')
                        target_exec.execute(
                            'powershell -Command "'
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\output\\*';"
                            "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'C:\\emulator\\stats\\*'"
                            '"'
                        )
                    else:
                        target_exec.execute("pgrep -f '[e]mulator' | xargs -r kill -9 2>/dev/null; true")
                        target_exec.execute("rm -rf /opt/emulator/output/* /opt/emulator/stats/* 2>/dev/null; "
                                            "sudo rm -rf /opt/emulator/output/* /opt/emulator/stats/* 2>/dev/null; true")

                    self._check_dirty_snapshot(target_exec, thread_session.get(ServerORM, server_id), snap_name)

                    if emu_grp_id:
                        emu_packages = resolver.resolve(
                            thread_session, [emu_grp_id], thread_session.get(ServerORM, server_id),
                        )
                        deployer.deploy_all(target_exec, emu_packages)
                        for pkg in emu_packages:
                            if pkg.run_command:
                                start_cmd = f"sudo {pkg.run_command}" if server_os_family != "windows" else pkg.run_command
                                result = target_exec.execute(start_cmd, timeout_sec=60)
                                if not result.success:
                                    raise RuntimeError(f"Emulator start failed on {server_hostname}: {result.stderr}")

                    em_client = EmulatorClient(host=actual_ip, port=emulator_port)
                    try:
                        em_client.health_check()
                    except Exception as e:
                        raise RuntimeError(f"Emulator health check failed on {server_hostname}: {e}")
                    finally:
                        try:
                            em_client.close()
                        except Exception:
                            pass
                finally:
                    target_exec.close()

                return (server_hostname, None)
            except Exception as e:
                logger.error("Deploy testing failed for %s: %s\n%s", server_hostname, e, traceback.format_exc())
                return (server_hostname, str(e))
            finally:
                thread_session.close()

        deploy_tasks = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            deploy_tasks.append((
                server.id, server.hostname, server.ip_address, server.os_family.value,
                server.server_infra_ref, test_snapshot.provider_ref, test_snapshot.name,
            ))

        errors = []
        hostname_to_target = {
            server.hostname: target_orm
            for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets
        }
        with ThreadPoolExecutor(max_workers=len(deploy_tasks)) as pool:
            futures = {pool.submit(_deploy_one_test_target, t): t for t in deploy_tasks}
            for future in as_completed(futures):
                hostname, err = future.result()
                if err:
                    errors.append(f"[{hostname}] {err}")
                    t_orm = hostname_to_target.get(hostname)
                    if t_orm:
                        session.expire(t_orm)
                        self._set_target_state(
                            session, t_orm, BaselineTargetState.failed,
                            error_message=f"[LP={current_lp.name}, cycle={current_cycle}] {err}",
                        )

        if errors:
            raise RuntimeError(
                f"Deploy testing failed for {len(errors)}/{len(deploy_tasks)} target(s) "
                f"[LP={current_lp.name}, cycle={current_cycle}]:\n" + "\n".join(errors)
            )

        session.expire_all()

        # ── BARRIER: all targets ready for execution ──
        sm.transition(session, test_run, BaselineTestState.executing)

    # ------------------------------------------------------------------
    # State: EXECUTING (single LP, single cycle — inlined)
    # ------------------------------------------------------------------
    def _do_execution(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, duration_overrides = self._load_context(session, test_run)

        current_lp_id = test_run.current_load_profile_id
        current_lp = session.get(LoadProfileORM, current_lp_id)
        current_cycle = test_run.current_cycle
        needs_pool = scenario.template_type in self._POOL_HEAP_PERCENT
        emulator_port = self._config.emulator.emulator_api_port

        eff_duration, eff_ramp_up = duration_overrides.get(
            current_lp.id, (current_lp.duration_sec, current_lp.ramp_up_sec),
        )

        logger.info(
            "Executing LP='%s' cycle=%d/%d on %d targets (duration=%ds, ramp_up=%ds)",
            current_lp.name, current_cycle, test_run.cycle_count,
            len(targets), eff_duration, eff_ramp_up,
        )

        # Set target states
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.executing)

        # ── Phase A: Configure emulators + start stats ──
        target_resources = []
        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            target_cred = self._credentials.get_server_credential(server.id, server.os_family.value)
            target_exec = create_executor(
                os_family=server.os_family.value,
                host=server.ip_address,
                username=target_cred.username,
                password=target_cred.password,
                orchestrator_url=self._get_orchestrator_url(),
            )
            em_client = EmulatorClient(host=server.ip_address, port=emulator_port)

            # Configure emulator
            partner_fqdn = "localhost"
            if target_orm.partner_id and target_orm.partner_id != server.id:
                partner_server = session.get(ServerORM, target_orm.partner_id)
                partner_fqdn = partner_server.ip_address
            if target_orm.output_folders:
                out_folders = [f.strip() for f in target_orm.output_folders.split(",") if f.strip()]
            elif server.os_family.value == "windows":
                out_folders = ["C:\\emulator\\output"]
            else:
                out_folders = ["/opt/emulator/output"]
            em_client.set_config(
                output_folders=out_folders,
                partner={"fqdn": partner_fqdn, "port": emulator_port},
                stats={"default_interval_sec": self._config.stats.collect_interval_sec},
                service_monitor_patterns=target_orm.service_monitor_patterns,
            )

            # Get thread_count
            if test_run.test_type == BaselineTestType.compare:
                profile_data = session.query(SnapshotProfileDataORM).filter(
                    SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                    SnapshotProfileDataORM.load_profile_id == current_lp.id,
                ).first()
                if not profile_data:
                    raise RuntimeError(f"No stored profile data for compare snapshot / profile {current_lp.id}")
                thread_count = profile_data.thread_count
            else:
                cal = session.query(CalibrationResultORM).filter(
                    CalibrationResultORM.baseline_test_run_id == test_run.id,
                    CalibrationResultORM.server_id == server.id,
                    CalibrationResultORM.load_profile_id == current_lp.id,
                ).first()
                if not cal:
                    raise RuntimeError(f"No calibration result for server {server.id} / profile {current_lp.id}")
                thread_count = cal.thread_count

            # Start stats
            start_resp = em_client.start_test(
                test_run_id=str(test_run.id),
                scenario_id=scenario.name,
                mode="normal",
                collect_interval_sec=self._config.stats.collect_interval_sec,
                thread_count=thread_count,
                duration_sec=eff_duration,
            )
            test_id = start_resp.get("test_id", f"baseline-{test_run.id}-lp{current_lp.id}-srv{server.id}")

            # Pool setup
            extra_props = None
            if needs_pool:
                self._setup_pool(em_client, scenario.template_type)
                extra_props = self._build_work_extra_properties()

            loadgen_cred = self._credentials.get_server_credential(loadgen.id, loadgen.os_family.value)
            loadgen_exec = create_executor(
                os_family=loadgen.os_family.value,
                host=loadgen.ip_address,
                username=loadgen_cred.username,
                password=loadgen_cred.password,
            )
            jmeter_ctrl = JMeterController(
                executor=loadgen_exec,
                jmeter_bin="/opt/jmeter/bin/jmeter",
                os_family=loadgen.os_family.value,
            )

            run_dir = f"/opt/jmeter/runs/baseline_{test_run.id}/lg_{loadgen.id}/target_{server.id}"

            target_resources.append({
                "target_orm": target_orm,
                "server": server,
                "loadgen": loadgen,
                "test_snapshot": test_snapshot,
                "compare_snapshot": compare_snapshot,
                "target_exec": target_exec,
                "em_client": em_client,
                "test_id": test_id,
                "loadgen_exec": loadgen_exec,
                "jmeter_ctrl": jmeter_ctrl,
                "thread_count": thread_count,
                "extra_props": extra_props,
                "run_dir": run_dir,
            })

        # ── Phase B: Start JMeter on all targets ──
        jmeter_pids = []
        for tr in target_resources:
            server = tr["server"]
            try:
                ops_path = f"{tr['run_dir']}/ops_sequence_{current_lp.name}.csv"
                pid = tr["jmeter_ctrl"].start(
                    jmx_path=f"{tr['run_dir']}/test.jmx",
                    jtl_path=f"{tr['run_dir']}/results.jtl",
                    log_path=f"{tr['run_dir']}/jmeter.log",
                    thread_count=tr["thread_count"],
                    ramp_up_sec=eff_ramp_up,
                    duration_sec=86400,
                    target_host=server.ip_address,
                    target_port=emulator_port,
                    ops_sequence_path=ops_path,
                    extra_properties=tr["extra_props"],
                )
                jmeter_pids.append(pid)
                logger.info("Started JMeter for %s (pid=%s)", server.hostname, pid)
            except Exception as e:
                # Kill ALL JMeter on this loadgen
                try:
                    tr["loadgen_exec"].execute("pkill -f jmeter || true")
                except Exception:
                    pass
                raise RuntimeError(f"JMeter start failed on {server.hostname}: {e}")

        # ── Phase C: Wait ──
        total_wait = eff_ramp_up + eff_duration
        logger.info("Waiting %ds (ramp_up=%d + duration=%d)", total_wait, eff_ramp_up, eff_duration)
        time.sleep(total_wait)

        # ── Phase D: Stop + collect from all targets ──
        try:
            for i, tr in enumerate(target_resources):
                server = tr["server"]
                loadgen = tr["loadgen"]
                try:
                    # Stop JMeter
                    tr["jmeter_ctrl"].stop(jmeter_pids[i], jtl_path=f"{tr['run_dir']}/results.jtl")

                    # Stop emulator stats
                    tr["em_client"].stop_test(tr["test_id"])
                    stats_json = tr["em_client"].get_all_stats(test_run_id=str(test_run.id))

                    # Save stats (cycle-keyed)
                    results_base = Path(self._config.results_dir) / str(test_run.id) / f"server_{server.id}"
                    stats_dir = results_base / "stats"
                    stats_dir.mkdir(parents=True, exist_ok=True)
                    stats_path = str(stats_dir / f"lp{current_lp.id}_cycle{current_cycle}_stats.json")
                    with open(stats_path, "w", encoding="utf-8") as f:
                        json.dump(stats_json, f, indent=2)

                    # Download JTL (cycle-keyed local path)
                    jtl_dir = results_base / "jtl"
                    jtl_dir.mkdir(parents=True, exist_ok=True)
                    local_jtl = str(jtl_dir / f"lp{current_lp.id}_cycle{current_cycle}.jtl")
                    tr["loadgen_exec"].download(f"{tr['run_dir']}/results.jtl", local_jtl)

                    # Validate JTL
                    jtl_result = self._jtl_parser.parse(local_jtl)
                    success_rate = 100.0 - jtl_result.error_rate_percent
                    jtl_min = self._config.stats.jtl_min_success_rate_pct
                    logger.info(
                        "JTL: %s / LP='%s' / cycle=%d: %d requests, %d errors, %.2f%% success (threshold=%.1f%%)",
                        server.hostname, current_lp.name, current_cycle,
                        jtl_result.total_requests, jtl_result.total_errors, success_rate, jtl_min,
                    )
                    if jtl_result.total_requests == 0:
                        raise RuntimeError(
                            f"[LP={current_lp.name}, cycle={current_cycle}] "
                            f"JTL validation FAILED for {server.hostname}: 0 requests"
                        )
                    if success_rate < jtl_min:
                        raise RuntimeError(
                            f"[LP={current_lp.name}, cycle={current_cycle}] "
                            f"JTL validation FAILED for {server.hostname}: "
                            f"success rate {success_rate:.2f}% < {jtl_min:.1f}%"
                        )

                    # Download logs (non-fatal)
                    logs_dir = results_base / "logs"
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    local_jmeter_log = str(logs_dir / f"lp{current_lp.id}_cycle{current_cycle}_jmeter.log")
                    try:
                        tr["loadgen_exec"].download(f"{tr['run_dir']}/jmeter.log", local_jmeter_log)
                    except Exception as e:
                        logger.warning("Failed to download JMeter log (non-fatal): %s", e)
                        local_jmeter_log = ""

                    local_emulator_log = str(logs_dir / f"lp{current_lp.id}_cycle{current_cycle}_emulator_logs.tar.gz")
                    try:
                        tr["em_client"].download_logs(local_emulator_log)
                    except Exception as e:
                        logger.warning("Failed to download emulator logs (non-fatal): %s", e)
                        local_emulator_log = ""

                    # Compute stats summary
                    samples = stats_json.get("samples", [])
                    trimmed = self._stats_parser.trim_samples(
                        samples,
                        self._config.stats.stats_trim_start_sec,
                        self._config.stats.stats_trim_end_sec,
                    )
                    stats_summary = self._stats_parser.compute_summary(trimmed)

                    # Save JMX data (shared across cycles)
                    jmx_dir = results_base / "jmx_data"
                    jmx_dir.mkdir(parents=True, exist_ok=True)
                    local_jmx_data = str(jmx_dir / f"lp{current_lp.id}_ops_sequence.csv")
                    if not Path(local_jmx_data).exists():
                        ops_path = f"{tr['run_dir']}/ops_sequence_{current_lp.name}.csv"
                        tr["loadgen_exec"].download(ops_path, local_jmx_data)

                    # Destroy pool if allocated
                    if tr["extra_props"] and needs_pool:
                        self._destroy_pool(tr["em_client"])

                    # Store result in manifest (cycle-keyed)
                    self._save_execution_result(
                        test_run.id, server.id, current_lp.id, current_cycle,
                        ExecutionResult(
                            stats_path=stats_path,
                            jtl_path=local_jtl,
                            stats_summary=stats_summary,
                            jmx_test_case_data_path=local_jmx_data,
                            jmeter_log_path=local_jmeter_log,
                            emulator_log_path=local_emulator_log,
                            jtl_total_requests=jtl_result.total_requests,
                            jtl_total_errors=jtl_result.total_errors,
                            jtl_success_rate_pct=round(success_rate, 2),
                        ),
                    )

                    logger.info(
                        "Execution complete: %s LP='%s' cycle=%d",
                        server.hostname, current_lp.name, current_cycle,
                    )
                finally:
                    # Mark this target's resources as closed
                    tr["_closed"] = True
                    tr["target_exec"].close()
                    try:
                        tr["loadgen_exec"].close()
                    except Exception:
                        pass
                    try:
                        tr["em_client"].close()
                    except Exception:
                        pass
        finally:
            # Clean up any resources not yet closed (targets not reached in Phase D)
            for tr in target_resources:
                if tr.get("_closed"):
                    continue
                try:
                    tr["target_exec"].close()
                except Exception:
                    pass
                try:
                    tr["loadgen_exec"].close()
                except Exception:
                    pass
                try:
                    tr["em_client"].close()
                except Exception:
                    pass

        # Determine next state
        next_iter = self._next_test_iteration(test_run, load_profiles)
        if next_iter is not None:
            next_lp_id, next_cycle = next_iter
            sm.update_current_profile(session, test_run, next_lp_id)
            sm.update_current_cycle(session, test_run, next_cycle)
            sm.transition(session, test_run, BaselineTestState.deploying_testing)
        elif test_run.test_type == BaselineTestType.new_baseline:
            sm.transition(session, test_run, BaselineTestState.storing)
        else:
            sm.transition(session, test_run, BaselineTestState.comparing)

    # ------------------------------------------------------------------
    # State: COMPARING (all LPs x cycles)
    # ------------------------------------------------------------------
    def _do_comparison(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, _duration_overrides = self._load_context(session, test_run)

        from orchestrator.services.comparison import ComparisonEngine
        comparison_engine = ComparisonEngine(self._config)

        is_option_b = (test_run.test_type == BaselineTestType.compare_with_new_calibration)
        overall_verdict = Verdict.passed

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.comparing)

            for lp in load_profiles:
                compare_data = session.query(SnapshotProfileDataORM).filter(
                    SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                    SnapshotProfileDataORM.load_profile_id == lp.id,
                ).first()
                if not compare_data:
                    logger.warning(
                        "No stored profile data for snapshot '%s' / profile '%s' (server %s), skipping",
                        compare_snapshot.name, lp.name, server.hostname,
                    )
                    continue

                for cycle in range(1, test_run.cycle_count + 1):
                    exec_result = self._load_single_execution_result(
                        test_run.id, server.id, lp.id, cycle,
                    )
                    if not exec_result:
                        logger.warning(
                            "No execution result for server %s / LP='%s' / cycle=%d",
                            server.hostname, lp.name, cycle,
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
                        cycle=cycle,
                    )

                    if verdict == Verdict.failed:
                        overall_verdict = Verdict.failed
                    elif verdict == Verdict.warning and overall_verdict != Verdict.failed:
                        overall_verdict = Verdict.warning

        test_run.verdict = overall_verdict
        session.commit()
        sm.transition(session, test_run, BaselineTestState.storing)

    # ------------------------------------------------------------------
    # State: STORING (all LPs x cycles)
    # ------------------------------------------------------------------
    def _do_storing(self, session: Session, test_run: BaselineTestRunORM) -> None:
        lab, scenario, targets, load_profiles, _duration_overrides = self._load_context(session, test_run)

        all_targets_ok = True

        for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
            self._set_target_state(session, target_orm, BaselineTargetState.storing)

            try:
                for lp in load_profiles:
                    for cycle in range(1, test_run.cycle_count + 1):
                        exec_result = self._load_single_execution_result(
                            test_run.id, server.id, lp.id, cycle,
                        )
                        if not exec_result:
                            continue

                        # Determine source_snapshot_id and thread_count
                        if test_run.test_type == BaselineTestType.compare:
                            source_snapshot_id = compare_snapshot.id
                            compare_data = session.query(SnapshotProfileDataORM).filter(
                                SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                                SnapshotProfileDataORM.load_profile_id == lp.id,
                            ).first()
                            if not compare_data:
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
                                continue
                            thread_count = cal.thread_count
                            jmx_path = exec_result.jmx_test_case_data_path

                        summary_dict = (
                            dataclasses.asdict(exec_result.stats_summary)
                            if dataclasses.is_dataclass(exec_result.stats_summary)
                            else exec_result.stats_summary
                        )

                        # Upsert on (snapshot_id, load_profile_id, cycle)
                        existing = session.query(SnapshotProfileDataORM).filter(
                            SnapshotProfileDataORM.snapshot_id == test_snapshot.id,
                            SnapshotProfileDataORM.load_profile_id == lp.id,
                            SnapshotProfileDataORM.cycle == cycle,
                        ).first()

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
                                cycle=cycle,
                                thread_count=thread_count,
                                jmx_test_case_data=jmx_path,
                                stats_data=exec_result.stats_path,
                                stats_summary=summary_dict,
                                jtl_data=exec_result.jtl_path,
                                source_snapshot_id=source_snapshot_id,
                            )
                            session.add(profile_data)

                self._set_target_state(session, target_orm, BaselineTargetState.completed)
                logger.info(
                    "Stored profile data for server %s, snapshot '%s' (id=%d)",
                    server.hostname, test_snapshot.name, test_snapshot.id,
                )
            except Exception as e:
                logger.error("Storing failed for %s: %s", server.hostname, e)
                self._set_target_state(
                    session, target_orm, BaselineTargetState.failed,
                    error_message=str(e),
                )
                all_targets_ok = False

        if not all_targets_ok:
            raise RuntimeError("Storing failed for one or more targets")

        # Mark snapshot as baseline only after ALL targets succeed
        if test_run.test_type == BaselineTestType.new_baseline:
            for target_orm, server, loadgen, test_snapshot, compare_snapshot in targets:
                test_snapshot.is_baseline = True

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
                test_run_id=test_run_id, load_profile=load_profile_name,
            )
        elif template == TemplateType.db_load:
            return DbLoadOpsGenerator(
                test_run_id=test_run_id, load_profile=load_profile_name,
            )
        else:
            return ServerNormalOpsGenerator(test_run_id, load_profile_name)

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
    # Pool helpers
    # ------------------------------------------------------------------
    _POOL_HEAP_PERCENT = {
        TemplateType.server_steady: 0.5,
        TemplateType.server_file_heavy: 0.3,
    }

    @staticmethod
    def _setup_pool(em_client: 'EmulatorClient', template_type: 'TemplateType') -> None:
        pct = BaselineOrchestrator._POOL_HEAP_PERCENT.get(template_type, 0.5)
        logger.info("%s: requesting pool allocation at %.0f%% of JVM heap", template_type.value, pct * 100)
        result = em_client.allocate_pool_by_heap_percent(pct)
        logger.info("%s: pool allocated — %s", template_type.value, result)

    @staticmethod
    def _destroy_pool(em_client: 'EmulatorClient') -> None:
        try:
            result = em_client.destroy_pool()
            logger.info("Pool destroyed — %s", result)
        except Exception as e:
            logger.warning("Pool destroy failed (non-fatal): %s", e)

    def _cleanup_pools(self, session: Session, test_run: 'BaselineTestRunORM') -> None:
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
        return {
            "cpu_ms": "10",
            "intensity": "0.8",
            "touch_mb": "1.0",
        }

    # ------------------------------------------------------------------
    # Execution result persistence (cycle-keyed manifests)
    # ------------------------------------------------------------------
    def _save_execution_result(
        self, test_run_id: int, server_id: int, lp_id: int, cycle: int,
        result: ExecutionResult,
    ) -> None:
        """Save one execution result to the manifest (keyed by lp{id}_cycle{cycle})."""
        results_base = Path(self._config.results_dir) / str(test_run_id) / f"server_{server_id}"
        results_base.mkdir(parents=True, exist_ok=True)
        manifest_path = results_base / "execution_manifest.json"

        # Load existing manifest
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        key = f"lp{lp_id}_cycle{cycle}"
        manifest[key] = {
            "stats_path": result.stats_path,
            "jtl_path": result.jtl_path,
            "stats_summary": (
                dataclasses.asdict(result.stats_summary)
                if dataclasses.is_dataclass(result.stats_summary)
                else result.stats_summary
            ),
            "jmx_test_case_data_path": result.jmx_test_case_data_path,
            "jtl_total_requests": result.jtl_total_requests,
            "jtl_total_errors": result.jtl_total_errors,
            "jtl_success_rate_pct": result.jtl_success_rate_pct,
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _load_single_execution_result(
        self, test_run_id: int, server_id: int, lp_id: int, cycle: int,
    ) -> Optional[ExecutionResult]:
        """Load one execution result from the manifest."""
        results_base = Path(self._config.results_dir) / str(test_run_id) / f"server_{server_id}"
        manifest_path = results_base / "execution_manifest.json"

        if not manifest_path.exists():
            return None

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        key = f"lp{lp_id}_cycle{cycle}"
        data = manifest.get(key)
        if not data:
            return None

        return ExecutionResult(
            stats_path=data["stats_path"],
            jtl_path=data["jtl_path"],
            stats_summary=data["stats_summary"],
            jmx_test_case_data_path=data["jmx_test_case_data_path"],
            jtl_total_requests=data.get("jtl_total_requests", 0),
            jtl_total_errors=data.get("jtl_total_errors", 0),
            jtl_success_rate_pct=data.get("jtl_success_rate_pct", 0.0),
        )
