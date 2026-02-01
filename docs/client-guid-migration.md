# Client GUID Format Fix - Migration Guide

## Issue
Client GUIDs were using short string identifiers (e.g., "client-hedge-fund") instead of proper UUID format, causing validation errors when calling MCP tools that require 36-character UUIDs.

## Root Cause
Simulation data generation used human-readable string IDs for easy reference during development, but MCP tool validation enforces UUID format for all client_guid parameters.

## Solution
Replaced short string GUIDs with stable UUIDs across all simulation files.

## Changes Made

### Simulation Code Updates
1. **generate_synthetic_clients.py** - Updated MockClient creation:
   - Hedge Fund: `client-hedge-fund` → `550e8400-e29b-41d4-a716-446655440001`
   - Pension Fund: `client-pension-fund` → `550e8400-e29b-41d4-a716-446655440002`
   - Retail Trader: `client-retail` → `550e8400-e29b-41d4-a716-446655440003`

2. **query_client_feed.py** - Updated documentation and help text
3. **generate_client_ips.py** - Updated client GUID references
4. **demo_ips_filtering.py** - Updated client list
5. **generate_synthetic_stories.py** - Updated client portfolio mapping

### UUID Selection Rationale
Used sequential UUIDs based on standard UUID format (RFC 4122) with stable, memorable pattern:
- Base: `550e8400-e29b-41d4-a716-44665544000X`
- Last digit increments: 1 (hedge), 2 (pension), 3 (retail)

This ensures:
- Valid UUID format (36 characters with hyphens)
- Stable across resets (deterministic, not random)
- Easy to identify in logs/debugging

## Migration Steps

### 1. Clear Existing Client Data
```bash
# Option A: Full database reset (recommended)
./scripts/purge_local_data.sh --confirm

# Option B: Manual Neo4j cleanup (if you want to preserve other data)
docker exec gofr-neo4j cypher-shell -u neo4j -p $NEO4J_PASSWORD \
  "MATCH (c:Client) WHERE c.simulation_id IN ['phase2', 'phase1'] DETACH DELETE c"
```

### 2. Reload Simulation Data
```bash
# Reload universe and clients with new UUIDs
uv run simulation/run_simulation.py --count 10
```

### 3. Verify Fix
```bash
# Test list_clients
curl -X POST "http://gofr-iq-mcp:8080/tools/list_clients" \
  -H "Content-Type: application/json" \
  -d '{"auth_tokens":["<admin_token>"]}'

# Should return clients with proper UUID format:
# {
#   "clients": [
#     {
#       "client_guid": "550e8400-e29b-41d4-a716-446655440001",
#       "name": "Apex Capital",
#       ...
#     }
#   ]
# }

# Test get_client_profile with returned GUID
curl -X POST "http://gofr-iq-mcp:8080/tools/get_client_profile" \
  -H "Content-Type: application/json" \
  -d '{
    "client_guid":"550e8400-e29b-41d4-a716-446655440001",
    "auth_tokens":["<admin_token>"]
  }'

# Should now work without validation errors
```

## Client Reference Guide

### Stable Client GUIDs
| Name | Type | GUID | Holdings |
|------|------|------|----------|
| **Apex Capital** | Hedge Fund | `550e8400-e29b-41d4-a716-446655440001` | QNTM, BANKO, VIT, GTX |
| **Teachers Retirement System** | Pension Fund | `550e8400-e29b-41d4-a716-446655440002` | OMNI, SHOPM, TRUCK |
| **DiamondHands420** | Retail Trader | `550e8400-e29b-41d4-a716-446655440003` | VELO, BLK |

### Quick Test Commands
```bash
# Query hedge fund feed
uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440001 --limit 10

# Query pension fund feed
uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440002 --limit 10

# Query retail trader feed
uv run simulation/query_client_feed.py --client 550e8400-e29b-41d4-a716-446655440003 --limit 10
```

## Validation Checklist
- [x] Updated generate_synthetic_clients.py with UUID format
- [x] Updated query_client_feed.py documentation
- [x] Updated generate_client_ips.py references
- [x] Updated demo_ips_filtering.py client list
- [x] Updated generate_synthetic_stories.py client mapping
- [ ] Reset simulation data (run by user)
- [ ] Test list_clients returns UUID format
- [ ] Test get_client_profile accepts returned GUIDs
- [ ] Test client feed queries work
- [ ] Verify GOFR Console UI client detail view

## Impact
- **Before**: list_clients → get_client_profile workflow broken
- **After**: Seamless client management across all MCP tools
- **Breaking Change**: Existing client GUIDs invalidated (simulation data only)
- **Production Impact**: None (simulation data not used in production)

## Related Files
- Bug Report: [docs/bug-report-client-guid-format.md] (if saved)
- Neo4j Schema: [docs/neo4j-schema.md]
- MCP Tool Interface: [docs/mcp-tool-interface.md]

## Date
2026-02-01
