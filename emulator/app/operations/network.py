"""Network I/O operation."""

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class NETOperationParams:
    """Parameters for network operation."""

    duration_ms: int
    target_host: str
    target_port: int
    packet_size_bytes: int = 1024
    mode: Literal["send", "receive", "both"] = "both"


@dataclass(frozen=True)
class NETOperationResult:
    """Result of network operation."""

    operation: str
    duration_ms: int
    target_host: str
    target_port: int
    mode: str
    status: str
    actual_duration_ms: int
    bytes_sent: int
    bytes_received: int
    connection_established: bool
    error_message: Optional[str] = None


class NETOperation:
    """Network I/O operation."""

    @staticmethod
    def _network_io(
        duration_sec: float,
        target_host: str,
        target_port: int,
        packet_size_bytes: int,
        mode: str,
    ) -> tuple[int, int, int, bool, Optional[str]]:
        """
        Perform network I/O operations.

        Returns (actual_duration_ms, bytes_sent, bytes_received, connected, error).
        """
        start_time = time.perf_counter()
        bytes_sent = 0
        bytes_received = 0
        connected = False
        error_message = None

        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)

            try:
                sock.connect((target_host, target_port))
                connected = True
                sock.setblocking(False)

                data = b"X" * packet_size_bytes
                end_time = start_time + duration_sec

                while time.perf_counter() < end_time:
                    try:
                        if mode in ["send", "both"]:
                            sent = sock.send(data)
                            bytes_sent += sent

                        if mode in ["receive", "both"]:
                            try:
                                received = sock.recv(packet_size_bytes)
                                bytes_received += len(received)
                            except BlockingIOError:
                                pass

                    except BlockingIOError:
                        # Non-blocking socket, try again
                        time.sleep(0.001)
                    except socket.error:
                        break

            finally:
                sock.close()

        except socket.timeout:
            error_message = "Connection timeout"
        except ConnectionRefusedError:
            error_message = "Connection refused"
        except socket.gaierror as e:
            error_message = f"DNS resolution failed: {e}"
        except Exception as e:
            error_message = str(e)

        actual_duration = time.perf_counter() - start_time
        return int(actual_duration * 1000), bytes_sent, bytes_received, connected, error_message

    @staticmethod
    async def execute(params: NETOperationParams) -> NETOperationResult:
        """Execute network operation asynchronously."""
        duration_sec = params.duration_ms / 1000

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            NETOperation._network_io,
            duration_sec,
            params.target_host,
            params.target_port,
            params.packet_size_bytes,
            params.mode,
        )
        actual_duration_ms, bytes_sent, bytes_received, connected, error = result

        status = "completed" if connected else "failed"

        return NETOperationResult(
            operation="NET",
            duration_ms=params.duration_ms,
            target_host=params.target_host,
            target_port=params.target_port,
            mode=params.mode,
            status=status,
            actual_duration_ms=actual_duration_ms,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            connection_established=connected,
            error_message=error,
        )
