# Graph Architecture for News Ranking & Client Matching

## Current Model

### Existing Node Types (6)

| Node | Purpose | Key Properties |
|------|---------|----------------|
| **Source** | News provider | guid, name, type, trust_level, region, languages |
| **Document** | Individual news story | guid, title, content, created_at, language, word_count |
| **Company** | Entity mentioned in stories | guid, name |
| **Sector** | Industry classification | guid, name |
| **Region** | Geographic area | guid, name |
| **Group** | Access control boundary | guid, name, tokens |

### Existing Relationship Types (4)

| Relationship | Pattern | Purpose |
|--------------|---------|---------|
| `PRODUCED_BY` | Document → Source | Story origin |
| `MENTIONS` | Document → Company | Entity extraction |
| `BELONGS_TO` | Company → Sector, Document → Region | Classification |
| `IN_GROUP` | Document → Group, Source → Group | Access control |

---

## Enhanced Model

### A. Document Impact Properties

Add ranking signals directly to Document node:

| Property | Type | Purpose |
|----------|------|---------|
| `impact_score` | float | Composite 0-100 score |
| `impact_tier` | enum | PLATINUM / GOLD / SILVER / BRONZE / STANDARD |
| `price_move_abs` | float | Absolute % move (beta-adjusted) |
| `volume_spike` | float | Volume / 20-day avg |
| `iv_jump` | float | Options implied vol change |
| `news_velocity` | int | Articles in first hour |
| `event_type` | string | EARNINGS / M&A / GUIDANCE / ACTIVIST / etc. |
| `decay_lambda` | float | Tier-specific decay rate |
| `relevance_at` | datetime | Time-decayed relevance timestamp |

### B. New Node Types (+10)

#### Client Domain

| Node | Purpose | Key Properties |
|------|---------|----------------|
| **ClientType** | Template/defaults for category | code, name, default_alert_frequency, default_impact_threshold, default_decay_lambda |
| **Client** | Specific firm (Citadel, BlackRock) | guid, name, override_alert_frequency, override_impact_threshold |
| **ClientProfile** | Client's preferences/constraints | mandate_type, benchmark, turnover_rate, esg_constrained, horizon |
| **Portfolio** | Client's holdings | guid, as_of_date |
| **Position** | Single holding | ticker, weight, shares, avg_cost |
| **Watchlist** | Stocks of interest | guid, name, alert_threshold |

#### Market Domain

| Node | Purpose | Key Properties |
|------|---------|----------------|
| **Instrument** | Tradeable security | guid, ticker, name, instrument_type, exchange, currency, country, isin, cusip, sedol, company_guid |
| **Index** | Benchmark index | guid, name, provider, constituents_count |
| **Factor** | Risk factor | guid, name (VALUE, MOMENTUM, QUALITY, SIZE, VOLATILITY) |
| **EventType** | Categorized news event | code, name, category, base_impact, default_tier, decay_lambda |

##### Instrument Types

| Type | Description | Examples |
|------|-------------|----------|
| `STOCK` | Common equity | AAPL, TSLA |
| `ADR` | American Depositary Receipt | BABA, TSM |
| `GDR` | Global Depositary Receipt | Gazprom GDR |
| `ETF` | Exchange-Traded Fund | SPY, QQQ |
| `ETN` | Exchange-Traded Note | VXX |
| `REIT` | Real Estate Investment Trust | SPG, AMT |
| `MLP` | Master Limited Partnership | EPD, ET |
| `SPAC` | Special Purpose Acquisition Co | Pre-merger SPACs |
| `CRYPTO` | Cryptocurrency | BTC, ETH |
| `CRYPTO_ETF` | Crypto ETF | BITO, GBTC |
| `INDEX` | Index (non-tradeable ref) | SPX, NDX |
| `PREFERRED` | Preferred stock | BAC-L |
| `WARRANT` | Warrant | Various |
| `RIGHT` | Rights offering | Various |

##### Event Types (Top 20)

| Code | Name | Category | Base Impact | Default Tier | Decay λ |
|------|------|----------|-------------|--------------|--------|
| `EARNINGS_BEAT` | Earnings Beat | Earnings | 70 | GOLD | 0.10 |
| `EARNINGS_MISS` | Earnings Miss | Earnings | 75 | GOLD | 0.10 |
| `EARNINGS_WARNING` | Earnings Warning/Preannouncement | Earnings | 85 | PLATINUM | 0.08 |
| `GUIDANCE_RAISE` | Guidance Raised | Guidance | 65 | GOLD | 0.12 |
| `GUIDANCE_CUT` | Guidance Cut | Guidance | 80 | PLATINUM | 0.08 |
| `M&A_ANNOUNCE` | M&A Announcement (Target) | Corporate Action | 95 | PLATINUM | 0.05 |
| `M&A_RUMOR` | M&A Rumor | Corporate Action | 60 | SILVER | 0.20 |
| `IPO` | Initial Public Offering | Corporate Action | 70 | GOLD | 0.10 |
| `SECONDARY` | Secondary Offering | Corporate Action | 55 | SILVER | 0.15 |
| `BUYBACK` | Share Buyback Announced | Corporate Action | 50 | SILVER | 0.15 |
| `DIVIDEND_CHANGE` | Dividend Initiation/Cut/Raise | Corporate Action | 60 | SILVER | 0.12 |
| `ACTIVIST` | Activist Stake Disclosed (13D) | Ownership | 80 | PLATINUM | 0.08 |
| `INSIDER_TXN` | Insider Transaction (>$1M) | Ownership | 45 | SILVER | 0.18 |
| `INDEX_ADD` | Index Addition | Index | 70 | GOLD | 0.10 |
| `INDEX_DELETE` | Index Deletion | Index | 70 | GOLD | 0.10 |
| `INDEX_REBAL` | Index Rebalance | Index | 50 | SILVER | 0.20 |
| `RATING_UPGRADE` | Analyst Upgrade (Top Tier) | Analyst | 55 | SILVER | 0.15 |
| `RATING_DOWNGRADE` | Analyst Downgrade (Top Tier) | Analyst | 55 | SILVER | 0.15 |
| `FDA_APPROVAL` | FDA/Regulatory Approval | Regulatory | 90 | PLATINUM | 0.06 |
| `FDA_REJECTION` | FDA/Regulatory Rejection | Regulatory | 90 | PLATINUM | 0.06 |
| `LEGAL_RULING` | Major Litigation Outcome | Legal | 75 | GOLD | 0.10 |
| `FRAUD_SCANDAL` | Fraud/Accounting Scandal | Legal | 95 | PLATINUM | 0.05 |
| `MGMT_CHANGE` | CEO/CFO Change | Management | 60 | SILVER | 0.12 |
| `PRODUCT_LAUNCH` | Major Product Launch | Business | 50 | SILVER | 0.18 |
| `CONTRACT_WIN` | Major Contract Win/Loss | Business | 55 | SILVER | 0.15 |
| `MACRO_DATA` | Macro Data Release (CPI, NFP) | Macro | 65 | GOLD | 0.25 |
| `CENTRAL_BANK` | Central Bank Decision | Macro | 80 | PLATINUM | 0.15 |
| `GEOPOLITICAL` | Geopolitical Event | Macro | 70 | GOLD | 0.20 |
| `POSITIVE_SENTIMENT` | General Positive News | Sentiment | 30 | BRONZE | 0.25 |
| `NEGATIVE_SENTIMENT` | General Negative News | Sentiment | 30 | BRONZE | 0.25 |

### C. New Relationship Types (+14)

#### Client Hierarchy

| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `IS_TYPE_OF` | Client → ClientType | - | Inherit defaults |
| `HAS_PROFILE` | Client → ClientProfile | - | Preferences |
| `HAS_PORTFOLIO` | Client → Portfolio | - | Holdings |
| `HAS_WATCHLIST` | Client → Watchlist | - | Interest list |

#### Document → Market

| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `AFFECTS` | Document → Instrument | direction, magnitude, confidence | Instrument impact |
| `TRIGGERED_BY` | Document → EventType | confidence, detected_at | Event classification |

#### Document → Client

| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `RELEVANT_TO` | Document → ClientProfile | score, reasons[] | **Core matching** |
| `DELIVERED_TO` | Document → Client | delivered_at, channel, opened | Audit trail |

#### Client → Market

| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `HOLDS` | Portfolio → Instrument | weight, shares, avg_cost | Current positions |
| `WATCHES` | Watchlist → Instrument | alert_threshold, added_at | Interest list |
| `BENCHMARKED_TO` | ClientProfile → Index | tracking_error_target | Mandate |
| `EXCLUDES` | ClientProfile → Company/Sector | reason (ESG, liquidity) | Constraints |
| `SUBSCRIBED_TO` | Client → Sector/Region/EventType | priority | Preferences |
| `EXPOSED_TO` | Portfolio → Factor | loading | Risk exposure |

#### Market Structure

| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `PEER_OF` | Company → Company | correlation | Peer read-through |
| `CONSTITUENT_OF` | Instrument → Index | weight, added_at | Index membership |
| `ISSUED_BY` | Instrument → Company | - | Instrument issuer |
| `TRACKS` | Instrument → Index/Instrument | tracking_error | ETF underlying |

---

## Permission Model

### Two-Tier Architecture

| Tier | Node Types | Permission Model |
|------|------------|------------------|
| **Global Reference Data** | Instrument, Index, Sector, Company, EventType, Factor, ClientType | No group restriction - shared taxonomy |
| **Permissioned Content** | Document, Source, Client, ClientProfile, Portfolio, Watchlist | Must have `IN_GROUP` - always filtered |

### Group as Permission Gate

```
┌─────────────────────────────────────────────────────────────┐
│                         GROUP                                │
│  (Permission Boundary - Token grants access to Group)        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌──────────┐     IN_GROUP      ┌──────────┐               │
│   │ Document │◄──────────────────│  Group   │               │
│   └────┬─────┘                   └────┬─────┘               │
│        │                              │                      │
│        │ RELEVANT_TO                  │ IN_GROUP             │
│        ▼                              ▼                      │
│   ┌──────────────┐              ┌──────────┐                │
│   │ClientProfile │◄─────────────│  Client  │                │
│   └──────────────┘  HAS_PROFILE └────┬─────┘                │
│                                      │                       │
│                                      │ IS_TYPE_OF            │
│                                      ▼                       │
│                                ┌────────────┐                │
│                                │ ClientType │  (Global)      │
│                                └────────────┘                │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              GLOBAL REFERENCE DATA (No Group)                │
│                                                              │
│ Instrument  Index  Sector  Company  EventType  Factor        │
│                                                              │
│   (Shared taxonomy - not permissioned, but content           │
│    ABOUT these entities IS permissioned via Document)        │
└─────────────────────────────────────────────────────────────┘
```

### Query Enforcement

Every query returning content MUST include Group filter:

```cypher
// CORRECT: Always filter by group
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.impact_tier = 'PLATINUM'
RETURN d

// Client must also be in permitted group
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
MATCH (d)-[r:RELEVANT_TO]->(cp:ClientProfile)
MATCH (cp)<-[:HAS_PROFILE]-(c:Client)-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups
RETURN d, c, r.score
```

---

## Complete Schema Definition

### Node Labels (16 total)

```python
class NodeLabel(str, Enum):
    # Existing (6)
    SOURCE = "Source"
    DOCUMENT = "Document"
    COMPANY = "Company"
    SECTOR = "Sector"
    REGION = "Region"
    GROUP = "Group"
    
    # Client Domain (6)
    CLIENT_TYPE = "ClientType"
    CLIENT = "Client"
    CLIENT_PROFILE = "ClientProfile"
    PORTFOLIO = "Portfolio"
    POSITION = "Position"
    WATCHLIST = "Watchlist"
    
    # Market Domain (4)
    INSTRUMENT = "Instrument"
    INDEX = "Index"
    FACTOR = "Factor"
    EVENT_TYPE = "EventType"
```

### Relationship Types (20 total)

```python
class RelationType(str, Enum):
    # Existing (4)
    PRODUCED_BY = "PRODUCED_BY"      # Document → Source
    MENTIONS = "MENTIONS"            # Document → Company
    BELONGS_TO = "BELONGS_TO"        # Company → Sector, Document → Region
    IN_GROUP = "IN_GROUP"            # Document, Source, Client → Group
    
    # Client Hierarchy (4)
    IS_TYPE_OF = "IS_TYPE_OF"        # Client → ClientType
    HAS_PROFILE = "HAS_PROFILE"      # Client → ClientProfile
    HAS_PORTFOLIO = "HAS_PORTFOLIO"  # Client → Portfolio
    HAS_WATCHLIST = "HAS_WATCHLIST"  # Client → Watchlist
    
    # Document → Market (2)
    AFFECTS = "AFFECTS"              # Document → Instrument
    TRIGGERED_BY = "TRIGGERED_BY"    # Document → EventType
    
    # Document → Client (2)
    RELEVANT_TO = "RELEVANT_TO"      # Document → ClientProfile
    DELIVERED_TO = "DELIVERED_TO"    # Document → Client
    
    # Client → Market (4)
    HOLDS = "HOLDS"                  # Portfolio → Instrument
    WATCHES = "WATCHES"              # Watchlist → Instrument
    BENCHMARKED_TO = "BENCHMARKED_TO"  # ClientProfile → Index
    EXCLUDES = "EXCLUDES"            # ClientProfile → Company/Sector
    SUBSCRIBED_TO = "SUBSCRIBED_TO"  # Client → Sector/Region/EventType
    EXPOSED_TO = "EXPOSED_TO"        # Portfolio → Factor
    
    # Market Structure (4)
    PEER_OF = "PEER_OF"              # Company → Company
    CONSTITUENT_OF = "CONSTITUENT_OF"  # Instrument → Index
    ISSUED_BY = "ISSUED_BY"          # Instrument → Company
    TRACKS = "TRACKS"                # Instrument → Index/Instrument (ETF underlying)
```

---

## Key Query Patterns

### 1. Score a Story for a Client

```cypher
MATCH (d:Document {guid: $doc_guid})-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
MATCH (d)-[:AFFECTS]->(inst:Instrument)
MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups
MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
MATCH (cp)-[:BENCHMARKED_TO]->(idx:Index)
OPTIONAL MATCH (inst)-[:CONSTITUENT_OF]->(idx)
OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(inst)
OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(inst)
RETURN d, inst,
       d.impact_score AS base_score,
       CASE WHEN h IS NOT NULL THEN h.weight * 100 ELSE 0 END AS position_boost,
       CASE WHEN w IS NOT NULL THEN 50 ELSE 0 END AS watchlist_boost,
       CASE WHEN (inst)-[:CONSTITUENT_OF]->(idx) THEN 30 ELSE 0 END AS benchmark_boost
```

### 2. Find Platinum Stories for Hedge Funds Today

```cypher
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.impact_tier = 'PLATINUM' 
  AND d.created_at > datetime() - duration('P1D')
MATCH (d)-[:RELEVANT_TO]->(cp:ClientProfile)
MATCH (cp)<-[:HAS_PROFILE]-(c:Client)-[:IS_TYPE_OF]->(ct:ClientType {code: 'HEDGE_FUND'})
MATCH (c)-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups
RETURN d, c, d.impact_score
ORDER BY d.impact_score DESC
```

### 3. Time-Decayed Relevance

```cypher
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
WITH d, d.impact_score * exp(-d.decay_lambda * 
     duration.between(d.created_at, datetime()).days) AS current_relevance
WHERE current_relevance > 10
RETURN d, current_relevance
ORDER BY current_relevance DESC
```

### 4. Client-Specific Feed with Exclusions

```cypher
MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups
MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)

// Get exclusions
OPTIONAL MATCH (cp)-[:EXCLUDES]->(excluded)

// Get documents that affect tickers in portfolio or watchlist
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.created_at > datetime() - duration('P1D')
MATCH (d)-[:AFFECTS]->(inst:Instrument)
WHERE (c)-[:HAS_PORTFOLIO]->(:Portfolio)-[:HOLDS]->(inst)
   OR (c)-[:HAS_WATCHLIST]->(:Watchlist)-[:WATCHES]->(inst)

// Exclude based on profile constraints
MATCH (inst)-[:ISSUED_BY]->(company:Company)
WHERE NOT company IN collect(excluded)

RETURN d, inst, d.impact_tier, d.impact_score
ORDER BY d.impact_score DESC
LIMIT 50
```

---

## Implementation Priority

| Phase | Scope | Enables |
|-------|-------|---------|
| **Phase 1** | Add impact properties to Document node | Basic ranking |
| **Phase 2** | Add EventType node + TRIGGERED_BY | Event categorization |
| **Phase 3** | Add Instrument node + AFFECTS + ISSUED_BY | Instrument-level tracking |
| **Phase 4** | Add ClientType, Client, ClientProfile + relationships | Client personalization |
| **Phase 5** | Add Portfolio, Watchlist + HOLDS, WATCHES | Position-aware ranking |

---

## Index Strategy

### Required Neo4j Indexes

```cypher
// Unique constraints
CREATE CONSTRAINT doc_guid IF NOT EXISTS FOR (d:Document) REQUIRE d.guid IS UNIQUE;
CREATE CONSTRAINT client_guid IF NOT EXISTS FOR (c:Client) REQUIRE c.guid IS UNIQUE;
CREATE CONSTRAINT instrument_guid IF NOT EXISTS FOR (i:Instrument) REQUIRE i.guid IS UNIQUE;
CREATE CONSTRAINT instrument_ticker IF NOT EXISTS FOR (i:Instrument) REQUIRE (i.ticker, i.exchange) IS UNIQUE;
CREATE CONSTRAINT group_guid IF NOT EXISTS FOR (g:Group) REQUIRE g.group_guid IS UNIQUE;

// Performance indexes
CREATE INDEX doc_impact IF NOT EXISTS FOR (d:Document) ON (d.impact_tier, d.created_at);
CREATE INDEX doc_created IF NOT EXISTS FOR (d:Document) ON (d.created_at);
CREATE INDEX client_type IF NOT EXISTS FOR (c:Client) ON (c.type);

// Full-text search
CREATE FULLTEXT INDEX doc_content IF NOT EXISTS FOR (d:Document) ON EACH [d.title, d.content];
```
