"""Discovery service — detects OS kind, version, and agent versions on targets.

Runs after each snapshot restore to populate per-snapshot fields on
TestRunTargetORM.  Discovery is non-fatal: failures are logged as warnings
and leave fields null so the test run can continue normally.

Supports pluggable discovery scripts under the discovery/ directory:
    discovery/<os_kind>/os_version.sh|.ps1
    discovery/<os_kind>/<agent_discovery_key>.sh|.ps1

All scripts must output JSON to stdout.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.infra.remote_executor import RemoteExecutor, create_executor
from orchestrator.models.enums import OSFamily
from orchestrator.models.orm import (
    AgentORM,
    ScenarioORM,
    ServerORM,
    TestRunORM,
    TestRunTargetORM,
)

logger = logging.getLogger(__name__)

# Maps /etc/os-release ID values to canonical os_kind values
KIND_MAP = {
    "rhel": "rhel",
    "centos": "rhel",
    "rocky": "rhel",
    "almalinux": "rhel",
    "oracle": "rhel",
    "ubuntu": "ubuntu",
    "debian": "ubuntu",
    "sles": "sles",
    "opensuse-leap": "sles",
}


@dataclass
class OSDiscoveryResult:
    """Result of OS version discovery on one target."""
    os_kind: str
    os_major_ver: str
    os_minor_ver: Optional[str] = None
    os_build: Optional[str] = None
    os_kernel_ver: Optional[str] = None


@dataclass
class AgentDiscoveryResult:
    """Result of agent version discovery for one agent on one target."""
    agent_id: int
    agent_name: str
    discovery_key: str
    discovered_version: str
    status: str = "unknown"


@dataclass
class TargetDiscoveryResult:
    """Combined discovery results for one target server."""
    target_id: int
    os_family: OSFamily
    os_discovery: Optional[OSDiscoveryResult] = None
    agent_discoveries: List[AgentDiscoveryResult] = field(default_factory=list)
    raw_outputs: Dict[str, str] = field(default_factory=dict)


class DiscoveryService:
    """Discovers OS and agent version information on test run targets.

    Connects to each target via SSH/WinRM, runs discovery scripts
    (or built-in fallback commands), and stores results on the
    TestRunTargetORM record.
    """

    def __init__(self, credentials: CredentialsStore, discovery_dir: Path):
        self._credentials = credentials
        self._discovery_dir = discovery_dir

    def discover_and_store(
        self, session: Session, test_run: TestRunORM, snapshot_num: int
    ) -> None:
        """Run discovery on all targets and update TestRunTargetORM fields.

        Called TWICE per test run:
          snapshot_num=1  after base snapshot restore
                          populates os_kind, base_os_*, base_agent_versions
          snapshot_num=2  after initial snapshot restore
                          populates initial_os_*, initial_agent_versions
        """
        targets = (
            session.query(TestRunTargetORM)
            .filter(TestRunTargetORM.test_run_id == test_run.id)
            .all()
        )

        # Load agents linked to the scenario
        scenario = session.get(ScenarioORM, test_run.scenario_id)
        agents: List[AgentORM] = list(scenario.agents) if scenario else []

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            if not server:
                logger.warning("Target server %d not found, skipping discovery", target_config.target_id)
                continue

            try:
                result = self._discover_target(server, agents)
                self._store_result(session, target_config, result, snapshot_num)
            except Exception as e:
                logger.warning(
                    "Discovery failed for target %s (id=%d): %s",
                    server.hostname, server.id, e,
                )

        session.commit()

    def _discover_target(
        self, server: ServerORM, agents: List[AgentORM]
    ) -> TargetDiscoveryResult:
        """SSH/WinRM into target, run discovery scripts, return results."""
        result = TargetDiscoveryResult(
            target_id=server.id, os_family=server.os_family
        )

        cred = self._credentials.get_server_credential(server.id, server.os_family.value)
        if not cred:
            logger.warning("No credentials for server %s (id=%d)", server.hostname, server.id)
            return result

        executor = create_executor(
            os_family=server.os_family.value,
            host=server.ip_address,
            username=cred.username,
            password=cred.password,
        )

        try:
            # 1. Determine OS kind
            os_kind = self._determine_os_kind(executor, server.os_family)

            # 2. Discover OS version
            os_discovery = self._discover_os_version(executor, server.os_family, os_kind)
            result.os_discovery = os_discovery

            # 3. Discover agent versions
            for agent in agents:
                if not agent.discovery_key:
                    continue
                try:
                    agent_result = self._discover_agent_version(
                        executor, agent, os_kind, server.os_family
                    )
                    result.agent_discoveries.append(agent_result)
                except Exception as e:
                    logger.warning(
                        "Agent discovery failed for '%s' on %s: %s",
                        agent.name, server.hostname, e,
                    )
        finally:
            executor.close()

        return result

    def _determine_os_kind(self, executor: RemoteExecutor, os_family: OSFamily) -> str:
        """Determine the canonical OS kind.

        Linux: parse /etc/os-release ID field and map via KIND_MAP.
        Windows: always returns 'windows_server'.
        """
        if os_family == OSFamily.windows:
            return "windows_server"

        # Linux: read /etc/os-release
        cmd_result = executor.execute("cat /etc/os-release", timeout_sec=30)
        if not cmd_result.success:
            logger.warning("Failed to read /etc/os-release: %s", cmd_result.stderr)
            return "unknown"

        os_id = ""
        for line in cmd_result.stdout.splitlines():
            if line.startswith("ID="):
                os_id = line.split("=", 1)[1].strip().strip('"').lower()
                break

        return KIND_MAP.get(os_id, os_id or "unknown")

    def _discover_os_version(
        self,
        executor: RemoteExecutor,
        os_family: OSFamily,
        os_kind: str,
    ) -> OSDiscoveryResult:
        """Run OS version discovery script or fall back to built-in commands."""
        # Try discovery script first
        script_result = self._run_discovery_script(executor, os_family, os_kind, "os_version")
        if script_result:
            return OSDiscoveryResult(
                os_kind=os_kind,
                os_major_ver=script_result.get("os_major_ver", ""),
                os_minor_ver=script_result.get("os_minor_ver"),
                os_build=script_result.get("os_build"),
                os_kernel_ver=script_result.get("os_kernel_ver"),
            )

        # Fallback: built-in detection
        return self._fallback_os_version(executor, os_family, os_kind)

    def _discover_agent_version(
        self,
        executor: RemoteExecutor,
        agent: AgentORM,
        os_kind: str,
        os_family: OSFamily,
    ) -> AgentDiscoveryResult:
        """Run agent discovery script, parse JSON output."""
        script_result = self._run_discovery_script(
            executor, os_family, os_kind, agent.discovery_key
        )

        if script_result:
            return AgentDiscoveryResult(
                agent_id=agent.id,
                agent_name=agent.name,
                discovery_key=agent.discovery_key,
                discovered_version=script_result.get("version", "unknown"),
                status=script_result.get("status", "unknown"),
            )

        return AgentDiscoveryResult(
            agent_id=agent.id,
            agent_name=agent.name,
            discovery_key=agent.discovery_key,
            discovered_version="unknown",
            status="script_not_found",
        )

    def _run_discovery_script(
        self,
        executor: RemoteExecutor,
        os_family: OSFamily,
        os_kind: str,
        script_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Locate and run a discovery script, returning parsed JSON or None."""
        ext = ".ps1" if os_family == OSFamily.windows else ".sh"
        script_path = self._discovery_dir / os_kind / f"{script_name}{ext}"

        if not script_path.exists():
            logger.debug("Discovery script not found: %s", script_path)
            return None

        script_content = script_path.read_text(encoding="utf-8")

        # Execute the script content remotely.
        # Use base64 encoding for Linux to avoid shell quoting issues
        # (scripts may contain single quotes in grep patterns, etc.).
        if os_family == OSFamily.windows:
            cmd = f"powershell -NoProfile -Command \"{script_content}\""
        else:
            encoded = base64.b64encode(script_content.encode("utf-8")).decode("ascii")
            cmd = f"echo {encoded} | base64 -d | bash"

        cmd_result = executor.execute(cmd, timeout_sec=60)
        if not cmd_result.success:
            logger.warning(
                "Discovery script %s failed (exit=%d): %s",
                script_path.name, cmd_result.exit_code, cmd_result.stderr,
            )
            return None

        # Parse JSON output
        try:
            return json.loads(cmd_result.stdout.strip())
        except json.JSONDecodeError as e:
            logger.warning(
                "Discovery script %s returned invalid JSON: %s (output: %s)",
                script_path.name, e, cmd_result.stdout[:200],
            )
            return None

    def _fallback_os_version(
        self,
        executor: RemoteExecutor,
        os_family: OSFamily,
        os_kind: str,
    ) -> OSDiscoveryResult:
        """Built-in OS version detection when no script is available."""
        if os_family == OSFamily.windows:
            cmd = 'powershell -NoProfile -Command "[System.Environment]::OSVersion.Version | Select-Object Major, Minor, Build | ConvertTo-Json -Compress"'
            cmd_result = executor.execute(cmd, timeout_sec=30)
            if cmd_result.success:
                try:
                    data = json.loads(cmd_result.stdout.strip())
                    return OSDiscoveryResult(
                        os_kind=os_kind,
                        os_major_ver=str(data.get("Major", "")),
                        os_minor_ver=str(data.get("Minor", "")),
                        os_build=str(data.get("Build", "")),
                    )
                except (json.JSONDecodeError, KeyError):
                    pass

            return OSDiscoveryResult(os_kind=os_kind, os_major_ver="unknown")

        # Linux fallback: parse /etc/os-release VERSION_ID + uname -r
        ver_cmd = executor.execute(
            "grep ^VERSION_ID= /etc/os-release | cut -d= -f2 | tr -d '\"'",
            timeout_sec=30,
        )
        kernel_cmd = executor.execute("uname -r", timeout_sec=30)

        version_id = ver_cmd.stdout.strip() if ver_cmd.success else ""
        kernel_ver = kernel_cmd.stdout.strip() if kernel_cmd.success else None

        parts = version_id.split(".", 1) if version_id else ["unknown"]
        major = parts[0]
        minor = parts[1] if len(parts) > 1 else None

        return OSDiscoveryResult(
            os_kind=os_kind,
            os_major_ver=major,
            os_minor_ver=minor,
            os_build=version_id or None,
            os_kernel_ver=kernel_ver,
        )

    def _store_result(
        self,
        session: Session,
        target_config: TestRunTargetORM,
        result: TargetDiscoveryResult,
        snapshot_num: int,
    ) -> None:
        """Write discovery result into the appropriate TestRunTargetORM fields."""
        if result.os_discovery:
            # os_kind is shared (set once, usually same for both snapshots)
            target_config.os_kind = result.os_discovery.os_kind

        # Build agent versions list
        agent_versions = [
            {
                "agent_id": ad.agent_id,
                "agent_name": ad.agent_name,
                "discovered_version": ad.discovered_version,
                "status": ad.status,
            }
            for ad in result.agent_discoveries
        ] or None

        if snapshot_num == 1:
            # Base snapshot fields
            if result.os_discovery:
                target_config.base_os_major_ver = result.os_discovery.os_major_ver
                target_config.base_os_minor_ver = result.os_discovery.os_minor_ver
            target_config.base_agent_versions = agent_versions
        else:
            # Initial snapshot fields
            if result.os_discovery:
                target_config.initial_os_major_ver = result.os_discovery.os_major_ver
                target_config.initial_os_minor_ver = result.os_discovery.os_minor_ver
            target_config.initial_agent_versions = agent_versions
