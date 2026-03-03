"""Structured logging configuration.

Sets up JSON-formatted logging for production and human-readable logging
for development. Per-test-run log files are supported.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class JSONFormatter(logging.Formatter):
    """JSON-structured log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "test_run_id"):
            log_entry["test_run_id"] = record.test_run_id
        return json.dumps(log_entry)


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_dir: Optional[str] = None,
) -> None:
    """Configure application-wide logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, use JSON formatter; otherwise human-readable
        log_dir: Directory for log files. If None, logs only to stderr.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if json_format:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root_logger.addHandler(console_handler)

    # File handler (if log_dir specified) — human-readable, line-buffered for tailing
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        fh_stream = open(log_path / "orchestrator.log", "a", encoding="utf-8", buffering=1)
        file_handler = logging.StreamHandler(fh_stream)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_logger.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_test_run_logger(test_run_id: int, log_dir: str) -> logging.Logger:
    """Create a per-test-run logger that writes to its own log file.

    Args:
        test_run_id: Test run ID
        log_dir: Base log directory

    Returns:
        Logger instance with a file handler for this test run
    """
    logger = logging.getLogger(f"orchestrator.test_run.{test_run_id}")
    logger.setLevel(logging.DEBUG)

    # Create test run log directory
    run_log_dir = Path(log_dir) / str(test_run_id)
    run_log_dir.mkdir(parents=True, exist_ok=True)

    # File handler for this test run
    file_handler = logging.FileHandler(
        run_log_dir / "test_run.log", encoding="utf-8"
    )
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger
