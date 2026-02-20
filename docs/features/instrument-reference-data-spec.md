# Instrument Reference Data Specification

## Overview

This document defines a first-class instrument reference data capability, covering MCP tools, CLI management, data model updates, and migration from direct Neo4j writes. The goal is to make instruments authoritative and updatable, not just auto-created stubs during ingestion.

## Problem Statement

- Instruments are auto-created during ingestion with minimal fields and no lifecycle management.
- There is no MCP-first interface to create, update, or defunct instruments.
- Identifiers beyond ticker (RIC, Bloomberg, ISIN, CUSIP) are not modeled or resolvable.
- Universe bootstrap scripts write directly to Neo4j and bypass auth and validation.

## Goals

- Provide MCP tools for instrument CRUD with defunct (no delete).
- Add management script `manage_instrument.sh` (MCP-only) similar to `manage_client.sh`.
- Migrate universe bootstrap to use the management script.
- Extend instrument model to support multiple identifiers and aliases.
- Maintain backward compatibility with existing instruments created by ingestion.

## Non-Goals

- Build a full reference data vendor integration (OpenFIGI, Bloomberg, etc).
- Backfill all historical instruments at once.
- Change document ingestion semantics beyond identifier resolution.

## Current Model Summary

- `Instrument` nodes use `guid` and `ticker` with minimal metadata.
- Ingestion auto-creates `Instrument` nodes when tickers are extracted.
- `create_instrument()` exists in [app/services/graph_index.py](app/services/graph_index.py) but has no MCP wrapper.

## Proposed Data Model

### Instrument Node

Required fields:
- `guid`: UUID, system-of-record key (immutable)
- `canonical_symbol`: string, business key `TICKER:MIC` (e.g., `AAPL:XNAS`)
- `ticker`: string, primary tradeable symbol
- `mic`: string, ISO 10383 Market Identifier Code (e.g., `XNAS`, `XNYS`)
- `name`: string
- `instrument_type`: string (STOCK, ETF, etc)
- `status`: string `ACTIVE|DEFUNCT`

Optional fields:
- `currency`, `country`
- `defunct_at`, `defunct_reason`
- `successor_guid`: UUID of the new instrument (if rebrand/merger)
- `created_at`, `updated_at`, `updated_by`, `source`
- `identifiers`: map of external identifiers
- `aliases`: list of alternate names (e.g. "Google" for GOOGL)

### Identifier Support

Start with an inline map on `Instrument`:

```
identifiers: {
  ticker: "AAPL",
  isin: "US0378331005",
  ric: "AAPL.O",
  bloomberg: "AAPL US",
  cusip: "037833100"
}
```

Future extension (optional): dedicated `Identifier` nodes and `HAS_IDENTIFIER` edges.

### Constraints

- Unique constraint on `Instrument.guid`.
- Unique constraint on `Instrument.canonical_symbol` (Business Key).
- Identifier values are not enforced unique in v1 to avoid migration friction.

## MCP Tools

### tool: instrument.create
- Create an instrument.
- Auto-generates `guid` (UUID) if not provided.
- Enforces `canonical_symbol` uniqueness.

### tool: instrument.update
- Update mutable fields (name, mic, status).
- **Critical:** Allows updating `ticker` only if it's a correction. For actual ticker changes (rebrand), use `defunct` + new `create`.

### tool: instrument.get
- Fetch by `guid`, `canonical_symbol`, or any identifier.
- Returns successor info if status is DEFUNCT.

### tool: instrument.list
- Filter by `status`, `ticker`, `mic`, `instrument_type`.

### tool: instrument.defunct
- Set `status=DEFUNCT` and `defunct_at`.
- Optional: `successor_guid` to link to new entity (e.g., FB -> META).
- Never delete node or relationships.

### tool: instrument.resolve
- Map any identifier (ticker, ric, bloomberg, isin, cusip) to `guid`.
- If resolved instrument is DEFUNCT with `successor_guid`, return the successor (with metadata indicating redirect).

## Auth and Permissions

- New permission group `refdata-admin` or reuse admin for now.
- `instrument.create/update/defunct` require admin or refdata-admin.
- `instrument.get/list/resolve` allow read-only access for normal users.

## manage_instrument.sh

CLI wrapper for MCP tools.

Examples:
```
# Create
./scripts/manage_instrument.sh --token $TOKEN create \
  --ticker AAPL --mic XNAS --name "Apple Inc." \
  --type STOCK --currency USD --country US --isin US0378331005 \
  --ric AAPL.O --bloomberg "AAPL US" --cusip 037833100

# Defunct (Rebrand)
./scripts/manage_instrument.sh --token $TOKEN defunct \
  --ticker FB --mic XNAS --reason "Rebrand to META" --successor <META_GUID>

# Resolve
./scripts/manage_instrument.sh --token $TOKEN resolve --identifier "AAPL.O"
```

## Universe Bootstrap Migration

- Replace direct `MERGE (i:Instrument ...)` in [simulation/load_simulation_data.py](simulation/load_simulation_data.py) with `manage_instrument.sh create`.
- Add a `--source simulation` field so reference data origin is explicit.
- Keep a `--skip-instrument-bootstrap` flag to reuse existing universe.

## Ingestion Behavior Changes

- During ingestion, attempt `instrument.resolve` for any identifier.
- If `strict_ticker_validation` is enabled and no match, do not auto-create.
- If strict mode is off and unknown, still auto-create but mark:
  - `source=ingest-auto`
  - `status=ACTIVE`
  - `identifiers.ticker=<ticker>`

## Migration Strategy

1. Add `primary_id` to existing instruments:
   - If `guid` is `TICKER:EXCHANGE`, use that.
   - If `guid` is `inst-TICKER`, set `primary_id=TICKER:UNKNOWN`.
2. Add default `status=ACTIVE` where missing.
3. Preserve all existing relationships.

## Logging and Audit

- All tool actions log via `StructuredLogger`.
- Include `instrument_id`, `operation`, `actor`, `source`, and `result`.

## Risks

- Mixed identifiers from ingestion could create duplicates if resolution is not strict.
- Migration must preserve existing guid usage in code to avoid breaking queries.

## Open Questions

- Do we standardize exchange codes (NYSE, NASDAQ) or accept free text?
- Should identifier values be normalized (case, whitespace) at ingest time?
- Should `instrument.resolve` prefer ACTIVE instruments when multiple matches exist?
