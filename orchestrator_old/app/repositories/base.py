"""Base repository class with common functionality."""

from typing import Generic, TypeVar, Type, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Base

ORMModel = TypeVar("ORMModel", bound=Base)
AppModel = TypeVar("AppModel")


class BaseRepository(Generic[ORMModel, AppModel]):
    """Base repository with common CRUD operations.

    Subclasses must implement:
    - _orm_to_model: Convert ORM model to Application model
    - _model_to_orm: Convert Application model to ORM model (optional)
    """

    def __init__(self, session: AsyncSession, orm_class: Type[ORMModel]):
        self._session = session
        self._orm_class = orm_class

    @property
    def session(self) -> AsyncSession:
        """Get the database session."""
        return self._session

    def _orm_to_model(self, orm: ORMModel) -> AppModel:
        """Convert ORM model to Application model.

        Must be implemented by subclasses.
        """
        raise NotImplementedError

    async def get_by_id(self, id: int) -> Optional[AppModel]:
        """Get entity by ID."""
        stmt = select(self._orm_class).where(self._orm_class.id == id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def get_all(self) -> list[AppModel]:
        """Get all entities."""
        stmt = select(self._orm_class).order_by(self._orm_class.id)
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def delete_by_id(self, id: int) -> bool:
        """Delete entity by ID. Returns True if deleted."""
        stmt = select(self._orm_class).where(self._orm_class.id == id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return False

        await self._session.delete(orm)
        await self._session.flush()
        return True
