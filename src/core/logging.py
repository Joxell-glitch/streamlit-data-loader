from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from src.config.models import LoggingSettings


def setup_logging(settings: LoggingSettings) -> None:
    level = getattr(logging, settings.level.upper(), logging.INFO)
    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    handlers = []

    Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(settings.log_file, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.setLevel(level)
    handlers.append(file_handler)

    if settings.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        console_handler.setLevel(level)
        handlers.append(console_handler)

    logging.basicConfig(level=level, handlers=handlers, format=log_format)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name)
