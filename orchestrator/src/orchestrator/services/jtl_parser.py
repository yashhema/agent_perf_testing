"""JMeter JTL CSV parser.

Matches ORCHESTRATOR_INTERFACES.md Section 4 exactly.
Parses JTL CSV files produced by JMeter and extracts:
  - Total requests, errors, error rate
  - Throughput (requests/sec)
  - Response times (avg, p50, p90, p95, p99)
  - Per-label breakdown
  - Raw data for statistical tests (per-second throughput timeseries,
    response time distributions, per-label response times)
"""

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class JtlRawData:
    """Raw data extracted from JTL for statistical comparison.

    Contains per-second throughput timeseries, raw response times,
    and per-label response times for Cliff's delta / Mann-Whitney tests.
    """
    throughput_per_sec_timeseries: List[float]  # request count per 1-second bucket
    response_times_ms: List[float]  # all individual elapsed_ms values
    per_label_response_times: Dict[str, List[float]]  # label -> list of elapsed_ms


@dataclass
class LabelResult:
    """Per-operation-type metrics."""
    count: int
    errors: int
    error_rate_percent: float
    avg_response_ms: float
    p90_response_ms: float
    p99_response_ms: float


@dataclass
class JtlResult:
    """Aggregate and per-label JTL parsing results."""
    total_requests: int
    total_errors: int
    error_rate_percent: float
    throughput_per_sec: float
    duration_sec: float
    avg_response_ms: float
    p50_response_ms: float
    p90_response_ms: float
    p95_response_ms: float
    p99_response_ms: float
    per_label: Dict[str, LabelResult] = field(default_factory=dict)


class JtlParser:
    """Parses JMeter JTL CSV files.

    JTL CSV columns:
      timeStamp,elapsed,label,responseCode,responseMessage,
      threadName,success,bytes,sentBytes,grpThreads,allThreads,
      URL,Latency,IdleTime,Connect
    """

    def parse(self, jtl_path: str) -> JtlResult:
        """Parse JTL CSV file.

        Returns: JtlResult with per-label and aggregate metrics.
        """
        timestamps: List[int] = []
        elapsed_times: List[float] = []
        errors = 0
        label_data: Dict[str, List[Dict]] = {}

        with open(jtl_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = int(row["timeStamp"])
                elapsed_ms = float(row["elapsed"])
                label = row["label"]
                success = row["success"].strip().lower() == "true"

                timestamps.append(ts)
                elapsed_times.append(elapsed_ms)
                if not success:
                    errors += 1

                if label not in label_data:
                    label_data[label] = []
                label_data[label].append({
                    "elapsed_ms": elapsed_ms,
                    "success": success,
                })

        total = len(timestamps)
        if total == 0:
            return JtlResult(
                total_requests=0, total_errors=0, error_rate_percent=0.0,
                throughput_per_sec=0.0, duration_sec=0.0,
                avg_response_ms=0.0, p50_response_ms=0.0,
                p90_response_ms=0.0, p95_response_ms=0.0,
                p99_response_ms=0.0, per_label={},
            )

        duration_ms = max(timestamps) - min(timestamps)
        duration_sec = duration_ms / 1000.0 if duration_ms > 0 else 1.0
        throughput = total / duration_sec

        sorted_elapsed = sorted(elapsed_times)
        avg_response = sum(elapsed_times) / total

        # Per-label results
        per_label = {}
        for label, entries in label_data.items():
            label_elapsed = sorted([e["elapsed_ms"] for e in entries])
            label_errors = sum(1 for e in entries if not e["success"])
            label_count = len(entries)
            per_label[label] = LabelResult(
                count=label_count,
                errors=label_errors,
                error_rate_percent=round((label_errors / label_count) * 100, 2) if label_count > 0 else 0.0,
                avg_response_ms=round(sum(label_elapsed) / label_count, 2),
                p90_response_ms=round(self._percentile(label_elapsed, 90), 2),
                p99_response_ms=round(self._percentile(label_elapsed, 99), 2),
            )

        return JtlResult(
            total_requests=total,
            total_errors=errors,
            error_rate_percent=round((errors / total) * 100, 2),
            throughput_per_sec=round(throughput, 2),
            duration_sec=round(duration_sec, 2),
            avg_response_ms=round(avg_response, 2),
            p50_response_ms=round(self._percentile(sorted_elapsed, 50), 2),
            p90_response_ms=round(self._percentile(sorted_elapsed, 90), 2),
            p95_response_ms=round(self._percentile(sorted_elapsed, 95), 2),
            p99_response_ms=round(self._percentile(sorted_elapsed, 99), 2),
            per_label=per_label,
        )

    def parse_raw(self, jtl_path: str) -> JtlRawData:
        """Parse JTL CSV and extract raw data for statistical comparison.

        Returns JtlRawData with:
          - Per-second throughput timeseries (request counts per 1s bucket)
          - All individual response times
          - Per-label response times
        """
        timestamps: List[int] = []
        elapsed_times: List[float] = []
        label_times: Dict[str, List[float]] = {}

        with open(jtl_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = int(row["timeStamp"])
                elapsed_ms = float(row["elapsed"])
                label = row["label"]

                timestamps.append(ts)
                elapsed_times.append(elapsed_ms)

                if label not in label_times:
                    label_times[label] = []
                label_times[label].append(elapsed_ms)

        if not timestamps:
            return JtlRawData(
                throughput_per_sec_timeseries=[],
                response_times_ms=[],
                per_label_response_times={},
            )

        # Build per-second throughput timeseries
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        duration_sec = (max_ts - min_ts) // 1000 + 1

        # Bucket requests into 1-second intervals
        buckets = [0.0] * duration_sec
        for ts in timestamps:
            bucket_idx = (ts - min_ts) // 1000
            if 0 <= bucket_idx < duration_sec:
                buckets[bucket_idx] += 1.0

        # Trim first and last buckets (may be partial seconds)
        if len(buckets) > 2:
            throughput_ts = buckets[1:-1]
        else:
            throughput_ts = buckets

        return JtlRawData(
            throughput_per_sec_timeseries=throughput_ts,
            response_times_ms=elapsed_times,
            per_label_response_times=label_times,
        )

    @staticmethod
    def merge_raw_data(raw_list: List[JtlRawData]) -> JtlRawData:
        """Merge raw data from multiple JTL files (across cycles).

        Concatenates throughput timeseries, response times, and per-label data.
        """
        if len(raw_list) == 1:
            return raw_list[0]

        all_throughput: List[float] = []
        all_response: List[float] = []
        all_per_label: Dict[str, List[float]] = {}

        for raw in raw_list:
            all_throughput.extend(raw.throughput_per_sec_timeseries)
            all_response.extend(raw.response_times_ms)
            for label, times in raw.per_label_response_times.items():
                if label not in all_per_label:
                    all_per_label[label] = []
                all_per_label[label].extend(times)

        return JtlRawData(
            throughput_per_sec_timeseries=all_throughput,
            response_times_ms=all_response,
            per_label_response_times=all_per_label,
        )

    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        """Compute percentile using linear interpolation."""
        n = len(sorted_values)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_values[0]

        k = (percentile / 100.0) * (n - 1)
        f = math.floor(k)
        c = math.ceil(k)

        if f == c:
            return sorted_values[int(k)]

        lower = sorted_values[f]
        upper = sorted_values[c]
        return lower + (upper - lower) * (k - f)
