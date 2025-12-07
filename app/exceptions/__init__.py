"""Custom exceptions for GOFR-IQ application.

All exceptions include detailed error messages designed for LLM processing,
enabling intelligent error recovery and decision-making.

Base exceptions are re-exported from gofr_common.exceptions.
"""

# Re-export common exceptions from gofr_common
from gofr_common.exceptions import (
    GofrError,
    ValidationError,
    ResourceNotFoundError,
    SecurityError,
    ConfigurationError,
    RegistryError,
)

# Project-specific alias for backward compatibility
GofrIqError = GofrError

__all__ = [
    # Base exceptions (from gofr_common)
    "GofrError",
    "GofrIqError",  # Alias for backward compatibility
    "ValidationError",
    "ResourceNotFoundError",
    "SecurityError",
    "ConfigurationError",
    "RegistryError",
]
