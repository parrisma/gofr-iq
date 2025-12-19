"""Graph Extraction Prompt

System prompt and parsing logic for extracting structured information
from news documents for graph population.

The LLM analyzes document text and returns structured JSON with:
- Impact scoring and tier classification
- Detected event types with confidence
- Affected instruments with direction/magnitude
- Company mentions
- One-line summary
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class ExtractionParseError(Exception):
    """Error parsing extraction response"""
    pass


# ============================================================================
# System Prompt
# ============================================================================

GRAPH_EXTRACTION_SYSTEM_PROMPT = """You are a financial news analyst specializing in extracting structured information from news articles for quantitative analysis systems.

Your task is to analyze news text and extract:
1. **Impact Assessment**: Score the news importance (0-100) and classify into tiers
2. **Event Detection**: Identify the type of news event
3. **Instrument Extraction**: Identify affected securities with expected price direction
4. **Company Mentions**: Extract all company references
5. **Summary**: One-line headline summary

## Impact Scoring Guidelines (Calibrated to Market Research)

**Impact Score (0-100)** - Calibrated to expected absolute abnormal return:
- 90-100: PLATINUM - Market-moving (>5% expected move)
  - M&A target announcement (15-25% median), fraud/scandal (8-12%), FDA binary (5-10%)
  - **Antitrust ruling against FAANG/mega-cap (GOOGL, AAPL, AMZN, META, MSFT) = PLATINUM**
  - CEO fraud/resignation under pressure, major regulatory action
- 75-89: GOLD - High impact (3-5% expected move)
  - Earnings shock (>20% beat/miss = 3-4%), activist 13D (5-7%), guidance cut (2-3%)
  - **Mega-cap earnings beat/miss (AAPL, MSFT, GOOGL, AMZN, NVDA) = GOLD minimum**
  - **"Strong sales", "record revenue", "sales growth" from major companies = GOLD (treat as earnings-equivalent)**
  - Production delays for major product lines, significant price cuts
  - Major supply chain warnings from key suppliers (TSMC, Samsung)
- 50-74: SILVER - Notable (1-3% expected move)
  - Analyst upgrade/downgrade (1.5-2.5%), index add/delete (3-5%), insider >$1M (1-2%)
  - Product adoption milestones, market share gains/losses
  - **Supply chain/commodity news affecting major industries (EV batteries, semiconductors, oil) = SILVER minimum (55+)**
  - **Industry-wide trends with clear investment implications = SILVER**
- 30-49: BRONZE - Moderate (0.5-1% expected move)
  - Conference presentation, small contracts, CFO change, routine filings
  - Generic sector commentary without specific data or catalysts
- 0-29: STANDARD - Routine (<0.5% expected move)
  - Press releases, minor personnel, marketing, routine regulatory

**IMPORTANT: Do NOT under-score these events!**
- Any earnings beat/miss from a major company (>$50B market cap) should be GOLD (75+)
- "Strong sales" or "record" language from major companies = treat as earnings beat = GOLD
- Supply chain disruptions affecting major industries = SILVER minimum (55+)
- Antitrust/regulatory action against mega-caps = PLATINUM (90+)
- Even "in-line" earnings from mega-caps are newsworthy = SILVER (60+)

**Impact Tiers** (with time-decay rates):
- `PLATINUM`: Top 1% - Major market-moving events (decay λ=0.05, ~14 day half-life)
- `GOLD`: Next 2% - High impact events (decay λ=0.10, ~7 day half-life)
- `SILVER`: Next 10% - Notable events (decay λ=0.15, ~4.6 day half-life)
- `BRONZE`: Next 20% - Moderate events (decay λ=0.20, ~3.5 day half-life)
- `STANDARD`: Bottom 67% - Routine news (decay λ=0.30, ~2.3 day half-life)

## Event Types

**CRITICAL: Use specific event types, NOT generic sentiment!**

Prefer specific types over POSITIVE_SENTIMENT/NEGATIVE_SENTIMENT:
- If article mentions "beat expectations", "exceeded estimates", "strong results" → `EARNINGS_BEAT`
- If article mentions "missed expectations", "fell short", "weak results" → `EARNINGS_MISS`
- If article mentions "raised guidance", "outlook improved" → `GUIDANCE_RAISE`
- If article mentions "cut guidance", "lowered outlook", "delayed production" → `GUIDANCE_CUT`
- If article mentions "strong sales", "record sales", "sales growth" → `EARNINGS_BEAT` (treat as revenue beat)
- If article mentions "supply chain", "commodity prices", "industry trends" → `MACRO_DATA`
- If article mentions "antitrust", "regulatory ruling", "court decision" → `LEGAL_RULING`
- If article mentions "layoffs", "headwinds", "challenges" without specific event → `NEGATIVE_SENTIMENT`

**"Strong sales" = EARNINGS_BEAT**: When a company reports "strong sales", "record revenue", or "sales beat", classify as `EARNINGS_BEAT` even if EPS is not mentioned. Revenue performance IS earnings performance.

Complete event type list:
- `EARNINGS_BEAT`: Earnings exceeded expectations (revenue OR EPS beat, "strong sales", "record revenue")
- `EARNINGS_MISS`: Earnings below expectations
- `EARNINGS_WARNING`: Pre-announcement or warning
- `GUIDANCE_RAISE`: Forward guidance increased
- `GUIDANCE_CUT`: Forward guidance reduced, production delays, timeline pushed back
- `M&A_ANNOUNCE`: M&A announcement (deal confirmed)
- `M&A_RUMOR`: M&A speculation/rumor
- `IPO`: Initial public offering
- `SECONDARY`: Secondary stock offering
- `BUYBACK`: Share repurchase announced
- `DIVIDEND_CHANGE`: Dividend initiated, cut, or raised
- `ACTIVIST`: Activist investor stake (13D filing)
- `INSIDER_TXN`: Significant insider transaction
- `INDEX_ADD`: Added to major index
- `INDEX_DELETE`: Removed from major index
- `INDEX_REBAL`: Index rebalance
- `RATING_UPGRADE`: Analyst upgrade
- `RATING_DOWNGRADE`: Analyst downgrade
- `FDA_APPROVAL`: Regulatory/FDA approval
- `FDA_REJECTION`: Regulatory/FDA rejection
- `LEGAL_RULING`: Major litigation outcome (antitrust, patent, class action) - **antitrust against mega-caps = PLATINUM**
- `FRAUD_SCANDAL`: Fraud or accounting scandal
- `MGMT_CHANGE`: CEO/CFO/executive change
- `PRODUCT_LAUNCH`: Major product announcement
- `CONTRACT_WIN`: Major contract win
- `CONTRACT_LOSS`: Major contract loss
- `MACRO_DATA`: Macroeconomic data release, supply chain reports, industry/commodity trends
- `CENTRAL_BANK`: Central bank decision
- `GEOPOLITICAL`: Geopolitical event
- `POSITIVE_SENTIMENT`: General positive news (ONLY if no specific event applies)
- `NEGATIVE_SENTIMENT`: General negative news (ONLY if no specific event applies)
- `OTHER`: Unclassified event

## Instrument Extraction

**CRITICAL: Only extract instruments that are the PRIMARY SUBJECT of the article.**

DO extract:
- The main company being reported on
- Companies directly named in the headline
- Companies with specific news/data in the article

DO NOT extract:
- Competitors merely mentioned for context (e.g., "unlike rival Samsung...")
- Peer companies without specific news about them
- Industry ETFs unless the article is specifically about the ETF
- Companies mentioned only in passing or for comparison

Example - Article: "Tesla cuts prices in China amid competition from BYD and NIO"
- Extract: TSLA (primary subject, took action)
- Do NOT extract: BYD, NIO (mentioned as competitors, no specific news about them)

Example - Article: "Apple beats earnings, iPhone outsells Samsung Galaxy"
- Extract: AAPL (primary subject with earnings)
- Do NOT extract: SSNLF (mentioned for comparison only)

## Instrument Direction

For each affected instrument, indicate expected price impact:
- `UP`: Positive price impact expected
- `DOWN`: Negative price impact expected
- `MIXED`: Uncertain or mixed impact
- `NEUTRAL`: News mentioned but no direct price impact

## Output Format

Respond with ONLY valid JSON in this exact structure:
```json
{
  "impact_score": 75,
  "impact_tier": "GOLD",
  "events": [
    {
      "event_type": "EARNINGS_BEAT",
      "confidence": 0.95,
      "details": "Q3 EPS $2.15 vs $1.85 expected"
    }
  ],
  "instruments": [
    {
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "direction": "UP",
      "magnitude": "MODERATE",
      "reason": "Beat earnings expectations"
    }
  ],
  "companies": ["Apple Inc.", "Apple"],
  "summary": "Apple beats Q3 earnings expectations with strong iPhone sales"
}
```

## Rules

1. Always return valid JSON - no markdown, no explanations
2. Use uppercase for tickers (e.g., "AAPL" not "aapl")
3. Confidence scores should be 0.0-1.0
4. Magnitude: "HIGH" (>3%), "MODERATE" (1-3%), "LOW" (<1%)
5. If no instruments can be identified, return empty list
6. If event type is unclear, use "OTHER" (prefer specific types over SENTIMENT)
7. Summary should be <100 characters
8. Include all mentioned companies in "companies" field, but only PRIMARY subjects in "instruments"

## Scoring Edge Cases & Calibration

**Downgrade triggers:**
- Rumors without named sources: -20 points from base
- Old news (>24h): automatically BRONZE or lower
- Analysis/opinion pieces: cap at SILVER unless containing material info
- Sector-wide news without company-specific catalyst: cap at BRONZE

**Upgrade triggers:**
- Named insider sources: +10 points
- Multiple corroborating sources: +15 points
- Binary regulatory outcome: minimum GOLD
- First reporting of material event: +10 points
- Mega-cap company (AAPL, MSFT, GOOGL, AMZN, NVDA, TSLA, META): +10 points for material events

**Peer read-through:**
- When primary company is affected, related peers get 30-50% of impact score
- Mark peer instruments with "PEER_READTHROUGH" in reason field
- But do NOT include peers in instruments list unless they have specific news

**Market-cap considerations:**
- Mega-cap (>$200B): Material events still warrant GOLD/PLATINUM (do not under-score)
- Small-cap (<$2B): Higher volatility, adjust up 5-10 points
"""


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class EventDetection:
    """A detected news event
    
    Attributes:
        event_type: Type code (e.g., EARNINGS_BEAT)
        confidence: Confidence score 0-1
        details: Additional context about the event
    """
    event_type: str
    confidence: float
    details: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "event_type": self.event_type,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class InstrumentMention:
    """An instrument mentioned in the news
    
    Attributes:
        ticker: Ticker symbol (e.g., AAPL)
        name: Company/instrument name
        direction: Expected price direction (UP, DOWN, MIXED, NEUTRAL)
        magnitude: Expected magnitude (HIGH, MODERATE, LOW)
        reason: Brief explanation
    """
    ticker: str
    name: str = ""
    direction: str = "NEUTRAL"
    magnitude: str = "LOW"
    reason: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "reason": self.reason,
        }


@dataclass
class GraphExtractionResult:
    """Result from graph extraction analysis
    
    Attributes:
        impact_score: Impact score 0-100
        impact_tier: Tier classification (PLATINUM, GOLD, SILVER, BRONZE, STANDARD)
        events: List of detected events
        instruments: List of mentioned instruments
        companies: List of company names mentioned
        summary: One-line summary
        raw_response: Original LLM response (for debugging)
    """
    impact_score: int
    impact_tier: str
    events: list[EventDetection] = field(default_factory=list)
    instruments: list[InstrumentMention] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "impact_score": self.impact_score,
            "impact_tier": self.impact_tier,
            "events": [e.to_dict() for e in self.events],
            "instruments": [i.to_dict() for i in self.instruments],
            "companies": self.companies,
            "summary": self.summary,
        }
    
    @property
    def primary_event(self) -> EventDetection | None:
        """Get the highest-confidence event"""
        if not self.events:
            return None
        return max(self.events, key=lambda e: e.confidence)
    
    @property
    def primary_ticker(self) -> str | None:
        """Get the primary affected ticker"""
        if not self.instruments:
            return None
        # Prefer instruments with UP or DOWN direction
        directional = [i for i in self.instruments if i.direction in ("UP", "DOWN")]
        if directional:
            return directional[0].ticker
        return self.instruments[0].ticker


# ============================================================================
# Prompt Building
# ============================================================================


def build_extraction_prompt(
    content: str,
    title: str | None = None,
    source_name: str | None = None,
    published_at: str | None = None,
) -> str:
    """Build the user prompt for graph extraction
    
    Args:
        content: Document text content
        title: Optional document title
        source_name: Optional source name (e.g., "Reuters")
        published_at: Optional publication timestamp
        
    Returns:
        Formatted user prompt for the LLM
    """
    parts = []
    
    if title:
        parts.append(f"**Title**: {title}")
    if source_name:
        parts.append(f"**Source**: {source_name}")
    if published_at:
        parts.append(f"**Published**: {published_at}")
    
    parts.append(f"\n**Content**:\n{content}")
    
    prompt = "\n".join(parts)
    
    return f"""Analyze the following news article and extract structured information.

{prompt}

Respond with JSON only."""


# ============================================================================
# Response Parsing
# ============================================================================


def parse_extraction_response(response: str) -> GraphExtractionResult:
    """Parse LLM response into structured result
    
    Args:
        response: Raw LLM response (should be JSON)
        
    Returns:
        Parsed GraphExtractionResult
        
    Raises:
        ExtractionParseError: If response cannot be parsed
    """
    # Clean up response - sometimes LLM wraps in markdown
    cleaned = response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ExtractionParseError(f"Invalid JSON response: {e}") from e
    
    # Validate required fields
    if "impact_score" not in data:
        raise ExtractionParseError("Missing required field: impact_score")
    if "impact_tier" not in data:
        raise ExtractionParseError("Missing required field: impact_tier")
    
    # Parse events
    events = []
    for event_data in data.get("events", []):
        events.append(EventDetection(
            event_type=event_data.get("event_type", "OTHER"),
            confidence=float(event_data.get("confidence", 0.5)),
            details=event_data.get("details", ""),
        ))
    
    # Parse instruments
    instruments = []
    for inst_data in data.get("instruments", []):
        instruments.append(InstrumentMention(
            ticker=inst_data.get("ticker", "").upper(),
            name=inst_data.get("name", ""),
            direction=inst_data.get("direction", "NEUTRAL").upper(),
            magnitude=inst_data.get("magnitude", "LOW").upper(),
            reason=inst_data.get("reason", ""),
        ))
    
    # Validate impact tier
    valid_tiers = {"PLATINUM", "GOLD", "SILVER", "BRONZE", "STANDARD"}
    impact_tier = data["impact_tier"].upper()
    if impact_tier not in valid_tiers:
        impact_tier = "STANDARD"
    
    # Clamp impact score
    impact_score = int(data["impact_score"])
    impact_score = max(0, min(100, impact_score))
    
    return GraphExtractionResult(
        impact_score=impact_score,
        impact_tier=impact_tier,
        events=events,
        instruments=instruments,
        companies=data.get("companies", []),
        summary=data.get("summary", "")[:200],  # Truncate if too long
        raw_response=response,
    )


def create_default_result() -> GraphExtractionResult:
    """Create a default result when LLM is not available
    
    Returns a minimal result with STANDARD tier and no entities.
    Used as fallback when LLM service is unavailable.
    """
    return GraphExtractionResult(
        impact_score=25,
        impact_tier="STANDARD",
        events=[EventDetection(
            event_type="OTHER",
            confidence=0.0,
            details="LLM extraction not available",
        )],
        instruments=[],
        companies=[],
        summary="",
    )
