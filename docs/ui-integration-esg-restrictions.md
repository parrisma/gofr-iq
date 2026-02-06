# UI Integration Guide: ESG & Compliance Restrictions

This document details the MCP API interface for the extended ESG restrictions feature, enabling UI developers to build comprehensive client profile management screens.

## Overview

The restrictions system extends beyond the simple `esg_constrained` boolean to provide granular ESG and compliance controls. Restrictions are stored as a JSON object on the client profile and affect:

1. **Negative Screening** (Anti-Pitch): Exclude stories about certain industries
2. **Positive Screening** (Relevance Boost): Prioritize stories matching impact themes
3. **Future Capabilities**: Legal, operational, and tax constraints (placeholders)

---

## Data Model

### Full Restrictions Schema

```typescript
interface ClientRestrictions {
  ethical_sector: EthicalSector;
  impact_sustainability: ImpactSustainability;
  legal_regulatory: LegalRegulatory;       // Future use
  operational_risk: OperationalRisk;       // Future use
  tax_accounting: TaxAccounting;           // Future use
}

interface EthicalSector {
  // Industries to EXCLUDE from news feed (negative screening)
  excluded_industries: string[];
  // Religious compliance framework
  faith_based: "none" | "shariah" | "catholic" | "other";
}

interface ImpactSustainability {
  // Fund has specific positive impact goals
  impact_mandate: boolean;
  // Themes to BOOST in story ranking (positive screening)
  impact_themes: string[];
  // Fund requires active voting/engagement with portfolio companies
  stewardship_obligations: boolean;
}

interface LegalRegulatory {
  jurisdictions: string[];  // ISO country codes
  investor_eligibility: "retail" | "accredited" | "institutional" | null;
  sanctions_restricted: boolean;
}

interface OperationalRisk {
  max_issuer_concentration_pct: number | null;  // 0-100
  leverage_limit_nav_pct: number | null;        // >= 0
  illiquid_asset_limit_nav_pct: number | null;  // 0-100
}

interface TaxAccounting {
  structure: "UCITS" | "REIT" | "mutual_fund" | "hedge_fund" | "other" | null;
  reporting_standard: "IFRS" | "GAAP" | null;
  tax_constraints: string[];
}
```

### Standard Industry Codes for `excluded_industries`

| Code | Description |
|------|-------------|
| `TOBACCO` | Tobacco products and manufacturing |
| `WEAPONS` | Defense, firearms, controversial weapons |
| `GAMBLING` | Casinos, betting, lottery |
| `ADULT_ENTERTAINMENT` | Adult content producers/distributors |
| `FOSSIL_FUELS` | Oil, gas, coal extraction and processing |
| `ALCOHOL` | Alcoholic beverage production |
| `NUCLEAR` | Nuclear energy and weapons |
| `ANIMAL_TESTING` | Companies with animal testing practices |
| `PRIVATE_PRISONS` | Private prison operators |
| `PALM_OIL` | Unsustainable palm oil production |

### Standard Impact Themes for `impact_themes`

| Theme | Description |
|-------|-------------|
| `clean_energy` | Renewable energy, solar, wind |
| `sustainable_transport` | EVs, public transit, cycling |
| `circular_economy` | Recycling, waste reduction |
| `social_housing` | Affordable housing development |
| `diversity` | DEI initiatives, inclusive employers |
| `water_stewardship` | Water conservation and access |
| `healthcare_access` | Healthcare affordability and access |
| `education` | Educational technology and access |
| `financial_inclusion` | Banking for underserved populations |
| `sustainable_agriculture` | Organic, regenerative farming |

---

## MCP API Endpoints

### 1. Create Client with Restrictions

**Tool:** `create_client`

```json
{
  "tool": "create_client",
  "arguments": {
    "name": "Green Capital Partners",
    "client_type": "HEDGE_FUND",
    "alert_frequency": "daily",
    "impact_threshold": 50,
    "mandate_type": "equity_long_short",
    "mandate_text": "Long-short equity fund focused on sustainable technology companies...",
    "benchmark": "SPY",
    "horizon": "medium",
    "esg_constrained": true,
    "restrictions": {
      "ethical_sector": {
        "excluded_industries": ["TOBACCO", "WEAPONS", "FOSSIL_FUELS"],
        "faith_based": "none"
      },
      "impact_sustainability": {
        "impact_mandate": true,
        "impact_themes": ["clean_energy", "sustainable_transport"],
        "stewardship_obligations": true
      }
    }
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001",
    "portfolio_guid": "...",
    "watchlist_guid": "...",
    "profile_guid": "...",
    "group_guid": "reuters-feed",
    "settings": {
      "alert_frequency": "daily",
      "impact_threshold": 50,
      "mandate_type": "equity_long_short",
      "mandate_text": "Long-short equity fund focused...",
      "benchmark": "SPY",
      "horizon": "medium",
      "esg_constrained": true,
      "restrictions_applied": true
    }
  },
  "message": "Created client 'Green Capital Partners' with ESG restrictions"
}
```

**Auto-ESG Behavior:** If `excluded_industries` is non-empty, `esg_constrained` is automatically set to `true` even if not explicitly provided.

---

### 2. Get Client Profile (includes restrictions)

**Tool:** `get_client_profile`

```json
{
  "tool": "get_client_profile",
  "arguments": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Green Capital Partners",
    "client_type": "HEDGE_FUND",
    "group_guid": "group-uuid-here",
    "status": "active",
    "profile": {
      "guid": "profile-guid-here",
      "mandate_type": "equity_long_short",
      "mandate_text": "Long-short equity fund focused on sustainable technology...",
      "benchmark": "SPY",
      "horizon": "medium",
      "esg_constrained": true,
      "restrictions": {
        "ethical_sector": {
          "excluded_industries": ["TOBACCO", "WEAPONS", "FOSSIL_FUELS"],
          "faith_based": "none"
        },
        "impact_sustainability": {
          "impact_mandate": true,
          "impact_themes": ["clean_energy", "sustainable_transport"],
          "stewardship_obligations": true
        },
        "legal_regulatory": {
          "jurisdictions": [],
          "investor_eligibility": null,
          "sanctions_restricted": false
        },
        "operational_risk": {
          "max_issuer_concentration_pct": null,
          "leverage_limit_nav_pct": null,
          "illiquid_asset_limit_nav_pct": null
        },
        "tax_accounting": {
          "structure": null,
          "reporting_standard": null,
          "tax_constraints": []
        }
      }
    },
    "settings": {
      "alert_frequency": "daily",
      "impact_threshold": 50
    },
    "portfolio_guid": "...",
    "watchlist_guid": "...",
    "created_at": "2026-02-06T10:30:00Z"
  }
}
```

**Note:** If no restrictions have been set, `profile.restrictions` will be `null`.

---

### 3. Update Client Restrictions

**Tool:** `update_client_profile`

#### Add/Modify Restrictions
```json
{
  "tool": "update_client_profile",
  "arguments": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001",
    "restrictions": {
      "ethical_sector": {
        "excluded_industries": ["TOBACCO", "WEAPONS", "GAMBLING"],
        "faith_based": "shariah"
      },
      "impact_sustainability": {
        "impact_mandate": true,
        "impact_themes": ["clean_energy", "water_stewardship"],
        "stewardship_obligations": true
      }
    }
  }
}
```

#### Clear All Restrictions
```json
{
  "tool": "update_client_profile",
  "arguments": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001",
    "restrictions": {}
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "client_guid": "550e8400-e29b-41d4-a716-446655440001",
    "changes": ["restrictions", "esg_constrained"],
    "profile": { /* updated profile */ }
  },
  "message": "Updated profile for 'Green Capital Partners'"
}
```

**Important:** The `restrictions` parameter is a **full replacement**. You must provide the complete restrictions object when updating. Omitting the parameter keeps current restrictions.

---

### 4. List Clients (summary only)

**Tool:** `list_clients`

```json
{
  "tool": "list_clients",
  "arguments": {
    "client_type": "HEDGE_FUND",
    "include_completeness_score": true,
    "limit": 50
  }
}
```

**Note:** `list_clients` returns summary data only - it does NOT include restrictions. Use `get_client_profile` to fetch full restrictions for a specific client.

---

## UI Implementation Recommendations

### 1. Restrictions Editor Component

Create a multi-section form with collapsible panels:

```
┌─────────────────────────────────────────────────────────────┐
│ ESG & Compliance Restrictions                               │
├─────────────────────────────────────────────────────────────┤
│ ▼ Ethical Screening (Exclusions)                            │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ ☑ TOBACCO    ☑ WEAPONS    ☐ GAMBLING                │   │
│   │ ☐ ADULT_ENTERTAINMENT    ☑ FOSSIL_FUELS            │   │
│   │ ☐ ALCOHOL    ☐ NUCLEAR    ☐ ANIMAL_TESTING         │   │
│   └─────────────────────────────────────────────────────┘   │
│   Faith-Based: [None ▼]                                     │
│                                                             │
│ ▶ Impact & Sustainability (collapsed)                       │
│ ▶ Legal & Regulatory (collapsed, future)                    │
│ ▶ Operational Risk (collapsed, future)                      │
│ ▶ Tax & Accounting (collapsed, future)                      │
└─────────────────────────────────────────────────────────────┘
```

### 2. Impact Themes Selector

Use a tag-style multi-select with suggestions:

```
Impact Themes:
┌─────────────────────────────────────────────────────────────┐
│ [clean_energy ×] [sustainable_transport ×]                  │
│ ─────────────────────────────────────────────────────────── │
│ + Add theme: [water_stewardship     ▼]                     │
└─────────────────────────────────────────────────────────────┘
```

### 3. Client Profile Summary Card

Show restriction status in client list/card views:

```
┌─────────────────────────────────────────────────────────────┐
│ Green Capital Partners                        [HEDGE_FUND]  │
│ ─────────────────────────────────────────────────────────── │
│ Alert: Daily | Threshold: 50 | Horizon: Medium              │
│                                                             │
│ 🚫 ESG Exclusions: TOBACCO, WEAPONS, FOSSIL_FUELS (3)       │
│ 🌱 Impact Themes: clean_energy, sustainable_transport (2)   │
│ ☪️  Faith-Based: Shariah Compliant                          │
└─────────────────────────────────────────────────────────────┘
```

### 4. Validation Rules

| Field | Validation |
|-------|------------|
| `excluded_industries` | Array of strings (use standard codes) |
| `faith_based` | Enum: `none`, `shariah`, `catholic`, `other` |
| `impact_themes` | Array of strings (use standard themes) |
| `impact_mandate` | Boolean |
| `stewardship_obligations` | Boolean |
| `max_issuer_concentration_pct` | Number 0-100 or null |
| `leverage_limit_nav_pct` | Number >= 0 or null |
| `illiquid_asset_limit_nav_pct` | Number 0-100 or null |
| `investor_eligibility` | Enum or null |
| `structure` | Enum or null |
| `reporting_standard` | Enum: `IFRS`, `GAAP`, or null |

### 5. Error Handling

**Invalid Restrictions Schema:**
```json
{
  "status": "error",
  "error_code": "INVALID_RESTRICTIONS",
  "message": "Invalid restrictions schema",
  "details": {
    "validation_errors": [
      {
        "loc": ["ethical_sector", "faith_based"],
        "msg": "Input should be 'none', 'shariah', 'catholic' or 'other'",
        "type": "enum"
      }
    ]
  },
  "recovery_strategy": "Check restrictions structure against documented schema."
}
```

---

## Relationship to Other Profile Fields

| Field | Description | Interaction with Restrictions |
|-------|-------------|-------------------------------|
| `esg_constrained` | Master ESG filter toggle | Auto-enabled when `excluded_industries` is non-empty |
| `mandate_type` | Investment style category | Independent - restrictions add granular rules |
| `mandate_text` | Free-text mandate description | Independent - used for semantic matching |
| `impact_threshold` | Min impact score for alerts | Works with restrictions to filter news |

---

## Example: Complete Client Creation with All Restrictions

```json
{
  "tool": "create_client",
  "arguments": {
    "name": "Shariah Sustainable Fund",
    "client_type": "LONG_ONLY",
    "alert_frequency": "daily",
    "impact_threshold": 40,
    "mandate_type": "equity_long_short",
    "mandate_text": "Shariah-compliant sustainable equity fund investing in companies meeting strict ESG and Islamic finance criteria. Focus on clean technology and ethical business practices.",
    "benchmark": "MSCI World ESG Leaders",
    "horizon": "long",
    "restrictions": {
      "ethical_sector": {
        "excluded_industries": [
          "TOBACCO",
          "WEAPONS",
          "GAMBLING",
          "ADULT_ENTERTAINMENT",
          "ALCOHOL"
        ],
        "faith_based": "shariah"
      },
      "impact_sustainability": {
        "impact_mandate": true,
        "impact_themes": [
          "clean_energy",
          "sustainable_transport",
          "water_stewardship",
          "financial_inclusion"
        ],
        "stewardship_obligations": true
      },
      "legal_regulatory": {
        "jurisdictions": ["US", "GB", "AE", "MY"],
        "investor_eligibility": "accredited",
        "sanctions_restricted": true
      },
      "operational_risk": {
        "max_issuer_concentration_pct": 5.0,
        "leverage_limit_nav_pct": 0,
        "illiquid_asset_limit_nav_pct": 10.0
      },
      "tax_accounting": {
        "structure": "UCITS",
        "reporting_standard": "IFRS",
        "tax_constraints": ["no-withholding-treaty"]
      }
    }
  }
}
```

---

## Migration Notes for Existing UI

1. **Existing `esg_constrained` toggle**: Keep this as a quick on/off, but link it to the restrictions panel for granular control
2. **Backwards compatibility**: Clients without restrictions will have `profile.restrictions = null`
3. **Partial restrictions**: Any category can be omitted - defaults will be applied (empty arrays, false booleans, null for optional fields)

---

## API Endpoint Reference

| Action | MCP Tool | Key Parameters |
|--------|----------|----------------|
| Create client | `create_client` | `restrictions: object` |
| Get full profile | `get_client_profile` | `client_guid` → returns `profile.restrictions` |
| Update restrictions | `update_client_profile` | `restrictions: object` (full replacement) or `{}` (clear) |
| List clients | `list_clients` | Does NOT include restrictions |

All endpoints require authentication via `auth_tokens` parameter or `Authorization: Bearer <token>` header.
