"""Tests for pool allocation, network endpoints, and JMX template changes.

Covers:
  - MemoryPoolService chunked allocation (via emulator client mock)
  - _setup_pool() dynamic RAM calculation (60% steady, 40% file-heavy)
  - _build_work_extra_properties() returns correct JMeter flags
  - CalibrationContext.extra_properties propagation to JMeter start
  - Emulator deployment to loadgen for /networkclient partner
  - JMX templates have correct ThroughputController percentages
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ── Paths ──
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "jmx"


# ═══════════════════════════════════════════════════════════════════════
# 1. Pool allocation: _setup_pool() and _build_work_extra_properties()
# ═══════════════════════════════════════════════════════════════════════

class TestSetupPool:
    """Test BaselineOrchestrator._setup_pool() with mocked EmulatorClient."""

    def _get_orchestrator_class(self):
        from orchestrator.core.baseline_orchestrator import BaselineOrchestrator
        return BaselineOrchestrator

    def _make_em_client(self, total_mb: float):
        """Create a mock EmulatorClient that returns given total RAM."""
        # Simulate: available = 70% of total, used = 30% of total
        avail_mb = round(total_mb * 0.7, 1)
        used_mb = round(total_mb * 0.3, 1)
        em = MagicMock()
        em.get_system_stats.return_value = {
            "memory_available_mb": avail_mb,
            "memory_used_mb": used_mb,
        }
        em.allocate_pool.return_value = {"allocated": True, "size_bytes": 0}
        return em

    def test_steady_allocates_60_percent(self):
        """server_steady should allocate ~60% of total RAM."""
        from orchestrator.models.enums import TemplateType
        Bo = self._get_orchestrator_class()

        em = self._make_em_client(8000)  # 8 GB
        Bo._setup_pool(em, TemplateType.server_steady)

        em.allocate_pool.assert_called_once()
        pool_gb = em.allocate_pool.call_args[0][0]
        # 8000 * 0.6 / 1024 ≈ 4.7
        assert 4.5 <= pool_gb <= 5.0, f"Expected ~4.7 GB, got {pool_gb}"

    def test_file_heavy_allocates_40_percent(self):
        """server_file_heavy should allocate ~40% of total RAM."""
        from orchestrator.models.enums import TemplateType
        Bo = self._get_orchestrator_class()

        em = self._make_em_client(8000)  # 8 GB
        Bo._setup_pool(em, TemplateType.server_file_heavy)

        em.allocate_pool.assert_called_once()
        pool_gb = em.allocate_pool.call_args[0][0]
        # 8000 * 0.4 / 1024 ≈ 3.1
        assert 3.0 <= pool_gb <= 3.3, f"Expected ~3.1 GB, got {pool_gb}"

    def test_small_ram_gets_sanity_floor(self):
        """Very small RAM should still allocate at least 0.1 GB."""
        from orchestrator.models.enums import TemplateType
        Bo = self._get_orchestrator_class()

        em = self._make_em_client(100)  # 100 MB — tiny VM
        Bo._setup_pool(em, TemplateType.server_steady)

        pool_gb = em.allocate_pool.call_args[0][0]
        assert pool_gb >= 0.1, f"Expected >= 0.1 GB, got {pool_gb}"

    def test_pool_ram_percent_dict_entries(self):
        """_POOL_RAM_PERCENT must have entries for steady and file_heavy."""
        from orchestrator.models.enums import TemplateType
        Bo = self._get_orchestrator_class()

        assert TemplateType.server_steady in Bo._POOL_RAM_PERCENT
        assert TemplateType.server_file_heavy in Bo._POOL_RAM_PERCENT
        assert Bo._POOL_RAM_PERCENT[TemplateType.server_steady] == 0.6
        assert Bo._POOL_RAM_PERCENT[TemplateType.server_file_heavy] == 0.4

    def test_server_normal_not_in_pool_templates(self):
        """server_normal should NOT be in pool templates."""
        from orchestrator.models.enums import TemplateType
        Bo = self._get_orchestrator_class()

        assert TemplateType.server_normal not in Bo._POOL_RAM_PERCENT


class TestBuildWorkExtraProperties:
    """Test _build_work_extra_properties() returns correct JMeter -J flags."""

    def test_returns_expected_keys(self):
        from orchestrator.core.baseline_orchestrator import BaselineOrchestrator
        props = BaselineOrchestrator._build_work_extra_properties()

        assert "cpu_ms" in props
        assert "intensity" in props
        assert "touch_mb" in props
        # pool_gb must NOT be here — pool is allocated directly
        assert "pool_gb" not in props

    def test_values_are_strings(self):
        from orchestrator.core.baseline_orchestrator import BaselineOrchestrator
        props = BaselineOrchestrator._build_work_extra_properties()

        for k, v in props.items():
            assert isinstance(v, str), f"{k} should be str, got {type(v)}"


# ═══════════════════════════════════════════════════════════════════════
# 2. CalibrationContext extra_properties propagation
# ═══════════════════════════════════════════════════════════════════════

class TestCalibrationContextExtraProps:
    """Verify CalibrationContext accepts extra_properties and it propagates."""

    def test_extra_properties_field_exists(self):
        from orchestrator.core.calibration import CalibrationContext
        ctx = CalibrationContext(
            server=MagicMock(),
            load_profile=MagicMock(),
            emulator_client=MagicMock(),
            jmeter_controller=MagicMock(),
            jmx_path="/tmp/test.jmx",
            ops_sequence_path="/tmp/ops.csv",
            emulator_port=8080,
            extra_properties={"cpu_ms": "10", "intensity": "0.8"},
        )
        assert ctx.extra_properties == {"cpu_ms": "10", "intensity": "0.8"}

    def test_extra_properties_defaults_none(self):
        from orchestrator.core.calibration import CalibrationContext
        ctx = CalibrationContext(
            server=MagicMock(),
            load_profile=MagicMock(),
            emulator_client=MagicMock(),
            jmeter_controller=MagicMock(),
            jmx_path="/tmp/test.jmx",
            ops_sequence_path="/tmp/ops.csv",
            emulator_port=8080,
        )
        assert ctx.extra_properties is None


# ═══════════════════════════════════════════════════════════════════════
# 3. JMeterController.start() passes extra_properties
# ═══════════════════════════════════════════════════════════════════════

class TestJMeterControllerExtraProperties:
    """Verify JMeterController.start() includes extra_properties as -J flags."""

    def test_extra_properties_in_command(self):
        from orchestrator.infra.jmeter_controller import JMeterController

        executor = MagicMock()
        executor.execute.return_value = MagicMock(success=True, stdout="12345\n")

        ctrl = JMeterController(executor=executor, jmeter_bin="/opt/jmeter/bin/jmeter")
        ctrl.start(
            jmx_path="/tmp/test.jmx",
            jtl_path="/tmp/results.jtl",
            log_path="/tmp/jmeter.log",
            thread_count=5,
            ramp_up_sec=10,
            duration_sec=60,
            target_host="10.0.0.92",
            target_port=8080,
            extra_properties={"cpu_ms": "10", "intensity": "0.8", "touch_mb": "1.0"},
        )

        cmd = executor.execute.call_args[0][0]
        assert "-Jcpu_ms=10" in cmd
        assert "-Jintensity=0.8" in cmd
        assert "-Jtouch_mb=1.0" in cmd
        # pool_gb should NOT be in the command
        assert "-Jpool_gb" not in cmd

    def test_no_extra_properties_no_extra_flags(self):
        from orchestrator.infra.jmeter_controller import JMeterController

        executor = MagicMock()
        executor.execute.return_value = MagicMock(success=True, stdout="12345\n")

        ctrl = JMeterController(executor=executor, jmeter_bin="/opt/jmeter/bin/jmeter")
        ctrl.start(
            jmx_path="/tmp/test.jmx",
            jtl_path="/tmp/results.jtl",
            log_path="/tmp/jmeter.log",
            thread_count=5,
            ramp_up_sec=10,
            duration_sec=60,
            target_host="10.0.0.92",
            target_port=8080,
        )

        cmd = executor.execute.call_args[0][0]
        assert "-Jcpu_ms" not in cmd
        assert "-Jintensity" not in cmd


# ═══════════════════════════════════════════════════════════════════════
# 4. EmulatorClient.allocate_pool() and destroy_pool()
# ═══════════════════════════════════════════════════════════════════════

class TestEmulatorClientPool:
    """Verify EmulatorClient has pool methods with correct HTTP calls."""

    def test_allocate_pool_method_exists(self):
        from orchestrator.infra.emulator_client import EmulatorClient
        assert hasattr(EmulatorClient, "allocate_pool")
        assert hasattr(EmulatorClient, "destroy_pool")

    @patch("orchestrator.infra.emulator_client.httpx.Client")
    def test_allocate_pool_sends_correct_request(self, mock_client_cls):
        from orchestrator.infra.emulator_client import EmulatorClient

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"allocated": True, "size_bytes": 4831838208}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        em = EmulatorClient(host="10.0.0.92", port=8080)
        result = em.allocate_pool(4.5)

        mock_client.post.assert_called_once_with(
            "/api/v1/config/pool",
            json={"size_gb": 4.5},
            timeout=120,
        )
        assert result["allocated"] is True


# ═══════════════════════════════════════════════════════════════════════
# 5. JMX template validation
# ═══════════════════════════════════════════════════════════════════════

class TestJMXTemplates:
    """Validate JMX templates have correct ThroughputController percentages."""

    @staticmethod
    def _parse_throughput_controllers(jmx_path: str) -> dict:
        """Parse JMX and return {testname: percentage} for all ThroughputControllers."""
        tree = ET.parse(jmx_path)
        root = tree.getroot()
        result = {}
        for tc in root.iter("ThroughputController"):
            name = tc.get("testname", "")
            for prop in tc.iter("stringProp"):
                if prop.get("name") == "ThroughputController.percentThroughput":
                    result[name] = float(prop.text)
        return result

    @staticmethod
    def _parse_sampler_paths(jmx_path: str) -> list:
        """Get all HTTP sampler paths from JMX."""
        tree = ET.parse(jmx_path)
        root = tree.getroot()
        paths = []
        for sampler in root.iter("HTTPSamplerProxy"):
            for prop in sampler.iter("stringProp"):
                if prop.get("name") == "HTTPSampler.path" and prop.text:
                    paths.append(prop.text)
        return paths

    @staticmethod
    def _has_setup_thread_group(jmx_path: str) -> bool:
        """Check if JMX has a SetupThreadGroup."""
        tree = ET.parse(jmx_path)
        root = tree.getroot()
        return len(list(root.iter("SetupThreadGroup"))) > 0

    def test_steady_ratios(self):
        jmx = str(ARTIFACTS_DIR / "server-steady.jmx")
        ratios = self._parse_throughput_controllers(jmx)

        assert ratios.get("Work (68%)") == 68.0
        assert ratios.get("File Create (10%)") == 10.0
        assert ratios.get("Network (20%)") == 20.0
        assert ratios.get("CPU Spike (1%)") == 1.0
        assert ratios.get("Suspicious (1%)") == 1.0
        assert sum(ratios.values()) == 100.0

    def test_file_heavy_ratios(self):
        jmx = str(ARTIFACTS_DIR / "server-file-heavy.jmx")
        ratios = self._parse_throughput_controllers(jmx)

        assert ratios.get("Work (48%)") == 48.0
        assert ratios.get("File Create (30%)") == 30.0
        assert ratios.get("Network (20%)") == 20.0
        assert ratios.get("CPU Spike (1%)") == 1.0
        assert ratios.get("Suspicious (1%)") == 1.0
        assert sum(ratios.values()) == 100.0

    def test_steady_no_setup_thread(self):
        """server-steady.jmx should NOT have a setUp thread group (pool allocated by orchestrator)."""
        jmx = str(ARTIFACTS_DIR / "server-steady.jmx")
        assert not self._has_setup_thread_group(jmx)

    def test_file_heavy_no_setup_thread(self):
        """server-file-heavy.jmx should NOT have a setUp thread group."""
        jmx = str(ARTIFACTS_DIR / "server-file-heavy.jmx")
        assert not self._has_setup_thread_group(jmx)

    def test_steady_uses_correct_endpoints(self):
        jmx = str(ARTIFACTS_DIR / "server-steady.jmx")
        paths = self._parse_sampler_paths(jmx)

        assert "/api/v1/operations/work" in paths
        assert "/api/v1/operations/file" in paths
        assert "/api/v1/operations/networkclient" in paths
        assert "/api/v1/operations/cpu" in paths
        assert "/api/v1/operations/suspicious" in paths
        # Old endpoints should NOT be present
        assert "/api/v1/operations/mem" not in paths
        assert "/api/v1/operations/net" not in paths
        assert "/api/v1/config/pool" not in paths

    def test_file_heavy_uses_correct_endpoints(self):
        jmx = str(ARTIFACTS_DIR / "server-file-heavy.jmx")
        paths = self._parse_sampler_paths(jmx)

        assert "/api/v1/operations/work" in paths
        assert "/api/v1/operations/file" in paths
        assert "/api/v1/operations/networkclient" in paths
        assert "/api/v1/operations/cpu" in paths
        assert "/api/v1/operations/suspicious" in paths
        assert "/api/v1/operations/mem" not in paths
        assert "/api/v1/operations/net" not in paths

    def test_steady_has_work_extra_props_vars(self):
        """server-steady.jmx should have CPU_MS, INTENSITY, TOUCH_MB user variables."""
        tree = ET.parse(str(ARTIFACTS_DIR / "server-steady.jmx"))
        root = tree.getroot()
        var_names = set()
        for args in root.iter("Arguments"):
            for ep in args.iter("elementProp"):
                name = ep.get("name", "")
                if name:
                    var_names.add(name)

        assert "CPU_MS" in var_names
        assert "INTENSITY" in var_names
        assert "TOUCH_MB" in var_names

    def test_file_heavy_has_zip_percent_var(self):
        """server-file-heavy.jmx should have ZIP_PERCENT for file randomization."""
        tree = ET.parse(str(ARTIFACTS_DIR / "server-file-heavy.jmx"))
        root = tree.getroot()
        var_names = set()
        for args in root.iter("Arguments"):
            for ep in args.iter("elementProp"):
                name = ep.get("name", "")
                if name:
                    var_names.add(name)

        assert "ZIP_PERCENT" in var_names


# ═══════════════════════════════════════════════════════════════════════
# 6. Java source validation (file existence and key patterns)
# ═══════════════════════════════════════════════════════════════════════

EMULATOR_SRC = Path(__file__).resolve().parents[2] / "emulator_java" / "src" / "main" / "java" / "com" / "emulator"


class TestJavaSourceFiles:
    """Verify new Java source files exist and contain expected patterns."""

    def test_network_client_request_exists(self):
        f = EMULATOR_SRC / "model" / "request" / "NetworkClientRequest.java"
        assert f.exists(), f"Missing: {f}"
        content = f.read_text()
        assert "req_size_kb" in content
        assert "resp_size_kb" in content

    def test_network_server_request_exists(self):
        f = EMULATOR_SRC / "model" / "request" / "NetworkServerRequest.java"
        assert f.exists(), f"Missing: {f}"
        content = f.read_text()
        assert "payload" in content
        assert "resp_size_kb" in content

    def test_network_client_service_exists(self):
        f = EMULATOR_SRC / "service" / "NetworkClientService.java"
        assert f.exists(), f"Missing: {f}"
        content = f.read_text()
        assert "/api/v1/operations/networkserver" in content
        assert "ConfigService" in content
        assert "getPartnerFqdn" in content

    def test_memory_pool_service_uses_chunked_arrays(self):
        f = EMULATOR_SRC / "service" / "MemoryPoolService.java"
        content = f.read_text()
        assert "byte[][] chunks" in content or "byte[][]" in content
        assert "MAX_CHUNK_BYTES" in content
        # Single byte[] pool should NOT be present
        assert "private volatile byte[] pool;" not in content

    def test_operations_controller_has_new_endpoints(self):
        f = EMULATOR_SRC / "controller" / "OperationsController.java"
        content = f.read_text()
        assert "/networkclient" in content
        assert "/networkserver" in content
        assert "NetworkClientService" in content
        assert "NetworkClientRequest" in content
        assert "NetworkServerRequest" in content
