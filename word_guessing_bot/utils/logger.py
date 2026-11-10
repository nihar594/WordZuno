"""Structured (JSON-lines) logging to console and a rotating file."""
from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            data.update(extra)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    fmt = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_dir:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / "bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
            )
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            root.warning("file logging disabled (cannot write to %s)", log_dir)
    # keep third-party noise down (httpx logs the bot token in URLs at INFO!)
    for noisy in ("httpx", "httpcore", "telegram.ext.Application"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
