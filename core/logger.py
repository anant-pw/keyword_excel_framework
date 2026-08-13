"""
Centralized logger setup. One log file per run (timestamped) under logs/,
plus console output. Import get_logger(__name__) anywhere in the framework
rather than configuring the logging module per-file.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
# PID included so parallel worker processes (see --workers in tests/runner.py)
# never collide on the same log file - two workers starting in the same
# second would otherwise interleave writes into one file.
_LOG_FILE = _LOG_DIR / f"run_{_RUN_TIMESTAMP}_pid{os.getpid()}.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root():
    global _configured
    if _configured:
        return
    root = logging.getLogger("keyword_framework")
    root.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(f"keyword_framework.{name}")


def current_log_file() -> Path:
    return _LOG_FILE
