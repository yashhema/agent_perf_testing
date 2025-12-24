"""JMeter process manager."""

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Set


class ProcessStatus(str, Enum):
    """JMeter process status."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class JMeterConfig:
    """Configuration for a JMeter test."""

    target_id: int
    test_run_id: str
    jmx_file: str
    thread_count: int
    ramp_up_sec: int
    loop_count: int
    duration_sec: Optional[int]
    emulator_host: str
    emulator_port: int
    jmeter_port: int
    additional_props: Dict[str, str] = field(default_factory=dict)


@dataclass
class JMeterProcess:
    """Represents a running JMeter process."""

    config: JMeterConfig
    status: ProcessStatus = ProcessStatus.PENDING
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    jtl_file: Optional[str] = None
    log_file: Optional[str] = None
    error_message: Optional[str] = None
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)

    @property
    def elapsed_sec(self) -> float:
        """Get elapsed time in seconds."""
        if not self.started_at:
            return 0.0
        end_time = self.stopped_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()


class JMeterManager:
    """Manages JMeter processes for load generation."""

    # Port range for JMeter instances
    PORT_RANGE_START = 4445
    PORT_RANGE_END = 4500

    def __init__(
        self,
        jmeter_home: Optional[str] = None,
        output_dir: Optional[str] = None,
    ):
        self._jmeter_home = jmeter_home or os.environ.get("JMETER_HOME", "/opt/jmeter")
        self._output_dir = output_dir or os.environ.get("LOADGEN_OUTPUT_DIR", "/tmp/loadgen")
        self._processes: Dict[int, JMeterProcess] = {}
        self._used_ports: Set[int] = set()

        # Ensure output directory exists
        Path(self._output_dir).mkdir(parents=True, exist_ok=True)

    @property
    def jmeter_bin(self) -> str:
        """Get path to JMeter executable."""
        if os.name == "nt":
            return os.path.join(self._jmeter_home, "bin", "jmeter.bat")
        return os.path.join(self._jmeter_home, "bin", "jmeter")

    def is_jmeter_available(self) -> bool:
        """Check if JMeter is available."""
        return os.path.exists(self.jmeter_bin)

    def get_jmeter_version(self) -> Optional[str]:
        """Get JMeter version."""
        if not self.is_jmeter_available():
            return None

        try:
            result = subprocess.run(
                [self.jmeter_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Parse version from output
            for line in result.stdout.split("\n"):
                if "Apache JMeter" in line or "jmeter" in line.lower():
                    return line.strip()
            return "Unknown"
        except Exception:
            return None

    def _allocate_port(self, requested_port: Optional[int] = None) -> int:
        """Allocate a port for JMeter."""
        if requested_port:
            if requested_port in self._used_ports:
                raise ValueError(f"Port {requested_port} is already in use")
            self._used_ports.add(requested_port)
            return requested_port

        # Find available port in range
        for port in range(self.PORT_RANGE_START, self.PORT_RANGE_END):
            if port not in self._used_ports:
                self._used_ports.add(port)
                return port

        raise RuntimeError("No available ports in range")

    def _release_port(self, port: int) -> None:
        """Release a port."""
        self._used_ports.discard(port)

    async def start_jmeter(self, config: JMeterConfig) -> JMeterProcess:
        """Start a JMeter process."""
        target_id = config.target_id

        # Check if already running for this target
        if target_id in self._processes:
            existing = self._processes[target_id]
            if existing.status in [ProcessStatus.RUNNING, ProcessStatus.STARTING]:
                raise RuntimeError(f"JMeter already running for target {target_id}")

        # Validate JMX file exists
        if not os.path.exists(config.jmx_file):
            raise FileNotFoundError(f"JMX file not found: {config.jmx_file}")

        # Create process entry
        process = JMeterProcess(config=config, status=ProcessStatus.STARTING)

        # Set up output files
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        process.jtl_file = os.path.join(
            self._output_dir, f"results_{target_id}_{timestamp}.jtl"
        )
        process.log_file = os.path.join(
            self._output_dir, f"jmeter_{target_id}_{timestamp}.log"
        )

        # Build JMeter command
        cmd = self._build_jmeter_command(config, process.jtl_file, process.log_file)

        try:
            # Start JMeter process
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )

            process._process = proc
            process.pid = proc.pid
            process.status = ProcessStatus.RUNNING
            process.started_at = datetime.utcnow()

            self._processes[target_id] = process

            # Start monitoring task
            asyncio.create_task(self._monitor_process(target_id))

            return process

        except Exception as e:
            process.status = ProcessStatus.FAILED
            process.error_message = str(e)
            self._release_port(config.jmeter_port)
            raise

    def _build_jmeter_command(
        self, config: JMeterConfig, jtl_file: str, log_file: str
    ) -> List[str]:
        """Build JMeter command line."""
        cmd = [
            self.jmeter_bin,
            "-n",  # Non-GUI mode
            "-t", config.jmx_file,
            "-l", jtl_file,
            "-j", log_file,
            f"-Jthreads={config.thread_count}",
            f"-Jrampup={config.ramp_up_sec}",
            f"-Jloopcount={config.loop_count}",
            f"-Jhost={config.emulator_host}",
            f"-Jport={config.emulator_port}",
        ]

        if config.duration_sec:
            cmd.append(f"-Jduration={config.duration_sec}")

        # Add additional properties
        for key, value in config.additional_props.items():
            cmd.append(f"-J{key}={value}")

        return cmd

    async def _monitor_process(self, target_id: int) -> None:
        """Monitor a JMeter process for completion."""
        if target_id not in self._processes:
            return

        process = self._processes[target_id]

        while process.status == ProcessStatus.RUNNING:
            if process._process is None:
                break

            # Check if process is still running
            return_code = process._process.poll()
            if return_code is not None:
                process.stopped_at = datetime.utcnow()
                if return_code == 0:
                    process.status = ProcessStatus.COMPLETED
                else:
                    process.status = ProcessStatus.FAILED
                    # Try to get error output
                    if process._process.stderr:
                        try:
                            stderr = process._process.stderr.read()
                            if stderr:
                                process.error_message = stderr.decode("utf-8", errors="ignore")[:1000]
                        except Exception:
                            pass

                self._release_port(process.config.jmeter_port)
                break

            await asyncio.sleep(1)

    async def stop_jmeter(self, target_id: int, force: bool = False) -> bool:
        """Stop a JMeter process."""
        if target_id not in self._processes:
            return False

        process = self._processes[target_id]

        if process.status not in [ProcessStatus.RUNNING, ProcessStatus.STARTING]:
            return False

        process.status = ProcessStatus.STOPPING

        if process._process is not None:
            try:
                if force:
                    process._process.kill()
                else:
                    # Try graceful shutdown first
                    if os.name == "nt":
                        process._process.terminate()
                    else:
                        os.killpg(os.getpgid(process._process.pid), signal.SIGTERM)

                # Wait for process to terminate
                try:
                    process._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process._process.kill()

            except Exception:
                pass

        process.status = ProcessStatus.STOPPED
        process.stopped_at = datetime.utcnow()
        self._release_port(process.config.jmeter_port)

        return True

    def get_status(self, target_id: int) -> Optional[JMeterProcess]:
        """Get status of a JMeter process."""
        return self._processes.get(target_id)

    def get_all_processes(self) -> List[JMeterProcess]:
        """Get all JMeter processes."""
        return list(self._processes.values())

    def get_running_processes(self) -> List[JMeterProcess]:
        """Get all running JMeter processes."""
        return [
            p for p in self._processes.values()
            if p.status in [ProcessStatus.RUNNING, ProcessStatus.STARTING]
        ]

    def cleanup_completed(self) -> int:
        """Remove completed/stopped processes from tracking."""
        to_remove = [
            target_id
            for target_id, process in self._processes.items()
            if process.status in [
                ProcessStatus.COMPLETED,
                ProcessStatus.STOPPED,
                ProcessStatus.FAILED,
            ]
        ]

        for target_id in to_remove:
            del self._processes[target_id]

        return len(to_remove)


# Global manager instance
_jmeter_manager: Optional[JMeterManager] = None


def get_jmeter_manager() -> JMeterManager:
    """Get the global JMeter manager instance."""
    global _jmeter_manager
    if _jmeter_manager is None:
        _jmeter_manager = JMeterManager()
    return _jmeter_manager
