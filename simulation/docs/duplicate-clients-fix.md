# Simulation Duplicate Clients Fix

## Problem

The simulation was creating duplicate clients every time it ran because:

1. **`generate_synthetic_clients.py`** creates `MockClient` objects with hardcoded GUIDs:
   - Quantum Momentum Partners: `550e8400-e29b-41d4-a716-446655440001`
   - Nebula Retirement Fund: `550e8400-e29b-41d4-a716-446655440002`
   - DiamondHands420: `550e8400-e29b-41d4-a716-446655440003`

2. **`load_simulation_data.py`** ignored these GUIDs and called `_create_client_via_mcp()` which generates **new random UUIDs** every time

3. **No existence check** was performed before creating clients, leading to duplicates on every `run_simulation.py` execution

## Evidence

Before fix:
```bash
$ ./scripts/manage_client.sh --docker --token $TOKEN list | jq -r '.data.clients[] | .name'
Quantum Momentum Partners
Quantum Momentum Partners        # Duplicate!
DiamondHands420
DiamondHands420                 # Duplicate!
Nebula Retirement Fund
Nebula Retirement Fund          # Duplicate!
Test Client Alpha
Test Mandate Client
Test Mandate Client v2
```

## Solution

Added duplicate prevention logic to `load_simulation_data.py`:

1. **New function** `_get_existing_simulation_clients()` - queries existing clients via `list_clients` MCP tool
2. **Check before create** - maps client names to GUIDs and skips creation if client already exists
3. **Idempotent behavior** - simulation can now be run multiple times without creating duplicates

### Code Changes

```python
def _get_existing_simulation_clients(token: str) -> dict[str, str]:
    """Get existing simulation clients by name.
    
    Returns:
        Dict mapping client name to client_guid
    """
    # ... calls list_clients via manage_client.sh ...
    return {c["name"]: c["client_guid"] for c in clients}
```

```python
# In load_clients section:
existing_clients = _get_existing_simulation_clients(token)
logger.info(f"Found {len(existing_clients)} existing clients in database")

for client in clients:
    if client.name in existing_clients:
        existing_guid = existing_clients[client.name]
        logger.info(f"Client '{client.name}' already exists ({existing_guid}), skipping creation...")
        continue
    
    # Create new client only if it doesn't exist
    logger.info(f"Creating client: {client.name}")
    # ...
```

## Verification

After fix:
```bash
$ # Run simulation
$ uv run simulation/run_simulation.py --count 0 --skip-universe

2026-02-03 13:34:46 - INFO - Checking for existing simulation clients...
2026-02-03 13:34:46 - INFO - Found 6 existing clients in database
2026-02-03 13:34:46 - INFO - Creating/updating 3 Clients via MCP...
2026-02-03 13:34:46 - INFO - Client 'Quantum Momentum Partners' already exists (8e2c7b18...), skipping creation...
2026-02-03 13:34:46 - INFO - Client 'Nebula Retirement Fund' already exists (912811cc...), skipping creation...
2026-02-03 13:34:46 - INFO - Client 'DiamondHands420' already exists (6466c557...), skipping creation...

✅ SUCCESS: No duplicate clients created (9 == 9)
```

## Future Enhancements

1. **Use hardcoded GUIDs from generator** - Pass `client.guid` to `_create_client_via_mcp()` to use deterministic UUIDs
2. **Update existing clients** - Instead of skipping, optionally update profile/holdings/watchlist for existing clients
3. **Simulation metadata tag** - Add `simulation_id` tag to clients for easier filtering/cleanup
4. **Cleanup command** - Add `--reset-clients` flag to remove all simulation clients before recreating

## Testing

```bash
# Test 1: Run twice, verify no duplicates
uv run simulation/run_simulation.py --count 0 --skip-universe
uv run simulation/run_simulation.py --count 0 --skip-universe  # Should skip all 3 clients

# Test 2: Clean existing clients, verify creation
./scripts/manage_client.sh --docker --token $TOKEN delete <guid>  # Delete simulation clients
uv run simulation/run_simulation.py --count 0 --skip-universe   # Should create 3 clients

# Test 3: Verify client count unchanged
BEFORE=$(./scripts/manage_client.sh --docker --token $TOKEN list | jq '.data.clients | length')
uv run simulation/run_simulation.py --count 0 --skip-universe
AFTER=$(./scripts/manage_client.sh --docker --token $TOKEN list | jq '.data.clients | length')
[ "$BEFORE" -eq "$AFTER" ] && echo "✅ PASS" || echo "❌ FAIL"
```

## Related Files

- [simulation/load_simulation_data.py](../load_simulation_data.py) - Main fix location
- [simulation/generate_synthetic_clients.py](../generate_synthetic_clients.py) - Client generation with hardcoded GUIDs
- [simulation/run_simulation.py](../run_simulation.py) - Orchestrates simulation execution

## Date

February 3, 2026
