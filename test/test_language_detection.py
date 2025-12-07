"""Tests for Language Detection - Phase 5.

Tests for automatic language detection with focus on APAC languages
(English, Chinese, Japanese, Korean, etc.).
"""

from __future__ import annotations

from app.services import (
    LanguageDetector,
    LanguageResult,
    detect_language,
    detect_language_with_confidence,
)


# =============================================================================
# Phase 5.1: Language Detection Tests
# =============================================================================


class TestDetectEnglish:
    """Tests for English language detection."""

    def test_detect_english_simple(self) -> None:
        """Test detecting simple English text."""
        detector = LanguageDetector()
        result = detector.detect(
            "This is a simple English sentence for testing language detection."
        )

        assert result.language == "en"
        assert result.confidence > 0.5
        assert result.is_apac is True  # English is APAC-focused

    def test_detect_english_financial(self) -> None:
        """Test detecting English financial news text."""
        detector = LanguageDetector()
        text = """
        The Federal Reserve announced today that interest rates will remain 
        unchanged at 5.25% following their latest monetary policy meeting. 
        Markets reacted positively with the S&P 500 gaining 0.5% in early trading.
        """
        result = detector.detect(text)

        assert result.language == "en"
        assert result.confidence > 0.7

    def test_detect_english_short_text(self) -> None:
        """Test that very short text returns default."""
        detector = LanguageDetector()
        result = detector.detect("Hi there")  # Less than min_text_length

        assert result.language == "en"  # Default
        assert result.confidence == 0.0  # Low confidence for short text


class TestDetectChinese:
    """Tests for Chinese language detection."""

    def test_detect_chinese_simplified(self) -> None:
        """Test detecting simplified Chinese text."""
        detector = LanguageDetector()
        text = "中国人民银行今日宣布将基准利率维持不变，市场对此反应积极。"
        result = detector.detect(text)

        assert result.language == "zh"
        assert result.confidence > 0.5
        assert result.is_apac is True

    def test_detect_chinese_financial(self) -> None:
        """Test detecting Chinese financial news."""
        detector = LanguageDetector()
        text = """
        上海证券交易所今日开盘，沪指高开后震荡走低。
        科技板块领涨，其中半导体概念股涨幅居前。
        市场人士分析认为，近期政策利好将持续提振市场信心。
        """
        result = detector.detect(text)

        assert result.language == "zh"
        assert result.confidence > 0.7


class TestDetectJapanese:
    """Tests for Japanese language detection."""

    def test_detect_japanese(self) -> None:
        """Test detecting Japanese text."""
        detector = LanguageDetector()
        text = "日本銀行は本日、金融政策決定会合を開催し、現行の金融緩和政策を維持することを決定しました。"
        result = detector.detect(text)

        assert result.language == "ja"
        assert result.confidence > 0.5
        assert result.is_apac is True

    def test_detect_japanese_hiragana(self) -> None:
        """Test detecting Japanese with hiragana."""
        detector = LanguageDetector()
        text = "これは日本語のテストです。今日の天気はとても良いですね。"
        result = detector.detect(text)

        assert result.language == "ja"
        assert result.confidence > 0.5

    def test_detect_japanese_financial(self) -> None:
        """Test detecting Japanese financial news."""
        detector = LanguageDetector()
        text = """
        東京株式市場は続伸で始まった。日経平均株価は前日比100円高の
        33,000円台で推移している。米国株高を受けて投資家心理が改善した。
        """
        result = detector.detect(text)

        assert result.language == "ja"


class TestDetectKorean:
    """Tests for Korean language detection."""

    def test_detect_korean(self) -> None:
        """Test detecting Korean text."""
        detector = LanguageDetector()
        text = "한국은행은 오늘 기준금리를 동결하기로 결정했습니다. 시장은 이에 긍정적으로 반응했습니다."
        result = detector.detect(text)

        assert result.language == "ko"
        assert result.confidence > 0.5
        assert result.is_apac is True


class TestDetectOtherLanguages:
    """Tests for other language detection."""

    def test_detect_indonesian(self) -> None:
        """Test detecting Indonesian text."""
        detector = LanguageDetector()
        text = "Bank Indonesia hari ini mengumumkan keputusan untuk mempertahankan suku bunga acuan."
        result = detector.detect(text)

        assert result.language == "id"
        assert result.is_apac is True

    def test_detect_thai(self) -> None:
        """Test detecting Thai text."""
        detector = LanguageDetector()
        text = "ธนาคารแห่งประเทศไทยประกาศคงอัตราดอกเบี้ยนโยบายในวันนี้"
        result = detector.detect(text)

        assert result.language == "th"
        assert result.is_apac is True


class TestLanguageDetectorMethods:
    """Tests for LanguageDetector methods."""

    def test_detect_simple(self) -> None:
        """Test the detect_simple convenience method."""
        detector = LanguageDetector()
        lang = detector.detect_simple(
            "This is a test sentence for language detection."
        )

        assert lang == "en"

    def test_detect_with_fallback(self) -> None:
        """Test detection with custom fallback."""
        detector = LanguageDetector()

        # Short text should use fallback
        lang = detector.detect_with_fallback("Hi", fallback="zh")

        assert lang == "zh"

    def test_is_cjk(self) -> None:
        """Test CJK character detection."""
        detector = LanguageDetector()

        assert detector.is_cjk("中文测试") is True
        assert detector.is_cjk("日本語テスト") is True
        assert detector.is_cjk("한국어") is True
        assert detector.is_cjk("English only") is False
        assert detector.is_cjk("Mixed 中文 English") is True

    def test_detect_from_title_and_content(self) -> None:
        """Test detection from title and content."""
        detector = LanguageDetector()

        result = detector.detect_from_title_and_content(
            title="Short title",
            content="This is a longer English content that should be detected with higher confidence than the short title.",
        )

        assert result.language == "en"

    def test_empty_text(self) -> None:
        """Test handling of empty text."""
        detector = LanguageDetector()

        result = detector.detect("")

        assert result.language == "en"  # Default
        assert result.confidence == 0.0

    def test_whitespace_only(self) -> None:
        """Test handling of whitespace-only text."""
        detector = LanguageDetector()

        result = detector.detect("   \n\t   ")

        assert result.language == "en"  # Default
        assert result.confidence == 0.0


class TestLanguageResult:
    """Tests for LanguageResult dataclass."""

    def test_language_result_to_dict(self) -> None:
        """Test LanguageResult serialization."""
        result = LanguageResult(
            language="en",
            confidence=0.95,
            detected_code="en",
            is_apac=True,
        )

        d = result.to_dict()

        assert d["language"] == "en"
        assert d["confidence"] == 0.95
        assert d["detected_code"] == "en"
        assert d["is_apac"] is True


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_detect_language(self) -> None:
        """Test the module-level detect_language function."""
        lang = detect_language(
            "This is a test sentence for the module-level function."
        )

        assert lang == "en"

    def test_detect_language_with_confidence(self) -> None:
        """Test the module-level detect_language_with_confidence function."""
        result = detect_language_with_confidence(
            "This is another test sentence for language detection with confidence."
        )

        assert isinstance(result, LanguageResult)
        assert result.language == "en"
        assert result.confidence > 0.5


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_mixed_language_text(self) -> None:
        """Test handling of mixed-language text."""
        detector = LanguageDetector()

        # Mostly English with some Chinese
        text = "The company announced 股东大会 will be held next week."
        result = detector.detect(text)

        # Should detect the dominant language
        assert result.language in ["en", "zh"]

    def test_numeric_text(self) -> None:
        """Test handling of primarily numeric text."""
        detector = LanguageDetector()

        text = "1234567890 + 9876543210 = 11111111100"
        result = detector.detect(text)

        # Should return default for non-textual content
        assert result.language == "en"

    def test_custom_default_language(self) -> None:
        """Test custom default language."""
        detector = LanguageDetector(default_language="zh")

        result = detector.detect("Hi")  # Too short

        assert result.language == "zh"

    def test_custom_min_text_length(self) -> None:
        """Test custom minimum text length."""
        detector = LanguageDetector(min_text_length=5)

        # Now "Hello there" should be detected
        result = detector.detect("Hello there!")

        assert result.confidence > 0.0  # Should attempt detection


# =============================================================================
# Phase 5.2: Integration Tests (placeholder for ingest integration)
# =============================================================================


class TestLanguageDetectorConfiguration:
    """Tests for detector configuration."""

    def test_default_configuration(self) -> None:
        """Test default detector configuration."""
        detector = LanguageDetector()

        assert detector.default_language == "en"
        assert detector.min_text_length == 20

    def test_apac_languages(self) -> None:
        """Test APAC language classification."""
        from app.services.language_detector import APAC_LANGUAGES

        assert "en" in APAC_LANGUAGES
        assert "zh" in APAC_LANGUAGES
        assert "ja" in APAC_LANGUAGES
        assert "ko" in APAC_LANGUAGES

    def test_language_code_mapping(self) -> None:
        """Test language code normalization."""
        from app.services.language_detector import LANGUAGE_CODE_MAP

        # Chinese variants should map to zh
        assert LANGUAGE_CODE_MAP.get("zh-cn") == "zh"
        assert LANGUAGE_CODE_MAP.get("zh-tw") == "zh"
