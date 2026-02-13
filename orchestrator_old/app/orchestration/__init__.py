"""Scenario orchestration module."""

from .scenario import ScenarioOrchestrator, ScenarioConfig, ScenarioResult
from .models import (
    ServerSetup,
    ScenarioPhase,
    PhaseResult,
    CalibrationData,
    SetupResult,
)
from .phase_orchestrator import (
    PhaseOrchestrator,
    PhaseExecutionConfig,
    PhaseExecutionResult,
    PhaseStage,
)
from .test_executor import (
    TestExecutor,
    TestExecutionConfig,
    TestExecutionResult,
    TargetConfig,
    TargetResult,
    ExecutionStage,
    SnapshotManager,
    EmulatorManager,
)
from .managers import (
    HTTPEmulatorManager,
    HypervisorSnapshotManager,
    DockerSnapshotManager,
    SSHJMeterExecutor,
    TestExecutorFactory,
    CalibrationExecutorFactory,
)
from .environment import (
    EnvironmentType,
    EnvironmentConfig,
    ContainerConfig,
    get_environment_config,
    set_environment_config,
    is_docker_mode,
)
from .execution_controller import (
    ExecutionController,
    ControllerState,
    ControllerProgress,
)
from .calibration_executor import (
    CalibrationExecutor,
    CalibrationExecutionConfig,
    CalibrationExecutionResult,
    CalibrationTargetConfig,
    TargetCalibrationResult,
    CalibrationStage,
)
from .os_discovery import (
    OSDiscoveryService,
    DiscoveryResult,
    OSInfo,
    BaselineDiscoveryResult,
)

__all__ = [
    # Scenario setup/calibration orchestration (legacy)
    "ScenarioOrchestrator",
    "ScenarioConfig",
    "ScenarioResult",
    "ServerSetup",
    "ScenarioPhase",
    "PhaseResult",
    "CalibrationData",
    "SetupResult",
    # Phase orchestration (single target)
    "PhaseOrchestrator",
    "PhaseExecutionConfig",
    "PhaseExecutionResult",
    "PhaseStage",
    # Test execution (barrier-based, all targets)
    "TestExecutor",
    "TestExecutionConfig",
    "TestExecutionResult",
    "TargetConfig",
    "TargetResult",
    "ExecutionStage",
    # Calibration execution (barrier-based, all targets)
    "CalibrationExecutor",
    "CalibrationExecutionConfig",
    "CalibrationExecutionResult",
    "CalibrationTargetConfig",
    "TargetCalibrationResult",
    "CalibrationStage",
    # Protocols
    "SnapshotManager",
    "EmulatorManager",
    # Production managers
    "HTTPEmulatorManager",
    "HypervisorSnapshotManager",
    "DockerSnapshotManager",
    "SSHJMeterExecutor",
    # Factories
    "TestExecutorFactory",
    "CalibrationExecutorFactory",
    # Environment
    "EnvironmentType",
    "EnvironmentConfig",
    "ContainerConfig",
    "get_environment_config",
    "set_environment_config",
    "is_docker_mode",
    # Execution Controller
    "ExecutionController",
    "ControllerState",
    "ControllerProgress",
    # OS Discovery
    "OSDiscoveryService",
    "DiscoveryResult",
    "OSInfo",
    "BaselineDiscoveryResult",
]
