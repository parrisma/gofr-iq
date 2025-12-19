# GOFR-IQ Demo

Realistic APAC market data for demonstrating graph relationships, semantic search, and client feeds.

## Quick Start

```bash
# Dry run to see what would be loaded
python demo/load_demo_data.py --dry-run

# Load from dev container (via direct MCP)
python demo/load_demo_data.py --mcp-url http://gofr-iq-mcp:8080/mcp

# Load from host (via MCPO proxy)
python demo/load_demo_data.py --mcpo-url http://localhost:8081

# Generate 50 stories instead of default 30
python demo/load_demo_data.py --mcpo-url http://localhost:8081 --num-stories 50
```

## What Gets Loaded

### 1. Access Groups (4)
- `public` - Free access
- `premium-apac` - Paid subscribers
- `internal-sales` - Internal proprietary
- `quant-desk` - High-frequency signals

### 2. News Sources (8)
- **Reuters Asia** (news_agency, APAC, verified, public)
- **Bloomberg Terminal** (news_agency, APAC, verified, premium)
- **日本経済新聞 Nikkei** (news_agency, JP, verified, public)
- **CLSA Research** (broker, HK, trusted, premium)
- **Nomura Securities** (broker, JP, trusted, premium)
- **CITIC Securities** (broker, CN, trusted, premium)
- **Internal Alpha Signals** (analyst, APAC, standard, quant-desk)
- **HKEX Regulatory** (regulator, HK, verified, public)

### 3. Companies & Instruments (17)

**Chinese Tech**
- `9988.HK` Alibaba Group (Technology, $220B)
- `700.HK` Tencent Holdings (Technology, $380B)
- `9618.HK` JD.com (E-Commerce, $45B)
- `1024.HK` Kuaishou Technology (Technology, $25B)

**Japanese Industrials**
- `7203.T` Toyota Motor (Automotive, $280B)
- `6758.T` Sony Group (Technology, $110B)
- `6502.T` Toshiba (Technology, $18B)
- `7267.T` Honda Motor (Automotive, $52B)
- `9984.T` SoftBank Group (Technology, $65B)

**Korean Semiconductors**
- `005930.KS` Samsung Electronics (Semiconductors, $320B)
- `000660.KS` SK Hynix (Semiconductors, $75B)

**Singapore Banks**
- `D05.SI` DBS Group (Banking, $65B)
- `O39.SI` OCBC Bank (Banking, $45B)
- `U11.SI` UOB (Banking, $42B)

**Australian Banks**
- `CBA.AX` Commonwealth Bank (Banking, $135B)
- `NAB.AX` NAB (Banking, $68B)
- `WBC.AX` Westpac (Banking, $55B)

### 4. Story Templates (7 types, ~30 stories)

| Template | Count | Impact | Example |
|----------|-------|--------|---------|
| Earnings Beat | 8 | GOLD | "Alibaba Q3 earnings beat estimates by 12.3%" |
| Earnings Miss | 6 | PLATINUM | "Toyota misses Q2 estimates, stock falls 7.2%" |
| Regulatory | 4 | PLATINUM | "China SAMR announces new antitrust rules for Technology" |
| M&A Announce | 3 | PLATINUM | "Samsung in talks to acquire SK Hynix for $95.2B" |
| Guidance Raise | 5 | GOLD | "Tencent raises FY2025 guidance on strong cloud demand" |
| Product Launch | 3 | SILVER | "Sony unveils PlayStation 6 targeting $50B market" |
| Analyst Upgrade | 1 | SILVER | "CLSA upgrades DBS to Buy, sees 25% upside" |

### 5. Demo Clients (3)

**Citadel APAC Long/Short** (Hedge Fund)
- Portfolio: 9988.HK (8%), 700.HK (12%), 005930.KS (10%), 7203.T (7%)
- Watchlist: 9618.HK, 6758.T, D05.SI
- Impact threshold: 60

**Temasek Tech Growth** (Long Only)
- Portfolio: 700.HK (15%), 005930.KS (12%), 9988.HK (10%), 6758.T (8%)
- Watchlist: 1024.HK, 9984.T
- Impact threshold: 50

**Singapore Sovereign Wealth** (Pension)
- Portfolio: CBA.AX (6%), D05.SI (8%), 7203.T (5%), 005930.KS (4%)
- Watchlist: NAB.AX, O39.SI
- Impact threshold: 70

## Testing Scenarios

### Semantic Search
```python
# Query about specific company
query_documents("Alibaba earnings")

# Query about sector/theme
query_documents("China tech regulation")

# Query about event type
query_documents("M&A semiconductor industry")
```

### Graph Exploration
```python
# Explore company relationships
explore_graph(node_type="INSTRUMENT", node_id="9988.HK")

# Find peers
get_market_context(ticker="700.HK", include_peers=True)

# Get news affecting stock
get_instrument_news(ticker="7203.T", days_back=30)
```

### Personalized Feeds
```python
# Get feed for specific client
get_client_feed(client_guid="<citadel_guid>")

# Filter by impact
get_client_feed(client_guid="<temasek_guid>", min_impact_score=70)
```

## Data Characteristics

- **Temporal**: Stories span 30 days (recent history)
- **Multi-region**: CN, JP, KR, SG, AU coverage
- **Multi-language**: en, zh, ja content
- **Impact distribution**: 40% PLATINUM, 40% GOLD, 20% SILVER
- **Sector diversity**: Tech, Automotive, Semiconductors, Banking
- **Event diversity**: 7 distinct event types

## Next Steps

After loading:
1. Verify data via health_check tool
2. Test semantic similarity across languages
3. Demonstrate graph relationship discovery
4. Show personalized client feeds with impact filtering
