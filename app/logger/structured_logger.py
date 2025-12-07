import logging
import json
import sys
import uuid
from typing import Any, Optional
from datetime import datetime
from gofr_common.logger import Logger

class JsonFormatter(logging.Formatter):
    """JSON formatter for logging records"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        # Add session_id if present
        # Use getattr to avoid static type checking errors since session_id is dynamically added
        session_id = getattr(record, "session_id", None)
        if session_id:
            log_data["session_id"] = str(session_id)
            
        # Add any other attributes that are not standard LogRecord attributes
        # This handles the extra kwargs passed to the logger
        skip_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename", 
            "funcName", "levelname", "levelno", "lineno", "module", 
            "msecs", "message", "msg", "name", "pathname", "process", 
            "processName", "relativeCreated", "stack_info", "thread", 
            "threadName", "session_id"
        }
        
        for key, value in record.__dict__.items():
            if key not in skip_keys:
                log_data[key] = value

        return json.dumps(log_data)

class TextFormatter(logging.Formatter):
    """Text formatter that appends extra kwargs to the message"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Format the base message using the standard formatter
        s = super().format(record)
        
        # Extract and append extra fields
        skip_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename", 
            "funcName", "levelname", "levelno", "lineno", "module", 
            "msecs", "message", "msg", "name", "pathname", "process", 
            "processName", "relativeCreated", "stack_info", "thread", 
            "threadName", "session_id"
        }
        
        extra_args = {}
        for key, value in record.__dict__.items():
            if key not in skip_keys:
                extra_args[key] = value
                
        if extra_args:
            s += " " + " ".join(f"{k}={v}" for k, v in extra_args.items())
            
        return s

class StructuredLogger(Logger):
    """
    Logger implementation that supports structured JSON logging and file output.
    """

    def __init__(
        self,
        name: str = "gofr-np",
        level: int = logging.INFO,
        log_file: Optional[str] = None,
        json_format: bool = False,
    ):
        self._session_id = str(uuid.uuid4())[:8]
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        
        # Clear existing handlers to avoid duplication if re-initialized
        if self._logger.hasHandlers():
            self._logger.handlers.clear()
            
        self._logger.propagate = False

        # Create formatter
        if json_format:
            formatter = JsonFormatter()
        else:
            # Standard format string
            formatter = TextFormatter(
                "%(asctime)s [%(levelname)s] [session:%(session_id)s] %(message)s"
            )

        # Console Handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # File Handler (if configured)
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(formatter)
                self._logger.addHandler(file_handler)
            except Exception as e:
                # Fallback to console if file cannot be opened
                print(f"Failed to setup log file {log_file}: {e}", file=sys.stderr)

    def get_session_id(self) -> str:
        return self._session_id

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        extra = {"session_id": self._session_id}
        
        # Filter out reserved LogRecord attributes from kwargs to prevent "Attempt to overwrite" errors
        reserved_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename", 
            "funcName", "levelname", "levelno", "lineno", "module", 
            "msecs", "message", "msg", "name", "pathname", "process", 
            "processName", "relativeCreated", "stack_info", "thread", 
            "threadName"
        }
        
        for k, v in kwargs.items():
            if k not in reserved_keys:
                extra[k] = v
            else:
                # If a reserved key is passed, prefix it to preserve it but avoid collision
                extra[f"_{k}"] = v
                
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, message, **kwargs)
