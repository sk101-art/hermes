import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class SecretRedactingFilter(logging.Filter):
    """Redacts sensitive tokens, credentials, and API keys from log records."""

    PATTERNS = [
        re.compile(r"ghp_[a-zA-Z0-9]{20,}", re.IGNORECASE),
        re.compile(r"github_pat_[a-zA-Z0-9_]{20,}", re.IGNORECASE),
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE),
        re.compile(r"(api_key|token|password|secret)=([a-zA-Z0-9_\-\.]{8,})", re.IGNORECASE),
        re.compile(r"(PRIVATE KEY|BEGIN OPENSSH PRIVATE KEY|BEGIN RSA PRIVATE KEY)", re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.redact(a) if isinstance(a, str) else a for a in record.args)
        return True

    @classmethod
    def redact(cls, text: str) -> str:
        res = text
        for pattern in cls.PATTERNS:
            res = pattern.sub("[REDACTED_SECRET]", res)
        return res


def setup_runtime_logging(
    log_file: str = "logs/hermes.log",
    log_level: str = "INFO",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    console: bool = True,
) -> logging.Logger:
    """Configures structured rotating file logging and console logging."""
    logger = logging.getLogger("hermes")
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redact_filter = SecretRedactingFilter()

    # File Handler
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redact_filter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[Warning] Failed to initialize file logger on {log_file}: {e}")

    # Console Handler
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redact_filter)
        logger.addHandler(console_handler)

    return logger
