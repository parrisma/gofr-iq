"""GOFR-IQ Web Server Entry Point.

Minimal health-check web server. For REST API, use MCPO.
"""

import argparse
import json
import logging
import os
import sys
import urllib.request

import uvicorn

from app.logger import ConsoleLogger
from app.web_server import GofrIqWebServer

logger = ConsoleLogger(name="main_web", level=logging.INFO)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="gofr-iq Web Server - Health Check Only (use MCPO for REST API)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("GOFR_IQ_WEB_HOST", "0.0.0.0"),  # nosec B104
        help="Host address to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ["GOFR_IQ_WEB_PORT"]) if "GOFR_IQ_WEB_PORT" in os.environ else None,
        help="Port number to listen on (required: set GOFR_IQ_WEB_PORT or use --port)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level",
    )
    # Accept but ignore legacy auth arguments for backward compatibility
    parser.add_argument("--jwt-secret", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-auth", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--auth-disabled", action="store_true", help=argparse.SUPPRESS)
    
    args = parser.parse_args()
    
    # Validate required port
    if args.port is None:
        parser.error("Port is required: set GOFR_IQ_WEB_PORT environment variable or use --port")

    # Fail fast: ensure JWT secret matches Vault (single source of truth) when provided
    jwt_secret = os.environ.get("GOFR_IQ_JWT_SECRET") or os.environ.get("GOFR_JWT_SECRET")
    vault_addr = os.environ.get("GOFR_VAULT_URL") or os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN")
    if jwt_secret:
        if not vault_addr or not vault_token:
            parser.error("VAULT_ADDR/VAULT_TOKEN required to validate GOFR_IQ_JWT_SECRET")
        req = urllib.request.Request(
            f"{vault_addr}/v1/secret/data/gofr/config/jwt-signing-secret",
            headers={"X-Vault-Token": vault_token},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - Vault URL is trusted
            payload = json.loads(resp.read())
        vault_jwt = payload.get("data", {}).get("data", {}).get("value")
        if not vault_jwt:
            parser.error("JWT secret not found in Vault at secret/gofr/config/jwt-signing-secret")
        if jwt_secret != vault_jwt:
            parser.error("GOFR_IQ_JWT_SECRET does not match Vault jwt-signing-secret")
        
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)

    server = GofrIqWebServer(log_level=log_level)

    banner = f"""
{'='*60}
  gofr-iq Web Server - Health Check Only
{'='*60}
  Version:    2.0.0
  Host:       {args.host}
  Port:       {args.port}
  
  Endpoints:
    /health   - Health check
    /ping     - Health check (alias)
    /docs     - OpenAPI docs
    /         - Service info
  
  NOTE: For REST API access to MCP tools, use MCPO on port 8081
{'='*60}
    """
    print(banner)

    try:
        uvicorn.run(
            server.app,
            host=args.host,
            port=args.port,
            log_level=args.log_level.lower(),
        )
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)
