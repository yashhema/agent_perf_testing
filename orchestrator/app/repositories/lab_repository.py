"""Repository for Lab entity."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Lab
from app.models.orm import LabORM
from app.repositories.base import BaseRepository


class LabRepository(BaseRepository[LabORM, Lab]):
    """Repository for Lab CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, LabORM)

    def _orm_to_model(self, orm: LabORM) -> Lab:
        """Convert LabORM to Lab application model."""
        return Lab(
            id=orm.id,
            name=orm.name,
            description=orm.description,
            lab_type=orm.lab_type,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        name: str,
        lab_type: str,
        description: Optional[str] = None,
    ) -> Lab:
        """Create a new lab."""
        orm = LabORM(
            name=name,
            lab_type=lab_type,
            description=description,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_name(self, name: str) -> Optional[Lab]:
        """Get lab by name."""
        stmt = select(LabORM).where(LabORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update(
        self,
        lab_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        lab_type: Optional[str] = None,
    ) -> Optional[Lab]:
        """Update a lab."""
        stmt = select(LabORM).where(LabORM.id == lab_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if name is not None:
            orm.name = name
        if description is not None:
            orm.description = description
        if lab_type is not None:
            orm.lab_type = lab_type

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)
