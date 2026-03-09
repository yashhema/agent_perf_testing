"""Enumeration types for the orchestrator database schema.

All enums derive from (str, Enum) so they serialize as strings in SQLAlchemy
and Pydantic. Values match the database schema specification exactly.
"""

from enum import Enum


class OSFamily(str, Enum):
    linux = "linux"
    windows = "windows"


class HypervisorType(str, Enum):
    proxmox = "proxmox"
    vsphere = "vsphere"
    vultr = "vultr"


class ServerInfraType(str, Enum):
    proxmox_vm = "proxmox_vm"
    vsphere_vm = "vsphere_vm"
    vultr_instance = "vultr_instance"


class BaselineType(str, Enum):
    proxmox = "proxmox"
    vsphere = "vsphere"
    vultr = "vultr"


class DBType(str, Enum):
    mssql = "mssql"
    postgresql = "postgresql"


class DiskType(str, Enum):
    ssd = "ssd"
    hdd = "hdd"


class TemplateType(str, Enum):
    server_normal = "server-normal"
    server_file_heavy = "server-file-heavy"
    db_load = "db-load"


class FunctionalTestPhase(str, Enum):
    base = "base"
    initial = "initial"


class TestRunState(str, Enum):
    created = "created"
    validating = "validating"
    setting_up = "setting_up"
    calibrating = "calibrating"
    generating_sequences = "generating_sequences"
    executing = "executing"
    comparing = "comparing"
    completed = "completed"
    paused = "paused"
    cancelled = "cancelled"
    failed = "failed"


class RunMode(str, Enum):
    complete = "complete"
    step_by_step = "step_by_step"


class ExecutionStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TestPhaseType(str, Enum):
    load = "load"
    stress = "stress"
    network_degradation = "network_degradation"


class AgentType(str, Enum):
    edr = "edr"
    av = "av"
    dlp = "dlp"
    monitoring = "monitoring"
    backup = "backup"
    other = "other"


class RuleSeverity(str, Enum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Verdict(str, Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    warning = "warning"


# ---------------------------------------------------------------------------
# Baseline-Compare Mode Enums
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    """Determines how a lab runs tests: live-compare (2 snapshots per run)
    or baseline-compare (1 snapshot compared against stored baseline data)."""
    live_compare = "live_compare"
    baseline_compare = "baseline_compare"


class BaselineTestType(str, Enum):
    """The three test types available in baseline-compare mode."""
    new_baseline = "new_baseline"
    compare = "compare"
    compare_with_new_calibration = "compare_with_new_calibration"


class BaselineTestState(str, Enum):
    """State machine states for baseline-compare test runs."""
    created = "created"
    validating = "validating"
    setting_up = "setting_up"
    calibrating = "calibrating"
    generating = "generating"
    executing = "executing"
    storing = "storing"
    comparing = "comparing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
