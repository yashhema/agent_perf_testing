"""Repository for Server entity."""

from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Server
from app.models.enums import OSFamily, ServerType
from app.models.orm import ServerORM
from app.repositories.base import BaseRepository


class ServerRepository(BaseRepository[ServerORM, Server]):
    """Repository for Server CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ServerORM)

    def _orm_to_model(self, orm: ServerORM) -> Server:
        """Convert ServerORM to Server application model."""
        return Server(
            id=orm.id,
            hostname=orm.hostname,
            ip_address=orm.ip_address,
            os_family=OSFamily(orm.os_family),
            server_type=ServerType(orm.server_type),
            lab_id=orm.lab_id,
            ssh_username=orm.ssh_username,
            ssh_key_path=orm.ssh_key_path,
            winrm_username=orm.winrm_username,
            emulator_port=orm.emulator_port,
            loadgen_service_port=orm.loadgen_service_port,
            is_active=orm.is_active,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        hostname: str,
        ip_address: str,
        os_family: OSFamily,
        server_type: ServerType,
        lab_id: int,
        ssh_username: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        winrm_username: Optional[str] = None,
        emulator_port: int = 8080,
        loadgen_service_port: int = 8090,
        is_active: bool = True,
    ) -> Server:
        """Create a new server."""
        orm = ServerORM(
            hostname=hostname,
            ip_address=ip_address,
            os_family=os_family.value,
            server_type=server_type.value,
            lab_id=lab_id,
            ssh_username=ssh_username,
            ssh_key_path=ssh_key_path,
            winrm_username=winrm_username,
            emulator_port=emulator_port,
            loadgen_service_port=loadgen_service_port,
            is_active=is_active,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_lab_id(self, lab_id: int) -> list[Server]:
        """Get all servers in a lab."""
        stmt = (
            select(ServerORM)
            .where(ServerORM.lab_id == lab_id)
            .order_by(ServerORM.hostname)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_type(
        self,
        lab_id: int,
        server_type: ServerType,
        active_only: bool = True,
    ) -> list[Server]:
        """Get servers by type in a lab."""
        conditions = [
            ServerORM.lab_id == lab_id,
            ServerORM.server_type == server_type.value,
        ]

        if active_only:
            conditions.append(ServerORM.is_active == True)

        stmt = (
            select(ServerORM)
            .where(and_(*conditions))
            .order_by(ServerORM.hostname)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_hostname(
        self,
        hostname: str,
        lab_id: Optional[int] = None,
    ) -> Optional[Server]:
        """Get server by hostname."""
        conditions = [ServerORM.hostname == hostname]

        if lab_id is not None:
            conditions.append(ServerORM.lab_id == lab_id)

        stmt = select(ServerORM).where(and_(*conditions))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update(
        self,
        server_id: int,
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        os_family: Optional[OSFamily] = None,
        server_type: Optional[ServerType] = None,
        ssh_username: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        winrm_username: Optional[str] = None,
        emulator_port: Optional[int] = None,
        loadgen_service_port: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Server]:
        """Update a server."""
        stmt = select(ServerORM).where(ServerORM.id == server_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if hostname is not None:
            orm.hostname = hostname
        if ip_address is not None:
            orm.ip_address = ip_address
        if os_family is not None:
            orm.os_family = os_family.value
        if server_type is not None:
            orm.server_type = server_type.value
        if ssh_username is not None:
            orm.ssh_username = ssh_username
        if ssh_key_path is not None:
            orm.ssh_key_path = ssh_key_path
        if winrm_username is not None:
            orm.winrm_username = winrm_username
        if emulator_port is not None:
            orm.emulator_port = emulator_port
        if loadgen_service_port is not None:
            orm.loadgen_service_port = loadgen_service_port
        if is_active is not None:
            orm.is_active = is_active

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def deactivate(self, server_id: int) -> Optional[Server]:
        """Deactivate a server (soft delete)."""
        return await self.update(server_id, is_active=False)

    async def activate(self, server_id: int) -> Optional[Server]:
        """Activate a server."""
        return await self.update(server_id, is_active=True)
