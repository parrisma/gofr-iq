"""Application configuration

Provides GofrIqConfig extending InfrastructureConfig from gofr_common for GOFR-IQ specific settings.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gofr_common.config import BaseConfig, InfrastructureConfig

# Project-specific prefix
_ENV_PREFIX = "GOFR_IQ"

# Project root for default data directory
_PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class GofrIqConfig(InfrastructureConfig):
    """GOFR-IQ specific configuration extending InfrastructureConfig.
    
    Inherits infrastructure settings (Vault, Neo4j, etc.) and adds
    GOFR-IQ specific settings for LLM and ChromaDB.
    
    Attributes:
        Inherited from InfrastructureConfig:
            env, project_root, log_level, log_format, prefix
            vault_url, vault_token, vault_role_id, vault_secret_id,
            vault_path_prefix, vault_mount_point
            chroma_host, chroma_port
            neo4j_host, neo4j_bolt_port, neo4j_http_port
            shared_jwt_secret
        
        GOFR-IQ Specific:
            openrouter_api_key: OpenRouter API key for LLM
            openrouter_base_url: OpenRouter API base URL
            llm_model: Chat completion model
            embedding_model: Embedding model
            llm_max_retries: Maximum LLM retry attempts
            llm_timeout: LLM request timeout in seconds
    """
    
    # LLM Configuration
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-opus-4"
    embedding_model: str = "qwen/qwen3-embedding-8b"
    llm_max_retries: int = 3
    llm_timeout: int = 60
    
    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR_IQ",
        project_root: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ) -> "GofrIqConfig":
        """Load configuration from environment variables.
        
        Args:
            prefix: Environment variable prefix (default: GOFR_IQ)
            project_root: Project root directory (default: auto-detected)
            env_file: Optional .env file path
            
        Returns:
            GofrIqConfig instance with all settings loaded
        """
        # Get base infrastructure config
        base = InfrastructureConfig.from_env(prefix=prefix, project_root=project_root, env_file=env_file)
        
        # Load GOFR-IQ specific settings from environment
        from gofr_common.config.env_loader import EnvLoader
        env_data = EnvLoader(env_file).load()
        
        return cls(
            # Base config
            env=base.env,
            project_root=base.project_root,
            log_level=base.log_level,
            log_format=base.log_format,
            prefix=prefix,
            # Infrastructure config
            vault_url=base.vault_url,
            vault_token=base.vault_token,
            vault_role_id=base.vault_role_id,
            vault_secret_id=base.vault_secret_id,
            vault_path_prefix=base.vault_path_prefix,
            vault_mount_point=base.vault_mount_point,
            chroma_host=base.chroma_host,
            chroma_port=base.chroma_port,
            neo4j_host=base.neo4j_host,
            neo4j_bolt_port=base.neo4j_bolt_port,
            neo4j_http_port=base.neo4j_http_port,
            shared_jwt_secret=base.shared_jwt_secret,
            # GOFR-IQ specific
            openrouter_api_key=env_data.get(f"{prefix}_OPENROUTER_API_KEY"),
            openrouter_base_url=env_data.get(
                f"{prefix}_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            llm_model=env_data.get(f"{prefix}_LLM_MODEL", "anthropic/claude-opus-4"),
            embedding_model=env_data.get(f"{prefix}_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"),
            llm_max_retries=int(env_data.get(f"{prefix}_LLM_MAX_RETRIES", "3")),
            llm_timeout=int(env_data.get(f"{prefix}_LLM_TIMEOUT", "60")),
        )
    
    @property
    def llm_is_available(self) -> bool:
        """Check if LLM service is configured."""
        return self.openrouter_api_key is not None and len(self.openrouter_api_key) > 0
    
    @property
    def chromadb_is_http_mode(self) -> bool:
        """Check if configured for ChromaDB HTTP client mode."""
        return self.chroma_host is not None


# Singleton instance cache
_config_instance: Optional[GofrIqConfig] = None


def get_config(reload: bool = False, env_file: Optional[Path] = None) -> GofrIqConfig:
    """Get or create the singleton GofrIqConfig instance.
    
    Args:
        reload: Force reload configuration from environment
        env_file: Optional .env file path to load
        
    Returns:
        GofrIqConfig singleton instance
    """
    global _config_instance
    
    if reload or _config_instance is None:
        _config_instance = GofrIqConfig.from_env(
            prefix=_ENV_PREFIX,
            project_root=_PROJECT_ROOT,
            env_file=env_file,
        )
    
    return _config_instance


def reset_config() -> None:
    """Reset the singleton config instance (useful for testing)."""
    global _config_instance
    _config_instance = None


__all__ = [
    "GofrIqConfig",
    "BaseConfig",
    "InfrastructureConfig",
    "get_config",
    "reset_config",
]
