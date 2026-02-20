# GOFR-IQ MCP Tool Interface (Concise)

## How to Call
- Base URL: http://gofr-iq:8080
- Endpoint pattern: POST /tools/{tool_name} with JSON body
- Auth: Authorization: Bearer <token> (preferred) or body field auth_tokens: ["<token>"]
- Response envelope (success): {status: "success", data: {...}, message: "..."}
- Response envelope (error): {status: "error", error_code, message, recovery_strategy?, details?}
- Streaming: Standard HTTP responses; safe to use fetch() with ReadableStream if you want progressive rendering.

## Shared Types
- UUID: 36-char lowercase with hyphens (e.g., 550e8400-e29b-41d4-a716-446655440000)
- Ticker: AAPL, 9988.HK, 700.HK
- Impact score: 0–100; tiers: PLATINUM, GOLD, SILVER, BRONZE, STANDARD
- Admin-only tools: create_source, update_source, delete_source, delete_document

## Tools (26)

### Client Management
- create_client(name, client_type, alert_frequency, impact_threshold, mandate_type?, benchmark?, horizon?, esg_constrained?) -> {guid, portfolio_guid, watchlist_guid}
- list_clients(client_type?, limit?) -> {clients:[{guid,name,client_type,portfolio_guid,watchlist_guid}]}
- get_client_profile(client_guid) -> {name, client_type, alert_frequency, impact_threshold, mandate_type, benchmark, ...}
- update_client_profile(client_guid, alert_frequency?, impact_threshold?, mandate_type?, benchmark?) -> {updated_fields,...}
- get_client_feed(client_guid, limit?, min_impact_score?, impact_tiers?, include_portfolio?, include_watchlist?) -> {articles:[...]}
- get_top_client_news(client_guid, limit?, time_window_hours?, min_impact_score?, impact_tiers?, include_portfolio?, include_watchlist?, include_lateral_graph?) -> {articles:[... (each includes why_it_matters_base)], ...}
- why_it_matters_to_client(client_guid, document_guid) -> {why_it_matters (<=30 words), story_summary (<=30 words)}

### Portfolio
- add_to_portfolio(client_guid, ticker, weight, shares?, avg_cost?) -> {ticker, weight, shares}
- get_portfolio_holdings(client_guid) -> {holdings:[{ticker, weight, shares, avg_cost}]}
- remove_from_portfolio(client_guid, ticker) -> {ticker, message}

### Watchlist
- add_to_watchlist(client_guid, ticker, alert_threshold?) -> {ticker, alert_threshold}
- get_watchlist_items(client_guid) -> {watchlist:[{ticker, alert_threshold}]}
- remove_from_watchlist(client_guid, ticker) -> {ticker, message}

### Documents
- ingest_document(title, content, source_guid, language?, metadata?) -> {guid, group_guid, language, embedding_generated}
- validate_document(title, content, source_guid, language?) -> {is_duplicate, duplicate_guid?, similarity?}
- get_document(guid, date_hint?) -> {guid, title, content, source_guid, language, created_at, metadata, ...}
- delete_document(document_guid, group_guid, confirm, date_hint?) -> {message}
- query_documents(query, n_results?, regions?, sectors?, companies?, languages?, date_from?, date_to?) -> {documents:[...]}

### Sources
- list_sources(region?, source_type?, active_only?) -> {sources:[{guid, name, source_type, region, languages, trust_level}]}
- get_source(source_guid) -> {guid, name, source_type, region, languages, trust_level, active, ...}
- create_source(name, source_type, region?, languages?, trust_level) -> {guid, name, trust_level}
- update_source(source_guid, name?, source_type?, region?, languages?, trust_level?) -> {message}
- delete_source(source_guid) -> {message}

### Knowledge Graph
- explore_graph(node_type, node_id, relationship_types?, max_depth?, limit?) -> {start_node, relationships:[...], total_found}
- get_market_context(ticker, include_peers?, include_events?, include_indices?, days_back?) -> {instrument, company, sector, peers, events, indices}
- get_instrument_news(ticker, days_back?, min_impact_score?, limit?) -> {ticker, articles:[...], total_found}

### Health
- health_check() -> {status, neo4j, chromadb, llm}

---

## Neo4j Graph Schema Reference

### Node Types (Labels)
| Label | GUID Format | Key Properties | Description |
|-------|-------------|----------------|-------------|
| `Instrument` | `TICKER:EXCHANGE` (e.g., `AAPL:NYSE`) | ticker, name, instrument_type, exchange, currency | Tradeable securities |
| `Company` | ticker (e.g., `AAPL`) | ticker, name, sector | Issuing companies |
| `Document` | UUID | guid, title, content, impact_score, impact_tier, created_at | News/articles |
| `Source` | UUID | name, type, trust_level | News sources |
| `Client` | UUID | name, alert_frequency, impact_threshold | Investment clients |
| `ClientType` | code (e.g., `HEDGE_FUND`) | code, name, default_alert_frequency | Client templates |
| `Portfolio` | UUID | name | Client holdings container |
| `Watchlist` | UUID | name | Client watch items |
| `Sector` | code/guid | name, code | Industry classification |
| `Region` | guid | name, code | Geographic regions |
| `EventType` | code (e.g., `EARNINGS_BEAT`) | code, name, category, base_impact | Event categories |
| `Index` | code (e.g., `SPY`) | name, code | Market indices |
| `Group` | UUID | guid, name | Access control groups |

### Instrument Types
`STOCK` | `ADR` | `GDR` | `ETF` | `ETN` | `REIT` | `MLP` | `SPAC` | `CRYPTO` | `CRYPTO_ETF` | `INDEX` | `PREFERRED` | `WARRANT` | `RIGHT`

### Impact Tiers
| Tier | Meaning | Typical Score Range |
|------|---------|---------------------|
| `PLATINUM` | Market moving (top 1%) | 90-100 |
| `GOLD` | High impact (next 2%) | 75-89 |
| `SILVER` | Notable (next 10%) | 50-74 |
| `BRONZE` | Moderate (next 20%) | 25-49 |
| `STANDARD` | Routine (bottom 67%) | 0-24 |

### Relationship Types
| Relationship | Pattern | Properties | Purpose |
|--------------|---------|------------|---------|
| `PRODUCED_BY` | Document → Source | - | Document origin |
| `MENTIONS` | Document → Company | - | Company references |
| `AFFECTS` | Document → Instrument | direction, magnitude, confidence | Price impact |
| `TRIGGERED_BY` | Document → EventType | confidence | Event classification |
| `BELONGS_TO` | Company → Sector | - | Industry classification |
| `IN_GROUP` | Document/Source/Client → Group | - | Access control |
| `ISSUED_BY` | Instrument → Company | - | Security issuer |
| `PEER_OF` | Company ↔ Company | correlation | Similar companies |
| `CONSTITUENT_OF` | Instrument → Index | weight | Index membership |
| `IS_TYPE_OF` | Client → ClientType | - | Client template |
| `HAS_PROFILE` | Client → ClientProfile | - | Client settings |
| `HAS_PORTFOLIO` | Client → Portfolio | - | Holdings link |
| `HAS_WATCHLIST` | Client → Watchlist | - | Watch items link |
| `HOLDS` | Portfolio → Instrument | weight, shares, avg_cost | Portfolio positions |
| `WATCHES` | Watchlist → Instrument | alert_threshold | Watch list items |
| `BENCHMARKED_TO` | ClientProfile → Index | tracking_error_target | Mandate benchmark |
| `EXCLUDES` | ClientProfile → Company/Sector | reason | ESG/liquidity constraints |
| `SUBSCRIBED_TO` | Client → Sector/Region/EventType | priority | Alert preferences |

---

## Query Patterns (MCP Tool Usage)

### ⚠️ LIMITATION: No Direct "List All Instruments" Tool
There is NO `list_instruments` or `list_companies` tool. Use these workarounds:

**Option A: Use Known Tickers Directly**
The simulated universe has these 12 tickers - use them directly with `get_market_context`:
`BANKO`, `BLK`, `ECO`, `FIN`, `GENE`, `GTX`, `TRUCK`, `LUXE`, `NXS`, `OMNI`, `PROP`, `QNTM`

**Option B: Search Documents to Discover Companies**
```json
POST /tools/query_documents
{
  "query": "technology sector companies",
  "n_results": 50
}
```
Parse the results to extract mentioned company tickers from document content.

**Option C: Explore from a Known Starting Point**
```json
POST /tools/explore_graph
{
  "node_type": "INSTRUMENT",
  "node_id": "AAPL",
  "relationship_types": ["PEER_OF", "ISSUED_BY"],
  "max_depth": 2,
  "limit": 50
}
```
Start from any known ticker and traverse to find related instruments.

---

### Pattern 1: Get Instrument Details (RECOMMENDED STARTING POINT)
```json
POST /tools/get_market_context
{
  "ticker": "AAPL",
  "include_peers": true,
  "include_events": true,
  "include_indices": true,
  "days_back": 30
}
```
Returns: Full context for AAPL including company info, peer companies, recent news, index memberships (S&P 500), and sector.

### Pattern 3: Find News Affecting a Stock
```json
POST /tools/get_instrument_news
{
  "ticker": "TSLA",
  "days_back": 7,
  "min_impact_score": 50,
  "limit": 20
}
```
Returns: High-impact news articles affecting TSLA, sorted by impact score.

### Pattern 4: Explore Company Relationships
```json
POST /tools/explore_graph
{
  "node_type": "COMPANY",
  "node_id": "AAPL",
  "relationship_types": ["PEER_OF", "BELONGS_TO"],
  "max_depth": 2,
  "limit": 50
}
```
Returns: AAPL's peer companies and sector classification.

### Pattern 5: List All Clients
```json
POST /tools/list_clients
{
  "client_type": "HEDGE_FUND",
  "limit": 50
}
```
Returns: All hedge fund clients accessible to the authenticated user.

### Pattern 6: Get Client Portfolio Holdings
```json
POST /tools/get_portfolio_holdings
{
  "client_guid": "550e8400-e29b-41d4-a716-446655440000"
}
```
Returns: All instruments held in the client's portfolio with weights and shares.

### Pattern 7: Get Personalized Client Feed
```json
POST /tools/get_client_feed
{
  "client_guid": "550e8400-e29b-41d4-a716-446655440000",
  "limit": 20,
  "min_impact_score": 40,
  "impact_tiers": ["PLATINUM", "GOLD"],
  "include_portfolio": true,
  "include_watchlist": true
}
```
Returns: News articles ranked by relevance to the client's holdings and watchlist.

---

## Simulated Universe (Reference Data)

### 🎯 Known Tickers (Use These Directly)
These 12 tickers exist in the graph. Use them with `get_market_context(ticker)` or `get_instrument_news(ticker)`:

| Ticker | Name | Sector | Use With |
|--------|------|--------|----------|
| `BANKO` | BankOne | Financial | `get_market_context("BANKO")` |
| `BLK` | BlockChain Verify | Financial | `get_market_context("BLK")` |
| `ECO` | EcoPower Systems | Energy | `get_market_context("ECO")` |
| `FIN` | FinCorp | Financial | `get_market_context("FIN")` |
| `GENE` | GeneSys | Healthcare | `get_market_context("GENE")` |
| `GTX` | GigaTech Inc. | Technology | `get_market_context("GTX")` |
| `TRUCK` | HeavyTrucks Inc. | Auto | `get_market_context("TRUCK")` |
| `LUXE` | LuxeBrands | Consumer Cyclical | `get_market_context("LUXE")` |
| `NXS` | Nexus Software | Technology | `get_market_context("NXS")` |
| `OMNI` | OmniCorp Global | Conglomerate | `get_market_context("OMNI")` |
| `PROP` | PropCo REIT | Real Estate | `get_market_context("PROP")` |
| `QNTM` | Quantum Compute | Technology | `get_market_context("QNTM")` |

### Client Types
| Code | Description | Default Alert Freq | Default Impact Threshold |
|------|-------------|-------------------|--------------------------|
| `HEDGE_FUND` | Hedge funds | realtime (100) | 50 |
| `LONG_ONLY` | Long-only asset managers | hourly (24) | 60 |
| `QUANT` | Quantitative funds | realtime (100) | 40 |
| `PENSION` | Pension funds | daily (1) | 70 |
| `FAMILY_OFFICE` | Family offices | daily (1) | 60 |

### Event Categories
| Category | Example Event Types |
|----------|---------------------|
| Earnings | EARNINGS_BEAT, EARNINGS_MISS, GUIDANCE_RAISE |
| Corporate Action | M&A, SPINOFF, BUYBACK |
| Ownership | INSIDER_BUY, 13F_FILING |
| Analyst | UPGRADE, DOWNGRADE, PRICE_TARGET |
| Regulatory | FDA_APPROVAL, SEC_INVESTIGATION |
| Management | CEO_CHANGE, BOARD_CHANGE |
| Macro | RATE_DECISION, GDP_DATA |

---

## Common Workflows

### 1. Research a Stock
```
get_market_context(ticker) → explore_graph(COMPANY, ticker, [PEER_OF]) → get_instrument_news(ticker)
```

### 2. Set Up a New Client
```
create_client(name, type) → add_to_portfolio(client_guid, ticker, weight) → add_to_watchlist(client_guid, ticker) → get_client_feed(client_guid)
```

### 3. Find High-Impact News
```
query_documents(query, n_results=50) → filter by impact_tier → get_instrument_news(affected_ticker)
```

### 4. Explore Sector Exposure
```
explore_graph(SECTOR, "Technology", [BELONGS_TO]) → get_instrument_news(each ticker)
```
