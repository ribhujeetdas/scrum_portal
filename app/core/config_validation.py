from __future__ import annotations

import logging
from typing import Iterable

from flask import Flask


REQUIRED_INTEGRATION_SETTINGS = (
    "JIRA_BASE_URL",
    "TABLEAU_BASE_URL",
)


def collect_config_warnings(app: Flask) -> list[str]:
    warnings: list[str] = []
    for key in REQUIRED_INTEGRATION_SETTINGS:
        if not str(app.config.get(key, "") or "").strip():
            warnings.append(f"{key} is missing.")
    return warnings


def log_config_warnings(app: Flask, warnings: Iterable[str] | None = None) -> None:
    logger = logging.getLogger("app.config")
    for warning in list(warnings if warnings is not None else collect_config_warnings(app)):
        logger.warning("config warning: %s", warning, extra={"event": "config.warning"})
