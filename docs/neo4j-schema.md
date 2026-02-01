# Neo4j Graph Schema - GOFR-IQ

## Overview
This document defines the **actual implemented schema** for the GOFR-IQ Neo4j graph database based on code analysis of `graph_index.py`.

## Node Types (Labels)

### Content Domain
| Label | GUID/Key | Properties | Description | Created By |
|-------|----------|------------|-------------|------------|
| **Document** | UUID | guid, title, language, source_guid, group_guid, created_at, impact_score, impact_tier, decay_lambda, meta_* | News articles and content | `create_document_node()` |
| **Source** | UUID | guid, name, type, trust_level, region?, languages? | Content providers | `create_source()` |

**Note on Document Properties:**
- ✅ **Stored**: guid, title, language, source_guid, group_guid, created_at, impact_score, impact_tier, decay_lambda, meta_*
- ❌ **NOT stored**: content (stored in ChromaDB/filesystem), event_type (use TRIGGERED_BY relationship instead)

### Market Domain
| Label | GUID/Key | Properties | Description | Created By |
|-------|----------|------------|-------------|------------|
| **Instrument** | `{ticker}:{exchange}` | ticker, name, instrument_type, exchange, currency, country?, isin? | Tradeable securities | `create_instrument()` |
| **Company** | ticker | ticker, name, sector? | Issuing companies | `add_company_mention()` (implicit) |
| **Sector** | code | code, name | Industry classifications | Not auto-created |
| **Region** | code | code, name | Geographic regions | Not auto-created |
| **Index** | code/ticker | code/ticker, name | Market indices | Not auto-created |
| **Factor** | factor_id | factor_id, name | Risk/style factors | Not auto-created |
| **EventType** | code | code, name, category, base_impact, default_tier, decay_lambda | Event classifications | `create_event_type()` |

**Note on Company Nodes:**
- Company nodes use **ticker as guid** (not UUID)
- Created implicitly via `add_company_mention()` in document ingestion
- Properties: ticker, name (optional)
- NO `create_company()` method exists

### Client Domain
| Label | GUID/Key | Properties | Description | Created By |
|-------|----------|------------|-------------|------------|
| **ClientType** | code | code, name, default_alert_frequency, default_impact_threshold, default_decay_lambda | Client templates | `create_client_type()` |
| **Client** | UUID | guid, name, + custom properties | Investment clients | `create_client()` |
| **ClientProfile** | UUID | guid, mandate_type?, benchmark_guid?, turnover_rate?, esg_constrained, horizon? | Client investment constraints | `create_client_profile()` |
| **Portfolio** | UUID | guid, as_of_date? | Holdings container | `create_portfolio()` |
| **Watchlist** | UUID | guid, name, alert_threshold | Watch items container | `create_watchlist()` |
| **Position** | UUID | guid | Portfolio position details | Not auto-created |

### Access Control Domain
| Label | GUID/Key | Properties | Description | Created By |
|-------|----------|------------|-------------|------------|
| **Group** | UUID | guid, name, description? | Access control groups | `create_group()` |

## Relationship Types

### Content Relationships
| Relationship | Pattern | Properties | Description | Created By |
|--------------|---------|------------|-------------|------------|
| **PRODUCED_BY** | Document → Source | - | Document authorship | `create_document_node()` |
| **MENTIONS** | Document → Company | - | Company references in document | `add_company_mention()` |
| **IN_GROUP** | Document/Source/Client → Group | - | Access control membership | Multiple create methods |

### Document → Market Relationships
| Relationship | Pattern | Properties | Description | Created By |
|--------------|---------|------------|-------------|------------|
| **AFFECTS** | Document → Instrument | direction, magnitude, confidence | Price impact prediction | `add_document_affects()` |
| **TRIGGERED_BY** | Document → EventType | confidence? | Event classification | `set_document_impact()` |

**Note:** Use `TRIGGERED_BY` relationship to get event_type, not a document property.

### Market Structure Relationships
| Relationship | Pattern | Properties | Description | Created By |
|--------------|---------|------------|-------------|------------|
| **ISSUED_BY** | Instrument → Company | - | Security issuer | `create_instrument()` |
| **BELONGS_TO** | Company → Sector | - | Industry classification | Not auto-created |
| **CONSTITUENT_OF** | Instrument → Index | weight? | Index membership | Not auto-created |
| **TRACKS** | Instrument → Index/Instrument | - | ETF underlying | Not auto-created |

**⚠️ NOT IMPLEMENTED:**
- `PEER_OF` (Company ↔ Company) - defined but never created
- `IN_SECTOR` (Instrument → Sector) - doesn't exist in schema
- `EXPOSED_TO` (Portfolio → Factor) - defined but not created

### Client Hierarchy Relationships
| Relationship | Pattern | Properties | Description | Created By |
|--------------|---------|------------|-------------|------------|
| **IS_TYPE_OF** | Client → ClientType | - | Client template reference | `create_client()` |
| **HAS_PROFILE** | Client → ClientProfile | - | Investment constraints | `create_client_profile()` |
| **HAS_PORTFOLIO** | Client → Portfolio | - | Holdings link | `create_portfolio()` |
| **HAS_WATCHLIST** | Client → Watchlist | - | Watch items link | `create_watchlist()` |

### Client → Market Relationships
| Relationship | Pattern | Properties | Description | Created By |
|--------------|---------|------------|-------------|------------|
| **HOLDS** | Portfolio → Instrument | weight, shares?, avg_cost? | Portfolio positions | `add_holding()` |
| **WATCHES** | Watchlist → Instrument | alert_threshold?, added_at | Watch list items | `add_to_watchlist()` |
| **BENCHMARKED_TO** | ClientProfile → Index | tracking_error_target? | Mandate benchmark | `create_client_profile()` |
| **EXCLUDES** | ClientProfile → Company/Sector | reason? | ESG/liquidity constraints | Not auto-created |
| **SUBSCRIBED_TO** | Client → Sector/Region/EventType | priority? | Alert preferences | Not auto-created |

## Instrument Types
```
STOCK | ADR | GDR | ETF | ETN | REIT | MLP | SPAC | 
CRYPTO | CRYPTO_ETF | INDEX | PREFERRED | WARRANT | RIGHT
```

## Impact Tiers
```
PLATINUM  (90-100) - Market moving (top 1%)
GOLD      (75-89)  - High impact (next 2%)
SILVER    (50-74)  - Notable (next 10%)
BRONZE    (25-49)  - Moderate (next 20%)
STANDARD  (0-24)   - Routine (bottom 67%)
```

## Event Categories
```
Earnings | Guidance | Corporate Action | Ownership | Index | Analyst |
Regulatory | Legal | Management | Business | Macro | Sentiment
```

## Schema Constraints (from `init_schema()`)

### Uniqueness Constraints
- All node types: `guid IS UNIQUE`
- Instrument: `ticker IS UNIQUE`
- Company: `ticker IS UNIQUE`
- Factor: `factor_id IS UNIQUE`
- Sector: `code IS UNIQUE`
- Region: `code IS UNIQUE`
- EventType: `code IS UNIQUE`
- ClientType: `code IS UNIQUE`
- Index: `ticker IS UNIQUE`
- Source: `guid IS UNIQUE`

### Performance Indexes
- Document: `created_at`
- Document: `language`
- Document: `impact_score`
- Document: full-text search on title (name: `document_fulltext`)

## Common Query Patterns

### Get Document with Event Type
```cypher
MATCH (d:Document {guid: $guid})
OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(e:EventType)
RETURN d.guid, d.title, d.impact_score, d.impact_tier, e.code AS event_type
```

### Find Peer Instruments (via Sector)
```cypher
MATCH (i1:Instrument {ticker: $ticker})-[:ISSUED_BY]->(c1:Company)-[:BELONGS_TO]->(s:Sector)
MATCH (i2:Instrument)-[:ISSUED_BY]->(c2:Company)-[:BELONGS_TO]->(s)
WHERE i1.ticker <> i2.ticker
RETURN DISTINCT i2.ticker
LIMIT 5
```

### Get Documents Affecting Instrument
```cypher
MATCH (d:Document)-[:AFFECTS]->(i:Instrument {ticker: $ticker})
MATCH (d)-[:IN_GROUP]->(g:Group)
WHERE g.guid IN $group_guids
OPTIONAL MATCH (d)-[:PRODUCED_BY]->(s:Source)
OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(e:EventType)
RETURN d.guid, d.title, d.created_at, d.language,
       d.impact_score, d.impact_tier,
       e.code AS event_type,
       s.guid AS source_guid, s.name AS source_name
ORDER BY d.created_at DESC
```

### Get Client Portfolio
```cypher
MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
MATCH (p)-[h:HOLDS]->(i:Instrument)
RETURN i.ticker, i.name, h.weight, h.shares, h.avg_cost
ORDER BY h.weight DESC
```

## Known Limitations

### Not Auto-Created During Ingestion
These node types exist in schema but are NOT created during document ingestion:
- **Sector** nodes (only referenced in Company → Sector relationship)
- **Region** nodes (only referenced in filters)
- **Index** nodes (only referenced in benchmarks)
- **Factor** nodes (only referenced in risk models)

### Relationships Never Created
These relationships are defined but never created by existing code:
- **PEER_OF** (Company ↔ Company) - no bootstrap or ingestion code
- **CONSTITUENT_OF** (Instrument → Index) - no bootstrap or ingestion code
- **BELONGS_TO** (Company → Sector) - no ingestion code
- **EXCLUDES** (ClientProfile → Company/Sector) - no client setup code
- **SUBSCRIBED_TO** (Client → Sector/Region/EventType) - no client setup code
- **TRACKS** (Instrument → Index) - no ETF tracking code
- **EXPOSED_TO** (Portfolio → Factor) - no risk attribution code

### Properties That Don't Exist
- **Document.content** - stored in ChromaDB/filesystem, not Neo4j
- **Document.event_type** - use TRIGGERED_BY relationship to EventType node instead

## Workarounds

### Finding Peer Instruments
Since PEER_OF doesn't exist, traverse via sector:
```cypher
// Instead of: (i1)-[:PEER_OF]-(i2)
// Use:
(i1)-[:ISSUED_BY]->(c1)-[:BELONGS_TO]->(s:Sector)
<-[:BELONGS_TO]-(c2)<-[:ISSUED_BY]-(i2)
```

### Getting Event Type
Since Document.event_type doesn't exist, follow relationship:
```cypher
// Instead of: d.event_type
// Use:
OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(e:EventType)
RETURN e.code AS event_type
```

### Getting Document Content
Since Document.content doesn't exist in Neo4j:
1. Query Neo4j for document guid
2. Fetch content from ChromaDB or filesystem using guid
3. Don't try to return d.content in Cypher queries
