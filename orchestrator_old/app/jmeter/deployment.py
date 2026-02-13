"""JMX deployment service.

Generates and deploys JMX test plans to load generators.
This is production code used for Lab1/Lab2 type deployments.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from app.jmeter.template import (
    JMXTemplateManager,
    JMXTestPlanConfig,
    HTTPSamplerConfig,
)
from app.jmeter.models import JMeterConfig


logger = logging.getLogger(__name__)


class SSHFileTransfer(Protocol):
    """Protocol for SSH file operations."""

    async def write_file(
        self,
        remote_path: str,
        content: str,
    ) -> bool:
        """Write content to remote file. Returns success."""
        ...

    async def file_exists(
        self,
        remote_path: str,
    ) -> bool:
        """Check if remote file exists."""
        ...

    async def mkdir(
        self,
        remote_path: str,
    ) -> bool:
        """Create remote directory. Returns success."""
        ...


@dataclass
class TestPlanSpec:
    """Specification for generating a test plan."""

    # Target info
    target_host: str
    target_port: int

    # Load configuration (from calibration)
    thread_count: int
    warmup_sec: int
    measured_sec: int

    # Test identification
    test_run_id: int
    target_id: int
    load_profile: str

    # Optional customization
    ramp_up_sec: int = 30
    samplers: Optional[list[HTTPSamplerConfig]] = None


class JMXDeploymentService:
    """
    Service for generating and deploying JMX test plans.

    Handles the complete flow:
    1. Generate JMX content from test specification
    2. Deploy to load generator via SSH
    3. Return path for JMeterService to use
    """

    def __init__(
        self,
        template_manager: Optional[JMXTemplateManager] = None,
        jmx_base_dir: str = "/opt/jmeter/plans",
    ):
        """
        Initialize deployment service.

        Args:
            template_manager: JMX template manager (created if not provided)
            jmx_base_dir: Base directory on loadgen for JMX files
        """
        self._template_manager = template_manager or JMXTemplateManager()
        self._jmx_base_dir = jmx_base_dir

    def generate_jmx(self, spec: TestPlanSpec) -> str:
        """
        Generate JMX content from test specification.

        Args:
            spec: Test plan specification

        Returns:
            JMX file content as string
        """
        # Build samplers - default set if not provided
        samplers = spec.samplers or [
            HTTPSamplerConfig(name="Health Check", path="/health"),
            HTTPSamplerConfig(name="Status", path="/status"),
            HTTPSamplerConfig(name="Calibration", path="/calibration"),
        ]

        config = JMXTestPlanConfig(
            name=f"TestRun-{spec.test_run_id}-Target-{spec.target_id}-{spec.load_profile}",
            comments=f"Generated for test run {spec.test_run_id}, target {spec.target_id}, profile {spec.load_profile}",
            target_host=spec.target_host,
            target_port=spec.target_port,
            thread_count=spec.thread_count,
            ramp_up_sec=spec.ramp_up_sec,
            warmup_sec=spec.warmup_sec,
            duration_sec=spec.warmup_sec + spec.measured_sec,
            samplers=samplers,
            include_warmup_group=True,
        )

        return self._template_manager.generate_test_plan(config)

    def get_jmx_path(
        self,
        test_run_id: int,
        target_id: int,
        load_profile: str,
    ) -> str:
        """
        Get the remote path where JMX file should be stored.

        Args:
            test_run_id: Test run ID
            target_id: Target server ID
            load_profile: Load profile name

        Returns:
            Remote path for JMX file
        """
        filename = f"testrun_{test_run_id}_target_{target_id}_{load_profile}.jmx"
        return f"{self._jmx_base_dir}/{filename}"

    async def deploy_jmx(
        self,
        ssh_transfer: SSHFileTransfer,
        spec: TestPlanSpec,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Generate and deploy JMX to load generator.

        Args:
            ssh_transfer: SSH file transfer interface
            spec: Test plan specification

        Returns:
            Tuple of (success, jmx_path, error_message)
        """
        try:
            # Generate JMX content
            jmx_content = self.generate_jmx(spec)

            # Get remote path
            jmx_path = self.get_jmx_path(
                spec.test_run_id,
                spec.target_id,
                spec.load_profile,
            )

            # Ensure directory exists
            await ssh_transfer.mkdir(self._jmx_base_dir)

            # Write JMX file
            success = await ssh_transfer.write_file(jmx_path, jmx_content)

            if success:
                logger.info(f"Deployed JMX to {jmx_path}")
                return True, jmx_path, None
            else:
                return False, "", "Failed to write JMX file"

        except Exception as e:
            logger.error(f"JMX deployment failed: {e}")
            return False, "", str(e)

    def create_jmeter_config(
        self,
        spec: TestPlanSpec,
        jmx_path: str,
        result_dir: str = "/var/log/jmeter",
    ) -> JMeterConfig:
        """
        Create JMeterConfig from spec and deployed path.

        Args:
            spec: Test plan specification
            jmx_path: Path to deployed JMX file
            result_dir: Directory for result files

        Returns:
            JMeterConfig ready for JMeterService
        """
        result_file = f"{result_dir}/results_{spec.test_run_id}_{spec.target_id}_{spec.load_profile}.jtl"
        log_file = f"{result_dir}/jmeter_{spec.test_run_id}_{spec.target_id}_{spec.load_profile}.log"

        return JMeterConfig(
            jmx_file_path=jmx_path,
            result_file_path=result_file,
            log_file_path=log_file,
            target_host=spec.target_host,
            target_port=spec.target_port,
            thread_count=spec.thread_count,
            ramp_up_sec=spec.ramp_up_sec,
            warmup_sec=spec.warmup_sec,
            measured_sec=spec.measured_sec,
            total_duration_sec=spec.warmup_sec + spec.measured_sec,
        )


class SSHFileTransferAdapter:
    """
    Adapter to provide SSHFileTransfer from SSHExecutor.

    Converts SSHExecutor's command-based interface to file transfer operations.
    """

    def __init__(self, ssh_executor):
        """
        Initialize adapter.

        Args:
            ssh_executor: SSHExecutor instance connected to loadgen
        """
        self._ssh = ssh_executor

    async def write_file(
        self,
        remote_path: str,
        content: str,
    ) -> bool:
        """Write content to remote file using cat heredoc."""
        # Escape content for shell
        escaped_content = content.replace("'", "'\"'\"'")

        # Use cat with heredoc to write file
        command = f"cat > {remote_path} << 'JMXEOF'\n{content}\nJMXEOF"

        result = self._ssh.execute_command(command, timeout=60)
        return result.success

    async def file_exists(
        self,
        remote_path: str,
    ) -> bool:
        """Check if file exists."""
        result = self._ssh.execute_command(f"test -f {remote_path}", timeout=10)
        return result.success

    async def mkdir(
        self,
        remote_path: str,
    ) -> bool:
        """Create directory."""
        result = self._ssh.execute_command(f"mkdir -p {remote_path}", timeout=10)
        return result.success
