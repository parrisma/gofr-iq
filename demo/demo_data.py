"""Demo data definitions for GOFR-IQ.

This module contains realistic APAC market data for demonstrating
graph relationships, semantic search, and client feeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# =============================================================================
# Groups (Access Control Tiers)
# =============================================================================

GROUPS = [
    {"id": "public", "description": "Public news - free access"},
    {"id": "premium-apac", "description": "Premium APAC research - paid subscribers"},
    {"id": "internal-sales", "description": "Internal sales team - proprietary"},
    {"id": "quant-desk", "description": "Quantitative trading desk - high frequency"},
]

# =============================================================================
# Sources (News Providers)
# =============================================================================

@dataclass
class Source:
    name: str
    type: Literal["news_agency", "broker", "analyst", "regulator", "other"]
    region: str
    trust_level: Literal["verified", "trusted", "standard", "unverified"]
    group: str
    languages: list[str]

SOURCES = [
    Source("Reuters Asia", "news_agency", "APAC", "verified", "public", ["en"]),
    Source("Bloomberg Terminal", "news_agency", "APAC", "verified", "premium-apac", ["en"]),
    Source("日本経済新聞 (Nikkei)", "news_agency", "JP", "verified", "public", ["ja", "en"]),
    Source("CLSA Research", "broker", "HK", "trusted", "premium-apac", ["en"]),
    Source("Nomura Securities", "broker", "JP", "trusted", "premium-apac", ["en", "ja"]),
    Source("CITIC Securities", "broker", "CN", "trusted", "premium-apac", ["zh", "en"]),
    Source("Internal Alpha Signals", "analyst", "APAC", "standard", "quant-desk", ["en"]),
    Source("HKEX Regulatory", "regulator", "HK", "verified", "public", ["en", "zh"]),
]

# =============================================================================
# Companies & Instruments
# =============================================================================

@dataclass
class Company:
    ticker: str
    name: str
    sector: str
    country: str
    exchange: str
    peers: list[str]  # Other tickers
    market_cap_b: float  # In billions USD

COMPANIES = [
    # Chinese Tech Giants
    Company("9988.HK", "Alibaba Group", "Technology", "CN", "HKEX", ["700.HK", "9618.HK", "PDD"], 220.0),
    Company("700.HK", "Tencent Holdings", "Technology", "CN", "HKEX", ["9988.HK", "BIDU", "NTES"], 380.0),
    Company("9618.HK", "JD.com", "E-Commerce", "CN", "HKEX", ["9988.HK", "PDD"], 45.0),
    Company("1024.HK", "Kuaishou Technology", "Technology", "CN", "HKEX", ["700.HK", "BIDU"], 25.0),
    
    # Japanese Industrials & Tech
    Company("7203.T", "Toyota Motor", "Automotive", "JP", "TSE", ["7267.T", "7201.T"], 280.0),
    Company("6758.T", "Sony Group", "Technology", "JP", "TSE", ["6502.T", "4063.T"], 110.0),
    Company("6502.T", "Toshiba", "Technology", "JP", "TSE", ["6758.T"], 18.0),
    Company("7267.T", "Honda Motor", "Automotive", "JP", "TSE", ["7203.T", "7201.T"], 52.0),
    Company("9984.T", "SoftBank Group", "Technology", "JP", "TSE", ["6758.T"], 65.0),
    
    # Korean Semiconductors
    Company("005930.KS", "Samsung Electronics", "Semiconductors", "KR", "KRX", ["SK Hynix", "TSMC"], 320.0),
    Company("000660.KS", "SK Hynix", "Semiconductors", "KR", "KRX", ["005930.KS"], 75.0),
    
    # Singapore Finance
    Company("D05.SI", "DBS Group", "Banking", "SG", "SGX", ["O39.SI", "U11.SI"], 65.0),
    Company("O39.SI", "OCBC Bank", "Banking", "SG", "SGX", ["D05.SI", "U11.SI"], 45.0),
    Company("U11.SI", "UOB", "Banking", "SG", "SGX", ["D05.SI", "O39.SI"], 42.0),
    
    # Australian Banks
    Company("CBA.AX", "Commonwealth Bank", "Banking", "AU", "ASX", ["NAB.AX", "WBC.AX"], 135.0),
    Company("NAB.AX", "NAB", "Banking", "AU", "ASX", ["CBA.AX", "WBC.AX"], 68.0),
    Company("WBC.AX", "Westpac", "Banking", "AU", "ASX", ["CBA.AX", "NAB.AX"], 55.0),
]

# =============================================================================
# Story Templates
# =============================================================================

STORY_TEMPLATES = {
    "earnings_beat": {
        "title": "{company} Q{quarter} earnings beat estimates by {beat_pct}%",
        "content": """{company} reported Q{quarter} {year} earnings per share of ${eps}, exceeding analyst estimates of ${estimate} by {beat_pct}%. 
Revenue grew {revenue_growth}% year-over-year to ${revenue}B, driven by strong demand in {driver}. 
Management raised full-year guidance, citing {outlook_driver}. 
{sector} sector analysts upgraded the stock to {rating}, with price targets ranging from ${pt_low} to ${pt_high}.
Shares rose {stock_move}% in {exchange} trading on the news.""",
        "impact_tier": "GOLD",
        "event_type": "EARNINGS_BEAT",
    },
    
    "earnings_miss": {
        "title": "{company} misses Q{quarter} estimates, stock falls {stock_move}%",
        "content": """{company} reported disappointing Q{quarter} {year} results, with EPS of ${eps} missing estimates of ${estimate}. 
Revenue of ${revenue}B fell short of projections, declining {revenue_decline}% year-over-year. 
The company cited {headwind} as major headwinds impacting margins. 
CEO {ceo_name} announced {cost_action} to restore profitability. 
Analysts at {broker} downgraded the stock to {rating}, cutting price targets to ${pt_low}.""",
        "impact_tier": "PLATINUM",
        "event_type": "EARNINGS_MISS",
    },
    
    "regulatory": {
        "title": "{regulator} announces new {regulation_type} rules for {sector}",
        "content": """The {regulator} unveiled comprehensive {regulation_type} regulations affecting {company} and peers. 
Key provisions include {provision_1} and {provision_2}, with compliance deadlines set for {deadline}. 
Industry analysts estimate the rules could impact {sector} sector margins by {margin_impact} basis points. 
{company} shares fell {stock_move}% on concerns about {concern}. 
Management pledged full compliance, stating "{ceo_quote}".""",
        "impact_tier": "PLATINUM",
        "event_type": "REGULATORY_CHANGE",
    },
    
    "m_and_a": {
        "title": "{acquirer} in talks to acquire {target} for ${amount}B",
        "content": """{acquirer} is in advanced discussions to acquire {target} in a deal valued at ${amount}B, according to sources familiar with the matter. 
The transaction would create a {sector} powerhouse with combined market cap exceeding ${combined_mc}B. 
{target} shareholders would receive ${offer_price} per share, representing a {premium}% premium to the current trading price. 
Regulatory approval in {jurisdictions} is expected to take {timeline}. 
Analysts view the deal as {view}, citing {rationale}.""",
        "impact_tier": "PLATINUM",
        "event_type": "M&A_ANNOUNCE",
    },
    
    "guidance_raise": {
        "title": "{company} raises FY{year} guidance on strong {driver} demand",
        "content": """{company} upgraded its full-year {year} outlook, now expecting revenue growth of {new_guidance}%, up from prior guidance of {old_guidance}%. 
The revision reflects better-than-expected performance in {geography} and accelerating adoption of {product}. 
Management highlighted {metric} as a key indicator, which grew {metric_growth}% in recent weeks. 
{analyst_firm} raised its price target to ${new_pt} from ${old_pt}, maintaining a {rating} rating.""",
        "impact_tier": "GOLD",
        "event_type": "GUIDANCE_RAISE",
    },
    
    "product_launch": {
        "title": "{company} unveils {product} targeting ${market_size}B market",
        "content": """{company} announced the launch of {product}, a {category} designed to compete with {competitor_product}. 
The new offering features {feature_1} and {feature_2}, addressing customer demand for {need}. 
CEO {ceo_name} stated: "{ceo_quote}". 
Initial orders from {customer_segment} customers exceeded expectations, with delivery scheduled for {timeline}. 
The {sector} sector could see disruption as rivals respond to the competitive threat.""",
        "impact_tier": "SILVER",
        "event_type": "PRODUCT_LAUNCH",
    },
    
    "analyst_upgrade": {
        "title": "{broker} upgrades {company} to {new_rating}, sees {upside}% upside",
        "content": """{broker} analyst {analyst_name} upgraded {company} to {new_rating} from {old_rating}, raising the price target to ${new_pt} from ${old_pt}. 
The upgrade reflects improving fundamentals in {driver}, with {metric} expected to inflect in {timeframe}. 
{analyst_name} noted: "{quote}". 
Key catalysts include {catalyst_1} and {catalyst_2}. 
The stock rose {stock_move}% following the upgrade.""",
        "impact_tier": "SILVER",
        "event_type": "ANALYST_UPGRADE",
    },
}

# =============================================================================
# Sample Clients (for personalized feeds)
# =============================================================================

@dataclass
class DemoClient:
    name: str
    type: Literal["HEDGE_FUND", "LONG_ONLY", "QUANT", "PENSION", "FAMILY_OFFICE"]
    portfolio: list[tuple[str, float]]  # (ticker, weight)
    watchlist: list[str]  # tickers
    mandate: str
    benchmark: str
    impact_threshold: float

DEMO_CLIENTS = [
    DemoClient(
        name="Citadel APAC Long/Short",
        type="HEDGE_FUND",
        portfolio=[("9988.HK", 0.08), ("700.HK", 0.12), ("005930.KS", 0.10), ("7203.T", 0.07)],
        watchlist=["9618.HK", "6758.T", "D05.SI"],
        mandate="equity_long_short",
        benchmark="MSCI APAC",
        impact_threshold=60.0,
    ),
    DemoClient(
        name="Temasek Tech Growth",
        type="LONG_ONLY",
        portfolio=[("700.HK", 0.15), ("005930.KS", 0.12), ("9988.HK", 0.10), ("6758.T", 0.08)],
        watchlist=["1024.HK", "9984.T"],
        mandate="technology_growth",
        benchmark="MSCI APAC Tech",
        impact_threshold=50.0,
    ),
    DemoClient(
        name="Singapore Sovereign Wealth",
        type="PENSION",
        portfolio=[("CBA.AX", 0.06), ("D05.SI", 0.08), ("7203.T", 0.05), ("005930.KS", 0.04)],
        watchlist=["NAB.AX", "O39.SI"],
        mandate="conservative_growth",
        benchmark="MSCI APAC Low Vol",
        impact_threshold=70.0,
    ),
]
