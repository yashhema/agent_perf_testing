"""Service layer for Lab operations."""

from typing import Optional

from app.models.application import Lab
from app.repositories.lab_repository import LabRepository


class LabService:
    """Service for Lab business logic."""

    def __init__(self, repository: LabRepository):
        self._repo = repository

    async def create_lab(
        self,
        name: str,
        lab_type: str,
        description: Optional[str] = None,
    ) -> Lab:
        """
        Create a new lab.

        Args:
            name: Unique name for the lab.
            lab_type: Type of lab ('server' or 'euc').
            description: Optional description.

        Returns:
            The created Lab.

        Raises:
            ValueError: If a lab with the same name already exists.
        """
        # Check for duplicate name
        existing = await self._repo.get_by_name(name)
        if existing is not None:
            raise ValueError(f"Lab with name '{name}' already exists")

        return await self._repo.create(
            name=name,
            lab_type=lab_type,
            description=description,
        )

    async def get_lab(self, lab_id: int) -> Optional[Lab]:
        """
        Get a lab by ID.

        Args:
            lab_id: The lab ID.

        Returns:
            The Lab if found, None otherwise.
        """
        return await self._repo.get_by_id(lab_id)

    async def get_lab_by_name(self, name: str) -> Optional[Lab]:
        """
        Get a lab by name.

        Args:
            name: The lab name.

        Returns:
            The Lab if found, None otherwise.
        """
        return await self._repo.get_by_name(name)

    async def list_labs(self) -> list[Lab]:
        """
        List all labs.

        Returns:
            List of all labs.
        """
        return await self._repo.get_all()

    async def update_lab(
        self,
        lab_id: int,
        name: Optional[str] = None,
        lab_type: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Lab]:
        """
        Update a lab.

        Args:
            lab_id: The lab ID to update.
            name: New name (optional).
            lab_type: New lab type (optional).
            description: New description (optional).

        Returns:
            The updated Lab if found, None otherwise.

        Raises:
            ValueError: If the new name conflicts with an existing lab.
        """
        # Check for duplicate name if changing
        if name is not None:
            existing = await self._repo.get_by_name(name)
            if existing is not None and existing.id != lab_id:
                raise ValueError(f"Lab with name '{name}' already exists")

        return await self._repo.update(
            lab_id=lab_id,
            name=name,
            lab_type=lab_type,
            description=description,
        )

    async def delete_lab(self, lab_id: int) -> bool:
        """
        Delete a lab.

        Args:
            lab_id: The lab ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        return await self._repo.delete_by_id(lab_id)
