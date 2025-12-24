"""Agent installation and management router."""

import os
import subprocess
import platform
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models.responses import AgentInfoResponse


router = APIRouter(prefix="/agent")


class InstallAgentRequest(BaseModel):
    """Request to install an agent."""

    agent_type: str = Field(..., description="Type of agent to install")
    installer_path: str = Field(..., description="Path to installer")
    install_options: dict = Field(default_factory=dict, description="Install options")


class UninstallAgentRequest(BaseModel):
    """Request to uninstall an agent."""

    agent_type: str = Field(..., description="Type of agent to uninstall")
    force: bool = Field(default=False, description="Force uninstall")


class AgentServiceRequest(BaseModel):
    """Request to control agent service."""

    agent_type: str = Field(..., description="Type of agent")
    action: str = Field(..., description="Service action (start, stop, restart)")


# Agent installation paths and service names
AGENT_CONFIG = {
    "crowdstrike": {
        "windows": {
            "install_path": r"C:\Program Files\CrowdStrike",
            "service_name": "CSFalconService",
            "uninstall_cmd": "CsUninstallTool.exe /quiet",
        },
        "linux": {
            "install_path": "/opt/CrowdStrike",
            "service_name": "falcon-sensor",
            "uninstall_cmd": "falcon-kernel-check -u",
        },
    },
    "sentinelone": {
        "windows": {
            "install_path": r"C:\Program Files\SentinelOne",
            "service_name": "SentinelAgent",
            "uninstall_cmd": "SentinelCtl.exe uninstall",
        },
        "linux": {
            "install_path": "/opt/sentinelone",
            "service_name": "sentinelone",
            "uninstall_cmd": "sentinelctl uninstall",
        },
    },
    "carbonblack": {
        "windows": {
            "install_path": r"C:\Program Files\Confer",
            "service_name": "CbDefense",
            "uninstall_cmd": "RepCLI.exe uninstall",
        },
        "linux": {
            "install_path": "/opt/carbonblack",
            "service_name": "cbagentd",
            "uninstall_cmd": "cbagentd -u",
        },
    },
}


def _get_platform() -> str:
    """Get current platform."""
    system = platform.system().lower()
    return "windows" if system == "windows" else "linux"


def _get_service_status(service_name: str) -> Optional[str]:
    """Get service status."""
    system = _get_platform()

    try:
        if system == "windows":
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "RUNNING" in result.stdout:
                return "running"
            elif "STOPPED" in result.stdout:
                return "stopped"
            return "unknown"
        else:
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
    except Exception:
        return None


def _get_agent_version(agent_type: str) -> Optional[str]:
    """Get installed agent version."""
    # This would need agent-specific version detection
    # Returning None for now - actual implementation depends on agent
    return None


@router.get("/{agent_type}", response_model=AgentInfoResponse)
async def get_agent_info(agent_type: str) -> AgentInfoResponse:
    """Get information about an installed agent."""
    agent_type_lower = agent_type.lower()

    if agent_type_lower not in AGENT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    platform_key = _get_platform()
    config = AGENT_CONFIG[agent_type_lower].get(platform_key)

    if not config:
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_type} not supported on {platform_key}",
        )

    install_path = config["install_path"]
    service_name = config["service_name"]

    installed = os.path.exists(install_path)
    service_status = _get_service_status(service_name) if installed else None
    version = _get_agent_version(agent_type_lower) if installed else None

    return AgentInfoResponse(
        agent_type=agent_type_lower,
        installed=installed,
        version=version,
        service_status=service_status,
        install_path=install_path if installed else None,
    )


@router.post("/install")
async def install_agent(request: InstallAgentRequest) -> dict:
    """Install an agent."""
    agent_type = request.agent_type.lower()

    if agent_type not in AGENT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    if not os.path.exists(request.installer_path):
        raise HTTPException(status_code=400, detail="Installer path does not exist")

    platform_key = _get_platform()

    try:
        # Build install command based on agent type
        if platform_key == "windows":
            cmd = [request.installer_path, "/quiet", "/norestart"]
        else:
            cmd = ["sudo", request.installer_path]

        # Add any custom options
        for key, value in request.install_options.items():
            cmd.append(f"/{key}={value}" if platform_key == "windows" else f"--{key}={value}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "message": f"Installation failed: {result.stderr}",
                "exit_code": result.returncode,
            }

        return {
            "success": True,
            "message": f"Agent {agent_type} installed successfully",
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Installation timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uninstall")
async def uninstall_agent(request: UninstallAgentRequest) -> dict:
    """Uninstall an agent."""
    agent_type = request.agent_type.lower()

    if agent_type not in AGENT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    platform_key = _get_platform()
    config = AGENT_CONFIG[agent_type].get(platform_key)

    if not config:
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_type} not supported on {platform_key}",
        )

    if not os.path.exists(config["install_path"]):
        return {"success": True, "message": "Agent not installed"}

    try:
        uninstall_cmd = config["uninstall_cmd"]
        cmd_parts = uninstall_cmd.split()

        if platform_key != "windows":
            cmd_parts = ["sudo"] + cmd_parts

        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=config["install_path"],
        )

        if result.returncode != 0 and not request.force:
            return {
                "success": False,
                "message": f"Uninstall failed: {result.stderr}",
                "exit_code": result.returncode,
            }

        return {
            "success": True,
            "message": f"Agent {agent_type} uninstalled successfully",
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Uninstall timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/service")
async def control_agent_service(request: AgentServiceRequest) -> dict:
    """Control agent service (start/stop/restart)."""
    agent_type = request.agent_type.lower()
    action = request.action.lower()

    if agent_type not in AGENT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    if action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    platform_key = _get_platform()
    config = AGENT_CONFIG[agent_type].get(platform_key)

    if not config:
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_type} not supported on {platform_key}",
        )

    service_name = config["service_name"]

    try:
        if platform_key == "windows":
            cmd = ["sc", action, service_name]
        else:
            cmd = ["sudo", "systemctl", action, service_name]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "message": f"Service {action} failed: {result.stderr}",
            }

        return {
            "success": True,
            "message": f"Service {service_name} {action} successful",
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Service operation timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
