"""Emulator HTTP client.

Matches ORCHESTRATOR_INTERFACES.md Section 1.3 exactly.
One instance per target server. Base URL: http://{ip}:{port}
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class EmulatorClient:
    """HTTP client for emulator REST API."""

    def __init__(self, host: str, port: int = 8080, timeout_sec: int = 30):
        self.base_url = f"http://{host}:{port}"
        self.timeout_sec = timeout_sec
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_sec)

    def close(self):
        self._client.close()

    # --- Health ---

    def health_check(self) -> Dict[str, Any]:
        """GET /health"""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    # --- Configuration ---

    def get_config(self) -> Dict[str, Any]:
        """GET /api/v1/config"""
        resp = self._client.get("/api/v1/config")
        resp.raise_for_status()
        return resp.json()

    def set_config(
        self,
        input_folders: Dict[str, str],
        output_folders: List[str],
        partner: Dict[str, Any],
        stats: Optional[Dict[str, Any]] = None,
        service_monitor_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/config

        Args:
            input_folders: {"normal": path, "confidential": path}
            output_folders: list of output directory paths
            partner: {"fqdn": hostname, "port": port}
            stats: {"output_dir", "max_memory_samples", "default_interval_sec"}
            service_monitor_patterns: regex patterns for agent process monitoring
        """
        body: Dict[str, Any] = {
            "input_folders": input_folders,
            "output_folders": output_folders,
            "partner": partner,
        }
        if stats is not None:
            body["stats"] = stats
        if service_monitor_patterns is not None:
            body["service_monitor_patterns"] = service_monitor_patterns
        resp = self._client.post("/api/v1/config", json=body)
        resp.raise_for_status()
        return resp.json()

    # --- Test Lifecycle ---

    def start_test(
        self,
        test_run_id: str,
        scenario_id: str,
        mode: str,
        collect_interval_sec: float,
        thread_count: int,
        duration_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/tests/start

        Starts stats-only mode (operation=None per Mismatch #4 resolution).
        Returns: TestStatusResponse with test_id.
        """
        body: Dict[str, Any] = {
            "test_run_id": test_run_id,
            "scenario_id": scenario_id,
            "mode": mode,
            "collect_interval_sec": collect_interval_sec,
            "thread_count": thread_count,
        }
        if duration_sec is not None:
            body["duration_sec"] = duration_sec
        # operation is intentionally omitted → stats-only mode
        resp = self._client.post("/api/v1/tests/start", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_test_status(self, test_id: str) -> Dict[str, Any]:
        """GET /api/v1/tests/{test_id}"""
        resp = self._client.get(f"/api/v1/tests/{test_id}")
        resp.raise_for_status()
        return resp.json()

    def stop_test(self, test_id: str, force: bool = False) -> Dict[str, Any]:
        """POST /api/v1/tests/{test_id}/stop"""
        resp = self._client.post(f"/api/v1/tests/{test_id}/stop", json={"force": force})
        resp.raise_for_status()
        return resp.json()

    # --- Stats ---

    def get_recent_stats(self, count: int = 100) -> Dict[str, Any]:
        """GET /api/v1/stats/recent?count={count}

        Used during calibration to poll CPU readings.
        """
        resp = self._client.get("/api/v1/stats/recent", params={"count": count})
        resp.raise_for_status()
        return resp.json()

    def get_all_stats(
        self,
        test_run_id: str,
        scenario_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /api/v1/stats/all?test_run_id={id}&scenario_id={id}

        Returns AllStatsResponse with metadata, samples, summary.
        """
        params: Dict[str, str] = {"test_run_id": test_run_id}
        if scenario_id is not None:
            params["scenario_id"] = scenario_id
        resp = self._client.get("/api/v1/stats/all", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_system_stats(self) -> Dict[str, Any]:
        """GET /api/v1/stats/system

        Returns single StatsSample snapshot (current system state).
        Used during pre-flight validation.
        """
        resp = self._client.get("/api/v1/stats/system")
        resp.raise_for_status()
        return resp.json()
