"""JMeter controller for load generators.

Matches ORCHESTRATOR_INTERFACES.md Section 2.1 exactly.
Controls JMeter on load generator via SSH/WinRM (RemoteExecutor).
"""

import logging
from typing import Dict, Optional

from orchestrator.infra.remote_executor import RemoteExecutor

logger = logging.getLogger(__name__)


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
            full_cmd = f"nohup {command} > /dev/null 2>&1 & echo $!"
        else:
            # Windows: use start /B and get PID via WMI
            full_cmd = f'start /B {command} & for /F "tokens=2" %i in (\'tasklist /FI "IMAGENAME eq java.exe" /NH\') do @echo %i'

        logger.info("Starting JMeter on %s: threads=%d, duration=%ds", target_host, thread_count, duration_sec)
        result = self._executor.execute(full_cmd)

        if not result.success:
            raise RuntimeError(f"JMeter start failed: {result.stderr}")

        pid = int(result.stdout.strip().split("\n")[-1].strip())
        logger.info("JMeter started with PID %d", pid)
        return pid

    def is_running(self, pid: int) -> bool:
        """Check if JMeter process is still running."""
        if self._os_family == "linux":
            result = self._executor.execute(f"kill -0 {pid} 2>/dev/null && echo RUNNING || echo STOPPED")
        else:
            result = self._executor.execute(f'tasklist /FI "PID eq {pid}" /NH')

        return "RUNNING" in result.stdout or (self._os_family == "windows" and "java" in result.stdout.lower())

    def stop(self, pid: int) -> None:
        """Stop JMeter process."""
        if self._os_family == "linux":
            self._executor.execute(f"kill {pid}")
        else:
            self._executor.execute(f"taskkill /PID {pid} /F")
        logger.info("JMeter stopped (PID %d)", pid)

    def collect_jtl(self, remote_jtl_path: str, local_jtl_path: str) -> str:
        """Download JTL file from load gen via SFTP.

        Returns: local_jtl_path
        """
        logger.info("Collecting JTL: %s -> %s", remote_jtl_path, local_jtl_path)
        self._executor.download(remote_jtl_path, local_jtl_path)
        return local_jtl_path

    def deploy_files(self, files: Dict[str, str]) -> None:
        """Upload JMX template and CSV files to load gen via SFTP.

        Args:
            files: {remote_path: local_path}
        """
        for remote_path, local_path in files.items():
            logger.info("Deploying %s -> %s", local_path, remote_path)
            self._executor.upload(local_path, remote_path)
