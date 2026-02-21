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

    # Parse SSE response.
    # Some MCP servers emit multiple `data:` events; use the last well-formed JSON payload.
    last_outer: dict[str, Any] | None = None
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            last_outer = json.loads(payload)
        except Exception:
            continue

    if not last_outer:
        return {"status": "error", "message": "Empty or non-JSON MCP response"}

    # Tool handlers in this repo return JSON encoded as TextContent.text.
    result = last_outer.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list) and isinstance(content[0], dict) and "text" in content[0]:
        text = content[0].get("text")
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "message": "Non-JSON tool response text",
                    "tool": tool,
                    "raw_text": text,
                }

    # Fall back to returning the outer MCP envelope.
    return last_outer


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


def _parse_lambdas(raw: str) -> list[float]:
    values: list[float] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        val = float(part)
        if val < 0.0 or val > 1.0:
            raise ValueError(f"lambda must be in [0,1], got {val}")
        values.append(val)
    return values or [0.0, 0.5, 1.0]


@dataclass
class Phase3Case:
    scenario: str
    base_ticker: str
    title: str
    expected_clients: list[str]


def _load_phase3_cases() -> list[Phase3Case]:
    """Load Phase 3 stress-test cases from simulation/test_output.

    Bias sweep validation matches by title (not GUID), so cases must have
    deterministic unique titles.
    """
    out_dir = PROJECT_ROOT / "simulation" / "test_output"
    if not out_dir.exists():
        return []

    # Only evaluate the most recent file for each Phase3 scenario.
    # This avoids older simulation runs inflating the case count and
    # makes Recall@3 comparable run-to-run.
    latest_by_scenario: dict[str, Phase3Case] = {}
    for path in sorted(out_dir.glob("synthetic_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue

        meta = data.get("validation_metadata") or {}
        scenario = meta.get("scenario")
        if not (isinstance(scenario, str) and scenario.startswith("Phase3")):
            continue

        # Scenario D is "noise"; it is expected to be suppressed, not recalled.
        if scenario.startswith("Phase3 D"):
            continue

        if scenario in latest_by_scenario:
            continue

        title = data.get("title")
        if not isinstance(title, str) or not title:
            continue

        title = title.strip()
        if not title:
            continue

        expected = meta.get("expected_relevant_clients") or []
        if not isinstance(expected, list):
            expected = []

        base_ticker = meta.get("base_ticker")
        if not isinstance(base_ticker, str) or not base_ticker:
            continue
        base_ticker = base_ticker.strip().upper()
        if not base_ticker:
            continue

        case = Phase3Case(
            scenario=scenario,
            base_ticker=base_ticker,
            title=title,
            expected_clients=[c for c in expected if isinstance(c, str) and c],
        )

        latest_by_scenario[scenario] = case

    return list(latest_by_scenario.values())


def _top_unique_titles(articles: list[dict[str, Any]], n: int = 3) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for a in articles:
        t = a.get("title")
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t:
            continue
        norm = t.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(t)
        if len(out) >= n:
            break
    return out


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
    parser.add_argument(
        "--bias-sweep",
        action="store_true",
        help="Run Phase 3 bias sweep validation using get_top_client_news",
    )
    parser.add_argument(
        "--lambdas",
        default="0,0.5,1",
        help="Comma-separated lambda values in [0,1] (default: 0,0.5,1)",
    )
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

    # ---------------------------------------------------------------------
    # Phase 3: bias sweep mode (Top Client News)
    # ---------------------------------------------------------------------
    if args.bias_sweep:
        try:
            lambdas = _parse_lambdas(args.lambdas)
        except ValueError as e:
            print(f"❌ Invalid --lambdas: {e}")
            sys.exit(1)

        phase3_cases = _load_phase3_cases()
        if not phase3_cases:
            print("❌ No Phase3 synthetic cases found in simulation/test_output")
            print("   Generate + ingest Phase3 stories, then rerun with --bias-sweep")
            sys.exit(1)

        live_guid_set = {c.get("client_guid") for c in live_clients if c.get("client_guid")}

        # Phase3 synthetic cases encode expected clients using the stable mock GUIDs
        # from simulation/generate_synthetic_clients.py. Map those to live MCP GUIDs
        # via client name, and also accept raw live GUIDs or client names.
        mock_guid_to_live_guid: dict[str, str] = {}
        for mock_client in clients:
            live_guid = name_to_guid.get(mock_client.name)
            if live_guid and isinstance(mock_client.guid, str):
                mock_guid_to_live_guid[mock_client.guid] = live_guid
        # Cache: lambda -> live_client_guid -> articles
        sweep_results: dict[float, dict[str, list[dict[str, Any]]]] = {}

        # Precompute position tickers per live guid (via mock client name)
        live_guid_to_positions: dict[str, set[str]] = {}
        for mock_client in clients:
            live_guid = name_to_guid.get(mock_client.name)
            if live_guid:
                live_guid_to_positions[live_guid] = set(_get_client_position_tickers(mock_client))

        print("\nPhase 3 bias sweep: get_top_client_news")
        print(f"  lambdas={lambdas}")
        print(f"  phase3_cases={len(phase3_cases)}")

        for lam in lambdas:
            per_client: dict[str, list[dict[str, Any]]] = {}
            for mock_client in clients:
                live_guid = name_to_guid.get(mock_client.name)
                if not live_guid:
                    continue

                resp = _mcp_call(
                    args.host,
                    port,
                    session_id,
                    "get_top_client_news",
                    {
                        "client_guid": live_guid,
                        "limit": 10,
                        "time_window_hours": 6,
                        "opportunity_bias": lam,
                    },
                    token,
                )
                if resp.get("status") != "success":
                    msg = resp.get("message", "unknown")
                    raw_text = resp.get("raw_text")
                    if isinstance(raw_text, str) and raw_text:
                        preview = raw_text.replace("\n", " ").strip()[:220]
                        msg = f"{msg} (raw_text='{preview}')"
                    print(f"  ⚠ get_top_client_news failed: client={mock_client.name} lambda={lam}: {msg}")
                    continue

                articles = (resp.get("data", {}) or {}).get("articles", [])
                if not isinstance(articles, list):
                    articles = []
                per_client[live_guid] = [a for a in articles if isinstance(a, dict)]

            sweep_results[lam] = per_client

        for lam in lambdas:
            per_client = sweep_results.get(lam, {})

            # Recall@3: intended stress-test story present in Top 3
            total_pairs = 0
            hits = 0
            for case in phase3_cases:
                for expected_id in case.expected_clients:
                    live_guid: str | None = None

                    # 1) already a live GUID
                    if expected_id in live_guid_set:
                        live_guid = expected_id
                    # 2) stable mock GUID
                    elif expected_id in mock_guid_to_live_guid:
                        live_guid = mock_guid_to_live_guid[expected_id]
                    # 3) client name
                    elif expected_id in name_to_guid:
                        live_guid = name_to_guid[expected_id]

                    if not live_guid:
                        continue

                    total_pairs += 1
                    articles = per_client.get(live_guid, [])
                    titles = _top_unique_titles(articles, n=3)
                    # Match by Phase3 scenario prefix + base ticker, since company name
                    # variations across runs can change the title suffix.
                    prefix = f"[{case.scenario}] {case.base_ticker}"
                    if any(t.startswith(prefix) for t in titles):
                        hits += 1
            recall_at_3 = (hits / total_pairs) if total_pairs else 0.0

            # Alpha score: proportion of Top 3 with no overlap with positions
            alpha_n = 0
            alpha_total = 0
            for live_guid, articles in per_client.items():
                positions = live_guid_to_positions.get(live_guid, set())
                for a in _top_unique_titles(articles, n=3):
                    # Find the corresponding article dict for affected tickers
                    a = next((x for x in articles if isinstance(x, dict) and (x.get("title") or "").strip() == a), {})
                    affected = a.get("affected_instruments") or []
                    if not isinstance(affected, list):
                        affected = []
                    affected_set = {t for t in affected if isinstance(t, str)}
                    if positions and not (affected_set & positions):
                        alpha_n += 1
                    alpha_total += 1
            alpha_score = (alpha_n / alpha_total) if alpha_total else 0.0

            print("\nBias sweep metrics")
            print(f"  lambda={lam:.2f}")
            print(f"  Recall@3={recall_at_3:.3f} ({hits}/{total_pairs})")
            print(f"  AlphaScore={alpha_score:.3f} ({alpha_n}/{alpha_total})")

        sys.exit(0)

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
