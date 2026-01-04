# Client Feeds & Personalization

Personalized news feeds deliver documents most relevant to each client based on portfolio holdings, watchlists, preferences, and mandate constraints.

---

## Client Feed Architecture

```
┌────────────────────────────────────────────────────────┐
│              CLIENT PROFILE & HOLDINGS                 │
│  ├─ Portfolio: [AAPL 5%, MSFT 3%, TSM 2%, ...]        │
│  ├─ Watchlist: [GOOG, META, NVDA]                     │
│  ├─ Benchmark: S&P 500                                │
│  ├─ Mandate: +/- 50bps tracking error                 │
│  └─ Exclusions: ESG constraints (fossil fuels)        │
└────────────────────────────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────┐
│    QUERY: Find documents affecting portfolio           │
│  (Traverse Neo4j: Document → AFFECTS → Instrument)     │
└────────────────────────────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────┐
│   SCORING: Calculate relevance for client              │
│  ├─ Position boost: weight * impact_score             │
│  ├─ Watchlist boost: +bonus if on watchlist          │
│  ├─ Time decay: exp(-lambda * hours_old)             │
│  ├─ Benchmark boost: if in benchmark index           │
│  └─ Constraint filter: exclude ESG violations        │
└────────────────────────────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────┐
│      RANKING: Sort by relevance score (highest first)  │
│  (Final score = position + watchlist + decay + bonus)  │
└────────────────────────────────────────────────────────┘
                          ▼
┌────────────────────────────────────────────────────────┐
│         DELIVERY: Stream or batch to client            │
│  ├─ Real-time SSE events (WebSocket)                  │
│  ├─ Hourly digest email                               │
│  ├─ Mobile push notifications                         │
│  └─ API polling                                       │
└────────────────────────────────────────────────────────┘
```

---

## Feed Scoring Formula

### Core Formula

```
relevance_score = impact_score × time_decay + position_boost + watchlist_boost + benchmark_boost

Where:
  impact_score = 0-100 (from LLM extraction or event type)
  time_decay = exp(-lambda * hours_old)
  position_boost = holding_weight × 50
  watchlist_boost = is_on_watchlist ? 40 : 0
  benchmark_boost = in_benchmark_index ? 30 : 0
```

### Time Decay by Impact Tier

Faster decay for lower-impact news (less relevant over time):

```python
DECAY_RATES = {
    "PLATINUM": 0.05,   # 50% decay per 14 hours (major events linger)
    "GOLD":     0.10,   # 50% decay per 7 hours
    "SILVER":   0.15,   # 50% decay per 4.6 hours
    "BRONZE":   0.20,   # 50% decay per 3.5 hours
    "STANDARD": 0.30,   # 50% decay per 2.3 hours
}

hours_old = (now - created_at).total_seconds() / 3600
time_decay = exp(-DECAY_RATES[impact_tier] * hours_old)

# At 0 hours:   decay = 1.0
# At 6 hours:   decay = 0.7 (GOLD)
# At 12 hours:  decay = 0.3 (GOLD)
# At 24 hours:  decay = 0.09 (GOLD)
```

### Position Boost

Higher boost for larger positions:

```python
position_boost = portfolio_weight * 50

# Examples:
# 5% position:   5 * 50 = 250
# 3% position:   3 * 50 = 150
# 1% position:   1 * 50 = 50
# 0.5% position: 0.5 * 50 = 25
```

### Example Calculation

**Document**: Apple quarterly earnings announcement
- **Base impact score**: 70 (GOLD tier)
- **Created**: 6 hours ago
- **Client portfolio**: AAPL 5%
- **On watchlist**: Yes
- **In benchmark (S&P 500)**: Yes

**Scoring**:
```
time_decay = exp(-0.10 * 6) = 0.548
position_boost = 5 * 50 = 250
watchlist_boost = 40
benchmark_boost = 30
time_decayed_impact = 70 * 0.548 = 38.4

relevance_score = 38.4 + 250 + 40 + 30 = 358.4
```

---

## Feed Retrieval (Neo4j)

### Query Pattern: Client's Personalized Feed

```cypher
// Get documents affecting client's portfolio
MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups

// Load portfolio and preferences
MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)
OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)
OPTIONAL MATCH (cp)-[:EXCLUDES]->(excluded)

// Get documents affecting holdings or watchlist
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.created_at > datetime() - duration('P1D')

MATCH (d)-[:AFFECTS]->(inst:Instrument)
WHERE (p)-[:HOLDS]->(inst)
   OR (w)-[:WATCHES]->(inst)

// Verify not excluded
MATCH (inst)-[:ISSUED_BY]->(company:Company)
WHERE NOT company IN collect(excluded)

// Load position details for boost calculation
OPTIONAL MATCH (p)-[h:HOLDS]->(inst)

RETURN d, inst,
       d.impact_score AS impact_score,
       d.impact_tier AS tier,
       d.decay_lambda AS decay_lambda,
       COALESCE(h.weight, 0) AS portfolio_weight,
       CASE WHEN (w)-[:WATCHES]->(inst) THEN true ELSE false END AS on_watchlist
ORDER BY d.created_at DESC
LIMIT 100
```

### Query Pattern: By Impact Tier

```cypher
// Show only PLATINUM/GOLD for executive summary
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
  AND d.impact_tier IN ['PLATINUM', 'GOLD']
  AND d.created_at > datetime() - duration('P1D')

MATCH (d)-[:RELEVANT_TO]->(cp:ClientProfile)
MATCH (cp)<-[:HAS_PROFILE]-(c:Client)-[:IN_GROUP]->(cg:Group)
WHERE cg.group_guid IN $permitted_groups

RETURN d, c, d.impact_score
ORDER BY d.impact_score DESC, d.created_at DESC
```

---

## Feed Management

### Types of Feeds

| Feed Type | Frequency | Contents | Use Case |
|-----------|-----------|----------|----------|
| **Real-time** | As published | All documents | Active traders, hedge funds |
| **Hourly Digest** | Every hour | Top 5 PLATINUM, top 10 GOLD | Traders reviewing |
| **Daily Summary** | 8 AM daily | Top 20 documents | Fund managers |
| **Weekly Briefing** | Friday afternoon | Weekly summary | Board reviews |
| **Alert Only** | When impact ≥ threshold | High-impact events only | Sleeping mode |

### Configuration

```python
@dataclass
class ClientFeedPreferences:
    # Delivery
    feed_type: str  # "realtime", "hourly", "daily", "weekly", "alert_only"
    delivery_channels: list[str]  # ["api", "email", "push", "sse"]
    
    # Filtering
    min_impact_score: float  # 0-100, default 30
    impact_tiers: list[str]  # ["PLATINUM", "GOLD", ...], default all
    event_types: list[str]  # ["EARNINGS_BEAT", "M&A_ANNOUNCE", ...], default all
    
    # Timing
    delivery_time: str  # "08:00", "17:00", etc.
    timezone: str  # "America/New_York"
    
    # Results
    max_results: int  # Per delivery, default 20
    include_graph_context: bool  # Enrich with entities, default True
```

### Preferences Example

```python
from app.models import ClientFeedPreferences

# Hedge fund: high-impact real-time alerts
hedge_fund_prefs = ClientFeedPreferences(
    feed_type="realtime",
    delivery_channels=["sse", "push"],
    min_impact_score=70,  # Only PLATINUM/GOLD
    impact_tiers=["PLATINUM", "GOLD"],
    max_results=50
)

# Asset manager: daily summary
asset_manager_prefs = ClientFeedPreferences(
    feed_type="daily",
    delivery_channels=["email"],
    min_impact_score=40,  # GOLD and above
    impact_tiers=["PLATINUM", "GOLD", "SILVER"],
    delivery_time="08:00",
    max_results=20
)

# Sleep mode: alerts only
sleep_mode_prefs = ClientFeedPreferences(
    feed_type="alert_only",
    delivery_channels=["push"],
    min_impact_score=90,  # Only PLATINUM
    impact_tiers=["PLATINUM"],
)
```

---

## Exclusions & Constraints

### ESG Exclusions Example

```cypher
// Client excludes fossil fuel companies
MATCH (c:Client {guid: $client_guid})-[:HAS_PROFILE]->(cp:ClientProfile)
MATCH (cp)-[:EXCLUDES]->(sector:Sector {name: "fossil_fuels"})

// Filter out documents mentioning excluded companies
MATCH (d:Document)-[:AFFECTS]->(inst:Instrument)
MATCH (inst)-[:ISSUED_BY]->(company:Company)
WHERE company NOT IN (
  MATCH (sector)-[esg_list]-(company) RETURN company
)

RETURN d
```

### Liquidity Constraints

```cypher
// Client only trades liquid stocks (>$10M daily volume)
MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
MATCH (p)-[h:HOLDS]->(inst:Instrument)
WHERE inst.avg_daily_volume_usd > 10_000_000

// Only show documents for liquid holdings
MATCH (d:Document)-[:AFFECTS]->(inst)
WHERE inst IN collect(inst)  // Only from above

RETURN d
```

---

## Real-Time Feed (SSE)

### WebSocket/SSE Stream

```python
# Client subscribes to live feed
@app.get("/api/v1/feeds/{client_id}/stream")
async def stream_client_feed(
    client_id: str,
    user: CurrentUser,
    background_tasks: BackgroundTasks
):
    """Stream documents for client as they're ingested."""
    
    async def event_generator():
        queue = asyncio.Queue()
        
        # Register callback for new documents
        def on_new_document(doc: Document):
            # Check if relevant for this client
            if is_relevant_to_client(doc, client_id):
                score = calculate_feed_score(doc, client_id)
                if score >= min_threshold:
                    asyncio.create_task(queue.put({
                        "document": doc.to_dict(),
                        "score": score,
                        "timestamp": datetime.now().isoformat()
                    }))
        
        document_service.subscribe(on_new_document)
        
        try:
            while True:
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            document_service.unsubscribe(on_new_document)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### Client-Side Consumption

```javascript
// JavaScript client
const eventSource = new EventSource(
  `/api/v1/feeds/my-client/stream`
);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`New document: ${data.document.title} (${data.score})`);
  updateUI(data);
};
```

---

## Batch Feed Delivery

### Hourly Digest

```python
async def generate_hourly_digest(client_id: str):
    """Generate and deliver hourly digest to client."""
    
    # Get top documents for this hour
    documents = query_service.search_feed(
        client_guid=client_id,
        time_range="past_hour",
        limit=10,
        min_impact_tier="GOLD"
    )
    
    if not documents:
        return  # No documents to send
    
    # Generate email
    email_html = render_feed_email(documents, client_id)
    
    # Send via email service
    await email_service.send(
        to=client.email,
        subject=f"GOFR-IQ Hourly Digest - {len(documents)} documents",
        html=email_html
    )
    
    # Log delivery
    audit_service.log_feed_delivery(
        client_id=client_id,
        feed_type="hourly_digest",
        document_count=len(documents),
        delivered_at=datetime.now()
    )
```

### Email Template

```html
<h2>GOFR-IQ Hourly Digest</h2>
<p>Top {count} documents affecting your portfolio:</p>

{% for doc in documents %}
<div class="document">
  <h3>{{ doc.title }}</h3>
  <p class="meta">
    {{ doc.source_name }} | 
    <span class="impact {{ doc.impact_tier }}">{{ doc.impact_tier }}</span> |
    Score: {{ doc.feed_score | round(1) }}
  </p>
  <p>{{ doc.content_snippet }}</p>
  
  <div class="impacts">
    {% for instrument in doc.instruments_affected %}
    <span class="instrument {{ instrument.direction }}">
      {{ instrument.ticker }} {{ instrument.direction }}
    </span>
    {% endfor %}
  </div>
  
  <a href="https://gofr-iq.internal/documents/{{ doc.guid }}">Read full document →</a>
</div>
{% endfor %}
```

---

## Analytics & Metrics

### Feed Engagement

Track which documents clients open/act on:

```python
@dataclass
class FeedEngagement:
    document_guid: str
    client_guid: str
    delivered_at: datetime
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    opened_duration_seconds: Optional[float] = None
    action_taken: Optional[str] = None  # "trade", "research", "ignore"
```

### Scoring Quality

Monitor if feed scores align with client behavior:

```python
# If clients ignore documents we score high, adjust weights
def analyze_feed_quality(client_id: str, days: int = 7):
    engagements = audit_service.get_feed_engagements(
        client_id=client_id,
        start_date=datetime.now() - timedelta(days=days)
    )
    
    # Calculate correlation between feed score and engagement
    scores = [e.feed_score for e in engagements]
    opened = [1 if e.opened_at else 0 for e in engagements]
    
    correlation = pearsonr(scores, opened)
    
    if correlation < 0.5:
        logger.warning(f"Low feed quality for {client_id}: {correlation}")
        # Suggest weight adjustment
```

---

## Performance Optimization

### Caching

```python
# Cache client portfolios (update daily)
portfolio_cache = TTLCache(
    maxsize=10000,
    ttl=86400  # 24 hours
)

def get_client_portfolio(client_id: str):
    if client_id in portfolio_cache:
        return portfolio_cache[client_id]
    
    portfolio = graph_index.get_client_portfolio(client_id)
    portfolio_cache[client_id] = portfolio
    return portfolio
```

### Batch Processing

For thousands of clients, batch feed generation:

```python
async def batch_generate_daily_feeds():
    """Generate feeds for all clients in parallel."""
    
    clients = client_service.list_all_clients()
    
    # Process 100 at a time
    for chunk in batches(clients, 100):
        tasks = [
            generate_client_feed(client.guid)
            for client in chunk
        ]
        await asyncio.gather(*tasks)
        
        # Wait between batches to avoid overload
        await asyncio.sleep(60)
```

---

## Best Practices

### 1. Set Reasonable Thresholds
```python
# Don't overwhelm clients with too many documents
min_impact_score = 40  # At least SILVER tier
max_results = 20  # Per delivery
```

### 2. Respect Constraints
```python
# Always apply exclusions (ESG, liquidity, etc.)
def validate_feed_document(doc, client):
    # Check ESG exclusions
    if doc_violates_esg(doc, client.profile):
        return False
    
    # Check liquidity constraints
    if doc_affects_illiquid_stock(doc, client.profile):
        return False
    
    return True
```

### 3. Monitor Feed Quality
```python
# Track engagement to optimize scoring
def quality_check():
    for client in all_clients:
        engagement = analyze_engagement(client.id, days=7)
        if engagement.open_rate < 0.3:
            adjust_weights_for_client(client.id)
```

---

## Related Documentation

- [Hybrid Search](hybrid-search.md)
- [Graph Design](../architecture/graph-design.md)
- [Configuration Reference](../getting-started/configuration.md)
- [Architecture Overview](../architecture/overview.md)
