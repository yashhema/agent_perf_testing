"""SQLAlchemy Base and common mixins for all domain models."""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Boolean, func
from sqlalchemy.orm import declarative_base, declared_attr


# Create the declarative base with unmapped annotation support
# This allows using Column return types in mixins without Mapped[] annotations
class _Base:
    """Base class that allows unmapped column annotations for SQLAlchemy 2.0 compatibility."""
    __allow_unmapped__ = True

Base = declarative_base(cls=_Base)


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""
    __allow_unmapped__ = True

    @declared_attr
    def created_at(cls):
        return Column(
            DateTime,
            nullable=False,
            server_default=func.now(),
            comment="Record creation timestamp"
        )

    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime,
            nullable=True,
            onupdate=func.now(),
            comment="Last update timestamp"
        )


class AuditMixin(TimestampMixin):
    """Mixin that adds audit columns (created_by, updated_by, is_active)."""

    @declared_attr
    def created_by(cls):
        return Column(
            String(100),
            nullable=True,
            comment="User who created the record"
        )

    @declared_attr
    def updated_by(cls):
        return Column(
            String(100),
            nullable=True,
            comment="User who last updated the record"
        )

    @declared_attr
    def is_active(cls):
        return Column(
            Boolean,
            nullable=False,
            default=True,
            comment="Whether the record is active"
        )


class SoftDeleteMixin:
    """Mixin that adds soft delete capability."""
    __allow_unmapped__ = True

    @declared_attr
    def is_deleted(cls):
        return Column(
            Boolean,
            nullable=False,
            default=False,
            comment="Whether the record is soft deleted"
        )

    @declared_attr
    def deleted_at(cls):
        return Column(
            DateTime,
            nullable=True,
            comment="Deletion timestamp"
        )

    @declared_attr
    def deleted_by(cls):
        return Column(
            String(100),
            nullable=True,
            comment="User who deleted the record"
        )


def get_all_tables():
    """Get all registered table classes."""
    return Base.metadata.tables


def get_table_names():
    """Get all registered table names."""
    return list(Base.metadata.tables.keys())


def get_table_by_name(name: str):
    """Get table class by name."""
    return Base.metadata.tables.get(name)
