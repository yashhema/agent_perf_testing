"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import yaml

from orchestrator.config.settings import (
    AppConfig,
    CalibrationConfig,
    InfrastructureConfig,
    StatsConfig,
    load_config,
)


class TestLoadConfig:
    def test_default_config(self):
        """Loading a non-existent file returns defaults."""
        config = load_config("/non/existent/path.yaml")
        assert isinstance(config, AppConfig)
        assert config.calibration.observation_duration_sec == 30
        assert config.stats.stats_trim_start_sec == 30
        assert config.stats.stats_trim_end_sec == 10
        assert config.barrier.barrier_timeout_margin_percent == 0.20
        assert config.emulator.emulator_api_port == 8080

    def test_load_from_yaml(self, tmp_path):
        """Load config from a YAML file with custom values."""
        config_data = {
            "calibration": {
                "observation_duration_sec": 60,
                "max_calibration_iterations": 100,
            },
            "stats": {
                "collect_interval_sec": 10,
            },
            "database": {
                "url": "postgresql://custom:pass@db:5432/mydb",
                "echo": True,
            },
            "results_dir": "/custom/results",
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(str(config_file))
        assert config.calibration.observation_duration_sec == 60
        assert config.calibration.max_calibration_iterations == 100
        # Default values preserved for unspecified fields
        assert config.calibration.observation_reading_count == 5
        assert config.stats.collect_interval_sec == 10
        assert config.database.url == "postgresql://custom:pass@db:5432/mydb"
        assert config.database.echo is True
        assert config.results_dir == "/custom/results"

    def test_unknown_keys_ignored(self, tmp_path):
        """Unknown keys in YAML don't cause errors."""
        config_data = {
            "calibration": {
                "observation_duration_sec": 30,
                "nonexistent_field": 42,
            },
            "totally_unknown_section": True,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(str(config_file))
        assert config.calibration.observation_duration_sec == 30

    def test_empty_yaml(self, tmp_path):
        """Empty YAML file returns defaults."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        config = load_config(str(config_file))
        assert isinstance(config, AppConfig)
        assert config.calibration.observation_duration_sec == 30
