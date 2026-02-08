#!/usr/bin/env python3
"""Quick test: can we see clients via MCP the same way validate_avatar_feeds.py does?"""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

from gofr_common.gofr_env import get_admin_token

# Load ports
env_path = PROJECT_ROOT / "lib" / "gofr-common" / "config" / "gofr_ports.env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

host = "gofr-iq-mcp"
port = int(os.environ.get("GOFR_IQ_MCP_PORT", "8080"))

print(f"Host: {host}:{port}")

# Get admin token
try:
    token = get_admin_token()
    print(f"Token: {token[:30]}...")
except Exception as e:
    print(f"ERROR getting admin token: {e}")
    sys.exit(1)

# Step 1: Init MCP session
init_payload = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0.0"},
    },
}
req = Request(
    f"http://{host}:{port}/mcp",
    data=json.dumps(init_payload).encode(),
    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    method="POST",
)
try:
    with urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("mcp-session-id")
        print(f"Session: {session_id}")
except Exception as e:
    print(f"ERROR init: {e}")
    sys.exit(1)

# Step 2: list_clients
call_payload = {
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {
        "name": "list_clients",
        "arguments": {"limit": 50, "auth_tokens": [token]},
    },
}
req = Request(
    f"http://{host}:{port}/mcp",
    data=json.dumps(call_payload).encode(),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id,
    },
    method="POST",
)
try:
    with urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
except Exception as e:
    print(f"ERROR list_clients: {e}")
    sys.exit(1)

# Parse SSE
print(f"\nRaw response (first 500 chars):\n{raw[:500]}\n")
for line in raw.splitlines():
    if line.startswith("data:"):
        outer = json.loads(line[5:].strip())
        result = outer.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            data = json.loads(content[0]["text"])
            print(f"Status: {data.get('status')}")
            clients = data.get("data", {}).get("clients", [])
            print(f"Clients found: {len(clients)}")
            for c in clients:
                print(f"  {c['name']} -> {c['client_guid']}")
        else:
            print(f"No text content in result: {json.dumps(outer)[:300]}")
        break
