"""Tests for JTL CSV parser."""

import csv
from pathlib import Path

import pytest

from orchestrator.services.jtl_parser import JtlParser, JtlResult, LabelResult


@pytest.fixture
def parser():
    return JtlParser()


def _write_jtl(path: str, rows: list):
    """Helper to write a JTL CSV file."""
    fieldnames = [
        "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
        "threadName", "success", "bytes", "sentBytes", "grpThreads",
        "allThreads", "URL", "Latency", "IdleTime", "Connect",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestJtlParser:
    def test_empty_file(self, parser, tmp_path):
        jtl_path = str(tmp_path / "empty.jtl")
        _write_jtl(jtl_path, [])
        result = parser.parse(jtl_path)
        assert result.total_requests == 0
        assert result.throughput_per_sec == 0.0

    def test_single_request(self, parser, tmp_path):
        jtl_path = str(tmp_path / "single.jtl")
        _write_jtl(jtl_path, [{
            "timeStamp": "1700000000000", "elapsed": "150",
            "label": "GET /api", "responseCode": "200",
            "responseMessage": "OK", "threadName": "Thread-1",
            "success": "true", "bytes": "1024", "sentBytes": "128",
            "grpThreads": "1", "allThreads": "1",
            "URL": "http://localhost/api", "Latency": "100",
            "IdleTime": "0", "Connect": "10",
        }])
        result = parser.parse(jtl_path)
        assert result.total_requests == 1
        assert result.total_errors == 0
        assert result.avg_response_ms == 150.0

    def test_multiple_requests_with_errors(self, parser, tmp_path):
        jtl_path = str(tmp_path / "multi.jtl")
        base_ts = 1700000000000
        rows = [
            {
                "timeStamp": str(base_ts), "elapsed": "100",
                "label": "GET /api", "responseCode": "200",
                "responseMessage": "OK", "threadName": "T1",
                "success": "true", "bytes": "500", "sentBytes": "50",
                "grpThreads": "1", "allThreads": "1",
                "URL": "http://localhost/api", "Latency": "80",
                "IdleTime": "0", "Connect": "5",
            },
            {
                "timeStamp": str(base_ts + 1000), "elapsed": "200",
                "label": "POST /api", "responseCode": "201",
                "responseMessage": "Created", "threadName": "T1",
                "success": "true", "bytes": "300", "sentBytes": "200",
                "grpThreads": "1", "allThreads": "1",
                "URL": "http://localhost/api", "Latency": "150",
                "IdleTime": "0", "Connect": "10",
            },
            {
                "timeStamp": str(base_ts + 2000), "elapsed": "500",
                "label": "GET /api", "responseCode": "500",
                "responseMessage": "Error", "threadName": "T1",
                "success": "false", "bytes": "100", "sentBytes": "50",
                "grpThreads": "1", "allThreads": "1",
                "URL": "http://localhost/api", "Latency": "400",
                "IdleTime": "0", "Connect": "5",
            },
        ]
        _write_jtl(jtl_path, rows)
        result = parser.parse(jtl_path)

        assert result.total_requests == 3
        assert result.total_errors == 1
        assert result.error_rate_percent == pytest.approx(33.33, abs=0.01)
        assert result.duration_sec == 2.0
        assert result.throughput_per_sec == pytest.approx(1.5, abs=0.01)

    def test_per_label_breakdown(self, parser, tmp_path):
        jtl_path = str(tmp_path / "labels.jtl")
        base_ts = 1700000000000
        rows = []
        for i in range(10):
            rows.append({
                "timeStamp": str(base_ts + i * 100), "elapsed": str(100 + i * 10),
                "label": "GET /api", "responseCode": "200",
                "responseMessage": "OK", "threadName": "T1",
                "success": "true", "bytes": "500", "sentBytes": "50",
                "grpThreads": "1", "allThreads": "1",
                "URL": "http://localhost/api", "Latency": "80",
                "IdleTime": "0", "Connect": "5",
            })
        for i in range(5):
            rows.append({
                "timeStamp": str(base_ts + 1000 + i * 100), "elapsed": str(200 + i * 20),
                "label": "POST /data", "responseCode": "201",
                "responseMessage": "Created", "threadName": "T1",
                "success": "true", "bytes": "300", "sentBytes": "200",
                "grpThreads": "1", "allThreads": "1",
                "URL": "http://localhost/data", "Latency": "150",
                "IdleTime": "0", "Connect": "10",
            })
        _write_jtl(jtl_path, rows)
        result = parser.parse(jtl_path)

        assert "GET /api" in result.per_label
        assert "POST /data" in result.per_label
        assert result.per_label["GET /api"].count == 10
        assert result.per_label["POST /data"].count == 5


class TestPercentile:
    def test_empty(self):
        assert JtlParser._percentile([], 50) == 0.0

    def test_single(self):
        assert JtlParser._percentile([42.0], 99) == 42.0

    def test_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        p50 = JtlParser._percentile(values, 50)
        assert p50 == 30.0
