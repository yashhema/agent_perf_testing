"""Compression utilities for result data.

Results are stored as compressed binary blobs to save space.
Uses gzip compression for JSON-serializable dictionaries.
"""

import gzip
import json
from typing import Any, Optional


def compress_dict(data: dict) -> bytes:
    """
    Compress a dictionary to a gzip-compressed binary blob.

    Args:
        data: Dictionary to compress (must be JSON-serializable)

    Returns:
        Compressed bytes ready for storage in LargeBinary field
    """
    json_str = json.dumps(data, default=str)
    json_bytes = json_str.encode('utf-8')
    compressed = gzip.compress(json_bytes, compresslevel=6)
    return compressed


def decompress_dict(blob: bytes) -> dict:
    """
    Decompress a gzip-compressed blob back to a dictionary.

    Args:
        blob: Compressed bytes from LargeBinary field

    Returns:
        Original dictionary
    """
    decompressed = gzip.decompress(blob)
    json_str = decompressed.decode('utf-8')
    return json.loads(json_str)


def compress_results(
    results_by_package: dict[str, Any],
    include_raw: bool = True,
) -> bytes:
    """
    Compress results dictionary organized by package_id.

    Structure:
    {
        "jmeter": {
            "success": True,
            "total_requests": 100000,
            "avg_response_time_ms": 25.5,
            ...
            "raw_jtl": "..." (if include_raw)
        },
        "pkg_101": {
            "package_id": 101,
            "package_name": "Functional Test A",
            "success": True,
            "tests_passed": 10,
            ...
        },
        ...
    }

    Args:
        results_by_package: Dictionary of package_id -> results
        include_raw: Whether to include raw data (JTL, logs, etc.)

    Returns:
        Compressed bytes
    """
    if not include_raw:
        # Strip raw data fields to reduce size
        filtered = {}
        for key, value in results_by_package.items():
            if isinstance(value, dict):
                filtered[key] = {
                    k: v for k, v in value.items()
                    if not k.startswith('raw_') and k not in ('stdout', 'stderr', 'log_content')
                }
            else:
                filtered[key] = value
        return compress_dict(filtered)

    return compress_dict(results_by_package)


def decompress_results(blob: Optional[bytes]) -> dict:
    """
    Decompress results blob back to dictionary.

    Args:
        blob: Compressed bytes or None

    Returns:
        Dictionary of results or empty dict if blob is None
    """
    if blob is None:
        return {}
    return decompress_dict(blob)


def get_compression_ratio(original: dict, compressed: bytes) -> float:
    """
    Calculate compression ratio for diagnostics.

    Args:
        original: Original dictionary
        compressed: Compressed bytes

    Returns:
        Compression ratio (original_size / compressed_size)
    """
    original_size = len(json.dumps(original, default=str).encode('utf-8'))
    compressed_size = len(compressed)
    if compressed_size == 0:
        return 0.0
    return original_size / compressed_size


def estimate_uncompressed_size(blob: bytes) -> int:
    """
    Estimate uncompressed size without fully decompressing.

    Useful for checking if blob is too large before decompressing.

    Args:
        blob: Compressed bytes

    Returns:
        Estimated uncompressed size in bytes
    """
    # gzip stores original size in last 4 bytes (modulo 2^32)
    if len(blob) < 4:
        return 0
    return int.from_bytes(blob[-4:], byteorder='little')
