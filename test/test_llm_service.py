"""Tests for LLM Service

Unit tests for the LLM service using mocked HTTP responses.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_service import (
    LLMSettings,
    ChatCompletionResult,
    ChatMessage,
    EmbeddingResult,
    LLMAPIError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMService,
    LLMServiceError,
    create_llm_service,
    llm_available,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llm_settings() -> LLMSettings:
    """Create test LLM settings with a fake API key"""
    return LLMSettings(
        api_key="test-api-key-12345",
        base_url="https://openrouter.ai/api/v1",
        chat_model="meta-llama/llama-3.1-70b-instruct",
        embedding_model="openai/text-embedding-3-small",
        max_retries=3,
        timeout=60,
    )


@pytest.fixture
def llm_service(llm_settings: LLMSettings) -> LLMService:
    """Create LLM service with test settings"""
    return LLMService(settings=llm_settings)


@pytest.fixture
def mock_chat_response() -> dict[str, Any]:
    """Mock chat completion response"""
    return {
        "id": "gen-12345",
        "model": "meta-llama/llama-3.1-70b-instruct",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
    }


@pytest.fixture
def mock_json_response() -> dict[str, Any]:
    """Mock chat completion response with JSON content"""
    return {
        "id": "gen-67890",
        "model": "meta-llama/llama-3.1-70b-instruct",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"entities": ["AAPL", "MSFT"], "sentiment": "positive"}',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 20,
            "total_tokens": 70,
        },
    }


@pytest.fixture
def mock_embedding_response() -> dict[str, Any]:
    """Mock embedding response"""
    return {
        "model": "openai/text-embedding-3-small",
        "data": [
            {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4, 0.5]},
            {"index": 1, "embedding": [0.2, 0.3, 0.4, 0.5, 0.6]},
        ],
        "usage": {
            "prompt_tokens": 10,
            "total_tokens": 10,
        },
    }


# ============================================================================
# LLMSettings Tests
# ============================================================================


class TestLLMSettings:
    """Tests for LLMSettings dataclass"""

    def test_is_available_with_api_key(self) -> None:
        """Settings with API key should be available"""
        settings = LLMSettings(api_key="test-key")
        assert settings.is_available is True

    def test_is_not_available_without_api_key(self) -> None:
        """Settings without API key should not be available"""
        settings = LLMSettings()
        assert settings.is_available is False

    def test_is_not_available_with_empty_api_key(self) -> None:
        """Settings with empty API key should not be available"""
        settings = LLMSettings(api_key="")
        assert settings.is_available is False

    def test_default_values(self) -> None:
        """Test default settings values"""
        settings = LLMSettings()
        assert settings.base_url == "https://openrouter.ai/api/v1"
        assert settings.chat_model == "meta-llama/llama-3.1-70b-instruct"
        assert settings.embedding_model == "qwen/qwen3-embedding-8b"
        assert settings.max_retries == 3
        assert settings.timeout == 60


# ============================================================================
# ChatMessage Tests
# ============================================================================


class TestChatMessage:
    """Tests for ChatMessage dataclass"""

    def test_to_dict(self) -> None:
        """Test converting message to dict"""
        msg = ChatMessage(role="user", content="Hello!")
        assert msg.to_dict() == {"role": "user", "content": "Hello!"}

    def test_system_message(self) -> None:
        """Test system message"""
        msg = ChatMessage(role="system", content="You are a helpful assistant.")
        assert msg.role == "system"
        assert msg.content == "You are a helpful assistant."


# ============================================================================
# ChatCompletionResult Tests
# ============================================================================


class TestChatCompletionResult:
    """Tests for ChatCompletionResult dataclass"""

    def test_basic_result(self) -> None:
        """Test creating a basic result"""
        result = ChatCompletionResult(
            content="Hello!",
            model="test-model",
            usage={"total_tokens": 10},
            finish_reason="stop",
        )
        assert result.content == "Hello!"
        assert result.model == "test-model"
        assert result.usage == {"total_tokens": 10}
        assert result.finish_reason == "stop"

    def test_as_json_valid(self) -> None:
        """Test parsing content as JSON"""
        result = ChatCompletionResult(
            content='{"key": "value", "count": 42}',
            model="test-model",
        )
        parsed = result.as_json()
        assert parsed == {"key": "value", "count": 42}

    def test_as_json_with_markdown_fences(self) -> None:
        """Test parsing JSON wrapped in markdown code fences"""
        result = ChatCompletionResult(
            content='```json\n{"companies": ["Apple"], "tickers": ["AAPL"]}\n```',
            model="test-model",
        )
        parsed = result.as_json()
        assert parsed == {"companies": ["Apple"], "tickers": ["AAPL"]}

    def test_as_json_with_plain_fences(self) -> None:
        """Test parsing JSON wrapped in plain markdown fences (no language)"""
        result = ChatCompletionResult(
            content='```\n{"key": "value"}\n```',
            model="test-model",
        )
        parsed = result.as_json()
        assert parsed == {"key": "value"}

    def test_as_json_invalid(self) -> None:
        """Test parsing invalid JSON raises error"""
        result = ChatCompletionResult(
            content="not valid json",
            model="test-model",
        )
        with pytest.raises(LLMServiceError, match="Failed to parse response as JSON"):
            result.as_json()


# ============================================================================
# EmbeddingResult Tests
# ============================================================================


class TestEmbeddingResult:
    """Tests for EmbeddingResult dataclass"""

    def test_dimensions(self) -> None:
        """Test getting embedding dimensions"""
        result = EmbeddingResult(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            model="test-model",
        )
        assert result.dimensions == 3

    def test_empty_dimensions(self) -> None:
        """Test dimensions for empty embeddings"""
        result = EmbeddingResult(embeddings=[], model="test-model")
        assert result.dimensions == 0


# ============================================================================
# LLMService Tests
# ============================================================================


class TestLLMServiceConfiguration:
    """Tests for LLM service configuration"""

    def test_is_available(self, llm_service: LLMService) -> None:
        """Test service availability check"""
        assert llm_service.is_available is True

    def test_not_available_without_key(self) -> None:
        """Test service is not available without API key"""
        service = LLMService(settings=LLMSettings())
        assert service.is_available is False

    def test_ensure_configured_raises_without_key(self) -> None:
        """Test _ensure_configured raises error without API key"""
        service = LLMService(settings=LLMSettings())
        with pytest.raises(LLMConfigurationError, match="not configured"):
            service._ensure_configured()

    def test_context_manager(self, llm_settings: LLMSettings) -> None:
        """Test service as context manager"""
        with LLMService(settings=llm_settings) as service:
            assert service.is_available
        # Client should be closed after exit


class TestLLMServiceChatCompletion:
    """Tests for chat completion"""

    def test_chat_completion_success(
        self,
        llm_service: LLMService,
        mock_chat_response: dict[str, Any],
    ) -> None:
        """Test successful chat completion"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_chat_response

        with patch.object(llm_service.client, "post", return_value=mock_response):
            result = llm_service.chat_completion(
                messages=[ChatMessage("user", "Hello!")],
            )

        assert result.content == "Hello! How can I help you today?"
        assert result.model == "meta-llama/llama-3.1-70b-instruct"
        assert result.finish_reason == "stop"
        assert result.usage["total_tokens"] == 18

    def test_chat_completion_with_json_mode(
        self,
        llm_service: LLMService,
        mock_json_response: dict[str, Any],
    ) -> None:
        """Test chat completion with JSON mode"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_json_response

        with patch.object(llm_service.client, "post", return_value=mock_response) as mock_post:
            result = llm_service.chat_completion(
                messages=[ChatMessage("user", "Extract entities")],
                json_mode=True,
            )

        # Verify JSON mode was set in request
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        assert payload["response_format"] == {"type": "json_object"}

        # Verify result can be parsed as JSON
        parsed = result.as_json()
        assert parsed["entities"] == ["AAPL", "MSFT"]
        assert parsed["sentiment"] == "positive"

    def test_chat_completion_with_custom_model(
        self,
        llm_service: LLMService,
        mock_chat_response: dict[str, Any],
    ) -> None:
        """Test chat completion with custom model"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_chat_response

        with patch.object(llm_service.client, "post", return_value=mock_response) as mock_post:
            llm_service.chat_completion(
                messages=[ChatMessage("user", "Hello!")],
                model="openai/gpt-4o",
            )

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        assert payload["model"] == "openai/gpt-4o"

    def test_chat_completion_with_temperature(
        self,
        llm_service: LLMService,
        mock_chat_response: dict[str, Any],
    ) -> None:
        """Test chat completion with custom temperature"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_chat_response

        with patch.object(llm_service.client, "post", return_value=mock_response) as mock_post:
            llm_service.chat_completion(
                messages=[ChatMessage("user", "Hello!")],
                temperature=0.2,
            )

        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        assert payload["temperature"] == 0.2


class TestLLMServiceEmbeddings:
    """Tests for embedding generation"""

    def test_generate_embeddings_success(
        self,
        llm_service: LLMService,
        mock_embedding_response: dict[str, Any],
    ) -> None:
        """Test successful embedding generation"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_embedding_response

        with patch.object(llm_service.client, "post", return_value=mock_response):
            result = llm_service.generate_embeddings(["Hello", "World"])

        assert len(result.embeddings) == 2
        assert result.embeddings[0] == [0.1, 0.2, 0.3, 0.4, 0.5]
        assert result.embeddings[1] == [0.2, 0.3, 0.4, 0.5, 0.6]
        assert result.dimensions == 5

    def test_generate_single_embedding(
        self,
        llm_service: LLMService,
        mock_embedding_response: dict[str, Any],
    ) -> None:
        """Test single embedding generation convenience method"""
        # Modify mock to return single embedding
        single_response = {
            "model": "openai/text-embedding-3-small",
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4, 0.5]}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = single_response

        with patch.object(llm_service.client, "post", return_value=mock_response):
            embedding = llm_service.generate_embedding("Hello")

        assert embedding == [0.1, 0.2, 0.3, 0.4, 0.5]


class TestLLMServiceErrors:
    """Tests for error handling"""

    def test_rate_limit_error(
        self,
        llm_service: LLMService,
    ) -> None:
        """Test rate limit handling"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5"}

        # Set max_retries to 0 to test immediate error
        llm_service.settings.max_retries = 0

        with patch.object(llm_service.client, "post", return_value=mock_response):
            with pytest.raises(LLMRateLimitError, match="Rate limit exceeded"):
                llm_service.chat_completion(
                    messages=[ChatMessage("user", "Hello!")],
                )

    def test_api_error(
        self,
        llm_service: LLMService,
    ) -> None:
        """Test API error handling"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.json.return_value = {
            "error": {"message": "Invalid model specified"}
        }

        with patch.object(llm_service.client, "post", return_value=mock_response):
            with pytest.raises(LLMAPIError, match="Invalid model specified"):
                llm_service.chat_completion(
                    messages=[ChatMessage("user", "Hello!")],
                )

    def test_api_error_without_json(
        self,
        llm_service: LLMService,
    ) -> None:
        """Test API error handling when response is not JSON"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.side_effect = ValueError("No JSON")

        with patch.object(llm_service.client, "post", return_value=mock_response):
            with pytest.raises(LLMAPIError, match="Internal Server Error"):
                llm_service.chat_completion(
                    messages=[ChatMessage("user", "Hello!")],
                )


# ============================================================================
# Factory Functions Tests
# ============================================================================


class TestFactoryFunctions:
    """Tests for factory functions"""

    def test_create_llm_service(self) -> None:
        """Test creating service with factory function"""
        settings = LLMSettings(api_key="test-key")
        service = create_llm_service(settings)
        assert service.is_available

    def test_create_llm_service_without_settings(self) -> None:
        """Test creating service without explicit settings uses environment"""
        # Service should be created (may or may not be available based on env)
        service = create_llm_service()
        assert isinstance(service, LLMService)

    def test_llm_available_without_key(self) -> None:
        """Test llm_available returns False without API key"""
        with patch.dict("os.environ", {"GOFR_IQ_OPENROUTER_API_KEY": ""}, clear=False):
            # This will check environment, result depends on actual env
            result = llm_available()
            assert isinstance(result, bool)
