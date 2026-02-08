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
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# SSOT: Add workspace to path and import env module
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))
from gofr_common.gofr_env import get_admin_token, GofrEnvError  # noqa: E402 - path modification required before import

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
    ],  # Quantum Momentum Partners (Hedge Fund)
    "550e8400-e29b-41d4-a716-446655440002": [
        "OMNI",
        "SHOPM",
        "TRUCK",
    ],  # Teachers Retirement (Pension)
    "550e8400-e29b-41d4-a716-446655440003": ["VELO", "BLK"],  # DiamondHands420 (Retail)
}

CLIENT_WATCHLISTS = {
    "client-hedge-fund": ["NXS", "FIN"],
    "client-pension-fund": ["ECO", "STR"],
    "client-retail": ["QNTM", "LUXE"],
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

        logger.info(
            f"Loaded API Key: {self.api_key[:10]}...{self.api_key[-5:] if len(self.api_key) > 5 else ''}"
        )

        self.client = httpx.Client(
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

        # Minimal config: sources/tokens
        self.sources = MOCK_SOURCES
        self.tokens = {}

        # Load bootstrap tokens via SSOT module
        try:
            admin_token = get_admin_token()
            # Map the default simulation group GUID to the admin token for simplified access/ingestion
            self.tokens["group-simulation"] = admin_token
            logger.info("✓ Loaded admin token for group-simulation via SSOT module")
        except GofrEnvError as e:
            logger.error(f"Failed to load tokens via SSOT module: {e}")
            logger.error("Run: uv run python scripts/bootstrap.py")
            sys.exit(1)

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

    def _generate_story_text(self, prompt: str) -> str:
        """Call LLM to generate story body"""
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
                response = self.client.post("/chat/completions", json=payload)
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

    def generate_batch(self, count: int, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Generating {count} stories to {output_dir}...")

        all_tickers = UNIVERSE.get_tickers()
        all_relationships = UNIVERSE.get_relationships()
        all_factor_exposures = UNIVERSE.get_factor_exposures()

        for i in range(count):
            scenario = self._select_scenario()

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
                    continue

                ticker_sym = random.choice(exposed_tickers)
                ticker = UNIVERSE.get_ticker(ticker_sym)

                # Get the exposure details
                exposure = next(
                    e
                    for e in all_factor_exposures
                    if e.ticker == ticker_sym and e.factor_id == factor_id
                )
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
                "factor_exposure_desc": "N/A",
                "factor_beta": "0.0",
                "regulation_context": "SEC announces new disclosure requirements",
            }

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
                    # Fallback if no relations: Skip this scenario or pick random other
                    # For simplicity, we just pick a random other ticker as a "Competitor"
                    related_ticker = random.choice(
                        [t for t in all_tickers if t.ticker != ticker.ticker]
                    )
                    prompt_vars["related_ticker"] = related_ticker.ticker
                    prompt_vars["related_name"] = related_ticker.name
                    prompt_vars["relationship_desc"] = "operates in the same market"

            full_prompt = scenario.template.format(**prompt_vars)

            try:
                logger.info(
                    f"[{i+1}/{count}] Generating '{scenario.name}' for {ticker.ticker} via {source.name}"
                )
                story_body = self._generate_story_text(full_prompt)

                # Use Default Simulation Group
                group_guid = DEFAULT_GROUP["guid"]
                token = self.tokens.get(group_guid)

                # If no token loaded (bootstrap failed), validation might fail downstream
                if not token:
                    token = "placeholder_token"
                    if i == 0:
                        logger.warning("Using placeholder token (bootstrap tokens missing)")

                # Calculate expected_relevant_clients based on portfolios and watchlists
                expected_clients = []
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
                output_data = {
                    "source": source.name,  # Legacy field
                    "source_name": source.name,  # Standardized field
                    "meta_source_name": source.name,  # For graph node matching
                    "source_guid": source.guid,
                    "trust_level": source.trust_level,
                    "source_type": "NEWS_WIRE",  # Default for synthetic generator
                    "group_guid": group_guid,
                    "event_type": scenario.validation.expected_event,
                    "published_at": self._get_random_date(),
                    "upload_as_group": group_guid,
                    "token": token,
                    "title": f"Update regarding {prompt_vars['name']}",
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

            except Exception as e:
                logger.error(f"Failed to generate story {i}: {e}")


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
        "--mode",
        type=str,
        default="generate",
        choices=["generate", "ingest"],
        help="Operation mode: 'generate' stories or 'ingest' them (default: generate)",
    )

    args = parser.parse_args()

    if args.mode == "generate":
        generator = SyntheticGenerator(args.env, model=args.model)
        generator.generate_batch(args.count, Path(args.output))
        logger.info("Batch generation complete.")
    elif args.mode == "ingest":
        logger.info("Ingestion mode not yet implemented.")
        # Future implementation: Read JSON files from output dir and POST to ingestion endpoint


if __name__ == "__main__":
    main()
