"""Application configuration using Pydantic Settings.

All configuration is loaded from environment variables or .env file.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://apt:apt_password@localhost:5432/apt_db"
    database_echo: bool = False

    # Application
    app_name: str = "Agent Performance Testing Orchestrator"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Test Database (for testing only)
    test_database_url: str = (
        "postgresql+asyncpg://test_user:test_password@localhost:5433/test_db"
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
