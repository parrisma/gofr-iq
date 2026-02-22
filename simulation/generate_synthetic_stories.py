#!/usr/bin/env python3
"""
Synthetic Story Generator for GOFR-IQ

Generates synthetic news stories to stress-test graph extraction logic.
Follows the specification in simulation/synthetic_data_proposal.md.

Usage:
    python simulation/generate_synthetic_stories.py --count 10 --output data/synthetic
"""

import os
import sys
import json
import random
import time
import argparse
import logging
import concurrent.futures
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# Add workspace to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Try to import dependencies
try:
    import httpx
except ImportError:
    logger.error("Missing dependencies. Please run: pip install httpx")
    sys.exit(1)

# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_MODEL = "meta-llama/llama-3.1-70b-instruct"
MAX_RETRIES = 3
TIMEOUT = 60.0


@dataclass
class MockTicker:
    ticker: str
    name: str
    sector: str
    persona: str


@dataclass
class ValidationRule:
    min_score: int = 0
    max_score: int = 100
    expected_tier: str = "STANDARD"
    must_match_event: bool = False
    expected_event: Optional[str] = None
    expected_entities: List[str] = field(default_factory=list)
    expected_relevant_clients: List[str] = field(default_factory=list)  # Client GUIDs
    relationship_hops: int = 0  # 0=direct, 1=supplier/customer, 2=competitor
    expected_feed_rank_range: str = "1-50"  # e.g., "1-5", "6-15", "16+"


@dataclass
class Scenario:
    name: str
    description: str
    target_tier: str
    template: str
    validation: ValidationRule
    weight: float  # Selection probability weight


@dataclass
class MockSource:
    guid: str
    name: str
    trust_level: int
    persona: str
    style_guide: str


# Source Registry with varying trust levels
MOCK_SOURCES = [
    MockSource(
        guid="src-global-wire",
        name="Global Wire",
        trust_level=10,
        persona="dry_factual",
        style_guide="Dry, extremely factual, immediate. Uses formal identifiers (Full Company Name, exact Timestamps). No emotional language.",
    ),
    MockSource(
        guid="src-market-blog",
        name="The Daily Alpha",
        trust_level=4,
        persona="opinionated",
        style_guide="Opinionated, uses trading slang ('to the moon', 'bagholder'). Focuses on stock price action and speculation.",
    ),
    MockSource(
        guid="src-rumor-mill",
        name="Insider Whispers",
        trust_level=2,
        persona="speculative",
        style_guide="Vague ('sources say', 'unconfirmed reports'), volatile, sensationalist. Use capitalized words for emphasis. Explicitly unconfirmed.",
    ),
    MockSource(
        guid="src-local-gazette",
        name="Regional Business Journal",
        trust_level=8,
        persona="local_context",
        style_guide="Hyper-specific local context. Mentions city names, employee counts, local politics. Slower, more narrative pace.",
    ),
    MockSource(
        guid="src-tech-cruncher",
        name="Silicon Circuits",
        trust_level=6,
        persona="tech_focused",
        style_guide="Deeply technical, focused on specs, benchmarks, and engineering details. Jargon heavy.",
    ),
]

# ============================================================================
# Data Definitions
# ============================================================================

from simulation.universe.builder import UniverseBuilder, DEFAULT_GROUP  # noqa: E402 - imports after config setup

# Initialize the universe builder to access the shared topology
UNIVERSE = UniverseBuilder()

# Client portfolio mappings for validation metadata
CLIENT_PORTFOLIOS = {
    "550e8400-e29b-41d4-a716-446655440001": [
        "QNTM",
        "BANKO",
        "VIT",
        "GTX",
        "NXS",
    ],  # Quantum Momentum Partners (Hedge Fund)
    "550e8400-e29b-41d4-a716-446655440002": [
        "OMNI",
        "SHOPM",
        "TRUCK",
    ],  # Nebula Retirement Fund (Pension)
    "550e8400-e29b-41d4-a716-446655440003": [
        "VELO",
        "BLK",
    ],  # DiamondHands420 (Retail)
    "550e8400-e29b-41d4-a716-446655440004": [
        "ECO",
        "STR",
        "SHOPM",
    ],  # Green Horizon Capital (ESG)
    "550e8400-e29b-41d4-a716-446655440005": [
        "QNTM",
        "SHOPM",
        "GTX",
    ],  # Sunrise Long Opportunities (Long Bias)
    "550e8400-e29b-41d4-a716-446655440006": [
        "BANKO",
        "OMNI",
        "TRUCK",
    ],  # Ironclad Short Strategies (Short Bias)
    "550e8400-e29b-41d4-a716-446655440007": [
        "GENE",
        "VIT",
    ],  # Genomics Partners
    "550e8400-e29b-41d4-a716-446655440008": [
        "PROP",
        "BANKO",
    ],  # Macro Rates Fund
    "550e8400-e29b-41d4-a716-446655440009": [
        "FIN",
        "BLK",
    ],  # Crypto Ventures
}

CLIENT_WATCHLISTS = {
    "550e8400-e29b-41d4-a716-446655440001": ["NXS", "FIN"],
    "550e8400-e29b-41d4-a716-446655440002": ["ECO", "STR"],
    "550e8400-e29b-41d4-a716-446655440003": ["QNTM", "LUXE"],
    "550e8400-e29b-41d4-a716-446655440004": ["OMNI", "TRUCK"],
    "550e8400-e29b-41d4-a716-446655440005": ["VIT", "ECO"],
    "550e8400-e29b-41d4-a716-446655440006": ["FIN", "STR"],
    "550e8400-e29b-41d4-a716-446655440007": ["QNTM", "GTX"],
    "550e8400-e29b-41d4-a716-446655440008": ["OMNI", "TRUCK"],
    "550e8400-e29b-41d4-a716-446655440009": ["BANKO", "QNTM"],
}

SCENARIOS = [
    Scenario(
        name="Platinum Regulator",
        description="Antitrust ruling against mega-cap",
        target_tier="PLATINUM",
        weight=0.01,
        template="News Event: Antitrust Ruling. Subject: {ticker} ({name}). Context: DOJ/EU ruling. Style Guide: {style_guide}. \nTask: Write a news story following the style guide. A major ruling has been issued potentially forcing a breakup or fine. Use appropriate tone for the source.",
        validation=ValidationRule(
            min_score=90,
            expected_tier="PLATINUM",
            expected_event="LEGAL_RULING",
            must_match_event=True,
        ),
    ),
    Scenario(
        name="Semantic Earnings Beat",
        description="Strong sales/revenue without saying EPS",
        target_tier="GOLD",
        weight=0.04,
        template="News Event: Earnings Report. Subject: {ticker} ({name}). Style Guide: {style_guide}. \nTask: Write about financial results. DO NOT use words 'earnings per share', 'EPS', or 'profit'. Focus on 'revenue', 'sales', 'growth'. Tone: Bullish. Adhere to the source persona.",
        validation=ValidationRule(
            min_score=75,
            expected_tier="GOLD",
            expected_event="EARNINGS_BEAT",
            must_match_event=True,
        ),
    ),
    Scenario(
        name="Supply Chain Ripple",
        description="Supply chain news affecting industry",
        target_tier="SILVER",
        weight=0.10,
        template="News Event: Supply Chain Disruption. Subject: {sector}. Affected: {ticker} ({name}). Style Guide: {style_guide}. \nTask: Write about industry-wide shortages affecting {ticker}. Frame it as a sector issue.",
        validation=ValidationRule(
            min_score=50, max_score=74, expected_tier="SILVER", expected_event="MACRO_DATA"
        ),
    ),
    Scenario(
        name="Rumor Penalty",
        description="M&A rumor with unnamed sources",
        target_tier="BRONZE",  # Should be downgraded from higher
        weight=0.10,
        template="News Event: M&A Rumor. Subject: {ticker} ({name}). Style Guide: {style_guide}. \nTask: Write about a rumored acquisition. Attribute to 'people familiar'. Explicitly unconfirmed. If the source is low trust, make it very speculative. If high trust, strictly cite 'rumors'.",
        validation=ValidationRule(max_score=74, expected_event="M&A_RUMOR"),
    ),
    Scenario(
        name="Indirect Supplier Delay",
        description="News about a supplier affecting the main company",
        target_tier="GOLD",
        weight=0.08,
        template="News Event: Supplier Delay. Primary Subject: {related_ticker} ({related_name}). Impacted: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write a story about a failure at {related_name} that will specifically hurt {name} because of their relationship ({relationship_desc}). The headline should focus on the Supplier.",
        validation=ValidationRule(
            expected_tier="GOLD", expected_event="SUPPLY_CHAIN", relationship_hops=1
        ),
    ),
    Scenario(
        name="Competitor Product Launch",
        description="Rival launches a better product",
        target_tier="SILVER",
        weight=0.08,
        template="News Event: Competitor Product Launch. Subject: {related_ticker} ({related_name}). Threat to: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write a story about {related_name} launching a product that makes {name}'s flagship look obsolete. Focus on the competitive threat.",
        validation=ValidationRule(
            expected_tier="SILVER", expected_event="PRODUCT_LAUNCH", relationship_hops=2
        ),
    ),
    Scenario(
        name="Standard Filler",
        description="Routine corporate news",
        target_tier="STANDARD",
        weight=0.20,
        template="News Event: Routine Update. Subject: {ticker} ({name}). Style Guide: {style_guide}. \nTask: Write a routine update (personnel, marketing, ESG). content should be low impact.",
        validation=ValidationRule(
            max_score=49, expected_tier="STANDARD", expected_event="OTHER", relationship_hops=0
        ),
    ),
    # === NEW: Macro Factor Scenarios ===
    Scenario(
        name="Interest Rate Impact",
        description="Central bank rate decision affecting rate-sensitive stocks",
        target_tier="GOLD",
        weight=0.08,
        template="News Event: Interest Rate Decision. Context: Federal Reserve raises/cuts rates by 25-50 bps. Focus: {ticker} ({name}). Exposure: {factor_exposure_desc}. Beta: {factor_beta}. Style Guide: {style_guide}. \nTask: Write about the rate decision and its SPECIFIC impact on {name} based on their exposure ({factor_exposure_desc}). If beta is positive, rates help them. If negative, rates hurt them.",
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="MACRO_DATA",
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Commodity Price Shock",
        description="Oil/commodity price spike affecting exposed companies",
        target_tier="SILVER",
        weight=0.05,
        template="News Event: Commodity Price Surge. Context: Oil/lithium/steel prices spike 20%. Focus: {ticker} ({name}). Exposure: {factor_exposure_desc}. Beta: {factor_beta}. Style Guide: {style_guide}. \nTask: Write about commodity price movement and SPECIFIC impact on {name}. Negative beta means higher costs hurt margins. Positive beta means they benefit.",
        validation=ValidationRule(
            min_score=50,
            max_score=74,
            expected_tier="SILVER",
            expected_event="MACRO_DATA",
            relationship_hops=0,
            expected_feed_rank_range="6-15",
        ),
    ),
    Scenario(
        name="Regulatory Event",
        description="New regulation affecting specific sectors",
        target_tier="GOLD",
        weight=0.05,
        template="News Event: Regulatory Announcement. Context: {regulation_context}. Focus: {ticker} ({name}). Exposure: {factor_exposure_desc}. Beta: {factor_beta}. Style Guide: {style_guide}. \nTask: Write about the new regulation and its SPECIFIC impact on {name}. Positive beta means regulations help them (subsidies/approvals). Negative beta means increased compliance costs or restrictions.",
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="LEGAL_RULING",
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="China Economic Data",
        description="China GDP/policy affecting exposed multinationals",
        target_tier="SILVER",
        weight=0.04,
        template="News Event: China Economic Report. Context: China GDP growth slows/accelerates. Focus: {ticker} ({name}). Exposure: {factor_exposure_desc}. Beta: {factor_beta}. Style Guide: {style_guide}. \nTask: Write about China economic data and SPECIFIC impact on {name}. Higher beta means more revenue exposure to China. Frame as opportunity or risk.",
        validation=ValidationRule(
            min_score=50,
            max_score=74,
            expected_tier="SILVER",
            expected_event="MACRO_DATA",
            relationship_hops=0,
            expected_feed_rank_range="6-15",
        ),
    ),
    # === NEW: Enhanced Supply Chain & Competitor Scenarios ===
    Scenario(
        name="Supply Chain Fire",
        description="Factory fire at supplier creates 2-hop supply shock",
        target_tier="GOLD",
        weight=0.08,
        template="News Event: Supplier Catastrophe. Primary: {related_ticker} ({related_name}) has major factory fire/shutdown. Downstream Impact: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write about the fire at {related_name}. Then explain how this will SPECIFICALLY hurt {name} in 2-4 weeks because {relationship_desc}. Focus headline on the supplier, but mention downstream impact.",
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="SUPPLY_CHAIN",
            relationship_hops=1,
            expected_feed_rank_range="6-15",
        ),
    ),
    Scenario(
        name="Competitor Product Recall",
        description="Rival's product recall creates Schadenfreude opportunity",
        target_tier="SILVER",
        weight=0.08,
        template="News Event: Product Recall. Subject: {related_ticker} ({related_name}) recalls flagship product. Beneficiary: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write about {related_name}'s embarrassing product recall/failure. Mention that {name}, their direct competitor, stands to gain market share. Frame as {related_name}'s problem but {name}'s opportunity.",
        validation=ValidationRule(
            min_score=50,
            max_score=74,
            expected_tier="SILVER",
            expected_event="PRODUCT_RECALL",
            relationship_hops=2,
            expected_feed_rank_range="6-15",
        ),
    ),

    # =====================================================================
    # Phase 3 Stress-Test Scenarios (Sunshine & Rain)
    # =====================================================================
    Scenario(
        name="Phase3 A Defense Tail Holding Failure",
        description="Massive failure in a small (0.5%) tail holding",
        target_tier="PLATINUM",
        weight=0.02,
        template=(
            "News Event: Operational Failure / Catastrophe. Subject: {ticker} ({name}). "
            "Context: This is a small tail holding (~0.5% weight) but the downside risk is severe. "
            "Style Guide: {style_guide}.\n"
            "Task: Write a breaking news story about a catastrophic operational failure (fraud, product failure, regulatory stop) "
            "that could plausibly be existential for the company. Be specific and urgent."
        ),
        validation=ValidationRule(
            min_score=90,
            expected_tier="PLATINUM",
            expected_event="FRAUD_SCANDAL",
            must_match_event=False,
            # Expanded to include clients reachable via lateral graph hops
            # (e.g., competitors of NXS such as GTX/QNTM) so we can measure
            # hop-based retrieval separately from direct-holding retrieval.
            expected_relevant_clients=[
                "550e8400-e29b-41d4-a716-446655440001",
                "550e8400-e29b-41d4-a716-446655440005",
            ],
            relationship_hops=0,
            expected_feed_rank_range="6-15",
        ),
    ),
    Scenario(
        name="Phase3 B Offense Thematic M&A",
        description="Competitor M&A in a sector matching client mandate (non-holding)",
        target_tier="PLATINUM",
        weight=0.02,
        template=(
            "News Event: Competitor M&A / Strategic Acquisition. Subject: {ticker} ({name}). "
            "Theme: {sector} and mandate-aligned catalysts. Style Guide: {style_guide}.\n"
            "Task: Write a story about a competitor acquisition (or takeover interest) that signals a major thematic shift "
            "in the sector. Make the implications clear for mandate-themed investors, not just holders of the stock."
        ),
        validation=ValidationRule(
            min_score=90,
            expected_tier="PLATINUM",
            expected_event="M_AND_A",
            must_match_event=False,
            # Expanded to include competitor holders (SHOPM) alongside the
            # direct watchlist client (DiamondHands420) to exercise lateral hops.
            expected_relevant_clients=[
                "550e8400-e29b-41d4-a716-446655440003",
                "550e8400-e29b-41d4-a716-446655440002",
                "550e8400-e29b-41d4-a716-446655440004",
                "550e8400-e29b-41d4-a716-446655440005",
            ],
            relationship_hops=0,
            expected_feed_rank_range="1-5",
        ),
    ),
    Scenario(
        name="Phase3 C Systemic Multi-Holding Shock",
        description="Systemic supplier explosion impacting 3 holdings",
        target_tier="PLATINUM",
        weight=0.02,
        template=(
            "News Event: Systemic Supply Shock / Explosion / Shutdown. "
            "Affected holdings: {affected_tickers_csv}. Style Guide: {style_guide}.\n"
            "Task: Write a breaking story about a systemic shock (e.g. major supplier plant explosion or critical component shortage) "
            "that is explicitly impacting ALL of: {affected_tickers_csv}. Make sure each ticker is mentioned clearly in the body."
        ),
        validation=ValidationRule(
            min_score=90,
            expected_tier="PLATINUM",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440001"],
            relationship_hops=1,
            expected_feed_rank_range="1-5",
        ),
    ),
    Scenario(
        name="Phase3 D Noise Generic Sector Chatter",
        description="Generic sector noise that should be suppressed",
        target_tier="STANDARD",
        weight=0.02,
        template=(
            "News Event: Generic Sector Noise. Subject: {sector}. Mention: {ticker} ({name}). "
            "Style Guide: {style_guide}.\n"
            "Task: Write a vague, low-signal sector roundup with no concrete catalyst, no numbers, and no actionable facts. "
            "It should read like noise."
        ),
        validation=ValidationRule(
            max_score=35,
            expected_tier="STANDARD",
            expected_event="OTHER",
            must_match_event=False,
            expected_relevant_clients=[],
            relationship_hops=0,
            expected_feed_rank_range="16+",
        ),
    ),

    # =====================================================================
    # Phase 4 Calibration Scenarios (mandate needles, relationship hops,
    # negative controls).  weight=0.0 -> never randomly selected.
    # =====================================================================

    # --- Group A: Mandate-targeted non-holding needles ---
    Scenario(
        name="Phase4 M1 AI Compute Supply Chain",
        description="AI compute demand creating semiconductor fab bottlenecks (mandate: ai/semiconductor)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: AI Compute Supply Chain. Subject: {ticker} ({name}). "
            "Theme: AI hardware and semiconductor supply chain. Style Guide: {style_guide}.\n"
            "Task: Write a breaking story about surging AI compute demand creating semiconductor "
            "fabrication bottlenecks. {name} has emerged as a key player requiring massive GPU "
            "clusters for AI-driven research. Focus on semiconductor shortage implications and "
            "data-center buildout pressure."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=[
                "550e8400-e29b-41d4-a716-446655440001",
                "550e8400-e29b-41d4-a716-446655440007",
            ],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Phase4 M2 Rates Shock Inflation Print",
        description="Rate hike / inflation print impacting real-asset valuations (mandate: commodities/rates)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Rates Shock / Inflation Print. Subject: {ticker} ({name}). "
            "Theme: Interest rates, inflation, and macro impact. Style Guide: {style_guide}.\n"
            "Task: Write a breaking story about a surprise central bank rate decision or "
            "inflation print directly impacting {name}. Frame around rising rates, yield curve "
            "dynamics, and specific impact on real-asset and commodity-linked valuations."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=[
                "550e8400-e29b-41d4-a716-446655440002",
                "550e8400-e29b-41d4-a716-446655440008",
            ],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Phase4 M3 Crypto Protocol Exploit",
        description="Blockchain protocol exploit / regulatory headline (mandate: blockchain/ev_battery)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Crypto Protocol Exploit / Regulatory. Subject: {ticker} ({name}). "
            "Theme: Blockchain and cryptocurrency. Style Guide: {style_guide}.\n"
            "Task: Write a breaking story about a major crypto protocol exploit or regulatory "
            "crackdown reshaping the blockchain landscape and {name}'s competitive position. "
            "Focus on DeFi security, protocol vulnerabilities, and regulatory response."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="LEGAL_RULING",
            must_match_event=False,
            expected_relevant_clients=[
                "550e8400-e29b-41d4-a716-446655440003",
                "550e8400-e29b-41d4-a716-446655440009",
            ],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Phase4 M4 Energy Transition Policy",
        description="Policy catalyst for energy transition / clean transport (mandate: esg/energy_transition)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Energy Transition Policy Catalyst. Subject: {ticker} ({name}). "
            "Theme: ESG and energy transition policy. Style Guide: {style_guide}.\n"
            "Task: Write a story about a major policy decision (subsidy, carbon tax, or "
            "regulation) driving energy transition. Explain the specific impact on {name}'s "
            "clean energy or sustainable transport strategy. Frame through ESG and climate "
            "policy lenses."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="LEGAL_RULING",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440004"],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Phase4 M5 Cloud Pricing SaaS Shift",
        description="Cloud pricing / SaaS demand shift (mandate: cloud/consumer)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Cloud Pricing / SaaS Demand Shift. Subject: {ticker} ({name}). "
            "Theme: Cloud infrastructure and consumer digital transformation. "
            "Style Guide: {style_guide}.\n"
            "Task: Write a story about a significant cloud pricing shift or SaaS demand wave "
            "impacting {name}'s digital commerce strategy. Focus on cloud adoption, e-commerce "
            "growth, and consumer technology themes."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440005"],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),
    Scenario(
        name="Phase4 M6 Credit Downgrade Geopolitical",
        description="Credit downgrade amid geopolitical risk (mandate: credit/geopolitical)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Credit Downgrade / Geopolitical Shock. Subject: {ticker} ({name}). "
            "Theme: Credit deterioration and geopolitical risk. Style Guide: {style_guide}.\n"
            "Task: Write a story about a credit downgrade or geopolitical event creating "
            "downside risk for {name}. Focus on credit market stress, leverage concerns, and "
            "policy tightening. Frame as a risk catalyst for short-biased strategies."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440006"],
            relationship_hops=0,
            expected_feed_rank_range="1-10",
        ),
    ),

    # --- Group B: Relationship-hop calibration ---
    Scenario(
        name="Phase4 R1 Supplier Disruption 1Hop",
        description="EcoPower battery disruption impacting Velocity Motors (1-hop partner)",
        target_tier="GOLD",
        weight=0.0,
        template=(
            "News Event: Supplier Disruption. Primary Subject: {related_ticker} ({related_name}). "
            "Impacted: {ticker} ({name}). Relationship: {relationship_desc}. "
            "Style Guide: {style_guide}.\n"
            "Task: Write about a critical supply disruption at {related_name} that directly "
            "threatens {name}'s operations because {relationship_desc}. The headline should "
            "focus on {related_name}, but the body must explain the downstream impact on {name}."
        ),
        validation=ValidationRule(
            min_score=70,
            expected_tier="GOLD",
            expected_event="SUPPLY_CHAIN",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440003"],
            relationship_hops=1,
            expected_feed_rank_range="6-15",
        ),
    ),
    Scenario(
        name="Phase4 R2 Competitor Recall 2Hop",
        description="GeneSys product recall benefiting Vitality Pharma (2-hop competitor)",
        target_tier="SILVER",
        weight=0.0,
        template=(
            "News Event: Competitor Product Recall. Subject: {related_ticker} ({related_name}). "
            "Beneficiary: {ticker} ({name}). Relationship: {relationship_desc}. "
            "Style Guide: {style_guide}.\n"
            "Task: Write about {related_name}'s major product recall or clinical trial failure. "
            "Explain how {name}, their direct competitor, stands to gain market share and "
            "investor confidence. Focus on the competitive dynamics."
        ),
        validation=ValidationRule(
            min_score=50,
            max_score=74,
            expected_tier="SILVER",
            expected_event="PRODUCT_RECALL",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440001"],
            relationship_hops=2,
            expected_feed_rank_range="6-15",
        ),
    ),
    Scenario(
        name="Phase4 R3 Systemic Multi-Ticker Shock",
        description="Systemic logistics crisis affecting OMNI, SHOPM, TRUCK (multi-holding)",
        target_tier="PLATINUM",
        weight=0.0,
        template=(
            "News Event: Systemic Supply Chain Crisis. "
            "Affected: {affected_tickers_csv}. Style Guide: {style_guide}.\n"
            "Task: Write about a systemic logistics and supply chain crisis affecting all of: "
            "{affected_tickers_csv}. Mention each ticker explicitly with specific impact "
            "details. Frame as a broad macro shock with cascading consequences."
        ),
        validation=ValidationRule(
            min_score=90,
            expected_tier="PLATINUM",
            expected_event="MACRO_DATA",
            must_match_event=False,
            expected_relevant_clients=["550e8400-e29b-41d4-a716-446655440002"],
            relationship_hops=1,
            expected_feed_rank_range="1-5",
        ),
    ),

    # --- Group C: Negative controls ---
    Scenario(
        name="Phase4 N1 Generic Sector Chatter",
        description="Generic noise that should not rank for any client",
        target_tier="STANDARD",
        weight=0.0,
        template=(
            "News Event: Generic Sector Chatter. Subject: {ticker} ({name}). "
            "Style Guide: {style_guide}.\n"
            "Task: Write a vague, low-signal sector roundup mentioning {name}. No concrete "
            "catalyst, no specific numbers, and no actionable facts. It should read like "
            "background noise."
        ),
        validation=ValidationRule(
            max_score=35,
            expected_tier="STANDARD",
            expected_event="OTHER",
            must_match_event=False,
            expected_relevant_clients=[],
            relationship_hops=0,
            expected_feed_rank_range="16+",
        ),
    ),
    Scenario(
        name="Phase4 N2 Wrong Theme Strong Headline",
        description="Strong headline with off-mandate theme (false positive guard)",
        target_tier="SILVER",
        weight=0.0,
        template=(
            "News Event: Agricultural Policy Impact. Subject: {ticker} ({name}). "
            "Style Guide: {style_guide}.\n"
            "Task: Write a strong, attention-grabbing headline and story about agricultural "
            "subsidies, crop yields, and farming policy changes. Mention {name} only briefly "
            "in passing context. The story must be primarily about agriculture and food "
            "production, not matching any financial technology, energy, blockchain, or "
            "defense themes."
        ),
        validation=ValidationRule(
            max_score=49,
            expected_tier="STANDARD",
            expected_event="OTHER",
            must_match_event=False,
            expected_relevant_clients=[],
            relationship_hops=0,
            expected_feed_rank_range="16+",
        ),
    ),
]

# ============================================================================
# Generator Class
# ============================================================================


class SyntheticGenerator:
    def __init__(self, env_path: Optional[str] = None, model: Optional[str] = None):
        # Load config first (for tokens/sources)
        self._load_config(env_path)

        # Model: explicit arg > env var > default
        self.model = model or os.environ.get("GOFR_IQ_LLM_MODEL", DEFAULT_MODEL)
        logger.info(f"Using LLM model: {self.model}")

        # API key should already be in environment (from production config)
        self.api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOFR_IQ_OPENROUTER_API_KEY not set. "
                "Run simulation via: ./simulation/run_simulation.sh"
            )

        logger.info("Loaded OpenRouter API key from environment (redacted)")

        self.client = httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/gofr/gofr-iq",
                "X-Title": "Gofr-IQ Synthetic Generator",
            },
            timeout=TIMEOUT,
        )

    def _create_client(self):
        """Create a dedicated client (safe for use from a worker thread)."""
        import httpx

        return httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/gofr/gofr-iq",
                "X-Title": "Gofr-IQ Synthetic Generator",
            },
            timeout=TIMEOUT,
        )

    def _load_config(self, env_path: Optional[str]):
        # SSOT: do not load ad-hoc .env files; rely on Vault-derived env
        if env_path:
            logger.error("Custom env files are not supported; use Vault-derived environment")
            sys.exit(1)

        # Minimal config: sources
        self.sources = MOCK_SOURCES

    def _select_scenario(self) -> Scenario:
        weights = [s.weight for s in SCENARIOS]
        return random.choices(SCENARIOS, weights=weights, k=1)[0]

    def _get_random_date(self) -> str:
        days_back = random.randint(0, 60)
        date = datetime.now() - timedelta(days=days_back)
        # Randomize time within the day
        hours = random.randint(0, 23)
        mins = random.randint(0, 59)
        date = date.replace(hour=hours, minute=mins)
        return date.isoformat()

    def _get_recent_date(self, hours_back: int = 24) -> str:
        """Return a recent timestamp within the last N hours.

        Phase 3 validation relies on MCP tool windows capped at 168h, so
        Phase3 stories must be recent enough to be queryable.
        """
        hours_back = max(1, int(hours_back))
        mins_back = random.randint(0, hours_back * 60)
        date = datetime.now() - timedelta(minutes=mins_back)
        return date.isoformat()

    def _generate_story_text(self, prompt: str, client=None) -> str:
        """Call LLM to generate story body."""
        if client is None:
            client = self.client

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are generating SYNTHETIC TEST DATA for a news analysis system. "
                        "Write realistic journalistic stories. Max 400 words. Plain text only (no markdown, no bold). "
                        "\n\nCRITICAL RULES:\n"
                        "1. Use ONLY company names, tickers, and facts from the user prompt\n"
                        "2. NEVER invent: companies, executives, numbers, dates, or relationships\n"
                        "3. If the prompt says 'QNTM beats earnings', do NOT add 'CEO John Smith said...' unless provided\n"
                        "4. Keep all figures, percentages, and timelines EXACTLY as specified in the prompt\n"
                        "5. This tests entity extraction - stick to the provided universe"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1000,
            "temperature": 0.7,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = client.post("/chat/completions", json=payload)
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
                elif response.status_code == 429:
                    logger.warning("Rate limit hit, sleeping...")
                    time.sleep(2**attempt)
                else:
                    logger.error(f"API Error {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Request failed: {e}")
                time.sleep(1)

        raise RuntimeError("Failed to generate story after retries")

    def generate_batch(
        self,
        count: int,
        output_dir: Path,
        scenarios_override: list[Scenario] | None = None,
        max_workers: int = 1,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)

        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")

        total = len(scenarios_override) if scenarios_override is not None else count
        logger.info(f"Generating {total} stories to {output_dir}...")

        all_tickers = UNIVERSE.get_tickers()
        all_relationships = UNIVERSE.get_relationships()
        all_factor_exposures = UNIVERSE.get_factor_exposures()

        def _scenario_for_index(i: int) -> Scenario:
            if scenarios_override is not None:
                return scenarios_override[i]
            return self._select_scenario()

        def _generate_one(i: int):
            scenario = _scenario_for_index(i)

            # Phase 3 / Phase 4: steer scenario selection toward deterministic
            # tickers so bias-sweep validation can reliably match titles.
            forced_ticker_sym: str | None = None
            forced_affected_tickers: list[str] | None = None
            forced_related_ticker_sym: str | None = None
            forced_relationship_desc: str | None = None

            if scenario.name == "Phase3 A Defense Tail Holding Failure":
                forced_ticker_sym = "NXS"
            elif scenario.name == "Phase3 B Offense Thematic M&A":
                forced_ticker_sym = "LUXE"
            elif scenario.name == "Phase3 C Systemic Multi-Holding Shock":
                # Hedge fund holdings (stable simulation client) - use three tickers.
                forced_affected_tickers = ["QNTM", "BANKO", "VIT"]
                forced_ticker_sym = forced_affected_tickers[0]

            # Phase 4 calibration: mandate needles
            elif scenario.name == "Phase4 M1 AI Compute Supply Chain":
                forced_ticker_sym = "GENE"
            elif scenario.name == "Phase4 M2 Rates Shock Inflation Print":
                forced_ticker_sym = "PROP"
            elif scenario.name == "Phase4 M3 Crypto Protocol Exploit":
                forced_ticker_sym = "FIN"
            elif scenario.name == "Phase4 M4 Energy Transition Policy":
                forced_ticker_sym = "VELO"
            elif scenario.name == "Phase4 M5 Cloud Pricing SaaS Shift":
                forced_ticker_sym = "LUXE"
            elif scenario.name == "Phase4 M6 Credit Downgrade Geopolitical":
                forced_ticker_sym = "VIT"
            # Phase 4 calibration: relationship hops
            elif scenario.name == "Phase4 R1 Supplier Disruption 1Hop":
                forced_ticker_sym = "VELO"
                forced_related_ticker_sym = "ECO"
                forced_relationship_desc = "Velocity Motors uses EcoPower batteries"
            elif scenario.name == "Phase4 R2 Competitor Recall 2Hop":
                forced_ticker_sym = "VIT"
                forced_related_ticker_sym = "GENE"
                forced_relationship_desc = "GeneSys vs Vitality Pharma in Healthcare"
            elif scenario.name == "Phase4 R3 Systemic Multi-Ticker Shock":
                forced_affected_tickers = ["OMNI", "SHOPM", "TRUCK"]
                forced_ticker_sym = forced_affected_tickers[0]
            # Phase 4 calibration: negative controls
            elif scenario.name == "Phase4 N1 Generic Sector Chatter":
                forced_ticker_sym = "PROP"
            elif scenario.name == "Phase4 N2 Wrong Theme Strong Headline":
                forced_ticker_sym = "GENE"

            # For macro factor scenarios, select a ticker with relevant exposure
            if scenario.name in [
                "Interest Rate Impact",
                "Commodity Price Shock",
                "Regulatory Event",
                "China Economic Data",
            ]:
                # Map scenario to factor
                factor_map = {
                    "Interest Rate Impact": "INTEREST_RATES",
                    "Commodity Price Shock": "COMMODITY_PRICES",
                    "Regulatory Event": "REGULATION",
                    "China Economic Data": "CHINA_ECONOMY",
                }
                factor_id = factor_map[scenario.name]

                # Find tickers with exposure to this factor
                exposed_tickers = [
                    exp.ticker for exp in all_factor_exposures if exp.factor_id == factor_id
                ]

                if not exposed_tickers:
                    # No exposures, skip this scenario
                    logger.warning(f"No exposures for {factor_id}, skipping scenario")
                    return False

                ticker_sym = forced_ticker_sym or random.choice(exposed_tickers)
                ticker = UNIVERSE.get_ticker(ticker_sym)

                # Get the exposure details
                exposure = next(
                    e
                    for e in all_factor_exposures
                    if e.ticker == ticker_sym and e.factor_id == factor_id
                )
            else:
                if forced_ticker_sym:
                    ticker = UNIVERSE.get_ticker(forced_ticker_sym)
                else:
                    ticker = random.choice(all_tickers)
                exposure = None

            source = random.choice(MOCK_SOURCES)

            # Context Variables
            prompt_vars = {
                "ticker": ticker.ticker,
                "name": ticker.name,
                "sector": ticker.sector,
                "style_guide": source.style_guide,
                "related_ticker": "N/A",
                "related_name": "N/A",
                "relationship_desc": "N/A",
                "affected_tickers_csv": ticker.ticker,
                "factor_exposure_desc": "N/A",
                "factor_beta": "0.0",
                "regulation_context": "SEC announces new disclosure requirements",
            }

            if forced_affected_tickers:
                prompt_vars["affected_tickers_csv"] = ", ".join(forced_affected_tickers)

            # Handle macro factor scenarios
            if exposure:
                prompt_vars["factor_exposure_desc"] = exposure.description
                prompt_vars["factor_beta"] = f"{exposure.beta:.1f}"

                # Context-specific regulation descriptions
                if scenario.name == "Regulatory Event":
                    if exposure.beta > 0:
                        prompt_vars["regulation_context"] = (
                            "Government announces favorable policy/subsidies"
                        )
                    else:
                        prompt_vars["regulation_context"] = (
                            "Regulators announce stricter compliance requirements"
                        )
            # Select competitors for "Peer Exclusion" context (Legacy support)
            competitors = [
                t for t in all_tickers if t.ticker != ticker.ticker and t.sector == ticker.sector
            ]
            if not competitors:
                competitors = [t for t in all_tickers if t.ticker != ticker.ticker]
            comp_sample = random.sample(competitors, min(2, len(competitors)))

            prompt_vars["competitor1"] = (
                comp_sample[0].name if len(comp_sample) > 0 else "Competitor"
            )
            prompt_vars["competitor2"] = comp_sample[1].name if len(comp_sample) > 1 else "Rival"
            # 30% chance to use Alias if available
            if ticker.aliases and random.random() < 0.3:
                # Override ticker/name with alias for the Prompt to force vague writing
                alias = random.choice(ticker.aliases)
                prompt_vars["name"] = alias
                # leave ticker as is for metadata, but instructions say "Subject: {ticker} ({name})"
                # We'll rely on the model instructions to follow the name provided in the text prompt

            # Handle Relationship Scenarios
            if "related_ticker" in scenario.template:
                if forced_related_ticker_sym:
                    # Phase 4: deterministic related ticker
                    related_ticker = UNIVERSE.get_ticker(forced_related_ticker_sym)
                    prompt_vars["related_ticker"] = related_ticker.ticker
                    prompt_vars["related_name"] = related_ticker.name
                    prompt_vars["relationship_desc"] = (
                        forced_relationship_desc or "related entity"
                    )
                else:
                    # Find relationships where this ticker is the target (e.g. Supplier -> TARGET)
                    # or source depending on scenario logic.
                    # For "Supplier Delay", we want a Supplier (Source) affecting Ticker (Target).
                    # For "Competitor", we want a Competitor (Source/Target) vs Ticker.

                    relevant_rels = [
                        r
                        for r in all_relationships
                        if r.target == ticker.ticker or r.source == ticker.ticker
                    ]

                    if relevant_rels:
                        rel = random.choice(relevant_rels)
                        # Determine which is the "Related" entity
                        if rel.source == ticker.ticker:
                            related_ticker_sym = rel.target
                        else:
                            related_ticker_sym = rel.source

                        related_ticker = UNIVERSE.get_ticker(related_ticker_sym)

                        prompt_vars["related_ticker"] = related_ticker.ticker
                        prompt_vars["related_name"] = related_ticker.name
                        prompt_vars["relationship_desc"] = rel.description
                    else:
                        # Fallback if no relations: pick random other ticker as "Competitor"
                        related_ticker = random.choice(
                            [t for t in all_tickers if t.ticker != ticker.ticker]
                        )
                        prompt_vars["related_ticker"] = related_ticker.ticker
                        prompt_vars["related_name"] = related_ticker.name
                        prompt_vars["relationship_desc"] = "operates in the same market"

            full_prompt = scenario.template.format(**prompt_vars)

            client = None
            try:
                if max_workers > 1:
                    client = self._create_client()

                logger.info(
                    f"[{i+1}/{total}] Generating '{scenario.name}' for {ticker.ticker} via {source.name}"
                )
                story_body = self._generate_story_text(full_prompt, client=client)

                # Use Default Simulation Group
                group_guid = DEFAULT_GROUP["guid"]

                # Calculate expected_relevant_clients based on portfolios and watchlists,
                # unless the scenario explicitly defines expected clients.
                expected_clients = []
                if scenario.validation.expected_relevant_clients:
                    expected_clients = list(scenario.validation.expected_relevant_clients)
                else:
                    for client_guid, portfolio in CLIENT_PORTFOLIOS.items():
                        if ticker.ticker in portfolio:
                            expected_clients.append(client_guid)
                        elif ticker.ticker in CLIENT_WATCHLISTS.get(client_guid, []):
                            expected_clients.append(client_guid)

                # For relationship scenarios, also include clients holding the related ticker
                if prompt_vars.get("related_ticker") != "N/A":
                    related_ticker_sym = prompt_vars["related_ticker"]
                    for client_guid, portfolio in CLIENT_PORTFOLIOS.items():
                        if related_ticker_sym in portfolio and client_guid not in expected_clients:
                            expected_clients.append(client_guid)

                # Construct Output JSON
                if scenario.name.startswith(("Phase3", "Phase4")):
                    title = f"[{scenario.name}] {prompt_vars['ticker']} - {prompt_vars['name']}"
                else:
                    title = f"Update regarding {prompt_vars['name']}"

                published_at = (
                    self._get_recent_date(hours_back=1)
                    if scenario.name.startswith(("Phase3", "Phase4"))
                    else self._get_random_date()
                )

                output_data = {
                    "source": source.name,  # Legacy field
                    "source_name": source.name,  # Standardized field
                    "meta_source_name": source.name,  # For graph node matching
                    "source_guid": source.guid,
                    "trust_level": source.trust_level,
                    "source_type": "NEWS_WIRE",  # Default for synthetic generator
                    "group_guid": group_guid,
                    "event_type": scenario.validation.expected_event,
                    "published_at": published_at,
                    "upload_as_group": group_guid,
                    "title": title,
                    "story_body": story_body,
                    "validation_metadata": {
                        "scenario": scenario.name,
                        "base_ticker": ticker.ticker,  # Ground truth
                        "expected_tier": scenario.validation.expected_tier,
                        "expected_event": scenario.validation.expected_event,
                        "expected_relevant_clients": expected_clients,
                        "relationship_hops": scenario.validation.relationship_hops,
                        "expected_feed_rank_range": scenario.validation.expected_feed_rank_range,
                        "validation_rules": asdict(scenario.validation),
                    },
                }

                # Save
                filename = f"synthetic_{int(time.time())}_{i}_{ticker.ticker}.json"
                with open(output_dir / filename, "w") as f:
                    json.dump(output_data, f, indent=2)

                return True
            except Exception as e:
                logger.error(f"Failed to generate story {i}: {e}")
                return False
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass

        if max_workers == 1:
            ok = 0
            for i in range(total):
                if _generate_one(i):
                    ok += 1
            logger.info(f"Batch generation complete: {ok}/{total} succeeded")
            return

        ok = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_generate_one, i) for i in range(total)]
            for f in concurrent.futures.as_completed(futures):
                try:
                    if f.result():
                        ok += 1
                except Exception as e:
                    logger.error(f"Generation worker failed: {e}")

        logger.info(f"Batch generation complete: {ok}/{total} succeeded")


# ============================================================================
# Main
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic financial news")
    parser.add_argument("--count", type=int, default=5, help="Number of stories to generate")
    parser.add_argument("--output", type=str, default="data/synthetic", help="Output directory")
    parser.add_argument("--env", type=str, help="Path to .env file")
    parser.add_argument("--model", type=str, default=None, help=f"LLM model name (default: $GOFR_IQ_LLM_MODEL or {DEFAULT_MODEL})")
    parser.add_argument(
        "--phase3",
        action="store_true",
        help="Generate exactly one story per Phase3 scenario (A-D)",
    )
    parser.add_argument(
        "--phase4",
        action="store_true",
        help="Generate exactly one story per Phase4 calibration scenario",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="generate",
        choices=["generate", "ingest"],
        help="Operation mode: 'generate' stories or 'ingest' them (default: generate)",
    )

    args = parser.parse_args()

    if args.mode == "generate":
        generator = SyntheticGenerator(args.env, model=args.model)
        if args.phase3:
            phase3_scenarios = [s for s in SCENARIOS if s.name.startswith("Phase3")]
            if not phase3_scenarios:
                raise RuntimeError(
                    "No Phase3 scenarios found. Expected scenario names starting with 'Phase3'."
                )
            generator.generate_batch(
                count=len(phase3_scenarios),
                output_dir=Path(args.output),
                scenarios_override=phase3_scenarios,
            )
        elif args.phase4:
            phase4_scenarios = [s for s in SCENARIOS if s.name.startswith("Phase4")]
            if not phase4_scenarios:
                raise RuntimeError(
                    "No Phase4 scenarios found. Expected scenario names starting with 'Phase4'."
                )
            generator.generate_batch(
                count=len(phase4_scenarios),
                output_dir=Path(args.output),
                scenarios_override=phase4_scenarios,
            )
        else:
            generator.generate_batch(args.count, Path(args.output))
        logger.info("Batch generation complete.")
    elif args.mode == "ingest":
        logger.info("Ingestion mode not yet implemented.")
        # Future implementation: Read JSON files from output dir and POST to ingestion endpoint


if __name__ == "__main__":
    main()
