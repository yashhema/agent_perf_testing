"""Service layer for TestRun operations."""

from typing import Optional

from app.models.application import TestRun, TestRunTarget, LoadProfile
from app.repositories.test_run_repository import TestRunRepository, TestRunTargetRepository
from app.repositories.lab_repository import LabRepository
from app.repositories.server_repository import ServerRepository
from app.repositories.baseline_repository import BaselineRepository


class TestRunService:
    """Service for TestRun business logic."""

    def __init__(
        self,
        repository: TestRunRepository,
        target_repository: TestRunTargetRepository,
        lab_repository: LabRepository,
        server_repository: ServerRepository,
        baseline_repository: BaselineRepository,
    ):
        self._repo = repository
        self._target_repo = target_repository
        self._lab_repo = lab_repository
        self._server_repo = server_repository
        self._baseline_repo = baseline_repository

    async def create_test_run(
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
        """
        Create a new test run.

        Args:
            name: Test run name.
            lab_id: ID of the lab.
            req_loadprofile: List of load profiles to run.
            loadgenerator_package_grpid_lst: List of load generator package group IDs.
            description: Optional description.
            warmup_sec: Warmup duration in seconds.
            measured_sec: Measured duration in seconds.
            analysis_trim_sec: Analysis trim duration in seconds.
            repetitions: Number of repetitions.

        Returns:
            The created TestRun.

        Raises:
            ValueError: If the lab doesn't exist.
        """
        # Verify lab exists
        lab = await self._lab_repo.get_by_id(lab_id)
        if lab is None:
            raise ValueError(f"Lab with ID {lab_id} not found")

        return await self._repo.create(
            name=name,
            lab_id=lab_id,
            req_loadprofile=req_loadprofile,
            loadgenerator_package_grpid_lst=loadgenerator_package_grpid_lst,
            description=description,
            warmup_sec=warmup_sec,
            measured_sec=measured_sec,
            analysis_trim_sec=analysis_trim_sec,
            repetitions=repetitions,
        )

    async def get_test_run(self, test_run_id: int) -> Optional[TestRun]:
        """Get a test run by ID."""
        return await self._repo.get_by_id(test_run_id)

    async def get_test_run_with_targets(self, test_run_id: int) -> Optional[TestRun]:
        """Get a test run with eager-loaded targets."""
        return await self._repo.get_with_targets(test_run_id)

    async def list_test_runs(self, lab_id: int) -> list[TestRun]:
        """List all test runs in a lab."""
        return await self._repo.get_by_lab_id(lab_id)

    async def update_test_run(
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
        return await self._repo.update(
            test_run_id=test_run_id,
            name=name,
            description=description,
            req_loadprofile=req_loadprofile,
            warmup_sec=warmup_sec,
            measured_sec=measured_sec,
            analysis_trim_sec=analysis_trim_sec,
            repetitions=repetitions,
        )

    async def delete_test_run(self, test_run_id: int) -> bool:
        """Delete a test run and all its targets."""
        # Delete targets first
        await self._target_repo.delete_by_test_run_id(test_run_id)
        return await self._repo.delete_by_id(test_run_id)

    # ============================================================
    # Test Run Target Operations
    # ============================================================

    async def add_target(
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
        """
        Add a target to a test run.

        Args:
            test_run_id: The test run ID.
            target_id: The target server ID.
            loadgenerator_id: The load generator server ID.
            jmeter_port: Optional JMeter port.
            jmx_file_path: Optional JMX file path.
            base_baseline_id: Optional base baseline ID.
            initial_baseline_id: Optional initial baseline ID.
            upgrade_baseline_id: Optional upgrade baseline ID.

        Returns:
            The created TestRunTarget.

        Raises:
            ValueError: If test run, target, or load generator doesn't exist.
        """
        # Verify test run exists
        test_run = await self._repo.get_by_id(test_run_id)
        if test_run is None:
            raise ValueError(f"Test run with ID {test_run_id} not found")

        # Verify target server exists
        target = await self._server_repo.get_by_id(target_id)
        if target is None:
            raise ValueError(f"Target server with ID {target_id} not found")

        # Verify load generator exists
        loadgen = await self._server_repo.get_by_id(loadgenerator_id)
        if loadgen is None:
            raise ValueError(f"Load generator with ID {loadgenerator_id} not found")

        # Verify baselines exist if provided
        if base_baseline_id is not None:
            baseline = await self._baseline_repo.get_by_id(base_baseline_id)
            if baseline is None:
                raise ValueError(f"Base baseline with ID {base_baseline_id} not found")

        if initial_baseline_id is not None:
            baseline = await self._baseline_repo.get_by_id(initial_baseline_id)
            if baseline is None:
                raise ValueError(f"Initial baseline with ID {initial_baseline_id} not found")

        if upgrade_baseline_id is not None:
            baseline = await self._baseline_repo.get_by_id(upgrade_baseline_id)
            if baseline is None:
                raise ValueError(f"Upgrade baseline with ID {upgrade_baseline_id} not found")

        return await self._target_repo.create(
            test_run_id=test_run_id,
            target_id=target_id,
            loadgenerator_id=loadgenerator_id,
            jmeter_port=jmeter_port,
            jmx_file_path=jmx_file_path,
            base_baseline_id=base_baseline_id,
            initial_baseline_id=initial_baseline_id,
            upgrade_baseline_id=upgrade_baseline_id,
        )

    async def get_targets(self, test_run_id: int) -> list[TestRunTarget]:
        """Get all targets for a test run."""
        return await self._target_repo.get_by_test_run_id(test_run_id)

    async def remove_target(self, target_id: int) -> bool:
        """Remove a target from a test run."""
        return await self._target_repo.delete_by_id(target_id)

    async def remove_all_targets(self, test_run_id: int) -> int:
        """Remove all targets from a test run. Returns count deleted."""
        return await self._target_repo.delete_by_test_run_id(test_run_id)
