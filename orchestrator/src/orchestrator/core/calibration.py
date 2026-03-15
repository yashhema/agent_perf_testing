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
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.settings import CalibrationConfig
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.jmeter_controller import JMeterController
from typing import Union

from orchestrator.models.orm import (
    BaselineTestRunORM,
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
    test_run_id: Optional[int] = None  # For unique temp paths on shared loadgen
    results_dir: Optional[str] = None  # Base dir for saving logs
    extra_properties: Optional[dict] = None  # Extra -J flags for JMeter (e.g. pool_gb for server_steady)


class CalibrationEngine:
    """Calibrates JMeter thread counts via binary search."""

    def __init__(self, config: CalibrationConfig):
        self._config = config

    def calibrate(
        self,
        session: Session,
        test_run: Union[TestRunORM, BaselineTestRunORM],
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
        test_run: Union[TestRunORM, BaselineTestRunORM],
        ctx: CalibrationContext,
        target_min: float,
        target_max: float,
    ) -> CalibrationResultORM:
        """Get existing or create new CalibrationResultORM for live progress tracking.

        Supports both live-compare (TestRunORM) and baseline-compare (BaselineTestRunORM).
        """
        is_baseline = isinstance(test_run, BaselineTestRunORM)

        # Build filter based on test run type
        if is_baseline:
            query_filter = (
                CalibrationResultORM.baseline_test_run_id == test_run.id,
            )
        else:
            query_filter = (
                CalibrationResultORM.test_run_id == test_run.id,
            )

        existing = session.query(CalibrationResultORM).filter(
            *query_filter,
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
        if is_baseline:
            record.baseline_test_run_id = test_run.id
        else:
            record.test_run_id = test_run.id
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
        """Intelligent ascending search for thread_count that produces target CPU.

        Uses data-driven prediction instead of blind exponential doubling:
        1. Start at 1 thread (with JVM settle), observe CPU
        2. Use observed CPU-per-thread ratio to predict the thread count
           needed for the target midpoint
        3. Observe at predicted count, refine using linear interpolation
           between the two closest data points
        4. Fall back to binary search when bracketed (last_below, first_over)

        Updates cal_record at each iteration.
        Returns the best thread_count found.
        """
        max_threads = self._config.max_thread_count
        target_mid = (target_min + target_max) / 2
        best_thread_count = None
        iteration = 0
        consecutive_failures = 0
        max_consecutive_failures = 3

        # Observation history: list of (thread_count, avg_cpu) tuples
        observations = []

        # Bounds for binary search fallback
        last_below = None       # highest thread count still below target_min
        last_below_cpu = None
        first_over = None       # lowest thread count above target_max
        first_over_cpu = None

        candidate = 1

        while iteration < self._config.max_calibration_iterations and candidate <= max_threads:
            iteration += 1

            # First iteration gets extra settle time for JVM warmup
            settle = self._config.first_observation_settle_sec if iteration == 1 else 0

            # Update progress
            cal_record.phase = "ramp_up"
            cal_record.current_iteration = iteration
            cal_record.current_thread_count = candidate
            settle_msg = f" (+{settle}s settle)" if settle else ""
            cal_record.message = (
                f"Iter {iteration}: trying {candidate} threads{settle_msg}"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info("Calibration iteration %d: trying thread_count=%d%s",
                        iteration, candidate,
                        f" (settle {settle}s)" if settle else "")

            avg_cpu = self._run_observation(ctx, candidate, ramp_up_sec, extra_settle_sec=settle)
            self._cleanup_iteration(ctx, iteration=iteration, phase="ramp_up")

            if avg_cpu is None:
                consecutive_failures += 1
                cal_record.message = (
                    f"Iter {iteration}: failed to read CPU at "
                    f"{candidate} threads ({consecutive_failures}/{max_consecutive_failures})"
                )
                cal_record.updated_at = datetime.utcnow()
                session.commit()
                logger.warning(
                    "Failed to get CPU reading (%d/%d consecutive failures)",
                    consecutive_failures, max_consecutive_failures,
                )
                if consecutive_failures >= max_consecutive_failures:
                    raise CalibrationError(
                        f"Emulator unreachable: {max_consecutive_failures} consecutive "
                        f"observation failures on {ctx.server.hostname}:{ctx.emulator_port}. "
                        f"The emulator may have crashed or the target VM is down."
                    )
                continue

            consecutive_failures = 0
            observations.append((candidate, avg_cpu))

            cal_record.last_observed_cpu = round(avg_cpu, 1)
            cal_record.message = (
                f"Iter {iteration}: {candidate} threads → "
                f"{avg_cpu:.1f}% CPU (target {target_min:.0f}-{target_max:.0f}%)"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info("Observed avg CPU: %.1f%% (target: %.0f-%.0f%%)",
                        avg_cpu, target_min, target_max)

            # Classify the observation
            if avg_cpu < target_min:
                if last_below is None or candidate > last_below:
                    last_below = candidate
                    last_below_cpu = avg_cpu
            elif avg_cpu > target_max:
                if first_over is None or candidate < first_over:
                    first_over = candidate
                    first_over_cpu = avg_cpu
            else:
                # In range — done
                best_thread_count = candidate
                break

            # ── Decide next candidate ──
            if best_thread_count is not None:
                break

            # If we have both bounds, switch to binary search refinement
            if last_below is not None and first_over is not None:
                candidate = self._interpolate_candidate(
                    last_below, last_below_cpu, first_over, first_over_cpu,
                    target_mid, max_threads,
                )
                # Safety: binary search fallback if interpolation keeps repeating
                if candidate == last_below or candidate == first_over:
                    candidate = (last_below + first_over) // 2
                if candidate <= last_below or candidate >= first_over:
                    # Gap is too small — no integer thread count fits
                    candidate = max(1, (last_below + first_over) // 2)
                    if candidate == last_below or candidate == first_over:
                        # Truly adjacent, nothing to try
                        break
                logger.info(
                    "Bracketed [%d(%.1f%%), %d(%.1f%%)] → interpolated candidate=%d",
                    last_below, last_below_cpu, first_over, first_over_cpu, candidate,
                )
                continue

            # Only have observations on one side — predict using linear model
            next_candidate = self._predict_next_candidate(
                observations, target_mid, max_threads,
            )

            if next_candidate is not None:
                candidate = next_candidate
            else:
                # Fallback: double the last tried count
                candidate = min(candidate * 2, max_threads)

        # ── Fallback: pick closest candidate if no exact match ──
        if best_thread_count is None:
            if first_over is not None and last_below is not None:
                best_thread_count = max(1, (last_below + first_over) // 2)
                cal_record.message = (
                    f"Search gap: no integer thread count lands in "
                    f"{target_min:.0f}-{target_max:.0f}%. "
                    f"Using {best_thread_count} threads (midpoint of "
                    f"{last_below}@{last_below_cpu:.0f}% and {first_over}@{first_over_cpu:.0f}%)."
                )
                logger.warning(
                    "Search gap (last_below=%d@%.1f%%, first_over=%d@%.1f%%) — using %d",
                    last_below, last_below_cpu, first_over, first_over_cpu, best_thread_count,
                )
            elif first_over is not None:
                best_thread_count = 1
                cal_record.message = (
                    f"Even 1 thread exceeds target ({target_max:.0f}%), using 1 thread"
                )
                logger.warning("Even 1 thread exceeds target_max; using 1")
            elif last_below is not None:
                best_thread_count = max_threads
                cal_record.message = (
                    f"Max threads ({max_threads}) still below target "
                    f"({target_min:.0f}%), using {max_threads}"
                )
                logger.warning("Max threads %d still below target_min; using max",
                               max_threads)
            else:
                best_thread_count = 1
                cal_record.message = "No observations succeeded; defaulting to 1 thread"
                logger.warning("No observations succeeded; defaulting to 1 thread")

            cal_record.current_thread_count = best_thread_count
            cal_record.updated_at = datetime.utcnow()
            session.commit()

        return best_thread_count

    @staticmethod
    def _interpolate_candidate(
        low_tc: int, low_cpu: float,
        high_tc: int, high_cpu: float,
        target_cpu: float,
        max_threads: int,
    ) -> int:
        """Linear interpolation between two bracketing observations.

        Given (low_tc → low_cpu) and (high_tc → high_cpu), predict which
        thread count would produce target_cpu.
        """
        if high_tc <= low_tc or high_cpu <= low_cpu:
            return (low_tc + high_tc) // 2

        # Linear: target_cpu = low_cpu + slope * (tc - low_tc)
        # tc = low_tc + (target_cpu - low_cpu) / slope
        slope = (high_cpu - low_cpu) / (high_tc - low_tc)
        predicted = low_tc + (target_cpu - low_cpu) / slope
        clamped = max(low_tc + 1, min(int(round(predicted)), high_tc - 1))
        return min(clamped, max_threads)

    @staticmethod
    def _predict_next_candidate(
        observations: list,
        target_cpu: float,
        max_threads: int,
    ) -> Optional[int]:
        """Predict next thread count using observed data points.

        With 1 observation: assumes CPU scales linearly from 0 threads = 0% CPU.
        With 2+ observations: uses the last two data points for slope estimation.

        Returns predicted thread count, or None if prediction is not useful.
        """
        if not observations:
            return None

        if len(observations) == 1:
            tc, cpu = observations[0]
            if cpu <= 0:
                return None
            # Assume roughly linear: cpu_per_thread ≈ cpu / tc
            cpu_per_thread = cpu / tc
            predicted = target_cpu / cpu_per_thread
            # Ensure we move forward (at least tc + 1)
            predicted = max(tc + 1, int(round(predicted)))
            predicted = min(predicted, max_threads)
            logger.info(
                "Prediction (1 point): %d threads→%.1f%% CPU, "
                "cpu/thread=%.1f%%, predict %d threads for %.1f%% target",
                tc, cpu, cpu_per_thread, predicted, target_cpu,
            )
            return predicted

        # Use last two observations for slope
        tc1, cpu1 = observations[-2]
        tc2, cpu2 = observations[-1]
        if tc2 == tc1:
            return None

        slope = (cpu2 - cpu1) / (tc2 - tc1)
        if slope <= 0:
            # CPU decreased with more threads (unlikely but handle it)
            # Fall back to doubling
            return min(tc2 * 2, max_threads)

        # Extrapolate: target_cpu = cpu2 + slope * (predicted - tc2)
        predicted = tc2 + (target_cpu - cpu2) / slope
        # Ensure we move in the right direction
        if cpu2 < target_cpu:
            predicted = max(tc2 + 1, int(round(predicted)))
        else:
            predicted = min(tc2 - 1, int(round(predicted)))
        predicted = max(1, min(predicted, max_threads))

        logger.info(
            "Prediction (2 points): [%d→%.1f%%, %d→%.1f%%], "
            "slope=%.2f%%/thread, predict %d threads for %.1f%% target",
            tc1, cpu1, tc2, cpu2, slope, predicted, target_cpu,
        )
        return predicted

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
        stability_duration = min(
            int(duration_sec * self._config.calibration_stability_ratio),
            900,  # cap at 15 minutes
        )
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
                self._cleanup_iteration(ctx, iteration=check_num, phase=f"stability_attempt{attempt+1}")

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
        extra_settle_sec: int = 0,
    ) -> Optional[float]:
        """Run a single observation cycle: start JMeter, wait, read CPU, stop.

        Args:
            extra_settle_sec: additional wait before reading stats (e.g. JVM warmup
                on the first observation).

        Returns avg CPU %, or None if the observation failed (emulator may be down).
        """
        test_id = None
        pid = None
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

            # Start JMeter (use test_run_id/server/profile IDs to avoid path collision on shared loadgen)
            run_tag = f"r{ctx.test_run_id}_s{ctx.server.id}_lp{ctx.load_profile.id}"
            cal_prefix = f"/tmp/calibration_{run_tag}"
            pid = ctx.jmeter_controller.start(
                jmx_path=ctx.jmx_path,
                jtl_path=f"{cal_prefix}.jtl",
                log_path=f"{cal_prefix}.log",
                thread_count=thread_count,
                ramp_up_sec=ramp_up_sec,
                duration_sec=3600,  # run indefinitely; orchestrator kills after reading stats
                target_host=ctx.server.ip_address,
                target_port=ctx.emulator_port,
                ops_sequence_path=ctx.ops_sequence_path,
                extra_properties=ctx.extra_properties,
            )

            # Wait for ramp-up + optional settle + observation
            time.sleep(ramp_up_sec)
            if extra_settle_sec > 0:
                logger.info("Settling %ds before observation (JVM warmup)", extra_settle_sec)
                time.sleep(extra_settle_sec)
            time.sleep(self._config.observation_duration_sec)

            # Get recent stats
            stats = ctx.emulator_client.get_recent_stats(
                count=self._config.observation_reading_count
            )
            samples = stats.get("samples", [])

            # Stop JMeter and emulator
            try:
                ctx.jmeter_controller.stop(pid, jtl_path=f"{cal_prefix}.jtl")
            except Exception:
                pass
            pid = None
            ctx.emulator_client.stop_test(test_id)
            test_id = None

            if not samples:
                logger.warning("Observation returned 0 samples — emulator may not be collecting")
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
            # Try to clean up JMeter if it was started
            if pid is not None:
                try:
                    ctx.jmeter_controller.stop(pid, jtl_path=f"{cal_prefix}.jtl")
                except Exception:
                    pass
            if test_id is not None:
                try:
                    ctx.emulator_client.stop_test(test_id)
                except Exception:
                    pass
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

            run_tag = f"r{ctx.test_run_id}_s{ctx.server.id}_lp{ctx.load_profile.id}"
            stab_prefix = f"/tmp/calibration-stability_{run_tag}"
            pid = ctx.jmeter_controller.start(
                jmx_path=ctx.jmx_path,
                jtl_path=f"{stab_prefix}.jtl",
                log_path=f"{stab_prefix}.log",
                thread_count=thread_count,
                ramp_up_sec=ramp_up_sec,
                duration_sec=3600,  # run indefinitely; orchestrator kills after reading stats
                target_host=ctx.server.ip_address,
                target_port=ctx.emulator_port,
                ops_sequence_path=ctx.ops_sequence_path,
                extra_properties=ctx.extra_properties,
            )

            time.sleep(ramp_up_sec)
            time.sleep(duration_sec)

            stats = ctx.emulator_client.get_recent_stats(count=min(duration_sec, 1000))
            samples = stats.get("samples", [])

            ctx.jmeter_controller.stop(pid, jtl_path=f"{stab_prefix}.jtl")
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

        except (ConnectionError, OSError, TimeoutError) as e:
            # Connectivity failures should not be silently swallowed
            logger.error("Stability check failed (connectivity): %s", e)
            raise CalibrationError(
                f"Emulator unreachable during stability check on "
                f"{ctx.server.hostname}:{ctx.emulator_port}: {e}"
            ) from e
        except Exception as e:
            logger.error("Stability check failed: %s", e)
            return False, 0.0, 0.0, 0.0

    def _cleanup_iteration(self, ctx: CalibrationContext, iteration: int = 0, phase: str = "binary_search") -> None:
        """Collect logs then clean up temp files created during calibration iterations."""
        run_tag = f"r{ctx.test_run_id}_s{ctx.server.id}_lp{ctx.load_profile.id}"
        cal_prefix = f"/tmp/calibration_{run_tag}"
        stab_prefix = f"/tmp/calibration-stability_{run_tag}"

        # Collect logs before cleanup
        if ctx.results_dir:
            logs_dir = os.path.join(
                ctx.results_dir, str(ctx.test_run_id),
                f"server_{ctx.server.id}", "logs",
                f"calibration_{phase}_iter{iteration}",
            )
            os.makedirs(logs_dir, exist_ok=True)

            # JMeter logs (jtl + log for both cal and stability prefixes)
            for prefix_name, prefix in [("cal", cal_prefix), ("stability", stab_prefix)]:
                for ext in [".jtl", ".log"]:
                    remote = f"{prefix}{ext}"
                    local = os.path.join(logs_dir, f"jmeter_{prefix_name}{ext}")
                    try:
                        ctx.jmeter_controller._executor.download(remote, local)
                        logger.info("Collected %s -> %s", remote, local)
                    except Exception:
                        pass  # File may not exist for this phase

            # Emulator logs
            try:
                emulator_log = os.path.join(logs_dir, "emulator_logs.tar.gz")
                ctx.emulator_client.download_logs(emulator_log)
            except Exception as e:
                logger.debug("Emulator log download failed (non-fatal): %s", e)

        # Clean up remote temp files
        try:
            ctx.jmeter_controller._executor.execute(
                f"rm -f {cal_prefix}.jtl {cal_prefix}.log "
                f"{stab_prefix}.jtl {stab_prefix}.log"
            )
        except Exception as e:
            logger.debug("Cleanup failed (non-fatal): %s", e)
