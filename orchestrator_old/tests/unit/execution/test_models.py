"""Unit tests for execution models."""

import pytest
from datetime import datetime

from app.execution.models import (
    EmulatorDeployment,
    ExecutionConfig,
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionPhase,
    ExecutionProgress,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    ExecutionStatus,
    PhaseResult,
    TargetInfo,
)


class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""

    def test_status_values(self):
        """Test ExecutionStatus enum values."""
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.INITIALIZING == "initializing"
        assert ExecutionStatus.CALIBRATING == "calibrating"
        assert ExecutionStatus.DEPLOYING == "deploying"
        assert ExecutionStatus.RUNNING == "running"
        assert ExecutionStatus.COLLECTING == "collecting"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.CANCELLED == "cancelled"


class TestExecutionPhase:
    """Tests for ExecutionPhase enum."""

    def test_phase_values(self):
        """Test ExecutionPhase enum values."""
        assert ExecutionPhase.INIT == "init"
        assert ExecutionPhase.VM_PREPARATION == "vm_preparation"
        assert ExecutionPhase.EMULATOR_DEPLOYMENT == "emulator_deployment"
        assert ExecutionPhase.CALIBRATION == "calibration"
        assert ExecutionPhase.LOAD_TEST == "load_test"
        assert ExecutionPhase.RESULT_COLLECTION == "result_collection"
        assert ExecutionPhase.CLEANUP == "cleanup"
        assert ExecutionPhase.DONE == "done"


class TestExecutionConfig:
    """Tests for ExecutionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ExecutionConfig()

        assert config.test_duration_sec == 300
        assert config.warmup_sec == 30
        assert config.cooldown_sec == 30
        assert config.max_retries == 3
        assert config.retry_delay_sec == 60
        assert config.vm_operation_timeout_sec == 300
        assert config.deployment_timeout_sec == 600
        assert config.calibration_timeout_sec == 900
        assert config.test_timeout_sec == 3600
        assert config.cleanup_on_failure is True
        assert config.revert_snapshot_on_failure is True
        assert config.max_parallel_targets == 5

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ExecutionConfig(
            test_duration_sec=600,
            max_parallel_targets=10,
        )

        assert config.test_duration_sec == 600
        assert config.max_parallel_targets == 10

    def test_immutability(self):
        """Test ExecutionConfig is immutable."""
        config = ExecutionConfig()

        with pytest.raises(AttributeError):
            config.test_duration_sec = 600


class TestTargetInfo:
    """Tests for TargetInfo dataclass."""

    def test_create_target_info(self):
        """Test creating TargetInfo."""
        target = TargetInfo(
            target_id=1,
            hostname="test-server-01",
            ip_address="192.168.1.100",
            os_type="linux",
            cpu_count=8,
            memory_gb=16.0,
        )

        assert target.target_id == 1
        assert target.hostname == "test-server-01"
        assert target.ip_address == "192.168.1.100"
        assert target.os_type == "linux"
        assert target.cpu_count == 8
        assert target.memory_gb == 16.0
        assert target.vm_name is None
        assert target.vcenter_host is None
        assert target.snapshot_name is None

    def test_with_vm_info(self):
        """Test TargetInfo with VM information."""
        target = TargetInfo(
            target_id=1,
            hostname="test-server-01",
            ip_address="192.168.1.100",
            os_type="windows",
            cpu_count=4,
            memory_gb=8.0,
            vm_name="vm-test-01",
            vcenter_host="vcenter.example.com",
            snapshot_name="baseline",
        )

        assert target.vm_name == "vm-test-01"
        assert target.vcenter_host == "vcenter.example.com"
        assert target.snapshot_name == "baseline"

    def test_immutability(self):
        """Test TargetInfo is immutable."""
        target = TargetInfo(
            target_id=1,
            hostname="test",
            ip_address="192.168.1.1",
            os_type="linux",
            cpu_count=4,
            memory_gb=8.0,
        )

        with pytest.raises(AttributeError):
            target.cpu_count = 8


class TestEmulatorDeployment:
    """Tests for EmulatorDeployment dataclass."""

    def test_create_deployment(self):
        """Test creating EmulatorDeployment."""
        now = datetime.utcnow()
        deployment = EmulatorDeployment(
            target_id=1,
            host="192.168.1.100",
            port=8080,
            deployed_at=now,
        )

        assert deployment.target_id == 1
        assert deployment.host == "192.168.1.100"
        assert deployment.port == 8080
        assert deployment.deployed_at == now
        assert deployment.version is None
        assert deployment.pid is None

    def test_with_optional_fields(self):
        """Test EmulatorDeployment with optional fields."""
        now = datetime.utcnow()
        deployment = EmulatorDeployment(
            target_id=1,
            host="192.168.1.100",
            port=8080,
            deployed_at=now,
            version="1.2.0",
            pid=12345,
        )

        assert deployment.version == "1.2.0"
        assert deployment.pid == 12345


class TestPhaseResult:
    """Tests for PhaseResult dataclass."""

    def test_create_in_progress(self):
        """Test creating in-progress phase result."""
        now = datetime.utcnow()
        result = PhaseResult(
            phase=ExecutionPhase.CALIBRATION,
            status=ExecutionStatus.RUNNING,
            started_at=now,
        )

        assert result.phase == ExecutionPhase.CALIBRATION
        assert result.status == ExecutionStatus.RUNNING
        assert result.started_at == now
        assert result.completed_at is None
        assert result.duration_sec is None
        assert result.error_message is None

    def test_create_completed(self):
        """Test creating completed phase result."""
        start = datetime.utcnow()
        end = datetime.utcnow()
        result = PhaseResult(
            phase=ExecutionPhase.LOAD_TEST,
            status=ExecutionStatus.COMPLETED,
            started_at=start,
            completed_at=end,
            duration_sec=300.5,
            details="Test completed successfully",
        )

        assert result.status == ExecutionStatus.COMPLETED
        assert result.completed_at == end
        assert result.duration_sec == 300.5
        assert result.details == "Test completed successfully"

    def test_create_failed(self):
        """Test creating failed phase result."""
        result = PhaseResult(
            phase=ExecutionPhase.EMULATOR_DEPLOYMENT,
            status=ExecutionStatus.FAILED,
            started_at=datetime.utcnow(),
            error_message="Connection refused",
        )

        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Connection refused"


class TestExecutionMetrics:
    """Tests for ExecutionMetrics dataclass."""

    def test_create_minimal(self):
        """Test creating minimal metrics."""
        metrics = ExecutionMetrics(total_duration_sec=600.0)

        assert metrics.total_duration_sec == 600.0
        assert metrics.total_requests is None
        assert metrics.avg_response_time_ms is None
        assert metrics.throughput_rps is None

    def test_create_full(self):
        """Test creating full metrics."""
        metrics = ExecutionMetrics(
            total_duration_sec=600.0,
            calibration_duration_sec=120.0,
            deployment_duration_sec=60.0,
            test_duration_sec=300.0,
            total_requests=150000,
            successful_requests=149500,
            failed_requests=500,
            avg_response_time_ms=42.5,
            p50_response_time_ms=38.0,
            p90_response_time_ms=65.0,
            p99_response_time_ms=120.0,
            throughput_rps=500.0,
            avg_cpu_percent=70.0,
            max_cpu_percent=85.0,
            avg_memory_percent=45.0,
            max_memory_percent=55.0,
        )

        assert metrics.total_requests == 150000
        assert metrics.successful_requests == 149500
        assert metrics.failed_requests == 500
        assert metrics.avg_response_time_ms == 42.5
        assert metrics.p50_response_time_ms == 38.0
        assert metrics.p90_response_time_ms == 65.0
        assert metrics.p99_response_time_ms == 120.0
        assert metrics.throughput_rps == 500.0
        assert metrics.avg_cpu_percent == 70.0
        assert metrics.max_cpu_percent == 85.0


class TestExecutionState:
    """Tests for ExecutionState dataclass."""

    def test_create_initial_state(self):
        """Test creating initial execution state."""
        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

        assert state.execution_id == "exec-123"
        assert state.test_run_id == 1
        assert state.target_id == 100
        assert state.baseline_id == 50
        assert state.status == ExecutionStatus.PENDING
        assert state.current_phase == ExecutionPhase.INIT
        assert state.retry_count == 0
        assert state.created_at is not None
        assert state.started_at is None
        assert state.completed_at is None
        assert state.phase_results == []
        assert state.emulator_deployment is None
        assert state.last_error is None

    def test_state_is_mutable(self):
        """Test ExecutionState is mutable."""
        state = ExecutionState(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
        )

        state.status = ExecutionStatus.RUNNING
        state.retry_count = 1

        assert state.status == ExecutionStatus.RUNNING
        assert state.retry_count == 1


class TestExecutionRequest:
    """Tests for ExecutionRequest dataclass."""

    def test_create_request(self):
        """Test creating execution request."""
        target = TargetInfo(
            target_id=1,
            hostname="test",
            ip_address="192.168.1.1",
            os_type="linux",
            cpu_count=4,
            memory_gb=8.0,
        )

        request = ExecutionRequest(
            test_run_id=1,
            target_id=1,
            baseline_id=100,
            target_info=target,
            load_profile="medium",
        )

        assert request.test_run_id == 1
        assert request.target_id == 1
        assert request.baseline_id == 100
        assert request.target_info == target
        assert request.load_profile == "medium"
        assert isinstance(request.config, ExecutionConfig)


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_create_success_result(self):
        """Test creating successful result."""
        now = datetime.utcnow()
        result = ExecutionResult(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
            status=ExecutionStatus.COMPLETED,
            load_profile="high",
            started_at=now,
            completed_at=now,
            total_duration_sec=600.0,
            thread_count=20,
            target_cpu_percent=70.0,
            achieved_cpu_percent=71.5,
        )

        assert result.status == ExecutionStatus.COMPLETED
        assert result.thread_count == 20
        assert result.error_message is None

    def test_create_failed_result(self):
        """Test creating failed result."""
        now = datetime.utcnow()
        result = ExecutionResult(
            execution_id="exec-123",
            test_run_id=1,
            target_id=100,
            baseline_id=50,
            status=ExecutionStatus.FAILED,
            load_profile="medium",
            started_at=now,
            completed_at=now,
            total_duration_sec=60.0,
            thread_count=0,
            target_cpu_percent=50.0,
            achieved_cpu_percent=0.0,
            error_message="Calibration failed",
            error_phase=ExecutionPhase.CALIBRATION,
        )

        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Calibration failed"
        assert result.error_phase == ExecutionPhase.CALIBRATION


class TestExecutionProgress:
    """Tests for ExecutionProgress dataclass."""

    def test_create_progress(self):
        """Test creating progress update."""
        progress = ExecutionProgress(
            execution_id="exec-123",
            status=ExecutionStatus.RUNNING,
            current_phase=ExecutionPhase.LOAD_TEST,
            phase_progress_percent=45.0,
            overall_progress_percent=65.0,
            message="Running load test...",
        )

        assert progress.execution_id == "exec-123"
        assert progress.status == ExecutionStatus.RUNNING
        assert progress.current_phase == ExecutionPhase.LOAD_TEST
        assert progress.phase_progress_percent == 45.0
        assert progress.overall_progress_percent == 65.0
        assert progress.message == "Running load test..."


class TestExecutionEvent:
    """Tests for ExecutionEvent dataclass."""

    def test_create_event(self):
        """Test creating execution event."""
        event = ExecutionEvent(
            execution_id="exec-123",
            event_type="calibration_started",
            phase=ExecutionPhase.CALIBRATION,
            message="Starting calibration for medium profile",
        )

        assert event.execution_id == "exec-123"
        assert event.event_type == "calibration_started"
        assert event.phase == ExecutionPhase.CALIBRATION
        assert event.is_error is False

    def test_create_error_event(self):
        """Test creating error event."""
        event = ExecutionEvent(
            execution_id="exec-123",
            event_type="deployment_failed",
            phase=ExecutionPhase.EMULATOR_DEPLOYMENT,
            message="Connection refused",
            details="SSH connection to 192.168.1.100 failed",
            is_error=True,
        )

        assert event.is_error is True
        assert event.details is not None
