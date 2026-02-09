"""Mandate Enrichment Service

Extracts investment themes from free-text mandate descriptions using LLM.
Designed to run at update-time (not query-time) for deterministic results.

Key design principles:
- Idempotent: same mandate_text → same themes (via hash caching)
- Async-safe: can be called synchronously or enqueued for background processing
- No query-time LLM: enrichment happens when mandate_text changes, never at search time
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.logger import StructuredLogger
from app.models.themes import VALID_THEMES
from app.services.llm_service import (
    ChatCompletionResult,
    ChatMessage,
    LLMService,
    LLMServiceError,
)

logger = StructuredLogger(__name__)

# System prompt for theme extraction
MANDATE_THEME_EXTRACTION_PROMPT = """You are an expert investment analyst assistant.
Your task is to extract relevant investment themes from fund mandate descriptions.

IMPORTANT: You must ONLY use themes from this controlled vocabulary:
{themes}

Rules:
1. Extract 1-5 themes that are EXPLICITLY supported by the mandate text
2. Do NOT infer themes that are not mentioned or strongly implied
3. Use lowercase theme names exactly as listed above
4. Return ONLY a JSON object with a "themes" array
5. If no themes match, return {{"themes": []}}

Example input: "We focus on semiconductor supply chains in Asia, with emphasis on Korean and Japanese manufacturers."
Example output: {{"themes": ["semiconductor", "supply_chain", "korea", "japan"]}}

Example input: "Our fund invests in US large cap equities with no sector restrictions."
Example output: {{"themes": []}}
"""

USER_PROMPT_TEMPLATE = """Extract investment themes from this fund mandate description:

{mandate_text}

Return ONLY valid JSON: {{"themes": ["theme1", "theme2", ...]}}"""


@dataclass
class MandateEnrichmentResult:
    """Result of mandate text enrichment"""
    
    mandate_text: str
    mandate_text_hash: str
    themes: list[str]
    raw_response: str | None = None
    error: str | None = None
    
    @property
    def success(self) -> bool:
        """Check if enrichment was successful"""
        return self.error is None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "mandate_text_hash": self.mandate_text_hash,
            "themes": self.themes,
            "error": self.error,
        }


class MandateEnrichmentError(Exception):
    """Error during mandate enrichment"""
    pass


def compute_mandate_hash(mandate_text: str) -> str:
    """Compute a stable hash for mandate text (for idempotency)
    
    Args:
        mandate_text: The mandate text to hash
        
    Returns:
        SHA-256 hash of normalized mandate text (first 16 hex chars)
    """
    # Normalize: strip whitespace, lowercase
    normalized = mandate_text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def extract_themes_from_mandate(
    mandate_text: str,
    llm_service: LLMService,
    temperature: float = 0.0,
) -> MandateEnrichmentResult:
    """Extract investment themes from mandate text using LLM
    
    This function is idempotent - the same mandate text will produce
    consistent results (using temperature=0 for determinism).
    
    Args:
        mandate_text: Free-text fund mandate description
        llm_service: Configured LLM service instance
        temperature: LLM temperature (0 for deterministic results)
        
    Returns:
        MandateEnrichmentResult with extracted themes or error
    """
    mandate_hash = compute_mandate_hash(mandate_text)
    
    # Handle empty mandate
    if not mandate_text.strip():
        return MandateEnrichmentResult(
            mandate_text=mandate_text,
            mandate_text_hash=mandate_hash,
            themes=[],
        )
    
    # Check if LLM is available
    if not llm_service.is_available:
        logger.warning(
            "LLM service not available for mandate enrichment",
            mandate_hash=mandate_hash,
        )
        return MandateEnrichmentResult(
            mandate_text=mandate_text,
            mandate_text_hash=mandate_hash,
            themes=[],
            error="LLM service not configured",
        )
    
    # Build messages
    system_prompt = MANDATE_THEME_EXTRACTION_PROMPT.format(
        themes=", ".join(sorted(VALID_THEMES))
    )
    user_prompt = USER_PROMPT_TEMPLATE.format(mandate_text=mandate_text)
    
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    ]
    
    try:
        logger.info(
            "Extracting themes from mandate text",
            mandate_hash=mandate_hash,
            mandate_length=len(mandate_text),
        )
        
        result: ChatCompletionResult = llm_service.chat_completion(
            messages=messages,
            json_mode=True,
            temperature=temperature,
            max_tokens=200,
        )
        
        # Parse JSON response
        raw_content = result.content.strip()
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse LLM response as JSON",
                mandate_hash=mandate_hash,
                raw_content=raw_content,
                error=str(e),
            )
            return MandateEnrichmentResult(
                mandate_text=mandate_text,
                mandate_text_hash=mandate_hash,
                themes=[],
                raw_response=raw_content,
                error=f"Invalid JSON response: {e}",
            )
        
        # Extract and validate themes
        raw_themes = parsed.get("themes", [])
        if not isinstance(raw_themes, list):
            return MandateEnrichmentResult(
                mandate_text=mandate_text,
                mandate_text_hash=mandate_hash,
                themes=[],
                raw_response=raw_content,
                error=f"Expected 'themes' to be a list, got {type(raw_themes).__name__}",
            )
        
        # Filter to valid themes only
        valid_themes = []
        invalid_themes = []
        for theme in raw_themes:
            if isinstance(theme, str):
                normalized = theme.strip().lower()
                if normalized in VALID_THEMES:
                    valid_themes.append(normalized)
                else:
                    invalid_themes.append(theme)
        
        if invalid_themes:
            logger.warning(
                "LLM returned invalid themes (filtered out)",
                mandate_hash=mandate_hash,
                invalid_themes=invalid_themes,
            )
        
        logger.info(
            "Successfully extracted themes from mandate",
            mandate_hash=mandate_hash,
            themes=valid_themes,
            theme_count=len(valid_themes),
        )
        
        return MandateEnrichmentResult(
            mandate_text=mandate_text,
            mandate_text_hash=mandate_hash,
            themes=valid_themes,
            raw_response=raw_content,
        )
        
    except LLMServiceError as e:
        logger.error(
            "LLM service error during mandate enrichment",
            mandate_hash=mandate_hash,
            error=str(e),
        )
        return MandateEnrichmentResult(
            mandate_text=mandate_text,
            mandate_text_hash=mandate_hash,
            themes=[],
            error=f"LLM error: {e}",
        )


def enrich_mandate_themes_sync(
    mandate_text: str,
    llm_service: LLMService | None = None,
    config: Any | None = None,
) -> MandateEnrichmentResult:
    """Synchronous wrapper for mandate theme extraction
    
    Creates LLM service if not provided. Suitable for direct calls
    from MCP tools or synchronous code paths.
    
    Args:
        mandate_text: Free-text fund mandate description
        llm_service: Optional pre-configured LLM service
        config: Optional GofrIqConfig for creating LLM service
        
    Returns:
        MandateEnrichmentResult with extracted themes
    """
    if llm_service is None:
        from app.services.llm_service import create_llm_service
        llm_service = create_llm_service(config=config)
    
    try:
        return extract_themes_from_mandate(mandate_text, llm_service)
    finally:
        # Clean up if we created the service
        if llm_service is not None:
            llm_service.close()


# Export public API
__all__ = [
    "VALID_THEMES",
    "MandateEnrichmentResult",
    "MandateEnrichmentError",
    "compute_mandate_hash",
    "extract_themes_from_mandate",
    "enrich_mandate_themes_sync",
]
