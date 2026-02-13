"""Service layer for Baseline operations."""

from typing import Optional

from app.models.application import Baseline, BaselineConfig
from app.models.enums import BaselineType
from app.repositories.baseline_repository import BaselineRepository
from app.repositories.lab_repository import LabRepository


class BaselineService:
    """Service for Baseline business logic."""

    def __init__(
        self,
        repository: BaselineRepository,
        lab_repository: LabRepository,
    ):
        self._repo = repository
        self._lab_repo = lab_repository

    async def create_baseline(
        self,
        name: str,
        baseline_type: BaselineType,
        baseline_conf: BaselineConfig,
        lab_id: int,
        description: Optional[str] = None,
    ) -> Baseline:
        """
        Create a new baseline.

        Args:
            name: Baseline name.
            baseline_type: Type of baseline.
            baseline_conf: Baseline configuration.
            lab_id: ID of the lab this baseline belongs to.
            description: Optional description.

        Returns:
            The created Baseline.

        Raises:
            ValueError: If the lab doesn't exist or name is duplicate in lab.
        """
        # Verify lab exists
        lab = await self._lab_repo.get_by_id(lab_id)
        if lab is None:
            raise ValueError(f"Lab with ID {lab_id} not found")

        # Check for duplicate name in lab
        existing = await self._repo.get_by_name(name, lab_id)
        if existing is not None:
            raise ValueError(
                f"Baseline with name '{name}' already exists in lab {lab_id}"
            )

        return await self._repo.create(
            name=name,
            baseline_type=baseline_type,
            baseline_conf=baseline_conf,
            lab_id=lab_id,
            description=description,
        )

    async def get_baseline(self, baseline_id: int) -> Optional[Baseline]:
        """Get a baseline by ID."""
        return await self._repo.get_by_id(baseline_id)

    async def get_baseline_by_name(
        self,
        name: str,
        lab_id: int,
    ) -> Optional[Baseline]:
        """Get a baseline by name in a lab."""
        return await self._repo.get_by_name(name, lab_id)

    async def list_baselines(self, lab_id: int) -> list[Baseline]:
        """List all baselines in a lab."""
        return await self._repo.get_by_lab_id(lab_id)

    async def list_baselines_by_type(
        self,
        lab_id: int,
        baseline_type: BaselineType,
    ) -> list[Baseline]:
        """List baselines by type in a lab."""
        return await self._repo.get_by_type(lab_id, baseline_type)

    async def update_baseline(
        self,
        baseline_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        baseline_conf: Optional[BaselineConfig] = None,
    ) -> Optional[Baseline]:
        """
        Update a baseline.

        Args:
            baseline_id: The baseline ID to update.
            name: New name (optional).
            description: New description (optional).
            baseline_conf: New configuration (optional).

        Returns:
            The updated Baseline if found, None otherwise.

        Raises:
            ValueError: If the new name conflicts with an existing baseline.
        """
        # Get existing baseline to check lab_id
        existing = await self._repo.get_by_id(baseline_id)
        if existing is None:
            return None

        # Check for duplicate name if changing
        if name is not None:
            name_check = await self._repo.get_by_name(name, existing.lab_id)
            if name_check is not None and name_check.id != baseline_id:
                raise ValueError(
                    f"Baseline with name '{name}' already exists in lab {existing.lab_id}"
                )

        return await self._repo.update(
            baseline_id=baseline_id,
            name=name,
            description=description,
            baseline_conf=baseline_conf,
        )

    async def delete_baseline(self, baseline_id: int) -> bool:
        """Delete a baseline."""
        return await self._repo.delete_by_id(baseline_id)
