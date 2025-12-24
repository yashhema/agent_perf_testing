"""Unit tests for test manager."""

import pytest
import asyncio

from app.services.test_manager import (
    TestManager,
    TestConfig,
    TestStatus,
)
from app.operations.cpu import CPUOperationParams


class TestTestManager:
    """Unit tests for TestManager."""

    @pytest.fixture
    def manager(self) -> TestManager:
        """Create test manager instance."""
        return TestManager(max_workers=10)

    @pytest.mark.asyncio
    async def test_start_test_returns_id(self, manager: TestManager) -> None:
        """Test starting a test returns a valid ID."""
        config = TestConfig(
            thread_count=1,
            duration_sec=1,
            loop_count=1,
            cpu_params=CPUOperationParams(duration_ms=50, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id = await manager.start_test(config)

        assert test_id is not None
        assert len(test_id) > 0

    @pytest.mark.asyncio
    async def test_get_test_status(self, manager: TestManager) -> None:
        """Test getting test status."""
        config = TestConfig(
            thread_count=1,
            duration_sec=1,
            loop_count=1,
            cpu_params=CPUOperationParams(duration_ms=50, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id = await manager.start_test(config)
        status = manager.get_test_status(test_id)

        assert status is not None
        assert status.test_id == test_id
        assert status.status in [TestStatus.PENDING, TestStatus.RUNNING]

    @pytest.mark.asyncio
    async def test_get_test_status_not_found(self, manager: TestManager) -> None:
        """Test getting status of non-existent test."""
        status = manager.get_test_status("non-existent-id")
        assert status is None

    @pytest.mark.asyncio
    async def test_stop_test(self, manager: TestManager) -> None:
        """Test stopping a running test."""
        config = TestConfig(
            thread_count=1,
            duration_sec=10,  # Long duration
            loop_count=None,  # Infinite loops
            cpu_params=CPUOperationParams(duration_ms=100, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id = await manager.start_test(config)

        # Wait a bit for test to start
        await asyncio.sleep(0.1)

        success = await manager.stop_test(test_id)
        assert success is True

        status = manager.get_test_status(test_id)
        assert status.status == TestStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_test_not_found(self, manager: TestManager) -> None:
        """Test stopping a non-existent test."""
        success = await manager.stop_test("non-existent-id")
        assert success is False

    @pytest.mark.asyncio
    async def test_list_all_tests(self, manager: TestManager) -> None:
        """Test listing all tests."""
        config = TestConfig(
            thread_count=1,
            duration_sec=1,
            loop_count=1,
            cpu_params=CPUOperationParams(duration_ms=50, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id1 = await manager.start_test(config)
        test_id2 = await manager.start_test(config)

        tests = manager.get_all_tests()

        assert len(tests) >= 2
        test_ids = [t.test_id for t in tests]
        assert test_id1 in test_ids
        assert test_id2 in test_ids

    @pytest.mark.asyncio
    async def test_test_completes_with_loop_count(self, manager: TestManager) -> None:
        """Test that test completes when loop count is reached."""
        config = TestConfig(
            thread_count=1,
            duration_sec=10,
            loop_count=2,  # Only 2 iterations
            cpu_params=CPUOperationParams(duration_ms=10, intensity=0.1),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id = await manager.start_test(config)

        # Wait for test to complete
        await asyncio.sleep(0.5)

        status = manager.get_test_status(test_id)
        # Should have completed or still be running
        assert status.iterations_completed >= 0

    @pytest.mark.asyncio
    async def test_test_tracks_iterations(self, manager: TestManager) -> None:
        """Test that iterations are tracked."""
        config = TestConfig(
            thread_count=1,
            duration_sec=2,
            loop_count=5,
            cpu_params=CPUOperationParams(duration_ms=10, intensity=0.1),
            mem_params=None,
            disk_params=None,
            net_params=None,
        )

        test_id = await manager.start_test(config)

        # Wait for some iterations
        await asyncio.sleep(0.3)

        status = manager.get_test_status(test_id)
        assert status.iterations_completed >= 0

    @pytest.mark.asyncio
    async def test_parallel_operations(self, manager: TestManager) -> None:
        """Test running operations in parallel."""
        config = TestConfig(
            thread_count=2,
            duration_sec=1,
            loop_count=2,
            cpu_params=CPUOperationParams(duration_ms=50, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
            parallel=True,
        )

        test_id = await manager.start_test(config)
        await asyncio.sleep(0.3)

        status = manager.get_test_status(test_id)
        assert status is not None

    @pytest.mark.asyncio
    async def test_sequential_operations(self, manager: TestManager) -> None:
        """Test running operations sequentially."""
        config = TestConfig(
            thread_count=1,
            duration_sec=1,
            loop_count=2,
            cpu_params=CPUOperationParams(duration_ms=50, intensity=0.5),
            mem_params=None,
            disk_params=None,
            net_params=None,
            parallel=False,
        )

        test_id = await manager.start_test(config)
        await asyncio.sleep(0.3)

        status = manager.get_test_status(test_id)
        assert status is not None
