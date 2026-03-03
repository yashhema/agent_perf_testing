"""Calibration engine.

Binary search for thread_count that produces target CPU utilization.
Per ORCHESTRATOR_INTERFACES.md Section 6.2 and ORCHESTRATOR_DATABASE_SCHEMA.md.

For each (target x load_profile):
  1. Health-check the emulator (fail fast if not running)
  2. Binary search loop: start JMeter, observe CPU, adjust thread_count
  3. Sustained stability check with re-verification on failure
  4. Cleanup temp files between iterations
  5. Commit thread_count -> CalibrationResultORM

Progress is tracked live in CalibrationResultORM so the UI can show
real-time status during calibration.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.settings import CalibrationConfig
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.jmeter_controller import JMeterController
from orchestrator.models.orm import (
    CalibrationResultORM,
    LoadProfileORM,
    ServerORM,
    TestRunORM,
)

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """Raised when calibration cannot achieve a stable thread count."""
    pass


@dataclass
class CalibrationContext:
    """Context for a single calibration target."""
    server: ServerORM
    load_profile: LoadProfileORM
    emulator_client: EmulatorClient
    jmeter_controller: JMeterController
    jmx_path: str
    ops_sequence_path: str
    emulator_port: int


class CalibrationEngine:
    """Calibrates JMeter thread counts via binary search."""

    def __init__(self, config: CalibrationConfig):
        self._config = config

    def calibrate(
        self,
        session: Session,
        test_run: TestRunORM,
        ctx: CalibrationContext,
    ) -> int:
        """Run calibration for a single server x load_profile.

        Returns: calibrated thread_count
        Raises CalibrationError if stable calibration cannot be achieved.
        """
        target_min = ctx.load_profile.target_cpu_range_min
        target_max = ctx.load_profile.target_cpu_range_max
        ramp_up_sec = ctx.load_profile.ramp_up_sec
        duration_sec = ctx.load_profile.duration_sec

        logger.info(
            "Calibrating server %s for profile '%s' (target CPU: %.0f-%.0f%%)",
            ctx.server.hostname, ctx.load_profile.name, target_min, target_max,
        )

        # Health-check: fail fast if emulator is not reachable
        self._verify_emulator_health(ctx)

        # Create or get the live progress record
        cal_record = self._get_or_create_record(
            session, test_run, ctx, target_min, target_max
        )

        try:
            # --- Binary search phase ---
            best_thread_count = self._run_binary_search(
                session, ctx, cal_record, ramp_up_sec, target_min, target_max
            )

            # --- Stability verification phase ---
            best_thread_count = self._run_stability_loop(
                session, ctx, cal_record, best_thread_count,
                ramp_up_sec, duration_sec, target_min, target_max,
            )

            # --- Success ---
            cal_record.thread_count = best_thread_count
            cal_record.status = "completed"
            cal_record.phase = None
            cal_record.message = (
                f"Calibration complete: {best_thread_count} threads "
                f"(target {target_min:.0f}-{target_max:.0f}%)"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info(
                "Calibration complete for %s / %s: thread_count=%d",
                ctx.server.hostname, ctx.load_profile.name, best_thread_count,
            )
            return best_thread_count

        except CalibrationError as e:
            # Record the failure in DB before re-raising
            cal_record.status = "failed"
            cal_record.phase = None
            cal_record.error_message = str(e)
            cal_record.message = f"FAILED: {str(e)[:200]}"
            cal_record.updated_at = datetime.utcnow()
            session.commit()
            raise

    def _get_or_create_record(
        self,
        session: Session,
        test_run: TestRunORM,
        ctx: CalibrationContext,
        target_min: float,
        target_max: float,
    ) -> CalibrationResultORM:
        """Get existing or create new CalibrationResultORM for live progress tracking."""
        existing = session.query(CalibrationResultORM).filter(
            CalibrationResultORM.test_run_id == test_run.id,
            CalibrationResultORM.server_id == ctx.server.id,
            CalibrationResultORM.load_profile_id == ctx.load_profile.id,
        ).first()

        if existing:
            existing.status = "in_progress"
            existing.phase = "binary_search"
            existing.current_iteration = 0
            existing.target_cpu_min = target_min
            existing.target_cpu_max = target_max
            existing.message = f"Starting calibration (target {target_min:.0f}-{target_max:.0f}%)"
            existing.error_message = None
            existing.updated_at = datetime.utcnow()
            session.commit()
            return existing

        record = CalibrationResultORM(
            test_run_id=test_run.id,
            server_id=ctx.server.id,
            os_type=ctx.server.os_family,
            load_profile_id=ctx.load_profile.id,
            thread_count=0,
            status="in_progress",
            phase="binary_search",
            current_iteration=0,
            target_cpu_min=target_min,
            target_cpu_max=target_max,
            message=f"Starting calibration (target {target_min:.0f}-{target_max:.0f}%)",
        )
        session.add(record)
        session.commit()
        return record

    def _run_binary_search(
        self,
        session: Session,
        ctx: CalibrationContext,
        cal_record: CalibrationResultORM,
        ramp_up_sec: int,
        target_min: float,
        target_max: float,
    ) -> int:
        """Binary search for thread_count that produces target CPU.

        Updates cal_record at each iteration.
        Returns the best thread_count found.
        """
        low = 1
        high = self._config.max_thread_count
        best_thread_count = None
        iteration = 0

        while iteration < self._config.max_calibration_iterations and low <= high:
            iteration += 1
            candidate = (low + high) // 2

            # Update progress
            cal_record.phase = "binary_search"
            cal_record.current_iteration = iteration
            cal_record.current_thread_count = candidate
            cal_record.message = (
                f"Binary search iter {iteration}: trying {candidate} threads "
                f"(range {low}-{high})"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info("Calibration iteration %d: trying thread_count=%d (range %d-%d)",
                        iteration, candidate, low, high)

            avg_cpu = self._run_observation(ctx, candidate, ramp_up_sec)
            self._cleanup_iteration(ctx)

            if avg_cpu is None:
                cal_record.message = (
                    f"Binary search iter {iteration}: failed to read CPU at "
                    f"{candidate} threads, retrying"
                )
                cal_record.updated_at = datetime.utcnow()
                session.commit()
                logger.warning("Failed to get CPU reading, retrying with same count")
                continue

            # Update observed CPU
            cal_record.last_observed_cpu = round(avg_cpu, 1)
            cal_record.message = (
                f"Binary search iter {iteration}: {candidate} threads → "
                f"{avg_cpu:.1f}% CPU (target {target_min:.0f}-{target_max:.0f}%)"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info("Observed avg CPU: %.1f%% (target: %.0f-%.0f%%)",
                        avg_cpu, target_min, target_max)

            if avg_cpu < target_min:
                low = candidate + 1
            elif avg_cpu > target_max:
                high = candidate - 1
            else:
                best_thread_count = candidate
                break

        if best_thread_count is None:
            if low > high:
                best_thread_count = max(1, (low + high) // 2)
                cal_record.message = (
                    f"Binary search gap: no integer thread count lands in "
                    f"{target_min:.0f}-{target_max:.0f}%. "
                    f"Trying {best_thread_count} threads in stability."
                )
                logger.warning(
                    "Binary search gap (low=%d > high=%d) — trying thread_count=%d",
                    low, high, best_thread_count,
                )
            else:
                best_thread_count = (low + high) // 2
                cal_record.message = (
                    f"Binary search didn't converge, using {best_thread_count} threads"
                )
                logger.warning("Binary search didn't converge; using thread_count=%d",
                               best_thread_count)

            cal_record.current_thread_count = best_thread_count
            cal_record.updated_at = datetime.utcnow()
            session.commit()

        return best_thread_count

    def _run_stability_loop(
        self,
        session: Session,
        ctx: CalibrationContext,
        cal_record: CalibrationResultORM,
        thread_count: int,
        ramp_up_sec: int,
        duration_sec: int,
        target_min: float,
        target_max: float,
    ) -> int:
        """Run stability checks, restarting from round 1 on any failure.

        Updates cal_record at each step.
        Returns the final verified thread_count.
        Raises CalibrationError if stability cannot be achieved.
        """
        stability_duration = int(duration_sec * self._config.calibration_stability_ratio)
        max_decrements = 5
        confirmation_count = self._config.calibration_confirmation_count

        cal_record.phase = "stability_check"
        cal_record.stability_checks_total = confirmation_count
        cal_record.updated_at = datetime.utcnow()
        session.commit()

        for attempt in range(max_decrements):
            all_passed = True
            for check_num in range(1, confirmation_count + 1):
                # Update progress before each check
                cal_record.current_thread_count = thread_count
                cal_record.stability_check_num = check_num
                cal_record.stability_attempt = attempt + 1
                cal_record.stability_pct_in_range = None
                cal_record.message = (
                    f"Stability check {check_num}/{confirmation_count} "
                    f"(attempt {attempt + 1}/{max_decrements}): "
                    f"{thread_count} threads for {stability_duration}s"
                )
                cal_record.updated_at = datetime.utcnow()
                session.commit()

                logger.info(
                    "Stability check %d/%d: thread_count=%d for %ds",
                    check_num, confirmation_count, thread_count, stability_duration,
                )

                stable, pct_in_range, avg_cpu, pct_below = self._run_stability_check(
                    ctx, thread_count, ramp_up_sec, stability_duration,
                    target_min, target_max,
                )
                self._cleanup_iteration(ctx)

                # Update result of this check
                cal_record.stability_pct_in_range = pct_in_range
                cal_record.last_observed_cpu = avg_cpu
                cal_record.updated_at = datetime.utcnow()

                if not stable:
                    # Decide direction: if too many below min, need MORE threads;
                    # if too many above max (or low in-range%), need FEWER threads.
                    if thread_count == 1 and pct_below > 10.0:
                        # At minimum threads and CPU is too low — try incrementing
                        new_tc = thread_count + 1
                        direction = "Incrementing"
                    else:
                        new_tc = max(1, thread_count - 1)
                        direction = "Decrementing"

                    cal_record.message = (
                        f"Stability check {check_num}/{confirmation_count} FAILED: "
                        f"{pct_in_range:.1f}% in range, "
                        f"avg CPU={avg_cpu:.1f}%. "
                        f"{direction} to {new_tc} threads."
                    )
                    session.commit()

                    logger.warning(
                        "Stability check %d failed at thread_count=%d "
                        "(below_min=%.1f%%), %s to %d threads",
                        check_num, thread_count, pct_below, direction.lower(), new_tc,
                    )
                    thread_count = new_tc
                    all_passed = False
                    break
                else:
                    cal_record.message = (
                        f"Stability check {check_num}/{confirmation_count} PASSED: "
                        f"{pct_in_range:.1f}% in range, avg CPU={avg_cpu:.1f}%"
                    )
                    session.commit()

            if all_passed:
                logger.info("All %d stability checks passed at thread_count=%d",
                            confirmation_count, thread_count)
                return thread_count

        error_msg = (
            f"Stability loop exhausted after {max_decrements} attempts for "
            f"{ctx.server.hostname} / {ctx.load_profile.name}. "
            f"Cannot achieve stable CPU in {target_min:.0f}-{target_max:.0f}% range. "
            f"Last thread_count={thread_count}. "
            f"The target CPU range is too narrow for the thread granularity on this VM."
        )
        raise CalibrationError(error_msg)

    def _verify_emulator_health(self, ctx: CalibrationContext) -> None:
        """Health-check the emulator. Raises if unreachable."""
        try:
            resp = ctx.emulator_client.health_check()
            logger.info("Emulator health OK on %s:%d: %s",
                        ctx.server.ip_address, ctx.emulator_port, resp)
        except Exception as e:
            raise RuntimeError(
                f"Emulator not reachable on {ctx.server.ip_address}:{ctx.emulator_port}. "
                f"Ensure the emulator is started (run start.sh on target). Error: {e}"
            ) from e

    def _run_observation(
        self,
        ctx: CalibrationContext,
        thread_count: int,
        ramp_up_sec: int,
    ) -> Optional[float]:
        """Run a single observation cycle: start JMeter, wait, read CPU, stop."""
        try:
            # Start emulator stats collection
            test_resp = ctx.emulator_client.start_test(
                test_run_id="calibration",
                scenario_id="calibration",
                mode="calibration",
                collect_interval_sec=1.0,
                thread_count=thread_count,
            )
            test_id = test_resp.get("test_id", "")

            # Start JMeter
            pid = ctx.jmeter_controller.start(
                jmx_path=ctx.jmx_path,
                jtl_path="/tmp/calibration.jtl",
                log_path="/tmp/calibration.log",
                thread_count=thread_count,
                ramp_up_sec=ramp_up_sec,
                duration_sec=self._config.observation_duration_sec + ramp_up_sec,
                target_host=ctx.server.ip_address,
                target_port=ctx.emulator_port,
                ops_sequence_path=ctx.ops_sequence_path,
            )

            # Wait for ramp-up + observation
            time.sleep(ramp_up_sec)
            time.sleep(self._config.observation_duration_sec)

            # Get recent stats
            stats = ctx.emulator_client.get_recent_stats(
                count=self._config.observation_reading_count
            )
            samples = stats.get("samples", [])

            # Stop JMeter and emulator
            ctx.jmeter_controller.stop(pid)
            ctx.emulator_client.stop_test(test_id)

            if not samples:
                return None

            cpu_values = [s.get("cpu_percent", 0) for s in samples]
            avg_cpu = sum(cpu_values) / len(cpu_values)
            min_cpu = min(cpu_values)
            max_cpu = max(cpu_values)
            logger.info(
                "Observation: %d samples, CPU avg=%.1f%% min=%.1f%% max=%.1f%% spread=%.1f%%",
                len(cpu_values), avg_cpu, min_cpu, max_cpu, max_cpu - min_cpu,
            )
            # Log all CPU values for post-hoc analysis
            logger.info(
                "Observation CPU values (thread_count=%d): %s",
                thread_count,
                ", ".join(f"{v:.1f}" for v in cpu_values),
            )
            # Log memory if available
            mem_values = [s.get("memory_percent", 0) for s in samples]
            if any(v > 0 for v in mem_values):
                logger.info(
                    "Observation MEM values: avg=%.1f%% min=%.1f%% max=%.1f%%",
                    sum(mem_values) / len(mem_values), min(mem_values), max(mem_values),
                )
            # Log process stats if available
            last_sample = samples[-1]
            proc_stats = last_sample.get("process_stats", [])
            if proc_stats:
                for p in proc_stats:
                    logger.info(
                        "  proc '%s' (pid %s): cpu=%.1f%% mem=%.1f%% rss=%.1fMB",
                        p.get("name", "?"), p.get("pid", "?"),
                        p.get("cpu_percent", 0), p.get("memory_percent", 0),
                        p.get("memory_rss_mb", 0),
                    )
            return avg_cpu

        except Exception as e:
            logger.error("Observation failed: %s", e)
            return None

    def _run_stability_check(
        self,
        ctx: CalibrationContext,
        thread_count: int,
        ramp_up_sec: int,
        duration_sec: int,
        target_min: float,
        target_max: float,
    ) -> tuple:
        """Run sustained stability check.

        Returns (passed: bool, pct_in_range: float, avg_cpu: float).
        """
        try:
            test_resp = ctx.emulator_client.start_test(
                test_run_id="calibration-stability",
                scenario_id="calibration",
                mode="calibration",
                collect_interval_sec=1.0,
                thread_count=thread_count,
            )
            test_id = test_resp.get("test_id", "")

            pid = ctx.jmeter_controller.start(
                jmx_path=ctx.jmx_path,
                jtl_path="/tmp/calibration-stability.jtl",
                log_path="/tmp/calibration-stability.log",
                thread_count=thread_count,
                ramp_up_sec=ramp_up_sec,
                duration_sec=duration_sec + ramp_up_sec,
                target_host=ctx.server.ip_address,
                target_port=ctx.emulator_port,
                ops_sequence_path=ctx.ops_sequence_path,
            )

            time.sleep(ramp_up_sec)
            time.sleep(duration_sec)

            stats = ctx.emulator_client.get_recent_stats(count=min(duration_sec, 1000))
            samples = stats.get("samples", [])

            ctx.jmeter_controller.stop(pid)
            ctx.emulator_client.stop_test(test_id)

            if not samples:
                return False, 0.0, 0.0, 0.0

            cpu_values = [s.get("cpu_percent", 0) for s in samples]
            in_range = 0
            below_min = 0
            above_max = 0
            below_values = []
            above_values = []
            for cpu in cpu_values:
                if cpu < target_min:
                    below_min += 1
                    below_values.append(cpu)
                elif cpu > target_max:
                    above_max += 1
                    above_values.append(cpu)
                else:
                    in_range += 1

            total = len(samples)
            pct_in_range = (in_range / total) * 100
            pct_below_min = (below_min / total) * 100
            pct_above_max = (above_max / total) * 100
            avg_cpu = sum(cpu_values) / total
            sorted_cpu = sorted(cpu_values)
            p5 = sorted_cpu[int(total * 0.05)] if total >= 20 else sorted_cpu[0]
            p50 = sorted_cpu[total // 2]
            p95 = sorted_cpu[int(total * 0.95)] if total >= 20 else sorted_cpu[-1]

            logger.info(
                "Stability check: %d samples — in-range=%.1f%% (%d), "
                "below-min=%.1f%% (%d), above-max=%.1f%% (%d), avg CPU=%.1f%%",
                total, pct_in_range, in_range,
                pct_below_min, below_min,
                pct_above_max, above_max, avg_cpu,
            )
            logger.info(
                "Stability CPU distribution: min=%.1f%% p5=%.1f%% p50=%.1f%% "
                "p95=%.1f%% max=%.1f%% (target %.0f-%.0f%%)",
                sorted_cpu[0], p5, p50, p95, sorted_cpu[-1], target_min, target_max,
            )
            if below_values:
                logger.info(
                    "Stability below-min values (%d): avg=%.1f%% min=%.1f%% max=%.1f%%",
                    len(below_values),
                    sum(below_values) / len(below_values),
                    min(below_values), max(below_values),
                )
            if above_values:
                logger.info(
                    "Stability above-max values (%d): avg=%.1f%% min=%.1f%% max=%.1f%%",
                    len(above_values),
                    sum(above_values) / len(above_values),
                    min(above_values), max(above_values),
                )

            # Pass criteria (from config):
            #  - At least stability_min_in_range_pct of samples in target range
            #  - No more than stability_max_below_pct of samples BELOW the minimum
            #    (above-max spikes are tolerable — we're generating enough load)
            max_below_pct = self._config.stability_max_below_pct
            min_in_range_pct = self._config.stability_min_in_range_pct

            if pct_below_min > max_below_pct:
                logger.warning(
                    "Stability failed: %.1f%% of samples below target min %.0f%% "
                    "(max allowed %.0f%%)",
                    pct_below_min, target_min, max_below_pct,
                )
                return False, round(pct_in_range, 1), round(avg_cpu, 1), round(pct_below_min, 1)

            if pct_in_range < min_in_range_pct:
                logger.warning(
                    "Stability failed: only %.1f%% in range (need %.0f%%), "
                    "%.1f%% below min, %.1f%% above max",
                    pct_in_range, min_in_range_pct, pct_below_min, pct_above_max,
                )
                return False, round(pct_in_range, 1), round(avg_cpu, 1), round(pct_below_min, 1)

            logger.info(
                "Stability PASSED: %.1f%% in range, %.1f%% above max (OK), "
                "%.1f%% below min",
                pct_in_range, pct_above_max, pct_below_min,
            )
            return True, round(pct_in_range, 1), round(avg_cpu, 1), round(pct_below_min, 1)

        except Exception as e:
            logger.error("Stability check failed: %s", e)
            return False, 0.0, 0.0, 0.0

    def _cleanup_iteration(self, ctx: CalibrationContext) -> None:
        """Clean up temp files created during calibration iterations."""
        try:
            ctx.jmeter_controller._executor.execute(
                "rm -f /tmp/calibration.jtl /tmp/calibration.log "
                "/tmp/calibration-stability.jtl /tmp/calibration-stability.log"
            )
        except Exception as e:
            logger.debug("Cleanup failed (non-fatal): %s", e)
