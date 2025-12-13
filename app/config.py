"""Application configuration

Re-exports configuration from gofr_common.config with GOFR_IQ prefix.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from gofr_common.config import (
    Config as BaseConfig,
    Settings,
    ServerSettings,
    AuthSettings,
    StorageSettings,
    LogSettings,
    get_settings as _get_settings,
    reset_settings,
)

# Project-specific prefix
_ENV_PREFIX = "GOFR_IQ"

# Project root for default data directory
_PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class LLMSettings:
    """LLM service configuration
    
    Attributes:
        api_key: OpenRouter API key (required for LLM features)
        base_url: OpenRouter API base URL
        chat_model: Model for chat completions
        embedding_model: Model for embeddings
        max_retries: Maximum retry attempts
        timeout: Request timeout in seconds
    """
    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "anthropic/claude-opus-4"
    embedding_model: str = "openai/text-embedding-3-small"
    max_retries: int = 3
    timeout: int = 60
    
    @property
    def is_available(self) -> bool:
        """Check if LLM service is configured"""
        return self.api_key is not None and len(self.api_key) > 0


def get_llm_settings() -> LLMSettings:
    """Get LLM settings from environment variables"""
    return LLMSettings(
        api_key=os.environ.get("GOFR_IQ_OPENROUTER_API_KEY"),
        base_url=os.environ.get("GOFR_IQ_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        chat_model=os.environ.get("GOFR_IQ_LLM_MODEL", "anthropic/claude-opus-4"),
        embedding_model=os.environ.get("GOFR_IQ_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        max_retries=int(os.environ.get("GOFR_IQ_LLM_MAX_RETRIES", "3")),
        timeout=int(os.environ.get("GOFR_IQ_LLM_TIMEOUT", "60")),
    )


class Config(BaseConfig):
    """Project-specific Config with GOFR_IQ prefix"""

    _env_prefix = _ENV_PREFIX


def get_settings(reload: bool = False, require_auth: bool = True) -> Settings:
    """Get settings with GOFR_IQ prefix"""
    return _get_settings(
        prefix=_ENV_PREFIX,
        reload=reload,
        require_auth=require_auth,
        project_root=_PROJECT_ROOT,
    )


# Convenience functions
def get_public_storage_dir() -> str:
    """Get public storage directory as string"""
    return str(Config.get_storage_dir() / "public")


def get_default_storage_dir() -> str:
    """Get default storage directory as string"""
    return str(Config.get_storage_dir())


def get_default_token_store_path() -> str:
    """Get default token store path as string"""
    return str(Config.get_token_store_path())


def get_default_sessions_dir() -> str:
    """Get default sessions directory as string"""
    return str(Config.get_sessions_dir())


def get_default_proxy_dir() -> str:
    """Get default proxy directory as string"""
    return str(Config.get_proxy_dir())


__all__ = [
    "Config",
    "Settings",
    "ServerSettings",
    "AuthSettings",
    "StorageSettings",
    "LogSettings",
    "LLMSettings",
    "get_settings",
    "get_llm_settings",
    "reset_settings",
    "get_public_storage_dir",
    "get_default_storage_dir",
    "get_default_token_store_path",
    "get_default_sessions_dir",
    "get_default_proxy_dir",
]
