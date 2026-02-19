"""LLM Service using OpenRouter API

Provides chat completion and embedding generation using OpenRouter,
which offers access to multiple LLM providers through a unified API.

Features:
- Chat completion with JSON mode support
- Embedding generation for ChromaDB
- Automatic retries with exponential backoff
- Rate limiting and error handling
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

import httpx

from app.config import GofrIqConfig
from app.logger import StructuredLogger

if TYPE_CHECKING:
    from gofr_common.auth import OpenRouterKeyProvider

logger = StructuredLogger(__name__)


# Legacy LLMSettings for backward compatibility
@dataclass
class LLMSettings:
    """Legacy LLM settings (deprecated, use GofrIqConfig instead)."""
    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "meta-llama/llama-3.1-70b-instruct"
    embedding_model: str = "qwen/qwen3-embedding-8b"
    max_retries: int = 3
    timeout: int = 60
    
    @property
    def is_available(self) -> bool:
        """Check if LLM service is configured"""
        return self.api_key is not None and len(self.api_key) > 0


class LLMServiceError(Exception):
    """Base exception for LLM service errors"""

    pass


class LLMConfigurationError(LLMServiceError):
    """Raised when LLM service is not properly configured"""

    pass


class LLMRateLimitError(LLMServiceError):
    """Raised when rate limit is exceeded"""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after}s"
            if retry_after
            else "Rate limit exceeded"
        )


class LLMAPIError(LLMServiceError):
    """Raised when API returns an error"""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"API error ({status_code}): {message}")


@dataclass
class ChatMessage:
    """A chat message
    
    Attributes:
        role: Message role (system, user, assistant)
        content: Message content
    """

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        """Convert to API format"""
        return {"role": self.role, "content": self.content}


@dataclass
class ChatCompletionResult:
    """Result from a chat completion
    
    Attributes:
        content: The generated text content
        model: Model used for generation
        usage: Token usage statistics
        finish_reason: Why generation stopped
    """

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        """Parse content as JSON, stripping markdown fences if present"""
        content = self.content.strip()
        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line if it's closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        try:
            return json.loads(content)  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:
            raise LLMServiceError(f"Failed to parse response as JSON: {e}") from e


@dataclass
class EmbeddingResult:
    """Result from embedding generation
    
    Attributes:
        embeddings: List of embedding vectors
        model: Model used for generation
        usage: Token usage statistics
    """

    embeddings: list[list[float]]
    model: str
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions"""
        return len(self.embeddings[0]) if self.embeddings else 0


class LLMService:
    """Service for LLM chat completion and embedding generation
    
    Uses OpenRouter API which provides access to multiple LLM providers
    through a unified OpenAI-compatible interface.
    
    Example:
        >>> service = LLMService()
        >>> result = service.chat_completion(
        ...     messages=[ChatMessage("user", "Hello!")],
        ... )
        >>> print(result.content)
        
        >>> embeddings = service.generate_embeddings(["Hello", "World"])
        >>> print(embeddings.dimensions)
    """

    def __init__(
        self,
        settings: LLMSettings | None = None,
        config: GofrIqConfig | None = None,
        openrouter_key_provider: OpenRouterKeyProvider | None = None,
    ) -> None:
        """Initialize LLM service
        
        Args:
            settings: Legacy LLM settings (deprecated, use config instead)
            config: GofrIqConfig instance (preferred)
            
        Note:
            If config is provided, LLM settings are extracted from it.
            Otherwise falls back to settings parameter or loads from environment.
        """
        if config is not None:
            api_key = config.openrouter_api_key
            if (api_key is None or len(api_key) == 0) and openrouter_key_provider is not None:
                api_key = openrouter_key_provider.get()

            # Extract LLM settings from GofrIqConfig
            self.settings = LLMSettings(
                api_key=api_key,
                base_url=config.openrouter_base_url,
                chat_model=config.llm_model,
                embedding_model=config.embedding_model,
                max_retries=config.llm_max_retries,
                timeout=config.llm_timeout,
            )
        elif settings is not None:
            # Use provided settings
            self.settings = settings
        else:
            # Load from environment
            import os
            api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
            if (api_key is None or len(api_key) == 0) and openrouter_key_provider is not None:
                api_key = openrouter_key_provider.get()
            self.settings = LLMSettings(
                api_key=api_key,
                base_url=os.environ.get("GOFR_IQ_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                chat_model=os.environ.get("GOFR_IQ_LLM_MODEL", "meta-llama/llama-3.1-70b-instruct"),
                embedding_model=os.environ.get("GOFR_IQ_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"),
                max_retries=int(os.environ.get("GOFR_IQ_LLM_MAX_RETRIES", "3")),
                timeout=int(os.environ.get("GOFR_IQ_LLM_TIMEOUT", "60")),
            )
        self._client: httpx.Client | None = None

    @property
    def is_available(self) -> bool:
        """Check if LLM service is configured and available"""
        return self.settings.is_available

    def _ensure_configured(self) -> None:
        """Ensure service is properly configured"""
        if not self.is_available:
            raise LLMConfigurationError(
                "LLM service not configured. Provide OpenRouter API key via Vault (gofr/config/api-keys/openrouter) "
                "or set GOFR_IQ_OPENROUTER_API_KEY as an override."
            )

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.settings.base_url,
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "HTTP-Referer": "https://github.com/gofr/gofr-iq",
                    "X-Title": "Gofr-IQ News Intelligence",
                    "Content-Type": "application/json",
                },
                timeout=self.settings.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client"""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "LLMService":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _make_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        retries: int | None = None,
    ) -> dict[str, Any]:
        """Make an API request with retries
        
        Args:
            endpoint: API endpoint path
            payload: Request payload
            retries: Number of retries (uses settings default if not specified)
            
        Returns:
            API response as dictionary
        """
        self._ensure_configured()
        max_retries = retries if retries is not None else self.settings.max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = self.client.post(endpoint, json=payload)

                if response.status_code == 429:
                    # Rate limited
                    retry_after = response.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else (2**attempt)
                    if attempt < max_retries:
                        time.sleep(wait_time)
                        continue
                    raise LLMRateLimitError(wait_time)

                if response.status_code >= 400:
                    error_detail = response.text
                    try:
                        error_json = response.json()
                        error_detail = error_json.get("error", {}).get(
                            "message", response.text
                        )
                    except Exception:
                        pass  # nosec B110
                    raise LLMAPIError(response.status_code, error_detail)

                return response.json()  # type: ignore[no-any-return]

            except httpx.TransportError as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                raise LLMServiceError(f"Network error: {e}") from e

        raise last_error or LLMServiceError("Request failed after all retries")

    def chat_completion(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatCompletionResult:
        """Generate a chat completion
        
        Args:
            messages: List of chat messages
            model: Model to use (uses settings default if not specified)
            json_mode: Request JSON output format
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            
        Returns:
            ChatCompletionResult with generated content
        """
        payload: dict[str, Any] = {
            "model": model or self.settings.chat_model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        if max_tokens:
            payload["max_tokens"] = max_tokens

        logger.info(f"LLM chat completion: model={payload['model']}, json_mode={json_mode}, messages={len(messages)}")
        response = self._make_request("/chat/completions", payload)

        choice = response["choices"][0]
        return ChatCompletionResult(
            content=choice["message"]["content"],
            model=response.get("model", payload["model"]),
            usage=response.get("usage", {}),
            finish_reason=choice.get("finish_reason"),
        )

    def generate_embeddings(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embeddings for texts
        
        Args:
            texts: List of texts to embed
            model: Embedding model to use (uses settings default if not specified)
            
        Returns:
            EmbeddingResult with embedding vectors
            
        Raises:
            LLMAPIError: If the embedding API returns an error
        """
        payload = {
            "model": model or self.settings.embedding_model,
            "input": texts,
        }

        logger.info(f"LLM embeddings: model={payload['model']}, texts={len(texts)}")
        response = self._make_request("/embeddings", payload)

        # Check for error in response body (OpenRouter returns 200 with error object)
        if "error" in response:
            error_msg = response["error"].get("message", "Unknown embedding error")
            error_code = response["error"].get("code", 500)
            raise LLMAPIError(error_code, f"Embedding failed: {error_msg}")

        # Extract embeddings from response
        if "data" not in response:
            raise LLMAPIError(500, f"Invalid embedding response: missing 'data' field. Response: {response}")
        
        embeddings = [item["embedding"] for item in response["data"]]

        return EmbeddingResult(
            embeddings=embeddings,
            model=response.get("model", payload["model"]),
            usage=response.get("usage", {}),
        )

    def generate_embedding(self, text: str, model: str | None = None) -> list[float]:
        """Generate embedding for a single text
        
        Convenience method for single text embedding.
        
        Args:
            text: Text to embed
            model: Embedding model to use
            
        Returns:
            Embedding vector as list of floats
        """
        result = self.generate_embeddings([text], model)
        # Ensure all values are floats (API may return ints or other numeric types)
        return [float(x) for x in result.embeddings[0]]


def create_llm_service(
    settings: LLMSettings | None = None,
    config: GofrIqConfig | None = None,
) -> LLMService:
    """Factory function to create LLM service
    
    Args:
        settings: Optional legacy LLM settings (deprecated)
        config: Optional GofrIqConfig instance (preferred)
        
    Returns:
        Configured LLMService instance
    """
    return LLMService(settings=settings, config=config)


def llm_available() -> bool:
    """Check if LLM service is available
    
    Returns:
        True if GOFR_IQ_OPENROUTER_API_KEY is set
    """
    import os
    api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    return api_key is not None and len(api_key) > 0
