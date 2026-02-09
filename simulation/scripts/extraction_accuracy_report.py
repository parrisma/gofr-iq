#!/usr/bin/env python3
"""
Post-Ingestion Extraction Accuracy Report
==========================================
Compares LLM extraction results (AFFECTS edges, themes, impact_tier) against
the ground truth embedded in each generated story's validation_metadata.

This answers: "Did the LLM get the ticker/tier/themes right at scale?"

Usage:
    uv run python simulation/scripts/extraction_accuracy_report.py
    uv run python simulation/scripts/extraction_accuracy_report.py --verbose
    uv run python simulation/scripts/extraction_accuracy_report.py --report-json tmp/accuracy.json

Requires:
    - Production Neo4j running with ingested documents
    - Generated story files in simulation/test_output/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.themes import VALID_THEMES  # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DocAccuracy:
    """Accuracy result for a single document."""
    story_file: str
    title: str
    scenario: str
    # Ground truth (from validation_metadata)
    expected_ticker: str
    expected_tier: str
    expected_event: str
    expected_clients: list[str]
    # Actual (from Neo4j)
    found_in_neo4j: bool = False
    actual_tickers: list[str] = field(default_factory=list)
    actual_tier: str = ""
    actual_themes: list[str] = field(default_factory=list)
    actual_score: float = 0.0
    # Accuracy flags
    ticker_match: bool = False      # base_ticker in AFFECTS edges
    tier_match: bool = False        # impact_tier matches expected
    tier_close: bool = False        # tier within 1 level
    has_themes: bool = False        # at least 1 theme extracted
    themes_valid: bool = False      # all themes in VALID_THEMES
    oov_themes: list[str] = field(default_factory=list)  # out-of-vocab themes
    # Error info
    error: str = ""


TIER_ORDER = ["STANDARD", "BRONZE", "SILVER", "GOLD", "PLATINUM"]


def tier_distance(a: str, b: str) -> int:
    """Numeric distance between two impact tiers."""
    a_idx = TIER_ORDER.index(a.upper()) if a.upper() in TIER_ORDER else -1
    b_idx = TIER_ORDER.index(b.upper()) if b.upper() in TIER_ORDER else -1
    if a_idx < 0 or b_idx < 0:
        return 99
    return abs(a_idx - b_idx)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_stories(story_dir: Path) -> list[dict]:
    """Load all generated story files with validation_metadata."""
    stories = []
    for f in sorted(story_dir.glob("synthetic_*.json")):
        try:
            data = json.loads(f.read_text())
            if "validation_metadata" not in data:
                continue
            data["_file"] = f.name
            stories.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return stories


def query_documents(neo4j_uri: str, neo4j_password: str) -> dict[str, dict]:
    """Query all Documents with their AFFECTS edges, themes, scores from Neo4j.

    Returns: {title: {tickers, tier, score, themes}} indexed by title.
    """
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", neo4j_password))
    docs = {}

    with driver.session() as session:
        # Get all documents with their properties and AFFECTS edges
        result = session.run("""
            MATCH (d:Document)
            OPTIONAL MATCH (d)-[:AFFECTS]->(i:Instrument)
            WITH d, collect(DISTINCT i.ticker) AS tickers
            RETURN d.title AS title,
                   d.guid AS guid,
                   d.impact_score AS score,
                   d.impact_tier AS tier,
                   d.themes AS themes,
                   tickers
        """)

        for record in result:
            title = record["title"]
            if not title:
                continue
            raw_themes = record["themes"]
            if isinstance(raw_themes, str):
                try:
                    themes = json.loads(raw_themes)
                except json.JSONDecodeError:
                    themes = [raw_themes]
            elif raw_themes is None:
                themes = []
            else:
                themes = list(raw_themes)

            docs[title] = {
                "guid": record["guid"],
                "tickers": record["tickers"] or [],
                "tier": (record["tier"] or "").upper(),
                "score": record["score"] or 0,
                "themes": themes,
            }

    driver.close()
    return docs


def evaluate(stories: list[dict], neo4j_docs: dict[str, dict]) -> list[DocAccuracy]:
    """Compare each story's ground truth against Neo4j extraction results."""
    results = []

    for story in stories:
        meta = story["validation_metadata"]
        title = story.get("title", "")

        acc = DocAccuracy(
            story_file=story.get("_file", ""),
            title=title,
            scenario=meta.get("scenario", ""),
            expected_ticker=meta.get("base_ticker", ""),
            expected_tier=meta.get("expected_tier", ""),
            expected_event=meta.get("expected_event", ""),
            expected_clients=meta.get("expected_relevant_clients", []),
        )

        # Find in Neo4j by title
        doc = neo4j_docs.get(title)
        if not doc:
            acc.found_in_neo4j = False
            acc.error = "Document not found in Neo4j (ingestion failed?)"
            results.append(acc)
            continue

        acc.found_in_neo4j = True
        acc.actual_tickers = doc["tickers"]
        acc.actual_tier = doc["tier"]
        acc.actual_score = doc["score"]
        acc.actual_themes = doc["themes"]

        # Ticker accuracy: did LLM find the base_ticker?
        acc.ticker_match = acc.expected_ticker in acc.actual_tickers

        # Tier accuracy
        acc.tier_match = acc.actual_tier == acc.expected_tier.upper()
        acc.tier_close = tier_distance(acc.actual_tier, acc.expected_tier) <= 1

        # Theme quality
        acc.has_themes = len(acc.actual_themes) > 0
        acc.oov_themes = [t for t in acc.actual_themes if t not in VALID_THEMES]
        acc.themes_valid = len(acc.oov_themes) == 0

        results.append(acc)

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(results: list[DocAccuracy], verbose: bool = False):
    """Print accuracy report to stdout."""
    total = len(results)
    if total == 0:
        print("No stories to evaluate.")
        return

    found = sum(1 for r in results if r.found_in_neo4j)
    ticker_ok = sum(1 for r in results if r.ticker_match)
    tier_ok = sum(1 for r in results if r.tier_match)
    tier_close = sum(1 for r in results if r.tier_close)
    has_themes = sum(1 for r in results if r.has_themes)
    themes_valid = sum(1 for r in results if r.themes_valid and r.found_in_neo4j)
    oov_total = sum(len(r.oov_themes) for r in results)

    pct = lambda n, d: f"{100*n/d:.1f}%" if d > 0 else "N/A"

    print("")
    print("=" * 70)
    print("  EXTRACTION ACCURACY REPORT")
    print("=" * 70)
    print(f"  Stories evaluated:     {total}")
    print(f"  Found in Neo4j:        {found}/{total} ({pct(found, total)})")
    print("")
    print(f"  TICKER ACCURACY")
    print(f"    Base ticker found:   {ticker_ok}/{found} ({pct(ticker_ok, found)})")
    print(f"    (LLM extracted the ground-truth ticker as an AFFECTS edge)")
    print("")
    print(f"  TIER ACCURACY")
    print(f"    Exact match:         {tier_ok}/{found} ({pct(tier_ok, found)})")
    print(f"    Within 1 level:      {tier_close}/{found} ({pct(tier_close, found)})")
    print("")
    print(f"  THEME QUALITY")
    print(f"    Has >= 1 theme:      {has_themes}/{found} ({pct(has_themes, found)})")
    print(f"    All themes valid:    {themes_valid}/{found} ({pct(themes_valid, found)})")
    print(f"    Out-of-vocab themes: {oov_total} total")
    print("=" * 70)

    # Per-scenario breakdown
    scenarios = sorted(set(r.scenario for r in results))
    if len(scenarios) > 1:
        print("")
        print("  PER-SCENARIO BREAKDOWN")
        print("  " + "-" * 66)
        print(f"  {'Scenario':<30s} {'Count':>5s} {'Ticker':>8s} {'Tier':>8s} {'Themes':>8s}")
        print("  " + "-" * 66)
        for scenario in scenarios:
            sc_results = [r for r in results if r.scenario == scenario]
            sc_found = [r for r in sc_results if r.found_in_neo4j]
            sc_total = len(sc_found)
            if sc_total == 0:
                print(f"  {scenario:<30s} {len(sc_results):>5d}     -        -        -")
                continue
            sc_ticker = sum(1 for r in sc_found if r.ticker_match)
            sc_tier = sum(1 for r in sc_found if r.tier_match)
            sc_themes = sum(1 for r in sc_found if r.has_themes)
            print(f"  {scenario:<30s} {sc_total:>5d} {pct(sc_ticker, sc_total):>8s} {pct(sc_tier, sc_total):>8s} {pct(sc_themes, sc_total):>8s}")
        print("  " + "-" * 66)

    # Failures detail
    if verbose:
        failures = [r for r in results if r.found_in_neo4j and not r.ticker_match]
        if failures:
            print("")
            print("  TICKER MISSES (base_ticker not in AFFECTS edges)")
            print("  " + "-" * 66)
            for r in failures:
                print(f"  {r.story_file}")
                print(f"    Expected: {r.expected_ticker}  Got: {r.actual_tickers}")
                print(f"    Scenario: {r.scenario}  Tier: {r.expected_tier}->{r.actual_tier}")

        not_found = [r for r in results if not r.found_in_neo4j]
        if not_found:
            print("")
            print(f"  NOT FOUND IN NEO4J ({len(not_found)} docs)")
            print("  " + "-" * 66)
            for r in not_found[:10]:
                print(f"  {r.story_file}: {r.title[:60]}")
            if len(not_found) > 10:
                print(f"  ... and {len(not_found) - 10} more")

    print("")


def save_report_json(results: list[DocAccuracy], path: Path):
    """Save accuracy report as JSON."""
    total = len(results)
    found = sum(1 for r in results if r.found_in_neo4j)
    ticker_ok = sum(1 for r in results if r.ticker_match)
    tier_ok = sum(1 for r in results if r.tier_match)
    tier_close = sum(1 for r in results if r.tier_close)
    has_themes = sum(1 for r in results if r.has_themes)
    themes_valid = sum(1 for r in results if r.themes_valid and r.found_in_neo4j)

    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_stories": total,
            "found_in_neo4j": found,
            "ticker_accuracy": ticker_ok / found if found else 0,
            "tier_exact_match": tier_ok / found if found else 0,
            "tier_within_1": tier_close / found if found else 0,
            "has_themes": has_themes / found if found else 0,
            "themes_all_valid": themes_valid / found if found else 0,
        },
        "per_scenario": {},
        "details": [asdict(r) for r in results],
    }

    # Per-scenario summary
    for scenario in sorted(set(r.scenario for r in results)):
        sc = [r for r in results if r.scenario == scenario and r.found_in_neo4j]
        n = len(sc)
        if n == 0:
            continue
        report["per_scenario"][scenario] = {
            "count": n,
            "ticker_accuracy": sum(1 for r in sc if r.ticker_match) / n,
            "tier_exact_match": sum(1 for r in sc if r.tier_match) / n,
            "has_themes": sum(1 for r in sc if r.has_themes) / n,
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str))
    print(f"  Saved JSON report: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Post-ingestion extraction accuracy report"
    )
    parser.add_argument(
        "--story-dir", type=Path, default=PROJECT_ROOT / "simulation" / "test_output",
        help="Directory containing generated story JSON files",
    )
    parser.add_argument(
        "--report-json", type=Path, default=None,
        help="Save JSON report to this path",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # Neo4j connection from env
    # NEO4J_PASSWORD is the canonical production password (set by start-prod.sh).
    # GOFR_IQ_NEO4J_PASSWORD may be stale 'testpassword' from docker/.env.
    neo4j_uri = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687")
    neo4j_password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    if not neo4j_password:
        print("ERROR: NEO4J_PASSWORD or GOFR_IQ_NEO4J_PASSWORD must be set.")
        print("  source docker/.env  # loads NEO4J_PASSWORD")
        sys.exit(1)

    # Load stories
    stories = load_stories(args.story_dir)
    if not stories:
        print(f"No story files with validation_metadata found in {args.story_dir}")
        sys.exit(1)
    print(f"Loaded {len(stories)} stories from {args.story_dir}")

    # Query Neo4j
    print("Querying Neo4j for ingested documents...")
    try:
        neo4j_docs = query_documents(neo4j_uri, neo4j_password)
    except Exception as e:
        print(f"ERROR: Failed to query Neo4j: {e}")
        sys.exit(1)
    print(f"Found {len(neo4j_docs)} documents in Neo4j")

    # Evaluate
    results = evaluate(stories, neo4j_docs)

    # Report
    print_report(results, verbose=args.verbose)

    if args.report_json:
        save_report_json(results, args.report_json)

    # Exit code: fail if ticker accuracy < 50% (something is very wrong)
    found = sum(1 for r in results if r.found_in_neo4j)
    ticker_ok = sum(1 for r in results if r.ticker_match)
    if found > 0 and ticker_ok / found < 0.50:
        print("WARNING: Ticker accuracy below 50% -- extraction quality is poor.")
        sys.exit(1)


if __name__ == "__main__":
    main()
