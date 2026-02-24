# How News Routing Works
## A Plain-English Guide for Sales Traders

---

## 1. Overview

Two things happen in sequence:

1. **Ingestion** -- a story arrives and gets decoded into structured signals.
2. **Query** -- when you ask "what is relevant to my client today?", those signals are matched against that client's profile and a ranked list comes back.

You can influence both stages. This document explains how.

---

## 2. Ingestion -- what happens when a story arrives

```
Story text
   |
   v
[1] Source validation      -- is the source registered and trusted?
   |
   v
[2] Dedup check            -- have we seen this before?
   |
   v
[3] Language detection
   |
   v
[4] Store to file + ChromaDB embedding
   |
   v
[5] LLM extraction (one call, ~1s)
      -> impact_score  (0-100)
      -> impact_tier   (PLATINUM / GOLD / SILVER / BRONZE / STANDARD)
      -> tickers       (AAPL, TSLA, ...)     creates AFFECTS edges
      -> companies     (Apple Inc, ...)       creates MENTIONS edges
      -> event_type    (EARNINGS, M&A, ...)   creates TRIGGERED_BY edge
      -> themes        (ai, rates, esg, ...)  stored on Document node
   |
   v
[6] Graph links written to Neo4j
```

After step 6 the story is permanently queryable. No re-ingestion needed.

**What matters for routing:** the most important output is `themes` and `AFFECTS <ticker>`.  
A story tagged `themes=[ai, semiconductor]` will reach any client whose mandate includes those themes.  
A story with `AFFECTS NXS` will reach any client who holds or watches NXS.

**Impact tier** acts as a gatekeeper -- clients with a high `impact_threshold` will not see BRONZE/STANDARD items.

---

## 3. Query -- how "top news for this client" is built

When you call `get_top_client_news` the engine runs five parallel lookups
(called channels), then scores and ranks everything.

### 3.1 The five scoring channels

| Channel | What it finds | Base score |
|---|---|---|
| DIRECT_HOLDING | Stories affecting tickers the client holds | 0.9 (defense) down to 0.4 (offense) |
| WATCHLIST | Stories affecting tickers on the client's watchlist | 0.80 fixed |
| THEMATIC | Stories tagged with the client's mandate_themes | 0.6 (defense) up to 0.9 (offense) |
| VECTOR | Stories semantically similar to the client's mandate (embedding match) | 0.5 up to 0.9 (offense only) |
| COMPETITOR / SUPPLY_CHAIN / PEER | Stories about graph-linked companies | 0.4-0.6 depending on type |

A story can be captured by multiple channels at once. That earns an **influence boost** (+0.1 per extra path, max +0.3).

### 3.2 Final score formula

```
final_score =
    0.35 * graph_score          # best channel score from above
  + 0.35 * vector_score         # semantic similarity (if VECTOR channel fired)
  + 0.20 * impact_norm          # impact_score 0-100 normalised to 0-1
  + 0.10 * recency              # exponential decay, half-life = 60-240 min
  + influence_boost             # multi-path bonus
  + position_boost              # top-weight holdings rank higher
  + discovery_boost             # non-holding thematic hits get extra lift at high lambda
```

The 0.35/0.35/0.20/0.10 weights can be overridden per-client-type or via env vars -- see section 5.

---

## 4. Lambda (opportunity_bias) -- the main tuning dial

Lambda is the single most powerful lever for a sales trader.  
It is a number between 0 and 1 passed to `get_top_client_news` as `opportunity_bias`.

| Lambda | Mode | What it does |
|---|---|---|
| 0.0 | Defense | Prioritises direct holdings. High-weight positions dominate. VECTOR channel is off. New ideas do not surface. |
| 0.25 | Lean defense | Like defense but VECTOR activates. Rare thematic matches can sneak in. |
| 0.50 | Balanced | Equal weight between holdings and thematic/semantic channels. Good default for inbound calls. |
| 0.75 | Lean offense | Thematic and VECTOR channels dominate. Discovery boost fires. New names surface above smaller positions. |
| 1.0 | Offense | Maximum idea generation. Holdings still matter but a strong semantic match beats a weak holding. |

**Underlying mechanics changed by lambda:**

- `direct_holding_base` scores fall from 0.90 to 0.40 as lambda rises.
- `thematic_base` rises from 0.60 to 0.90.
- `vector_base` rises from 0.50 to 0.90; fully off at lambda=0.
- Recency half-life extends from 60 min to 240 min (offense looks further back).
- Position boost dampened by factor `(1 - 0.5 * lambda)`.
- Discovery boost (up to +0.40) fires only at lambda > 0.1 for non-holding thematic hits.

**Examples:**

- Client is anxious about their existing book ahead of FOMC: use `lambda=0` to surface threats to their holdings only.
- Pre-meeting pitch for an upsell: use `lambda=0.75-1.0` to surface ideas outside their current holdings.
- Daily morning briefing: `lambda=0.5` gives a balanced view.

---

## 5. Client profile -- what you can configure

These fields live on the `ClientProfile` node and affect every query for that client.

| Field | Type | Effect |
|---|---|---|
| `portfolio` (HOLDS edges) | ticker + weight % | DIRECT_HOLDING channel. Higher weight = higher position_boost. |
| `watchlist` (WATCHES edges) | list of tickers | WATCHLIST channel. No weight -- flat 0.80 score. |
| `benchmark` | ticker (e.g. SPY) | Appended to watchlist automatically. |
| `mandate_themes` | list of tags | THEMATIC channel. Match against `d.themes` on Document nodes. |
| `mandate_text` | free text | Embedded and stored as `mandate_embedding`. Drives VECTOR channel. |
| `mandate_embedding` | 4096-dim vector | Pre-computed from mandate_text. Re-run backfill script if text changes. |
| `impact_threshold` | 0-100 | Documents below this score are filtered out before scoring. |
| `esg_constrained` | bool | If true, ESG sector/company exclusions are applied. |
| `client_type` | LONG_ONLY, PENSION, ... | Shifts default scoring weights to 0.30/0.30/0.20/0.20 for conservative types. |
| `horizon` | SHORT_TERM / LONG_TERM | Used in why_it_matters narration (does not change ranking today). |

**Controlled vocabulary for mandate_themes:**

The themes on Document nodes are assigned by the LLM at ingest time from a fixed vocabulary.
If a client's `mandate_themes` tag is not in that vocabulary, THEMATIC channel will be silent.
Current recognised tags include: `ai`, `semiconductor`, `rates`, `commodities`, `consumer`,
`esg`, `energy_transition`, `blockchain`, `ev_battery`, `cloud`, `cybersecurity`.

---

## 6. Worked examples

### Example A: morning brief for a defensive pension fund

Client: Nebula Retirement Fund  
Holdings: OMNI (20%), SHOPM (15%), TRUCK (12%)  
Mandate themes: commodities, rates, consumer  
Call: `get_top_client_news(client_guid=..., limit=5, opportunity_bias=0.0)`

Result: top stories are ones with `AFFECTS OMNI/SHOPM/TRUCK` ranked by position weight,
followed by any SILVER+ story tagged `commodities` or `rates` or `consumer`.
Nothing outside their book will appear.

---

### Example B: pre-meeting pitch for a tech fund

Client: Quantum Momentum Partners  
Holdings: QNTM (15%), BANKO (12%), VIT (10%)  
Mandate themes: ai, semiconductor  
Call: `get_top_client_news(client_guid=..., limit=5, opportunity_bias=0.75)`

Result: VECTOR channel fires against their AI/semiconductor embedding.
A breaking story about a new GPU fab deal -- even for a ticker they do not hold --
will score highly if semantically similar to their mandate.
Their existing QNTM exposure still surfaces, but competes against new ideas.

---

### Example C: ESG exclusion in action

Client: Green Horizon Capital  
esg_constrained=true, excluded_industries: TOBACCO, WEAPONS, FOSSIL_FUELS

A high-impact story about an oil major (OILCO) affecting their sector would normally surface.
After exclusion filtering it is dropped entirely before scoring.
The exclusion happens after candidate collection, before final ranking.

---

### Example D: watchlist vs. holding distinction

Client holds VELO at 25% (DIRECT_HOLDING, base=0.9 at lambda=0).  
Client watches LUXE (WATCHLIST, base=0.80 always).

A medium-impact LUXE story scores: `0.35 * 0.80 + 0.20 * impact_norm + 0.10 * recency`.  
The VELO story scores: `0.35 * 0.90 + 0.20 * impact_norm + 0.10 * recency + position_boost`.

At lambda=0, the held position almost always outranks the watchlist item.  
At lambda=0.75, DIRECT_HOLDING base drops to ~0.525, so a LUXE story with strong themes
can overtake VELO if LUXE also fires the THEMATIC channel.

---

## 7. Quick reference -- API parameters for get_top_client_news

| Parameter | Default | Range | Notes |
|---|---|---|---|
| `client_guid` | required | UUID | Use list_clients to find |
| `limit` | 3 | 1-10 | Number of stories to return |
| `time_window_hours` | 24 | 1-168 | How far back to look |
| `opportunity_bias` | 0.0 | 0.0-1.0 | Lambda; see section 4 |
| `min_impact_score` | client default | 0-100 | Override client's threshold |
| `impact_tiers` | GOLD+SILVER+PLATINUM | list | Add BRONZE for more volume |
| `include_portfolio` | true | bool | Toggle DIRECT_HOLDING channel |
| `include_watchlist` | true | bool | Toggle WATCHLIST channel |
| `include_lateral_graph` | true | bool | Toggle competitor/supplier hops |

---

## 8. How to improve results for a specific client

| Symptom | Fix |
|---|---|
| Client gets nothing back | Lower `min_impact_score` or add `BRONZE` to `impact_tiers`. Check that at least one holding or theme tag is set. |
| Same old stories, no new ideas | Raise `opportunity_bias` toward 0.75-1.0. Check that `mandate_text` is set and `mandate_embedding` is backfilled. |
| Irrelevant stories dominating | Lower `opportunity_bias`. Remove watchlist tickers that are too broad. Tighten `mandate_themes` to specific tags. |
| ESG story appearing that should not | Ensure `esg_constrained=true` and the company's sector maps to an excluded industry. |
| A story is missing that should be there | Check that the story's tickers are in `AFFECTS` edges (re-ingest if LLM extraction failed). Check that its `themes` tags match the client's `mandate_themes`. |
| Competitor news not surfacing | Confirm COMPETES_WITH edges exist in the graph for the client's holdings. Check `include_lateral_graph=true`. |
