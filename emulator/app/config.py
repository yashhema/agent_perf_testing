"""Configuration model and state management for emulator."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from threading import Lock


# Auto-detect emulator root directory (where this package is installed)
_EMULATOR_ROOT = str(Path(__file__).resolve().parent.parent)


def _default_input_normal() -> str:
    return os.path.join(_EMULATOR_ROOT, "data", "normal")


def _default_input_confidential() -> str:
    return os.path.join(_EMULATOR_ROOT, "data", "confidential")


@dataclass
class PartnerConfig:
    """Network partner configuration."""
    fqdn: str = ""
    port: int = 8080


@dataclass
class InputFoldersConfig:
    """Input folders configuration — auto-detected from emulator install path."""
    normal: str = field(default_factory=_default_input_normal)
    confidential: str = field(default_factory=_default_input_confidential)


@dataclass
class StatsConfig:
    """Stats collection configuration."""
    output_dir: str = "./stats"
    max_memory_samples: int = 10000
    default_interval_sec: float = 1.0
    service_monitor_patterns: List[str] = field(default_factory=list)


@dataclass
class EmulatorConfig:
    """Emulator configuration."""
    input_folders: InputFoldersConfig = field(default_factory=InputFoldersConfig)
    output_folders: List[str] = field(default_factory=list)
    partner: PartnerConfig = field(default_factory=PartnerConfig)
    stats: StatsConfig = field(default_factory=StatsConfig)

    def is_configured(self) -> bool:
        """Check if emulator is properly configured."""
        return bool(
            self.output_folders
            and self.partner.fqdn
        )

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            "input_folders": {
                "normal": self.input_folders.normal,
                "confidential": self.input_folders.confidential,
            },
            "output_folders": self.output_folders,
            "partner": {
                "fqdn": self.partner.fqdn,
                "port": self.partner.port,
            },
            "stats": {
                "output_dir": self.stats.output_dir,
                "max_memory_samples": self.stats.max_memory_samples,
                "default_interval_sec": self.stats.default_interval_sec,
                "service_monitor_patterns": self.stats.service_monitor_patterns,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmulatorConfig":
        """Create configuration from dictionary."""
        partner = PartnerConfig(
            fqdn=data.get("partner", {}).get("fqdn", ""),
            port=data.get("partner", {}).get("port", 8080),
        )
        stats = StatsConfig(
            output_dir=data.get("stats", {}).get("output_dir", "./stats"),
            max_memory_samples=data.get("stats", {}).get("max_memory_samples", 10000),
            default_interval_sec=data.get("stats", {}).get("default_interval_sec", 1.0),
            service_monitor_patterns=data.get("stats", {}).get("service_monitor_patterns", []),
        )
        return cls(
            output_folders=data.get("output_folders", []),
            partner=partner,
            stats=stats,
        )


class ConfigManager:
    """Thread-safe configuration manager."""

    _instance: Optional["ConfigManager"] = None
    _lock = Lock()

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._config = EmulatorConfig()
        return cls._instance

    @property
    def config(self) -> EmulatorConfig:
        """Get current configuration."""
        return self._config

    def set_config(self, config: EmulatorConfig) -> None:
        """Set configuration."""
        with self._lock:
            self._config = config

    def update_config(self, data: dict) -> EmulatorConfig:
        """Update configuration from dictionary."""
        with self._lock:
            self._config = EmulatorConfig.from_dict(data)
            return self._config


def get_config_manager() -> ConfigManager:
    """Get the singleton config manager instance."""
    return ConfigManager()


def get_config() -> EmulatorConfig:
    """Get current emulator configuration."""
    return get_config_manager().config
