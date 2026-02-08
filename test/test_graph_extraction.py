"""Tests for Graph Extraction Prompt

Unit tests for the graph extraction prompt construction and response parsing.
"""

from __future__ import annotations

import json

import pytest

from app.prompts.graph_extraction import (
    GRAPH_EXTRACTION_SYSTEM_PROMPT,
    EventDetection,
    ExtractionParseError,
    GraphExtractionResult,
    InstrumentMention,
    build_extraction_prompt,
    create_default_result,
    parse_extraction_response,
)


# ============================================================================
# EventDetection Tests
# ============================================================================


class TestEventDetection:
    """Tests for EventDetection dataclass"""

    def test_basic_event(self) -> None:
        """Test creating a basic event"""
        event = EventDetection(
            event_type="EARNINGS_BEAT",
            confidence=0.95,
            details="Q3 EPS exceeded expectations",
        )
        assert event.event_type == "EARNINGS_BEAT"
        assert event.confidence == 0.95
        assert event.details == "Q3 EPS exceeded expectations"

    def test_to_dict(self) -> None:
        """Test converting to dictionary"""
        event = EventDetection(
            event_type="M&A_ANNOUNCE",
            confidence=0.98,
            details="Acquisition confirmed",
        )
        d = event.to_dict()
        assert d == {
            "event_type": "M&A_ANNOUNCE",
            "confidence": 0.98,
            "details": "Acquisition confirmed",
        }

    def test_default_details(self) -> None:
        """Test default empty details"""
        event = EventDetection(event_type="OTHER", confidence=0.5)
        assert event.details == ""


# ============================================================================
# InstrumentMention Tests
# ============================================================================


class TestInstrumentMention:
    """Tests for InstrumentMention dataclass"""

    def test_basic_instrument(self) -> None:
        """Test creating a basic instrument mention"""
        inst = InstrumentMention(
            ticker="AAPL",
            name="Apple Inc.",
            direction="UP",
            magnitude="MODERATE",
            reason="Beat earnings",
        )
        assert inst.ticker == "AAPL"
        assert inst.name == "Apple Inc."
        assert inst.direction == "UP"
        assert inst.magnitude == "MODERATE"

    def test_to_dict(self) -> None:
        """Test converting to dictionary"""
        inst = InstrumentMention(
            ticker="TSLA",
            name="Tesla Inc.",
            direction="DOWN",
            magnitude="HIGH",
            reason="Missed delivery targets",
        )
        d = inst.to_dict()
        assert d["ticker"] == "TSLA"
        assert d["direction"] == "DOWN"
        assert d["magnitude"] == "HIGH"

    def test_default_values(self) -> None:
        """Test default values"""
        inst = InstrumentMention(ticker="XYZ")
        assert inst.name == ""
        assert inst.direction == "NEUTRAL"
        assert inst.magnitude == "LOW"
        assert inst.reason == ""


# ============================================================================
# GraphExtractionResult Tests
# ============================================================================


class TestGraphExtractionResult:
    """Tests for GraphExtractionResult dataclass"""

    def test_basic_result(self) -> None:
        """Test creating a basic result"""
        result = GraphExtractionResult(
            impact_score=75,
            impact_tier="GOLD",
            summary="Apple beats earnings",
        )
        assert result.impact_score == 75
        assert result.impact_tier == "GOLD"
        assert result.summary == "Apple beats earnings"

    def test_to_dict(self) -> None:
        """Test converting to dictionary"""
        result = GraphExtractionResult(
            impact_score=90,
            impact_tier="PLATINUM",
            events=[EventDetection("M&A_ANNOUNCE", 0.98)],
            instruments=[InstrumentMention("AAPL", "Apple", "UP", "HIGH")],
            companies=["Apple Inc.", "Target Corp"],
            summary="Apple announces acquisition",
        )
        d = result.to_dict()
        assert d["impact_score"] == 90
        assert d["impact_tier"] == "PLATINUM"
        assert len(d["events"]) == 1
        assert len(d["instruments"]) == 1
        assert d["companies"] == ["Apple Inc.", "Target Corp"]

    def test_primary_event(self) -> None:
        """Test getting primary (highest confidence) event"""
        result = GraphExtractionResult(
            impact_score=70,
            impact_tier="GOLD",
            events=[
                EventDetection("GUIDANCE_RAISE", 0.8),
                EventDetection("EARNINGS_BEAT", 0.95),
                EventDetection("POSITIVE_SENTIMENT", 0.6),
            ],
        )
        primary = result.primary_event
        assert primary is not None
        assert primary.event_type == "EARNINGS_BEAT"
        assert primary.confidence == 0.95

    def test_primary_event_empty(self) -> None:
        """Test primary event with no events"""
        result = GraphExtractionResult(impact_score=20, impact_tier="STANDARD")
        assert result.primary_event is None

    def test_primary_ticker(self) -> None:
        """Test getting primary ticker"""
        result = GraphExtractionResult(
            impact_score=60,
            impact_tier="SILVER",
            instruments=[
                InstrumentMention("SPY", direction="NEUTRAL"),
                InstrumentMention("AAPL", direction="UP"),
                InstrumentMention("MSFT", direction="DOWN"),
            ],
        )
        # Should prefer directional (UP/DOWN) instruments
        assert result.primary_ticker == "AAPL"

    def test_primary_ticker_no_directional(self) -> None:
        """Test primary ticker when all neutral"""
        result = GraphExtractionResult(
            impact_score=30,
            impact_tier="BRONZE",
            instruments=[
                InstrumentMention("SPY", direction="NEUTRAL"),
                InstrumentMention("QQQ", direction="NEUTRAL"),
            ],
        )
        # Should return first instrument
        assert result.primary_ticker == "SPY"

    def test_primary_ticker_empty(self) -> None:
        """Test primary ticker with no instruments"""
        result = GraphExtractionResult(impact_score=20, impact_tier="STANDARD")
        assert result.primary_ticker is None


# ============================================================================
# Prompt Building Tests
# ============================================================================


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function"""

    def test_basic_prompt(self) -> None:
        """Test building a basic prompt"""
        prompt = build_extraction_prompt(
            content="Apple reported strong Q3 earnings today.",
        )
        assert "Apple reported strong Q3 earnings" in prompt
        assert "Analyze the following" in prompt
        assert "JSON only" in prompt

    def test_prompt_with_title(self) -> None:
        """Test prompt with title"""
        prompt = build_extraction_prompt(
            content="Full article content here.",
            title="Apple Beats Q3 Expectations",
        )
        assert "**Title**: Apple Beats Q3 Expectations" in prompt

    def test_prompt_with_metadata(self) -> None:
        """Test prompt with full metadata"""
        prompt = build_extraction_prompt(
            content="Article content.",
            title="Breaking News",
            source_name="Reuters",
            published_at="2024-01-15T10:30:00Z",
        )
        assert "**Title**: Breaking News" in prompt
        assert "**Source**: Reuters" in prompt
        assert "**Published**: 2024-01-15" in prompt


# ============================================================================
# Response Parsing Tests
# ============================================================================


class TestParseExtractionResponse:
    """Tests for parse_extraction_response function"""

    def test_valid_response(self) -> None:
        """Test parsing a valid JSON response"""
        response = json.dumps({
            "impact_score": 75,
            "impact_tier": "GOLD",
            "events": [
                {"event_type": "EARNINGS_BEAT", "confidence": 0.95, "details": "Q3 beat"}
            ],
            "instruments": [
                {"ticker": "AAPL", "name": "Apple", "direction": "UP", "magnitude": "MODERATE"}
            ],
            "companies": ["Apple Inc."],
            "summary": "Apple beats Q3 earnings",
        })
        
        result = parse_extraction_response(response)
        
        assert result.impact_score == 75
        assert result.impact_tier == "GOLD"
        assert len(result.events) == 1
        assert result.events[0].event_type == "EARNINGS_BEAT"
        assert len(result.instruments) == 1
        assert result.instruments[0].ticker == "AAPL"

    def test_markdown_wrapped_response(self) -> None:
        """Test parsing response wrapped in markdown code blocks"""
        response = """```json
{
    "impact_score": 50,
    "impact_tier": "SILVER",
    "events": [],
    "instruments": [],
    "companies": [],
    "summary": "Minor news"
}
```"""
        result = parse_extraction_response(response)
        assert result.impact_score == 50
        assert result.impact_tier == "SILVER"

    def test_missing_required_field(self) -> None:
        """Test error when required field is missing"""
        response = json.dumps({
            "impact_tier": "GOLD",
            "events": [],
        })
        
        with pytest.raises(ExtractionParseError, match="impact_score"):
            parse_extraction_response(response)

    def test_invalid_json(self) -> None:
        """Test error for invalid JSON"""
        response = "This is not JSON at all"
        
        with pytest.raises(ExtractionParseError, match="Invalid JSON"):
            parse_extraction_response(response)

    def test_impact_score_clamping(self) -> None:
        """Test impact score is clamped to 0-100"""
        response = json.dumps({
            "impact_score": 150,  # Over 100
            "impact_tier": "PLATINUM",
            "events": [],
            "instruments": [],
        })
        
        result = parse_extraction_response(response)
        assert result.impact_score == 100

    def test_negative_impact_score_clamping(self) -> None:
        """Test negative impact score is clamped"""
        response = json.dumps({
            "impact_score": -10,
            "impact_tier": "STANDARD",
            "events": [],
            "instruments": [],
        })
        
        result = parse_extraction_response(response)
        assert result.impact_score == 0

    def test_invalid_tier_defaults(self) -> None:
        """Test invalid tier defaults to STANDARD"""
        response = json.dumps({
            "impact_score": 50,
            "impact_tier": "DIAMOND",  # Invalid tier
            "events": [],
            "instruments": [],
        })
        
        result = parse_extraction_response(response)
        assert result.impact_tier == "STANDARD"

    def test_ticker_uppercased(self) -> None:
        """Test ticker symbols are uppercased"""
        response = json.dumps({
            "impact_score": 60,
            "impact_tier": "SILVER",
            "events": [],
            "instruments": [
                {"ticker": "aapl", "direction": "up"}
            ],
        })
        
        result = parse_extraction_response(response)
        assert result.instruments[0].ticker == "AAPL"
        assert result.instruments[0].direction == "UP"

    def test_summary_truncation(self) -> None:
        """Test long summary is truncated"""
        long_summary = "x" * 500
        response = json.dumps({
            "impact_score": 50,
            "impact_tier": "SILVER",
            "events": [],
            "instruments": [],
            "summary": long_summary,
        })
        
        result = parse_extraction_response(response)
        assert len(result.summary) == 200

    def test_raw_response_stored(self) -> None:
        """Test raw response is stored"""
        response = json.dumps({
            "impact_score": 50,
            "impact_tier": "SILVER",
        })
        
        result = parse_extraction_response(response)
        assert result.raw_response == response


# ============================================================================
# Default Result Tests
# ============================================================================


class TestCreateDefaultResult:
    """Tests for create_default_result function"""

    def test_default_result(self) -> None:
        """Test creating default result"""
        result = create_default_result()
        
        assert result.impact_score == 25
        assert result.impact_tier == "STANDARD"
        assert len(result.events) == 1
        assert result.events[0].event_type == "OTHER"
        assert result.events[0].confidence == 0.0
        assert result.instruments == []
        assert result.companies == []


# ============================================================================
# System Prompt Tests
# ============================================================================


class TestSystemPrompt:
    """Tests for the system prompt content"""

    def test_prompt_contains_instructions(self) -> None:
        """Test system prompt has required sections"""
        assert "Impact Assessment" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "Event Detection" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "Instrument Extraction" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "PLATINUM" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "GOLD" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "EARNINGS_BEAT" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "M&A_ANNOUNCE" in GRAPH_EXTRACTION_SYSTEM_PROMPT

    def test_prompt_has_json_format(self) -> None:
        """Test system prompt includes JSON format example"""
        assert '"impact_score"' in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert '"impact_tier"' in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert '"events"' in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert '"instruments"' in GRAPH_EXTRACTION_SYSTEM_PROMPT

    def test_prompt_has_themes_section(self) -> None:
        """Test system prompt includes thematic tagging instructions"""
        assert "Thematic Tagging" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert '"themes"' in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "semiconductor" in GRAPH_EXTRACTION_SYSTEM_PROMPT
        assert "ai" in GRAPH_EXTRACTION_SYSTEM_PROMPT


# ============================================================================
# Step 1 — Themes extraction tests (Client Avatar transformation)
# ============================================================================


class TestThemesExtraction:
    """Tests for themes[] field on GraphExtractionResult.

    Validates:
    - themes round-trips through to_dict()
    - parse_extraction_response picks up themes from JSON
    - backward-compat: old JSON without 'themes' key still parses (defaults [])
    - vocabulary normalization: spaces→underscores, lowercased, stripped
    """

    def test_themes_default_empty(self) -> None:
        """GraphExtractionResult defaults themes to empty list."""
        result = GraphExtractionResult(impact_score=50, impact_tier="SILVER")
        assert result.themes == []

    def test_themes_to_dict_roundtrip(self) -> None:
        """themes survives to_dict() serialization."""
        result = GraphExtractionResult(
            impact_score=60,
            impact_tier="SILVER",
            themes=["semiconductor", "supply_chain", "japan"],
        )
        d = result.to_dict()
        assert d["themes"] == ["semiconductor", "supply_chain", "japan"]

    def test_parse_response_with_themes(self) -> None:
        """parse_extraction_response extracts themes from JSON."""
        response = json.dumps({
            "impact_score": 70,
            "impact_tier": "GOLD",
            "events": [],
            "instruments": [],
            "companies": [],
            "themes": ["ai", "semiconductor", "china"],
            "summary": "TSMC AI chip demand surges",
        })
        result = parse_extraction_response(response)
        assert result.themes == ["ai", "semiconductor", "china"]

    def test_parse_response_without_themes_backward_compat(self) -> None:
        """Old JSON responses without 'themes' key still parse with themes=[]."""
        response = json.dumps({
            "impact_score": 50,
            "impact_tier": "SILVER",
            "events": [],
            "instruments": [],
            "companies": ["Apple Inc."],
            "summary": "Apple minor update",
        })
        result = parse_extraction_response(response)
        assert result.themes == []

    def test_parse_response_themes_normalized(self) -> None:
        """Themes are lowercased, stripped, and spaces become underscores."""
        response = json.dumps({
            "impact_score": 60,
            "impact_tier": "SILVER",
            "events": [],
            "instruments": [],
            "themes": ["AI", "  Supply Chain  ", "EV Battery", ""],
            "summary": "test",
        })
        result = parse_extraction_response(response)
        assert "ai" in result.themes
        assert "supply_chain" in result.themes
        assert "ev_battery" in result.themes
        # Empty strings are filtered out
        assert "" not in result.themes
        assert len(result.themes) == 3

    def test_parse_response_themes_non_string_filtered(self) -> None:
        """Non-string values in themes array are silently dropped."""
        response = json.dumps({
            "impact_score": 50,
            "impact_tier": "SILVER",
            "themes": ["ai", 42, None, True, "semiconductor"],
        })
        result = parse_extraction_response(response)
        assert result.themes == ["ai", "semiconductor"]
