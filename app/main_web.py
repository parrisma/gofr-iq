"""GOFR-IQ Web Server Entry Point.

Runs the FastAPI web server for the APAC Brokerage News Repository.
"""

import argparse
import logging
import os
import secrets
import sys
from pathlib import Path

import uvicorn

from app.auth import AuthService
from app.config import get_settings
from app.logger import ConsoleLogger
from app.web_server import GofrIqWebServer

logger = ConsoleLogger(name="main_web", level=logging.INFO)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="gofr-iq Web Server - APAC Brokerage News Repository REST API"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address to bind to (default: from env or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port number to listen on (default: from env or 8062)",
    )
    parser.add_argument(
        "--jwt-secret",
        type=str,
        default=None,
        help="JWT secret key (default: from GOFR_IQ_JWT_SECRET env var)",
    )
    parser.add_argument(
        "--token-store",
        type=str,
        default=None,
        help="Path to token store file (default: {data_dir}/auth/tokens.json)",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable authentication (WARNING: insecure, for development only)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level for all components (default: INFO)",
    )
    args = parser.parse_args()

    # Parse log level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)

    try:
        # Resolve authentication configuration
        jwt_secret = args.jwt_secret or os.getenv("GOFR_IQ_JWT_SECRET")
        token_store_path = args.token_store or os.getenv("GOFR_IQ_TOKEN_STORE")
        require_auth = not args.no_auth
        
        # Auto-generate secret for development if not provided
        if require_auth and not jwt_secret:
            env = os.getenv("GOFRIQ_ENV", os.getenv("GOFR_IQ_ENV", "PROD"))
            if env.upper() not in ["PROD", "PRODUCTION"]:
                jwt_secret = f"dev-secret-{secrets.token_hex(16)}"
                logger.info("Auto-generated development JWT secret")
            else:
                logger.error(
                    "FATAL: JWT secret required in production",
                    help="Set GOFR_IQ_JWT_SECRET environment variable or use --jwt-secret flag",
                )
                sys.exit(1)

        # Build settings from environment and CLI args
        settings = get_settings(require_auth=False)

        # Override with CLI arguments if provided
        if args.host:
            settings.server.host = args.host
        if args.port:
            settings.server.web_port = args.port

        # Use resolved auth configuration
        if require_auth:
            settings.auth.jwt_secret = jwt_secret
            settings.auth.token_store_path = Path(token_store_path) if token_store_path else None
            settings.auth.require_auth = True

        # Resolve defaults and validate
        settings.resolve_defaults()
        settings.validate()

    except ValueError as e:
        logger.error(
            "FATAL: Configuration error",
            error=str(e),
            help="Set GOFR_IQ_JWT_SECRET environment variable or use --jwt-secret flag, or use --no-auth to disable authentication",
        )
        sys.exit(1)

    # Create AuthService instance if authentication is enabled
    auth_service_instance = None
    if require_auth:
        auth_service_instance = AuthService(
            secret_key=jwt_secret,
            token_store_path=str(token_store_path),
        )
        logger.info(
            "Authentication service created",
            token_store=str(auth_service_instance.token_store_path),
            secret_fingerprint=auth_service_instance.get_secret_fingerprint(),
        )

    # Initialize server with dependency injection
    server = GofrIqWebServer(
        storage_dir=settings.storage.storage_dir,
        jwt_secret=settings.auth.jwt_secret,
        token_store_path=str(settings.auth.token_store_path),
        require_auth=require_auth,
        auth_service=auth_service_instance,
        log_level=log_level,
    )

    try:
        # Print detailed startup banner
        banner = f"""
{'='*80}
  gofr-iq Web Server - Starting
{'='*80}
  Version:          1.23.1
  Transport:        HTTP REST API
  Host:             {settings.server.host}
  Port:             {settings.server.web_port}
  
  Endpoints:
    - API Docs:      http://{settings.server.host}:{settings.server.web_port}/docs
    - Health Check:  http://{settings.server.host}:{settings.server.web_port}/ping
    - Ingest:        http://{settings.server.host}:{settings.server.web_port}/ingest
    - List Sources:  http://{settings.server.host}:{settings.server.web_port}/sources/list
    - Get Source:    http://{settings.server.host}:{settings.server.web_port}/sources/get
    - Get Document:  http://{settings.server.host}:{settings.server.web_port}/documents/get
  
  Container Network (from n8n/openwebui):
    - gofr-iq_dev:   http://gofr-iq_dev:{settings.server.web_port}
    - gofr-iq_prod:  http://gofr-iq_prod:{settings.server.web_port}
  
  Localhost Access:
    - API Docs:      http://localhost:{settings.server.web_port}/docs
    - Health:        curl http://localhost:{settings.server.web_port}/ping
    - Ingest:        curl -X POST http://localhost:{settings.server.web_port}/ingest
  
  Authentication:   {'Enabled' if require_auth else 'Disabled'}
  Token Store:      {settings.auth.token_store_path if require_auth else 'N/A'}
  Storage Dir:      {settings.storage.storage_dir}
{'='*80}
        """
        print(banner)

        # Start uvicorn server
        uvicorn.run(
            server.app,
            host=settings.server.host,
            port=settings.server.web_port,
            log_level=args.log_level.lower(),
        )

    except KeyboardInterrupt:
        logger.info("Received shutdown signal (SIGINT)")
    except Exception as e:
        logger.error("FATAL: Server error", error=str(e), error_type=type(e).__name__)
        sys.exit(1)
