"""Demo data loader for GOFR-IQ.

This script loads realistic APAC market data into GOFR-IQ for demonstrations.
It creates groups, sources, companies, and sample news stories.

Usage:
    # From dev environment
    python demo/load_demo_data.py --mcpo-url http://gofr-iq-mcpo:8081
    
    # From host
    python demo/load_demo_data.py --mcpo-url http://localhost:8081
"""

from __future__ import annotations

import argparse
import random
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from demo.demo_data import (
    COMPANIES,
    DEMO_CLIENTS,
    GROUPS,
    SOURCES,
    STORY_TEMPLATES,
)


def generate_story_content(template_type: str, **params) -> dict:
    """Generate story content from template with parameters."""
    template = STORY_TEMPLATES[template_type]
    
    title = template["title"].format(**params)
    content = template["content"].format(**params)
    
    return {
        "title": title,
        "content": content,
        "impact_tier": template["impact_tier"],
        "event_type": template["event_type"],
    }


def call_mcpo(mcpo_url: str, tool_name: str, auth_token: str | None = None, **params) -> dict:
    """Call an MCPO tool endpoint.
    
    Args:
        mcpo_url: Base MCPO URL
        tool_name: Name of the tool to call
        auth_token: Optional Bearer token for authentication
        **params: Tool parameters
        
    Returns:
        Response data dict
        
    Raises:
        Exception: If the tool call fails
    """
    url = f"{mcpo_url}/{tool_name}"
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    try:
        response = requests.post(url, json=params, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        # Check for error response
        if result.get("isError"):
            error_msg = result.get("content", [{}])[0].get("text", "Unknown error")
            raise Exception(f"Tool {tool_name} failed: {error_msg}")
        
        # Extract data from response
        if "content" in result and len(result["content"]) > 0:
            import json
            content_text = result["content"][0].get("text", "{}")
            parsed = json.loads(content_text)
            return parsed
        
        return result
    except requests.RequestException as e:
        raise Exception(f"HTTP request failed for {tool_name}: {e}")
    except (KeyError, json.JSONDecodeError) as e:
        raise Exception(f"Failed to parse response from {tool_name}: {e}\nResponse: {result}")


def load_demo_data(
    mcpo_url: str,
    num_stories: int = 30,
    dry_run: bool = False,
    auth_token: str | None = None,
) -> None:
    """Load demo data into GOFR-IQ.
    
    Args:
        mcpo_url: MCPO proxy URL
        num_stories: Number of news stories to generate
        dry_run: If True, print actions without executing
        auth_token: Optional Bearer token for authentication
    """
    
    print("=" * 70)
    print("GOFR-IQ Demo Data Loader")
    print("=" * 70)
    print()
    
    # Step 1: Create Groups
    print("Step 1: Creating Access Groups")
    print("-" * 70)
    for group in GROUPS:
        print(f"  • {group['id']}: {group['description']}")
        if not dry_run:
            # TODO: Call create_group via MCP
            pass
    print()
    
    # Step 2: Create Sources
    print("Step 2: Creating News Sources")
    print("-" * 70)
    source_map = {}  # name -> guid
    for source in SOURCES:
        print(f"  • {source.name} ({source.type}, {source.region}) -> {source.group}")
        if not dry_run:
            try:
                result = call_mcpo(
                    mcpo_url,
                    "create_source",
                    auth_token=auth_token,
                    name=source.name,
                    source_type=source.type,
                    region=source.region,
                    languages=source.languages,
                    trust_level=source.trust_level,
                )
                # Handle different response formats
                source_guid = result.get("source_guid") or result.get("data", {}).get("source_guid")
                if not source_guid:
                    raise Exception(f"No source_guid in response: {result}")
                source_map[source.name] = source_guid
                print(f"    ✓ Created: {source_guid}")
            except Exception as e:
                print(f"    ✗ Error: {e}")
                source_map[source.name] = str(uuid.uuid4())  # Fallback
        else:
            source_map[source.name] = str(uuid.uuid4())
    print()
    
    # Step 3: Create Companies (via graph)
    print("Step 3: Creating Companies & Instruments")
    print("-" * 70)
    for company in COMPANIES:
        print(f"  • {company.ticker}: {company.name} ({company.sector}, {company.country})")
        if not dry_run:
            # TODO: Call graph tool to create instrument + company
            pass
    print()
    
    # Step 4: Create Peer Relationships
    print("Step 4: Creating Peer Relationships")
    print("-" * 70)
    for company in COMPANIES:
        for peer_ticker in company.peers[:2]:  # Limit to 2 peers per company
            print(f"  • {company.ticker} <-> {peer_ticker}")
            if not dry_run:
                # TODO: Call graph tool to create PEER_OF relationship
                pass
    print()
    
    # Step 5: Generate News Stories
    print(f"Step 5: Generating {num_stories} News Stories")
    print("-" * 70)
    
    # Select template distribution
    template_distribution = [
        ("earnings_beat", 8),
        ("earnings_miss", 6),
        ("regulatory", 4),
        ("m_and_a", 3),
        ("guidance_raise", 5),
        ("product_launch", 3),
        ("analyst_upgrade", 1),
    ]
    
    stories_generated = 0
    base_date = datetime.now() - timedelta(days=30)
    
    for template_type, count in template_distribution:
        if stories_generated >= num_stories:
            break
            
        for i in range(min(count, num_stories - stories_generated)):
            # Pick random company
            company = random.choice(COMPANIES)
            
            # Pick random source (prefer same region)
            region_sources = [s for s in SOURCES if s.region == company.country or s.region == "APAC"]
            source = random.choice(region_sources if region_sources else SOURCES)
            
            # Generate story parameters based on template type
            story_date = base_date + timedelta(days=random.randint(0, 29))
            
            params: dict[str, str | int | float] = {
                "company": company.name,
                "ticker": company.ticker,
                "sector": company.sector,
                "quarter": random.choice(["Q1", "Q2", "Q3", "Q4"]),
                "year": "2025",
                "exchange": company.exchange,
            }
            
            # Template-specific parameters
            if template_type == "earnings_beat":
                eps = round(random.uniform(0.8, 2.5), 2)
                estimate = round(eps * random.uniform(0.85, 0.95), 2)
                params.update({
                    "eps": eps,
                    "estimate": estimate,
                    "beat_pct": round((eps / estimate - 1) * 100, 1),
                    "revenue_growth": random.randint(12, 35),
                    "revenue": round(random.uniform(1.5, 15.0), 1),
                    "driver": random.choice(["cloud services", "e-commerce", "automotive", "semiconductors"]),
                    "outlook_driver": random.choice(["improving macro conditions", "new product cycles", "market share gains"]),
                    "rating": random.choice(["Buy", "Overweight", "Strong Buy"]),
                    "pt_low": round(company.market_cap_b * random.uniform(0.9, 1.0), 0),
                    "pt_high": round(company.market_cap_b * random.uniform(1.2, 1.4), 0),
                    "stock_move": round(random.uniform(3.5, 8.5), 1),
                })
            
            elif template_type == "earnings_miss":
                eps = round(random.uniform(0.5, 1.8), 2)
                estimate = round(eps * random.uniform(1.1, 1.25), 2)
                params.update({
                    "eps": eps,
                    "estimate": estimate,
                    "revenue": round(random.uniform(1.0, 10.0), 1),
                    "revenue_decline": random.randint(5, 18),
                    "headwind": random.choice(["supply chain disruptions", "increased competition", "regulatory uncertainty", "weak consumer demand"]),
                    "ceo_name": random.choice(["Zhang Wei", "Tanaka Hiroshi", "Kim Min-ho", "Lee Kuan"]),
                    "cost_action": random.choice(["restructuring initiatives", "headcount reductions", "operational efficiency programs"]),
                    "broker": random.choice(["CLSA", "Nomura", "CITIC"]),
                    "rating": random.choice(["Hold", "Underweight", "Sell"]),
                    "pt_low": round(company.market_cap_b * random.uniform(0.7, 0.85), 0),
                    "stock_move": round(random.uniform(6.0, 15.0), 1),
                })
            
            elif template_type == "regulatory":
                params.update({
                    "regulator": random.choice(["China SAMR", "Hong Kong SFC", "Japan FSA", "Singapore MAS"]),
                    "regulation_type": random.choice(["antitrust", "data privacy", "consumer protection", "cross-border data"]),
                    "provision_1": random.choice(["mandatory data localization", "enhanced disclosure requirements", "market concentration limits"]),
                    "provision_2": random.choice(["third-party audits", "consumer consent mechanisms", "interoperability standards"]),
                    "deadline": random.choice(["Q4 2025", "H1 2026", "end of 2025"]),
                    "margin_impact": random.randint(50, 200),
                    "concern": random.choice(["compliance costs", "business model changes", "competitive disadvantages"]),
                    "ceo_quote": "We are committed to working with regulators to ensure full compliance while serving our customers",
                    "stock_move": round(random.uniform(2.5, 7.5), 1),
                })
            
            elif template_type == "m_and_a":
                target = random.choice([c for c in COMPANIES if c.ticker != company.ticker and c.sector == company.sector])
                params.update({
                    "acquirer": company.name,
                    "target": target.name,
                    "amount": round(target.market_cap_b * random.uniform(1.15, 1.35), 1),
                    "combined_mc": round(company.market_cap_b + target.market_cap_b * 1.25, 0),
                    "offer_price": round(random.uniform(15, 85), 2),
                    "premium": round(random.uniform(18, 35), 0),
                    "jurisdictions": random.choice(["China and Hong Kong", "Japan and Singapore", "Korea and US"]),
                    "timeline": random.choice(["9-12 months", "6-9 months", "12-18 months"]),
                    "view": random.choice(["strategically compelling", "financially attractive", "competitively necessary"]),
                    "rationale": random.choice(["revenue synergies", "cost efficiencies", "market consolidation"]),
                })
            
            elif template_type == "guidance_raise":
                params.update({
                    "driver": random.choice(["EV", "AI chip", "cloud", "semiconductor", "fintech"]),
                    "new_guidance": random.randint(18, 28),
                    "old_guidance": random.randint(10, 16),
                    "geography": random.choice(["China", "Southeast Asia", "Japan", "Korea"]),
                    "product": random.choice(["advanced semiconductors", "electric vehicles", "cloud services", "AI infrastructure"]),
                    "metric": random.choice(["order backlog", "customer acquisition", "revenue per user"]),
                    "metric_growth": random.randint(25, 55),
                    "analyst_firm": random.choice(["CLSA", "Nomura", "CITIC", "Morgan Stanley Asia"]),
                    "new_pt": round(company.market_cap_b * random.uniform(1.15, 1.30), 0),
                    "old_pt": round(company.market_cap_b * random.uniform(0.95, 1.05), 0),
                    "rating": random.choice(["Buy", "Overweight"]),
                })
            
            # Generate story
            story = generate_story_content(template_type, **params)
            
            print(f"  [{stories_generated+1}] {story['title']}")
            print(f"      Source: {source.name} | Date: {story_date.strftime('%Y-%m-%d')} | Impact: {story['impact_tier']}")
            
            if not dry_run:
                try:
                    # Get source GUID
                    source_guid = source_map.get(source.name)
                    if not source_guid:
                        print(f"      ✗ Source not found: {source.name}")
                        continue
                    
                    # Prepare article URL
                    url = f"https://{source.name.lower().replace(' ', '')}.com/articles/{uuid.uuid4().hex[:12]}"
                    
                    result = call_mcpo(
                        mcpo_url,
                        "ingest_document",
                        auth_token=auth_token,
                        source_guid=source_guid,
                        url=url,
                        title=story['title'],
                        content=story['content'],
                        published_at=story_date.isoformat(),
                    )
                    # Handle different response formats
                    doc_guid = result.get("document_guid") or result.get("data", {}).get("document_guid")
                    if doc_guid:
                        print(f"      ✓ Ingested: {doc_guid}")
                    else:
                        print(f"      ✓ Ingested (no GUID returned)")
                    time.sleep(0.3)  # Rate limiting
                except Exception as e:
                    print(f"      ✗ Error: {e}")
            
            stories_generated += 1
    
    print()
    
    # Step 6: Create Demo Clients
    print("Step 6: Creating Demo Clients")
    print("-" * 70)
    client_guids = {}
    for client in DEMO_CLIENTS:
        print(f"  • {client.name} ({client.type})")
        print(f"    Portfolio: {', '.join([f'{t} ({w*100:.0f}%)' for t, w in client.portfolio])}")
        print(f"    Watchlist: {', '.join(client.watchlist)}")
        if not dry_run:
            try:
                # Create client
                result = call_mcpo(
                    mcpo_url,
                    "create_client",
                    auth_token=auth_token,
                    name=client.name,
                    client_type=client.type,
                )
                # Handle different response formats
                client_guid = result.get("client_guid") or result.get("data", {}).get("client_guid")
                if not client_guid:
                    raise Exception(f"No client_guid in response: {result}")
                client_guids[client.name] = client_guid
                print(f"    ✓ Created client: {client_guid}")
                
                # Add portfolio holdings
                for ticker, weight in client.portfolio:
                    try:
                        call_mcpo(
                            mcpo_url,
                            "add_to_portfolio",
                            auth_token=auth_token,
                            client_guid=client_guid,
                            ticker=ticker,
                            weight=weight,
                        )
                        print(f"      ✓ Added to portfolio: {ticker} ({weight*100:.0f}%)")
                    except Exception as e:
                        print(f"      ✗ Portfolio error ({ticker}): {e}")
                
                # Add watchlist items
                for ticker in client.watchlist:
                    try:
                        call_mcpo(
                            mcpo_url,
                            "add_to_watchlist",
                            auth_token=auth_token,
                            client_guid=client_guid,
                            ticker=ticker,
                        )
                        print(f"      ✓ Added to watchlist: {ticker}")
                    except Exception as e:
                        print(f"      ✗ Watchlist error ({ticker}): {e}")
                
            except Exception as e:
                print(f"    ✗ Error creating client: {e}")
    print()
    
    print("=" * 70)
    print("Demo Data Loading Complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Test semantic search: query_documents 'Alibaba earnings'")
    print("  2. Test graph exploration: explore_graph INSTRUMENT 9988.HK")
    print("  3. Test client feeds: get_client_feed <client_guid>")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load demo data into GOFR-IQ via MCPO")
    parser.add_argument("--mcpo-url", required=True, help="MCPO proxy URL (e.g., http://localhost:8081)")
    parser.add_argument("--auth-token", help="Bearer token for authentication (not needed if auth disabled)")
    parser.add_argument("--num-stories", type=int, default=5, help="Number of stories to generate (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    
    args = parser.parse_args()
    
    load_demo_data(
        mcpo_url=args.mcpo_url,
        num_stories=args.num_stories,
        dry_run=args.dry_run,
        auth_token=args.auth_token,
    )
