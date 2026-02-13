"""Results collection and storage module.

Handles:
- Collecting results from JMeter, emulator, functional tests
- Compressing results to binary blobs for DB storage
- Decompressing blobs back to dictionaries for analysis
"""

from app.results.compression import (
    compress_results,
    decompress_results,
    compress_dict,
    decompress_dict,
)
from app.results.models import (
    DeviceResultData,
    DeviceStatsData,
    DeviceExecutionData,
    JMeterResultData,
    PhaseResults,
)
from app.results.collector import ResultCollector

__all__ = [
    # Compression utilities
    "compress_results",
    "decompress_results",
    "compress_dict",
    "decompress_dict",
    # Models
    "DeviceResultData",
    "DeviceStatsData",
    "DeviceExecutionData",
    "JMeterResultData",
    "PhaseResults",
    # Collector
    "ResultCollector",
]
