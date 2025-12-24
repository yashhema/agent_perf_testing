"""Repository for Baseline entity."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Baseline, BaselineConfig
from app.models.enums import BaselineType
from app.models.orm import BaselineORM
from app.repositories.base import BaseRepository


class BaselineRepository(BaseRepository[BaselineORM, Baseline]):
    """Repository for Baseline CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, BaselineORM)

    def _orm_to_model(self, orm: BaselineORM) -> Baseline:
        """Convert BaselineORM to Baseline application model."""
        # Convert JSONB to BaselineConfig
        conf_dict = orm.baseline_conf or {}
        baseline_conf = BaselineConfig(
            vcenter_host=conf_dict.get("vcenter_host"),
            datacenter=conf_dict.get("datacenter"),
            snapshot_name=conf_dict.get("snapshot_name"),
            ami_id=conf_dict.get("ami_id"),
            instance_type=conf_dict.get("instance_type"),
            region=conf_dict.get("region"),
            policy_id=conf_dict.get("policy_id"),
            group_id=conf_dict.get("group_id"),
        )

        return Baseline(
            id=orm.id,
            name=orm.name,
            description=orm.description,
            baseline_type=BaselineType(orm.baseline_type),
            baseline_conf=baseline_conf,
            lab_id=orm.lab_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def _config_to_dict(self, config: BaselineConfig) -> dict:
        """Convert BaselineConfig to dictionary for JSONB storage."""
        result = {}

        if config.vcenter_host is not None:
            result["vcenter_host"] = config.vcenter_host
        if config.datacenter is not None:
            result["datacenter"] = config.datacenter
        if config.snapshot_name is not None:
            result["snapshot_name"] = config.snapshot_name
        if config.ami_id is not None:
            result["ami_id"] = config.ami_id
        if config.instance_type is not None:
            result["instance_type"] = config.instance_type
        if config.region is not None:
            result["region"] = config.region
        if config.policy_id is not None:
            result["policy_id"] = config.policy_id
        if config.group_id is not None:
            result["group_id"] = config.group_id

        return result

    async def create(
        self,
        name: str,
        baseline_type: BaselineType,
        baseline_conf: BaselineConfig,
        lab_id: int,
        description: Optional[str] = None,
    ) -> Baseline:
        """Create a new baseline."""
        orm = BaselineORM(
            name=name,
            description=description,
            baseline_type=baseline_type.value,
            baseline_conf=self._config_to_dict(baseline_conf),
            lab_id=lab_id,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_lab_id(self, lab_id: int) -> list[Baseline]:
        """Get all baselines in a lab."""
        stmt = (
            select(BaselineORM)
            .where(BaselineORM.lab_id == lab_id)
            .order_by(BaselineORM.name)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_type(
        self,
        lab_id: int,
        baseline_type: BaselineType,
    ) -> list[Baseline]:
        """Get baselines by type in a lab."""
        stmt = (
            select(BaselineORM)
            .where(
                BaselineORM.lab_id == lab_id,
                BaselineORM.baseline_type == baseline_type.value,
            )
            .order_by(BaselineORM.name)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_name(
        self,
        name: str,
        lab_id: int,
    ) -> Optional[Baseline]:
        """Get baseline by name in a lab."""
        stmt = select(BaselineORM).where(
            BaselineORM.name == name,
            BaselineORM.lab_id == lab_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update(
        self,
        baseline_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        baseline_conf: Optional[BaselineConfig] = None,
    ) -> Optional[Baseline]:
        """Update a baseline."""
        stmt = select(BaselineORM).where(BaselineORM.id == baseline_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if name is not None:
            orm.name = name
        if description is not None:
            orm.description = description
        if baseline_conf is not None:
            orm.baseline_conf = self._config_to_dict(baseline_conf)

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)
