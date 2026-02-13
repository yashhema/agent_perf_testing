"""Pytest configuration for db-assets tests."""

import pytest
import sys
from pathlib import Path

# Add generator package to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def package_dir():
    """Get the package directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def confidential_data_dir(package_dir):
    """Get the ConfidentialData directory."""
    return package_dir.parent / "ConfidentialData"


@pytest.fixture(scope="session")
def config_path(package_dir):
    """Get the config.yaml path."""
    return package_dir / "config.yaml"
