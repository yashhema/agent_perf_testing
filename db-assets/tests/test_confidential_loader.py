"""Tests for the ConfidentialDataLoader."""

import pytest
from pathlib import Path

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from generator.loaders.confidential_loader import ConfidentialDataLoader


class TestConfidentialDataLoader:
    """Tests for ConfidentialDataLoader class."""

    @pytest.fixture
    def data_dir(self):
        """Get the ConfidentialData directory path."""
        # Navigate from tests/ to ConfidentialData/
        base = Path(__file__).parent.parent.parent
        return base / "ConfidentialData"

    def test_loader_initialization(self, data_dir):
        """Test loader can be initialized."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        assert loader is not None
        assert loader.data_dir == data_dir

    def test_loader_load(self, data_dir):
        """Test loader can load Excel files."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        assert loader.total_records > 0
        print(f"Loaded {loader.total_records} records")

    def test_loader_columns(self, data_dir):
        """Test loader has expected columns."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        expected_columns = ['FIRSTNAME', 'LASTNAME', 'EMAIL', 'SSN', 'CCNO']
        for col in expected_columns:
            assert col in loader.columns, f"Missing column: {col}"

    def test_get_next(self, data_dir):
        """Test get_next returns records."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        record = loader.get_next()
        assert record is not None
        assert 'FIRSTNAME' in record
        assert 'LASTNAME' in record

    def test_get_random(self, data_dir):
        """Test get_random returns records."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        record = loader.get_random()
        assert record is not None
        assert 'FIRSTNAME' in record

    def test_get_batch(self, data_dir):
        """Test get_batch returns correct number of records."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        batch = loader.get_batch(10)
        assert len(batch) == 10

    def test_get_column_values(self, data_dir):
        """Test get_column_values returns values."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir))
        loader.load()

        values = loader.get_column_values('FIRSTNAME', 5)
        assert len(values) == 5

    def test_cycling(self, data_dir):
        """Test that get_next cycles through records."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir), shuffle=False)
        loader.load()

        first_record = loader.get_next()

        # Cycle through all records
        for _ in range(loader.total_records - 1):
            loader.get_next()

        # Should be back at first
        cycled_record = loader.get_next()
        assert cycled_record == first_record

    def test_reset(self, data_dir):
        """Test reset functionality."""
        if not data_dir.exists():
            pytest.skip("ConfidentialData directory not found")

        loader = ConfidentialDataLoader(str(data_dir), shuffle=False)
        loader.load()

        first_record = loader.get_next()
        loader.get_next()  # Move forward
        loader.reset()

        reset_record = loader.get_next()
        assert reset_record == first_record


class TestConfidentialDataLoaderErrors:
    """Tests for error handling in ConfidentialDataLoader."""

    def test_missing_directory(self):
        """Test error when directory doesn't exist."""
        loader = ConfidentialDataLoader("/nonexistent/path")

        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_invalid_column(self, tmp_path):
        """Test error when requesting invalid column."""
        # Create a minimal loader that's been loaded
        loader = ConfidentialDataLoader(str(tmp_path))
        loader._data = None  # Will cause error on column access

        with pytest.raises(Exception):
            loader.get_column_values('INVALID_COLUMN', 5)
