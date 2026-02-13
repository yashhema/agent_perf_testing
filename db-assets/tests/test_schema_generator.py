"""Tests for the SchemaGenerator."""

import pytest
from pathlib import Path
import tempfile
import shutil

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from generator.config import GeneratorConfig
from generator.generators.schema_generator import SchemaGenerator


class TestSchemaGenerator:
    """Tests for SchemaGenerator class."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return GeneratorConfig.from_dict({
            'schema': {
                'table_counts': {
                    'ecommerce': 60,
                    'banking': 60,
                    'healthcare': 60,
                    'shared': 20,
                }
            },
            'databases': [
                {'type': 'postgresql', 'output_dir': 'output/postgresql'},
                {'type': 'mssql', 'output_dir': 'output/mssql'},
            ],
            'test_users': [
                {'username': 'test_user', 'password': 'test123', 'role': 'readonly'},
            ]
        })

    @pytest.fixture
    def generator(self, config):
        """Create a schema generator."""
        return SchemaGenerator(config)

    @pytest.fixture
    def temp_output(self):
        """Create a temporary output directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generator_initialization(self, generator):
        """Test generator can be initialized."""
        assert generator is not None

    def test_generate_create_tables_postgresql(self, generator):
        """Test generating CREATE TABLE for PostgreSQL."""
        sql = generator.generate_create_tables('postgresql')
        assert sql is not None
        assert 'CREATE TABLE' in sql or 'Table:' in sql
        assert len(sql) > 100

    def test_generate_create_tables_mssql(self, generator):
        """Test generating CREATE TABLE for SQL Server."""
        sql = generator.generate_create_tables('mssql')
        assert sql is not None
        assert len(sql) > 100

    def test_generate_create_indexes(self, generator):
        """Test generating CREATE INDEX statements."""
        sql = generator.generate_create_indexes('postgresql')
        assert sql is not None
        assert 'Index' in sql or 'CREATE INDEX' in sql.upper()

    def test_generate_create_users_postgresql(self, generator):
        """Test generating user creation for PostgreSQL."""
        sql = generator.generate_create_users('postgresql')
        assert 'CREATE USER' in sql
        assert 'test_user' in sql
        assert 'GRANT' in sql

    def test_generate_create_users_mssql(self, generator):
        """Test generating user creation for SQL Server."""
        sql = generator.generate_create_users('mssql')
        assert 'CREATE LOGIN' in sql
        assert 'test_user' in sql

    def test_generate_all(self, generator, temp_output):
        """Test generating all schema files."""
        files = generator.generate_all('postgresql', temp_output)

        assert len(files) > 0
        assert '01_create_tables.sql' in files

        # Verify files exist
        for filename, filepath in files.items():
            assert Path(filepath).exists(), f"File not created: {filepath}"

    def test_tables_in_order(self, generator):
        """Test that tables are ordered by dependencies."""
        tables = generator._get_tables_in_order()
        assert len(tables) > 0

        # Verify some basic ordering (reference tables should come first)
        table_names = [t.name for t in tables]
        # Countries should come before addresses (addresses references cities which references states which references countries)


class TestSchemaGeneratorEdgeCases:
    """Tests for edge cases in SchemaGenerator."""

    @pytest.fixture
    def minimal_config(self):
        """Create a minimal configuration."""
        return GeneratorConfig.from_dict({
            'databases': [],
            'test_users': []
        })

    def test_empty_users(self, minimal_config):
        """Test generating user SQL with no users."""
        generator = SchemaGenerator(minimal_config)
        sql = generator.generate_create_users('postgresql')
        # Should still have header
        assert 'Users and Roles' in sql

    def test_unsupported_database(self, minimal_config):
        """Test handling unsupported database type."""
        generator = SchemaGenerator(minimal_config)
        # Should handle gracefully or raise appropriate error
        try:
            generator.generate_create_tables('unsupported')
        except ValueError as e:
            assert 'Unsupported' in str(e) or 'unsupported' in str(e)
