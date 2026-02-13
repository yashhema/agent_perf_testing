"""Tests for the comparison engine."""

import pytest

from orchestrator.services.comparison import ComparisonData, ComparisonEngine, DeltaMetric
from orchestrator.services.stats_parser import MetricSummary, StatsSummary


@pytest.fixture
def engine():
    return ComparisonEngine(trim_start_sec=30, trim_end_sec=10)


def _make_metric(avg: float) -> MetricSummary:
    return MetricSummary(avg=avg, min=avg - 5, max=avg + 5, p50=avg, p90=avg + 3, p95=avg + 4, p99=avg + 5)


def _make_summary(cpu: float, mem: float) -> StatsSummary:
    return StatsSummary(
        cpu_percent=_make_metric(cpu),
        memory_percent=_make_metric(mem),
        disk_read_rate_mbps=_make_metric(1.0),
        disk_write_rate_mbps=_make_metric(0.5),
        network_sent_rate_mbps=_make_metric(0.2),
        network_recv_rate_mbps=_make_metric(0.1),
    )


class TestComputeDelta:
    def test_positive_delta(self, engine):
        base = _make_summary(cpu=50.0, mem=30.0)
        initial = _make_summary(cpu=55.0, mem=35.0)
        result = engine._compute_delta(target_id=1, load_profile_id=1, base=base, initial=initial)

        assert result.cpu_percent.base_avg == 50.0
        assert result.cpu_percent.initial_avg == 55.0
        assert result.cpu_percent.absolute_delta == 5.0
        assert result.cpu_percent.percentage_delta == 10.0

    def test_negative_delta(self, engine):
        base = _make_summary(cpu=60.0, mem=40.0)
        initial = _make_summary(cpu=55.0, mem=35.0)
        result = engine._compute_delta(target_id=1, load_profile_id=1, base=base, initial=initial)

        assert result.cpu_percent.absolute_delta == -5.0
        assert result.cpu_percent.percentage_delta == pytest.approx(-8.33, abs=0.01)

    def test_zero_base(self, engine):
        """Zero base should not cause division by zero."""
        base = StatsSummary(
            cpu_percent=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
            memory_percent=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
            disk_read_rate_mbps=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
            disk_write_rate_mbps=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
            network_sent_rate_mbps=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
            network_recv_rate_mbps=MetricSummary(avg=0, min=0, max=0, p50=0, p90=0, p95=0, p99=0),
        )
        initial = _make_summary(cpu=55.0, mem=35.0)
        result = engine._compute_delta(target_id=1, load_profile_id=1, base=base, initial=initial)
        assert result.cpu_percent.percentage_delta == 0.0  # safe fallback


class TestAggregateComparisons:
    def test_aggregate_two_targets(self, engine):
        base1 = _make_summary(cpu=50.0, mem=30.0)
        init1 = _make_summary(cpu=55.0, mem=35.0)
        base2 = _make_summary(cpu=60.0, mem=40.0)
        init2 = _make_summary(cpu=65.0, mem=45.0)

        c1 = engine._compute_delta(target_id=1, load_profile_id=1, base=base1, initial=init1)
        c2 = engine._compute_delta(target_id=2, load_profile_id=1, base=base2, initial=init2)

        agg = engine._aggregate_comparisons([c1, c2], load_profile_id=1)
        assert agg.target_id is None
        # Average CPU: base avg = (50+60)/2=55, init avg = (55+65)/2=60, delta=5
        assert agg.cpu_percent.base_avg == 55.0
        assert agg.cpu_percent.initial_avg == 60.0
        assert agg.cpu_percent.absolute_delta == 5.0


class TestGenerateSummaryText:
    def test_increase(self, engine):
        base = _make_summary(cpu=50.0, mem=30.0)
        initial = _make_summary(cpu=55.0, mem=35.0)
        comp = engine._compute_delta(target_id=1, load_profile_id=1, base=base, initial=initial)
        text = engine._generate_summary_text(comp, "server-01", "medium")

        assert "medium" in text
        assert "server-01" in text
        assert "increased" in text
        assert "5.0 percentage points" in text

    def test_decrease(self, engine):
        base = _make_summary(cpu=60.0, mem=40.0)
        initial = _make_summary(cpu=55.0, mem=35.0)
        comp = engine._compute_delta(target_id=1, load_profile_id=1, base=base, initial=initial)
        text = engine._generate_summary_text(comp, "server-01", "high")
        assert "decreased" in text
