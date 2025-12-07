"""Logger module for gofr-iq

This module provides a flexible logging interface that allows users to
drop in their own logger implementations.

Usage:
    from app.logger import Logger, DefaultLogger

    # Use the default logger
    logger = DefaultLogger()
    logger.info("Application started")

    # Or implement your own
    class MyCustomLogger(Logger):
        def info(self, message: str, **kwargs):
            # Your custom implementation
            pass
"""

# Re-export Logger from gofr_common for type compatibility
from gofr_common.logger import Logger
from .default_logger import DefaultLogger
from .console_logger import ConsoleLogger
from .structured_logger import StructuredLogger
import logging
import os

# Configuration from environment
LOG_LEVEL_STR = os.environ.get("GOFRIQ_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("GOFRIQ_LOG_FILE")
LOG_JSON = os.environ.get("GOFRIQ_LOG_JSON", "false").lower() == "true"

# Map string level to logging constant
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# Shared logger instance
session_logger: Logger = StructuredLogger(
    level=LOG_LEVEL,
    log_file=LOG_FILE,
    json_format=LOG_JSON
)

__all__ = [
    "Logger",
    "DefaultLogger",
    "ConsoleLogger",
    "StructuredLogger",
    "session_logger",
]
