"""Tests for stats parser and trimming logic."""

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.services.stats_parser import MetricSummary, StatsParser, StatsSummary


@pytest.fixture
def parser():
    return StatsParser()


class TestTrimSamples:
    def test_empty_samples(self, parser):
        assert parser.trim_samples([], 30, 10) == []

    def test_no_trim_needed(self, parser):
        samples = [
            {"elapsed_sec": 30, "cpu_percent": 50},
            {"elapsed_sec": 60, "cpu_percent": 55},
            {"elapsed_sec": 90, "cpu_percent": 52},
        ]
        result = parser.trim_samples(samples, 0, 0)
        assert len(result) == 3

    def test_trim_warmup(self, parser):
        samples = [
            {"elapsed_sec": 5, "cpu_percent": 10},   # warmup
            {"elapsed_sec": 15, "cpu_percent": 20},  # warmup
            {"elapsed_sec": 35, "cpu_percent": 50},  # keep
            {"elapsed_sec": 60, "cpu_percent": 55},  # keep
        ]
        result = parser.trim_samples(samples, trim_start_sec=30, trim_end_sec=0)
        assert len(result) == 2
        assert result[0]["elapsed_sec"] == 35

    def test_trim_cooldown(self, parser):
        samples = [
            {"elapsed_sec": 0, "cpu_percent": 50},
            {"elapsed_sec": 30, "cpu_percent": 55},
            {"elapsed_sec": 55, "cpu_percent": 52},  # cooldown (within 10s of end at 60)
            {"elapsed_sec": 60, "cpu_percent": 10},  # cooldown
        ]
        result = parser.trim_samples(samples, trim_start_sec=0, trim_end_sec=10)
        assert len(result) == 2
        assert result[-1]["elapsed_sec"] == 30

    def test_trim_both(self, parser):
        samples = [
            {"elapsed_sec": 5, "cpu_percent": 10},   # warmup
            {"elapsed_sec": 35, "cpu_percent": 50},  # keep
            {"elapsed_sec": 60, "cpu_percent": 55},  # keep
            {"elapsed_sec": 95, "cpu_percent": 52},  # cooldown
        ]
        result = parser.trim_samples(samples, trim_start_sec=30, trim_end_sec=10)
        assert len(result) == 2


class TestComputeSummary:
    def test_empty_samples(self, parser):
        summary = parser.compute_summary([])
        assert summary.cpu_percent.avg == 0
        assert summary.memory_percent.avg == 0

    def test_single_sample(self, parser):
        samples = [{
            "cpu_percent": 50.0,
            "memory_percent": 30.0,
            "disk_read_rate_mbps": 1.0,
            "disk_write_rate_mbps": 2.0,
            "network_sent_rate_mbps": 0.5,
            "network_recv_rate_mbps": 0.3,
        }]
        summary = parser.compute_summary(samples)
        assert summary.cpu_percent.avg == 50.0
        assert summary.cpu_percent.min == 50.0
        assert summary.cpu_percent.max == 50.0

    def test_multiple_samples(self, parser):
        samples = [
            {
                "cpu_percent": 40.0, "memory_percent": 20.0,
                "disk_read_rate_mbps": 1.0, "disk_write_rate_mbps": 0.5,
                "network_sent_rate_mbps": 0.1, "network_recv_rate_mbps": 0.2,
            },
            {
                "cpu_percent": 60.0, "memory_percent": 40.0,
                "disk_read_rate_mbps": 3.0, "disk_write_rate_mbps": 1.5,
                "network_sent_rate_mbps": 0.3, "network_recv_rate_mbps": 0.4,
            },
        ]
        summary = parser.compute_summary(samples)
        assert summary.cpu_percent.avg == 50.0
        assert summary.cpu_percent.min == 40.0
        assert summary.cpu_percent.max == 60.0
        assert summary.memory_percent.avg == 30.0


class TestPercentile:
    def test_empty(self, parser):
        assert parser._percentile([], 50) == 0.0

    def test_single_value(self, parser):
        assert parser._percentile([42.0], 50) == 42.0
        assert parser._percentile([42.0], 99) == 42.0

    def test_two_values(self, parser):
        result = parser._percentile([10.0, 20.0], 50)
        assert result == 15.0  # linear interpolation at midpoint

    def test_p90(self, parser):
        values = list(range(1, 101))  # 1..100
        float_values = [float(v) for v in values]
        p90 = parser._percentile(float_values, 90)
        assert p90 == pytest.approx(90.1, abs=0.1)


class TestParseStatsFile:
    def test_parse(self, parser, tmp_path):
        data = {
            "metadata": {"test_run_id": "run-1"},
            "samples": [
                {"elapsed_sec": 5, "cpu_percent": 50},
                {"elapsed_sec": 10, "cpu_percent": 55},
            ],
            "summary": {},
        }
        file_path = tmp_path / "stats.json"
        with open(file_path, "w") as f:
            json.dump(data, f)

        result = parser.parse_stats_file(str(file_path))
        assert result["metadata"]["test_run_id"] == "run-1"
        assert len(result["samples"]) == 2
