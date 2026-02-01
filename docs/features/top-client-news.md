# Top Client News (Hybrid Graph + Semantic)

## Purpose
Provide **timely, client‑specific** news for sales traders by combining:
1) Graph‑based relevance (holdings, watchlist, lateral relations)
2) Semantic relevance (mandate, ESG constraints, event preferences)
3) Recency/impact weighting

Default output is **top 3** actionable items.

---

## Goals
- **Personalized**: client profile (hedge fund vs long‑only, ESG, horizon) drives relevance.
- **Hybrid**: use both Neo4j traversal and ChromaDB semantic search.
- **Freshness**: filter and rank for recent items (default 24h window).
- **Explainable**: short “why it matters” for each item.

## Non‑Goals
- Portfolio analytics or risk modeling.
- Replacing the existing `get_client_feed` (this is a “top‑news lens”).

---

## API
**Tool**: `get_top_client_news`

```
get_top_client_news(
  client_guid: str,
  limit: int = 3,
  time_window_hours: int = 24,
  include_portfolio: bool = true,
  include_watchlist: bool = true,
  include_lateral_graph: bool = true,
  min_impact_score: float | None = None,
  impact_tiers: list[str] | None = None,
  auth_tokens: list[str] | None = None
) -> { articles: [...] }
```

### Output item
```
{
  document_guid,
  title,
  created_at,
  impact_score,
  impact_tier,
  affected_instruments,
  relevance_score,
  reasons: [DIRECT_HOLDING | WATCHLIST | SUPPLY_CHAIN | COMPETITOR | PEER | BENCHMARK | SEMANTIC_MATCH],
  why_it_matters
}
```

---

## Data Sources
- **Neo4j** (GraphIndex): holdings, watchlists, company/sector relations.
- **ChromaDB** (EmbeddingIndex via QueryService): semantic similarity search.
- **LLMService** (optional): to synthesize semantic query and to generate “why it matters”.

---

## Retrieval Strategy
### Channel A — Graph Candidates
Retrieve documents affecting:
- **Direct holdings** (`HOLDS`)
- **Watchlist** (`WATCHES`)
- **Lateral relations** (if enabled)
  - competitors (`COMPETES_WITH`)
  - supply chain (`SUPPLIES_TO`, `SUPPLIER_OF`, `PARTNER_OF`)
  - peers (same sector)
- **Benchmark** (if defined)

### Channel B — Semantic Candidates
Construct query text from:
- client type (hedge fund, pension, long‑only)
- mandate type + horizon
- ESG constraints
- portfolio & watchlist tickers

Run `QueryService.query()` with:
- group filtering
- date window
- impact filters (post‑filter)

---

## Scoring & Ranking
### Components
- **Semantic score**: similarity from ChromaDB
- **Graph score**: relationship strength (direct holding > watchlist > lateral)
- **Impact score**: normalized 0‑1
- **Recency**: exponential decay on timestamp

### Final Score
$$
\text{final} = w_s \cdot \text{semantic} + w_g \cdot \text{graph} + w_i \cdot \text{impact} + w_r \cdot \text{recency}
$$

### Default Weights
- **Hedge fund / high‑turnover**: $w_s=0.35, w_g=0.35, w_i=0.20, w_r=0.10$
- **Long‑only / pension**: $w_s=0.30, w_g=0.30, w_i=0.20, w_r=0.20$

---

## ESG & Mandate Filtering
If `esg_constrained`:
- Exclude documents tied to excluded companies or sectors.
- Use document entities (Company/Sector) when available.

---

## Explainability
Each item includes:
- **Reasons** (graph relation + semantic match)
- **Why it matters**: a short client‑specific summary (rule‑based or LLM‑generated)

---

## Implementation Notes
- New method in `QueryService`: `get_top_client_news()`
- New tool in `client_tools.py`: `get_top_client_news`
- `register_all_tools()` passes `query_service` into `register_client_tools()`

---

## Testing
1. **Client A vs Client B**: different top 3.
2. **ESG**: excluded sector/company docs are filtered.
3. **Recency**: older than time window are excluded.
4. **Hybrid**: semantic results + graph results merge without duplicates.

---

## Rollout Plan
1. Ship tool + tests in MCP server.
2. Validate with demo clients.
3. Tune weights per client archetype.
