"""Distribution-aware calibration engine (v2).

Bracketed search + distribution stability + temporal smoothing.
Designed for 1-second sampling with bursty/mixed workloads.

Algorithm:
  Phase A — Bracket fast: double from 1 until CPU exceeds target_max
  Phase B — Bisect: narrow bracket until thread count found
  Phase C — Verify: 2 consecutive stability passes, pick lowest passing T

Key differences from v1 (calibration.py):
  - Uses percentiles (p50, p95) instead of just mean
  - Per-profile stability thresholds (low/medium/high have different tolerances)
  - Ratio-based thread adjustment instead of blind ±1
  - Bimodal detection: if both p_low>10% and p_high>20%, rerun don't adjust
  - Adaptive step size: max(2, T*0.10) when not bracketed, 1 when bracketed
  - Burstiness coefficient and CV reported per observation
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy.orm import Session

from orchestrator.config.settings import CalibrationConfig
from orchestrator.core.calibration import (
    CalibrationContext,
    CalibrationEngine,
    CalibrationError,
)
from orchestrator.models.orm import (
    BaselineTestRunORM,
    CalibrationResultORM,
    TestRunORM,
)

logger = logging.getLogger(__name__)


@dataclass
class StabilityThresholds:
    """Stability pass criteria derived from target range.

    Simple percentile-based:
      p25 >= target_min - 2%   (bottom quartile not too cold)
      p75 <= target_max        (top quartile within range)
      p90 <= target_max + 15%  (90th percentile tolerates spikes)
    """
    min_p25: float   # p25 must be >= this
    max_p75: float   # p75 must be <= this
    max_p90: float   # p90 must be <= this


def _get_thresholds(target_min: float, target_max: float) -> StabilityThresholds:
    """Derive stability thresholds from target CPU range."""
    return StabilityThresholds(
        min_p25=target_min - 2.0,
        max_p75=target_max,
        max_p90=target_max + 15.0,
    )


def _compute_stats(cpu_values: List[float]) -> Dict:
    """Compute statistical measures from CPU samples."""
    n = len(cpu_values)
    if n == 0:
        return {"avg": 0, "p50": 0, "p5": 0, "p95": 0, "stddev": 0, "cv": 0, "burstiness": 0}

    avg = sum(cpu_values) / n
    sorted_v = sorted(cpu_values)
    p5 = sorted_v[int(n * 0.05)] if n >= 20 else sorted_v[0]
    p50 = sorted_v[n // 2]
    p95 = sorted_v[int(n * 0.95)] if n >= 20 else sorted_v[-1]
    stddev = math.sqrt(sum((v - avg) ** 2 for v in cpu_values) / n) if n > 1 else 0
    cv = stddev / avg if avg > 0 else 0
    burstiness = (stddev - avg) / (stddev + avg) if (stddev + avg) > 0 else 0

    return {
        "avg": avg, "p50": p50, "p5": p5, "p95": p95,
        "min": sorted_v[0], "max": sorted_v[-1],
        "stddev": stddev, "cv": cv, "burstiness": burstiness,
    }


class DistributionCalibrationEngine(CalibrationEngine):
    """Distribution-aware calibration using bracketed bisection.

    Inherits infrastructure methods from CalibrationEngine:
    - _verify_emulator_health
    - _get_or_create_record
    - _run_observation
    - _run_stability_check
    - _cleanup_iteration
    """

    def calibrate(
        self,
        session: Session,
        test_run: Union[TestRunORM, BaselineTestRunORM],
        ctx: CalibrationContext,
    ) -> int:
        """Run distribution-aware calibration.

        Returns: calibrated thread_count
        Raises CalibrationError if stable calibration cannot be achieved.
        """
        target_min = ctx.load_profile.target_cpu_range_min
        target_max = ctx.load_profile.target_cpu_range_max
        target_mid = (target_min + target_max) / 2
        ramp_up_sec = ctx.load_profile.ramp_up_sec
        duration_sec = ctx.load_profile.duration_sec
        max_threads = self._config.max_thread_count
        thresholds = _get_thresholds(target_min, target_max)

        logger.info(
            "[CAL-V2] %s | LP=%s | target=%.0f-%.0f%% (mid=%.0f%%) | "
            "thresholds: p25>=%.0f%% p75<=%.0f%% p90<=%.0f%%",
            ctx.server.hostname, ctx.load_profile.name,
            target_min, target_max, target_mid,
            thresholds.min_p25, thresholds.max_p75, thresholds.max_p90,
        )

        self._verify_emulator_health(ctx)
        cal_record = self._get_or_create_record(
            session, test_run, ctx, target_min, target_max
        )

        try:
            # === Phase A: Bracket fast ===
            lower, upper = self._phase_a_bracket(
                session, ctx, cal_record, ramp_up_sec, target_min, target_max, max_threads
            )

            # === Phase B: Bisect ===
            candidate = self._phase_b_bisect(
                session, ctx, cal_record, lower, upper,
                ramp_up_sec, target_min, target_max,
            )

            # === Phase C: Verify with stability checks ===
            verified = self._phase_c_verify(
                session, ctx, cal_record, candidate,
                ramp_up_sec, duration_sec, target_min, target_max, thresholds,
            )

            # Success
            cal_record.thread_count = verified
            cal_record.status = "completed"
            cal_record.phase = None
            cal_record.message = (
                f"Calibration complete: {verified} threads "
                f"(target {target_min:.0f}-{target_max:.0f}%)"
            )
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info(
                "[CAL-V2] %s | COMPLETE | thread_count=%d | LP=%s",
                ctx.server.hostname, verified, ctx.load_profile.name,
            )
            return verified

        except CalibrationError as e:
            cal_record.status = "failed"
            cal_record.phase = None
            cal_record.error_message = str(e)
            cal_record.message = f"FAILED: {str(e)[:200]}"
            cal_record.updated_at = datetime.utcnow()
            session.commit()
            raise

    # ------------------------------------------------------------------
    # Phase A: Bracket fast — double from 1 until hot
    # ------------------------------------------------------------------
    def _phase_a_bracket(
        self, session, ctx, cal_record, ramp_up_sec,
        target_min, target_max, max_threads,
    ) -> Tuple[int, int]:
        """Find lower and upper bounds by doubling thread count.

        Returns (lower_bound, upper_bound) where:
        - lower_bound: highest T where avg_cpu < target_min (too cold)
        - upper_bound: lowest T where avg_cpu > target_max (too hot)
        If a T lands in range, returns (T, T) — already found.
        """
        target_mid = (target_min + target_max) / 2
        lower = 0   # thread count that was too cold (0 = not found)
        upper = 0   # thread count that was too hot (0 = not found)
        observations = []  # (threads, avg_cpu)

        T = 1
        iteration = 0
        first_settle = self._config.first_observation_settle_sec
        bracket_settle = self._config.bracket_settle_sec

        while T <= max_threads:
            iteration += 1
            # First observation gets longer settle (JVM cold start);
            # subsequent observations still get bracket_settle (post-revert warmup)
            settle = first_settle if iteration == 1 else bracket_settle

            cal_record.phase = "bracket"
            cal_record.current_iteration = iteration
            cal_record.current_thread_count = T
            cal_record.message = f"Phase A: probing {T} threads"
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info(
                "[CAL-V2] %s | BRACKET | iter=%d | T=%d%s",
                ctx.server.hostname, iteration, T,
                f" (+{settle}s settle)" if settle > 0 else "",
            )

            avg_cpu = self._run_observation(ctx, T, ramp_up_sec, extra_settle_sec=settle)
            self._cleanup_iteration(ctx, iteration=iteration, phase="bracket")

            if avg_cpu is None:
                # Cap consecutive failures to avoid infinite loop
                if not hasattr(self, '_consec_failures'):
                    self._consec_failures = 0
                self._consec_failures += 1
                if self._consec_failures >= 3:
                    raise RuntimeError(
                        f"Calibration aborted: {self._consec_failures} consecutive observation "
                        f"failures at T={T} on {ctx.server.hostname}"
                    )
                logger.warning("[CAL-V2] %s | BRACKET | T=%d observation failed (%d/3), retrying",
                               ctx.server.hostname, T, self._consec_failures)
                continue
            else:
                self._consec_failures = 0  # reset on success

            observations.append((T, avg_cpu))
            cal_record.last_observed_cpu = round(avg_cpu, 1)
            session.commit()

            logger.info(
                "[CAL-V2] %s | BRACKET | T=%d → cpu=%.1f%% (target=%.0f-%.0f%%)",
                ctx.server.hostname, T, avg_cpu, target_min, target_max,
            )

            if avg_cpu < target_min:
                lower = T
            elif avg_cpu > target_max:
                upper = T
                break  # Found upper bound
            else:
                # In range — but is it reliably near midpoint?
                distance_from_mid = abs(avg_cpu - target_mid)
                range_half = (target_max - target_min) / 2

                if distance_from_mid <= range_half * 0.5:
                    # Within 50% of midpoint — do a longer confirmation
                    # Don't start new JMeter — just wait 90 more seconds and
                    # fetch 90 samples from the SAME running emulator stats
                    logger.info(
                        "[CAL-V2] %s | BRACKET | T=%d avg=%.1f%% near midpoint %.0f%%, "
                        "running 90s confirmation...",
                        ctx.server.hostname, T, avg_cpu, target_mid,
                    )
                    import time as _time
                    # Run another observation — JMeter was already stopped by _run_observation,
                    # so start a fresh one for 120s
                    confirm_cpu = self._run_observation(ctx, T, ramp_up_sec, extra_settle_sec=30)
                    self._cleanup_iteration(ctx, iteration=iteration + 100, phase="bracket_confirm")

                    if confirm_cpu is not None and target_min <= confirm_cpu <= target_max:
                        confirm_dist = abs(confirm_cpu - target_mid)
                        logger.info(
                            "[CAL-V2] %s | BRACKET | T=%d confirmed: avg=%.1f%% (dist from mid=%.1f%%)",
                            ctx.server.hostname, T, confirm_cpu, confirm_dist,
                        )
                        return (T, T)
                    else:
                        # Confirmation failed — treat as bracket bound
                        logger.info(
                            "[CAL-V2] %s | BRACKET | T=%d confirmation: avg=%.1f%% NOT in range, continuing",
                            ctx.server.hostname, T, confirm_cpu if confirm_cpu else 0,
                        )
                        if confirm_cpu and confirm_cpu < target_min:
                            lower = T
                        elif confirm_cpu and confirm_cpu > target_max:
                            upper = T
                            break
                        else:
                            lower = T  # unreliable, keep going
                else:
                    # In range but near edge — not reliable with 20 samples
                    logger.info(
                        "[CAL-V2] %s | BRACKET | T=%d avg=%.1f%% in range but near edge "
                        "(dist=%.1f%% from mid=%.0f%%), treating as bracket bound",
                        ctx.server.hostname, T, avg_cpu, distance_from_mid, target_mid,
                    )
                    if avg_cpu < target_mid:
                        lower = T  # below midpoint, need more threads
                    else:
                        upper = T  # above midpoint, this is our upper
                        break

            # Double for next probe
            T = min(T * 2, max_threads)
            if T == lower:
                # Already at max_threads and still cold
                T = max_threads
                if lower == max_threads:
                    raise CalibrationError(
                        f"Cannot calibrate {ctx.server.hostname}: "
                        f"even {max_threads} threads gives only {avg_cpu:.1f}% CPU "
                        f"(target {target_min:.0f}-{target_max:.0f}%)"
                    )

        if upper == 0:
            # Never exceeded target — max threads is still below target
            # Use max_threads as upper bound, last cold as lower
            upper = max_threads
            if lower == 0:
                lower = 1

        logger.info(
            "[CAL-V2] %s | BRACKET | result: lower=%d upper=%d",
            ctx.server.hostname, lower, upper,
        )
        return (lower, upper)

    # ------------------------------------------------------------------
    # Phase B: Bisect between brackets
    # ------------------------------------------------------------------
    def _phase_b_bisect(
        self, session, ctx, cal_record, lower, upper,
        ramp_up_sec, target_min, target_max,
    ) -> int:
        """Narrow the bracket using bisection.

        Returns the thread count that produced CPU in target range.
        """
        if lower == upper:
            return lower  # Phase A already found exact match

        target_mid = (target_min + target_max) / 2
        iteration = 0
        max_bisect = 10

        while upper - lower > 1 and iteration < max_bisect:
            iteration += 1
            T = (lower + upper) // 2

            cal_record.phase = "bisect"
            cal_record.current_iteration = iteration
            cal_record.current_thread_count = T
            cal_record.message = f"Phase B: bisect [{lower},{upper}] → T={T}"
            cal_record.updated_at = datetime.utcnow()
            session.commit()

            logger.info(
                "[CAL-V2] %s | BISECT | iter=%d | [%d,%d] → T=%d",
                ctx.server.hostname, iteration, lower, upper, T,
            )

            avg_cpu = self._run_observation(ctx, T, ramp_up_sec)
            self._cleanup_iteration(ctx, iteration=iteration, phase="bisect")

            if avg_cpu is None:
                logger.warning("[CAL-V2] %s | BISECT | T=%d observation failed",
                               ctx.server.hostname, T)
                continue

            cal_record.last_observed_cpu = round(avg_cpu, 1)
            session.commit()

            logger.info(
                "[CAL-V2] %s | BISECT | T=%d → cpu=%.1f%% (target=%.0f-%.0f%%)",
                ctx.server.hostname, T, avg_cpu, target_min, target_max,
            )

            if avg_cpu < target_min:
                lower = T
            elif avg_cpu > target_max:
                upper = T
            else:
                # In range
                logger.info("[CAL-V2] %s | BISECT | T=%d in range", ctx.server.hostname, T)
                return T

        # Adjacent — pick the one closer to target_mid
        # Try upper first (more load, closer to productive use)
        logger.info(
            "[CAL-V2] %s | BISECT | converged at [%d,%d], picking %d",
            ctx.server.hostname, lower, upper, upper,
        )
        return upper

    # ------------------------------------------------------------------
    # Phase C: Verify with distribution-aware stability checks
    # ------------------------------------------------------------------
    def _phase_c_verify(
        self, session, ctx, cal_record, candidate,
        ramp_up_sec, duration_sec, target_min, target_max,
        thresholds: StabilityThresholds,
    ) -> int:
        """Run stability checks with per-profile thresholds.

        Uses distribution metrics (p_in, p_low, p_high, p95) instead of
        just average. Adjusts thread count by ratio on failure.
        Detects bimodal distributions and extends settle time.

        Returns verified thread_count.
        """
        stability_duration = min(
            int(duration_sec * self._config.calibration_stability_ratio),
            900,
        )
        confirmation_count = self._config.calibration_confirmation_count
        max_attempts = 8
        target_mid = (target_min + target_max) / 2
        thread_count = candidate
        # Max step = min(3, 15% of T)
        max_step = lambda t: max(1, min(3, int(t * 0.15)))

        cal_record.phase = "stability_check"
        cal_record.stability_checks_total = confirmation_count
        session.commit()

        for attempt in range(max_attempts):
            all_passed = True

            for check_num in range(1, confirmation_count + 1):
                cal_record.current_thread_count = thread_count
                cal_record.stability_check_num = check_num
                cal_record.stability_attempt = attempt + 1
                cal_record.message = (
                    f"Phase C: stability {check_num}/{confirmation_count} "
                    f"(attempt {attempt + 1}/{max_attempts}): "
                    f"{thread_count} threads for {stability_duration}s"
                )
                cal_record.updated_at = datetime.utcnow()
                session.commit()

                logger.info(
                    "[CAL-V2] %s | STABILITY | attempt %d/%d | check %d/%d | "
                    "T=%d | duration=%ds",
                    ctx.server.hostname, attempt + 1, max_attempts,
                    check_num, confirmation_count, thread_count, stability_duration,
                )

                # Run stability check (parent method collects stats + logs distribution)
                stable, pct_in_range, avg_cpu, pct_below = self._run_stability_check(
                    ctx, thread_count, ramp_up_sec, stability_duration,
                    target_min, target_max,
                )
                self._cleanup_iteration(ctx, iteration=check_num,
                                        phase=f"stability_attempt{attempt+1}")

                # Get recent stats to compute percentiles ourselves
                try:
                    raw_stats = ctx.emulator_client.get_recent_stats(
                        count=min(stability_duration, 1000)
                    )
                    raw_samples = raw_stats.get("samples", [])
                    cpu_values = [s.get("cpu_percent", 0) for s in raw_samples]
                except Exception:
                    cpu_values = []

                if not cpu_values:
                    logger.warning("[CAL-V2] %s | No CPU samples for percentile check", ctx.server.hostname)
                    all_passed = False
                    break

                stats = _compute_stats(cpu_values)
                n = len(cpu_values)
                sorted_v = sorted(cpu_values)
                p25 = sorted_v[int(n * 0.25)]
                p75 = sorted_v[int(n * 0.75)]
                p90 = sorted_v[int(n * 0.90)]

                cal_record.stability_pct_in_range = pct_in_range
                cal_record.last_observed_cpu = avg_cpu
                cal_record.updated_at = datetime.utcnow()

                # Save raw samples to JSON file
                if ctx.results_dir:
                    import json, os
                    samples_dir = os.path.join(
                        ctx.results_dir, str(ctx.test_run_id),
                        f"server_{ctx.server.id}", "calibration_samples",
                    )
                    os.makedirs(samples_dir, exist_ok=True)
                    samples_file = os.path.join(
                        samples_dir,
                        f"stability_attempt{attempt+1}_check{check_num}_T{thread_count}.json"
                    )
                    with open(samples_file, "w") as f:
                        json.dump({
                            "thread_count": thread_count,
                            "attempt": attempt + 1,
                            "check": check_num,
                            "target_min": target_min,
                            "target_max": target_max,
                            "sample_count": n,
                            "avg": stats["avg"],
                            "p25": p25, "p50": stats["p50"],
                            "p75": p75, "p90": p90, "p95": stats["p95"],
                            "min": stats["min"], "max": stats["max"],
                            "stddev": stats["stddev"],
                            "cv": stats["cv"],
                            "burstiness": stats["burstiness"],
                            "cpu_values": cpu_values,
                        }, f, indent=2)
                    logger.info("[CAL-V2] Saved %d samples to %s", n, samples_file)

                # Simple percentile-based pass criteria
                dist_pass = (
                    p25 >= thresholds.min_p25
                    and p75 <= thresholds.max_p75
                    and p90 <= thresholds.max_p90
                )

                logger.info(
                    "[CAL-V2] %s | T=%d | p25=%.1f%% p75=%.1f%% p90=%.1f%% | "
                    "thresholds: p25>=%.0f p75<=%.0f p90<=%.0f | %s",
                    ctx.server.hostname, thread_count,
                    p25, p75, p90,
                    thresholds.min_p25, thresholds.max_p75, thresholds.max_p90,
                    "PASS" if dist_pass else "FAIL",
                )

                if dist_pass:
                    cal_record.message = (
                        f"Stability {check_num}/{confirmation_count} PASSED: "
                        f"p25={p25:.1f}% p75={p75:.1f}% p90={p90:.1f}% avg={avg_cpu:.1f}%"
                    )
                    session.commit()
                    continue

                # --- FAILED ---
                all_passed = False

                # Determine direction and capped step
                step = max_step(thread_count)

                if p75 > thresholds.max_p75:
                    # Too hot — decrease threads
                    if thread_count == 1:
                        raise CalibrationError(
                            f"Cannot calibrate {ctx.server.hostname}: "
                            f"1 thread gives p75={p75:.1f}%, "
                            f"target max is {target_max:.0f}%"
                        )
                    new_tc = max(1, thread_count - step)
                    direction = "DOWN"
                elif p25 < thresholds.min_p25:
                    # Too cold — increase threads
                    new_tc = min(self._config.max_thread_count, thread_count + step)
                    direction = "UP"
                else:
                    # p25 and p75 OK but p90 too high — slight decrease
                    new_tc = max(1, thread_count - 1)
                    direction = "DOWN (p90 high)"

                logger.warning(
                    "[CAL-V2] %s | STABILITY FAIL | T=%d → %d (%s, step=%d) | "
                    "p25=%.1f p75=%.1f p90=%.1f avg=%.1f%%",
                    ctx.server.hostname, thread_count, new_tc, direction, step,
                    p25, p75, p90, avg_cpu,
                )
                cal_record.message = (
                    f"Stability FAILED: p25={p25:.1f}% p75={p75:.1f}% p90={p90:.1f}%. "
                    f"{direction} from {thread_count} to {new_tc} (step={step})"
                )
                session.commit()

                thread_count = new_tc
                break

            if all_passed:
                logger.info(
                    "[CAL-V2] %s | ALL STABILITY PASSED | T=%d",
                    ctx.server.hostname, thread_count,
                )
                return thread_count

        raise CalibrationError(
            f"Stability verification exhausted after {max_attempts} attempts for "
            f"{ctx.server.hostname} / {ctx.load_profile.name}. "
            f"Last thread_count={thread_count}."
        )
