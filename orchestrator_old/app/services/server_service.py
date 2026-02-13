"""Service layer for Server operations."""

from typing import Optional

from app.models.application import Server
from app.models.enums import OSFamily, ServerRole
from app.repositories.server_repository import ServerRepository
from app.repositories.lab_repository import LabRepository


class ServerService:
    """Service for Server business logic."""

    def __init__(
        self,
        repository: ServerRepository,
        lab_repository: LabRepository,
    ):
        self._repo = repository
        self._lab_repo = lab_repository

    async def create_server(
        self,
        hostname: str,
        ip_address: str,
        os_family: OSFamily,
        server_type: ServerRole,
        lab_id: int,
        ssh_username: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        winrm_username: Optional[str] = None,
        emulator_port: int = 8080,
        loadgen_service_port: int = 8090,
        is_active: bool = True,
    ) -> Server:
        """
        Create a new server.

        Args:
            hostname: Server hostname.
            ip_address: Server IP address.
            os_family: Operating system family.
            server_type: Type of server.
            lab_id: ID of the lab this server belongs to.
            ssh_username: SSH username for Linux servers.
            ssh_key_path: Path to SSH key.
            winrm_username: WinRM username for Windows servers.
            emulator_port: Port for emulator service.
            loadgen_service_port: Port for load generator service.
            is_active: Whether the server is active.

        Returns:
            The created Server.

        Raises:
            ValueError: If the lab doesn't exist or hostname is duplicate in lab.
        """
        # Verify lab exists
        lab = await self._lab_repo.get_by_id(lab_id)
        if lab is None:
            raise ValueError(f"Lab with ID {lab_id} not found")

        # Check for duplicate hostname in lab
        existing = await self._repo.get_by_hostname(hostname, lab_id)
        if existing is not None:
            raise ValueError(
                f"Server with hostname '{hostname}' already exists in lab {lab_id}"
            )

        return await self._repo.create(
            hostname=hostname,
            ip_address=ip_address,
            os_family=os_family,
            server_type=server_type,
            lab_id=lab_id,
            ssh_username=ssh_username,
            ssh_key_path=ssh_key_path,
            winrm_username=winrm_username,
            emulator_port=emulator_port,
            loadgen_service_port=loadgen_service_port,
            is_active=is_active,
        )

    async def get_server(self, server_id: int) -> Optional[Server]:
        """Get a server by ID."""
        return await self._repo.get_by_id(server_id)

    async def get_server_by_hostname(
        self,
        hostname: str,
        lab_id: Optional[int] = None,
    ) -> Optional[Server]:
        """Get a server by hostname."""
        return await self._repo.get_by_hostname(hostname, lab_id)

    async def list_servers(self, lab_id: int) -> list[Server]:
        """List all servers in a lab."""
        return await self._repo.get_by_lab_id(lab_id)

    async def list_servers_by_type(
        self,
        lab_id: int,
        server_type: ServerRole,
        active_only: bool = True,
    ) -> list[Server]:
        """List servers by type in a lab."""
        return await self._repo.get_by_type(lab_id, server_type, active_only)

    async def get_load_generators(
        self,
        lab_id: int,
        active_only: bool = True,
    ) -> list[Server]:
        """Get all load generator servers in a lab."""
        return await self._repo.get_by_type(
            lab_id, ServerRole.LOAD_GENERATOR, active_only
        )

    async def get_app_servers(
        self,
        lab_id: int,
        active_only: bool = True,
    ) -> list[Server]:
        """Get all app servers in a lab."""
        return await self._repo.get_by_type(
            lab_id, ServerRole.APP_SERVER, active_only
        )

    async def update_server(
        self,
        server_id: int,
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        os_family: Optional[OSFamily] = None,
        server_type: Optional[ServerRole] = None,
        ssh_username: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        winrm_username: Optional[str] = None,
        emulator_port: Optional[int] = None,
        loadgen_service_port: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Server]:
        """Update a server."""
        return await self._repo.update(
            server_id=server_id,
            hostname=hostname,
            ip_address=ip_address,
            os_family=os_family,
            server_type=server_type,
            ssh_username=ssh_username,
            ssh_key_path=ssh_key_path,
            winrm_username=winrm_username,
            emulator_port=emulator_port,
            loadgen_service_port=loadgen_service_port,
            is_active=is_active,
        )

    async def deactivate_server(self, server_id: int) -> Optional[Server]:
        """Deactivate a server (soft delete)."""
        return await self._repo.deactivate(server_id)

    async def activate_server(self, server_id: int) -> Optional[Server]:
        """Activate a server."""
        return await self._repo.activate(server_id)

    async def delete_server(self, server_id: int) -> bool:
        """Delete a server."""
        return await self._repo.delete_by_id(server_id)
