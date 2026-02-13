"""Calibration engine.

Binary search for thread_count that produces target CPU utilization.
Per ORCHESTRATOR_INTERFACES.md Section 6.2 and ORCHESTRATOR_DATABASE_SCHEMA.md.

For each (target x load_profile):
  1. Restore calibration snapshot
  2. Deploy emulator + packages
  3. Binary search loop: start JMeter, observe CPU, adjust thread_count
  4. Sustained stability check: run for duration * stability_ratio
  5. Verify CPU stays in target range for confirmation_count times
  6. Commit thread_count -> CalibrationResultORM
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
        """
        target_min = ctx.load_profile.target_cpu_range_min
        target_max = ctx.load_profile.target_cpu_range_max
        ramp_up_sec = ctx.load_profile.ramp_up_sec
        duration_sec = ctx.load_profile.duration_sec

        logger.info(
            "Calibrating server %s for profile '%s' (target CPU: %.0f-%.0f%%)",
            ctx.server.hostname, ctx.load_profile.name, target_min, target_max,
        )

        # Binary search bounds
        low = 1
        high = 200
        best_thread_count = None
        iteration = 0

        while iteration < self._config.max_calibration_iterations and low <= high:
            iteration += 1
            candidate = (low + high) // 2
            logger.info("Calibration iteration %d: trying thread_count=%d", iteration, candidate)

            avg_cpu = self._run_observation(ctx, candidate, ramp_up_sec)

            if avg_cpu is None:
                logger.warning("Failed to get CPU reading, retrying with same count")
                continue

            logger.info("Observed avg CPU: %.1f%% (target: %.0f-%.0f%%)", avg_cpu, target_min, target_max)

            if avg_cpu < target_min:
                low = candidate + 1
            elif avg_cpu > target_max:
                high = candidate - 1
            else:
                best_thread_count = candidate
                break

        if best_thread_count is None:
            # If binary search didn't converge exactly, use closest
            best_thread_count = (low + high) // 2
            logger.warning("Binary search didn't converge; using thread_count=%d", best_thread_count)

        # Sustained stability check
        stability_duration = int(duration_sec * self._config.calibration_stability_ratio)
        for check_num in range(1, self._config.calibration_confirmation_count + 1):
            logger.info(
                "Stability check %d/%d: thread_count=%d for %ds",
                check_num, self._config.calibration_confirmation_count,
                best_thread_count, stability_duration,
            )
            stable = self._run_stability_check(
                ctx, best_thread_count, ramp_up_sec, stability_duration,
                target_min, target_max,
            )
            if not stable:
                logger.warning("Stability check %d failed, adjusting", check_num)
                best_thread_count = max(1, best_thread_count - 1)

        # Save result
        existing = session.query(CalibrationResultORM).filter(
            CalibrationResultORM.test_run_id == test_run.id,
            CalibrationResultORM.server_id == ctx.server.id,
            CalibrationResultORM.load_profile_id == ctx.load_profile.id,
        ).first()

        if existing:
            existing.thread_count = best_thread_count
        else:
            session.add(CalibrationResultORM(
                test_run_id=test_run.id,
                server_id=ctx.server.id,
                os_type=ctx.server.os_family,
                load_profile_id=ctx.load_profile.id,
                thread_count=best_thread_count,
            ))
        session.commit()

        logger.info(
            "Calibration complete for %s / %s: thread_count=%d",
            ctx.server.hostname, ctx.load_profile.name, best_thread_count,
        )
        return best_thread_count

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

            # Wait for ramp-up
            time.sleep(ramp_up_sec)

            # Collect observations
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

            avg_cpu = sum(s.get("cpu_percent", 0) for s in samples) / len(samples)
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
    ) -> bool:
        """Run sustained stability check. Returns True if CPU stays in range."""
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
                return False

            # Check all samples are in range
            for sample in samples:
                cpu = sample.get("cpu_percent", 0)
                if cpu < target_min or cpu > target_max:
                    logger.debug("Stability failed: CPU=%.1f outside %.0f-%.0f", cpu, target_min, target_max)
                    return False

            return True

        except Exception as e:
            logger.error("Stability check failed: %s", e)
            return False
