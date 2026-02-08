#!/usr/bin/env python3
"""
Graph Bootstrap & Validation

Standalone script that bootstraps the Neo4j graph schema (constraints, indexes)
and core taxonomy reference data (regions, sectors, event types, factors).

Safe to run multiple times (idempotent via MERGE).

Usage:
    uv run scripts/bootstrap_graph.py                       # Full bootstrap + validate
    uv run scripts/bootstrap_graph.py --validate-only       # Only run validations
    uv run scripts/bootstrap_graph.py --no-reference-data   # Constraints/indexes only
    uv run scripts/bootstrap_graph.py --verbose             # Detailed output

Environment variables:
    NEO4J_URI       (default: bolt://gofr-neo4j:7687)
    NEO4J_USER      (default: neo4j)
    NEO4J_PASSWORD  (required)

Also supports GOFR_IQ_NEO4J_* prefixed variants used by the app stack.
"""

import argparse
import os
import sys
import time
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

# ─── Project paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ═════════════════════════════════════════════════════════════════════════════
# Taxonomy definitions (single source of truth)
# Imported from the universe builder so there's exactly one place to maintain.
# ═════════════════════════════════════════════════════════════════════════════

from simulation.universe.builder import REGIONS, SECTORS, EVENT_TYPES  # noqa: E402 - path modification required before import

# Macro factors — defined inline here because they're core taxonomy,
# not simulation‑specific.  The universe builder also uses these via its own
# init, but the canonical list for production lives here.
FACTORS = [
    {
        "factor_id": "INTEREST_RATES",
        "name": "Interest Rate Changes",
        "category": "Monetary Policy",
        "description": "Central bank interest rate policy changes",
    },
    {
        "factor_id": "COMMODITY_PRICES",
        "name": "Commodity Price Volatility",
        "category": "Commodities",
        "description": "Oil, metals, agricultural commodity price movements",
    },
    {
        "factor_id": "REGULATION",
        "name": "Regulatory Environment",
        "category": "Policy",
        "description": "Government regulatory changes and enforcement",
    },
    {
        "factor_id": "CONSUMER_SPENDING",
        "name": "Consumer Spending",
        "category": "Economic",
        "description": "Household consumption and retail sales trends",
    },
    {
        "factor_id": "CHINA_ECONOMY",
        "name": "China Economic Growth",
        "category": "Geographic",
        "description": "Chinese GDP growth and economic policy",
    },
]


# ═════════════════════════════════════════════════════════════════════════════
# Schema: Constraints & Indexes
# ═════════════════════════════════════════════════════════════════════════════

# Uniqueness constraints on GUID for every node label the app defines.
GUID_NODE_LABELS = [
    "Document", "Source", "Company", "Instrument", "Group",
    "Client", "ClientProfile", "ClientType", "Portfolio", "Watchlist",
    "Region", "Sector", "Factor", "EventType", "Index",
]

# Singleton constraints: natural‑key uniqueness beyond GUID.
SINGLETON_CONSTRAINTS = [
    ("Instrument", "ticker"),
    ("Company", "ticker"),
    ("Factor", "factor_id"),
    ("Sector", "code"),
    ("Region", "code"),
    ("Index", "ticker"),
    ("EventType", "code"),
    ("ClientType", "code"),
]

# Performance indexes.
INDEXES = [
    ("document_created_at",   "Document",   "(d.created_at)"),
    ("document_language",     "Document",   "(d.language)"),
    ("document_impact",       "Document",   "(d.impact_tier, d.created_at)"),
    ("document_impact_score", "Document",   "(d.impact_score)"),
    ("document_feed_query",   "Document",   "(d.impact_tier, d.impact_score, d.created_at)"),
    ("instrument_ticker",     "Instrument", "(i.ticker)"),
    ("instrument_type",       "Instrument", "(i.instrument_type)"),
    ("company_ticker",        "Company",    "(c.ticker)"),
    ("client_name",           "Client",     "(c.name)"),
    ("group_guid_lookup",     "Group",      "(g.guid)"),
    ("eventtype_code",        "EventType",  "(e.code)"),
]

# Minimum expected constraint count after full bootstrap.
MIN_EXPECTED_CONSTRAINTS = len(GUID_NODE_LABELS) + len(SINGLETON_CONSTRAINTS)  # ~23


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _neo4j_env() -> tuple[str, str, str]:
    """Resolve Neo4j connection parameters from environment."""
    uri = (
        os.environ.get("NEO4J_URI")
        or os.environ.get("GOFR_IQ_NEO4J_URI")
        or "bolt://gofr-neo4j:7687"
    )
    user = (
        os.environ.get("NEO4J_USER")
        or os.environ.get("GOFR_IQ_NEO4J_USER")
        or "neo4j"
    )
    password = (
        os.environ.get("NEO4J_PASSWORD")
        or os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    )
    if not password:
        print(f"{RED}ERROR: NEO4J_PASSWORD (or GOFR_IQ_NEO4J_PASSWORD) is required{RESET}")
        sys.exit(1)
    return uri, user, password


def _connect(uri: str, user: str, password: str, retries: int = 5, delay: float = 3.0):
    """Connect to Neo4j with retries."""
    for attempt in range(1, retries + 1):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            return driver
        except ServiceUnavailable:
            if attempt == retries:
                raise
            print(f"  {YELLOW}Neo4j not ready (attempt {attempt}/{retries}), retrying in {delay}s...{RESET}")
            time.sleep(delay)
    raise RuntimeError("Unreachable")


# ═════════════════════════════════════════════════════════════════════════════
# Bootstrap steps
# ═════════════════════════════════════════════════════════════════════════════

def bootstrap_constraints(session, verbose: bool = False) -> int:
    """Create all uniqueness constraints. Returns count created."""
    created = 0

    # 1. GUID uniqueness on every node label
    for label in GUID_NODE_LABELS:
        name = f"{label.lower()}_guid_unique"
        session.run(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.guid IS UNIQUE"
        )
        if verbose:
            print(f"    ✓ GUID constraint: {label}")
        created += 1

    # 2. Singleton natural‑key constraints
    for label, prop in SINGLETON_CONSTRAINTS:
        name = f"{label.lower()}_{prop}_unique"
        session.run(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        if verbose:
            print(f"    ✓ Singleton constraint: {label}.{prop}")
        created += 1

    return created


def bootstrap_indexes(session, verbose: bool = False) -> int:
    """Create performance indexes. Returns count created."""
    created = 0
    for idx_name, label, cols in INDEXES:
        # Build the variable name from first char of label (lowercase)
        var = label[0].lower()
        session.run(
            f"CREATE INDEX {idx_name} IF NOT EXISTS FOR ({var}:{label}) ON {cols}"
        )
        if verbose:
            print(f"    ✓ Index: {idx_name}")
        created += 1
    return created


def bootstrap_taxonomy(session, verbose: bool = False) -> dict[str, int]:
    """Load core taxonomy reference data. Returns counts per label."""
    counts: dict[str, int] = {}

    # Regions
    for r in REGIONS:
        session.run(
            """
            MERGE (r:Region {code: $code})
            SET r.name = $name, r.description = $description
            """,
            r,
        )
    counts["Region"] = len(REGIONS)
    if verbose:
        print(f"    ✓ Regions: {len(REGIONS)}")

    # Sectors
    for s in SECTORS:
        session.run(
            """
            MERGE (s:Sector {code: $code})
            SET s.name = $name, s.description = $description
            """,
            s,
        )
    counts["Sector"] = len(SECTORS)
    if verbose:
        print(f"    ✓ Sectors: {len(SECTORS)}")

    # Event Types
    for et in EVENT_TYPES:
        session.run(
            """
            MERGE (e:EventType {code: $code})
            SET e.name = $name,
                e.category = $category,
                e.base_impact = $base_impact,
                e.default_tier = $default_tier
            """,
            et,
        )
    counts["EventType"] = len(EVENT_TYPES)
    if verbose:
        print(f"    ✓ Event Types: {len(EVENT_TYPES)}")

    # Factors
    for f in FACTORS:
        session.run(
            """
            MERGE (f:Factor {factor_id: $factor_id})
            SET f.name = $name,
                f.category = $category,
                f.description = $description
            """,
            f,
        )
    counts["Factor"] = len(FACTORS)
    if verbose:
        print(f"    ✓ Factors: {len(FACTORS)}")

    return counts


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════

def validate(session, verbose: bool = False) -> tuple[bool, list[str]]:
    """Validate graph bootstrap state.

    Returns (passed: bool, messages: list[str]).
    """
    errors: list[str] = []
    infos: list[str] = []

    # 1. Constraint count
    result = session.run("SHOW CONSTRAINTS")
    constraints = result.data()
    n_constraints = len(constraints)
    if n_constraints >= MIN_EXPECTED_CONSTRAINTS:
        infos.append(f"Constraints: {n_constraints} (≥ {MIN_EXPECTED_CONSTRAINTS}) ✓")
    else:
        errors.append(f"Constraints: {n_constraints} (expected ≥ {MIN_EXPECTED_CONSTRAINTS})")

    if verbose:
        for c in constraints:
            print(f"      {c.get('name', '?')}: {c.get('labelsOrTypes', '?')} {c.get('properties', '?')}")

    # 2. Index count
    result = session.run("SHOW INDEXES WHERE type <> 'LOOKUP'")
    indexes = result.data()
    n_indexes = len(indexes)
    # We expect at least len(INDEXES) custom indexes + some constraint-backing indexes
    if n_indexes >= len(INDEXES):
        infos.append(f"Indexes: {n_indexes} (≥ {len(INDEXES)}) ✓")
    else:
        errors.append(f"Indexes: {n_indexes} (expected ≥ {len(INDEXES)})")

    # 3. Taxonomy node counts
    expected_labels = {
        "Region": len(REGIONS),
        "Sector": len(SECTORS),
        "EventType": len(EVENT_TYPES),
        "Factor": len(FACTORS),
    }
    for label, expected in expected_labels.items():
        result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
        record = result.single()
        actual = record["cnt"] if record else 0
        if actual >= expected:
            infos.append(f"{label} nodes: {actual} (≥ {expected}) ✓")
        else:
            errors.append(f"{label} nodes: {actual} (expected ≥ {expected})")

    passed = len(errors) == 0
    return passed, infos + ([f"{RED}✗ {e}{RESET}" for e in errors] if errors else [])


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap Neo4j graph schema and core taxonomy."
    )
    parser.add_argument("--validate-only", action="store_true",
                        help="Only run validation checks (no writes)")
    parser.add_argument("--no-reference-data", action="store_true",
                        help="Skip taxonomy load (constraints/indexes only)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Detailed output")
    args = parser.parse_args()

    print()
    print(f"{BOLD}{'=' * 65}{RESET}")
    print(f"{BOLD}  📐 Graph Bootstrap & Validation{RESET}")
    print(f"{BOLD}{'=' * 65}{RESET}")

    uri, user, password = _neo4j_env()
    print(f"  Neo4j: {uri}")

    driver = _connect(uri, user, password)

    try:
        with driver.session() as session:

            if not args.validate_only:
                # ── Step 1: Constraints ──
                print(f"\n  {BLUE}[1/3] Creating constraints...{RESET}")
                n = bootstrap_constraints(session, verbose=args.verbose)
                print(f"  {GREEN}✓ {n} constraint definitions applied{RESET}")

                # ── Step 2: Indexes ──
                print(f"\n  {BLUE}[2/3] Creating indexes...{RESET}")
                n = bootstrap_indexes(session, verbose=args.verbose)
                print(f"  {GREEN}✓ {n} index definitions applied{RESET}")

                # ── Step 3: Taxonomy ──
                if args.no_reference_data:
                    print(f"\n  {YELLOW}[3/3] Skipping taxonomy (--no-reference-data){RESET}")
                else:
                    print(f"\n  {BLUE}[3/3] Loading taxonomy reference data...{RESET}")
                    counts = bootstrap_taxonomy(session, verbose=args.verbose)
                    total = sum(counts.values())
                    print(f"  {GREEN}✓ {total} taxonomy nodes merged{RESET}")

            # ── Validation ──
            print(f"\n  {BLUE}Validating...{RESET}")
            passed, messages = validate(session, verbose=args.verbose)
            for msg in messages:
                print(f"    {msg}")

            print()
            if passed:
                print(f"  {GREEN}{BOLD}✅ Graph bootstrap: ALL CHECKS PASSED{RESET}")
            else:
                print(f"  {RED}{BOLD}❌ Graph bootstrap: VALIDATION FAILED{RESET}")

            print()
            return 0 if passed else 1

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
