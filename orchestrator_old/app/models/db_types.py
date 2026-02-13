"""Database-agnostic type definitions.

Provides types that work across PostgreSQL and SQL Server:
- JsonType: JSONB on PostgreSQL, NVARCHAR(MAX) on SQL Server
- ArrayType: ARRAY on PostgreSQL, NVARCHAR(MAX) JSON on SQL Server
- GuidType: UUID on PostgreSQL, UNIQUEIDENTIFIER on SQL Server
"""

import json
import uuid
from typing import Any, Optional

from sqlalchemy import String, Text, TypeDecorator
from sqlalchemy.dialects import postgresql, mssql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import CHAR


class JsonType(TypeDecorator):
    """Database-agnostic JSON type.

    - PostgreSQL: Uses native JSONB for indexing and querying
    - SQL Server: Uses NVARCHAR(MAX) with JSON serialization
    - SQLite: Uses TEXT with JSON serialization
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        elif dialect.name == "mssql":
            return dialect.type_descriptor(String(length=None))  # NVARCHAR(MAX)
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[str]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL handles JSON natively
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL returns dict directly
        if isinstance(value, str):
            return json.loads(value)
        return value


class ArrayOfStrings(TypeDecorator):
    """Database-agnostic array of strings type.

    - PostgreSQL: Uses native ARRAY(String)
    - SQL Server: Uses NVARCHAR(MAX) with JSON array serialization
    - SQLite: Uses TEXT with JSON array serialization
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(String(50)))
        elif dialect.name == "mssql":
            return dialect.type_descriptor(String(length=None))  # NVARCHAR(MAX)
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[str]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL handles arrays natively
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL returns list directly
        if isinstance(value, str):
            return json.loads(value)
        return value


class ArrayOfIntegers(TypeDecorator):
    """Database-agnostic array of integers type.

    - PostgreSQL: Uses native ARRAY(Integer)
    - SQL Server: Uses NVARCHAR(MAX) with JSON array serialization
    - SQLite: Uses TEXT with JSON array serialization
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            from sqlalchemy import Integer
            return dialect.type_descriptor(postgresql.ARRAY(Integer))
        elif dialect.name == "mssql":
            return dialect.type_descriptor(String(length=None))  # NVARCHAR(MAX)
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[str]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL handles arrays natively
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # PostgreSQL returns list directly
        if isinstance(value, str):
            return json.loads(value)
        return value


class GuidType(TypeDecorator):
    """Database-agnostic UUID/GUID type.

    - PostgreSQL: Uses native UUID type
    - SQL Server: Uses UNIQUEIDENTIFIER
    - SQLite: Uses CHAR(36) with string representation
    """

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        elif dialect.name == "mssql":
            return dialect.type_descriptor(mssql.UNIQUEIDENTIFIER())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[str]:
        if value is None:
            return None
        if dialect.name in ("postgresql", "mssql"):
            return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        # SQLite - store as string
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Optional[uuid.UUID]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
