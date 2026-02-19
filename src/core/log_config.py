"""Centralized logging configuration for HashPass"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


def setup_logging() -> None:
    """
    Configure the root logger for the application.

    - StreamHandler to sys.stdout (matches previous print() behavior)
    - TimedRotatingFileHandler to log/hashpass.log (daily rotation, 30 days retention)
    - Format: %(asctime)s [%(name)s] %(levelname)s %(message)s
    - Default level: INFO, configurable via HASHPASS_LOG_LEVEL env var
    """
    level_name = os.getenv("HASHPASS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "hashpass.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
        delay=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
