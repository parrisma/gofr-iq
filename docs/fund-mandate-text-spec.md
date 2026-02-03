# Fund Mandate Free Text Field - Specification

## Overview
Add support for a free-text "fund mandate" field (`mandate_text`) to complement the existing structured `mandate_type` enum. This allows clients to capture detailed, nuanced mandate descriptions that go beyond categorical types.

## Problem Statement
The current `mandate_type` field (equity_long_short, global_macro, event_driven, etc.) is limited to predefined categories. Real-world fund mandates often contain:
- Specific investment restrictions/guidelines
- Custom sector allocations or geographic focus
- Risk parameters and leverage limits  
- ESG criteria and ethical guidelines
- Unique strategic objectives

A free-text field enables richer mandate capture while maintaining backward compatibility with structured filtering.

## Design Principles
1. **Complement, don't replace**: Keep `mandate_type` for categorical queries; add `mandate_text` for details
2. **Optional field**: Not required for CPCS scoring (existing mandate_type suffices)
3. **LLM-ready**: Structure for semantic analysis and document relevance matching
4. **Privacy-aware**: May contain sensitive strategy information; honor group permissions
5. **Validation-light**: Minimal constraints (length limits) to avoid restricting legitimate use cases

## Functional Requirements

### FR1: Data Model
- **Field name**: `mandate_text`
- **Type**: String (nullable)
- **Storage**: Neo4j `ClientProfile` node property
- **Length**: 0-5000 characters (allows ~1000 words)
- **Encoding**: UTF-8
- **Relationship**: Stored alongside `mandate_type`, `benchmark`, `horizon` in ClientProfile node

### FR2: API/MCP Interface
- **Read**: Included in `get_client_profile` response (if present)
- **Write**: New parameter in `update_client_profile` tool
  - `mandate_text: str | None = None` (optional)
  - Empty string clears the field
  - Null/omitted preserves existing value
- **Validation**: 
  - Max length 5000 chars
  - No profanity/abuse filtering (business context)
  - Trim whitespace

### FR3: CPCS Scoring
- **Include in CPCS calculation**: mandate_text presence contributes to Mandate section score
  - Rationale: Detailed mandate text enables semantic document matching and refined search
  - Scoring: Mandate section (35% weight) checks both `mandate_type` AND `mandate_text`
    - If `mandate_type` set: 50% of mandate section (0.175 of total)
    - If `mandate_text` set: 50% of mandate section (0.175 of total)
    - Both fields independent: can have one, both, or neither
  - Justification: mandate_text will be used for document relevance scoring and semantic matching

### FR4: Document Search Enhancement (Future)
- **Use mandate_text to enhance document search ranking for clients**
  - Generate embeddings for mandate_text in ChromaDB
  - Use in relevance scoring: match document content to mandate description
  - Combine semantic similarity with graph-based relevance
  - Enable mandate-aware document filtering and ranking
- Enable "find clients with similar mandates" queries
- **Phase 1**: Storage + CPCS scoring; semantic search enhancement deferred to Phase 2

### FR5: UI Display
- **Read-only view**: Show in client profile panel (expandable text area if long)
- **Edit mode**: Multi-line textarea (4-6 rows), character counter, save/cancel
- **Empty state**: "No mandate text provided" or similar
- Refer to [docs/ui-llm-client-profile-note.md](ui-llm-client-profile-note.md) for integration

## Non-Functional Requirements

### NFR1: Performance
- Field stored as Neo4j property (no performance impact vs other profile fields)
- Cypher queries return mandate_text alongside other profile properties
- No indexing required for Phase 1

### NFR2: Security
- Honor existing group-based access control (same as `mandate_type`)
- No special encryption (treat as business data, not PII)
- Audit logging: log updates via standard client_service audit trail

### NFR3: Data Quality
- No automatic content moderation (assume professional context)
- No format restrictions (markdown, plain text, etc. all accepted)
- Preserve original formatting/whitespace

## Migration Strategy
- **Backward compatible**: Existing clients have `mandate_text = null`
- **No schema migration**: Add property to existing ClientProfile nodes on first update
- **No data backfill**: Field remains null until explicitly set
- **Rollback safe**: Can ignore field in queries; no breaking changes

## Testing Strategy
1. **Unit tests**: Validate length limits, null handling, update logic
2. **Integration tests**: 
   - Create client, update mandate_text, verify stored
   - Update mandate_text multiple times (overwrite)
   - Clear mandate_text (set empty string)
   - Verify get_client_profile returns mandate_text
3. **CPCS tests**: Verify score unchanged when mandate_text present
4. **Permission tests**: Verify group-based access control applies

## Design Decisions (Confirmed)
1. **Should mandate_text replace mandate_type in CPCS?**
   - Decision: **No**. Both fields contribute independently to Mandate section (50%/50% split).
2. **Should we extract structured data from mandate_text via LLM?**
   - Decision: **Deferred to Phase 2**. Will be used to enhance document search ranking for clients (semantic + graph match).
3. **Should we validate against known mandate patterns?**
   - Decision: **No**. Over-constraining reduces value of free text.
4. **Character limit justification?**
   - Decision: **5000 chars approved**.
   - 5000 chars ≈ 1000 words ≈ 2 pages
   - Sufficient for detailed mandate, not a full prospectus
   - Prevents abuse/storage bloat

## Success Metrics
- % of clients with mandate_text populated (target: >50% within 6 months)
- Avg character count (expect 500-1500 range)
- User feedback on field utility
- Document relevance improvements (future, post-semantic analysis)

## Dependencies
- Neo4j 5.x (properties on nodes)
- Existing auth/group framework
- MCP tool infrastructure (update_client_profile)

## Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Storage bloat if users paste entire prospectuses | Low | 5000 char limit prevents |
| Inconsistent data quality (typos, abbreviations) | Medium | Accept as trade-off for flexibility |
| Duplicate info between mandate_type and mandate_text | Low | Guidance in UI/docs to use text for details |
| Performance degradation on large text queries | Low | No full-text search in Phase 1 |

## Future Enhancements (Out of Scope for Phase 1)
- LLM-based mandate extraction from uploaded documents
- Semantic search: "Find clients with ESG focus"
- Auto-suggest mandate_type based on mandate_text analysis
- Change tracking/versioning (audit history of mandate changes)
- Templates for common mandate structures
