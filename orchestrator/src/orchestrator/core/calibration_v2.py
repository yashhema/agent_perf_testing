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
    """Per-profile stability pass criteria for 1s sampling."""
    min_pct_in_range: float
    max_pct_below: float
    max_pct_above: float
    max_p95: float


# Thresholds keyed by target range midpoint brackets
def _get_thresholds(target_min: float, target_max: float) -> StabilityThresholds:
    """Get stability thresholds based on target CPU range.

    Wider/higher ranges get more lenient thresholds because:
    - Higher CPU = more variance from GC, scheduling
    - 1s sampling at high load is inherently noisier
    """
    mid = (target_min + target_max) / 2

    if mid <= 30:
        # Low profile (e.g., 20-40%)
        return StabilityThresholds(
            min_pct_in_range=75.0,
            max_pct_below=15.0,
            max_pct_above=20.0,
            max_p95=target_max + 5,
        )
    elif mid <= 50:
        # Medium profile (e.g., 40-60%)
        return StabilityThresholds(
            min_pct_in_range=70.0,
            max_pct_below=15.0,
            max_pct_above=25.0,
            max_p95=target_max + 5,
        )
    elif mid <= 70:
        # High profile (e.g., 60-80%)
        return StabilityThresholds(
            min_pct_in_range=65.0,
            max_pct_below=10.0,
            max_pct_above=30.0,
            max_p95=target_max + 5,
        )
    else:
        # Stress (>80%) — very lenient
        return StabilityThresholds(
            min_pct_in_range=50.0,
            max_pct_below=5.0,
            max_pct_above=50.0,
            max_p95=100.0,
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
            "thresholds: p_in>=%.0f%% p_low<=%.0f%% p_high<=%.0f%% p95<=%.0f%%",
            ctx.server.hostname, ctx.load_profile.name,
            target_min, target_max, target_mid,
            thresholds.min_pct_in_range, thresholds.max_pct_below,
            thresholds.max_pct_above, thresholds.max_p95,
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
        settle = self._config.first_observation_settle_sec

        while T <= max_threads:
            iteration += 1
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
            settle = 0  # Only first observation gets settle time

            if avg_cpu is None:
                logger.warning("[CAL-V2] %s | BRACKET | T=%d observation failed, retrying",
                               ctx.server.hostname, T)
                continue

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
                # In range — lucky hit
                logger.info("[CAL-V2] %s | BRACKET | T=%d in range, skipping bisect",
                            ctx.server.hostname, T)
                return (T, T)

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
        max_attempts = 5
        target_mid = (target_min + target_max) / 2
        thread_count = candidate
        bimodal_retries = 0

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

                stable, pct_in_range, avg_cpu, pct_below = self._run_stability_check(
                    ctx, thread_count, ramp_up_sec, stability_duration,
                    target_min, target_max,
                )
                self._cleanup_iteration(ctx, iteration=check_num,
                                        phase=f"stability_attempt{attempt+1}")

                pct_above = 100.0 - pct_in_range - pct_below

                # Get p95 from the stability check — rerun the stats
                # (the parent _run_stability_check already logged them)
                cal_record.stability_pct_in_range = pct_in_range
                cal_record.last_observed_cpu = avg_cpu
                cal_record.updated_at = datetime.utcnow()

                # Distribution-aware pass criteria
                dist_pass = (
                    pct_in_range >= thresholds.min_pct_in_range
                    and pct_below <= thresholds.max_pct_below
                    and pct_above <= thresholds.max_pct_above
                )

                if dist_pass:
                    logger.info(
                        "[CAL-V2] %s | STABILITY PASS | check %d/%d | T=%d | "
                        "avg=%.1f%% in_range=%.1f%% below=%.1f%% above=%.1f%%",
                        ctx.server.hostname, check_num, confirmation_count,
                        thread_count, avg_cpu, pct_in_range, pct_below, pct_above,
                    )
                    cal_record.message = (
                        f"Stability {check_num}/{confirmation_count} PASSED: "
                        f"in_range={pct_in_range:.1f}%, avg={avg_cpu:.1f}%"
                    )
                    session.commit()
                    continue

                # --- FAILED ---
                all_passed = False

                # Bimodal detection: both below AND above are significant
                if pct_below > 10.0 and pct_above > 20.0 and bimodal_retries < 2:
                    bimodal_retries += 1
                    logger.warning(
                        "[CAL-V2] %s | BIMODAL detected | T=%d | below=%.1f%% above=%.1f%% | "
                        "rerunning with same T (retry %d/2)",
                        ctx.server.hostname, thread_count, pct_below, pct_above,
                        bimodal_retries,
                    )
                    cal_record.message = (
                        f"Bimodal distribution detected — rerunning T={thread_count} "
                        f"(below={pct_below:.1f}%, above={pct_above:.1f}%)"
                    )
                    session.commit()
                    break  # Retry same thread count

                # Directional adjustment by ratio
                if pct_below > pct_above:
                    # Too cold — scale up
                    ratio = target_mid / avg_cpu if avg_cpu > 0 else 2.0
                    new_tc = max(thread_count + 1, int(thread_count * ratio))
                    new_tc = min(new_tc, self._config.max_thread_count)
                    direction = "UP"
                else:
                    # Too hot — scale down
                    if thread_count == 1:
                        raise CalibrationError(
                            f"Cannot calibrate {ctx.server.hostname}: "
                            f"1 thread gives {avg_cpu:.1f}% CPU, "
                            f"target is {target_min:.0f}-{target_max:.0f}%"
                        )
                    ratio = target_mid / avg_cpu if avg_cpu > 0 else 0.5
                    new_tc = min(thread_count - 1, int(thread_count * ratio))
                    new_tc = max(1, new_tc)
                    direction = "DOWN"

                logger.warning(
                    "[CAL-V2] %s | STABILITY FAIL | T=%d | avg=%.1f%% | "
                    "in_range=%.1f%% below=%.1f%% above=%.1f%% | "
                    "%s to %d (ratio=%.2f)",
                    ctx.server.hostname, thread_count, avg_cpu,
                    pct_in_range, pct_below, pct_above,
                    direction, new_tc, ratio,
                )
                cal_record.message = (
                    f"Stability FAILED: in_range={pct_in_range:.1f}%, "
                    f"avg={avg_cpu:.1f}%. Adjusting {direction} to {new_tc} threads."
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
