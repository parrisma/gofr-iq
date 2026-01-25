# Neo4j Cypher Query Guide
## GOFR-IQ Simulation Knowledge Graph

**About Cypher:** Cypher is Neo4j's declarative graph query language. It uses ASCII-art patterns to match graph structures:
- `()` represents nodes, `[]` represents relationships
- `-->` shows relationship direction
- `MATCH` finds patterns, `WHERE` filters, `RETURN` specifies output
- Similar to SQL but optimized for graph traversals

**Connection:**
- Neo4j Browser: http://localhost:7474
- Bolt URL: `bolt://localhost:7687`
- Username: `neo4j` | Password: (from Vault - see setup docs)

**Finding Docker Host IP (for external connections):**

If connecting from outside the container (e.g., Windows host to WSL2 Docker):

```bash
# Linux/WSL - get host IP
hostname -I
# Example output: 172.24.48.1 192.168.1.100
```

```powershell
# Windows PowerShell
wsl hostname -I
```

Then connect using the first IP address:
- Browser: `http://172.24.48.1:7474`
- Bolt: `bolt://172.24.48.1:7687`

---

## Quick Start: Visualize the Graph Model

```cypher
// See the complete graph schema visually
CALL db.schema.visualization()
```

This shows all node types, relationship types, and how they connect.

---

## Schema Queries

```cypher
// Node counts by type
MATCH (n) RETURN labels(n)[0] AS NodeType, count(*) AS Count ORDER BY Count DESC

// Relationship counts by type
MATCH ()-[r]->() RETURN type(r) AS RelationType, count(*) AS Count ORDER BY Count DESC

// All companies
MATCH (c:Company) RETURN c.name, c.ticker, c.sector ORDER BY c.name
```

---

## Document Queries

```cypher
// Recent documents
MATCH (d:Document)-[:PRODUCED_BY]->(s:Source)
RETURN d.headline, s.name, d.published_date, d.sentiment
ORDER BY d.published_date DESC LIMIT 10

// By company
MATCH (d:Document)-[:MENTIONS]->(c:Company)
WHERE c.name = 'Quantum Compute'
RETURN d.headline, d.sentiment, d.published_date
ORDER BY d.published_date DESC LIMIT 10

// By instrument ticker
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
WHERE i.ticker IN ['company-FIN', 'company-BANKO', 'company-PROP']
RETURN d.headline, i.ticker, d.sentiment, d.published_date
ORDER BY d.published_date DESC LIMIT 10

// High impact (strong sentiment)
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
WHERE abs(d.sentiment) > 0.5
RETURN d.headline, i.ticker, d.sentiment
ORDER BY abs(d.sentiment) DESC LIMIT 10

// By event type
MATCH (d:Document)-[:TRIGGERED_BY]->(e:EventType)
WHERE e.name CONTAINS 'Supply Chain'
RETURN d.headline, e.name, d.sentiment, d.published_date
ORDER BY d.published_date DESC LIMIT 10
```

---

## Company Analysis

```cypher
// Most mentioned companies
MATCH (d:Document)-[:MENTIONS]->(c:Company)
RETURN c.name, c.sector, count(d) AS mentions
ORDER BY mentions DESC LIMIT 10
```

**Companies:**
- BankOne (company-BANKO) - Financial
- BlockChain Verify (company-BLK) - Financial
- EcoPower Systems (company-ECO) - Energy
- FinCorp (company-FIN) - Financial
- GeneSys (company-GENE) - Healthcare
- GigaTech Inc. (company-GTX) - Technology
- HeavyTrucks Inc. (company-TRUCK) - Auto
- LuxeBrands (company-LUXE) - Consumer Cyclical
- Nexus Software (company-NXS) - Technology
- OmniCorp Global (company-OMNI) - Conglomerate
- PropCo REIT (company-PROP) - Real Estate
- Quantum Compute (company-QNTM) - Technology
- ShopMart (company-SHOPM) - Consumer Cyclical
- Stratos Defense (company-STR) - Industrials
- Velocity Motors (company-VELO) - Auto
- Vitality Pharma (company-VIT) - Healthcare

```cypher
// Most affected instruments
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
RETURN i.ticker, i.name, count(d) AS impact_count, avg(d.sentiment) AS avg_sentiment
ORDER BY impact_count DESC LIMIT 10

// Company sentiment analysis
MATCH (d:Document)-[:MENTIONS]->(c:Company)
WHERE c.name = 'Quantum Compute'
RETURN avg(d.sentiment) AS avg, count(d) AS count, 
       min(d.sentiment) AS min, max(d.sentiment) AS max, 
       stDev(d.sentiment) AS volatility

// Sector sentiment comparison
MATCH (d:Document)-[:MENTIONS]->(c:Company)
RETURN c.sector, avg(d.sentiment) AS avg_sentiment, count(d) AS mentions
ORDER BY avg_sentiment DESC

// Sentiment volatility by instrument
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
WITH i, stDev(d.sentiment) AS volatility, count(d) AS doc_count
WHERE doc_count > 3
RETURN i.ticker, volatility, doc_count
ORDER BY volatility DESC
```

---

## Source Analysis

```cypher
// Source coverage and reliability
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)
RETURN s.name, s.trust_level, count(d) AS articles, avg(d.sentiment) AS avg_sentiment
ORDER BY articles DESC

// Source bias detection
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)
RETURN s.name, s.trust_level, avg(d.sentiment) AS avg_sentiment, 
       stDev(d.sentiment) AS variance, count(d) AS articles
ORDER BY articles DESC

// Low-trust source alerts
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)-[:AFFECTS]->(i:Instrument)
WHERE s.trust_level IN ['low', 'unverified'] AND abs(d.sentiment) > 0.5
RETURN d.headline, s.name, i.ticker, d.sentiment
ORDER BY abs(d.sentiment) DESC LIMIT 10
```

---

## Event Analysis

```cypher
// Event distribution
MATCH (d:Document)-[:TRIGGERED_BY]->(e:EventType)
RETURN e.name, count(d) AS occurrences
ORDER BY occurrences DESC

// Event impact by sector
MATCH (d:Document)-[:TRIGGERED_BY]->(e:EventType),
      (d)-[:AFFECTS]->(i:Instrument)<-[:OWNS]-(c:Company)
RETURN e.name, c.sector, count(d) AS events, avg(d.sentiment) AS avg_impact
ORDER BY c.sector, events DESC

// Supply chain disruptions
MATCH (d:Document)-[:TRIGGERED_BY]->(e:EventType),
      (d)-[:AFFECTS]->(i:Instrument)
WHERE e.name CONTAINS 'Supply Chain'
RETURN d.headline, e.name, i.ticker, d.sentiment, d.published_date
ORDER BY d.published_date DESC LIMIT 15

// Event correlation (co-occurrence)
MATCH (d:Document)-[:TRIGGERED_BY]->(e1:EventType),
      (d)-[:TRIGGERED_BY]->(e2:EventType)
WHERE id(e1) < id(e2)
RETURN e1.name, e2.name, count(d) AS co_occurrences
ORDER BY co_occurrences DESC LIMIT 10
```

---

## Graph Traversals

```cypher
// Full path: Source → Document → Instrument → Company
MATCH path = (s:Source)<-[:PRODUCED_BY]-(d:Document)-[:AFFECTS]->(i:Instrument)<-[:OWNS]-(c:Company)
RETURN path LIMIT 25

// Multi-company mentions per document
MATCH (d:Document)-[:MENTIONS]->(c:Company)
WITH d, collect(c.name) AS companies, count(c) AS company_count
WHERE company_count > 1
RETURN d.headline, companies, company_count
ORDER BY company_count DESC LIMIT 10

// Cross-sector impact
MATCH (d:Document)-[:AFFECTS]->(i1:Instrument)<-[:OWNS]-(c1:Company),
      (d)-[:MENTIONS]->(c2:Company)
WHERE c1.sector <> c2.sector
RETURN d.headline, c1.name, c1.sector, collect(DISTINCT c2.sector) AS affected_sectors
LIMIT 10

// Multi-hop company connections
MATCH (d:Document)-[:MENTIONS]->(c1:Company),
      path = (c1)-[:SUPPLIER_TO|CUSTOMER_OF*1..2]-(c2:Company)
WHERE c1.name = 'Quantum Compute'
RETURN DISTINCT d.headline, c1.name, c2.name, d.sentiment
LIMIT 15
```

---

## Time-Based Analysis

```cypher
// Documents by source over time
MATCH (d:Document)-[:PRODUCED_BY]->(s:Source)
WITH s.name AS source, date(d.published_date) AS day, count(d) AS articles
RETURN source, day, articles
ORDER BY day DESC, articles DESC LIMIT 20

// Sentiment trend for instrument
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
WHERE i.ticker = 'company-LUXE'
RETURN date(d.published_date) AS day, avg(d.sentiment) AS avg_sentiment,
       count(d) AS docs, min(d.sentiment) AS min, max(d.sentiment) AS max
ORDER BY day DESC

// Sector sentiment trend
MATCH (d:Document)-[:AFFECTS]->(i:Instrument)<-[:OWNS]-(c:Company)
WHERE c.sector = 'Technology'
RETURN date(d.published_date) AS day, avg(d.sentiment) AS avg_sentiment, count(d) AS coverage
ORDER BY day DESC

// Event frequency timeline
MATCH (d:Document)-[:TRIGGERED_BY]->(e:EventType)
WHERE e.name CONTAINS 'Supply Chain'
RETURN e.name, date(d.published_date) AS day, count(d) AS occurrences
ORDER BY day DESC, occurrences DESC
```

---

## Visualization Queries

```cypher
// Full document network sample
MATCH path = (d:Document)-[r]-(other)
RETURN path LIMIT 100

// Instrument impact network
MATCH path = (i:Instrument)<-[:AFFECTS]-(d:Document)-[:PRODUCED_BY]->(s:Source)
WHERE i.ticker IN ['company-QNTM', 'company-LUXE', 'company-GENE']
RETURN path LIMIT 50

// Company mention network
MATCH path = (d:Document)-[:MENTIONS]->(c:Company)
WHERE c.name IN ['Quantum Compute', 'LuxeBrands', 'GeneSys']
RETURN path LIMIT 30

// Source coverage map
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)-[:MENTIONS]->(c:Company)
WHERE c.name IN ['Quantum Compute', 'LuxeBrands', 'GeneSys']
RETURN s.name, c.name, count(d) AS coverage
ORDER BY coverage DESC
```

---

## Advanced Patterns

```cypher
// Competing companies co-mentioned
MATCH (c1:Company)<-[:MENTIONS]-(d:Document)-[:MENTIONS]->(c2:Company)
WHERE c1.sector = c2.sector AND id(c1) < id(c2)
RETURN c1.name, c2.name, c1.sector, count(d) AS co_mentions,
       collect(DISTINCT d.headline)[..3] AS sample_headlines
ORDER BY co_mentions DESC LIMIT 10

// Supply chain contagion risk
MATCH (c:Company)-[r:SUPPLIER_TO|CUSTOMER_OF]-(connected:Company)
RETURN c.name, count(DISTINCT connected) AS connections,
       collect(DISTINCT connected.name)[..5] AS connected_companies
ORDER BY connections DESC LIMIT 10

// Source sentiment divergence
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)-[:MENTIONS]->(c:Company)
WHERE c.name = 'PropCo REIT'
RETURN s.name, s.trust_level, avg(d.sentiment) AS avg_sentiment, count(d) AS articles
ORDER BY avg_sentiment DESC

// Anomaly detection: extreme sentiment from low-trust sources
MATCH (s:Source)<-[:PRODUCED_BY]-(d:Document)-[:AFFECTS]->(i:Instrument)
WHERE s.trust_level IN ['low', 'unverified'] AND abs(d.sentiment) > 0.7
RETURN d.headline, s.name, s.trust_level, i.ticker, d.sentiment
ORDER BY abs(d.sentiment) DESC LIMIT 10
```

---

## Graph Algorithms

```cypher
// Shortest path between companies
MATCH path = shortestPath((c1:Company {name: 'Quantum Compute'})-[*]-(c2:Company {name: 'LuxeBrands'}))
RETURN path

// Node degree centrality (most connected)
MATCH (c:Company)-[r]-(other)
RETURN c.name, count(r) AS degree
ORDER BY degree DESC LIMIT 10

// Clustering (shared document mentions)
MATCH (c1:Company)<-[:MENTIONS]-(d:Document)-[:MENTIONS]->(c2:Company)
WHERE id(c1) < id(c2)
WITH c1, c2, count(d) AS shared_docs
WHERE shared_docs > 2
RETURN c1.name, c2.name, shared_docs
ORDER BY shared_docs DESC
```

## Performance & Indexing

```cypher
// Create indexes
CREATE INDEX ON :Document(published_date)
CREATE INDEX ON :Company(name)
CREATE INDEX ON :Instrument(ticker)

// Profile query performance
PROFILE MATCH (d:Document)-[:AFFECTS]->(i:Instrument) RETURN count(*)
```

**Best Practices:**
- Always use `LIMIT` for exploratory queries
- Filter early with `WHERE` before aggregations
- Use `PROFILE` to identify slow queries
- Index frequently filtered properties
