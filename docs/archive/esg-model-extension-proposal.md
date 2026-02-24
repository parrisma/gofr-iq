# ESG & Compliance Restrictions – Proposal

**Status**: Approved  
**Date**: 2026-02-04  
**Related**: [Implementation Plan](esg-implementation-plan.md)

---

## 1. Objective

Extend the current binary `esg_constrained` flag into a structured **restrictions** schema that captures multiple compliance layers for fund screening and story selection.

**Business Value**:
1. **Anti-Pitch Logic**: Automatically exclude news about sectors/companies the client cannot trade.
2. **Relevance Boosting**: Positively weight stories aligned with the client's impact themes.
3. **Mandate Alignment**: Combine `mandate_text` + `restrictions` to create client-specific search bias.

---

## 2. Current State

| Field | Type | Limitation |
|-------|------|------------|
| `esg_constrained` | Boolean | Only indicates *presence* of constraints, not *what* they are |

---

## 3. Proposed Data Model

We introduce a `restrictions` JSON object stored on the `ClientProfile` node. The schema groups constraints into functional categories.

### 3.1 Schema Structure (Simplified for Story Selection)

```json
{
  "ethical_sector": {
    "excluded_industries": ["TOBACCO", "WEAPONS", "GAMBLING"],
    "faith_based": "none"
  },
  "impact_sustainability": {
    "impact_mandate": true,
    "impact_themes": ["clean_energy", "sustainable_transport"],
    "stewardship_obligations": true
  },
  "legal_regulatory": {
    "jurisdictions": ["US", "EU"],
    "investor_eligibility": "institutional",
    "sanctions_restricted": true
  },
  "operational_risk": {
    "max_issuer_concentration_pct": 5.0,
    "leverage_limit_nav_pct": 150.0,
    "illiquid_asset_limit_nav_pct": 10.0
  },
  "tax_accounting": {
    "structure": "UCITS",
    "reporting_standard": "IFRS",
    "tax_constraints": []
  }
}
```

---

## 4. Category Definitions

### A. Ethical & Sector (Primary for Story Selection)
Defines negative screening and values-based exclusions.

| Field | Type | Description | Story Impact |
|-------|------|-------------|--------------|
| `excluded_industries` | `list[str]` | Industry codes to exclude | **Hard filter** |
| `faith_based` | `enum` | `none`, `shariah`, `catholic`, `other` | Future mapping |

### B. Impact & Sustainability (Primary for Story Selection)
Positive screening and active stewardship.

| Field | Type | Description | Story Impact |
|-------|------|-------------|--------------|
| `impact_mandate` | `bool` | Fund has positive impact goals | Enables boost logic |
| `impact_themes` | `list[str]` | Themes for relevance boost | **Soft boost** |
| `stewardship_obligations` | `bool` | Active voting required | Informational |

### C. Legal & Regulatory (Future)
Hard compliance rules derived from fund domicile.

| Field | Type | Description |
|-------|------|-------------|
| `jurisdictions` | `list[str]` | Allowed/disallowed regions |
| `investor_eligibility` | `enum` | `retail`, `accredited`, `institutional` |
| `sanctions_restricted` | `bool` | Strict OFAC compliance |

### D. Operational Risk (Future)
Quantitative portfolio construction limits.

| Field | Type | Description |
|-------|------|-------------|
| `max_issuer_concentration_pct` | `float` | Max % per issuer |
| `leverage_limit_nav_pct` | `float` | Max leverage as % NAV |
| `illiquid_asset_limit_nav_pct` | `float` | Cap on Level 3 assets |

### E. Tax & Accounting (Future)
Structural attributes for execution/reporting.

| Field | Type | Description |
|-------|------|-------------|
| `structure` | `enum` | `UCITS`, `REIT`, `mutual_fund`, `hedge_fund`, `other` |
| `reporting_standard` | `enum` | `IFRS`, `GAAP` |
| `tax_constraints` | `list[str]` | Treaty limitations |

---

## 5. Integration with Story Selection

### 5.1 `get_top_client_news` Enhancements

**Current behavior**: Uses `esg_constrained` boolean and `EXCLUDES` graph relationships.

**Enhanced behavior**:

1. **Semantic Query Bias**: Include `mandate_text` + `impact_themes` in the embedding search query.
2. **Exclusion Filter**: Parse `excluded_industries` and remove matching stories.
3. **Relevance Boost** (Phase 2): If `impact_mandate=True`, boost stories tagged with matching `impact_themes`.

### 5.2 Alignment with `mandate_text`

The `mandate_text` field (free-form, 0-5000 chars) complements restrictions:

| Field | Purpose | Example |
|-------|---------|---------|
| `mandate_text` | Describes investment style in prose | "We focus on European clean energy with a 3-5 year horizon" |
| `restrictions.impact_themes` | Structured keywords for boosting | `["clean_energy", "europe"]` |
| `restrictions.ethical_sector.excluded_industries` | Hard exclusion list | `["FOSSIL_FUELS"]` |

All three contribute to `_build_client_query_text()` for semantic search.

---

## 6. Extensibility

The JSON structure allows adding new categories (e.g., `crypto_constraints`) without schema migration. Clients can store partial objects; missing categories default to empty/disabled.

---

## 7. Next Steps

See [esg-implementation-plan.md](esg-implementation-plan.md) for detailed implementation steps, testing plan, and checklist.
