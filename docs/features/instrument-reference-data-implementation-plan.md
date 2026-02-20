# Instrument Reference Data - Implementation Plan

## Pre-Implementation
- [ ] **Spec Review**: Peer review [instrument-reference-data-spec.md](instrument-reference-data-spec.md) for simplifications/refinements
- [ ] **Tests Baseline**: Run `./scripts/run_tests.sh` - all tests must pass before starting

---

## Phase 1: Data Model and Constraints

### Step 1.1: Update Schema Documentation
**Goal**: Document new instrument fields and identifier support
**Files**:
- [docs/neo4j-schema.md](../neo4j-schema.md)
- [app/services/graph_index.py](../app/services/graph_index.py)

**Changes**:
- [ ] Add `primary_id`, `status`, `identifiers`, `aliases` to Instrument schema notes
- [ ] Document `DEFUNCT` behavior and non-delete policy
- [ ] Add notes on identifier resolution behavior

**Test**: None (documentation only)

---

### Step 1.2: Add Constraints for primary_id
**Goal**: Enforce unique canonical ID
**Files**:
- [app/services/graph_index.py](../app/services/graph_index.py)

**Changes**:
- [ ] Add constraint `instrument_primary_id_unique` on `Instrument.primary_id`
- [ ] Keep `instrument_ticker_unique` for compatibility

**Test**:
- `./scripts/run_tests.sh` (ensure no constraint violations)

---

## Phase 2: MCP Tooling

### Step 2.1: Add Instrument MCP Tools
**Goal**: MCP-first CRUD for instruments
**Files**:
- [app/tools/instrument_tools.py](../app/tools/instrument_tools.py) (new)
- [app/mcp_server/router.py](../app/mcp_server/router.py) (or equivalent tool registration)
- [app/services/graph_index.py](../app/services/graph_index.py)

**Changes**:
- [ ] Implement tool handlers for create, update, get, list, defunct, resolve
- [ ] Enforce admin or `refdata-admin` permissions for writes
- [ ] Use `StructuredLogger` with context

**Tests**:
- Add `test_instrument_tools_auth.py`
- Add `test_instrument_tools_crud.py`

---

### Step 2.2: Identifier Resolution Logic
**Goal**: Support mapping from RIC, Bloomberg, ISIN, CUSIP to canonical instrument
**Files**:
- [app/services/instrument_service.py](../app/services/instrument_service.py) (new)
- [app/services/graph_index.py](../app/services/graph_index.py)

**Changes**:
- [ ] Add normalization for identifier inputs (trim, uppercase, collapse spaces)
- [ ] Implement `resolve_identifier()` query
- [ ] Prefer `status=ACTIVE` when multiple matches

**Tests**:
- Add `test_instrument_resolve.py`

---

## Phase 3: CLI Management Script

### Step 3.1: `manage_instrument.sh` Wrapper
**Goal**: Provide MCP-only CLI for instrument lifecycle
**Files**:
- [scripts/manage_instrument.sh](../scripts/manage_instrument.sh) (new)
- [scripts/manage_instrument.py](../scripts/manage_instrument.py) (new)

**Changes**:
- [ ] Match `manage_client.sh` style (`--docker`, `--token`)
- [ ] Commands: create, update, get, list, defunct, resolve

**Tests**:
- Manual smoke test using `--token` and dev stack

---

## Phase 4: Universe Bootstrap Migration

### Step 4.1: Migrate Simulation Universe Load
**Goal**: Use MCP-managed instruments instead of direct Neo4j writes
**Files**:
- [simulation/load_simulation_data.py](../simulation/load_simulation_data.py)
- [simulation/run_simulation.py](../simulation/run_simulation.py)

**Changes**:
- [ ] Replace direct `MERGE (i:Instrument ...)` with `manage_instrument.sh create`
- [ ] Add `--skip-instrument-bootstrap` flag
- [ ] Set `source=simulation` when creating instruments

**Tests**:
- Run `./simulation/run_simulation.sh --count 0 --verbose`

---

## Phase 5: Ingestion Updates

### Step 5.1: Use Identifier Resolution in Ingest
**Goal**: Resolve instruments by non-ticker identifiers if present in content
**Files**:
- [app/services/ingest_service.py](../app/services/ingest_service.py)
- [app/prompts/graph_extraction.py](../app/prompts/graph_extraction.py)

**Changes**:
- [ ] Extend extraction to carry `identifier_type` and `identifier_value`
- [ ] Call `instrument.resolve` before auto-create
- [ ] Mark auto-created instruments with `source=ingest-auto`

**Tests**:
- Add `test_ingest_identifier_resolution.py`

---

## Phase 6: Migration and Backfill

### Step 6.1: Backfill primary_id and status
**Goal**: Add canonical IDs to existing instruments
**Files**:
- [scripts/migrate_instrument_ids.py](../scripts/migrate_instrument_ids.py) (new)

**Changes**:
- [ ] Set `primary_id` from existing `guid` or `ticker:UNKNOWN`
- [ ] Set `status=ACTIVE` where missing
- [ ] Preserve existing `guid` and relationships

**Tests**:
- Run migration in a dev copy, verify counts match before and after

---

## Post-Implementation

- [ ] **Spec Confirmation**: Validate implementation matches spec
- [ ] **Tests**: Run `./scripts/run_tests.sh`
- [ ] **Docs**: Update README or feature docs if required
