# Synthetic News Generation Proposal

## Objective
Create a flexible data generation script (`scripts/generate_synthetic_stories.py`) to stress-test the `graph_extraction.py` prompt logic. The goal is to verify that specific news patterns trigger the correct **Impact Scores**, **Tiers**, and **Event Types** defined in the system prompt.

## Core Architecture

The script will function as a **Scenario-Based Generator**. Instead of random text, it will iterate through defined "Market Scenarios" that map directly to the rules in `app/prompts/graph_extraction.py`.

### Proposed Script Structure

```python
@dataclass
class Scenario:
    name: str
    target_tier: str  # PLATINUM, GOLD, SILVER, etc.
    target_event: str # EARNINGS_BEAT, LEGAL_RULING, etc.
    min_score: int
    template: str     # Prompt template for the LLM to generate the story
    entities: List[str] # Entities to inject (e.g., ["AAPL", "GOOGL"])
```

## targeted Scenarios (Mapped to Prompt Logic)

The generator will focus on these specific edge cases found in the source code:

### 1. The "Platinum" Regulator
*   **Goal**: Verify rule `Antitrust ruling against FAANG/mega-cap = PLATINUM`
*   **Prompt Logic**: Checks if the extractor respects the >90 score rule for specifically named Tech Giants.
*   **Inputs**: GOOGL, AAPL, AMZN, META, MSFT.
*   **Expected Output**: Impact Score 90-100, Event: `LEGAL_RULING`.

### 2. The "Semantic" Earnings Beat
*   **Goal**: Verify rule `"Strong sales", "record revenue" ... = GOLD (treat as earnings-equivalent)`
*   **Challenge**: The story will **NOT** mention "EPS" or "Earnings per share". It will only use phraseology like "Record Top Line" or "Sales Smash Expectations".
*   **Expected Output**: Tier: GOLD, Event: `EARNINGS_BEAT` (Not `POSITIVE_SENTIMENT`).

### 3. The "Supply Chain" Ripple
*   **Goal**: Verify rule `Supply chain/commodity news affecting major industries = SILVER minimum`
*   **Inputs**: TSMC, Semiconductor Industry, EV Batteries.
*   **Expected Output**: Tier: SILVER (55+), Event: `MACRO_DATA` or `GUIDANCE_CUT`.

### 4. The "Rumor" Penalty
*   **Goal**: Verify rule `Rumors without named sources: -20 points from base`
*   **Details**: Generate a story about a massive M&A deal but explicitly attribute it to "people familiar with the matter" or "unnamed sources".
*   **Expected Output**: Tier: SILVER/BRONZE (downgraded from Gold/Platinum), Event: `M&A_RUMOR`.

### 5. The "Peer" Exclusion
*   **Goal**: Verify rule `Competitors merely mentioned for context... DO NOT extract`
*   **Scenario**: "Tesla cuts prices, putting pressure on Rivian and Lucid."
*   **Expected Output**: 
    *   Instruments: `TSLA` (Primary)
    *   Result: `RIVN`, `LCID` should appear in `companies` list but **NOT** in `instruments` list (or if they do, direction matches the "Peer read-through" rule).

## Output Artifacts

The script will generate individual JSON files (e.g., `data/synthetic/story_{N}.json`) which contain both the payload for ingestion and the metadata for validation.

**Structure:**

```json
{
  "source": "Bloomberg Technology",  // The simulate source name
  "upload_as_group": "admin",        // The user group context to use for the token (e.g. "admin", "apac-sales")
  "story_body": "The Department of Justice formally filed an antitrust lawsuit against...", // The generated content
  "validation_metadata": {           // Ground truth for testing
    "scenario": "Platinum Regulator",
    "expected_tier": "PLATINUM",
    "expected_event": "LEGAL_RULING",
    "expected_entities": ["GOOGL"],
    "validation_rules": {
      "min_score": 90,
      "must_match_event": true
    }
  }
}
```

## Execution Constraints

1.  **Story Length**: Maximum 500 words.
2.  **Date Range**: Random publication date up to 60 days in the past.
3.  **Stock Universe**: Stories will be built around a fixed bench of 20 fictional (or proxied) tickers to ensure we test repeated ingestion for the same entity.

### The "Mock Market" Universe (20 Tickers)

| Ticker | Type | Persona |
| :--- | :--- | :--- |
| **GIGATECH** (GTX) | Mega-Cap Tech | Apple/Google proxy. High impact threshold. |
| **OMNICORP** (OMNI) | Mega-Cap Ind | Conglomerate. Stable. |
| **QUANTUM** (QNTM) | High-Growth Tech | NVDA proxy. Extremely volatile events. |
| **NEXUS** (NXS) | Mid-Cap Software | SaaS. Frequent M&A target rumors. |
| **STRATOS** (STR) | Defense/Aero | Government contracts (Gold/Silver logic). |
| **VITALITY** (VIT) | Pharma | FDA approvals/rejections (Platinum/Gold binary). |
| **ECOPWR** (ECO) | Clean Energy | Regulatory/Subsidy sensitive. |
| **BLOCKCHAIN** (BLK) | Crypto Proxy | High volatility, sentiment driven. |
| *(plus 12 others covering Retail, Finance, Auto, etc.)*

## Distribution Strategy

To mirror reality, the generator will NOT select scenarios uniformly. It will use a weighted probability:

*   **STANDARD (65%)**: Routine filings, minor personnel changes, marketing fluff.
*   **BRONZE (20%)**: Moderate sector news, small contracts.
*   **SILVER (10%)**: Supply chain ripples, analyst moves.
*   **GOLD (4%)**: Earnings beats, major guidance changes.
*   **PLATINUM (1%)**: Antitrust rulings, massive fraud.

This ensures the system is mostly tested on "noise" filtering, which is the hardest part of production extraction.

## Configuration via .env

To decouple sensitive data and flexible options from the code, the script will read from a dedicated `.env` file (e.g., `scripts/.env.synthetic`).

**Required Environment Variables:**

1.  **`GOFR_SYNTHETIC_SOURCES`**: A JSON list of allowed news source names.
    *   Example: `["Bloomberg", "Reuters", "WSJ", "TechCrunch", "Seeking Alpha"]`
2.  **`GOFR_SYNTHETIC_TOKENS`**: A JSON map linking user groups to their valid upload tokens. The script will randomly select a group context for each story.
    *   Example: `{"admin": "gofr-dev-admin-token", "public": "gofr-dev-public-token", "apac_sales": "gofr-dev-apac-token"}`
3.  **`GOFR_IQ_OPENROUTER_API_KEY`**: The API key for generating the story content via LLM.
