"""Language Detection Service for APAC Brokerage News Repository.

This module provides automatic language detection for documents using
the langdetect library. Supports CJK (Chinese, Japanese, Korean) languages
along with English and other European languages.

The detector is designed for financial news content and handles:
- Short snippets (titles, abstracts)
- Mixed-language content
- Technical/financial terminology
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# langdetect is the industry-standard library for language detection
# It's based on Google's language-detection library
try:
    from langdetect import detect_langs as _detect_langs
    from langdetect import LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    _detect_langs = None  # type: ignore[assignment]
    LangDetectException = Exception  # type: ignore[misc, assignment]


# Mapping of langdetect codes to our standardized ISO 639-1 codes
LANGUAGE_CODE_MAP = {
    "en": "en",  # English
    "zh-cn": "zh",  # Chinese (Simplified)
    "zh-tw": "zh",  # Chinese (Traditional)
    "ja": "ja",  # Japanese
    "ko": "ko",  # Korean
    "id": "id",  # Indonesian
    "ms": "ms",  # Malay
    "th": "th",  # Thai
    "vi": "vi",  # Vietnamese
    "de": "de",  # German
    "fr": "fr",  # French
    "es": "es",  # Spanish
    "pt": "pt",  # Portuguese
    "ru": "ru",  # Russian
    "ar": "ar",  # Arabic
    "hi": "hi",  # Hindi
}

# APAC-focused languages we prioritize
APAC_LANGUAGES = {"en", "zh", "ja", "ko", "id", "ms", "th", "vi"}

# Default language when detection fails or text is too short
DEFAULT_LANGUAGE = "en"

# Minimum text length for reliable detection
MIN_TEXT_LENGTH = 20


class LanguageDetectionError(Exception):
    """Raised when language detection fails."""

    def __init__(self, reason: str, text_sample: str | None = None) -> None:
        self.reason = reason
        self.text_sample = text_sample[:50] if text_sample else None
        super().__init__(f"Language detection failed: {reason}")


@dataclass
class LanguageResult:
    """Result of language detection.
    
    Attributes:
        language: ISO 639-1 language code (e.g., "en", "zh", "ja")
        confidence: Confidence score (0.0 to 1.0)
        detected_code: Original code from langdetect (may differ from language)
        is_apac: Whether the language is in the APAC focus set
    """
    language: str
    confidence: float
    detected_code: str
    is_apac: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "language": self.language,
            "confidence": self.confidence,
            "detected_code": self.detected_code,
            "is_apac": self.is_apac,
        }


class LanguageDetector:
    """Service for detecting document language.
    
    Uses the langdetect library to identify document language from text.
    Supports all major APAC languages including CJK (Chinese, Japanese, Korean).
    
    Example:
        >>> detector = LanguageDetector()
        >>> result = detector.detect("This is an English sentence.")
        >>> result.language
        'en'
        >>> result = detector.detect("これは日本語の文章です。")
        >>> result.language
        'ja'
    """

    def __init__(
        self,
        default_language: str = DEFAULT_LANGUAGE,
        min_text_length: int = MIN_TEXT_LENGTH,
    ) -> None:
        """Initialize the language detector.
        
        Args:
            default_language: Fallback language when detection fails
            min_text_length: Minimum text length for detection
        """
        self.default_language = default_language
        self.min_text_length = min_text_length
        self._langdetect_available = LANGDETECT_AVAILABLE

    def detect(self, text: str) -> LanguageResult:
        """Detect the language of a text.
        
        Args:
            text: Text to analyze
            
        Returns:
            LanguageResult with detected language and confidence
            
        Raises:
            LanguageDetectionError: If detection fails unexpectedly
        """
        # Handle empty or short text
        if not text or len(text.strip()) < self.min_text_length:
            return LanguageResult(
                language=self.default_language,
                confidence=0.0,
                detected_code=self.default_language,
                is_apac=self.default_language in APAC_LANGUAGES,
            )

        # If langdetect not available, return default
        if not self._langdetect_available:
            return LanguageResult(
                language=self.default_language,
                confidence=0.5,
                detected_code=self.default_language,
                is_apac=self.default_language in APAC_LANGUAGES,
            )

        try:
            # Get language probabilities
            if _detect_langs is None:
                return self._default_result()
            detected_langs = _detect_langs(text)
            
            if not detected_langs:
                return self._default_result()

            # Get the most probable language
            top_lang = detected_langs[0]
            detected_code = str(top_lang.lang)
            confidence = float(top_lang.prob)

            # Map to our standardized code
            language = LANGUAGE_CODE_MAP.get(detected_code, detected_code)

            return LanguageResult(
                language=language,
                confidence=confidence,
                detected_code=detected_code,
                is_apac=language in APAC_LANGUAGES,
            )

        except LangDetectException:
            # Detection failed (e.g., text too short, no features)
            return self._default_result()
        except Exception as e:
            raise LanguageDetectionError(str(e), text) from e

    def detect_simple(self, text: str) -> str:
        """Detect language and return just the language code.
        
        Convenience method for simple use cases.
        
        Args:
            text: Text to analyze
            
        Returns:
            ISO 639-1 language code
        """
        return self.detect(text).language

    def detect_with_fallback(self, text: str, fallback: str = "en") -> str:
        """Detect language with custom fallback.
        
        Args:
            text: Text to analyze
            fallback: Language code to use if detection fails
            
        Returns:
            ISO 639-1 language code
        """
        result = self.detect(text)
        if result.confidence < 0.5:
            return fallback
        return result.language

    def _default_result(self) -> LanguageResult:
        """Create a default result when detection fails."""
        return LanguageResult(
            language=self.default_language,
            confidence=0.0,
            detected_code=self.default_language,
            is_apac=self.default_language in APAC_LANGUAGES,
        )

    def is_cjk(self, text: str) -> bool:
        """Check if text contains CJK (Chinese, Japanese, Korean) characters.
        
        This is a quick heuristic check without full language detection.
        
        Args:
            text: Text to check
            
        Returns:
            True if text contains CJK characters
        """
        for char in text:
            code = ord(char)
            # CJK Unified Ideographs
            if 0x4E00 <= code <= 0x9FFF:
                return True
            # Hiragana
            if 0x3040 <= code <= 0x309F:
                return True
            # Katakana
            if 0x30A0 <= code <= 0x30FF:
                return True
            # Hangul
            if 0xAC00 <= code <= 0xD7AF:
                return True
        return False

    def detect_from_title_and_content(
        self,
        title: str,
        content: str,
    ) -> LanguageResult:
        """Detect language from both title and content.
        
        Uses content primarily, but falls back to title if content
        detection is low confidence.
        
        Args:
            title: Document title
            content: Document content
            
        Returns:
            LanguageResult with best detection
        """
        # Try content first (usually more reliable)
        content_result = self.detect(content)
        
        if content_result.confidence >= 0.8:
            return content_result

        # Try title if content confidence is low
        title_result = self.detect(title)
        
        # Return whichever has higher confidence
        if title_result.confidence > content_result.confidence:
            return title_result
        return content_result


# Module-level convenience functions
_default_detector: LanguageDetector | None = None


def get_detector() -> LanguageDetector:
    """Get the default language detector instance."""
    global _default_detector
    if _default_detector is None:
        _default_detector = LanguageDetector()
    return _default_detector


def detect_language(text: str) -> str:
    """Detect language of text using the default detector.
    
    Args:
        text: Text to analyze
        
    Returns:
        ISO 639-1 language code
    """
    return get_detector().detect_simple(text)


def detect_language_with_confidence(text: str) -> LanguageResult:
    """Detect language with confidence score.
    
    Args:
        text: Text to analyze
        
    Returns:
        LanguageResult with language and confidence
    """
    return get_detector().detect(text)
