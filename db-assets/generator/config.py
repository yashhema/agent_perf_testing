"""Configuration loader for database schema generator."""

from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
import yaml


@dataclass
class TableCounts:
    """Table count configuration per domain."""
    ecommerce: int = 60
    banking: int = 60
    healthcare: int = 60
    shared: int = 20

    @property
    def total(self) -> int:
        return self.ecommerce + self.banking + self.healthcare + self.shared


@dataclass
class SeedDataConfig:
    """Seed data generation configuration."""
    records_per_table: int = 10000
    batch_size: int = 1000
    confidential_data_source: str = "../ConfidentialData"


@dataclass
class QueryGenerationConfig:
    """Query generation configuration."""
    param_rows_per_query: int = 5000


@dataclass
class DatabaseConfig:
    """Database output configuration."""
    type: str
    output_dir: str


@dataclass
class TestUser:
    """Test user configuration."""
    username: str
    password: str
    role: str


@dataclass
class SchemaConfig:
    """Schema configuration."""
    table_counts: TableCounts = field(default_factory=TableCounts)


@dataclass
class GeneratorConfig:
    """Main configuration for database schema generator."""
    schema: SchemaConfig = field(default_factory=SchemaConfig)
    seed_data: SeedDataConfig = field(default_factory=SeedDataConfig)
    query_generation: QueryGenerationConfig = field(default_factory=QueryGenerationConfig)
    databases: List[DatabaseConfig] = field(default_factory=list)
    test_users: List[TestUser] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, config_path: str) -> "GeneratorConfig":
        """Load configuration from YAML file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "GeneratorConfig":
        """Create configuration from dictionary."""
        schema_data = data.get('schema', {})
        table_counts_data = schema_data.get('table_counts', {})

        table_counts = TableCounts(
            ecommerce=table_counts_data.get('ecommerce', 60),
            banking=table_counts_data.get('banking', 60),
            healthcare=table_counts_data.get('healthcare', 60),
            shared=table_counts_data.get('shared', 20),
        )

        seed_data_data = data.get('seed_data', {})
        seed_data = SeedDataConfig(
            records_per_table=seed_data_data.get('records_per_table', 10000),
            batch_size=seed_data_data.get('batch_size', 1000),
            confidential_data_source=seed_data_data.get('confidential_data_source', '../ConfidentialData'),
        )

        query_gen_data = data.get('query_generation', {})
        query_generation = QueryGenerationConfig(
            param_rows_per_query=query_gen_data.get('param_rows_per_query', 5000),
        )

        databases = [
            DatabaseConfig(type=db['type'], output_dir=db['output_dir'])
            for db in data.get('databases', [])
        ]

        test_users = [
            TestUser(
                username=user['username'],
                password=user['password'],
                role=user['role']
            )
            for user in data.get('test_users', [])
        ]

        return cls(
            schema=SchemaConfig(table_counts=table_counts),
            seed_data=seed_data,
            query_generation=query_generation,
            databases=databases,
            test_users=test_users,
        )

    def get_database_config(self, db_type: str) -> Optional[DatabaseConfig]:
        """Get configuration for specific database type."""
        for db in self.databases:
            if db.type == db_type:
                return db
        return None

    def get_confidential_data_path(self, base_path: str) -> Path:
        """Get absolute path to confidential data folder."""
        base = Path(base_path)
        return (base / self.seed_data.confidential_data_source).resolve()


# Global config instance
_config: Optional[GeneratorConfig] = None


def load_config(config_path: str) -> GeneratorConfig:
    """Load and cache configuration."""
    global _config
    _config = GeneratorConfig.from_yaml(config_path)
    return _config


def get_config() -> GeneratorConfig:
    """Get cached configuration."""
    if _config is None:
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return _config
