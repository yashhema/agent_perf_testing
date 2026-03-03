"""Global configuration models and YAML loader.

Matches ORCHESTRATOR_DATABASE_SCHEMA.md Section 4 exactly.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml


@dataclass
class CalibrationConfig:
    observation_duration_sec: int = 30
    observation_reading_count: int = 20
    calibration_stability_ratio: float = 0.5
    calibration_confirmation_count: int = 2
    max_calibration_iterations: int = 50
    max_thread_count: int = 30
    stability_min_in_range_pct: float = 55.0
    stability_max_below_pct: float = 10.0


@dataclass
class InfrastructureConfig:
    snapshot_restore_timeout_sec: int = 300
    skip_snapshot_restore: bool = False
    post_restore_verification_enabled: bool = True
    post_restore_verification_commands: Dict[str, str] = field(default_factory=lambda: {
        "linux": "uptime",
        "windows": "systeminfo",
    })


@dataclass
class StatsConfig:
    collect_interval_sec: int = 5
    stats_trim_start_sec: int = 30
    stats_trim_end_sec: int = 10


@dataclass
class BarrierConfig:
    barrier_timeout_margin_percent: float = 0.20


@dataclass
class EmulatorConfig:
    emulator_api_port: int = 8080


@dataclass
class DatabaseConfig:
    """Database configuration supporting both PostgreSQL and SQL Server.

    URL format examples:
      PostgreSQL:  postgresql://user:pass@host:5432/dbname
      SQL Server:  mssql+pyodbc://user:pass@host/dbname?driver=ODBC+Driver+17+for+SQL+Server
      SQL Server (trusted):  mssql+pyodbc://@host/dbname?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes
    """
    url: str = "mssql+pyodbc://@localhost/orchestrator?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
    echo: bool = False


@dataclass
class AppConfig:
    """Root configuration container."""
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    infrastructure: InfrastructureConfig = field(default_factory=InfrastructureConfig)
    stats: StatsConfig = field(default_factory=StatsConfig)
    barrier: BarrierConfig = field(default_factory=BarrierConfig)
    emulator: EmulatorConfig = field(default_factory=EmulatorConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    credentials_path: str = "config/credentials.json"
    artifacts_dir: str = "artifacts"
    generated_dir: str = "generated"
    results_dir: str = "results"


def _build_dataclass(cls, data: Optional[dict]):
    """Build a dataclass instance from a dict, ignoring unknown keys."""
    if not data:
        return cls()
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)


def load_config(config_path: str) -> AppConfig:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Populated AppConfig instance. Missing sections use defaults.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path} (resolved: {path}). "
            f"Ensure you are running from the orchestrator/ directory, "
            f"or pass --config with an absolute path."
        )

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(
        calibration=_build_dataclass(CalibrationConfig, raw.get("calibration")),
        infrastructure=_build_dataclass(InfrastructureConfig, raw.get("infrastructure")),
        stats=_build_dataclass(StatsConfig, raw.get("stats")),
        barrier=_build_dataclass(BarrierConfig, raw.get("barrier")),
        emulator=_build_dataclass(EmulatorConfig, raw.get("emulator")),
        database=_build_dataclass(DatabaseConfig, raw.get("database")),
        credentials_path=raw.get("credentials_path", "config/credentials.json"),
        artifacts_dir=raw.get("artifacts_dir", "artifacts"),
        generated_dir=raw.get("generated_dir", "generated"),
        results_dir=raw.get("results_dir", "results"),
    )
