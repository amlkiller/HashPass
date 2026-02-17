"""Centralized logging configuration for HashPass"""

import logging
import os
import sys


def setup_logging() -> None:
    """
    Configure the root logger for the application.

    - StreamHandler to sys.stdout (matches previous print() behavior)
    - Format: %(asctime)s [%(name)s] %(levelname)s %(message)s
    - Default level: INFO, configurable via HASHPASS_LOG_LEVEL env var
    """
    level_name = os.getenv("HASHPASS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
