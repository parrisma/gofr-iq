#!/usr/bin/env python3
"""GOFR-IQ Client Management Script (MCP).

Thin MCP client for creating and managing clients. No direct Neo4j access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.logger import StructuredLogger


logger = StructuredLogger("manage-client")


@dataclass
class McpConfig:
    host: str
    port: int
    token: str


def load_ports_env(project_root: str) -> None:
    env_path = os.path.join(project_root, "lib", "gofr-common", "config", "gofr_ports.env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    description = (
        "Manage clients via MCP.\n\n"
        "Order matters: GLOBAL OPTIONS -> COMMAND -> COMMAND OPTIONS."
    )
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ./scripts/manage_client.sh --token $TOKEN list\n"
            "  ./scripts/manage_client.sh --token $TOKEN create --name \"Test\" --type HEDGE_FUND\n"
            "  ./scripts/manage_client.sh --token $TOKEN create --name \"Fund\" --mandate-text \"US tech focus\"\n"
            "  ./scripts/manage_client.sh --token $TOKEN update $GUID --mandate-text \"Updated mandate\"\n"
            "  ./scripts/manage_client.sh --token $TOKEN update $GUID --clear-mandate-text\n"
            "  ./scripts/manage_client.sh --docker --token $TOKEN list\n"
            "  ./scripts/manage_client.sh --dev --token $TOKEN create --name \"Local Test\"\n"
        ),
    )
    parser.add_argument("--docker", "--prod", action="store_true", dest="docker", help="Use docker host/ports")
    parser.add_argument("--dev", action="store_true", dest="dev", help="Use dev host/ports")
    parser.add_argument("--host", type=str, default=None, help="MCP host override")
    parser.add_argument("--port", type=int, default=None, help="MCP port override")
    parser.add_argument("--token", type=str, default=None, help="JWT token (or GOFR_IQ_TOKEN env)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--type", dest="client_type", default="HEDGE_FUND")
    create.add_argument("--alert-frequency", default="realtime")
    create.add_argument("--impact-threshold", type=float, default=50.0)
    create.add_argument("--mandate-type", default=None)
    create.add_argument("--mandate-text", default=None, help="Free-text fund mandate (0-5000 chars)")
    create.add_argument("--benchmark", default=None)
    create.add_argument("--horizon", default=None)
    create.add_argument("--esg-constrained", action="store_true")
    create.add_argument("--restrictions-file", default=None, help="Path to JSON file with restrictions object")

    get_cmd = subparsers.add_parser("get")
    get_cmd.add_argument("client_guid")

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--type", dest="client_type", default=None)
    list_cmd.add_argument("--limit", type=int, default=50)
    list_cmd.add_argument("--include-defunct", action="store_true")

    update = subparsers.add_parser("update")
    update.add_argument("client_guid")
    update.add_argument("--alert-frequency", default=None)
    update.add_argument("--impact-threshold", type=float, default=None)
    update.add_argument("--mandate-type", default=None)
    update.add_argument("--mandate-text", default=None, help="Free-text fund mandate (0-5000 chars). Omit to keep current.")
    update.add_argument("--clear-mandate-text", action="store_true", help="Clear mandate_text field (set to empty string)")
    update.add_argument("--benchmark", default=None)
    update.add_argument("--horizon", default=None)
    update.add_argument("--esg-constrained", choices=["true", "false"], default=None)
    update.add_argument("--restrictions-file", default=None, help="Path to JSON file with restrictions object")
    update.add_argument("--clear-restrictions", action="store_true", help="Clear restrictions (set to empty)")

    delete_cmd = subparsers.add_parser("delete")
    delete_cmd.add_argument("client_guid")

    defunct_cmd = subparsers.add_parser("defunct")
    defunct_cmd.add_argument("client_guid")
    defunct_cmd.add_argument("--reason", default=None)

    restore_cmd = subparsers.add_parser("restore")
    restore_cmd.add_argument("client_guid")

    add_holding = subparsers.add_parser("add-holding")
    add_holding.add_argument("client_guid")
    add_holding.add_argument("--ticker", required=True)
    add_holding.add_argument("--weight", type=float, required=True)
    add_holding.add_argument("--shares", type=int, default=None)
    add_holding.add_argument("--avg-cost", type=float, default=None)

    remove_holding = subparsers.add_parser("remove-holding")
    remove_holding.add_argument("client_guid")
    remove_holding.add_argument("--ticker", required=True)

    add_watch = subparsers.add_parser("add-watch")
    add_watch.add_argument("client_guid")
    add_watch.add_argument("--ticker", required=True)

    remove_watch = subparsers.add_parser("remove-watch")
    remove_watch.add_argument("client_guid")
    remove_watch.add_argument("--ticker", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("client_guid", nargs="?")

    avatar_feed = subparsers.add_parser("avatar-feed")
    avatar_feed.add_argument("client_guid")
    avatar_feed.add_argument("--limit", type=int, default=20)
    avatar_feed.add_argument("--time-window-hours", type=int, default=72)
    avatar_feed.add_argument("--min-impact-score", type=float, default=None)
    avatar_feed.add_argument("--impact-tiers", nargs="+", default=None)

    return parser.parse_args()


def build_config(args: argparse.Namespace, project_root: str) -> McpConfig:
    load_ports_env(project_root)

    if args.docker and args.dev:
        logger.error("Choose only one of --docker or --dev.")
        sys.exit(2)

    token = args.token or os.environ.get("GOFR_IQ_TOKEN", "")
    if not token:
        logger.error("Missing token. Use --token or GOFR_IQ_TOKEN.")
        sys.exit(2)

    host = args.host
    if host is None:
        if args.dev:
            host = "localhost"
        else:
            host = "gofr-iq-mcp"

    if args.port is not None:
        port = args.port
    else:
        port = int(os.environ.get("GOFR_IQ_MCP_PORT", "8080"))

    return McpConfig(host=host, port=port, token=token)


def mcp_initialize(cfg: McpConfig) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "manage-client", "version": "1.0.0"},
        },
    }
    url = f"http://{cfg.host}:{cfg.port}/mcp"
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("Missing MCP session id in response")
        return session_id


def parse_sse_response(raw: str) -> dict[str, Any]:
    for line in raw.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            return payload
    return {"status": "error", "error_code": "EMPTY_RESPONSE", "message": "No data in MCP response."}


def mcp_call(cfg: McpConfig, session_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {**arguments, "auth_tokens": [cfg.token]},
        },
    }
    url = f"http://{cfg.host}:{cfg.port}/mcp"
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
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    payload = parse_sse_response(raw)
    result = payload.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list) and "text" in content[0]:
        return json.loads(content[0]["text"])
    return payload


def run_command(args: argparse.Namespace, cfg: McpConfig) -> dict[str, Any]:
    session_id = mcp_initialize(cfg)

    if args.command == "create":
        # Load restrictions from file if provided
        restrictions = None
        if args.restrictions_file:
            with open(args.restrictions_file, "r", encoding="utf-8") as f:
                restrictions = json.load(f)
        
        return mcp_call(
            cfg,
            session_id,
            "create_client",
            {
                "name": args.name,
                "client_type": args.client_type,
                "alert_frequency": args.alert_frequency,
                "impact_threshold": args.impact_threshold,
                "mandate_type": args.mandate_type,
                "mandate_text": args.mandate_text,
                "benchmark": args.benchmark,
                "horizon": args.horizon,
                "esg_constrained": args.esg_constrained,
                "restrictions": restrictions,
            },
        )
    if args.command == "get":
        return mcp_call(cfg, session_id, "get_client_profile", {"client_guid": args.client_guid})
    if args.command == "list":
        return mcp_call(
            cfg,
            session_id,
            "list_clients",
            {
                "client_type": args.client_type,
                "limit": args.limit,
                "include_defunct": args.include_defunct,
            },
        )
    if args.command == "update":
        esg_value = None if args.esg_constrained is None else args.esg_constrained == "true"
        # Handle mandate_text: --clear-mandate-text sets to "", --mandate-text sets value, omit leaves None
        mandate_text_value = None
        if args.clear_mandate_text:
            mandate_text_value = ""
        elif args.mandate_text is not None:
            mandate_text_value = args.mandate_text
        
        # Handle restrictions: --clear-restrictions sets to {}, --restrictions-file loads JSON, omit leaves None
        restrictions = None
        if args.clear_restrictions:
            restrictions = {}
        elif args.restrictions_file:
            with open(args.restrictions_file, "r", encoding="utf-8") as f:
                restrictions = json.load(f)
        
        return mcp_call(
            cfg,
            session_id,
            "update_client_profile",
            {
                "client_guid": args.client_guid,
                "alert_frequency": args.alert_frequency,
                "impact_threshold": args.impact_threshold,
                "mandate_type": args.mandate_type,
                "mandate_text": mandate_text_value,
                "benchmark": args.benchmark,
                "horizon": args.horizon,
                "esg_constrained": esg_value,
                "restrictions": restrictions,
            },
        )
    if args.command == "delete":
        return mcp_call(cfg, session_id, "delete_client", {"client_guid": args.client_guid})
    if args.command == "defunct":
        return mcp_call(cfg, session_id, "defunct_client", {"client_guid": args.client_guid, "reason": args.reason})
    if args.command == "restore":
        return mcp_call(cfg, session_id, "restore_client", {"client_guid": args.client_guid})
    if args.command == "add-holding":
        return mcp_call(
            cfg,
            session_id,
            "add_to_portfolio",
            {
                "client_guid": args.client_guid,
                "ticker": args.ticker,
                "weight": args.weight,
                "shares": args.shares,
                "avg_cost": args.avg_cost,
            },
        )
    if args.command == "remove-holding":
        return mcp_call(
            cfg,
            session_id,
            "remove_from_portfolio",
            {"client_guid": args.client_guid, "ticker": args.ticker},
        )
    if args.command == "add-watch":
        return mcp_call(
            cfg,
            session_id,
            "add_to_watchlist",
            {"client_guid": args.client_guid, "ticker": args.ticker},
        )
    if args.command == "remove-watch":
        return mcp_call(
            cfg,
            session_id,
            "remove_from_watchlist",
            {"client_guid": args.client_guid, "ticker": args.ticker},
        )
    if args.command == "validate":
        if args.client_guid:
            profile = mcp_call(cfg, session_id, "get_client_profile", {"client_guid": args.client_guid})
            holdings = mcp_call(cfg, session_id, "get_portfolio_holdings", {"client_guid": args.client_guid})
            watchlist = mcp_call(cfg, session_id, "get_watchlist_items", {"client_guid": args.client_guid})
            return {
                "status": "success",
                "data": {
                    "profile": profile,
                    "holdings": holdings,
                    "watchlist": watchlist,
                },
            }
        return {"status": "error", "error_code": "CLIENT_GUID_REQUIRED", "message": "client_guid required for validate"}
    if args.command == "avatar-feed":
        return mcp_call(
            cfg,
            session_id,
            "get_client_avatar_feed",
            {
                "client_guid": args.client_guid,
                "limit": args.limit,
                "time_window_hours": args.time_window_hours,
                "min_impact_score": args.min_impact_score,
                "impact_tiers": args.impact_tiers,
            },
        )

    return {"status": "error", "error_code": "UNKNOWN_COMMAND", "message": args.command}


def main() -> None:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    args = parse_args()
    cfg = build_config(args, project_root)

    try:
        result = run_command(args, cfg)
        sys.stdout.write(json.dumps(result, indent=2))
        sys.stdout.write("\n")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        logger.error(
            "Request failed",
            status=exc.code,
            reason=str(exc.reason),
            body=body.strip(),
        )
        sys.exit(1)
    except URLError as exc:
        logger.error("Network error", reason=str(exc.reason))
        sys.exit(1)
    except (RuntimeError, ValueError) as exc:
        logger.error("Request failed", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
