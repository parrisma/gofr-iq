#!/usr/bin/env python3
"""Phase 4: Bias sensitivity measurement.

Sweeps opportunity_bias (lambda) for get_top_client_news and reports how Phase3
stress-test scenarios rank per client.

Intended usage (after generating + ingesting Phase3 docs):
  uv run python simulation/measure_bias_sensitivity.py --lambdas 0,0.25,0.5,0.75,1

Notes:
- Uses the same MCP JSON-RPC + SSE patterns as simulation/validate_avatar_feeds.py.
- Uses a tight time window (default 6h) to keep the measurement focused on the
  most recent simulation run.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

from simulation.validate_avatar_feeds import (
    _get_simulation_token,
    _load_ports,
    _mcp_call,
    _mcp_init,
    _parse_lambdas,
)


@dataclass(frozen=True)
class RankedItem:
    title: str
    scenario: str | None


def _parse_phase3_scenario(title: str) -> str | None:
    title = (title or "").strip()
    if not title.startswith("[Phase3"):
        return None
    end = title.find("]")
    if end <= 0:
        return None
    return title[1:end]


def _dedupe_titles(items: list[dict[str, Any]], n: int) -> list[RankedItem]:
    seen: set[str] = set()
    out: list[RankedItem] = []
    for item in items:
        title = item.get("title")
        if not isinstance(title, str):
            continue
        title = title.strip()
        if not title:
            continue
        norm = title.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(RankedItem(title=title, scenario=_parse_phase3_scenario(title)))
        if len(out) >= n:
            break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure bias sensitivity (Phase 4)")
    parser.add_argument("--host", default="gofr-iq-mcp")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--lambdas",
        default="0,0.25,0.5,0.75,1",
        help="Comma-separated lambda values in [0,1]",
    )
    parser.add_argument(
        "--time-window-hours",
        type=int,
        default=6,
        help="Time window for get_top_client_news (max 168)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many items to request (max 10)",
    )

    args = parser.parse_args()

    _load_ports()
    port = args.port or int(os.environ.get("GOFR_IQ_MCP_PORT", "8080"))

    lambdas = _parse_lambdas(args.lambdas)
    time_window_hours = int(args.time_window_hours)
    if time_window_hours < 1 or time_window_hours > 168:
        raise SystemExit("time-window-hours must be in [1,168]")

    limit = int(args.limit)
    if limit < 1 or limit > 10:
        raise SystemExit("limit must be in [1,10]")

    token = _get_simulation_token()
    session_id = _mcp_init(args.host, port)

    clients = _mcp_call(args.host, port, session_id, "list_clients", {"limit": 50}, token)
    if clients.get("status") != "success":
        raise SystemExit(f"list_clients failed: {clients}")

    live_clients = (clients.get("data", {}) or {}).get("clients", [])
    name_to_guid = {
        c.get("name"): c.get("client_guid")
        for c in live_clients
        if c.get("name") and c.get("client_guid")
    }

    # Pull results per lambda per client
    ranks: dict[float, dict[str, dict[str, int]]] = {}

    phase3_scenarios = [
        "Phase3 A Defense Tail Holding Failure",
        "Phase3 B Offense Thematic M&A",
        "Phase3 C Systemic Multi-Holding Shock",
    ]

    for lam in lambdas:
        per_client: dict[str, dict[str, int]] = {}
        for client_name, client_guid in sorted(name_to_guid.items()):
            resp = _mcp_call(
                args.host,
                port,
                session_id,
                "get_top_client_news",
                {
                    "client_guid": client_guid,
                    "limit": limit,
                    "time_window_hours": time_window_hours,
                    "opportunity_bias": lam,
                },
                token,
            )
            if resp.get("status") != "success":
                continue

            articles = (resp.get("data", {}) or {}).get("articles", [])
            if not isinstance(articles, list):
                articles = []

            top = _dedupe_titles([a for a in articles if isinstance(a, dict)], n=limit)

            scenario_to_rank: dict[str, int] = {}
            for idx, item in enumerate(top, 1):
                if item.scenario and item.scenario in phase3_scenarios:
                    scenario_to_rank.setdefault(item.scenario, idx)

            per_client[client_name] = scenario_to_rank

        ranks[lam] = per_client

    # Report
    print("Bias sensitivity: Phase3 scenario ranks")
    print(f"  time_window_hours={time_window_hours}")
    print(f"  lambdas={lambdas}")

    for client_name in sorted(name_to_guid.keys()):
        print(f"\nClient: {client_name}")
        for lam in lambdas:
            scenario_to_rank = ranks.get(lam, {}).get(client_name, {})
            a = scenario_to_rank.get(phase3_scenarios[0])
            b = scenario_to_rank.get(phase3_scenarios[1])
            c = scenario_to_rank.get(phase3_scenarios[2])
            print(f"  lambda={lam:.2f}: A={a} B={b} C={c}")

        # Crossover: first lambda where B outranks A (lower rank number)
        crossover = None
        for lam in lambdas:
            scenario_to_rank = ranks.get(lam, {}).get(client_name, {})
            a = scenario_to_rank.get(phase3_scenarios[0])
            b = scenario_to_rank.get(phase3_scenarios[1])
            if a is None or b is None:
                continue
            if b < a:
                crossover = lam
                break

        if crossover is None:
            print("  crossover(B outranks A): n/a")
        else:
            print(f"  crossover(B outranks A): {crossover:.2f}")


if __name__ == "__main__":
    main()
