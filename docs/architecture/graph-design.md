# Graph Design - Neo4j Schema

The GOFR-IQ graph database stores entity relationships, enabling sophisticated ranking, client matching, and traversal queries.

---

## Node Types

### Core Nodes (6)

| Node | Description | Key Properties |
|------|-------------|-----------------|
| **Document** | News article | guid, title, language, created_at, word_count, impact_score, impact_tier, event_type, decay_lambda |
| **Source** | News provider | guid, name, type, region, trust_level, languages |
| **Company** | Entity mentioned | guid, name, ticker (optional), sector |
| **Sector** | Industry classification | guid, name (e.g., "technology", "healthcare") |
| **Region** | Geographic area | guid, name (e.g., "APAC", "North America") |
| **Group** | Access control boundary | guid, name |

### Market Nodes (4)

| Node | Description | Key Properties |
|------|-------------|-----------------|
| **Instrument** | Tradeable security | guid, ticker, name, instrument_type (STOCK/ETF/ADR/etc.), exchange, currency, isin, cusip, sedol |
| **Index** | Benchmark index | guid, name, provider (e.g., "S&P500"), constituents_count |
| **EventType** | News event category | code (EARNINGS_BEAT), name, category, base_impact (0-100), default_tier, decay_lambda |
| **Factor** | Risk factor | guid, name (VALUE, MOMENTUM, QUALITY, SIZE, VOLATILITY) |

### Client Nodes (6)

| Node | Description | Key Properties |
|------|-------------|-----------------|
| **ClientType** | Client category template | code (HEDGE_FUND, ASSET_MANAGER), name, default_alert_frequency, default_impact_threshold |
| **Client** | Specific firm | guid, name (e.g., "Citadel"), override_alert_frequency |
| **ClientProfile** | Client preferences | mandate_type, benchmark, turnover_rate, esg_constrained, investment_horizon |
| **Portfolio** | Client holdings | guid, as_of_date, total_value |
| **Position** | Single holding | ticker, weight (%), shares, avg_cost |
| **Watchlist** | Interest tracking | guid, name, alert_threshold, created_at |

---

## Relationship Types

### Existing Relationships (4)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `PRODUCED_BY` | Document → Source | - | Document origin |
| `MENTIONS` | Document → Company | confidence | Entity extraction |
| `BELONGS_TO` | Company → Sector<br>Document → Region | - | Classification |
| `IN_GROUP` | Document → Group<br>Source → Group<br>Client → Group | - | Access control (**critical**) |

### Document-Market Relationships (2)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `AFFECTS` | Document → Instrument | direction (UP/DOWN/NEUTRAL), magnitude (0-1), confidence (0-1) | Document impact on instrument |
| `TRIGGERED_BY` | Document → EventType | confidence (0-1), detected_at | Event classification |

### Document-Client Relationships (2)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `RELEVANT_TO` | Document → ClientProfile | score (0-100), reasons (list) | Why document matters |
| `DELIVERED_TO` | Document → Client | delivered_at, channel, opened_at, read_at | Audit trail |

### Client Hierarchy Relationships (4)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `IS_TYPE_OF` | Client → ClientType | - | Inherit defaults |
| `HAS_PROFILE` | Client → ClientProfile | - | Preferences |
| `HAS_PORTFOLIO` | Client → Portfolio | - | Holdings |
| `HAS_WATCHLIST` | Client → Watchlist | - | Interest list |

### Client-Market Relationships (6)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `HOLDS` | Portfolio → Instrument | weight (%), shares, avg_cost, current_price | Current positions |
| `WATCHES` | Watchlist → Instrument | alert_threshold, added_at | Interest list |
| `BENCHMARKED_TO` | ClientProfile → Index | tracking_error_target (%) | Mandate |
| `EXCLUDES` | ClientProfile → Company/Sector | reason (ESG/LIQUIDITY/etc.) | Constraints |
| `SUBSCRIBED_TO` | Client → Sector/Region/EventType | priority (0-100) | Alert preferences |
| `EXPOSED_TO` | Portfolio → Factor | loading (0-1) | Risk exposure |

### Market Structure Relationships (4)

| Type | Pattern | Properties | Purpose |
|------|---------|-----------|---------|
| `ISSUED_BY` | Instrument → Company | - | Instrument issuer |
| `CONSTITUENT_OF` | Instrument → Index | weight (%), added_at | Index membership |
| `PEER_OF` | Company → Company | correlation (0-1) | Peer relationships |
| `TRACKS` | Instrument → Index/Instrument | tracking_error (%) | ETF underlying |

---

## Instrument Types

| Code | Name | Examples |
|------|------|----------|
| `STOCK` | Common equity | AAPL, TSLA, 0700.HK |
| `ADR` | American Depositary Receipt | BABA, TSM |
| `GDR` | Global Depositary Receipt | Gazprom GDR |
| `ETF` | Exchange-Traded Fund | SPY, QQQ, EWH |
| `ETN` | Exchange-Traded Note | VXX, UVXY |
| `REIT` | Real Estate Investment Trust | SPG, AMT |
| `MLP` | Master Limited Partnership | EPD, ET |
| `SPAC` | Special Purpose Acquisition | Pre-merger SPACs |
| `CRYPTO` | Cryptocurrency | BTC, ETH |
| `CRYPTO_ETF` | Crypto ETF | BITO, GBTC |
| `INDEX` | Index (non-tradeable) | SPX, NDX, HSI |
| `PREFERRED` | Preferred stock | BAC-L, ALLY-PR |

---

## Event Type Catalog (30 Types)

### Earnings Events (3)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `EARNINGS_BEAT` | Beat expectations | 70 | GOLD | 0.10 |
| `EARNINGS_MISS` | Miss expectations | 75 | GOLD | 0.10 |
| `EARNINGS_WARNING` | Warning/preannouncement | 85 | PLATINUM | 0.08 |

### Guidance Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `GUIDANCE_RAISE` | Guidance raised | 65 | GOLD | 0.12 |
| `GUIDANCE_CUT` | Guidance cut | 80 | PLATINUM | 0.08 |

### Corporate Actions (6)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `M&A_ANNOUNCE` | M&A announcement | 95 | PLATINUM | 0.05 |
| `M&A_RUMOR` | M&A rumor | 60 | SILVER | 0.20 |
| `IPO` | IPO launch | 70 | GOLD | 0.10 |
| `SECONDARY` | Secondary offering | 55 | SILVER | 0.15 |
| `BUYBACK` | Buyback announced | 50 | SILVER | 0.15 |
| `DIVIDEND_CHANGE` | Dividend change | 60 | SILVER | 0.12 |

### Ownership Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `ACTIVIST` | 13D activist stake | 80 | PLATINUM | 0.08 |
| `INSIDER_TXN` | Insider transaction >$1M | 45 | SILVER | 0.18 |

### Index Events (3)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `INDEX_ADD` | Index addition | 70 | GOLD | 0.10 |
| `INDEX_DELETE` | Index deletion | 70 | GOLD | 0.10 |
| `INDEX_REBAL` | Index rebalance | 50 | SILVER | 0.20 |

### Analyst Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `RATING_UPGRADE` | Analyst upgrade | 55 | SILVER | 0.15 |
| `RATING_DOWNGRADE` | Analyst downgrade | 55 | SILVER | 0.15 |

### Regulatory Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `FDA_APPROVAL` | FDA approval | 90 | PLATINUM | 0.06 |
| `FDA_REJECTION` | FDA rejection | 90 | PLATINUM | 0.06 |

### Legal Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `LEGAL_RULING` | Litigation outcome | 75 | GOLD | 0.10 |
| `FRAUD_SCANDAL` | Fraud/scandal | 95 | PLATINUM | 0.05 |

### Management Events (1)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `MGMT_CHANGE` | CEO/CFO change | 60 | SILVER | 0.12 |

### Business Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `PRODUCT_LAUNCH` | Product launch | 50 | SILVER | 0.18 |
| `CONTRACT_WIN` | Contract win/loss | 55 | SILVER | 0.15 |

### Macro Events (3)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `MACRO_DATA` | CPI, NFP, etc. | 65 | GOLD | 0.25 |
| `CENTRAL_BANK` | Fed decision | 80 | PLATINUM | 0.15 |
| `GEOPOLITICAL` | Geopolitical event | 70 | GOLD | 0.20 |

### Sentiment Events (2)

| Code | Name | Base Impact | Default Tier | Decay λ |
|------|------|------------|---------------|---------​|
| `POSITIVE_SENTIMENT` | Positive news | 30 | BRONZE | 0.25 |
| `NEGATIVE_SENTIMENT` | Negative news | 30 | BRONZE | 0.25 |

---

## Access Control Model

### Group-Based Permission Architecture

```
User Token → Groups: ["apac-research", "japan-desk"]
                        │
                        └──→ Can only see Documents/Sources/Clients IN these groups
                        
All permissioned nodes must have:
  (Document)-[:IN_GROUP]->(Group)
  (Source)-[:IN_GROUP]->(Group)
  (Client)-[:IN_GROUP]->(Group)
```

### Query Enforcement Pattern

**ALWAYS include group filter** for permissioned content:

```cypher
// CORRECT: Always filter by group
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.impact_tier = 'PLATINUM'
RETURN d

// WRONG: Missing group filter - NEVER do this
MATCH (d:Document)
WHERE d.impact_tier = 'PLATINUM'
RETURN d
```

### Reference Data (No Group Filter)

These nodes are **global taxonomy** - never filtered:
- Instrument (shared security master)
- Index (shared benchmark data)
- EventType (shared event catalog)
- Factor (shared risk factors)
- Sector (shared sector taxonomy)
- Region (shared region taxonomy)

---

## Key Query Patterns

### Pattern 1: Score a Document for a Client

```cypher
// Given document, client, calculate relevance score
MATCH (d:Document {guid: $doc_guid})-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups

MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups

MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)

// Affected instruments
MATCH (d)-[:AFFECTS]->(inst:Instrument)

// Position boost (if in portfolio)
OPTIONAL MATCH (p)-[h:HOLDS]->(inst)
WITH d, inst, cp, p, h, 
     COALESCE(h.weight, 0) * 100 AS position_boost

// Watchlist boost (if on watchlist)
OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(inst)
WITH d, inst, cp, p, position_boost,
     CASE WHEN w IS NOT NULL THEN 50 ELSE 0 END AS watchlist_boost

// Index boost (if in benchmark)
OPTIONAL MATCH (cp)-[:BENCHMARKED_TO]->(idx:Index)
OPTIONAL MATCH (inst)-[:CONSTITUENT_OF]->(idx)
WITH d, cp, position_boost, watchlist_boost,
     CASE WHEN (inst)-[:CONSTITUENT_OF]->(idx) THEN 30 ELSE 0 END AS benchmark_boost

// Final score
RETURN d.guid, 
       d.impact_score AS base_score,
       position_boost + watchlist_boost + benchmark_boost AS matching_boost,
       d.impact_score + position_boost + watchlist_boost + benchmark_boost AS total_score
```

### Pattern 2: Find Platinum Documents for Hedge Funds

```cypher
// Get all PLATINUM docs relevant to hedge funds in permitted groups
MATCH (ct:ClientType {code: 'HEDGE_FUND'})
MATCH (c:Client)-[:IS_TYPE_OF]->(ct)
MATCH (c)-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups

MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
MATCH (d:Document)-[:RELEVANT_TO]->(cp)
MATCH (d)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.impact_tier = 'PLATINUM'
  AND d.created_at > datetime() - duration('P1D')

RETURN d, c, d.impact_score
ORDER BY d.impact_score DESC
```

### Pattern 3: Time-Decayed Relevance

```cypher
// Calculate current relevance with time decay
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups

// Current relevance = base_score * decay
WITH d,
     d.impact_score * exp(
       -1.0 * d.decay_lambda * 
       duration.between(d.created_at, datetime()).days
     ) AS current_relevance

WHERE current_relevance > 10
RETURN d, current_relevance
ORDER BY current_relevance DESC
LIMIT 50
```

### Pattern 4: Client-Specific Feed

```cypher
// Get documents affecting client's portfolio, respecting exclusions
MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups

MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
OPTIONAL MATCH (cp)-[:EXCLUDES]->(excluded)

// Documents affecting portfolio/watchlist
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.created_at > datetime() - duration('P1D')

MATCH (d)-[:AFFECTS]->(inst:Instrument)
WHERE (c)-[:HAS_PORTFOLIO]->(:Portfolio)-[:HOLDS]->(inst)
   OR (c)-[:HAS_WATCHLIST]->(:Watchlist)-[:WATCHES]->(inst)

// Verify not excluded
MATCH (inst)-[:ISSUED_BY]->(company:Company)
WHERE NOT company IN collect(excluded)

RETURN d, inst, d.impact_tier, d.impact_score, d.created_at
ORDER BY d.impact_score DESC
LIMIT 50
```

### Pattern 5: Related Documents (Graph Expansion)

```cypher
// Find documents with shared context
MATCH (d1:Document {guid: $doc_guid})-[:AFFECTS]->(inst1:Instrument)
MATCH (d2:Document)-[:AFFECTS]->(inst1)
WHERE d1.guid <> d2.guid
  AND d1.created_at > datetime() - duration('P7D')
  AND d2.created_at > datetime() - duration('P7D')

MATCH (d2)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups

RETURN d2, inst1, "shared_instrument" AS relationship
UNION
// Documents on same company
MATCH (d1:Document {guid: $doc_guid})-[:MENTIONS]->(co:Company)
MATCH (d2:Document)-[:MENTIONS]->(co)
WHERE d1.guid <> d2.guid

MATCH (d2)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups

RETURN d2, co, "shared_company" AS relationship
ORDER BY d2.created_at DESC
LIMIT 20
```

---

## Neo4j Indexes

### Unique Constraints

```cypher
// These enforce uniqueness across entire database
CREATE CONSTRAINT doc_guid IF NOT EXISTS 
FOR (d:Document) REQUIRE d.guid IS UNIQUE;

CREATE CONSTRAINT client_guid IF NOT EXISTS 
FOR (c:Client) REQUIRE c.guid IS UNIQUE;

CREATE CONSTRAINT instrument_guid IF NOT EXISTS 
FOR (i:Instrument) REQUIRE i.guid IS UNIQUE;

CREATE CONSTRAINT source_guid IF NOT EXISTS 
FOR (s:Source) REQUIRE s.guid IS UNIQUE;

CREATE CONSTRAINT group_guid IF NOT EXISTS 
FOR (g:Group) REQUIRE g.group_guid IS UNIQUE;
```

### Performance Indexes

```cypher
// Queries filtering by impact and date
CREATE INDEX doc_impact IF NOT EXISTS 
FOR (d:Document) ON (d.impact_tier, d.created_at);

CREATE INDEX doc_created IF NOT EXISTS 
FOR (d:Document) ON (d.created_at);

CREATE INDEX doc_event IF NOT EXISTS 
FOR (d:Document) ON (d.event_type);

// Client type lookups
CREATE INDEX client_type IF NOT EXISTS 
FOR (c:Client) ON (c.type);

// Instrument ticker lookups
CREATE INDEX inst_ticker IF NOT EXISTS 
FOR (i:Instrument) ON (i.ticker, i.exchange);
```

### Full-Text Search

```cypher
// Search documents by title/content
CREATE FULLTEXT INDEX doc_content IF NOT EXISTS 
FOR (d:Document) ON EACH [d.title, d.content];

// Search companies by name
CREATE FULLTEXT INDEX company_search IF NOT EXISTS 
FOR (c:Company) ON EACH [c.name];
```

---

## Implementation Phases

| Phase | New Nodes | New Relationships | Enables |
|-------|-----------|------------------|---------|
| **1** | - | - | Current: Doc, Source, Company, Sector, Region, Group |
| **2** | EventType | TRIGGERED_BY | Event categorization |
| **3** | Instrument, Index | AFFECTS, ISSUED_BY, CONSTITUENT_OF | Instrument-level tracking |
| **4** | ClientType, Client, ClientProfile | IS_TYPE_OF, HAS_PROFILE, RELEVANT_TO | Client personalization |
| **5** | Portfolio, Watchlist, Position | HAS_PORTFOLIO, HAS_WATCHLIST, HOLDS, WATCHES | Position-aware ranking |

---

## Performance Considerations

### Graph Traversal Cost

| Query Pattern | Edges Traversed | Typical Time | Notes |
|---------------|-----------------|--------------|-------|
| Single document lookup | 0 | <1ms | Direct node access |
| Document + source | 1 | 1-2ms | Single relationship |
| Document + impacts + matching | 5-10 | 10-50ms | Multi-hop traversal |
| Client feed (50 results) | 100-500 | 500-2000ms | Aggregate of above |

### Scale Limits

| Measure | Limit | Scaling Strategy |
|---------|-------|------------------|
| Documents per group | 10M | Date partitioning, archiving |
| Client positions per portfolio | 10K | Cached materialization |
| Graph traversal depth | 3-4 hops | Materialized views for common queries |

---

## Related Documentation

- [Architecture Overview](overview.md)
- [Hybrid Search](../features/hybrid-search.md)
- [Document Ingestion](../features/document-ingestion.md)
- [Configuration Reference](../getting-started/configuration.md)
