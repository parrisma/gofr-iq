#!/usr/bin/env python3
"""
Demo: IPS-Enhanced Feed Queries

Demonstrates how IPS (supplied as JSON) enhances feed intelligence:
1. Load synthetic documents
2. Apply IPS filters (sector exclusions, ESG, trust)
3. Rerank based on theme alignment
4. Compare results for different client archetypes
"""

import json
import sys
from pathlib import Path
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from simulation.client_profiler import ClientProfiler


def load_ips(client_guid: str) -> Dict:
    """Load IPS JSON for client"""
    ips_file = Path(__file__).parent / "client_ips" / f"ips_{client_guid}.json"
    with open(ips_file) as f:
        return json.load(f)


def create_sample_documents() -> List[Dict]:
    """
    Create sample documents representing feed results
    Each has: title, sector, company_name, summary, primary_event, feed_rank
    """
    return [
        {
            "title": "OmniCorp Launches New Quantum Computing Division",
            "sector": "Technology",
            "company_name": "OmniCorp",
            "summary": "Leading tech company expands into quantum computing with $500M investment in AI and machine learning infrastructure",
            "primary_event": "New Product Launch",
            "feed_rank": 0.95,
            "trust_level": 7
        },
        {
            "title": "FusionEnergy Announces Major Offshore Wind Project",
            "sector": "Energy",
            "company_name": "FusionEnergy",
            "summary": "Renewable energy leader secures permits for 2GW offshore wind farm, advancing clean energy transition goals",
            "primary_event": "Project Announcement",
            "feed_rank": 0.88,
            "trust_level": 8
        },
        {
            "title": "TitanMining Faces Environmental Lawsuit Over Operations",
            "sector": "Mining",
            "company_name": "TitanMining",
            "summary": "Indigenous groups file lawsuit alleging water contamination and ecosystem damage from mining operations",
            "primary_event": "Legal Issue",
            "feed_rank": 0.82,
            "trust_level": 6
        },
        {
            "title": "ApexDefense Wins $2B Military Contract",
            "sector": "Defense",
            "company_name": "ApexDefense",
            "summary": "Defense contractor secures multi-year contract for next-generation weapons systems development",
            "primary_event": "Contract Award",
            "feed_rank": 0.78,
            "trust_level": 9
        },
        {
            "title": "SynthBio Breakthrough in Gene Therapy",
            "sector": "Biotechnology",
            "company_name": "SynthBio",
            "summary": "Clinical trials show promising results for genetic disorder treatment using innovative gene editing technology",
            "primary_event": "Research Breakthrough",
            "feed_rank": 0.75,
            "trust_level": 8
        },
        {
            "title": "NovaPharma Hit by Tobacco Product Allegations",
            "sector": "Healthcare",
            "company_name": "NovaPharma",
            "summary": "Reports surface of subsidiary involvement in tobacco product distribution, raising ethical concerns",
            "primary_event": "Controversy",
            "feed_rank": 0.70,
            "trust_level": 5
        },
        {
            "title": "QuantumTech CEO Announces Retirement",
            "sector": "Technology",
            "company_name": "QuantumTech",
            "summary": "Founder steps down after 20 years, succession plan in place with new leadership focused on AI expansion",
            "primary_event": "Executive Change",
            "feed_rank": 0.65,
            "trust_level": 7
        },
        {
            "title": "EcoTransport Launches Electric Vehicle Line",
            "sector": "Transportation",
            "company_name": "EcoTransport",
            "summary": "Sustainable transportation company introduces full electric vehicle lineup targeting zero-emissions future",
            "primary_event": "New Product Launch",
            "feed_rank": 0.60,
            "trust_level": 6
        }
    ]


def demo_filtering(client_guid: str, client_name: str):
    """
    Demonstrate IPS-based filtering for a specific client
    """
    print(f"\n{'='*80}")
    print(f"CLIENT: {client_name} ({client_guid})")
    print('='*80)
    
    # Load IPS
    ips_json = load_ips(client_guid)
    print(f"\n📋 IPS Summary:")
    print(f"   Primary Objective: {ips_json['primary_objective'][:80]}...")
    print(f"   Risk Tolerance: {ips_json['risk_tolerance']}")
    print(f"   Trust Requirement: {ips_json['trust_requirement']}")
    print(f"   Prohibited Sectors: {', '.join(ips_json['prohibited_sectors'])}")
    print(f"   ESG Exclusions: {', '.join(ips_json['esg_exclusions'][:5])}")
    print(f"   Positive Themes: {', '.join(ips_json['positive_themes'][:3])}")
    
    # Get sample documents
    documents = create_sample_documents()
    print(f"\n📰 Original Feed: {len(documents)} documents")
    
    # Apply filtering
    profiler = ClientProfiler()
    filtered_docs = profiler.apply_filters(
        client_guid=client_guid,
        documents=documents,
        ips_json=ips_json
    )
    
    print(f"\n✅ After IPS Filtering: {len(filtered_docs)} documents")
    print(f"   Removed: {len(documents) - len(filtered_docs)} documents")
    
    # Show filtered documents
    if filtered_docs:
        print(f"\n   Remaining Documents:")
        for doc in filtered_docs:
            print(f"   • {doc['title']}")
            print(f"     Sector: {doc['sector']}, Trust: {doc['trust_level']}, Score: {doc['feed_rank']:.2f}")
    
    # Apply reranking
    reranked_docs = profiler.rerank_documents(
        client_guid=client_guid,
        documents=filtered_docs.copy(),
        ips_json=ips_json,
        text_field="summary",
        event_type_field="primary_event",
        base_score_field="feed_rank"
    )
    
    print(f"\n🎯 After IPS Reranking:")
    print(f"   Top 3 Documents:")
    for i, doc in enumerate(reranked_docs[:3], 1):
        boost = doc.get('ips_boost', 0)
        boost_str = f"+{boost:.0%}" if boost > 0 else f"{boost:.0%}"
        print(f"   {i}. {doc['title']}")
        print(f"      Adjusted Score: {doc['feed_rank']:.3f} ({boost_str} boost)")
        print(f"      Boost Reasons: {doc.get('boost_reason', 'Base score')}")
    
    # Show removed documents
    removed_docs = [doc for doc in documents if doc not in filtered_docs]
    if removed_docs:
        print(f"\n❌ Filtered Out:")
        for doc in removed_docs:
            print(f"   • {doc['title']}")
            print(f"     Sector: {doc['sector']}, Trust: {doc['trust_level']}")


def main():
    """Run IPS filtering demo for all client archetypes"""
    
    print("\n" + "="*80)
    print("IPS-ENHANCED FEED INTELLIGENCE DEMO")
    print("="*80)
    print("\nDemonstrates how Investment Policy Statements enhance feed relevance")
    print("by filtering and reranking documents based on client preferences.")
    
    # Demo for each client archetype
    clients = [
        ("550e8400-e29b-41d4-a716-446655440001", "Apex Capital (Hedge Fund)"),
        ("550e8400-e29b-41d4-a716-446655440002", "GlobalPension Fund"),
        ("550e8400-e29b-41d4-a716-446655440003", "Individual Investor")
    ]
    
    for client_guid, client_name in clients:
        try:
            demo_filtering(client_guid, client_name)
        except FileNotFoundError:
            print(f"\n⚠️  IPS file not found for {client_guid}")
            print("   Run: python simulation/generate_client_ips.py")
    
    print(f"\n{'='*80}")
    print("DEMO COMPLETE")
    print('='*80)
    print("\nKey Observations:")
    print("• Hedge Fund: Aggressive, filters very little (min_trust=2)")
    print("• Pension Fund: Conservative, heavy ESG filtering (min_trust=8)")
    print("• Retail: Balanced, moderate filtering (min_trust=5)")
    print("\nIPS enables personalized intelligence - same raw feed, different results")
    print("based on each client's unique risk tolerance, values, and objectives.")
    print()


if __name__ == "__main__":
    main()
