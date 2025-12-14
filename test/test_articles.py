from dataclasses import dataclass, field
from typing import List

@dataclass
class ArticleDef:
    title: str
    content: str
    group_guid: str
    impact_score: float
    impact_tier: str
    event_type: str
    instruments: List[str] = field(default_factory=list)
    companies: List[str] = field(default_factory=list)

# 30 synthetic stories across 3 stocks (AAPL, MSFT, TSLA), 3 groups, 4 weeks, mixed event types
# Weeks: 2025-11-17, 2025-11-24, 2025-12-01, 2025-12-08
# Groups: A (Sales), B (Reuters), C (Alt Data)
# Event types: EARNINGS_BEAT, EARNINGS_MISS, GUIDANCE_RAISE, GUIDANCE_CUT, M&A_ANNOUNCE, M&A_RUMOR, DIVIDEND_CHANGE, INSIDER_TXN, PRODUCT_LAUNCH, MACRO_DATA
# Impact tiers: PLATINUM, GOLD, SILVER, BRONZE
# 10 per stock, spread over time and groups

def get_test_articles(TEST_GROUPS):
    return [
        # Week 1
        ArticleDef("AAPL: Q4 earnings beat, strong iPhone sales", "Apple reports Q4 earnings beat, driven by strong iPhone sales.", TEST_GROUPS["A"].guid, 90, "PLATINUM", "EARNINGS_BEAT", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Announces major buyback program", "Microsoft announces a $40B share buyback program.", TEST_GROUPS["B"].guid, 80, "GOLD", "BUYBACK", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: New Gigafactory opens in Berlin", "Tesla opens new Gigafactory in Berlin, expanding EU production.", TEST_GROUPS["C"].guid, 75, "GOLD", "PRODUCT_LAUNCH", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Insider transaction by CFO", "Apple CFO purchases $5M in AAPL shares.", TEST_GROUPS["A"].guid, 60, "SILVER", "INSIDER_TXN", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Dividend increase announced", "Microsoft increases quarterly dividend by 8%.", TEST_GROUPS["B"].guid, 65, "SILVER", "DIVIDEND_CHANGE", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Q4 production numbers miss estimates", "Tesla Q4 production falls short of analyst estimates.", TEST_GROUPS["C"].guid, 55, "BRONZE", "EARNINGS_MISS", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Guidance raised for FY2026", "Apple raises guidance for FY2026 on strong demand.", TEST_GROUPS["A"].guid, 70, "GOLD", "GUIDANCE_RAISE", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: M&A rumor - eyeing cybersecurity firm", "Rumors suggest Microsoft may acquire a leading cybersecurity company.", TEST_GROUPS["B"].guid, 60, "SILVER", "M&A_RUMOR", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Macro data - EV market share up", "EV market share in Europe rises, benefiting Tesla.", TEST_GROUPS["C"].guid, 50, "BRONZE", "MACRO_DATA", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Antitrust legal ruling in EU", "Apple faces antitrust ruling in the EU, fined $1B.", TEST_GROUPS["A"].guid, 85, "PLATINUM", "LEGAL_RULING", ["AAPL"], ["Apple Inc."]),

        # Week 2
        ArticleDef("MSFT: Q1 earnings miss, cloud growth slows", "Microsoft Q1 earnings miss as cloud growth slows.", TEST_GROUPS["B"].guid, 55, "BRONZE", "EARNINGS_MISS", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Announces new battery tech", "Tesla unveils new battery technology at investor day.", TEST_GROUPS["C"].guid, 80, "GOLD", "PRODUCT_LAUNCH", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Dividend unchanged", "Apple maintains current dividend for Q4.", TEST_GROUPS["A"].guid, 50, "BRONZE", "DIVIDEND_CHANGE", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Guidance cut for Q2", "Microsoft cuts guidance for Q2 due to FX headwinds.", TEST_GROUPS["B"].guid, 60, "SILVER", "GUIDANCE_CUT", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Insider sells $10M in shares", "Tesla executive sells $10M in TSLA shares.", TEST_GROUPS["C"].guid, 65, "SILVER", "INSIDER_TXN", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: M&A announcement - acquires AI startup", "Apple acquires AI startup to boost Siri.", TEST_GROUPS["A"].guid, 75, "GOLD", "M&A_ANNOUNCE", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Macro data - PC shipments down", "Global PC shipments decline, impacting Microsoft.", TEST_GROUPS["B"].guid, 50, "BRONZE", "MACRO_DATA", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Earnings beat, record deliveries", "Tesla beats earnings expectations with record deliveries.", TEST_GROUPS["C"].guid, 90, "PLATINUM", "EARNINGS_BEAT", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Product launch - new iPad", "Apple launches new iPad model.", TEST_GROUPS["A"].guid, 65, "SILVER", "PRODUCT_LAUNCH", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Legal ruling - patent dispute", "Microsoft wins patent dispute in US court.", TEST_GROUPS["B"].guid, 70, "GOLD", "LEGAL_RULING", ["MSFT"], ["Microsoft"]),

        # Week 3
        ArticleDef("TSLA: Guidance raised for FY2026", "Tesla raises guidance for FY2026 on strong demand.", TEST_GROUPS["C"].guid, 75, "GOLD", "GUIDANCE_RAISE", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Macro data - smartphone market share", "Smartphone market share data shows Apple gains.", TEST_GROUPS["A"].guid, 55, "BRONZE", "MACRO_DATA", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Insider transaction by CTO", "Microsoft CTO buys $2M in MSFT shares.", TEST_GROUPS["B"].guid, 60, "SILVER", "INSIDER_TXN", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: M&A rumor - battery supplier", "Rumors of Tesla acquiring battery supplier.", TEST_GROUPS["C"].guid, 60, "SILVER", "M&A_RUMOR", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Earnings warning for Q1", "Apple issues earnings warning for Q1.", TEST_GROUPS["A"].guid, 45, "BRONZE", "EARNINGS_WARNING", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Product launch - Teams update", "Microsoft launches major Teams update.", TEST_GROUPS["B"].guid, 65, "SILVER", "PRODUCT_LAUNCH", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Dividend change - initiates dividend", "Tesla initiates quarterly dividend.", TEST_GROUPS["C"].guid, 55, "BRONZE", "DIVIDEND_CHANGE", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Buyback announced", "Apple announces $20B share buyback.", TEST_GROUPS["A"].guid, 80, "GOLD", "BUYBACK", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Earnings beat, Azure growth", "Microsoft beats earnings on Azure growth.", TEST_GROUPS["B"].guid, 85, "PLATINUM", "EARNINGS_BEAT", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Legal ruling - autopilot case", "Tesla wins autopilot-related lawsuit.", TEST_GROUPS["C"].guid, 70, "GOLD", "LEGAL_RULING", ["TSLA"], ["Tesla"]),

        # Week 4
        ArticleDef("AAPL: Guidance cut for Q2", "Apple cuts guidance for Q2 due to supply chain.", TEST_GROUPS["A"].guid, 60, "SILVER", "GUIDANCE_CUT", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: M&A announcement - acquires gaming studio", "Microsoft acquires major gaming studio.", TEST_GROUPS["B"].guid, 90, "PLATINUM", "M&A_ANNOUNCE", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Macro data - China EV sales surge", "China EV sales surge, boosting Tesla outlook.", TEST_GROUPS["C"].guid, 80, "GOLD", "MACRO_DATA", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Insider transaction by CEO", "Apple CEO sells $10M in AAPL shares.", TEST_GROUPS["A"].guid, 55, "BRONZE", "INSIDER_TXN", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Product launch - Copilot AI", "Microsoft launches Copilot AI for Office.", TEST_GROUPS["B"].guid, 75, "GOLD", "PRODUCT_LAUNCH", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Earnings warning for Q2", "Tesla issues earnings warning for Q2.", TEST_GROUPS["C"].guid, 45, "BRONZE", "EARNINGS_WARNING", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: M&A rumor - AR/VR startup", "Rumors of Apple acquiring AR/VR startup.", TEST_GROUPS["A"].guid, 65, "SILVER", "M&A_RUMOR", ["AAPL"], ["Apple Inc."]),
        ArticleDef("MSFT: Dividend unchanged", "Microsoft maintains current dividend for Q4.", TEST_GROUPS["B"].guid, 50, "BRONZE", "DIVIDEND_CHANGE", ["MSFT"], ["Microsoft"]),
        ArticleDef("TSLA: Buyback announced", "Tesla announces $5B share buyback.", TEST_GROUPS["C"].guid, 60, "SILVER", "BUYBACK", ["TSLA"], ["Tesla"]),
        ArticleDef("AAPL: Earnings beat, record Mac sales", "Apple beats earnings with record Mac sales.", TEST_GROUPS["A"].guid, 85, "PLATINUM", "EARNINGS_BEAT", ["AAPL"], ["Apple Inc."]),
    ]
