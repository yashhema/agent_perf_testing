"""Unit tests for emulator client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.calibration.emulator_client import (
    EmulatorClient,
    EmulatorStats,
    TestConfig,
)


class TestEmulatorStats:
    """Tests for EmulatorStats dataclass."""

    def test_create_stats(self):
        """Test creating EmulatorStats."""
        stats = EmulatorStats(
            cpu_percent=45.5,
            memory_percent=60.0,
            memory_used_mb=1024.0,
            iteration_count=100,
            avg_iteration_ms=50.5,
        )

        assert stats.cpu_percent == 45.5
        assert stats.memory_percent == 60.0
        assert stats.memory_used_mb == 1024.0
        assert stats.iteration_count == 100
        assert stats.avg_iteration_ms == 50.5

    def test_immutability(self):
        """Test EmulatorStats is immutable."""
        stats = EmulatorStats(
            cpu_percent=45.5,
            memory_percent=60.0,
            memory_used_mb=1024.0,
            iteration_count=100,
            avg_iteration_ms=50.5,
        )

        with pytest.raises(AttributeError):
            stats.cpu_percent = 50.0


class TestTestConfig:
    """Tests for TestConfig dataclass."""

    def test_create_with_defaults(self):
        """Test creating TestConfig with defaults."""
        config = TestConfig(
            thread_count=10,
            duration_sec=60,
        )

        assert config.thread_count == 10
        assert config.duration_sec == 60
        assert config.cpu_duration_ms == 100
        assert config.cpu_intensity == 1.0
        assert config.mem_size_mb == 10
        assert config.include_disk is False
        assert config.include_network is False

    def test_create_with_all_values(self):
        """Test creating TestConfig with all values."""
        config = TestConfig(
            thread_count=20,
            duration_sec=120,
            cpu_duration_ms=200,
            cpu_intensity=0.8,
            mem_size_mb=50,
            include_disk=True,
            include_network=True,
        )

        assert config.thread_count == 20
        assert config.duration_sec == 120
        assert config.cpu_duration_ms == 200
        assert config.cpu_intensity == 0.8
        assert config.mem_size_mb == 50
        assert config.include_disk is True
        assert config.include_network is True

    def test_immutability(self):
        """Test TestConfig is immutable."""
        config = TestConfig(thread_count=10, duration_sec=60)

        with pytest.raises(AttributeError):
            config.thread_count = 20


class TestEmulatorClient:
    """Tests for EmulatorClient."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return EmulatorClient(host="localhost", port=8080, timeout=30)

    def test_init(self, client):
        """Test client initialization."""
        assert client._host == "localhost"
        assert client._port == 8080
        assert client._timeout == 30
        assert client._base_url == "http://localhost:8080"

    def test_base_url_property(self, client):
        """Test base_url property."""
        assert client.base_url == "http://localhost:8080"

    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Test health check success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.health_check()

            assert result is True
            mock_client.get.assert_called_once_with("http://localhost:8080/health")

    @pytest.mark.asyncio
    async def test_health_check_failure(self, client):
        """Test health check failure."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self, client):
        """Test health check handles exceptions."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_start_test_success(self, client):
        """Test starting a test."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"test_id": "test-123"}
        mock_response.raise_for_status = MagicMock()

        config = TestConfig(thread_count=10, duration_sec=60)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.start_test(config)

            assert result == "test-123"
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "http://localhost:8080/api/v1/tests/"

    @pytest.mark.asyncio
    async def test_start_test_failure(self, client):
        """Test starting test handles failure."""
        config = TestConfig(thread_count=10, duration_sec=60)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(RuntimeError, match="Failed to start test"):
                await client.start_test(config)

    @pytest.mark.asyncio
    async def test_stop_test_success(self, client):
        """Test stopping a test."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.stop_test("test-123")

            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_test_failure(self, client):
        """Test stopping test handles failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.stop_test("test-123")

            assert result is False

    @pytest.mark.asyncio
    async def test_get_test_status_success(self, client):
        """Test getting test status."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "running", "progress": 50}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_test_status("test-123")

            assert result == {"status": "running", "progress": 50}

    @pytest.mark.asyncio
    async def test_get_test_status_error(self, client):
        """Test getting test status handles error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_test_status("test-123")

            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_system_stats_success(self, client):
        """Test getting system stats."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "cpu_percent": 45.5,
            "memory_percent": 60.0,
            "memory_used_mb": 1024.0,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_system_stats()

            assert isinstance(result, EmulatorStats)
            assert result.cpu_percent == 45.5
            assert result.memory_percent == 60.0
            assert result.memory_used_mb == 1024.0

    @pytest.mark.asyncio
    async def test_get_system_stats_error(self, client):
        """Test getting system stats handles error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_system_stats()

            assert isinstance(result, EmulatorStats)
            assert result.cpu_percent == 0.0
            assert result.memory_percent == 0.0

    @pytest.mark.asyncio
    async def test_get_iteration_stats_success(self, client):
        """Test getting iteration stats."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "sample_count": 100,
            "avg_ms": 50.0,
            "stddev_ms": 5.0,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_iteration_stats()

            assert result["sample_count"] == 100
            assert result["avg_ms"] == 50.0

    @pytest.mark.asyncio
    async def test_clear_iteration_stats_success(self, client):
        """Test clearing iteration stats."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.clear_iteration_stats()

            assert result is True

    @pytest.mark.asyncio
    async def test_clear_iteration_stats_failure(self, client):
        """Test clearing iteration stats handles failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.clear_iteration_stats()

            assert result is False


class TestCalibrationTest:
    """Tests for calibration test methods."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return EmulatorClient(host="localhost", port=8080, timeout=30)

    @pytest.mark.asyncio
    async def test_run_calibration_test(self, client):
        """Test running calibration test."""
        mock_start_response = MagicMock()
        mock_start_response.status_code = 200
        mock_start_response.json.return_value = {"test_id": "test-123"}
        mock_start_response.raise_for_status = MagicMock()

        mock_stats_response = MagicMock()
        mock_stats_response.status_code = 200
        mock_stats_response.json.return_value = {"cpu_percent": 50.0}
        mock_stats_response.raise_for_status = MagicMock()

        mock_clear_response = MagicMock()
        mock_clear_response.status_code = 200

        mock_iter_response = MagicMock()
        mock_iter_response.status_code = 200
        mock_iter_response.json.return_value = {"sample_count": 100, "avg_ms": 50.0}
        mock_iter_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[mock_clear_response, mock_start_response]
            )
            mock_client.get = AsyncMock(
                side_effect=[mock_stats_response, mock_stats_response, mock_iter_response]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                avg_cpu, iteration_stats = await client.run_calibration_test(
                    thread_count=10,
                    duration_sec=10,
                    warmup_sec=5,
                )

                assert avg_cpu == 50.0
                assert iteration_stats is not None

    @pytest.mark.asyncio
    async def test_run_timing_test(self, client):
        """Test running timing test."""
        mock_start_response = MagicMock()
        mock_start_response.status_code = 200
        mock_start_response.json.return_value = {"test_id": "test-123"}
        mock_start_response.raise_for_status = MagicMock()

        mock_clear_response = MagicMock()
        mock_clear_response.status_code = 200

        mock_iter_response = MagicMock()
        mock_iter_response.status_code = 200
        mock_iter_response.json.return_value = {
            "sample_count": 100,
            "avg_ms": 50.0,
            "stddev_ms": 5.0,
        }
        mock_iter_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[mock_clear_response, mock_start_response]
            )
            mock_client.get = AsyncMock(return_value=mock_iter_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                timings = await client.run_timing_test(
                    thread_count=10,
                    iterations=100,
                )

                assert isinstance(timings, list)
                assert len(timings) <= 100

    @pytest.mark.asyncio
    async def test_run_timing_test_error(self, client):
        """Test running timing test handles error."""
        mock_start_response = MagicMock()
        mock_start_response.status_code = 200
        mock_start_response.json.return_value = {"test_id": "test-123"}
        mock_start_response.raise_for_status = MagicMock()

        mock_clear_response = MagicMock()
        mock_clear_response.status_code = 200

        mock_iter_response = MagicMock()
        mock_iter_response.status_code = 200
        mock_iter_response.json.return_value = {"error": "No data available"}
        mock_iter_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[mock_clear_response, mock_start_response]
            )
            mock_client.get = AsyncMock(return_value=mock_iter_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                timings = await client.run_timing_test(
                    thread_count=10,
                    iterations=100,
                )

                assert timings == []
