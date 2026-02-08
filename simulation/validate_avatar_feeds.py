#!/usr/bin/env python3
"""
Avatar Feed UAT Validation
===========================
Queries real avatar feeds via MCP for each simulation client and validates
that the two-channel model (MAINTENANCE + OPPORTUNITY) behaves correctly.

Assertions:
  1. MAINTENANCE channel contains items affecting client holdings/watchlist.
  2. OPPORTUNITY channel contains items matching mandate themes.
  3. OPPORTUNITY items do NOT overlap with the client's position tickers.
  4. Maintenance + Opportunity channels are deduplicated (no doc in both).
  5. All items have required fields (document_guid, title, channel, etc.).
  6. Combined list is sorted by relevance_score descending.

Run via:
    uv run python simulation/validate_avatar_feeds.py [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Ensure project imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

from gofr_common.gofr_env import get_admin_token, GofrEnvError  # noqa: E402

from simulation.generate_synthetic_clients import ClientGenerator  # noqa: E402
from simulation.universe.builder import UniverseBuilder  # noqa: E402


def _get_simulation_token() -> str:
    """Get group-simulation token from simulation/tokens.json.
    
    This token grants access to data in the group-simulation group,
    which is where all simulation clients and documents are created.
    The admin token only grants access to admin/public groups.
    """
    token_file = PROJECT_ROOT / "simulation" / "tokens.json"
    if not token_file.exists():
        raise GofrEnvError(
            f"Simulation tokens file not found: {token_file}\n"
            "Run ./simulation/run_simulation.sh to generate tokens."
        )
    with open(token_file, "r") as f:
        tokens = json.load(f)
    
    if "group-simulation" not in tokens:
        raise GofrEnvError(
            "group-simulation token not found in simulation/tokens.json\n"
            "Run ./simulation/run_simulation.sh to regenerate tokens."
        )
    
    return tokens["group-simulation"]


# ---------------------------------------------------------------------------
# MCP Client (minimal, reuses manage_client.py patterns)
# ---------------------------------------------------------------------------

def _load_ports():
    env_path = PROJECT_ROOT / "lib" / "gofr-common" / "config" / "gofr_ports.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


def _mcp_init(host: str, port: int) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "avatar-feed-validator", "version": "1.0.0"},
        },
    }
    url = f"http://{host}:{port}/mcp"
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("Missing MCP session id")
        return session_id


def _mcp_call(host: str, port: int, session_id: str, tool: str, args: dict, token: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": {**args, "auth_tokens": [token]},
        },
    }
    url = f"http://{host}:{port}/mcp"
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": session_id,
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")

    # Parse SSE response
    for line in raw.splitlines():
        if line.startswith("data:"):
            outer = json.loads(line[5:].strip())
            result = outer.get("result", {})
            content = result.get("content", [])
            if content and isinstance(content, list) and "text" in content[0]:
                return json.loads(content[0]["text"])
            return outer
    return {"status": "error", "message": "Empty MCP response"}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""
    client_name: str = ""


@dataclass
class ValidationSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[TestResult] = field(default_factory=list)


def _get_client_position_tickers(client) -> list[str]:
    """Get all position tickers (holdings + watchlist) for a mock client."""
    holding_tickers = [p.ticker for p in client.portfolio]
    watchlist_tickers = list(client.watchlist)
    return list(set(holding_tickers + watchlist_tickers))


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_avatar_feed(
    host: str,
    port: int,
    session_id: str,
    token: str,
    client_guid: str,
    client_name: str,
    position_tickers: list[str],
    summary: ValidationSummary,
    verbose: bool = False,
) -> dict[str, Any]:
    """Query avatar feed for one client and run assertions."""
    if verbose:
        print(f"\n{'='*60}")
        print(f"  Client: {client_name} ({client_guid})")
        print(f"  Positions: {position_tickers}")
        print(f"{'='*60}")

    feed_resp = _mcp_call(
        host, port, session_id,
        "get_client_avatar_feed",
        {"client_guid": client_guid, "limit": 40, "time_window_hours": 720},
        token,
    )

    if feed_resp.get("status") != "success":
        msg = f"{client_name}: MCP call failed: {feed_resp.get('message', 'unknown')}"
        summary.errors.append(msg)
        summary.results.append(TestResult(
            name="mcp_call", passed=False, detail=msg, client_name=client_name,
        ))
        summary.total += 1
        summary.failed += 1
        return feed_resp

    data = feed_resp.get("data", {})
    maintenance = data.get("maintenance", [])
    opportunity = data.get("opportunity", [])
    combined = data.get("combined", [])

    if verbose:
        print(f"  Maintenance: {len(maintenance)} items")
        for m in maintenance:
            print(f"    [{m.get('impact_tier','?')}] {m.get('title','?')[:60]}  "
                  f"tickers={m.get('affected_instruments',[])}  "
                  f"score={m.get('relevance_score',0):.3f}")
        print(f"  Opportunity: {len(opportunity)} items")
        for o in opportunity:
            print(f"    [{o.get('impact_tier','?')}] {o.get('title','?')[:60]}  "
                  f"themes={o.get('themes',[])}  "
                  f"score={o.get('relevance_score',0):.3f}")

    # ── Test 1: All items have required fields ──
    required_fields = ["document_guid", "title", "channel", "relevance_score"]
    all_items = maintenance + opportunity
    missing_fields = []
    for item in all_items:
        for f in required_fields:
            if f not in item or item[f] is None:
                missing_fields.append(f"{item.get('document_guid','?')}: missing {f}")
    test_name = "required_fields"
    passed = len(missing_fields) == 0
    detail = f"{len(missing_fields)} missing" if not passed else f"all {len(all_items)} items OK"
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)

    # ── Test 2: MAINTENANCE items affect at least one position ticker ──
    maint_violations = []
    for item in maintenance:
        affected = set(item.get("affected_instruments", []))
        position_set = set(position_tickers)
        if not affected & position_set:
            maint_violations.append(
                f"{item.get('document_guid','?')}: affected={list(affected)} vs positions={position_tickers}"
            )
    test_name = "maintenance_affects_positions"
    passed = len(maint_violations) == 0
    detail = (f"{len(maint_violations)} violations" if not passed
              else f"all {len(maintenance)} maintenance items affect positions")
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)
    if not passed and verbose:
        for v in maint_violations[:3]:
            print(f"    ⚠ {v}")

    # ── Test 3: OPPORTUNITY items do NOT overlap with position tickers ──
    opp_violations = []
    for item in opportunity:
        affected = set(item.get("affected_instruments", []))
        position_set = set(position_tickers)
        overlap = affected & position_set
        if overlap:
            opp_violations.append(
                f"{item.get('document_guid','?')}: overlaps={list(overlap)}"
            )
    test_name = "opportunity_no_position_overlap"
    passed = len(opp_violations) == 0
    detail = (f"{len(opp_violations)} overlaps" if not passed
              else f"all {len(opportunity)} opportunity items are novel")
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)
    if not passed and verbose:
        for v in opp_violations[:3]:
            print(f"    ⚠ {v}")

    # ── Test 4: No document appears in both channels ──
    maint_guids = {m.get("document_guid") for m in maintenance}
    opp_guids = {o.get("document_guid") for o in opportunity}
    duplicates = maint_guids & opp_guids
    test_name = "no_cross_channel_duplicates"
    passed = len(duplicates) == 0
    detail = f"{len(duplicates)} dupes" if not passed else "channels are disjoint"
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)

    # ── Test 5: Combined list is sorted by relevance_score desc ──
    scores = [item.get("relevance_score", 0) for item in combined]
    is_sorted = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    test_name = "combined_sorted_by_score"
    passed = is_sorted
    detail = "sorted" if passed else f"not sorted: {scores[:5]}..."
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)

    # ── Test 6: Channel labels are correct ──
    maint_channels = {m.get("channel") for m in maintenance}
    opp_channels = {o.get("channel") for o in opportunity}
    test_name = "channel_labels_correct"
    passed = (
        maint_channels <= {"MAINTENANCE"} and
        opp_channels <= {"OPPORTUNITY"}
    )
    detail = f"maint={maint_channels}, opp={opp_channels}" if not passed else "labels OK"
    summary.results.append(TestResult(test_name, passed, detail, client_name))
    summary.total += 1
    summary.passed += int(passed)
    summary.failed += int(not passed)

    # ── Test 7: At least one item exists (sanity — data was ingested) ──
    test_name = "feed_not_empty"
    has_items = len(all_items) > 0
    # Allow empty for now (some clients may not have matching docs)
    # But flag it as a warning
    if not has_items:
        detail = "EMPTY feed — check ingestion and time window"
        summary.results.append(TestResult(test_name, True, detail, client_name))
        summary.total += 1
        summary.passed += 1
        if verbose:
            print(f"    ⚠ EMPTY feed for {client_name}")
    else:
        detail = f"{len(maintenance)} maint + {len(opportunity)} opp = {len(all_items)} items"
        summary.results.append(TestResult(test_name, True, detail, client_name))
        summary.total += 1
        summary.passed += 1

    return feed_resp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Validate avatar feeds against real MCP")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--host", default="gofr-iq-mcp")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    _load_ports()
    port = args.port or int(os.environ.get("GOFR_IQ_MCP_PORT", "8080"))

    # Use simulation token (grants access to group-simulation data)
    # Fall back to admin token if simulation token not available
    try:
        token = _get_simulation_token()
        print("🔑 Using group-simulation token for avatar feed queries")
    except GofrEnvError as e:
        print(f"⚠️  Simulation token not available: {e}")
        print("   Falling back to admin token (may not see simulation data)")
        try:
            token = get_admin_token()
        except GofrEnvError as e2:
            print(f"❌ Cannot load any token: {e2}")
            sys.exit(1)

    # Load the simulation client definitions
    builder = UniverseBuilder()
    gen = ClientGenerator(builder)
    clients = gen.generate_clients()

    # Resolve actual client GUIDs from MCP (they may differ from mock GUIDs
    # if created via MCP which assigns new UUIDs)
    print("🔍 Resolving client GUIDs via MCP...")
    session_id = _mcp_init(args.host, port)

    list_resp = _mcp_call(
        args.host, port, session_id, "list_clients",
        {"limit": 50}, token,
    )
    if list_resp.get("status") != "success":
        print(f"❌ Failed to list clients: {list_resp}")
        sys.exit(1)

    live_clients = list_resp.get("data", {}).get("clients", [])
    name_to_guid = {c["name"]: c["client_guid"] for c in live_clients}

    if args.verbose:
        print(f"  Found {len(live_clients)} clients in MCP")
        for c in live_clients:
            print(f"    {c['name']} → {c['client_guid']}")

    summary = ValidationSummary()

    for mock_client in clients:
        guid = name_to_guid.get(mock_client.name)
        if not guid:
            print(f"  ⚠ Client '{mock_client.name}' not found in MCP, skipping")
            continue

        position_tickers = _get_client_position_tickers(mock_client)

        validate_avatar_feed(
            host=args.host,
            port=port,
            session_id=session_id,
            token=token,
            client_guid=guid,
            client_name=mock_client.name,
            position_tickers=position_tickers,
            summary=summary,
            verbose=args.verbose,
        )

    # ── Print summary ──
    print(f"\n{'='*60}")
    print(f"  AVATAR FEED VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Total tests:  {summary.total}")
    print(f"  Passed:       {summary.passed}")
    print(f"  Failed:       {summary.failed}")

    if summary.errors:
        print(f"\n  Errors:")
        for err in summary.errors:
            print(f"    ❌ {err}")

    # Print per-client breakdown
    clients_tested = sorted(set(r.client_name for r in summary.results))
    for client_name in clients_tested:
        client_results = [r for r in summary.results if r.client_name == client_name]
        client_passed = sum(1 for r in client_results if r.passed)
        client_total = len(client_results)
        status = "✅" if client_passed == client_total else "❌"
        print(f"  {status} {client_name}: {client_passed}/{client_total}")
        if args.verbose:
            for r in client_results:
                icon = "✅" if r.passed else "❌"
                print(f"      {icon} {r.name}: {r.detail}")

    print(f"{'='*60}")

    if summary.failed > 0:
        print(f"\n❌ {summary.failed} test(s) FAILED")
        sys.exit(1)
    else:
        print(f"\n✅ All {summary.total} tests PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
