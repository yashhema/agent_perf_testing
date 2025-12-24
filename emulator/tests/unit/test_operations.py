"""Unit tests for emulator operations."""

import pytest
import time

from app.operations.cpu import CPUOperation, CPUOperationParams
from app.operations.memory import MEMOperation, MEMOperationParams
from app.operations.disk import DISKOperation, DISKOperationParams
from app.operations.network import NETOperation, NETOperationParams


class TestCPUOperation:
    """Unit tests for CPU operation."""

    @pytest.mark.asyncio
    async def test_cpu_operation_completes(self) -> None:
        """Test CPU operation completes in expected time."""
        params = CPUOperationParams(duration_ms=100, intensity=0.5)

        start = time.perf_counter()
        result = await CPUOperation.execute(params)
        elapsed = time.perf_counter() - start

        assert result.status == "completed"
        assert result.operation == "CPU"
        # Should complete within reasonable tolerance (50ms to 300ms)
        assert 0.05 < elapsed < 0.3

    @pytest.mark.asyncio
    async def test_cpu_operation_returns_params(self) -> None:
        """Test CPU operation returns input parameters."""
        params = CPUOperationParams(duration_ms=50, intensity=0.8)
        result = await CPUOperation.execute(params)

        assert result.duration_ms == 50
        assert result.intensity == 0.8

    @pytest.mark.asyncio
    async def test_cpu_operation_zero_intensity(self) -> None:
        """Test CPU operation with zero intensity (mostly sleeping)."""
        params = CPUOperationParams(duration_ms=100, intensity=0.0)
        result = await CPUOperation.execute(params)

        assert result.status == "completed"
        assert result.intensity == 0.0

    @pytest.mark.asyncio
    async def test_cpu_operation_full_intensity(self) -> None:
        """Test CPU operation with full intensity."""
        params = CPUOperationParams(duration_ms=50, intensity=1.0)
        result = await CPUOperation.execute(params)

        assert result.status == "completed"
        assert result.intensity == 1.0


class TestMEMOperation:
    """Unit tests for memory operation."""

    @pytest.mark.asyncio
    async def test_mem_operation_completes(self) -> None:
        """Test memory operation completes."""
        params = MEMOperationParams(
            duration_ms=100,
            size_mb=10,
            pattern="sequential",
        )

        result = await MEMOperation.execute(params)

        assert result.status == "completed"
        assert result.operation == "MEM"

    @pytest.mark.asyncio
    async def test_mem_operation_sequential_pattern(self) -> None:
        """Test memory operation with sequential access pattern."""
        params = MEMOperationParams(
            duration_ms=100,
            size_mb=5,
            pattern="sequential",
        )

        result = await MEMOperation.execute(params)

        assert result.status == "completed"
        assert result.pattern == "sequential"
        assert result.access_count > 0

    @pytest.mark.asyncio
    async def test_mem_operation_random_pattern(self) -> None:
        """Test memory operation with random access pattern."""
        params = MEMOperationParams(
            duration_ms=100,
            size_mb=5,
            pattern="random",
        )

        result = await MEMOperation.execute(params)

        assert result.status == "completed"
        assert result.pattern == "random"
        assert result.access_count > 0

    @pytest.mark.asyncio
    async def test_mem_operation_returns_params(self) -> None:
        """Test memory operation returns input parameters."""
        params = MEMOperationParams(
            duration_ms=50,
            size_mb=8,
            pattern="sequential",
        )

        result = await MEMOperation.execute(params)

        assert result.duration_ms == 50
        assert result.size_mb == 8


class TestDISKOperation:
    """Unit tests for disk operation."""

    @pytest.mark.asyncio
    async def test_disk_write_operation(self) -> None:
        """Test disk write operation."""
        params = DISKOperationParams(
            duration_ms=100,
            mode="write",
            size_mb=1,
            block_size_kb=64,
        )

        result = await DISKOperation.execute(params)

        assert result.status == "completed"
        assert result.operation == "DISK"
        assert result.mode == "write"
        assert result.bytes_written > 0

    @pytest.mark.asyncio
    async def test_disk_read_operation(self) -> None:
        """Test disk read operation."""
        params = DISKOperationParams(
            duration_ms=100,
            mode="read",
            size_mb=1,
        )

        result = await DISKOperation.execute(params)

        assert result.status == "completed"
        assert result.mode == "read"
        # Note: read might be 0 if file is empty initially
        assert result.bytes_read >= 0

    @pytest.mark.asyncio
    async def test_disk_mixed_operation(self) -> None:
        """Test disk mixed read/write operation."""
        params = DISKOperationParams(
            duration_ms=100,
            mode="mixed",
            size_mb=1,
        )

        result = await DISKOperation.execute(params)

        assert result.status == "completed"
        assert result.mode == "mixed"

    @pytest.mark.asyncio
    async def test_disk_operation_returns_params(self) -> None:
        """Test disk operation returns input parameters."""
        params = DISKOperationParams(
            duration_ms=50,
            mode="write",
            size_mb=2,
            block_size_kb=32,
        )

        result = await DISKOperation.execute(params)

        assert result.duration_ms == 50
        assert result.size_mb == 2
        assert result.block_size_kb == 32


class TestNETOperation:
    """Unit tests for network operation."""

    @pytest.mark.asyncio
    async def test_net_operation_connection_refused(self) -> None:
        """Test network operation with connection refused."""
        params = NETOperationParams(
            duration_ms=100,
            target_host="127.0.0.1",
            target_port=59999,  # Unlikely to be open
            mode="send",
        )

        result = await NETOperation.execute(params)

        # Should fail but complete gracefully
        assert result.operation == "NET"
        assert result.connection_established is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_net_operation_invalid_host(self) -> None:
        """Test network operation with invalid host."""
        params = NETOperationParams(
            duration_ms=100,
            target_host="invalid.host.that.does.not.exist.local",
            target_port=80,
            mode="send",
        )

        result = await NETOperation.execute(params)

        assert result.connection_established is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_net_operation_returns_params(self) -> None:
        """Test network operation returns input parameters."""
        params = NETOperationParams(
            duration_ms=100,
            target_host="localhost",
            target_port=8080,
            packet_size_bytes=512,
            mode="both",
        )

        result = await NETOperation.execute(params)

        assert result.duration_ms == 100
        assert result.target_host == "localhost"
        assert result.target_port == 8080
        assert result.mode == "both"
