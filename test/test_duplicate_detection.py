"""Tests for Duplicate Detection - Phase 6.

Tests for detecting exact and near-duplicate documents at ingestion time.
"""

from __future__ import annotations

from app.services import (
    DuplicateDetector,
    DuplicateResult,
    check_duplicate,
    compute_content_hash,
    cosine_similarity,
    normalize_text,
    tokenize,
)


# =============================================================================
# TEXT PROCESSING TESTS
# =============================================================================


class TestNormalizeText:
    """Tests for normalize_text function."""

    def test_normalize_lowercase(self) -> None:
        """Test that normalization lowercases text."""
        result = normalize_text("Hello WORLD")
        assert result == "hello world"

    def test_normalize_whitespace(self) -> None:
        """Test that normalization collapses whitespace."""
        result = normalize_text("Hello   World")
        assert result == "hello world"

    def test_normalize_newlines(self) -> None:
        """Test that newlines are converted to spaces."""
        result = normalize_text("Hello\nWorld\tTest")
        assert result == "hello world test"

    def test_normalize_strip(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = normalize_text("  Hello World  ")
        assert result == "hello world"

    def test_normalize_empty(self) -> None:
        """Test empty string handling."""
        result = normalize_text("")
        assert result == ""

    def test_normalize_unicode(self) -> None:
        """Test Unicode text normalization."""
        result = normalize_text("Hello 世界")
        assert result == "hello 世界"


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_hash_deterministic(self) -> None:
        """Test that same content produces same hash."""
        hash1 = compute_content_hash("Hello World")
        hash2 = compute_content_hash("Hello World")
        assert hash1 == hash2

    def test_hash_case_insensitive(self) -> None:
        """Test that hash is case-insensitive."""
        hash1 = compute_content_hash("Hello World")
        hash2 = compute_content_hash("hello world")
        assert hash1 == hash2

    def test_hash_whitespace_normalized(self) -> None:
        """Test that whitespace is normalized before hashing."""
        hash1 = compute_content_hash("Hello World")
        hash2 = compute_content_hash("Hello  World")
        assert hash1 == hash2

    def test_hash_different_content(self) -> None:
        """Test that different content produces different hash."""
        hash1 = compute_content_hash("Hello World")
        hash2 = compute_content_hash("Goodbye World")
        assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Test that hash is 64 characters (SHA-256 hex)."""
        result = compute_content_hash("Test")
        assert len(result) == 64


class TestTokenize:
    """Tests for tokenize function."""

    def test_tokenize_simple(self) -> None:
        """Test simple tokenization."""
        result = tokenize("Hello World")
        assert result == ["hello", "world"]

    def test_tokenize_punctuation(self) -> None:
        """Test that punctuation is removed."""
        result = tokenize("Hello, World!")
        assert result == ["hello", "world"]

    def test_tokenize_empty(self) -> None:
        """Test empty string."""
        result = tokenize("")
        assert result == []

    def test_tokenize_numbers(self) -> None:
        """Test that numbers are preserved."""
        result = tokenize("Test 123 abc")
        assert result == ["test", "123", "abc"]


class TestCosineSimilarity:
    """Tests for cosine_similarity function."""

    def test_identical_texts(self) -> None:
        """Test similarity of identical texts."""
        tokens = ["hello", "world"]
        result = cosine_similarity(tokens, tokens)
        assert abs(result - 1.0) < 1e-10  # Use approximate comparison

    def test_completely_different(self) -> None:
        """Test similarity of completely different texts."""
        tokens1 = ["hello", "world"]
        tokens2 = ["goodbye", "moon"]
        result = cosine_similarity(tokens1, tokens2)
        assert result == 0.0

    def test_partial_overlap(self) -> None:
        """Test similarity of partially overlapping texts."""
        tokens1 = ["hello", "world", "test"]
        tokens2 = ["hello", "world", "different"]
        result = cosine_similarity(tokens1, tokens2)
        # Should be between 0 and 1
        assert 0.0 < result < 1.0

    def test_empty_tokens(self) -> None:
        """Test with empty token lists."""
        result = cosine_similarity([], ["hello"])
        assert result == 0.0

    def test_similarity_symmetric(self) -> None:
        """Test that similarity is symmetric."""
        tokens1 = ["hello", "world"]
        tokens2 = ["world", "test"]
        sim1 = cosine_similarity(tokens1, tokens2)
        sim2 = cosine_similarity(tokens2, tokens1)
        assert sim1 == sim2


# =============================================================================
# DUPLICATE RESULT TESTS
# =============================================================================


class TestDuplicateResult:
    """Tests for DuplicateResult dataclass."""

    def test_not_duplicate(self) -> None:
        """Test non-duplicate result."""
        result = DuplicateResult(is_duplicate=False)
        assert result.is_duplicate is False
        assert result.duplicate_of is None
        assert result.score == 0.0

    def test_duplicate_result(self) -> None:
        """Test duplicate result."""
        result = DuplicateResult(
            is_duplicate=True,
            duplicate_of="guid-123",
            score=1.0,
            method="hash",
        )
        assert result.is_duplicate is True
        assert result.duplicate_of == "guid-123"
        assert result.score == 1.0
        assert result.method == "hash"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = DuplicateResult(
            is_duplicate=True,
            duplicate_of="guid-123",
            score=0.98,
            method="similarity",
        )
        d = result.to_dict()
        assert d["is_duplicate"] is True
        assert d["duplicate_of"] == "guid-123"
        assert d["score"] == 0.98
        assert d["method"] == "similarity"


# =============================================================================
# EXACT DUPLICATE DETECTION TESTS
# =============================================================================


class TestExactDuplicateDetection:
    """Tests for exact duplicate detection via hash matching."""

    def test_detect_exact_duplicate(self) -> None:
        """Test detection of exact duplicate."""
        detector = DuplicateDetector()

        # Register original
        detector.register("doc-001", "Test Title", "Test content here")

        # Check duplicate
        result = detector.check("Test Title", "Test content here")

        assert result.is_duplicate is True
        assert result.duplicate_of == "doc-001"
        assert result.score == 1.0
        assert result.method == "hash"

    def test_no_duplicate_different_content(self) -> None:
        """Test that different content is not flagged."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Test Title", "Original content")
        result = detector.check("Different Title", "Different content")

        assert result.is_duplicate is False

    def test_case_insensitive_matching(self) -> None:
        """Test case-insensitive duplicate detection."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Test Title", "Test content here")
        result = detector.check("TEST TITLE", "TEST CONTENT HERE")

        assert result.is_duplicate is True
        assert result.duplicate_of == "doc-001"

    def test_whitespace_normalized_matching(self) -> None:
        """Test whitespace-normalized duplicate detection."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Test Title", "Test content here")
        result = detector.check("Test  Title", "Test   content  here")

        assert result.is_duplicate is True
        assert result.duplicate_of == "doc-001"


# =============================================================================
# NEAR-DUPLICATE DETECTION TESTS
# =============================================================================


class TestNearDuplicateDetection:
    """Tests for near-duplicate detection via similarity matching."""

    def test_detect_near_duplicate(self) -> None:
        """Test detection of near-duplicate with high similarity."""
        detector = DuplicateDetector(similarity_threshold=0.8)

        # Register original
        original = (
            "The stock market in Tokyo showed strong gains today. "
            "Major indices rose by 2% on positive economic data."
        )
        detector.register("doc-001", "Market Update", original)

        # Very similar text
        similar = (
            "The stock market in Tokyo showed strong gains today. "
            "Major indices rose by 2% following positive economic data."
        )
        result = detector.check("Market Update", similar)

        assert result.is_duplicate is True
        assert result.duplicate_of == "doc-001"
        assert result.score >= 0.8
        assert result.method == "similarity"

    def test_below_threshold_not_duplicate(self) -> None:
        """Test that text below threshold is not flagged."""
        detector = DuplicateDetector(similarity_threshold=0.95)

        detector.register("doc-001", "Market Update", "Tokyo stock market gained 2%")
        result = detector.check("Sports News", "Tokyo baseball team won championship")

        assert result.is_duplicate is False

    def test_custom_threshold(self) -> None:
        """Test custom similarity threshold."""
        # High threshold - should not match
        detector_high = DuplicateDetector(similarity_threshold=0.99)
        detector_high.register("doc-001", "Title", "Hello world test content")
        result_high = detector_high.check("Title", "Hello world test different")
        assert result_high.is_duplicate is False

        # Low threshold - should match
        detector_low = DuplicateDetector(similarity_threshold=0.5)
        detector_low.register("doc-001", "Title", "Hello world test content")
        result_low = detector_low.check("Title", "Hello world test different")
        assert result_low.is_duplicate is True


# =============================================================================
# DETECTOR MANAGEMENT TESTS
# =============================================================================


class TestDuplicateDetectorManagement:
    """Tests for detector management operations."""

    def test_register_and_check(self) -> None:
        """Test registering documents."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Title 1", "Content 1")
        detector.register("doc-002", "Title 2", "Content 2")

        assert detector.document_count == 2

    def test_unregister(self) -> None:
        """Test unregistering documents."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Title 1", "Content 1")
        assert detector.document_count == 1

        removed = detector.unregister("doc-001")
        assert removed is True
        assert detector.document_count == 0

    def test_unregister_nonexistent(self) -> None:
        """Test unregistering nonexistent document."""
        detector = DuplicateDetector()
        removed = detector.unregister("nonexistent")
        assert removed is False

    def test_clear(self) -> None:
        """Test clearing all documents."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Title 1", "Content 1")
        detector.register("doc-002", "Title 2", "Content 2")
        detector.clear()

        assert detector.document_count == 0

    def test_check_and_register(self) -> None:
        """Test check_and_register convenience method."""
        detector = DuplicateDetector()

        # First document - not a duplicate
        result1 = detector.check_and_register("doc-001", "Title", "Content")
        assert result1.is_duplicate is False
        assert detector.document_count == 1

        # Same content - is a duplicate, but still registered
        result2 = detector.check_and_register("doc-002", "Title", "Content")
        assert result2.is_duplicate is True
        assert result2.duplicate_of == "doc-001"
        assert detector.document_count == 2

    def test_repr(self) -> None:
        """Test string representation."""
        detector = DuplicateDetector(similarity_threshold=0.9)
        detector.register("doc-001", "Title", "Content")
        repr_str = repr(detector)
        assert "DuplicateDetector" in repr_str
        assert "documents=1" in repr_str
        assert "threshold=0.9" in repr_str


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestDuplicateDetectorConfiguration:
    """Tests for detector configuration options."""

    def test_disable_hash_detection(self) -> None:
        """Test disabling hash detection."""
        detector = DuplicateDetector(use_hash_detection=False)

        detector.register("doc-001", "Title", "Content")
        result = detector.check("Title", "Content")

        # Should still find via similarity since identical
        assert result.is_duplicate is True
        assert result.method == "similarity"

    def test_disable_similarity_detection(self) -> None:
        """Test disabling similarity detection."""
        detector = DuplicateDetector(
            use_similarity_detection=False,
            similarity_threshold=0.5,
        )

        detector.register("doc-001", "Title", "Hello world content")
        result = detector.check("Title", "Hello world different")

        # Should not find near-duplicate
        assert result.is_duplicate is False

    def test_disable_both_detections(self) -> None:
        """Test with both detection methods disabled."""
        detector = DuplicateDetector(
            use_hash_detection=False,
            use_similarity_detection=False,
        )

        detector.register("doc-001", "Title", "Content")
        result = detector.check("Title", "Content")

        # Should not detect anything
        assert result.is_duplicate is False


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_content(self) -> None:
        """Test handling of empty content."""
        detector = DuplicateDetector()
        result = detector.check("", "")
        assert result.is_duplicate is False

    def test_whitespace_only(self) -> None:
        """Test handling of whitespace-only content."""
        detector = DuplicateDetector()
        detector.register("doc-001", "  ", "  ")
        # After normalization, both are empty strings
        result = detector.check("", "")
        # Empty normalized content should not match
        assert result.is_duplicate is False

    def test_unicode_content(self) -> None:
        """Test duplicate detection with Unicode content."""
        detector = DuplicateDetector()

        # Chinese content
        detector.register("doc-001", "市场新闻", "今日股市大涨")
        result = detector.check("市场新闻", "今日股市大涨")
        assert result.is_duplicate is True

    def test_mixed_language(self) -> None:
        """Test duplicate detection with mixed language content."""
        detector = DuplicateDetector()

        detector.register("doc-001", "Market News 市场新闻", "Strong gains 大涨")
        result = detector.check("Market News 市场新闻", "Strong gains 大涨")
        assert result.is_duplicate is True

    def test_long_content(self) -> None:
        """Test duplicate detection with long content."""
        detector = DuplicateDetector()

        long_content = "Lorem ipsum " * 1000
        detector.register("doc-001", "Long Document", long_content)
        result = detector.check("Long Document", long_content)
        assert result.is_duplicate is True


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_check_duplicate(self) -> None:
        """Test check_duplicate function."""
        # Function uses default detector
        result = check_duplicate("Test Title", "Test Content")
        # First check should not be a duplicate
        assert isinstance(result, DuplicateResult)


# =============================================================================
# INGEST INTEGRATION TESTS (placeholder for Phase 7)
# =============================================================================


class TestIngestIntegration:
    """Tests for duplicate detection during ingestion.

    These tests verify the integration between duplicate detection
    and the ingest flow. Full integration tests will be added in Phase 7.
    """

    def test_ingest_flow_marks_duplicate(self) -> None:
        """Test that ingestion marks duplicate documents."""
        detector = DuplicateDetector()

        # Simulate ingest of first document
        result1 = detector.check_and_register(
            guid="guid-001",
            title="Breaking News",
            content="Markets surge on positive data",
        )
        assert result1.is_duplicate is False

        # Simulate ingest of duplicate
        result2 = detector.check_and_register(
            guid="guid-002",
            title="Breaking News",
            content="Markets surge on positive data",
        )
        assert result2.is_duplicate is True
        assert result2.duplicate_of == "guid-001"
        assert result2.score == 1.0

    def test_duplicate_sets_correct_fields(self) -> None:
        """Test that duplicate detection sets correct fields for Document."""
        detector = DuplicateDetector()

        detector.register("original-guid", "Title", "Content")
        result = detector.check("Title", "Content")

        # These values would be set on Document.duplicate_of and Document.duplicate_score
        assert result.duplicate_of == "original-guid"
        assert result.score == 1.0
