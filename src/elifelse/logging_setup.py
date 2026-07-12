"""Logging: terminal + rotating file under data/logs."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(logs_dir: Path, level: str = "INFO") -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("elifelse")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:  # already configured (tests create multiple apps)
        return logger

    fh = logging.handlers.RotatingFileHandler(
        logs_dir / "elifelse.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(fh)

    # Quiet noisy third-party loggers (chromadb telemetry etc.)
    for name in ("chromadb", "chromadb.telemetry", "httpx", "websockets"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return logger
