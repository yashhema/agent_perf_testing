"""Repository for TestRun and TestRunTarget entities."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import TestRun, TestRunTarget, LoadProfile
from app.models.orm import TestRunORM, TestRunTargetORM
from app.repositories.base import BaseRepository


class TestRunRepository(BaseRepository[TestRunORM, TestRun]):
    """Repository for TestRun CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, TestRunORM)

    def _orm_to_model(self, orm: TestRunORM) -> TestRun:
        """Convert TestRunORM to TestRun application model."""
        return TestRun(
            id=orm.id,
            name=orm.name,
            description=orm.description,
            lab_id=orm.lab_id,
            req_loadprofile=[LoadProfile(lp) for lp in orm.req_loadprofile],
            warmup_sec=orm.warmup_sec,
            measured_sec=orm.measured_sec,
            analysis_trim_sec=orm.analysis_trim_sec,
            repetitions=orm.repetitions,
            loadgenerator_package_grpid_lst=list(orm.loadgenerator_package_grpid_lst),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        name: str,
        lab_id: int,
        req_loadprofile: list[LoadProfile],
        loadgenerator_package_grpid_lst: list[int],
        description: Optional[str] = None,
        warmup_sec: int = 300,
        measured_sec: int = 10800,
        analysis_trim_sec: int = 300,
        repetitions: int = 1,
    ) -> TestRun:
        """Create a new test run."""
        orm = TestRunORM(
            name=name,
            description=description,
            lab_id=lab_id,
            req_loadprofile=[lp.value for lp in req_loadprofile],
            warmup_sec=warmup_sec,
            measured_sec=measured_sec,
            analysis_trim_sec=analysis_trim_sec,
            repetitions=repetitions,
            loadgenerator_package_grpid_lst=loadgenerator_package_grpid_lst,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_lab_id(self, lab_id: int) -> list[TestRun]:
        """Get all test runs in a lab."""
        stmt = (
            select(TestRunORM)
            .where(TestRunORM.lab_id == lab_id)
            .order_by(TestRunORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_with_targets(self, test_run_id: int) -> Optional[TestRun]:
        """Get test run with eager-loaded targets."""
        stmt = (
            select(TestRunORM)
            .where(TestRunORM.id == test_run_id)
            .options(selectinload(TestRunORM.targets))
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        return self._orm_to_model(orm)

    async def update(
        self,
        test_run_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        req_loadprofile: Optional[list[LoadProfile]] = None,
        warmup_sec: Optional[int] = None,
        measured_sec: Optional[int] = None,
        analysis_trim_sec: Optional[int] = None,
        repetitions: Optional[int] = None,
    ) -> Optional[TestRun]:
        """Update a test run."""
        stmt = select(TestRunORM).where(TestRunORM.id == test_run_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if orm is None:
            return None

        if name is not None:
            orm.name = name
        if description is not None:
            orm.description = description
        if req_loadprofile is not None:
            orm.req_loadprofile = [lp.value for lp in req_loadprofile]
        if warmup_sec is not None:
            orm.warmup_sec = warmup_sec
        if measured_sec is not None:
            orm.measured_sec = measured_sec
        if analysis_trim_sec is not None:
            orm.analysis_trim_sec = analysis_trim_sec
        if repetitions is not None:
            orm.repetitions = repetitions

        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)


class TestRunTargetRepository(BaseRepository[TestRunTargetORM, TestRunTarget]):
    """Repository for TestRunTarget CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, TestRunTargetORM)

    def _orm_to_model(self, orm: TestRunTargetORM) -> TestRunTarget:
        """Convert TestRunTargetORM to TestRunTarget application model."""
        return TestRunTarget(
            id=orm.id,
            test_run_id=orm.test_run_id,
            target_id=orm.target_id,
            loadgenerator_id=orm.loadgenerator_id,
            jmeter_port=orm.jmeter_port,
            jmx_file_path=orm.jmx_file_path,
            base_baseline_id=orm.base_baseline_id,
            initial_baseline_id=orm.initial_baseline_id,
            upgrade_baseline_id=orm.upgrade_baseline_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(
        self,
        test_run_id: int,
        target_id: int,
        loadgenerator_id: int,
        jmeter_port: Optional[int] = None,
        jmx_file_path: Optional[str] = None,
        base_baseline_id: Optional[int] = None,
        initial_baseline_id: Optional[int] = None,
        upgrade_baseline_id: Optional[int] = None,
    ) -> TestRunTarget:
        """Create a new test run target association."""
        orm = TestRunTargetORM(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgenerator_id,
            jmeter_port=jmeter_port,
            jmx_file_path=jmx_file_path,
            base_baseline_id=base_baseline_id,
            initial_baseline_id=initial_baseline_id,
            upgrade_baseline_id=upgrade_baseline_id,
        )

        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)

        return self._orm_to_model(orm)

    async def get_by_test_run_id(self, test_run_id: int) -> list[TestRunTarget]:
        """Get all targets for a test run."""
        stmt = (
            select(TestRunTargetORM)
            .where(TestRunTargetORM.test_run_id == test_run_id)
            .order_by(TestRunTargetORM.id)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def get_by_target_id(self, target_id: int) -> list[TestRunTarget]:
        """Get all test run associations for a target."""
        stmt = (
            select(TestRunTargetORM)
            .where(TestRunTargetORM.target_id == target_id)
            .order_by(TestRunTargetORM.test_run_id)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        return [self._orm_to_model(orm) for orm in orms]

    async def delete_by_test_run_id(self, test_run_id: int) -> int:
        """Delete all targets for a test run. Returns count deleted."""
        stmt = select(TestRunTargetORM).where(
            TestRunTargetORM.test_run_id == test_run_id
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()

        count = len(orms)
        for orm in orms:
            await self._session.delete(orm)

        await self._session.flush()
        return count
