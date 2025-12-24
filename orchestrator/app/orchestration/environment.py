"""Environment configuration for orchestration.

Provides a system-level flag to switch between production and Docker E2E modes.
"""

import os
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class EnvironmentType(str, Enum):
    """Execution environment type."""

    PRODUCTION = "production"  # Real VMs with vSphere/HyperV
    DOCKER_E2E = "docker_e2e"  # Docker containers for testing


@dataclass
class ContainerConfig:
    """Configuration for a Docker container."""

    name: str
    host: str  # Usually "localhost" for local Docker
    http_port: int  # For emulator API
    ssh_port: int  # For SSH access
    ssh_user: str = "root"
    ssh_password: str = "testpass"


@dataclass
class EnvironmentConfig:
    """
    Environment-aware configuration.

    Holds all settings needed to configure orchestration for either
    production or Docker E2E environments.
    """

    env_type: EnvironmentType

    # Production settings (used when env_type == PRODUCTION)
    hypervisor_host: Optional[str] = None
    hypervisor_user: Optional[str] = None
    hypervisor_password: Optional[str] = None

    # Docker settings (used when env_type == DOCKER_E2E)
    docker_host: str = "localhost"
    containers: dict[int, ContainerConfig] = None  # target_id -> config

    # Common settings
    ssh_user: str = "root"
    ssh_password: str = "testpass"
    ssh_key_path: Optional[str] = None

    def __post_init__(self):
        if self.containers is None:
            self.containers = {}

    @classmethod
    def from_environment(cls) -> "EnvironmentConfig":
        """
        Create config from environment variables.

        Environment variables:
            PERF_TEST_ENV: "production" or "docker_e2e"
            HYPERVISOR_HOST: vSphere/HyperV host
            HYPERVISOR_USER: Hypervisor username
            HYPERVISOR_PASSWORD: Hypervisor password
            DOCKER_HOST: Docker host (default: localhost)
            SSH_USER: SSH username
            SSH_PASSWORD: SSH password
            SSH_KEY_PATH: Path to SSH key
        """
        env_str = os.getenv("PERF_TEST_ENV", "production")
        env_type = EnvironmentType(env_str)

        return cls(
            env_type=env_type,
            hypervisor_host=os.getenv("HYPERVISOR_HOST"),
            hypervisor_user=os.getenv("HYPERVISOR_USER"),
            hypervisor_password=os.getenv("HYPERVISOR_PASSWORD"),
            docker_host=os.getenv("DOCKER_HOST", "localhost"),
            ssh_user=os.getenv("SSH_USER", "root"),
            ssh_password=os.getenv("SSH_PASSWORD", "testpass"),
            ssh_key_path=os.getenv("SSH_KEY_PATH"),
        )

    @classmethod
    def for_docker_e2e(
        cls,
        host: str = "localhost",
        containers: Optional[dict[int, ContainerConfig]] = None,
    ) -> "EnvironmentConfig":
        """Create config for Docker E2E testing."""
        return cls(
            env_type=EnvironmentType.DOCKER_E2E,
            docker_host=host,
            containers=containers or {},
        )

    @classmethod
    def for_production(
        cls,
        hypervisor_host: str,
        hypervisor_user: str,
        hypervisor_password: str,
    ) -> "EnvironmentConfig":
        """Create config for production environment."""
        return cls(
            env_type=EnvironmentType.PRODUCTION,
            hypervisor_host=hypervisor_host,
            hypervisor_user=hypervisor_user,
            hypervisor_password=hypervisor_password,
        )

    @property
    def is_docker(self) -> bool:
        """Check if running in Docker E2E mode."""
        return self.env_type == EnvironmentType.DOCKER_E2E

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.env_type == EnvironmentType.PRODUCTION


# Global config instance - set at startup
_current_config: Optional[EnvironmentConfig] = None


def get_environment_config() -> EnvironmentConfig:
    """Get current environment configuration."""
    global _current_config
    if _current_config is None:
        _current_config = EnvironmentConfig.from_environment()
    return _current_config


def set_environment_config(config: EnvironmentConfig) -> None:
    """Set environment configuration (for testing)."""
    global _current_config
    _current_config = config


def is_docker_mode() -> bool:
    """Quick check if running in Docker E2E mode."""
    return get_environment_config().is_docker
