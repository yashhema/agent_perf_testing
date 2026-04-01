"""JMeter controller for load generators.

Matches ORCHESTRATOR_INTERFACES.md Section 2.1 exactly.
Controls JMeter on load generator via SSH/WinRM (RemoteExecutor).
"""

import logging
import time
from typing import Dict, Optional

from orchestrator.infra.remote_executor import RemoteExecutor

logger = logging.getLogger(__name__)

# Location where jmeter_kill.py is deployed on the loadgen
_KILL_SCRIPT_REMOTE = "/data/jmeter/bin/jmeter_kill.py"


class JMeterController:
    """Controls JMeter on the load generator via SSH.

    One instance per load generator server.
    JMeter binary location comes from PackageGroupMemberORM.run_command.
    """

    def __init__(self, executor: RemoteExecutor, jmeter_bin: str, os_family: str = "linux"):
        """
        Args:
            executor: SSH/WinRM connection to load generator
            jmeter_bin: Full path to jmeter binary on load gen
                       (e.g., /opt/jmeter/bin/jmeter)
            os_family: "linux" or "windows" (affects process commands)
        """
        self._executor = executor
        self._jmeter_bin = jmeter_bin
        self._os_family = os_family

    def reconnect(self) -> None:
        """Reconnect the underlying executor transport."""
        self._executor.reconnect()

    def start(
        self,
        jmx_path: str,
        jtl_path: str,
        log_path: str,
        thread_count: int,
        ramp_up_sec: int,
        duration_sec: int,
        target_host: str,
        target_port: int,
        ops_sequence_path: Optional[str] = None,
        extra_properties: Optional[Dict[str, str]] = None,
    ) -> int:
        """Start JMeter process via SSH.

        Builds command:
          {jmeter_bin} -n -t {jmx_path} -l {jtl_path} -j {log_path}
            -Jthreads={thread_count} -Jrampup={ramp_up_sec}
            -Jduration={duration_sec} -Jhost={target_host}
            -Jport={target_port} [-Jops_sequence={ops_sequence_path}]
            -Jloopcount=-1 [{extra_properties as -Jkey=value}]

        Returns: PID of the JMeter process
        """
        cmd_parts = [
            self._jmeter_bin,
            "-n",
            f"-t {jmx_path}",
            f"-l {jtl_path}",
            f"-j {log_path}",
            f"-Jthreads={thread_count}",
            f"-Jrampup={ramp_up_sec}",
            f"-Jduration={duration_sec}",
            f"-Jhost={target_host}",
            f"-Jport={target_port}",
            "-Jloopcount=-1",
        ]
        if ops_sequence_path:
            cmd_parts.append(f"-Jops_sequence={ops_sequence_path}")
        if extra_properties:
            for key, value in extra_properties.items():
                cmd_parts.append(f"-J{key}={value}")

        command = " ".join(cmd_parts)

        if self._os_family == "linux":
            # Run in background, capture PID
            # < /dev/null detaches stdin so the SSH channel closes immediately
            # (without it, recv_exit_status blocks until JMeter exits or SSH times out)
            full_cmd = f"nohup {command} > /dev/null 2>&1 < /dev/null & echo $!"
        else:
            # Windows: use start /B and get PID via WMI
            full_cmd = f'start /B {command} & for /F "tokens=2" %i in (\'tasklist /FI "IMAGENAME eq java.exe" /NH\') do @echo %i'

        logger.info("Starting JMeter on %s: threads=%d, duration=%ds", target_host, thread_count, duration_sec)
        result = self._executor.execute_background(full_cmd)

        if not result.success:
            raise RuntimeError(f"JMeter start failed: {result.stderr}")

        pid = int(result.stdout.strip().split("\n")[-1].strip())
        logger.info("JMeter started with PID %d, verifying...", pid)

        # Wait for JVM to initialize, then verify the process is alive.
        # JMeter can fail immediately (bad JMX, missing Java, port conflict)
        # and the background launch still returns exit code 0 + a PID.
        time.sleep(5)
        if not self.is_running(pid):
            diag = ""
            try:
                log_result = self._executor.execute(f"tail -20 {log_path}", timeout_sec=10)
                if log_result.success:
                    diag = f"\nJMeter log tail:\n{log_result.stdout}"
            except Exception:
                pass
            raise RuntimeError(
                f"JMeter process {pid} is not running 5s after start. "
                f"It may have crashed during initialization.{diag}"
            )

        logger.info("JMeter PID %d verified running", pid)
        return pid

    def is_running(self, pid: int) -> bool:
        """Check if JMeter process is still running."""
        if self._os_family == "linux":
            result = self._executor.execute(f"kill -0 {pid} 2>/dev/null && echo RUNNING || echo STOPPED")
        else:
            result = self._executor.execute(f'tasklist /FI "PID eq {pid}" /NH')

        return "RUNNING" in result.stdout or (self._os_family == "windows" and "java" in result.stdout.lower())

    def stop(self, pid: int, jtl_path: Optional[str] = None) -> None:
        """Stop JMeter process tree.

        Uses jmeter_kill.py on the loadgen to find and kill both the
        shell wrapper and the orphaned Java child process.
        """
        if self._os_family == "linux":
            cmd = f"python3 {_KILL_SCRIPT_REMOTE} --stop-pid {pid}"
            if jtl_path:
                cmd += f" --jtl-path {jtl_path}"
            result = self._executor.execute(cmd)
            logger.info("stop(%d): %s", pid, result.stdout.strip())
        else:
            self._executor.execute(f"taskkill /PID {pid} /T /F")
        logger.info("JMeter stopped (PID %d)", pid)

    def kill_for_target(self, target_host: str) -> None:
        """Kill JMeter processes targeting a specific server.

        Uses jmeter_kill.py to match -Jhost={target_host} in command lines.
        Processes for other targets on a shared loadgen are not affected.
        """
        if self._os_family == "linux":
            result = self._executor.execute(
                f"python3 {_KILL_SCRIPT_REMOTE} --kill-for-target {target_host}"
            )
            logger.info("kill_for_target(%s): %s", target_host, result.stdout.strip())
        else:
            self._executor.execute(
                f'wmic process where "CommandLine like \'%ApacheJMeter%\' '
                f'and CommandLine like \'%Jhost={target_host}%\'" call terminate 2>NUL'
            )
        logger.info("Killed JMeter processes targeting %s", target_host)

    def collect_jtl(self, remote_jtl_path: str, local_jtl_path: str) -> str:
        """Download JTL file from load gen via SFTP.

        Returns: local_jtl_path
        """
        logger.info("Collecting JTL: %s -> %s", remote_jtl_path, local_jtl_path)
        self._executor.download(remote_jtl_path, local_jtl_path)
        return local_jtl_path

    def collect_log(self, remote_log_path: str, local_log_path: str) -> str:
        """Download JMeter log file from load gen via SFTP.

        Returns: local_log_path
        """
        logger.info("Collecting JMeter log: %s -> %s", remote_log_path, local_log_path)
        self._executor.download(remote_log_path, local_log_path)
        return local_log_path

    def deploy_files(self, files: Dict[str, str]) -> None:
        """Upload JMX template and CSV files to load gen via SFTP.

        Args:
            files: {remote_path: local_path}
        """
        for remote_path, local_path in files.items():
            logger.info("Deploying %s -> %s", local_path, remote_path)
            self._executor.upload(local_path, remote_path)
