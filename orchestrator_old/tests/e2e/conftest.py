"""E2E test fixtures and configuration."""

import pytest
from typing import Generator
from unittest.mock import patch, AsyncMock

from tests.e2e.mocks.vsphere import VSphereSimulator, MockVSphereClient
from tests.e2e.mocks.emulator import (
    EmulatorSimulator,
    MockEmulatorServer,
    MockEmulatorClient,
)


@pytest.fixture
def vsphere_simulator() -> VSphereSimulator:
    """Create vSphere simulator with default VMs."""
    simulator = VSphereSimulator(operation_delay_sec=0.01)

    # Add test VMs
    simulator.add_vm(
        name="test-agent-vm-01",
        ip_address="192.168.1.101",
        snapshots=["baseline", "clean-state"],
    )
    simulator.add_vm(
        name="test-agent-vm-02",
        ip_address="192.168.1.102",
        snapshots=["baseline"],
    )

    return simulator


@pytest.fixture
def vsphere_client(vsphere_simulator: VSphereSimulator) -> MockVSphereClient:
    """Create mock vSphere client."""
    return MockVSphereClient(vsphere_simulator)


@pytest.fixture
def emulator_simulator() -> EmulatorSimulator:
    """Create emulator simulator with realistic settings."""
    return EmulatorSimulator(
        base_cpu_per_thread=5.0,
        cpu_variance=1.0,
        base_iteration_ms=50.0,
        iteration_variance=5.0,
    )


@pytest.fixture
def emulator_server(emulator_simulator: EmulatorSimulator) -> MockEmulatorServer:
    """Create mock emulator server."""
    return MockEmulatorServer(emulator_simulator)


@pytest.fixture
def emulator_client(emulator_server: MockEmulatorServer) -> MockEmulatorClient:
    """Create mock emulator client."""
    return MockEmulatorClient(emulator_server)


@pytest.fixture
def mock_calibration_service(emulator_client: MockEmulatorClient):
    """
    Patch calibration service to use mock emulator.

    Returns a factory that creates properly configured mock services.
    """
    from app.calibration.models import (
        CalibrationResult,
        CalibrationStatus,
        LoadProfile,
    )

    async def mock_calibrate(
        target_id: int,
        baseline_id: int,
        loadprofile,  # Uses lowercase to match executor call
        emulator_host: str,
        emulator_port: int,
        cpu_count: int,
        memory_gb: float,
    ) -> CalibrationResult:
        """Mock calibration that returns realistic results."""
        # Simulate calibration finding optimal thread count
        thread_count = int(cpu_count * 2)  # 2 threads per CPU

        # Get expected CPU for this thread count
        cpu_percent = thread_count * 5.0  # ~5% per thread

        return CalibrationResult(
            target_id=target_id,
            baseline_id=baseline_id,
            loadprofile=loadprofile if isinstance(loadprofile, LoadProfile) else LoadProfile.MEDIUM,
            status=CalibrationStatus.COMPLETED,
            thread_count=thread_count,
            cpu_target_percent=50.0,
            achieved_cpu_percent=cpu_percent,
        )

    with patch("app.execution.executor.CalibrationService") as mock_class:
        mock_service = AsyncMock()
        mock_service.calibrate_target = AsyncMock(side_effect=mock_calibrate)
        mock_service.validate_calibration = lambda result: (True, "Valid")
        mock_class.return_value = mock_service
        yield mock_service


@pytest.fixture
def execution_config():
    """Create test execution configuration."""
    from app.execution.models import ExecutionConfig

    return ExecutionConfig(
        test_duration_sec=5,
        warmup_sec=1,
        sample_interval_sec=1,
        max_retries=2,
        retry_delay_sec=0.5,
    )


@pytest.fixture
def target_info():
    """Create test target info."""
    from app.execution.models import TargetInfo

    return TargetInfo(
        target_id=1,
        hostname="test-agent-vm-01",
        ip_address="192.168.1.101",
        os_type="linux",
        cpu_count=8,
        memory_gb=16.0,
        vm_name="test-agent-vm-01",
        vcenter_host="vcenter.test.local",
        snapshot_name="baseline",
    )


@pytest.fixture
def execution_request(target_info, execution_config):
    """Create test execution request."""
    from app.execution.models import ExecutionRequest

    return ExecutionRequest(
        test_run_id=1,
        target_id=1,
        baseline_id=100,
        target_info=target_info,
        load_profile="medium",
        config=execution_config,
    )
