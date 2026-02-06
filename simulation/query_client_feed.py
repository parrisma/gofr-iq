#!/usr/bin/env python3
"""
Query Client Feed - Retrieve documents relevant to a client's portfolio.

Usage:
    uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440001 --limit 10
    uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440002 --limit 20
    uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440003

Clients:
    550e8400-e29b-41d4-a716-446655440001    Quantum Momentum Partners (QNTM, BANKO, VIT, GTX)
    550e8400-e29b-41d4-a716-446655440002  Teachers Retirement (OMNI, SHOPM, TRUCK)
    550e8400-e29b-41d4-a716-446655440003        DiamondHands420 (VELO, BLK)
"""
import argparse
import json
import os
import sys
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

# Load environment using SSOT pattern BEFORE imports
from dotenv import load_dotenv
project_root = Path(__file__).parent.parent
load_dotenv(project_root / "docker" / ".env")  # NEO4J_PASSWORD
load_dotenv(project_root / "lib" / "gofr-common" / "config" / "gofr_ports.env")  # Ports

# Set Neo4j connection using docker hostnames (SSOT)
if not os.getenv("GOFR_IQ_NEO4J_URI"):
    os.environ["GOFR_IQ_NEO4J_URI"] = "bolt://gofr-neo4j:7687"
if not os.getenv("GOFR_IQ_NEO4J_USER"):
    os.environ["GOFR_IQ_NEO4J_USER"] = "neo4j"

# Add project root to path
sys.path.append(str(project_root))

from app.services.graph_index import GraphIndex  # noqa: E402 - path modification required before import

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class FeedItem:
    """A single item in a client's feed."""
    document_guid: str
    title: str
    affected_ticker: str
    source_name: str
    trust_level: int
    impact_tier: Optional[str]
    impact_score: Optional[float]
    relevance_reason: str  # DIRECT, WATCHLIST, SUPPLY_CHAIN, COMPETITOR
    position_weight: Optional[float]  # Client's position weight in this ticker
    created_at: Optional[str]


def get_client_feed(
    client_guid: str,
    max_results: int = 20,
    min_trust: Optional[int] = None,
) -> List[FeedItem]:
    """
    Retrieve documents relevant to a client's portfolio.
    
    Query logic:
    1. Find client's portfolio holdings (HOLDS relationship)
    2. Find client's watchlist (WATCHES relationship)
    3. Find documents that AFFECT those instruments
    4. Filter by trust level if client has min_trust preference
    5. Return ranked list
    
    Args:
        client_guid: Client identifier (UUID format, e.g., "550e8400-e29b-41d4-a716-446655440001")
        max_results: Maximum number of results to return
        min_trust: Minimum source trust level (overrides client profile if set)
        
    Returns:
        List of FeedItem objects ranked by relevance
    """
    feed_items: List[FeedItem] = []
    
    with GraphIndex() as graph:
        with graph.driver.session() as session:
            # First, get client's min_trust from profile if not overridden
            if min_trust is None:
                profile_query = """
                MATCH (c:Client {guid: $client_guid})-[:HAS_PROFILE]->(cp:ClientProfile)
                RETURN cp.min_trust as min_trust
                """
                profile_result = session.run(profile_query, {"client_guid": client_guid})
                record = profile_result.single()
                if record and record["min_trust"]:
                    min_trust = record["min_trust"]
                else:
                    min_trust = 0  # No filter
            
            # Query: Documents affecting client's holdings (DIRECT relevance)
            holdings_query = """
            MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(i:Instrument)
            MATCH (d:Document)-[:AFFECTS]->(i)
            MATCH (d)-[:PRODUCED_BY]->(s:Source)
            WHERE s.trust_level >= $min_trust
            RETURN DISTINCT
                d.guid as doc_guid,
                d.title as title,
                i.ticker as ticker,
                s.name as source_name,
                s.trust_level as trust_level,
                d.impact_tier as impact_tier,
                d.impact_score as impact_score,
                h.weight as position_weight,
                d.created_at as created_at,
                'DIRECT' as reason
            ORDER BY d.impact_score DESC, d.created_at DESC
            LIMIT $limit
            """
            
            holdings_result = session.run(holdings_query, {
                "client_guid": client_guid,
                "min_trust": min_trust,
                "limit": max_results
            })
            
            seen_docs = set()
            for record in holdings_result:
                if record["doc_guid"] not in seen_docs:
                    seen_docs.add(record["doc_guid"])
                    feed_items.append(FeedItem(
                        document_guid=record["doc_guid"],
                        title=record["title"] or "Untitled",
                        affected_ticker=record["ticker"],
                        source_name=record["source_name"] or "Unknown",
                        trust_level=record["trust_level"] or 0,
                        impact_tier=record["impact_tier"],
                        impact_score=record["impact_score"],
                        relevance_reason=record["reason"],
                        position_weight=record["position_weight"],
                        created_at=str(record["created_at"]) if record["created_at"] else None
                    ))
            
            # Query: Documents affecting client's watchlist (WATCHLIST relevance)
            watchlist_query = """
            MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(i:Instrument)
            MATCH (d:Document)-[:AFFECTS]->(i)
            MATCH (d)-[:PRODUCED_BY]->(s:Source)
            WHERE s.trust_level >= $min_trust
            AND NOT d.guid IN $seen_docs
            RETURN DISTINCT
                d.guid as doc_guid,
                d.title as title,
                i.ticker as ticker,
                s.name as source_name,
                s.trust_level as trust_level,
                d.impact_tier as impact_tier,
                d.impact_score as impact_score,
                d.created_at as created_at,
                'WATCHLIST' as reason
            ORDER BY d.impact_score DESC, d.created_at DESC
            LIMIT $limit
            """
            
            remaining = max_results - len(feed_items)
            if remaining > 0:
                watchlist_result = session.run(watchlist_query, {
                    "client_guid": client_guid,
                    "min_trust": min_trust,
                    "seen_docs": list(seen_docs),
                    "limit": remaining
                })
                
                for record in watchlist_result:
                    if record["doc_guid"] not in seen_docs:
                        seen_docs.add(record["doc_guid"])
                        feed_items.append(FeedItem(
                            document_guid=record["doc_guid"],
                            title=record["title"] or "Untitled",
                            affected_ticker=record["ticker"],
                            source_name=record["source_name"] or "Unknown",
                            trust_level=record["trust_level"] or 0,
                            impact_tier=record["impact_tier"],
                            impact_score=record["impact_score"],
                            relevance_reason=record["reason"],
                            position_weight=None,  # Watchlist items have no position weight
                            created_at=str(record["created_at"]) if record["created_at"] else None
                        ))
            
            # Query: Supply chain impact (2-hop traversal)
            # Documents affecting suppliers/customers that impact client's holdings
            remaining = max_results - len(feed_items)
            if remaining > 0:
                supply_chain_query = """
                MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(held:Instrument)
                MATCH (held)<-[:ISSUED_BY]-(heldCompany:Company)
                MATCH (heldCompany)<-[:SUPPLIER_OF|:SUPPLIES_TO|:PARTNER_OF]-(relatedCompany:Company)
                MATCH (relatedCompany)-[:ISSUED_BY]->(related:Instrument)
                MATCH (d:Document)-[:AFFECTS]->(related)
                MATCH (d)-[:PRODUCED_BY]->(s:Source)
                WHERE s.trust_level >= $min_trust
                AND NOT d.guid IN $seen_docs
                RETURN DISTINCT
                    d.guid as doc_guid,
                    d.title as title,
                    related.ticker as ticker,
                    s.name as source_name,
                    s.trust_level as trust_level,
                    d.impact_tier as impact_tier,
                    d.impact_score as impact_score,
                    d.created_at as created_at,
                    'SUPPLY_CHAIN' as reason,
                    h.weight as position_weight
                ORDER BY h.weight DESC, d.impact_score DESC, d.created_at DESC
                LIMIT $limit
                """
                
                supply_result = session.run(supply_chain_query, {
                    "client_guid": client_guid,
                    "min_trust": min_trust,
                    "seen_docs": list(seen_docs),
                    "limit": remaining
                })
                
                for record in supply_result:
                    if record["doc_guid"] not in seen_docs:
                        seen_docs.add(record["doc_guid"])
                        feed_items.append(FeedItem(
                            document_guid=record["doc_guid"],
                            title=record["title"] or "Untitled",
                            affected_ticker=record["ticker"],
                            source_name=record["source_name"] or "Unknown",
                            trust_level=record["trust_level"] or 0,
                            impact_tier=record["impact_tier"],
                            impact_score=record["impact_score"],
                            relevance_reason=record["reason"],
                            position_weight=record["position_weight"],
                            created_at=str(record["created_at"]) if record["created_at"] else None
                        ))
            
            # Query: Competitor impact (Schadenfreude opportunities)
            # Documents affecting competitors (bad news = good for client's holdings)
            remaining = max_results - len(feed_items)
            if remaining > 0:
                competitor_query = """
                MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(held:Instrument)
                MATCH (held)<-[:ISSUED_BY]-(heldCompany:Company)
                MATCH (heldCompany)-[:COMPETES_WITH]-(competitorCompany:Company)
                MATCH (competitorCompany)-[:ISSUED_BY]->(competitor:Instrument)
                MATCH (d:Document)-[:AFFECTS]->(competitor)
                MATCH (d)-[:PRODUCED_BY]->(s:Source)
                WHERE s.trust_level >= $min_trust
                AND NOT d.guid IN $seen_docs
                RETURN DISTINCT
                    d.guid as doc_guid,
                    d.title as title,
                    competitor.ticker as ticker,
                    s.name as source_name,
                    s.trust_level as trust_level,
                    d.impact_tier as impact_tier,
                    d.impact_score as impact_score,
                    d.created_at as created_at,
                    'COMPETITOR' as reason,
                    h.weight as position_weight
                ORDER BY h.weight DESC, d.impact_score DESC, d.created_at DESC
                LIMIT $limit
                """
                
                competitor_result = session.run(competitor_query, {
                    "client_guid": client_guid,
                    "min_trust": min_trust,
                    "seen_docs": list(seen_docs),
                    "limit": remaining
                })
                
                for record in competitor_result:
                    if record["doc_guid"] not in seen_docs:
                        seen_docs.add(record["doc_guid"])
                        feed_items.append(FeedItem(
                            document_guid=record["doc_guid"],
                            title=record["title"] or "Untitled",
                            affected_ticker=record["ticker"],
                            source_name=record["source_name"] or "Unknown",
                            trust_level=record["trust_level"] or 0,
                            impact_tier=record["impact_tier"],
                            impact_score=record["impact_score"],
                            relevance_reason=record["reason"],
                            position_weight=record["position_weight"],
                            created_at=str(record["created_at"]) if record["created_at"] else None
                        ))

            # Query: Macro Factor Impact
            # Documents affecting Factors that client's holdings are exposed to (beta != 0)
            remaining = max_results - len(feed_items)
            if remaining > 0:
                factor_query = """
                MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(held:Instrument)
                MATCH (held)<-[:ISSUED_BY]-(heldCompany:Company)
                MATCH (heldCompany)-[exp:EXPOSED_TO]->(f:Factor)
                MATCH (d:Document)-[:AFFECTS]->(f)
                MATCH (d)-[:PRODUCED_BY]->(s:Source)
                WHERE s.trust_level >= $min_trust
                AND NOT d.guid IN $seen_docs
                // Only include significant exposures
                AND abs(toFloat(exp.beta)) > 0.3
                RETURN DISTINCT
                    d.guid as doc_guid,
                    d.title as title,
                    f.factor_id as ticker, // Using factor ID as 'affected ticker'
                    s.name as source_name,
                    s.trust_level as trust_level,
                    d.impact_tier as impact_tier,
                    d.impact_score as impact_score,
                    d.created_at as created_at,
                    'MACRO_FACTOR' as reason,
                    h.weight as position_weight
                ORDER BY h.weight DESC, d.impact_score DESC, d.created_at DESC
                LIMIT $limit
                """
                
                factor_result = session.run(factor_query, {
                    "client_guid": client_guid,
                    "min_trust": min_trust,
                    "seen_docs": list(seen_docs),
                    "limit": remaining
                })
                
                for record in factor_result:
                    if record["doc_guid"] not in seen_docs:
                        seen_docs.add(record["doc_guid"])
                        feed_items.append(FeedItem(
                            document_guid=record["doc_guid"],
                            title=record["title"] or "Untitled",
                            affected_ticker=record["ticker"],
                            source_name=record["source_name"] or "Unknown",
                            trust_level=record["trust_level"] or 0,
                            impact_tier=record["impact_tier"],
                            impact_score=record["impact_score"],
                            relevance_reason=record["reason"],
                            position_weight=record["position_weight"],
                            created_at=str(record["created_at"]) if record["created_at"] else None
                        ))
    
    return feed_items


def print_feed(feed_items: List[FeedItem], format: str = "table") -> None:
    """Print feed items in specified format."""
    if format == "json":
        print(json.dumps([asdict(item) for item in feed_items], indent=2, default=str))
        return
    
    # Table format
    if not feed_items:
        print("No documents found in feed.")
        return
    
    print(f"\n{'='*80}")
    print(f"{'#':<3} {'Ticker':<8} {'Reason':<12} {'Trust':<6} {'Tier':<10} {'Source':<20} {'Title':<30}")
    print(f"{'='*80}")
    
    for i, item in enumerate(feed_items, 1):
        title = (item.title[:27] + "...") if len(item.title) > 30 else item.title
        source = (item.source_name[:17] + "...") if len(item.source_name) > 20 else item.source_name
        tier = item.impact_tier or "N/A"
        
        print(f"{i:<3} {item.affected_ticker:<8} {item.relevance_reason:<12} {item.trust_level:<6} {tier:<10} {source:<20} {title:<30}")
    
    print(f"{'='*80}")
    print(f"Total: {len(feed_items)} documents")


def get_client_summary(client_guid: str) -> dict:
    """Get summary of client's holdings and watchlist."""
    with GraphIndex() as graph:
        with graph.driver.session() as session:
            query = """
            MATCH (c:Client {guid: $client_guid})
            OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
            OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(i:Instrument)
            OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(wi:Instrument)
            RETURN 
                c.name as name,
                cp.min_trust as min_trust,
                cp.risk_appetite as risk_appetite,
                collect(DISTINCT {ticker: i.ticker, weight: h.weight}) as holdings,
                collect(DISTINCT wi.ticker) as watchlist
            """
            result = session.run(query, {"client_guid": client_guid})
            record = result.single()
            
            if not record:
                return {"error": f"Client {client_guid} not found"}
            
            # Clean up holdings (remove nulls)
            holdings = [h for h in record["holdings"] if h["ticker"]]
            watchlist = [w for w in record["watchlist"] if w]
            
            return {
                "name": record["name"],
                "min_trust": record["min_trust"],
                "risk_appetite": record["risk_appetite"],
                "holdings": holdings,
                "watchlist": watchlist
            }


def main():
    parser = argparse.ArgumentParser(
        description="Query client feed - retrieve documents relevant to a client's portfolio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--client", "-c",
        required=True,
        help="Client GUID (e.g., 550e8400-e29b-41d4-a716-446655440001, 550e8400-e29b-41d4-a716-446655440002, 550e8400-e29b-41d4-a716-446655440003)"
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)"
    )
    parser.add_argument(
        "--min-trust", "-t",
        type=int,
        help="Override minimum trust level filter"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Show client portfolio summary before feed"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Check Neo4j connection (SSOT uses GOFR_IQ_NEO4J_URI)
    if not os.environ.get("GOFR_IQ_NEO4J_URI"):
        logger.error("GOFR_IQ_NEO4J_URI environment variable not set.")
        sys.exit(1)
    
    # Show client summary if requested
    if args.summary:
        summary = get_client_summary(args.client)
        if "error" in summary:
            logger.error(summary["error"])
            sys.exit(1)
        
        print(f"\n=== Client: {summary['name']} ===")
        print(f"Risk Appetite: {summary['risk_appetite']}")
        print(f"Min Trust: {summary['min_trust']}")
        holdings_str = ', '.join(f"{h['ticker']} ({h['weight']*100:.0f}%)" for h in summary['holdings'])
        print(f"Holdings: {holdings_str}")
        print(f"Watchlist: {', '.join(summary['watchlist'])}")
    
    # Query feed
    logger.info(f"Querying feed for {args.client}...")
    
    try:
        feed = get_client_feed(
            client_guid=args.client,
            max_results=args.limit,
            min_trust=args.min_trust
        )
        
        print_feed(feed, format=args.format)
        
    except Exception as e:
        logger.error(f"Failed to query feed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
