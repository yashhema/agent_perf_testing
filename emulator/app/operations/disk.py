"""Disk I/O operation."""

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DISKOperationParams:
    """Parameters for disk operation."""

    duration_ms: int
    mode: Literal["read", "write", "mixed"]
    size_mb: int = 100
    block_size_kb: int = 64


@dataclass(frozen=True)
class DISKOperationResult:
    """Result of disk operation."""

    operation: str
    duration_ms: int
    mode: str
    size_mb: int
    block_size_kb: int
    status: str
    actual_duration_ms: int
    bytes_written: int
    bytes_read: int


class DISKOperation:
    """Disk I/O operation."""

    @staticmethod
    def _disk_io(
        duration_sec: float, mode: str, size_mb: int, block_size_kb: int
    ) -> tuple[int, int, int]:
        """
        Perform disk I/O operations.

        Returns (actual_duration_ms, bytes_written, bytes_read).
        """
        start_time = time.perf_counter()

        block_size = block_size_kb * 1024
        data = os.urandom(block_size)

        # Create temp file
        fd, path = tempfile.mkstemp(prefix="emulator_disk_")

        bytes_written = 0
        bytes_read = 0

        try:
            end_time = start_time + duration_sec
            blocks_to_write = (size_mb * 1024) // block_size_kb

            while time.perf_counter() < end_time:
                if mode in ["write", "mixed"]:
                    # Write operation
                    os.lseek(fd, 0, os.SEEK_SET)
                    for _ in range(blocks_to_write):
                        written = os.write(fd, data)
                        bytes_written += written
                    os.fsync(fd)

                if mode in ["read", "mixed"]:
                    # Read operation
                    os.lseek(fd, 0, os.SEEK_SET)
                    while True:
                        chunk = os.read(fd, block_size)
                        if not chunk:
                            break
                        bytes_read += len(chunk)

        finally:
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass

        actual_duration = time.perf_counter() - start_time
        return int(actual_duration * 1000), bytes_written, bytes_read

    @staticmethod
    async def execute(params: DISKOperationParams) -> DISKOperationResult:
        """Execute disk operation asynchronously."""
        duration_sec = params.duration_ms / 1000

        loop = asyncio.get_event_loop()
        actual_duration_ms, bytes_written, bytes_read = await loop.run_in_executor(
            None,
            DISKOperation._disk_io,
            duration_sec,
            params.mode,
            params.size_mb,
            params.block_size_kb,
        )

        return DISKOperationResult(
            operation="DISK",
            duration_ms=params.duration_ms,
            mode=params.mode,
            size_mb=params.size_mb,
            block_size_kb=params.block_size_kb,
            status="completed",
            actual_duration_ms=actual_duration_ms,
            bytes_written=bytes_written,
            bytes_read=bytes_read,
        )
