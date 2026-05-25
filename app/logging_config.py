"""Application logging setup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import resolve_project_path


LOGGER_NAME = "affiliate_video_machine"


def setup_logging(config: dict[str, Any]) -> logging.Logger:
    """Configure app and error log files, returning the shared logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    app_config = config.get("app", {})
    app_log = resolve_project_path(app_config.get("log_file", "logs/app.log"))
    error_log = resolve_project_path(app_config.get("error_log_file", "logs/errors.log"))

    app_log.parent.mkdir(parents=True, exist_ok=True)
    error_log.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_handler = logging.FileHandler(app_log, encoding="utf-8")
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(error_log, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    logger.info("Logging initialized")
    return logger
