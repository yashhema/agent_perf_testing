"""Result collection service for Lab1/Lab2 (Server) environments.

Collects:
1. JMeter results (JTL file, aggregated metrics)
2. Emulator stats (iteration times, CPU achieved)
3. System stats (CPU, memory, disk, network time series)
4. Functional/policy test results (for each other_package_lst item)
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol
import statistics

from app.results.models import (
    DeviceResultData,
    DeviceStatsData,
    DeviceExecutionData,
    JMeterResult,
    JMeterResultData,
    FunctionalTestResult,
    SystemStats,
    EmulatorStats,
    ExecutionCommand,
    PhaseResults,
)
from app.results.compression import compress_dict


class RemoteExecutor(Protocol):
    """Protocol for remote command execution."""

    async def execute(
        self,
        command: str,
        timeout_sec: int = 300,
    ) -> tuple[int, str, str]:
        """Execute command, return (exit_code, stdout, stderr)."""
        ...

    async def read_file(
        self,
        file_path: str,
    ) -> Optional[str]:
        """Read file contents from remote target."""
        ...


class EmulatorClient(Protocol):
    """Protocol for emulator API calls."""

    async def get_stats(self) -> dict:
        """Get emulator stats (iteration times, CPU)."""
        ...

    async def get_time_series(self) -> list[dict]:
        """Get time series data if available."""
        ...


@dataclass
class CollectionConfig:
    """Configuration for result collection."""

    # JMeter settings
    jmeter_result_path: str = "/tmp/jmeter_results.jtl"
    jmeter_log_path: str = "/tmp/jmeter.log"
    include_raw_jtl: bool = False  # JTL can be very large

    # Emulator settings
    emulator_stats_path: Optional[str] = None

    # System stats settings
    collect_system_stats: bool = True
    system_stats_path: str = "/tmp/system_stats.json"

    # Timeouts
    collection_timeout_sec: int = 300


class ResultCollector:
    """
    Collects results from JMeter, emulator, and functional tests.

    For Lab1/Lab2 (Server) environments where we have direct access.
    """

    def __init__(
        self,
        executor: RemoteExecutor,
        emulator_client: Optional[EmulatorClient] = None,
        config: Optional[CollectionConfig] = None,
    ):
        self.executor = executor
        self.emulator_client = emulator_client
        self.config = config or CollectionConfig()

    async def collect_phase_results(
        self,
        phase: str,
        loadprofile: str,
        package_list: list[dict],
        jmeter_config: Optional[dict] = None,
        jmeter_package_id: Optional[int] = None,
    ) -> PhaseResults:
        """
        Collect all results for a phase.

        Args:
            phase: Phase name ("base", "initial", "upgrade")
            loadprofile: Load profile ("low", "medium", "high")
            package_list: Packages in this phase (for functional tests)
            jmeter_config: JMeter configuration used
            jmeter_package_id: JMeter package ID from lab.jmeter_package_grpid

        Returns:
            PhaseResults with all data collected and compressed
        """
        collected_at = datetime.utcnow().isoformat()

        # Collect JMeter results (stored separately from target device results)
        jmeter_result = await self.collect_jmeter_results(jmeter_config)
        jmeter_result_data = JMeterResultData(
            jmeter=jmeter_result,
            package_id=jmeter_package_id,
            phase=phase,
            loadprofile=loadprofile,
            collected_at=collected_at,
        )

        # Collect emulator stats (target device)
        emulator_stats = await self.collect_emulator_stats()

        # Collect system stats (target device)
        system_stats = await self.collect_system_stats()

        # Collect functional test results for other_package_lst items
        functional_results = {}
        for pkg in package_list:
            pkg_type = pkg.get("package_type", "")
            if pkg_type in ("functional", "policy"):
                pkg_id = pkg["package_id"]
                func_result = await self.collect_functional_result(pkg)
                functional_results[pkg_id] = func_result

        # Build result data (target device - functional/policy tests only)
        result_data = DeviceResultData(
            functional_results=functional_results,
            phase=phase,
            loadprofile=loadprofile,
            collected_at=collected_at,
        )

        # Build stats data (target device)
        stats_data = DeviceStatsData(
            system=system_stats,
            emulator=emulator_stats,
            phase=phase,
            loadprofile=loadprofile,
            collected_at=collected_at,
        )

        # Build execution data (overall success)
        overall_success = (
            (jmeter_result is None or jmeter_result.success) and
            all(r.success for r in functional_results.values())
        )

        execution_data = DeviceExecutionData(
            overall_success=overall_success,
            phase=phase,
            loadprofile=loadprofile,
            executed_at=collected_at,
        )

        # JMeter execution data
        jmeter_execution_data = DeviceExecutionData(
            overall_success=jmeter_result is not None and jmeter_result.success,
            phase=phase,
            loadprofile=loadprofile,
            executed_at=collected_at,
        )

        # Create phase results and compress
        phase_results = PhaseResults(
            phase=phase,
            loadprofile=loadprofile,
            result_data=result_data,
            stats_data=stats_data,
            execution_data=execution_data,
            jmeter_result_data=jmeter_result_data,
            jmeter_execution_data=jmeter_execution_data,
        )
        phase_results.compress()

        return phase_results

    async def collect_jmeter_results(
        self,
        jmeter_config: Optional[dict] = None,
    ) -> Optional[JMeterResult]:
        """
        Collect JMeter results from JTL file.

        Args:
            jmeter_config: JMeter configuration (thread_count, duration, etc.)

        Returns:
            JMeterResult or None if collection failed
        """
        try:
            # Read JTL file
            jtl_content = await self.executor.read_file(
                self.config.jmeter_result_path
            )

            if not jtl_content:
                return JMeterResult(
                    success=False,
                    error_message="JTL file not found or empty",
                )

            # Parse JTL and calculate metrics
            metrics = self._parse_jtl(jtl_content)

            result = JMeterResult(
                success=True,
                thread_count=jmeter_config.get("thread_count") if jmeter_config else None,
                warmup_sec=jmeter_config.get("warmup_sec") if jmeter_config else None,
                measured_sec=jmeter_config.get("measured_sec") if jmeter_config else None,
                total_requests=metrics.get("total_requests", 0),
                successful_requests=metrics.get("successful_requests", 0),
                failed_requests=metrics.get("failed_requests", 0),
                avg_response_time_ms=metrics.get("avg_response_time_ms"),
                min_response_time_ms=metrics.get("min_response_time_ms"),
                max_response_time_ms=metrics.get("max_response_time_ms"),
                p50_response_time_ms=metrics.get("p50_response_time_ms"),
                p90_response_time_ms=metrics.get("p90_response_time_ms"),
                p95_response_time_ms=metrics.get("p95_response_time_ms"),
                p99_response_time_ms=metrics.get("p99_response_time_ms"),
                stddev_response_time_ms=metrics.get("stddev_response_time_ms"),
                throughput_rps=metrics.get("throughput_rps"),
                error_counts=metrics.get("error_counts"),
                jtl_file_path=self.config.jmeter_result_path,
            )

            # Include raw JTL if configured (can be large!)
            if self.config.include_raw_jtl:
                result.raw_jtl = jtl_content

            return result

        except Exception as e:
            return JMeterResult(
                success=False,
                error_message=f"Failed to collect JMeter results: {e}",
            )

    async def collect_emulator_stats(self) -> Optional[EmulatorStats]:
        """
        Collect emulator stats from emulator API or file.

        Returns:
            EmulatorStats or None if not available
        """
        if not self.emulator_client:
            return None

        try:
            stats = await self.emulator_client.get_stats()

            return EmulatorStats(
                total_iterations=stats.get("total_iterations", 0),
                avg_iteration_time_ms=stats.get("avg_iteration_time_ms"),
                min_iteration_time_ms=stats.get("min_iteration_time_ms"),
                max_iteration_time_ms=stats.get("max_iteration_time_ms"),
                stddev_iteration_time_ms=stats.get("stddev_iteration_time_ms"),
                p50_iteration_time_ms=stats.get("p50_iteration_time_ms"),
                p90_iteration_time_ms=stats.get("p90_iteration_time_ms"),
                p99_iteration_time_ms=stats.get("p99_iteration_time_ms"),
                target_cpu_percent=stats.get("target_cpu_percent"),
                achieved_cpu_percent=stats.get("achieved_cpu_percent"),
            )

        except Exception:
            return None

    async def collect_system_stats(self) -> Optional[SystemStats]:
        """
        Collect system stats (CPU, memory, etc.) from stats file.

        Returns:
            SystemStats or None if not available
        """
        if not self.config.collect_system_stats:
            return None

        try:
            # Read stats file (JSON with time series)
            stats_content = await self.executor.read_file(
                self.config.system_stats_path
            )

            if not stats_content:
                return None

            import json
            stats_data = json.loads(stats_content)
            samples = stats_data.get("samples", [])

            if not samples:
                return None

            # Calculate aggregates
            cpu_values = [s.get("cpu_percent", 0) for s in samples if s.get("cpu_percent") is not None]
            mem_values = [s.get("memory_percent", 0) for s in samples if s.get("memory_percent") is not None]

            return SystemStats(
                samples=samples,
                avg_cpu_percent=statistics.mean(cpu_values) if cpu_values else None,
                max_cpu_percent=max(cpu_values) if cpu_values else None,
                min_cpu_percent=min(cpu_values) if cpu_values else None,
                avg_memory_percent=statistics.mean(mem_values) if mem_values else None,
                max_memory_percent=max(mem_values) if mem_values else None,
                sample_interval_sec=stats_data.get("interval_sec", 1),
                total_samples=len(samples),
            )

        except Exception:
            return None

    async def collect_functional_result(
        self,
        package: dict,
    ) -> FunctionalTestResult:
        """
        Collect functional/policy test result for a package.

        Args:
            package: Package dict with result_path, etc.

        Returns:
            FunctionalTestResult
        """
        pkg_id = package["package_id"]
        pkg_name = package.get("package_name", f"Package {pkg_id}")
        pkg_type = package.get("package_type", "functional")
        result_path = package.get("test_results_path")

        if not result_path:
            return FunctionalTestResult(
                package_id=pkg_id,
                package_name=pkg_name,
                package_type=pkg_type,
                success=False,
                error_message="No test results path configured",
            )

        try:
            # Read result file
            result_content = await self.executor.read_file(result_path)

            if not result_content:
                return FunctionalTestResult(
                    package_id=pkg_id,
                    package_name=pkg_name,
                    package_type=pkg_type,
                    success=False,
                    error_message=f"Result file not found: {result_path}",
                )

            # Parse result (assume JSON format)
            import json
            try:
                result_data = json.loads(result_content)
            except json.JSONDecodeError:
                # Plain text result
                result_data = {"raw_output": result_content}

            # Extract test counts
            tests_passed = result_data.get("passed", 0)
            tests_failed = result_data.get("failed", 0)
            tests_skipped = result_data.get("skipped", 0)
            tests_total = tests_passed + tests_failed + tests_skipped

            return FunctionalTestResult(
                package_id=pkg_id,
                package_name=pkg_name,
                package_type=pkg_type,
                success=tests_failed == 0,
                tests_total=tests_total,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
                tests_skipped=tests_skipped,
                test_results=result_data.get("tests"),
                result_file_path=result_path,
            )

        except Exception as e:
            return FunctionalTestResult(
                package_id=pkg_id,
                package_name=pkg_name,
                package_type=pkg_type,
                success=False,
                error_message=f"Failed to collect result: {e}",
            )

    def _parse_jtl(self, jtl_content: str) -> dict:
        """
        Parse JMeter JTL file and calculate metrics.

        JTL format (CSV):
        timeStamp,elapsed,label,responseCode,responseMessage,threadName,
        dataType,success,failureMessage,bytes,sentBytes,grpThreads,
        allThreads,URL,Latency,IdleTime,Connect

        Args:
            jtl_content: Raw JTL file content

        Returns:
            Dictionary with calculated metrics
        """
        lines = jtl_content.strip().split('\n')
        if len(lines) < 2:
            return {}

        # Skip header
        data_lines = lines[1:]

        response_times = []
        success_count = 0
        fail_count = 0
        error_counts: dict[str, int] = {}
        first_timestamp = None
        last_timestamp = None

        for line in data_lines:
            try:
                fields = line.split(',')
                if len(fields) < 8:
                    continue

                timestamp = int(fields[0])
                elapsed = int(fields[1])
                response_code = fields[3]
                success = fields[7].lower() == 'true'

                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

                response_times.append(elapsed)

                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    error_key = response_code or "unknown"
                    error_counts[error_key] = error_counts.get(error_key, 0) + 1

            except (ValueError, IndexError):
                continue

        if not response_times:
            return {}

        # Calculate metrics
        sorted_times = sorted(response_times)
        total = len(response_times)

        duration_ms = (last_timestamp - first_timestamp) if first_timestamp and last_timestamp else 0
        duration_sec = duration_ms / 1000.0 if duration_ms else 1

        return {
            "total_requests": total,
            "successful_requests": success_count,
            "failed_requests": fail_count,
            "avg_response_time_ms": statistics.mean(response_times),
            "min_response_time_ms": min(response_times),
            "max_response_time_ms": max(response_times),
            "p50_response_time_ms": sorted_times[int(total * 0.50)],
            "p90_response_time_ms": sorted_times[int(total * 0.90)],
            "p95_response_time_ms": sorted_times[int(total * 0.95)],
            "p99_response_time_ms": sorted_times[int(total * 0.99)] if total >= 100 else sorted_times[-1],
            "stddev_response_time_ms": statistics.stdev(response_times) if total > 1 else 0,
            "throughput_rps": total / duration_sec if duration_sec > 0 else 0,
            "error_counts": error_counts if error_counts else None,
        }

    async def collect_execution_logs(
        self,
        phase: str,
        error_occurred: bool = True,
    ) -> Optional[dict]:
        """
        Collect execution logs (optional, typically on error).

        Args:
            phase: Phase name
            error_occurred: Whether an error occurred

        Returns:
            Dictionary with logs or None
        """
        if not error_occurred:
            return None

        logs = {}

        try:
            # Collect JMeter log
            jmeter_log = await self.executor.read_file(
                self.config.jmeter_log_path
            )
            if jmeter_log:
                logs["jmeter_log"] = jmeter_log

            # Collect system logs if available
            # Could add more log collection here

        except Exception:
            pass

        return logs if logs else None
