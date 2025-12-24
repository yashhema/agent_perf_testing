"""JTL result file parser."""

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import statistics


@dataclass(frozen=True)
class OperationStats:
    """Statistics for a single operation/label."""

    operation: str
    count: int
    success_count: int
    failure_count: int
    error_rate: float
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    stddev_ms: float
    p50_ms: float
    p90_ms: float
    p99_ms: float
    throughput: float  # requests per second


@dataclass(frozen=True)
class JTLSummary:
    """Summary of JTL results."""

    total_samples: int
    success_count: int
    failure_count: int
    error_rate: float
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    duration_sec: float
    throughput: float
    per_operation: List[OperationStats] = field(default_factory=list)
    start_timestamp: Optional[datetime] = None
    end_timestamp: Optional[datetime] = None


@dataclass
class JTLRecord:
    """Single JTL record."""

    timestamp: int  # milliseconds since epoch
    elapsed: int  # response time in ms
    label: str
    response_code: str
    response_message: str
    thread_name: str
    success: bool
    bytes_received: int
    bytes_sent: int = 0
    grp_threads: int = 0
    all_threads: int = 0
    latency: int = 0
    idle_time: int = 0
    connect: int = 0


class JTLParser:
    """Parser for JMeter JTL result files."""

    # Standard JTL CSV columns
    STANDARD_COLUMNS = [
        "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
        "threadName", "success", "bytes", "sentBytes", "grpThreads",
        "allThreads", "Latency", "IdleTime", "Connect"
    ]

    @classmethod
    def parse_jtl(cls, jtl_path: str) -> Dict:
        """
        Parse a JTL file and return results.

        Returns a dict with 'summary', 'per_operation', and 'error' keys.
        """
        if not os.path.exists(jtl_path):
            return {"error": f"JTL file not found: {jtl_path}"}

        try:
            records = cls._read_jtl_file(jtl_path)

            if not records:
                return {
                    "error": "No records found in JTL file",
                    "summary": cls._empty_summary(),
                }

            return {
                "summary": cls._calculate_summary(records),
                "per_operation": cls._calculate_per_operation(records),
            }

        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def parse_jtl_to_summary(cls, jtl_path: str) -> JTLSummary:
        """Parse a JTL file and return a JTLSummary object."""
        result = cls.parse_jtl(jtl_path)

        if "error" in result and "summary" not in result:
            # Return empty summary on error
            return JTLSummary(
                total_samples=0,
                success_count=0,
                failure_count=0,
                error_rate=0.0,
                avg_response_time_ms=0.0,
                min_response_time_ms=0.0,
                max_response_time_ms=0.0,
                duration_sec=0.0,
                throughput=0.0,
            )

        summary = result.get("summary", {})
        per_op = result.get("per_operation", {})

        operation_stats = [
            OperationStats(
                operation=name,
                count=stats["count"],
                success_count=stats["success_count"],
                failure_count=stats["failure_count"],
                error_rate=stats["error_rate"],
                avg_response_time_ms=stats["avg_response_time_ms"],
                min_response_time_ms=stats["min_response_time_ms"],
                max_response_time_ms=stats["max_response_time_ms"],
                stddev_ms=stats.get("stddev_ms", 0.0),
                p50_ms=stats.get("p50_ms", 0.0),
                p90_ms=stats.get("p90_ms", 0.0),
                p99_ms=stats.get("p99_ms", 0.0),
                throughput=stats.get("throughput", 0.0),
            )
            for name, stats in per_op.items()
        ]

        return JTLSummary(
            total_samples=summary.get("total_samples", 0),
            success_count=summary.get("success_count", 0),
            failure_count=summary.get("failure_count", 0),
            error_rate=summary.get("error_rate", 0.0),
            avg_response_time_ms=summary.get("avg_response_time_ms", 0.0),
            min_response_time_ms=summary.get("min_response_time_ms", 0.0),
            max_response_time_ms=summary.get("max_response_time_ms", 0.0),
            duration_sec=summary.get("duration_sec", 0.0),
            throughput=summary.get("throughput", 0.0),
            per_operation=operation_stats,
            start_timestamp=summary.get("start_timestamp"),
            end_timestamp=summary.get("end_timestamp"),
        )

    @classmethod
    def _read_jtl_file(cls, jtl_path: str) -> List[JTLRecord]:
        """Read and parse JTL file records."""
        records = []

        with open(jtl_path, "r", newline="", encoding="utf-8") as f:
            # Try to detect if file has header
            first_line = f.readline()
            f.seek(0)

            has_header = first_line.startswith("timeStamp") or "label" in first_line

            reader = csv.DictReader(f) if has_header else csv.reader(f)

            for row in reader:
                try:
                    record = cls._parse_row(row, has_header)
                    if record:
                        records.append(record)
                except Exception:
                    continue

        return records

    @classmethod
    def _parse_row(cls, row, has_header: bool) -> Optional[JTLRecord]:
        """Parse a single JTL row."""
        if has_header:
            # Dict-based parsing
            return JTLRecord(
                timestamp=int(row.get("timeStamp", 0)),
                elapsed=int(row.get("elapsed", 0)),
                label=row.get("label", ""),
                response_code=row.get("responseCode", ""),
                response_message=row.get("responseMessage", ""),
                thread_name=row.get("threadName", ""),
                success=row.get("success", "").lower() == "true",
                bytes_received=int(row.get("bytes", 0)),
                bytes_sent=int(row.get("sentBytes", 0)) if row.get("sentBytes") else 0,
                latency=int(row.get("Latency", 0)) if row.get("Latency") else 0,
            )
        else:
            # List-based parsing (positional)
            if len(row) < 8:
                return None
            return JTLRecord(
                timestamp=int(row[0]),
                elapsed=int(row[1]),
                label=row[2],
                response_code=row[3],
                response_message=row[4],
                thread_name=row[5],
                success=row[6].lower() == "true",
                bytes_received=int(row[7]) if row[7] else 0,
            )

    @classmethod
    def _calculate_summary(cls, records: List[JTLRecord]) -> Dict:
        """Calculate overall summary statistics."""
        if not records:
            return cls._empty_summary()

        elapsed_times = [r.elapsed for r in records]
        success_count = sum(1 for r in records if r.success)
        failure_count = len(records) - success_count

        timestamps = [r.timestamp for r in records]
        start_ts = min(timestamps)
        end_ts = max(timestamps) + max(r.elapsed for r in records)
        duration_sec = (end_ts - start_ts) / 1000.0

        return {
            "total_samples": len(records),
            "success_count": success_count,
            "failure_count": failure_count,
            "error_rate": (failure_count / len(records)) * 100 if records else 0.0,
            "avg_response_time_ms": statistics.mean(elapsed_times),
            "min_response_time_ms": min(elapsed_times),
            "max_response_time_ms": max(elapsed_times),
            "duration_sec": duration_sec,
            "throughput": len(records) / duration_sec if duration_sec > 0 else 0.0,
            "start_timestamp": datetime.fromtimestamp(start_ts / 1000.0),
            "end_timestamp": datetime.fromtimestamp(end_ts / 1000.0),
        }

    @classmethod
    def _calculate_per_operation(cls, records: List[JTLRecord]) -> Dict[str, Dict]:
        """Calculate per-operation statistics."""
        # Group records by label
        by_label: Dict[str, List[JTLRecord]] = {}
        for record in records:
            if record.label not in by_label:
                by_label[record.label] = []
            by_label[record.label].append(record)

        result = {}
        for label, label_records in by_label.items():
            elapsed_times = sorted([r.elapsed for r in label_records])
            success_count = sum(1 for r in label_records if r.success)
            failure_count = len(label_records) - success_count

            # Calculate duration for this operation
            timestamps = [r.timestamp for r in label_records]
            duration = (max(timestamps) - min(timestamps) + max(r.elapsed for r in label_records)) / 1000.0

            result[label] = {
                "count": len(label_records),
                "success_count": success_count,
                "failure_count": failure_count,
                "error_rate": (failure_count / len(label_records)) * 100,
                "avg_response_time_ms": statistics.mean(elapsed_times),
                "min_response_time_ms": min(elapsed_times),
                "max_response_time_ms": max(elapsed_times),
                "stddev_ms": statistics.stdev(elapsed_times) if len(elapsed_times) > 1 else 0.0,
                "p50_ms": cls._percentile(elapsed_times, 50),
                "p90_ms": cls._percentile(elapsed_times, 90),
                "p99_ms": cls._percentile(elapsed_times, 99),
                "throughput": len(label_records) / duration if duration > 0 else 0.0,
            }

        return result

    @staticmethod
    def _percentile(sorted_data: List[float], percent: int) -> float:
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * percent / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        if f == c:
            return float(sorted_data[f])
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    @staticmethod
    def _empty_summary() -> Dict:
        """Return empty summary dict."""
        return {
            "total_samples": 0,
            "success_count": 0,
            "failure_count": 0,
            "error_rate": 0.0,
            "avg_response_time_ms": 0.0,
            "min_response_time_ms": 0.0,
            "max_response_time_ms": 0.0,
            "duration_sec": 0.0,
            "throughput": 0.0,
        }
