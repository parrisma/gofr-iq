"""Integration tests for LLM Service

Live tests that make real API calls to OpenRouter.
These tests are SKIPPED by default unless GOFR_IQ_OPENROUTER_API_KEY is set.

To run:
    GOFR_IQ_OPENROUTER_API_KEY=your-key pytest test/test_integration_llm.py -v
"""

from __future__ import annotations

import pytest

from app.services.llm_service import (
    ChatCompletionResult,
    ChatMessage,
    EmbeddingResult,
    LLMService,
    create_llm_service,
    llm_available,
)
from app.services.embedding_index import (
    LLMEmbeddingFunction,
    create_llm_embedding_function,
)

# Qwen3 embedding model produces 4096-dimensional vectors
EMBEDDING_DIMENSIONS = 4096

# Skip all tests if LLM is not available
pytestmark = pytest.mark.skipif(
    not llm_available(),
    reason="GOFR_IQ_OPENROUTER_API_KEY not set",
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llm_service() -> LLMService:
    """Create LLM service using environment configuration"""
    return create_llm_service()


# ============================================================================
# Chat Completion Integration Tests
# ============================================================================


class TestChatCompletionIntegration:
    """Integration tests for chat completion"""

    def test_simple_chat(self, llm_service: LLMService) -> None:
        """Test simple chat completion"""
        result = llm_service.chat_completion(
            messages=[
                ChatMessage("user", "Reply with exactly: Hello World"),
            ],
            temperature=0.0,  # Deterministic
            max_tokens=10,
        )

        assert isinstance(result, ChatCompletionResult)
        assert result.content  # Has content
        assert "hello" in result.content.lower()
        assert result.model  # Model name is returned
        assert result.usage  # Usage stats are returned

    def test_chat_with_system_message(self, llm_service: LLMService) -> None:
        """Test chat with system message"""
        result = llm_service.chat_completion(
            messages=[
                ChatMessage(
                    "system",
                    "You are a helpful assistant that responds with exactly one word.",
                ),
                ChatMessage("user", "What color is the sky?"),
            ],
            temperature=0.0,
            max_tokens=10,
        )

        assert isinstance(result, ChatCompletionResult)
        assert result.content
        # Response should be short (one word)
        assert len(result.content.split()) <= 3

    def test_json_mode_extraction(self, llm_service: LLMService) -> None:
        """Test JSON mode for structured extraction"""
        result = llm_service.chat_completion(
            messages=[
                ChatMessage(
                    "system",
                    "Extract entities from the text. Respond with JSON: {\"companies\": [], \"tickers\": []}",
                ),
                ChatMessage(
                    "user",
                    "Apple (AAPL) reported strong earnings. Microsoft (MSFT) also beat expectations.",
                ),
            ],
            json_mode=True,
            temperature=0.0,
            max_tokens=100,
        )

        assert isinstance(result, ChatCompletionResult)
        
        # Parse as JSON
        data = result.as_json()
        assert "companies" in data or "tickers" in data

    def test_multi_turn_conversation(self, llm_service: LLMService) -> None:
        """Test multi-turn conversation"""
        result = llm_service.chat_completion(
            messages=[
                ChatMessage("user", "My favorite color is blue."),
                ChatMessage("assistant", "That's a nice color! Blue is often associated with calm and trust."),
                ChatMessage("user", "What did I say my favorite color was?"),
            ],
            temperature=0.0,
            max_tokens=20,
        )

        assert isinstance(result, ChatCompletionResult)
        assert "blue" in result.content.lower()


# ============================================================================
# Embedding Integration Tests
# ============================================================================


class TestEmbeddingIntegration:
    """Integration tests for embedding generation"""

    def test_single_embedding(self, llm_service: LLMService) -> None:
        """Test generating a single embedding"""
        embedding = llm_service.generate_embedding("Hello, world!")

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(x, float) for x in embedding)
        # Qwen3 embedding model produces 4096-dimensional vectors
        assert len(embedding) == EMBEDDING_DIMENSIONS

    def test_batch_embeddings(self, llm_service: LLMService) -> None:
        """Test generating batch embeddings"""
        texts = [
            "Apple reported strong Q4 earnings.",
            "Microsoft announced new AI features.",
            "Tesla stock rose 5% today.",
        ]
        result = llm_service.generate_embeddings(texts)

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 3
        assert result.dimensions == EMBEDDING_DIMENSIONS
        assert result.usage  # Usage stats returned

    def test_embedding_similarity(self, llm_service: LLMService) -> None:
        """Test that similar texts have similar embeddings"""
        texts = [
            "Apple Inc. reported quarterly earnings.",  # Similar to next
            "Apple announced its quarterly financial results.",  # Similar to previous
            "The weather is sunny today.",  # Different topic
        ]
        result = llm_service.generate_embeddings(texts)

        # Compute cosine similarities
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            return dot / (norm_a * norm_b)

        sim_0_1 = cosine_similarity(result.embeddings[0], result.embeddings[1])
        sim_0_2 = cosine_similarity(result.embeddings[0], result.embeddings[2])

        # Apple earnings texts should be more similar to each other
        # than to the weather text
        assert sim_0_1 > sim_0_2, f"Expected {sim_0_1} > {sim_0_2}"


# ============================================================================
# LLMEmbeddingFunction Integration Tests
# ============================================================================


class TestLLMEmbeddingFunctionIntegration:
    """Integration tests for LLM embedding function"""

    def test_embedding_function(self, llm_service: LLMService) -> None:
        """Test embedding function with LLM service"""
        embed_fn = LLMEmbeddingFunction(llm_service)

        embeddings = embed_fn(["Hello", "World"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) == EMBEDDING_DIMENSIONS  # Qwen3 embedding dimensions

    def test_embedding_function_dimensions(self, llm_service: LLMService) -> None:
        """Test dimensions property"""
        embed_fn = LLMEmbeddingFunction(llm_service)

        # Dimensions should be determined on first call
        dims = embed_fn.dimensions
        assert dims == EMBEDDING_DIMENSIONS

    def test_factory_function(self) -> None:
        """Test factory function creates working embedding function"""
        embed_fn = create_llm_embedding_function()

        embeddings = embed_fn(["Test embedding"])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == EMBEDDING_DIMENSIONS

    def test_embed_documents(self, llm_service: LLMService) -> None:
        """Test embed_documents interface"""
        embed_fn = LLMEmbeddingFunction(llm_service)

        embeddings = embed_fn.embed_documents(["Document one", "Document two"])

        assert len(embeddings) == 2

    def test_embed_query(self, llm_service: LLMService) -> None:
        """Test embed_query interface"""
        embed_fn = LLMEmbeddingFunction(llm_service)

        embeddings = embed_fn.embed_query("Search query")

        assert len(embeddings) == 1  # Single query returns list with one embedding
        assert len(embeddings[0]) == EMBEDDING_DIMENSIONS
