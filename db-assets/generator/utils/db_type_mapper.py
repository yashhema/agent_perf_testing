"""Database Type Mapper using SQLAlchemy Dialects.

Maps canonical SQLAlchemy types to vendor-specific SQL type strings.
This ensures DDL params generated for JMeter use correct database-specific types.
"""

import re
from typing import Dict, List, Type
from sqlalchemy import Integer, String, Text, Boolean, Float, DateTime, Numeric
from sqlalchemy.types import TypeEngine
from sqlalchemy.dialects import postgresql, mssql, oracle


# SQLAlchemy dialect mapping
DIALECTS = {
    'postgresql': postgresql.dialect(),
    'mssql': mssql.dialect(),
    'oracle': oracle.dialect(),
    'db2': postgresql.dialect(),  # DB2 uses similar types to PostgreSQL
}

# Canonical types for DDL testing - using SQLAlchemy type objects
# NOTE: Avoid types with commas in their definition (e.g., NUMERIC(10,2))
# as they cause CSV parsing issues in JMeter. Use FLOAT instead.
CANONICAL_TYPES: List[TypeEngine] = [
    String(100),
    Integer(),
    Float(),
    Text(),
    Boolean(),
    DateTime(),
]


def compile_type(sa_type: TypeEngine, db_type: str) -> str:
    """Compile a SQLAlchemy type to a vendor-specific SQL string.

    Args:
        sa_type: SQLAlchemy type object (e.g., Integer(), String(100))
        db_type: Database type ('postgresql', 'mssql', 'oracle', 'db2')

    Returns:
        Vendor-specific SQL type string (e.g., 'INT', 'NVARCHAR(100)')
    """
    dialect = DIALECTS.get(db_type)
    if not dialect:
        raise ValueError(f"Unsupported database type: {db_type}")

    # Compile the type using the dialect
    compiled = str(sa_type.compile(dialect=dialect))

    # Remove spaces inside parentheses to avoid SQL parsing issues
    # e.g., "NUMERIC(10, 2)" -> "NUMERIC(10,2)"
    compiled = re.sub(r'\(\s*', '(', compiled)  # Remove space after (
    compiled = re.sub(r'\s*\)', ')', compiled)  # Remove space before )
    compiled = re.sub(r',\s+', ',', compiled)   # Remove space after comma

    return compiled


def get_ddl_types(db_type: str) -> List[str]:
    """Get list of vendor-specific DDL types for a database.

    Args:
        db_type: Database type ('postgresql', 'mssql', 'oracle', 'db2')

    Returns:
        List of vendor-specific SQL type strings
    """
    return [compile_type(t, db_type) for t in CANONICAL_TYPES]


def get_type_mapping(db_type: str) -> Dict[str, str]:
    """Get mapping of canonical type names to vendor-specific types.

    Args:
        db_type: Database type ('postgresql', 'mssql', 'oracle', 'db2')

    Returns:
        Dictionary mapping canonical names to vendor-specific strings
    """
    mapping = {}
    for sa_type in CANONICAL_TYPES:
        canonical_name = type(sa_type).__name__
        if hasattr(sa_type, 'length') and sa_type.length:
            canonical_name = f"{canonical_name}({sa_type.length})"
        elif hasattr(sa_type, 'precision') and sa_type.precision:
            canonical_name = f"{canonical_name}({sa_type.precision},{sa_type.scale})"

        mapping[canonical_name] = compile_type(sa_type, db_type)

    return mapping


# Pre-compiled type lists for each database (for performance)
DDL_TYPES_BY_DB: Dict[str, List[str]] = {}


def get_cached_ddl_types(db_type: str) -> List[str]:
    """Get cached list of DDL types for a database.

    Args:
        db_type: Database type

    Returns:
        List of vendor-specific SQL type strings
    """
    if db_type not in DDL_TYPES_BY_DB:
        DDL_TYPES_BY_DB[db_type] = get_ddl_types(db_type)
    return DDL_TYPES_BY_DB[db_type]


if __name__ == '__main__':
    # Demo: Show type mappings for all databases
    print("SQLAlchemy Type Mappings by Database:\n")
    print(f"{'Canonical':<20} {'PostgreSQL':<20} {'MSSQL':<20} {'Oracle':<20}")
    print("-" * 80)

    for sa_type in CANONICAL_TYPES:
        canonical = type(sa_type).__name__
        if hasattr(sa_type, 'length') and sa_type.length:
            canonical = f"{canonical}({sa_type.length})"
        elif hasattr(sa_type, 'precision') and sa_type.precision:
            canonical = f"{canonical}({sa_type.precision},{sa_type.scale})"

        pg = compile_type(sa_type, 'postgresql')
        ms = compile_type(sa_type, 'mssql')
        ora = compile_type(sa_type, 'oracle')

        print(f"{canonical:<20} {pg:<20} {ms:<20} {ora:<20}")
