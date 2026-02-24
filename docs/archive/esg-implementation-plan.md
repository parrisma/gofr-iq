# ESG & Compliance Restrictions – Implementation Plan

**Status**: Draft  
**Version**: 2.0  
**Date**: 2026-02-04  
**Author**: Sales Trading SME / Systems Engineering  

---

## 1. Objective

Extend the binary `esg_constrained` flag into a structured **restrictions** schema that enables:

1. **Anti-Pitch filtering** – Automatically exclude stories mentioning sectors/companies the client cannot hold.
2. **Relevance boosting** – Positive alignment with `impact_sustainability` themes can *boost* story rank.
3. **Mandate-aligned search** – Combine `mandate_text` + `restrictions` to bias `get_top_client_news` results.

### Design Principles
- **Simplicity**: One JSON blob on `ClientProfile`; no new nodes or relationships.
- **Alignment**: Reuse existing `esg_constrained` boolean as the "master switch."
- **Extensibility**: Categories can be added without schema migration.

---

## 2. Functional Scope (What It Does for Story Selection)

| Category | Anti-Pitch (Exclusion) | Relevance Boost | Notes |
|----------|------------------------|-----------------|-------|
| `ethical_sector.excluded_industries` | ✅ Exclude stories tagged with these sectors | — | Hard filter |
| `ethical_sector.faith_based` | ✅ If Shariah, exclude interest/gambling stories | — | Future: tag mapping |
| `impact_sustainability.impact_mandate` | — | ✅ Boost ESG-positive stories | Soft boost |
| `impact_sustainability.impact_metrics` | — | ✅ Boost stories matching metrics (e.g., "carbon") | Semantic match |
| `legal_regulatory.jurisdictions` | ✅ If set to "allowed only", exclude non-matching regions | — | Future |
| `operational_risk.*` | — | — | Portfolio construction; not story filtering |
| `tax_accounting.*` | — | — | Reporting; not story filtering |

**Key insight**: Only `ethical_sector` and `impact_sustainability` affect story ranking in Phase 1. Others are stored for future use.

---

## 3. Data Model

### 3.1 Pydantic Schema

**File**: `app/models/restrictions.py`

```python
"""Client Restrictions Model for ESG & Compliance Filtering."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class EthicalSector(BaseModel):
    """Negative screening and values-based exclusions."""
    excluded_industries: list[str] = Field(
        default_factory=list,
        description="Industry codes to exclude (e.g., TOBACCO, WEAPONS, GAMBLING, ADULT_ENTERTAINMENT)",
    )
    faith_based: Literal["none", "shariah", "catholic", "other"] = Field(
        default="none",
        description="Religious compliance framework",
    )


class ImpactSustainability(BaseModel):
    """Positive screening and active stewardship."""
    impact_mandate: bool = Field(
        default=False,
        description="Fund has specific positive impact goals",
    )
    impact_themes: list[str] = Field(
        default_factory=list,
        description="Themes for relevance boost (e.g., clean_energy, social_housing, diversity)",
    )
    stewardship_obligations: bool = Field(
        default=False,
        description="Active voting/engagement required",
    )


class LegalRegulatory(BaseModel):
    """Hard compliance rules (future use)."""
    jurisdictions: list[str] = Field(default_factory=list)
    investor_eligibility: Literal["retail", "accredited", "institutional"] | None = None
    sanctions_restricted: bool = False


class OperationalRisk(BaseModel):
    """Portfolio construction limits (future use)."""
    max_issuer_concentration_pct: float | None = None
    leverage_limit_nav_pct: float | None = None
    illiquid_asset_limit_nav_pct: float | None = None


class TaxAccounting(BaseModel):
    """Structure and reporting (future use)."""
    structure: Literal["UCITS", "REIT", "mutual_fund", "hedge_fund", "other"] | None = None
    reporting_standard: Literal["IFRS", "GAAP"] | None = None
    tax_constraints: list[str] = Field(default_factory=list)


class ClientRestrictions(BaseModel):
    """
    Full restrictions schema for a client profile.
    
    Stored as JSON string on ClientProfile.restrictions property.
    """
    ethical_sector: EthicalSector = Field(default_factory=EthicalSector)
    impact_sustainability: ImpactSustainability = Field(default_factory=ImpactSustainability)
    legal_regulatory: LegalRegulatory = Field(default_factory=LegalRegulatory)
    operational_risk: OperationalRisk = Field(default_factory=OperationalRisk)
    tax_accounting: TaxAccounting = Field(default_factory=TaxAccounting)
```

### 3.2 Storage (Neo4j)

- **Node**: `ClientProfile`
- **Property**: `restrictions` (String – JSON serialized)
- **Relationship to `esg_constrained`**: If `restrictions` is set, `esg_constrained` should be `True`.

No APOC dependency; filtering done in Python after fetch.

---

## 4. MCP Tools API Changes

### 4.1 `create_client` – Add `restrictions` parameter

```python
restrictions: Annotated[dict[str, Any] | None, Field(
    default=None,
    description=(
        "Structured ESG & compliance restrictions. "
        "Categories: ethical_sector, impact_sustainability, legal_regulatory, operational_risk, tax_accounting. "
        "See docs/esg-model-extension-proposal.md for schema."
    ),
)] = None,
```

**Behavior**: If provided, validate via `ClientRestrictions(**restrictions)`, serialize to JSON, store on `ClientProfile.restrictions`. Auto-set `esg_constrained=True` if `ethical_sector.excluded_industries` is non-empty.

### 4.2 `update_client_profile` – Add `restrictions` parameter

Same signature. **Full replacement** semantics (not merge).

### 4.3 `get_client_profile` – Return parsed `restrictions`

Deserialize JSON string to dict in response payload.

### 4.4 CLI Script (`scripts/manage_client.py`)

Add `--restrictions-file` argument for `create` and `update` commands:
```bash
./scripts/manage_client.sh --token $T create --name "ESG Fund" --restrictions-file ./esg_restrictions.json
```

---

## 5. Integration with `get_top_client_news`

### 5.1 Current Flow (Simplified)

1. Fetch client profile (`_get_client_profile_context`)
2. Build semantic query from `mandate_type`, `horizon`, holdings (`_build_client_query_text`)
3. Get graph candidates (holdings, watchlist, lateral)
4. Get semantic candidates (embedding search)
5. Merge, filter by ESG exclusions (`_get_client_exclusions`), score, return top N

### 5.2 Enhanced Flow

**Step 1**: Extend `_get_client_profile_context` to fetch `restrictions` JSON and parse it.

**Step 2**: Extend `_build_client_query_text` to include:
- `mandate_text` (if set) – Already partially done; ensure it's appended.
- `impact_sustainability.impact_themes` – Append as search keywords.

**Step 3**: Extend `_get_client_exclusions` to:
- Parse `restrictions.ethical_sector.excluded_industries` → add to `exclusions["sectors"]`.
- (Future) Parse `restrictions.ethical_sector.faith_based` → map to sector codes.

**Step 4**: (Optional Phase 2) Add relevance boost:
- If `impact_mandate=True` and document has ESG-positive tags, add +0.1 to final score.

### 5.3 Code Changes

**File**: `app/services/query_service.py`

```python
def _get_client_profile_context(self, client_guid: str, group_guids: list[str]) -> dict[str, Any] | None:
    # ... existing query ...
    # ADD: cp.restrictions AS restrictions_json
    # After fetch:
    restrictions_json = record.get("restrictions_json")
    if restrictions_json:
        profile["restrictions"] = json.loads(restrictions_json)
    return profile

def _build_client_query_text(self, profile: dict, holdings: list, watchlist: list, llm_service) -> str:
    # ... existing logic ...
    # ADD: mandate_text
    mandate_text = profile.get("mandate_text", "")
    if mandate_text:
        base += f" Mandate description: {mandate_text}. "
    # ADD: impact themes
    restrictions = profile.get("restrictions", {})
    themes = restrictions.get("impact_sustainability", {}).get("impact_themes", [])
    if themes:
        base += f" Impact themes: {', '.join(themes)}. "
    # ... rest ...

def _get_client_exclusions(self, client_guid: str) -> dict[str, list[str]]:
    # ... existing graph query for EXCLUDES relationships ...
    # ADD: restrictions-based exclusions
    profile = self._get_client_profile_context(client_guid, [])  # internal call
    if profile:
        restrictions = profile.get("restrictions", {})
        ethical = restrictions.get("ethical_sector", {})
        excluded_industries = ethical.get("excluded_industries", [])
        exclusions["sectors"].extend(excluded_industries)
    return exclusions
```

---

## 6. Simulation Updates

### 6.1 `simulation/universe/types.py` – Add `restrictions` field

```python
@dataclass
class MockClient:
    guid: str
    name: str
    archetype: ClientArchetype
    portfolio: List[MockPosition]
    watchlist: List[str]
    mandate_text: Optional[str] = None
    restrictions: Optional[dict] = None  # ADD THIS
```

### 6.2 `simulation/generate_synthetic_clients.py` – Add restrictions to ESG fund

```python
def _generate_esg_fund(self) -> MockClient:
    # ... existing ...
    return MockClient(
        # ... existing fields ...
        restrictions={
            "ethical_sector": {
                "excluded_industries": ["TOBACCO", "WEAPONS", "GAMBLING", "FOSSIL_FUELS"],
                "faith_based": "none",
            },
            "impact_sustainability": {
                "impact_mandate": True,
                "impact_themes": ["clean_energy", "sustainable_transport", "circular_economy"],
                "stewardship_obligations": True,
            },
        },
    )
```

### 6.3 `simulation/load_simulation_data.py` – Pass restrictions to MCP

```python
def _create_client_via_mcp(client_data: dict[str, Any], token: str) -> dict[str, Any]:
    # ... existing cmd building ...
    if "restrictions" in client_data and client_data["restrictions"]:
        # Write to temp file and pass path
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(client_data["restrictions"], f)
            restrictions_file = f.name
        cmd.extend(["--restrictions-file", restrictions_file])
    # ... rest ...
```

---

## 7. Testing Plan

### 7.1 Unit Tests (`test/test_client_tools.py`)

| Test Case | Description |
|-----------|-------------|
| `test_create_client_with_restrictions` | Valid restrictions dict → stored as JSON |
| `test_create_client_invalid_restrictions` | Invalid schema → error response |
| `test_update_client_restrictions_replace` | Update replaces entire object |
| `test_get_client_profile_returns_restrictions` | Fetch deserializes JSON |

### 7.2 Unit Tests (`test/test_query_service.py`)

| Test Case | Description |
|-----------|-------------|
| `test_top_client_news_excludes_restricted_sectors` | Story tagged "TOBACCO" excluded for ESG client |
| `test_top_client_news_boosts_impact_themes` | Story with "clean_energy" tag ranks higher for ESG client |
| `test_build_query_includes_mandate_text` | Semantic query includes mandate_text content |
| `test_build_query_includes_impact_themes` | Semantic query includes impact_themes keywords |

### 7.3 Integration Tests (`test/integration/`)

| Test Case | Description |
|-----------|-------------|
| `test_esg_fund_excludes_tobacco_stories` | End-to-end: Create ESG client → Ingest tobacco story → Verify excluded from top news |
| `test_esg_fund_boosts_clean_energy_stories` | End-to-end: Create ESG client → Ingest clean energy story → Verify ranks higher |

---

## 8. Implementation Checklist

### Phase 1: Core Schema & Storage
- [ ] Create `app/models/restrictions.py`
- [ ] Update `app/tools/client_tools.py`:
  - [ ] `create_client` accepts `restrictions`
  - [ ] `update_client_profile` accepts `restrictions`
  - [ ] `get_client_profile` returns parsed `restrictions`
- [ ] Update `scripts/manage_client.py` with `--restrictions-file`

### Phase 2: Story Selection Integration
- [ ] Update `QueryService._get_client_profile_context` to fetch `restrictions`
- [ ] Update `QueryService._build_client_query_text` to include `mandate_text` and `impact_themes`
- [ ] Update `QueryService._get_client_exclusions` to use `excluded_industries`
- [ ] (Optional) Add impact_mandate boost to final scoring

### Phase 3: Simulation & Testing
- [ ] Update `simulation/universe/types.py` with `restrictions` field
- [ ] Update `simulation/generate_synthetic_clients.py` with ESG restrictions
- [ ] Update `simulation/load_simulation_data.py` to pass restrictions
- [ ] Add unit tests for restrictions validation
- [ ] Add unit tests for story filtering/boosting
- [ ] Add integration test for end-to-end ESG filtering

### Phase 4: Documentation
- [ ] Update `docs/mcp-tool-interface.md` with `restrictions` parameter
- [ ] Update `docs/neo4j-schema.md` with `ClientProfile.restrictions` property

---

## 9. Migration Notes

- **Backward compatible**: Clients without `restrictions` property continue to work.
- **Auto-upgrade**: When `esg_constrained=True` but no `restrictions`, exclusion logic falls back to graph `EXCLUDES` relationships (existing behavior).
- **No data migration required**: New property, defaults to NULL.
