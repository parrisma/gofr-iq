#!/usr/bin/env python3
"""
Generate Investment Policy Statements (IPS) for Client Archetypes

Creates realistic IPS documents that define investment mandates, risk profiles,
exclusions, and preferences for each client type. These will be used for:
1. Semantic filtering of news feeds
2. Context-aware reranking
3. ESG/thematic filtering
4. Mandate compliance checking

Usage:
    uv run simulation/generate_client_ips.py
"""

import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from simulation.universe.types import ClientArchetype

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class InvestmentPolicyStatement:
    """Complete IPS for a client"""
    client_guid: str
    client_name: str
    archetype: str
    
    # Investment Objectives
    primary_objective: str
    return_target: str
    risk_tolerance: str
    time_horizon: str
    
    # Investment Universe
    permitted_asset_classes: List[str]
    prohibited_sectors: List[str]
    geographic_focus: List[str]
    market_cap_preference: str
    
    # ESG & Thematic Constraints
    esg_policy: str
    esg_exclusions: List[str]
    positive_themes: List[str]
    
    # Risk Parameters
    max_position_size: float
    max_sector_concentration: float
    max_single_issuer: float
    volatility_constraint: Optional[float]
    
    # Information Preferences
    news_priority: List[str]  # Event types to prioritize
    trust_requirement: str  # Source trust level policy
    alert_threshold: float  # Impact score threshold
    
    # Compliance & Governance
    regulatory_framework: List[str]
    reporting_requirements: List[str]
    investment_committee_approval: List[str]


def generate_hedge_fund_ips() -> InvestmentPolicyStatement:
    """Alpha-focused hedge fund with aggressive risk profile"""
    return InvestmentPolicyStatement(
        client_guid="client-hedge-fund",
        client_name="Apex Capital",
        archetype="HEDGE_FUND",
        
        primary_objective="Generate absolute returns through long/short equity strategies with alpha generation from information asymmetries and event-driven catalysts",
        return_target="15-25% annual return (net of fees)",
        risk_tolerance="High - willing to accept volatility for alpha opportunities",
        time_horizon="Short to medium term (3-18 months per position)",
        
        permitted_asset_classes=[
            "Global equities (long/short)",
            "Derivatives (options, futures)",
            "Convertible bonds",
            "Warrants and rights"
        ],
        prohibited_sectors=[
            "Tobacco",
            "Controversial weapons",
            "Private prisons"
        ],
        geographic_focus=[
            "Global developed markets",
            "Select emerging markets (China, India, Brazil)"
        ],
        market_cap_preference="Mid to large cap ($2B+), opportunistic small cap",
        
        esg_policy="Integrated ESG analysis with focus on material risks, but not binding constraints",
        esg_exclusions=[
            "Companies with severe ESG controversies (MSCI CCC rated)",
            "Thermal coal producers (>25% revenue)",
            "Tobacco manufacturers"
        ],
        positive_themes=[
            "Technology disruption",
            "Healthcare innovation",
            "Financial technology"
        ],
        
        max_position_size=0.15,  # 15% of portfolio
        max_sector_concentration=0.40,  # 40% in any sector
        max_single_issuer=0.20,  # 20% max (concentrated conviction)
        volatility_constraint=None,  # No strict vol limit
        
        news_priority=[
            "M&A / Corporate Actions",
            "Earnings surprises",
            "Regulatory events",
            "Management changes",
            "Short interest / activist activity"
        ],
        trust_requirement="Accept medium-trust sources (trust level 2+) for speed advantage; verify before trading",
        alert_threshold=60.0,
        
        regulatory_framework=[
            "SEC Registered Investment Adviser",
            "Form PF reporting",
            "Internal compliance program"
        ],
        reporting_requirements=[
            "Monthly NAV and performance",
            "Quarterly investor letters",
            "Annual audited financials"
        ],
        investment_committee_approval=[
            "New positions >10% of portfolio",
            "Short positions >5% of portfolio",
            "New sector exposure >30%"
        ]
    )


def generate_pension_fund_ips() -> InvestmentPolicyStatement:
    """Conservative institutional investor with fiduciary duties"""
    return InvestmentPolicyStatement(
        client_guid="client-pension-fund",
        client_name="Teachers Retirement System",
        archetype="PENSION_FUND",
        
        primary_objective="Preserve capital and generate stable returns to meet long-term pension obligations with minimal downside risk",
        return_target="7-9% annual return (actuarial assumption: 7.25%)",
        risk_tolerance="Low - preservation of capital paramount; max 15% drawdown tolerance",
        time_horizon="Very long term (20+ years to meet obligations)",
        
        permitted_asset_classes=[
            "Investment-grade equities",
            "Investment-grade bonds",
            "Index funds and ETFs",
            "Real assets (infrastructure, real estate)"
        ],
        prohibited_sectors=[
            "Tobacco",
            "Firearms manufacturers",
            "Gambling",
            "Fossil fuel extraction (coal, oil sands)",
            "Private prisons"
        ],
        geographic_focus=[
            "Primarily US domestic",
            "Developed international (Europe, Japan, Australia)",
            "Limited emerging markets (<5%)"
        ],
        market_cap_preference="Large cap only ($10B+), blue-chip dividend payers",
        
        esg_policy="Strict ESG integration with exclusionary screens; signatory to UN PRI (Principles for Responsible Investment)",
        esg_exclusions=[
            "All UN Global Compact violators",
            "Fossil fuel extraction and coal power generation",
            "Tobacco, firearms, gambling, adult entertainment",
            "Companies with poor labor practices or union violations",
            "Severe environmental controversies"
        ],
        positive_themes=[
            "Clean energy transition",
            "Education and workforce development",
            "Healthcare accessibility",
            "Sustainable infrastructure"
        ],
        
        max_position_size=0.03,  # 3% max individual position
        max_sector_concentration=0.20,  # 20% sector limit
        max_single_issuer=0.05,  # 5% max (diversification required)
        volatility_constraint=18.0,  # Annual volatility <18%
        
        news_priority=[
            "ESG controversies",
            "Regulatory compliance",
            "Dividend policy changes",
            "Credit rating changes",
            "Systemic risk indicators"
        ],
        trust_requirement="High-trust sources only (trust level 8+) - verified, established news agencies required for investment decisions",
        alert_threshold=70.0,
        
        regulatory_framework=[
            "ERISA fiduciary standards",
            "State pension regulations",
            "DOL oversight",
            "Annual actuarial review"
        ],
        reporting_requirements=[
            "Quarterly board reporting",
            "Annual public disclosure",
            "Beneficiary statements",
            "ESG impact reporting"
        ],
        investment_committee_approval=[
            "All new positions",
            "Any sector allocation change >2%",
            "All ESG exclusions list updates",
            "Risk limit breaches"
        ]
    )


def generate_retail_trader_ips() -> InvestmentPolicyStatement:
    """Aggressive retail trader with meme stock / crypto exposure"""
    return InvestmentPolicyStatement(
        client_guid="client-retail",
        client_name="DiamondHands420",
        archetype="RETAIL_TRADER",
        
        primary_objective="Maximize gains through momentum trading, meme stocks, and crypto-adjacent plays; YOLO strategies with high risk tolerance",
        return_target="100%+ annual return (moon or bust)",
        risk_tolerance="Very High - comfortable with total loss risk; diamond hands mentality",
        time_horizon="Very short term (days to weeks); swing trading",
        
        permitted_asset_classes=[
            "High-beta equities",
            "Crypto-related stocks",
            "Meme stocks",
            "Options (especially 0DTE)",
            "SPACs and recent IPOs"
        ],
        prohibited_sectors=[],  # No exclusions - anything goes
        geographic_focus=[
            "US markets primarily",
            "Crypto exchanges anywhere"
        ],
        market_cap_preference="Any cap, prefer volatile small/mid caps",
        
        esg_policy="No formal ESG policy; may avoid companies with bad social media sentiment",
        esg_exclusions=[],  # None
        positive_themes=[
            "Blockchain / Web3",
            "Electric vehicles",
            "AI / Machine learning",
            "Gaming and esports",
            "Retail investor activism"
        ],
        
        max_position_size=0.50,  # Can go 50% in single position
        max_sector_concentration=1.0,  # No sector limits
        max_single_issuer=0.70,  # All-in on conviction plays
        volatility_constraint=None,  # Higher vol = more fun
        
        news_priority=[
            "Social media trends",
            "Short squeeze potential",
            "Retail sentiment",
            "Influencer mentions",
            "Meme potential",
            "Regulatory FUD"
        ],
        trust_requirement="Accept all sources (trust level 1+) including rumors and social media; speed over accuracy",
        alert_threshold=30.0,  # Want to see everything
        
        regulatory_framework=[
            "Retail brokerage account",
            "Options trading approved"
        ],
        reporting_requirements=[
            "Screenshot P&L for Reddit",
            "Tax forms (if gains exist)"
        ],
        investment_committee_approval=[
            "YOLO approval from r/wallstreetbets upvotes"
        ]
    )


def main():
    """Generate IPS documents for all client archetypes"""
    output_dir = Path(__file__).parent / "client_ips"
    output_dir.mkdir(exist_ok=True)
    
    clients = [
        generate_hedge_fund_ips(),
        generate_pension_fund_ips(),
        generate_retail_trader_ips()
    ]
    
    logger.info(f"Generating Investment Policy Statements for {len(clients)} clients...")
    
    for client in clients:
        # Save as JSON
        output_file = output_dir / f"ips_{client.client_guid}.json"
        with open(output_file, 'w') as f:
            json.dump(asdict(client), f, indent=2)
        
        logger.info(f"  ✓ Created IPS: {client.client_name} ({client.archetype})")
        logger.info(f"    - Trust requirement: {client.trust_requirement}")
        logger.info(f"    - ESG exclusions: {len(client.esg_exclusions)}")
        logger.info(f"    - Prohibited sectors: {len(client.prohibited_sectors)}")
        logger.info(f"    - News priority: {', '.join(client.news_priority[:3])}...")
        logger.info(f"    → Saved to {output_file}")
    
    logger.info(f"\n✅ Generated {len(clients)} IPS documents")
    logger.info(f"📁 Output directory: {output_dir}")
    
    # Print summary
    print("\n" + "="*70)
    print("INVESTMENT POLICY STATEMENTS GENERATED")
    print("="*70)
    for client in clients:
        print(f"\n{client.client_name} ({client.archetype})")
        print(f"  Objective: {client.primary_objective[:80]}...")
        print(f"  Risk: {client.risk_tolerance}")
        print(f"  Trust: {client.trust_requirement[:60]}...")
        print(f"  ESG: {len(client.esg_exclusions)} exclusions, {len(client.prohibited_sectors)} prohibited sectors")
    print("="*70)


if __name__ == "__main__":
    main()
