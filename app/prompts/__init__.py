"""Prompts package for LLM interactions

This package contains prompt templates and engineering for LLM-based
document analysis, entity extraction, and graph population.
"""

from app.prompts.graph_extraction import (
    GRAPH_EXTRACTION_SYSTEM_PROMPT,
    GraphExtractionResult,
    InstrumentMention,
    EventDetection,
    build_extraction_prompt,
    parse_extraction_response,
)

__all__ = [
    "GRAPH_EXTRACTION_SYSTEM_PROMPT",
    "GraphExtractionResult",
    "InstrumentMention",
    "EventDetection",
    "build_extraction_prompt",
    "parse_extraction_response",
]
