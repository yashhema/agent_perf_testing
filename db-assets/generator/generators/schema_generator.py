"""Schema generator for creating DDL for multiple database types."""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.schema import CreateTable, CreateIndex, AddConstraint
from sqlalchemy.engine import Engine

from ..models.base import Base
from ..models import shared, ecommerce, banking, healthcare
from ..config import GeneratorConfig


# Fixed database name for agent performance testing
DATABASE_NAME = 'agent_performance_measurement'

# Database dialect configurations
DIALECT_CONFIG = {
    'postgresql': {
        'dialect': 'postgresql',
        'driver': 'psycopg2',
        'placeholder': '%s',
    },
    'mssql': {
        'dialect': 'mssql',
        'driver': 'pyodbc',
        'placeholder': '?',
    },
    'oracle': {
        'dialect': 'oracle',
        'driver': 'oracledb',
        'placeholder': ':1',
    },
    'db2': {
        'dialect': 'db2',
        'driver': 'ibm_db_sa',
        'placeholder': '?',
    },
}


class SchemaGenerator:
    """Generate database schema DDL for multiple database types."""

    def __init__(self, config: GeneratorConfig):
        """Initialize the schema generator.

        Args:
            config: Generator configuration
        """
        self.config = config
        self._ensure_models_imported()

    def _ensure_models_imported(self):
        """Ensure all model modules are imported to register with Base."""
        # Models are already imported at module level
        pass

    def _get_mock_engine(self, db_type: str) -> Engine:
        """Create a mock engine for DDL generation.

        Args:
            db_type: Database type (postgresql, mssql, oracle, db2)

        Returns:
            SQLAlchemy engine
        """
        dialect_info = DIALECT_CONFIG.get(db_type)
        if not dialect_info:
            raise ValueError(f"Unsupported database type: {db_type}")

        # Use SQLite as a mock since we just need dialect compilation
        if db_type == 'postgresql':
            url = 'postgresql://'
        elif db_type == 'mssql':
            url = 'mssql+pyodbc://'
        elif db_type == 'oracle':
            url = 'oracle+oracledb://'
        elif db_type == 'db2':
            # DB2 dialect may not be available, fallback
            url = 'postgresql://'
        else:
            url = 'sqlite://'

        try:
            engine = create_engine(url, strategy='mock', executor=lambda *a, **kw: None)
        except Exception:
            # Fallback to SQLite for DDL generation
            engine = create_engine('sqlite://')

        return engine

    def _compile_ddl(self, ddl, engine: Engine) -> str:
        """Compile DDL statement for specific dialect.

        Args:
            ddl: DDL clause
            engine: SQLAlchemy engine

        Returns:
            Compiled SQL string
        """
        try:
            compiled = ddl.compile(dialect=engine.dialect)
            return str(compiled) + ";"
        except Exception as e:
            # Fallback: return a generic representation
            return str(ddl) + ";"

    def _strip_constraints_from_create_table(self, sql: str) -> str:
        """Remove UNIQUE and FOREIGN KEY constraints from CREATE TABLE SQL.

        For performance testing databases, we only keep PRIMARY KEY constraints.
        This post-processes the SQL to remove:
        - UNIQUE constraints (inline and named)
        - FOREIGN KEY constraints
        - REFERENCES clauses

        Args:
            sql: CREATE TABLE SQL statement

        Returns:
            SQL with constraints stripped
        """
        import re

        lines = sql.split('\n')
        filtered_lines = []
        skip_next_comma = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Skip lines that are UNIQUE or FOREIGN KEY constraints
            if stripped.startswith('UNIQUE (') or stripped.startswith('UNIQUE('):
                skip_next_comma = True
                continue
            if stripped.startswith('FOREIGN KEY'):
                skip_next_comma = True
                continue
            if 'CONSTRAINT ' in stripped and ' UNIQUE ' in stripped:
                skip_next_comma = True
                continue
            if 'CONSTRAINT ' in stripped and ' FOREIGN KEY ' in stripped:
                skip_next_comma = True
                continue
            # Skip lines that are just "UNIQUE (column_name)" within constraint definitions
            if re.match(r'^UNIQUE\s*\(', stripped):
                skip_next_comma = True
                continue

            # Handle trailing commas on the previous line if we skipped a constraint
            if skip_next_comma and filtered_lines:
                # Remove trailing comma from the previous line
                prev_line = filtered_lines[-1]
                if prev_line.rstrip().endswith(','):
                    filtered_lines[-1] = prev_line.rstrip()[:-1]
                skip_next_comma = False

            # Add this line
            filtered_lines.append(line)

        # Join and clean up any double blank lines
        result = '\n'.join(filtered_lines)

        # Also need to handle commas before PRIMARY KEY if we removed constraints
        # Pattern: "column_def, \n\tUNIQUE (...), \n\tPRIMARY KEY" -> "column_def, \n\tPRIMARY KEY"
        # This is handled by the logic above

        # Final cleanup: remove trailing comma before closing paren
        result = re.sub(r',\s*\n\s*\)', '\n)', result)

        return result

    def generate_create_database(self, db_type: str) -> str:
        """Generate DROP/CREATE DATABASE statements.

        This should be run FIRST before any other schema scripts.
        Database name is fixed as: agent_performance_measurement

        Args:
            db_type: Database type

        Returns:
            SQL string with database creation statements
        """
        statements = []
        db_name = DATABASE_NAME

        statements.append(f"-- ============================================================")
        statements.append(f"-- Database Creation Script for {db_type.upper()}")
        statements.append(f"-- Database: {db_name}")
        statements.append(f"-- ============================================================")
        statements.append(f"-- IMPORTANT: Run this script FIRST, connected to master/postgres")
        statements.append(f"-- This will DROP the existing database if it exists!")
        statements.append(f"-- ============================================================")
        statements.append("")

        if db_type == 'postgresql':
            statements.append(f"-- Terminate existing connections")
            statements.append(f"SELECT pg_terminate_backend(pg_stat_activity.pid)")
            statements.append(f"FROM pg_stat_activity")
            statements.append(f"WHERE pg_stat_activity.datname = '{db_name}'")
            statements.append(f"  AND pid <> pg_backend_pid();")
            statements.append("")
            statements.append(f"-- Drop database if exists")
            statements.append(f"DROP DATABASE IF EXISTS {db_name};")
            statements.append("")
            statements.append(f"-- Create database")
            statements.append(f"CREATE DATABASE {db_name}")
            statements.append(f"    WITH ENCODING = 'UTF8'")
            statements.append(f"    LC_COLLATE = 'en_US.UTF-8'")
            statements.append(f"    LC_CTYPE = 'en_US.UTF-8';")
            statements.append("")
            statements.append(f"-- Connect to the new database")
            statements.append(f"\\c {db_name}")

        elif db_type == 'mssql':
            statements.append(f"-- Switch to master database")
            statements.append(f"USE master;")
            statements.append(f"GO")
            statements.append("")
            statements.append(f"-- Drop database if exists (with single user mode to close connections)")
            statements.append(f"IF EXISTS (SELECT name FROM sys.databases WHERE name = N'{db_name}')")
            statements.append(f"BEGIN")
            statements.append(f"    ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;")
            statements.append(f"    DROP DATABASE [{db_name}];")
            statements.append(f"END")
            statements.append(f"GO")
            statements.append("")
            statements.append(f"-- Create database")
            statements.append(f"CREATE DATABASE [{db_name}];")
            statements.append(f"GO")
            statements.append("")
            statements.append(f"-- Switch to the new database")
            statements.append(f"USE [{db_name}];")
            statements.append(f"GO")

        elif db_type == 'oracle':
            statements.append(f"-- Oracle: Drop and create user/schema")
            statements.append(f"-- Run as SYSDBA")
            statements.append("")
            statements.append(f"-- Drop user if exists")
            statements.append(f"BEGIN")
            statements.append(f"    EXECUTE IMMEDIATE 'DROP USER {db_name} CASCADE';")
            statements.append(f"EXCEPTION")
            statements.append(f"    WHEN OTHERS THEN")
            statements.append(f"        IF SQLCODE != -1918 THEN RAISE; END IF;")
            statements.append(f"END;")
            statements.append(f"/")
            statements.append("")
            statements.append(f"-- Create user/schema")
            statements.append(f"CREATE USER {db_name} IDENTIFIED BY {db_name}_pwd")
            statements.append(f"    DEFAULT TABLESPACE users")
            statements.append(f"    TEMPORARY TABLESPACE temp")
            statements.append(f"    QUOTA UNLIMITED ON users;")
            statements.append("")
            statements.append(f"GRANT CONNECT, RESOURCE, DBA TO {db_name};")
            statements.append("")
            statements.append(f"-- Connect as the new user")
            statements.append(f"CONNECT {db_name}/{db_name}_pwd")

        elif db_type == 'db2':
            statements.append(f"-- DB2: Drop and create database")
            statements.append(f"-- Run from DB2 command line")
            statements.append("")
            statements.append(f"-- Force applications off and drop database")
            statements.append(f"CONNECT RESET;")
            statements.append(f"FORCE APPLICATION ALL;")
            statements.append(f"DROP DATABASE {db_name};")
            statements.append("")
            statements.append(f"-- Create database")
            statements.append(f"CREATE DATABASE {db_name}")
            statements.append(f"    AUTOMATIC STORAGE YES")
            statements.append(f"    USING CODESET UTF-8")
            statements.append(f"    TERRITORY US;")
            statements.append("")
            statements.append(f"-- Connect to the new database")
            statements.append(f"CONNECT TO {db_name};")

        statements.append("")
        statements.append(f"-- ============================================================")
        statements.append(f"-- Database '{db_name}' is ready. Run the following scripts next:")
        statements.append(f"-- 1. 01_create_tables.sql")
        statements.append(f"-- 2. 02_create_indexes.sql")
        statements.append(f"-- 3. 03_create_constraints.sql")
        statements.append(f"-- 4. 04_create_users.sql")
        statements.append(f"-- 5. seed/seed_data.sql")
        statements.append(f"-- ============================================================")

        return "\n".join(statements)

    def generate_create_tables(self, db_type: str) -> str:
        """Generate CREATE TABLE statements.

        NOTE: For performance testing databases, UNIQUE and FOREIGN KEY constraints
        are stripped from the CREATE TABLE statements. Only PRIMARY KEY is kept.

        Args:
            db_type: Database type

        Returns:
            SQL string with all CREATE TABLE statements
        """
        engine = self._get_mock_engine(db_type)
        statements = []

        # Add header
        statements.append(f"-- Database Schema for {db_type.upper()}")
        statements.append(f"-- Generated by Database Schema Generator")
        statements.append(f"-- Total Tables: {len(Base.metadata.tables)}")
        statements.append(f"--")
        statements.append(f"-- NOTE: UNIQUE and FOREIGN KEY constraints have been removed")
        statements.append(f"-- for performance testing. Only PRIMARY KEY constraints are kept.")
        statements.append("")

        # Get tables in dependency order
        tables = self._get_tables_in_order()

        for table in tables:
            try:
                create_stmt = CreateTable(table)
                sql = self._compile_ddl(create_stmt, engine)
                # Strip UNIQUE and FK constraints for performance testing
                sql = self._strip_constraints_from_create_table(sql)
                statements.append(f"-- Table: {table.name}")
                statements.append(sql)
                statements.append("")
            except Exception as e:
                statements.append(f"-- Error generating table {table.name}: {e}")
                statements.append("")

        return "\n".join(statements)

    def generate_create_indexes(self, db_type: str) -> str:
        """Generate CREATE INDEX statements.

        Args:
            db_type: Database type

        Returns:
            SQL string with all CREATE INDEX statements
        """
        engine = self._get_mock_engine(db_type)
        statements = []

        statements.append(f"-- Indexes for {db_type.upper()}")
        statements.append("")

        for table in Base.metadata.tables.values():
            for index in table.indexes:
                try:
                    create_stmt = CreateIndex(index)
                    sql = self._compile_ddl(create_stmt, engine)
                    statements.append(f"-- Index: {index.name} on {table.name}")
                    statements.append(sql)
                    statements.append("")
                except Exception as e:
                    statements.append(f"-- Error generating index {index.name}: {e}")
                    statements.append("")

        return "\n".join(statements)

    def generate_create_constraints(self, db_type: str) -> str:
        """Generate ALTER TABLE statements for constraints.

        NOTE: For performance testing databases, FK and UNIQUE constraints are NOT created.
        This simplifies data generation and avoids constraint violations during load testing.
        Only PRIMARY KEY constraints (defined in CREATE TABLE) and INDEXES are used.

        Args:
            db_type: Database type

        Returns:
            SQL string with constraint explanation (no actual constraints)
        """
        statements = []

        statements.append(f"-- ============================================================")
        statements.append(f"-- Constraints for {db_type.upper()}")
        statements.append(f"-- ============================================================")
        statements.append(f"--")
        statements.append(f"-- NOTE: Foreign Key and Unique constraints are INTENTIONALLY OMITTED")
        statements.append(f"-- for this performance testing database.")
        statements.append(f"--")
        statements.append(f"-- Reasons:")
        statements.append(f"-- 1. FK constraints complicate seed data generation order")
        statements.append(f"-- 2. UNIQUE constraints prevent random data generation")
        statements.append(f"-- 3. Neither is needed for query performance testing")
        statements.append(f"--")
        statements.append(f"-- The following constraints ARE in place:")
        statements.append(f"-- - PRIMARY KEY constraints (for row identification)")
        statements.append(f"-- - INDEXES (for query performance - see 02_create_indexes.sql)")
        statements.append(f"--")
        statements.append(f"-- ============================================================")
        statements.append(f"")
        statements.append(f"-- No constraints to add. This file is intentionally minimal.")
        statements.append(f"")

        return "\n".join(statements)

    def generate_create_users(self, db_type: str) -> str:
        """Generate CREATE USER/ROLE statements.

        Args:
            db_type: Database type

        Returns:
            SQL string with user creation statements
        """
        statements = []

        statements.append(f"-- Users and Roles for {db_type.upper()}")
        statements.append("")

        for user in self.config.test_users:
            if db_type == 'postgresql':
                statements.append(f"CREATE USER {user.username} WITH PASSWORD '{user.password}';")
                if user.role == 'readonly':
                    statements.append(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user.username};")
                elif user.role == 'readwrite':
                    statements.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {user.username};")
                elif user.role == 'admin':
                    statements.append(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {user.username};")

            elif db_type == 'mssql':
                statements.append(f"CREATE LOGIN [{user.username}] WITH PASSWORD = '{user.password}';")
                statements.append(f"CREATE USER [{user.username}] FOR LOGIN [{user.username}];")
                if user.role == 'readonly':
                    statements.append(f"ALTER ROLE db_datareader ADD MEMBER [{user.username}];")
                elif user.role == 'readwrite':
                    statements.append(f"ALTER ROLE db_datareader ADD MEMBER [{user.username}];")
                    statements.append(f"ALTER ROLE db_datawriter ADD MEMBER [{user.username}];")
                elif user.role == 'admin':
                    statements.append(f"ALTER ROLE db_owner ADD MEMBER [{user.username}];")

            elif db_type == 'oracle':
                statements.append(f"CREATE USER {user.username} IDENTIFIED BY \"{user.password}\";")
                statements.append(f"GRANT CONNECT TO {user.username};")
                if user.role == 'readonly':
                    statements.append(f"GRANT SELECT ANY TABLE TO {user.username};")
                elif user.role == 'readwrite':
                    statements.append(f"GRANT SELECT ANY TABLE, INSERT ANY TABLE, UPDATE ANY TABLE, DELETE ANY TABLE TO {user.username};")
                elif user.role == 'admin':
                    statements.append(f"GRANT DBA TO {user.username};")

            statements.append("")

        return "\n".join(statements)

    def _get_tables_in_order(self) -> List:
        """Get tables ordered by foreign key dependencies.

        Returns:
            List of tables in creation order
        """
        metadata = Base.metadata
        tables = list(metadata.tables.values())

        # Simple topological sort based on foreign keys
        ordered = []
        remaining = set(tables)

        while remaining:
            # Find tables with no unresolved dependencies
            ready = []
            for table in remaining:
                deps = set()
                for fk in table.foreign_key_constraints:
                    if fk.referred_table != table:  # Skip self-references
                        deps.add(fk.referred_table)

                if deps.issubset(set(ordered)):
                    ready.append(table)

            if not ready:
                # Break circular dependencies - just add remaining
                ready = list(remaining)

            for table in ready:
                ordered.append(table)
                remaining.discard(table)

        return ordered

    def generate_all(self, db_type: str, output_dir: str) -> Dict[str, str]:
        """Generate all schema files for a database type.

        Files are numbered in execution order:
        00_create_database.sql - DROP/CREATE database (run FIRST)
        01_create_tables.sql   - CREATE TABLE statements
        02_create_indexes.sql  - CREATE INDEX statements
        03_create_constraints.sql - Foreign key constraints
        04_create_users.sql    - Test users (config users)

        Args:
            db_type: Database type
            output_dir: Output directory path

        Returns:
            Dictionary of file paths to content
        """
        output_path = Path(output_dir)
        schema_path = output_path / "schema"
        schema_path.mkdir(parents=True, exist_ok=True)

        files = {}

        # Create database (FIRST!)
        db_sql = self.generate_create_database(db_type)
        db_file = schema_path / "00_create_database.sql"
        db_file.write_text(db_sql)
        files['00_create_database.sql'] = str(db_file)

        # Create tables
        tables_sql = self.generate_create_tables(db_type)
        tables_file = schema_path / "01_create_tables.sql"
        tables_file.write_text(tables_sql)
        files['01_create_tables.sql'] = str(tables_file)

        # Create indexes
        indexes_sql = self.generate_create_indexes(db_type)
        indexes_file = schema_path / "02_create_indexes.sql"
        indexes_file.write_text(indexes_sql)
        files['02_create_indexes.sql'] = str(indexes_file)

        # Create constraints
        constraints_sql = self.generate_create_constraints(db_type)
        constraints_file = schema_path / "03_create_constraints.sql"
        constraints_file.write_text(constraints_sql)
        files['03_create_constraints.sql'] = str(constraints_file)

        # Create users
        users_sql = self.generate_create_users(db_type)
        users_file = schema_path / "04_create_users.sql"
        users_file.write_text(users_sql)
        files['04_create_users.sql'] = str(users_file)

        print(f"Generated schema for {db_type} in {schema_path}")
        print(f"  Database name: {DATABASE_NAME}")
        return files

    def generate_for_all_databases(self, base_output_dir: str) -> Dict[str, Dict[str, str]]:
        """Generate schemas for all configured databases.

        Args:
            base_output_dir: Base output directory

        Returns:
            Dictionary of db_type -> file paths
        """
        results = {}

        for db_config in self.config.databases:
            output_dir = Path(base_output_dir) / db_config.output_dir
            results[db_config.type] = self.generate_all(db_config.type, str(output_dir))

        return results
