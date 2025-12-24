"""Unit tests for JTL result parser."""

import pytest
from pathlib import Path

from app.jmeter.result_parser import JTLParser, JTLSummary, OperationStats


class TestJTLParser:
    """Unit tests for JTL result parser."""

    @pytest.fixture
    def sample_jtl(self, tmp_path) -> str:
        """Create sample JTL file."""
        jtl_path = tmp_path / "results.jtl"
        jtl_content = """timeStamp,elapsed,label,responseCode,responseMessage,threadName,success,bytes
1703001000000,150,CPU_Operation,200,OK,Thread-1,true,100
1703001000200,180,CPU_Operation,200,OK,Thread-1,true,100
1703001000400,120,MEM_Operation,200,OK,Thread-1,true,100
1703001000600,200,DISK_Operation,500,Error,Thread-1,false,0
"""
        jtl_path.write_text(jtl_content)
        return str(jtl_path)

    @pytest.fixture
    def sample_jtl_no_header(self, tmp_path) -> str:
        """Create sample JTL file without header."""
        jtl_path = tmp_path / "results_no_header.jtl"
        jtl_content = """1703001000000,150,CPU_Operation,200,OK,Thread-1,true,100
1703001000200,180,CPU_Operation,200,OK,Thread-1,true,100
"""
        jtl_path.write_text(jtl_content)
        return str(jtl_path)

    @pytest.fixture
    def empty_jtl(self, tmp_path) -> str:
        """Create empty JTL file with only header."""
        jtl_path = tmp_path / "empty.jtl"
        jtl_content = """timeStamp,elapsed,label,responseCode,responseMessage,threadName,success,bytes
"""
        jtl_path.write_text(jtl_content)
        return str(jtl_path)

    def test_parse_jtl_summary(self, sample_jtl: str) -> None:
        """Test parsing JTL summary statistics."""
        result = JTLParser.parse_jtl(sample_jtl)

        assert "summary" in result
        assert result["summary"]["total_samples"] == 4
        assert result["summary"]["success_count"] == 3
        assert result["summary"]["failure_count"] == 1
        assert result["summary"]["error_rate"] == 25.0

    def test_parse_jtl_per_operation(self, sample_jtl: str) -> None:
        """Test parsing per-operation statistics."""
        result = JTLParser.parse_jtl(sample_jtl)

        assert "per_operation" in result
        assert "CPU_Operation" in result["per_operation"]
        assert result["per_operation"]["CPU_Operation"]["count"] == 2
        assert result["per_operation"]["MEM_Operation"]["count"] == 1
        assert result["per_operation"]["DISK_Operation"]["count"] == 1

    def test_parse_jtl_file_not_found(self, tmp_path) -> None:
        """Test parsing non-existent JTL file."""
        result = JTLParser.parse_jtl(str(tmp_path / "nonexistent.jtl"))

        assert "error" in result

    def test_parse_jtl_to_summary(self, sample_jtl: str) -> None:
        """Test parsing JTL to summary object."""
        summary = JTLParser.parse_jtl_to_summary(sample_jtl)

        assert isinstance(summary, JTLSummary)
        assert summary.total_samples == 4
        assert summary.success_count == 3
        assert summary.failure_count == 1
        assert len(summary.per_operation) == 3

    def test_parse_jtl_no_header(self, sample_jtl_no_header: str) -> None:
        """Test parsing JTL file without header."""
        result = JTLParser.parse_jtl(sample_jtl_no_header)

        assert "summary" in result
        assert result["summary"]["total_samples"] == 2

    def test_parse_empty_jtl(self, empty_jtl: str) -> None:
        """Test parsing empty JTL file."""
        result = JTLParser.parse_jtl(empty_jtl)

        assert "error" in result or result.get("summary", {}).get("total_samples", 0) == 0

    def test_parse_jtl_response_times(self, sample_jtl: str) -> None:
        """Test response time statistics."""
        result = JTLParser.parse_jtl(sample_jtl)

        summary = result["summary"]
        assert summary["min_response_time_ms"] == 120
        assert summary["max_response_time_ms"] == 200
        # Average of 150, 180, 120, 200 = 162.5
        assert summary["avg_response_time_ms"] == pytest.approx(162.5)

    def test_parse_jtl_operation_error_rate(self, sample_jtl: str) -> None:
        """Test per-operation error rates."""
        result = JTLParser.parse_jtl(sample_jtl)

        per_op = result["per_operation"]
        # CPU_Operation: 2 successes, 0 failures = 0% error
        assert per_op["CPU_Operation"]["error_rate"] == 0.0
        # DISK_Operation: 0 successes, 1 failure = 100% error
        assert per_op["DISK_Operation"]["error_rate"] == 100.0

    def test_percentile_calculation(self) -> None:
        """Test percentile calculation."""
        # Test with known values
        data = list(range(1, 101))  # 1 to 100

        p50 = JTLParser._percentile(data, 50)
        p90 = JTLParser._percentile(data, 90)
        p99 = JTLParser._percentile(data, 99)

        assert p50 == pytest.approx(50.5, rel=0.1)
        assert p90 == pytest.approx(90.1, rel=0.1)
        assert p99 == pytest.approx(99.01, rel=0.1)

    def test_percentile_empty_data(self) -> None:
        """Test percentile with empty data."""
        result = JTLParser._percentile([], 50)
        assert result == 0.0

    def test_percentile_single_value(self) -> None:
        """Test percentile with single value."""
        result = JTLParser._percentile([100], 50)
        assert result == 100.0


class TestOperationStats:
    """Unit tests for OperationStats."""

    def test_operation_stats_creation(self) -> None:
        """Test creating OperationStats."""
        stats = OperationStats(
            operation="CPU_Operation",
            count=100,
            success_count=95,
            failure_count=5,
            error_rate=5.0,
            avg_response_time_ms=150.0,
            min_response_time_ms=100.0,
            max_response_time_ms=300.0,
            stddev_ms=25.0,
            p50_ms=140.0,
            p90_ms=200.0,
            p99_ms=280.0,
            throughput=10.0,
        )

        assert stats.operation == "CPU_Operation"
        assert stats.count == 100
        assert stats.error_rate == 5.0

    def test_operation_stats_is_frozen(self) -> None:
        """Test that OperationStats is immutable."""
        stats = OperationStats(
            operation="test",
            count=1,
            success_count=1,
            failure_count=0,
            error_rate=0.0,
            avg_response_time_ms=100.0,
            min_response_time_ms=100.0,
            max_response_time_ms=100.0,
            stddev_ms=0.0,
            p50_ms=100.0,
            p90_ms=100.0,
            p99_ms=100.0,
            throughput=1.0,
        )

        with pytest.raises(AttributeError):
            stats.count = 2


class TestJTLSummary:
    """Unit tests for JTLSummary."""

    def test_jtl_summary_creation(self) -> None:
        """Test creating JTLSummary."""
        summary = JTLSummary(
            total_samples=100,
            success_count=95,
            failure_count=5,
            error_rate=5.0,
            avg_response_time_ms=150.0,
            min_response_time_ms=100.0,
            max_response_time_ms=300.0,
            duration_sec=60.0,
            throughput=1.67,
        )

        assert summary.total_samples == 100
        assert summary.error_rate == 5.0
        assert summary.throughput == 1.67

    def test_jtl_summary_with_operations(self) -> None:
        """Test JTLSummary with per-operation stats."""
        ops = [
            OperationStats(
                operation="op1",
                count=50,
                success_count=50,
                failure_count=0,
                error_rate=0.0,
                avg_response_time_ms=100.0,
                min_response_time_ms=80.0,
                max_response_time_ms=120.0,
                stddev_ms=10.0,
                p50_ms=100.0,
                p90_ms=110.0,
                p99_ms=118.0,
                throughput=0.83,
            )
        ]

        summary = JTLSummary(
            total_samples=50,
            success_count=50,
            failure_count=0,
            error_rate=0.0,
            avg_response_time_ms=100.0,
            min_response_time_ms=80.0,
            max_response_time_ms=120.0,
            duration_sec=60.0,
            throughput=0.83,
            per_operation=ops,
        )

        assert len(summary.per_operation) == 1
        assert summary.per_operation[0].operation == "op1"
