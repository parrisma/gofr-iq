#!/usr/bin/env python3
"""
Graph Probe Tool for Avatar Testing.

Usage:
  uv run probe_graph.py --client "Nebula"
  uv run probe_graph.py --ticker "TRUCK"
  uv run probe_graph.py --doc "doc-test-01"
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Fix imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Mock environment for config loader
if "NEO4J_PASSWORD" not in os.environ:
    # Try to load from docker/.env
    env_file = PROJECT_ROOT / "docker" / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith("NEO4J_PASSWORD="):
                    os.environ["NEO4J_PASSWORD"] = line.strip().split("=", 1)[1]

from app.config import GofrIqConfig
from app.services.graph_index import GraphIndex

def probe_client(graph: GraphIndex, name_part: str):
    print(f"\n🔍 Probing Client: '{name_part}'")
    with graph._get_session() as session:
        # Get basic profile
        result = session.run("""
            MATCH (c:Client) 
            WHERE toLower(c.name) CONTAINS toLower($name)
            RETURN c.guid, c.name, c.impact_threshold
            LIMIT 1
        """, name=name_part)
        record = result.single()
        
        if not record:
            print("❌ Client not found.")
            return

        client_guid = record["c.guid"]
        print(f"   Name: {record['c.name']}")
        print(f"   GUID: {client_guid}")
        print(f"   Impact Threshold: {record['c.impact_threshold']}")

        # Get Mandate Themes
        res_themes = session.run("""
            MATCH (c:Client {guid: $guid})-[:HAS_PROFILE]->(p:ClientProfile)
            RETURN p.mandate_themes
        """, guid=client_guid).single()
        themes = res_themes["p.mandate_themes"] if res_themes else []
        print(f"   Mandate Themes: {themes}")

        # Get Holdings
        res_holdings = session.run("""
            MATCH (c:Client {guid: $guid})-[:HAS_PORTFOLIO]->(p)-[h:HOLDS]->(i:Instrument)
            RETURN i.ticker
        """, guid=client_guid)
        holdings = [r["i.ticker"] for r in res_holdings]
        print(f"   Holdings: {holdings}")

        # Get Watchlist
        res_watch = session.run("""
            MATCH (c:Client {guid: $guid})-[:HAS_WATCHLIST]->(w)-[:WATCHES]->(i:Instrument)
            RETURN i.ticker
        """, guid=client_guid)
        watching = [r["i.ticker"] for r in res_watch]
        print(f"   Watchlist: {watching}")


def probe_ticker(graph: GraphIndex, ticker: str):
    print(f"\n🔍 Probing Ticker: '{ticker}'")
    with graph._get_session() as session:
        # Check Instrument existence
        res = session.run("MATCH (i:Instrument {ticker: $t}) RETURN i.name", t=ticker).single()
        if not res:
            print("❌ Ticker not found.")
            return
        print(f"   Instrument: {res['i.name']} ({ticker})")

        # Find connected Documents
        print(f"   --- Affecting Documents ---")
        res_docs = session.run("""
            MATCH (d:Document)-[a:AFFECTS]->(i:Instrument {ticker: $t})
            RETURN d.title, d.impact_score as score, d.impact_tier as tier, d.guid
            ORDER BY d.impact_score DESC
        """, t=ticker)
        
        count = 0
        for r in res_docs:
            count += 1
            print(f"   [{r['score']:>3}] {r['tier']:<8} | {r['d.title'][:50]}... ({r['d.guid']})")
        
        if count == 0:
            print("   (No documents found affecting this ticker)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", help="Partial client name")
    parser.add_argument("--ticker", help="Ticker symbol")
    args = parser.parse_args()

    # Init Graph
    try:
        config = GofrIqConfig.from_env()
        graph = GraphIndex(config)
    except Exception as e:
        print(f"Error connecting to graph: {e}")
        sys.exit(1)

    if args.client:
        probe_client(graph, args.client)
    
    if args.ticker:
        probe_ticker(graph, args.ticker)

    if not args.client and not args.ticker:
        parser.print_help()

if __name__ == "__main__":
    main()
