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

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Try to import dependencies
try:
    from dotenv import load_dotenv
    import httpx
except ImportError:
    logger.error("Missing dependencies. Please run: pip install python-dotenv httpx")
    sys.exit(1)

# ============================================================================
# Configuration & Constants
# ============================================================================

MODEL_NAME = "anthropic/claude-opus-4"  # or another capable model
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
        style_guide="Dry, extremely factual, immediate. Uses formal identifiers (Full Company Name, exact Timestamps). No emotional language."
    ),
    MockSource(
        guid="src-market-blog",
        name="The Daily Alpha",
        trust_level=4,
        persona="opinionated",
        style_guide="Opinionated, uses trading slang ('to the moon', 'bagholder'). Focuses on stock price action and speculation."
    ),
    MockSource(
        guid="src-rumor-mill",
        name="Insider Whispers",
        trust_level=2,
        persona="speculative",
        style_guide="Vague ('sources say', 'unconfirmed reports'), volatile, sensationalist. Use capitalized words for emphasis. Explicitly unconfirmed."
    ),
    MockSource(
        guid="src-local-gazette",
        name="Regional Business Journal",
        trust_level=8,
        persona="local_context",
        style_guide="Hyper-specific local context. Mentions city names, employee counts, local politics. Slower, more narrative pace."
    ),
    MockSource(
        guid="src-tech-cruncher",
        name="Silicon Circuits",
        trust_level=6,
        persona="tech_focused",
        style_guide="Deeply technical, focused on specs, benchmarks, and engineering details. Jargon heavy."
    )
]

# ============================================================================
# Data Definitions
# ============================================================================

from simulation.universe.builder import UniverseBuilder
# Initialize the universe builder to access the shared topology
UNIVERSE = UniverseBuilder()

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
        validation=ValidationRule(
            max_score=74, expected_event="M&A_RUMOR"
        ),
    ),
    Scenario(
        name="Indirect Supplier Delay",
        description="News about a supplier affecting the main company",
        target_tier="GOLD",
        weight=0.10,
        template="News Event: Supplier Delay. Primary Subject: {related_ticker} ({related_name}). Impacted: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write a story about a failure at {related_name} that will specifically hurt {name} because of their relationship ({relationship_desc}). The headline should focus on the Supplier.",
        validation=ValidationRule(
            expected_tier="GOLD", expected_event="SUPPLY_CHAIN"
        ),
    ),
     Scenario(
        name="Competitor Product Launch",
        description="Rival launches a better product",
        target_tier="SILVER",
        weight=0.10,
        template="News Event: Competitor Product Launch. Subject: {related_ticker} ({related_name}). Threat to: {ticker} ({name}). Relationship: {relationship_desc}. Style Guide: {style_guide}. \nTask: Write a story about {related_name} launching a product that makes {name}'s flagship look obsolete. Focus on the competitive threat.",
        validation=ValidationRule(
             expected_tier="SILVER", expected_event="PRODUCT_LAUNCH"
        ),
    ),
    Scenario(
        name="Standard Filler",
        description="Routine corporate news",
        target_tier="STANDARD",
        weight=0.55,
        template="News Event: Routine Update. Subject: {ticker} ({name}). Style Guide: {style_guide}. \nTask: Write a routine update (personnel, marketing, ESG). content should be low impact.",
        validation=ValidationRule(max_score=49, expected_tier="STANDARD", expected_event="OTHER"),
    ),
]

# ============================================================================
# Generator Class
# ============================================================================


class SyntheticGenerator:
    def __init__(self, env_path: Optional[str] = None):
        # Load config first (for tokens/sources)
        self._load_config(env_path)
        
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
        # Load .env file
        if env_path:
            load_dotenv(env_path, override=True)
        else:
            # Try default locations
            base_dir = Path(__file__).parent
            if (base_dir / ".env.synthetic").exists():
                load_dotenv(base_dir / ".env.synthetic", override=True)
            load_dotenv(base_dir.parent / "lib/gofr-common/.env")  # Fallback for API key

        # Parse JSON configs
        try:
            self.sources = json.loads(
                os.environ.get("GOFR_SYNTHETIC_SOURCES", '["Bloomberg", "Reuters"]')
            )
            self.tokens = json.loads(
                os.environ.get("GOFR_SYNTHETIC_TOKENS", '{"admin": "test-token"}')
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON configuration: {e}")
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
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a financial news generator. Write realistic, journalistic news stories. Max 400 words. Do not use markdown (like **bold**) in the body, just plain text logic.",
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

        for i in range(count):
            scenario = self._select_scenario()
            ticker = random.choice(all_tickers)
            source = random.choice(MOCK_SOURCES)

            # Context Variables
            prompt_vars = {
                "ticker": ticker.ticker,
                "name": ticker.name,
                "sector": ticker.sector,
                "style_guide": source.style_guide,
                "related_ticker": "N/A",
                "related_name": "N/A",
                "relationship_desc": "N/A"
            }
            # Select competitors for "Peer Exclusion" context (Legacy support)
            competitors = [
                t for t in all_tickers if t.ticker != ticker.ticker and t.sector == ticker.sector
            ]
            if not competitors:
                competitors = [t for t in all_tickers if t.ticker != ticker.ticker]
            comp_sample = random.sample(competitors, min(2, len(competitors)))
            
            prompt_vars["competitor1"] = comp_sample[0].name if len(comp_sample) > 0 else "Competitor"
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
                
                relevant_rels = [r for r in all_relationships 
                                 if r.target == ticker.ticker or r.source == ticker.ticker]
                
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
                    related_ticker = random.choice([t for t in all_tickers if t.ticker != ticker.ticker])
                    prompt_vars["related_ticker"] = related_ticker.ticker
                    prompt_vars["related_name"] = related_ticker.name
                    prompt_vars["relationship_desc"] = "operates in the same market"

            full_prompt = scenario.template.format(**prompt_vars)

            try:
                logger.info(f"[{i+1}/{count}] Generating '{scenario.name}' for {ticker.ticker} via {source.name}")
                story_body = self._generate_story_text(full_prompt)

                # Pick random group context
                group = random.choice(list(self.tokens.keys()))
                token = self.tokens[group]

                # Construct Output JSON
                output_data = {
                    "source": source.name,  # Legacy field
                    "source_guid": source.guid, # New field for ingestion
                    "trust_level": source.trust_level, # Helping ingest
                    "published_at": self._get_random_date(),
                    "upload_as_group": group,
                    "token": token,
                    "title": f"Update regarding {prompt_vars['name']}", 
                    "story_body": story_body,
                    "validation_metadata": {
                        "scenario": scenario.name,
                        "base_ticker": ticker.ticker, # Ground truth
                        "expected_tier": scenario.validation.expected_tier,
                        "expected_event": scenario.validation.expected_event,
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
    parser.add_argument(
        "--mode",
        type=str,
        default="generate",
        choices=["generate", "ingest"],
        help="Operation mode: 'generate' stories or 'ingest' them (default: generate)",
    )

    args = parser.parse_args()

    if args.mode == "generate":
        generator = SyntheticGenerator(args.env)
        generator.generate_batch(args.count, Path(args.output))
        logger.info("Batch generation complete.")
    elif args.mode == "ingest":
        logger.info("Ingestion mode not yet implemented.")
        # Future implementation: Read JSON files from output dir and POST to ingestion endpoint


if __name__ == "__main__":
    main()
