"""Logger module for gofr-iq

This module provides a flexible logging interface that allows users to
drop in their own logger implementations.

Re-exports logger classes from gofr_common for consistency across GOFR projects.

Usage:
    from app.logger import Logger, DefaultLogger

    # Use the default logger
    logger = DefaultLogger(name="gofr-iq")
    logger.info("Application started")

    # Or implement your own
    class MyCustomLogger(Logger):
        def info(self, message: str, **kwargs):
            # Your custom implementation
            pass
"""

import logging
import os

# Re-export all logger classes from gofr_common
from gofr_common.logger import (
    Logger,
    DefaultLogger,
    ConsoleLogger,
    StructuredLogger,
    JsonFormatter,
    TextFormatter,
)

# Configuration from environment (using GOFR_IQ prefix for consistency)
LOG_LEVEL_STR = os.environ.get("GOFR_IQ_LOG_LEVEL", os.environ.get("GOFR_IQ_LOG_LEVEL", "INFO")).upper()
LOG_FILE = os.environ.get("GOFR_IQ_LOG_FILE", os.environ.get("GOFR_IQ_LOG_FILE"))
LOG_JSON = os.environ.get("GOFR_IQ_LOG_JSON", os.environ.get("GOFR_IQ_LOG_JSON", "false")).lower() == "true"

# Map string level to logging constant
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# Shared logger instance
session_logger: Logger = StructuredLogger(
    name="gofr-iq",
    level=LOG_LEVEL,
    log_file=LOG_FILE,
    json_format=LOG_JSON
)

__all__ = [
    "Logger",
    "DefaultLogger",
    "ConsoleLogger",
    "StructuredLogger",
    "JsonFormatter",
    "TextFormatter",
    "session_logger",
]
