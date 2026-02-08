"""Tests for mandate enrichment service

Tests cover:
- Theme extraction from mandate text
- Hash computation for idempotency
- Validation against controlled vocabulary
- Mock LLM mode for deterministic tests
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from app.services.mandate_enrichment import (
    VALID_THEMES,
    MandateEnrichmentResult,
    compute_mandate_hash,
    extract_themes_from_mandate,
)
from app.services.llm_service import (
    ChatCompletionResult,
    LLMService,
    LLMServiceError,
)


def create_mock_llm(is_available: bool = True) -> MagicMock:
    """Create a mock LLM service with proper property mocking"""
    mock = MagicMock(spec=LLMService)
    type(mock).is_available = PropertyMock(return_value=is_available)
    return mock


class TestComputeMandateHash:
    """Tests for mandate text hashing"""

    def test_hash_deterministic(self) -> None:
        """Same text produces same hash"""
        text = "We invest in semiconductor stocks in Asia"
        hash1 = compute_mandate_hash(text)
        hash2 = compute_mandate_hash(text)
        assert hash1 == hash2

    def test_hash_normalized(self) -> None:
        """Whitespace and case are normalized"""
        text1 = "  AI semiconductor Japan  "
        text2 = "ai semiconductor japan"
        assert compute_mandate_hash(text1) == compute_mandate_hash(text2)

    def test_hash_length(self) -> None:
        """Hash is 16 hex characters"""
        text = "any mandate text"
        hash_val = compute_mandate_hash(text)
        assert len(hash_val) == 16
        # Should be valid hex
        int(hash_val, 16)

    def test_hash_different_texts(self) -> None:
        """Different texts produce different hashes"""
        hash1 = compute_mandate_hash("semiconductor focus")
        hash2 = compute_mandate_hash("biotech focus")
        assert hash1 != hash2


class TestExtractThemesFromMandate:
    """Tests for theme extraction"""

    def test_empty_mandate_returns_empty_themes(self) -> None:
        """Empty mandate text returns empty themes list"""
        mock_llm = create_mock_llm(is_available=True)
        
        result = extract_themes_from_mandate("", mock_llm)
        
        assert result.success
        assert result.themes == []
        # LLM should not be called for empty text
        mock_llm.chat_completion.assert_not_called()

    def test_whitespace_only_mandate_returns_empty(self) -> None:
        """Whitespace-only mandate returns empty themes"""
        mock_llm = create_mock_llm(is_available=True)
        
        result = extract_themes_from_mandate("   \n\t  ", mock_llm)
        
        assert result.success
        assert result.themes == []

    def test_llm_not_available(self) -> None:
        """Returns error when LLM not available"""
        mock_llm = create_mock_llm(is_available=False)
        
        result = extract_themes_from_mandate("semiconductor focus", mock_llm)
        
        assert not result.success
        assert result.themes == []
        assert result.error is not None and "not configured" in result.error

    def test_successful_extraction(self) -> None:
        """Successfully extracts themes from mandate"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": ["semiconductor", "japan", "supply_chain"]}',
            model="test-model",
            usage={},
        )
        
        mandate = "We focus on semiconductor supply chains in Japan"
        result = extract_themes_from_mandate(mandate, mock_llm)
        
        assert result.success
        assert set(result.themes) == {"semiconductor", "japan", "supply_chain"}
        assert result.mandate_text == mandate
        assert result.mandate_text_hash == compute_mandate_hash(mandate)

    def test_filters_invalid_themes(self) -> None:
        """Invalid themes from LLM are filtered out"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": ["semiconductor", "invalid_theme", "ai", "not_real"]}',
            model="test-model",
            usage={},
        )
        
        result = extract_themes_from_mandate("tech mandate", mock_llm)
        
        assert result.success
        assert set(result.themes) == {"semiconductor", "ai"}
        # Invalid themes should be filtered, not cause failure

    def test_normalizes_theme_case(self) -> None:
        """Theme case is normalized to lowercase"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": ["SEMICONDUCTOR", "Ai", "JAPAN"]}',
            model="test-model",
            usage={},
        )
        
        result = extract_themes_from_mandate("tech mandate", mock_llm)
        
        assert result.success
        assert set(result.themes) == {"semiconductor", "ai", "japan"}

    def test_handles_llm_error(self) -> None:
        """Handles LLM service errors gracefully"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.side_effect = LLMServiceError("API error")
        
        result = extract_themes_from_mandate("semiconductor focus", mock_llm)
        
        assert not result.success
        assert result.themes == []
        assert result.error is not None and "LLM error" in result.error

    def test_handles_invalid_json_response(self) -> None:
        """Handles non-JSON LLM response"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='not valid json',
            model="test-model",
            usage={},
        )
        
        result = extract_themes_from_mandate("semiconductor focus", mock_llm)
        
        assert not result.success
        assert result.themes == []
        assert result.error is not None and "Invalid JSON" in result.error

    def test_handles_missing_themes_key(self) -> None:
        """Handles JSON without themes key"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"other": "data"}',
            model="test-model",
            usage={},
        )
        
        result = extract_themes_from_mandate("semiconductor focus", mock_llm)
        
        assert result.success  # Empty themes is valid
        assert result.themes == []

    def test_handles_themes_not_list(self) -> None:
        """Handles themes that isn't a list"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": "semiconductor"}',
            model="test-model",
            usage={},
        )
        
        result = extract_themes_from_mandate("semiconductor focus", mock_llm)
        
        assert not result.success
        assert result.error is not None and "Expected 'themes' to be a list" in result.error
        
        assert not result.success
        assert result.error is not None and "Expected 'themes' to be a list" in result.error


class TestMandateEnrichmentResult:
    """Tests for MandateEnrichmentResult dataclass"""

    def test_success_property(self) -> None:
        """success is True when no error"""
        result = MandateEnrichmentResult(
            mandate_text="test",
            mandate_text_hash="abc123",
            themes=["ai"],
        )
        assert result.success

    def test_failure_property(self) -> None:
        """success is False when error present"""
        result = MandateEnrichmentResult(
            mandate_text="test",
            mandate_text_hash="abc123",
            themes=[],
            error="something went wrong",
        )
        assert not result.success

    def test_to_dict(self) -> None:
        """to_dict includes relevant fields"""
        result = MandateEnrichmentResult(
            mandate_text="test mandate",
            mandate_text_hash="abc123def456",
            themes=["ai", "semiconductor"],
        )
        d = result.to_dict()
        assert d["mandate_text_hash"] == "abc123def456"
        assert d["themes"] == ["ai", "semiconductor"]
        assert d["error"] is None


class TestValidThemes:
    """Tests for VALID_THEMES constant"""

    def test_contains_expected_themes(self) -> None:
        """VALID_THEMES contains expected values"""
        expected = {"ai", "semiconductor", "ev_battery", "japan", "china"}
        assert expected.issubset(VALID_THEMES)

    def test_theme_count(self) -> None:
        """VALID_THEMES has expected count"""
        assert len(VALID_THEMES) == 25

    def test_all_lowercase(self) -> None:
        """All themes are lowercase"""
        for theme in VALID_THEMES:
            assert theme == theme.lower()


class TestMandateEnrichmentDeterminism:
    """Tests for deterministic behavior (mock mode)"""

    def test_same_input_same_output(self) -> None:
        """Given same mandate_text, enrichment returns stable themes"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": ["semiconductor", "japan"]}',
            model="test-model",
            usage={},
        )
        
        mandate = "We focus on Japanese semiconductor manufacturers"
        
        result1 = extract_themes_from_mandate(mandate, mock_llm)
        result2 = extract_themes_from_mandate(mandate, mock_llm)
        
        assert result1.themes == result2.themes
        assert result1.mandate_text_hash == result2.mandate_text_hash

    def test_temperature_zero_for_determinism(self) -> None:
        """LLM is called with temperature=0 for determinism"""
        mock_llm = create_mock_llm(is_available=True)
        mock_llm.chat_completion.return_value = ChatCompletionResult(
            content='{"themes": ["ai"]}',
            model="test-model",
            usage={},
        )
        
        extract_themes_from_mandate("AI focus", mock_llm)
        
        # Verify temperature=0 was used
        call_kwargs = mock_llm.chat_completion.call_args[1]
        assert call_kwargs["temperature"] == 0.0
