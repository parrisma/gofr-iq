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


# ============================================================================
# Data Definitions
# ============================================================================

MOCK_UNIVERSE = [
    # Mega-Caps (The "FAANG" equivalents)
    MockTicker("GTX", "GigaTech Inc.", "Technology", "Mega-cap tech, dominant, antitrust target"),
    MockTicker("OMNI", "OmniCorp Global", "Conglomerate", "Industrial giant, slow steady growth"),
    MockTicker(
        "QNTM", "Quantum Compute", "Technology", "High-growth AI/Hardware, extremely volatile"
    ),
    # Mid-Caps & Growth
    MockTicker("NXS", "Nexus Software", "Technology", "SaaS, frequent M&A target"),
    MockTicker("VIT", "Vitality Pharma", "Healthcare", "Biotech, binary FDA outcomes"),
    MockTicker("ECO", "EcoPower Systems", "Energy", "Clean energy, regulatory sensitive"),
    MockTicker("BLK", "BlockChain Verify", "Financial", "Crypto proxy, sentiment driven"),
    # Industry Proxies
    MockTicker("STR", "Stratos Defense", "Industrials", "Defense contractor, government spending"),
    MockTicker(
        "SHOPM", "ShopMart", "Consumer Cyclical", "Retail giant, consumer spending bellwether"
    ),
    MockTicker("LUXE", "LuxeBrands", "Consumer Cyclical", "Luxury goods, China exposure"),
    MockTicker("BANKO", "BankOne", "Financial", "Major bank, interest rate sensitive"),
    MockTicker("FIN", "FinCorp", "Financial", "Fintech, regulatory risk"),
    MockTicker("VELO", "Velocity Motors", "Auto", "EV manufacturer, supply chain dependent"),
    MockTicker("TRUCK", "HeavyTrucks Inc.", "Auto", "Legacy auto, union labor issues"),
    MockTicker("GENE", "GeneSys", "Healthcare", "Genomics, R&D/Cash burn"),
    MockTicker("PROP", "PropCo REIT", "Real Estate", "Commercial real estate, interest rates"),
    MockTicker("YUM", "YummyFoods", "Consumer Defensive", "Staples, inflation resistant"),
    MockTicker("MEDIA", "MediaGroup", "Communication", "Streaming/Content, subscriber numbers"),
    MockTicker("ROCK", "RockMining", "Basic Materials", "Commodity prices (Lithium/Copper)"),
    MockTicker("SHIP", "ShipCo Logistics", "Industrials", "Global shipping, supply chain health"),
]

SCENARIOS = [
    Scenario(
        name="Platinum Regulator",
        description="Antitrust ruling against mega-cap",
        target_tier="PLATINUM",
        weight=0.01,
        template="Write a breaking news story about a major antitrust ruling against {ticker} ({name}). The Department of Justice or EU regulators have ruled against them, potentially forcing a breakup or massive fine. Use severe language. Do not focus on stock price movement yet, focus on the ruling.",
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
        template="Write a story about {ticker} ({name}) reporting financial results. DO NOT use the words 'earnings per share', 'EPS', or 'profit'. Focus ENTIRELY on 'record revenue', 'smashing sales expectations', 'top-line growth', and 'unprecedented demand'. The tone should be extremely bullish.",
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
        template="Write a story about significant supply chain disruptions affecting {sector}. Mention {ticker} ({name}) primarily, but frame it as an industry-wide issue (e.g., shortages, raw material costs, logistics jams). The outlook is worrying but not catastrophic.",
        validation=ValidationRule(
            min_score=50, max_score=74, expected_tier="SILVER", expected_event="MACRO_DATA"
        ),
    ),
    Scenario(
        name="Rumor Penalty",
        description="M&A rumor with unnamed sources",
        target_tier="BRONZE",  # Should be downgraded from higher
        weight=0.10,
        template="Write a story about a rumored acquisition of {ticker} ({name}). Attribute EVERYTHING to 'people familiar with the matter' or 'anonymous sources'. Explicitly state that companies declined to comment. It's a huge deal if true, but emphasize the lack of confirmation.",
        validation=ValidationRule(
            max_score=74, expected_event="M&A_RUMOR"
        ),  # Should not be GOLD/PLATINUM due to penalty
    ),
    Scenario(
        name="Peer Exclusion",
        description="Primary company news mentioning competitors",
        target_tier="SILVER",
        weight=0.10,
        template="Write a story about {ticker} ({name}) making a strategic move (price cut, new product). Mention competitors {competitor1} and {competitor2} ONLY for context/comparison (e.g., 'unlike rival...'). The news is about {ticker}, not the others.",
        validation=ValidationRule(expected_tier="SILVER"),
    ),
    Scenario(
        name="Standard Filler",
        description="Routine corporate news",
        target_tier="STANDARD",
        weight=0.65,
        template="Write a routine news update about {ticker} ({name}). Topics: minor personnel change, attendance at a conference, generic marketing campaign, or a small ESG initiative. Keep the tone neutral and the impact low.",
        validation=ValidationRule(max_score=49, expected_tier="STANDARD", expected_event="OTHER"),
    ),
]

# ============================================================================
# Generator Class
# ============================================================================


class SyntheticGenerator:
    def __init__(self, env_path: Optional[str] = None):
        self._load_config(env_path)
        self.api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
        if self.api_key:
            logger.info(
                f"Loaded API Key: {self.api_key[:10]}...{self.api_key[-5:] if len(self.api_key) > 5 else ''}"
            )
        else:
            logger.error("API Key not found!")

        if not self.api_key:
            raise ValueError("GOFR_IQ_OPENROUTER_API_KEY not set in environment or .env file")

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

        for i in range(count):
            scenario = self._select_scenario()
            ticker = random.choice(MOCK_UNIVERSE)

            # Select competitors for "Peer Exclusion" context
            competitors = [
                t for t in MOCK_UNIVERSE if t.ticker != ticker.ticker and t.sector == ticker.sector
            ]
            if not competitors:
                competitors = [t for t in MOCK_UNIVERSE if t.ticker != ticker.ticker]  # Fallback
            comp_sample = random.sample(competitors, min(2, len(competitors)))

            # Prepare Prompt
            prompt_vars = {
                "ticker": ticker.ticker,
                "name": ticker.name,
                "sector": ticker.sector,
                "competitor1": comp_sample[0].name if len(comp_sample) > 0 else "Competitor",
                "competitor2": comp_sample[1].name if len(comp_sample) > 1 else "Rival",
            }

            full_prompt = scenario.template.format(**prompt_vars)

            try:
                logger.info(f"[{i+1}/{count}] Generating '{scenario.name}' for {ticker.ticker}...")
                story_body = self._generate_story_text(full_prompt)

                # Pick random context
                source = random.choice(self.sources)
                group = random.choice(list(self.tokens.keys()))
                token = self.tokens[group]

                # Construct Output JSON
                output_data = {
                    "source": source,
                    "published_at": self._get_random_date(),
                    "upload_as_group": group,
                    "token": token,
                    "title": f"News regarding {ticker.name}",  # LLM could generate this too, but simple is fine
                    "story_body": story_body,
                    "validation_metadata": {
                        "scenario": scenario.name,
                        "base_ticker": ticker.ticker,
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
