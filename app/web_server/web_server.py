"""GOFR-IQ Web Server Implementation.

Minimal web server providing health check endpoints.
For REST API access to MCP tools, use MCPO (port 8081).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from gofr_common.web import CORSConfig

from app.logger import ConsoleLogger


class GofrIqWebServer:
    """Minimal FastAPI Web Server for GOFR-IQ health checks."""

    def __init__(
        self,
        log_level: int = logging.INFO,
        **kwargs,  # Accept but ignore legacy parameters for backward compatibility
    ):
        """Initialize GofrIqWebServer.

        Args:
            log_level: Logging level (logging.DEBUG, logging.INFO, etc.)
            **kwargs: Ignored (for backward compatibility with old callers)
        """
        self.app = FastAPI(
            title="gofr-iq",
            description="GOFR-IQ Health Check Server. For REST API, use MCPO on port 8081.",
            version="2.0.0",
        )

        self.logger = ConsoleLogger(name="web_server", level=log_level)

        # Configure CORS middleware
        cors_config = CORSConfig.from_env("GOFR_IQ")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_config.allow_origins,
            allow_credentials=cors_config.allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.logger.info(
            "Web server initialized (health-check only)",
            version="2.0.0",
        )

        self._setup_routes()

    def _setup_routes(self):
        """Setup health check routes."""

        @self.app.get("/health")
        @self.app.get("/ping")
        async def health():
            """Health check endpoint."""
            return JSONResponse(
                content={
                    "status": "ok",
                    "service": "gofr-iq",
                    "timestamp": datetime.utcnow().isoformat(),
                    "version": "2.0.0",
                    "note": "For REST API access to MCP tools, use MCPO on port 8081",
                }
            )

        @self.app.get("/")
        async def root():
            """Root endpoint with service info."""
            return JSONResponse(
                content={
                    "service": "gofr-iq",
                    "version": "2.0.0",
                    "endpoints": {
                        "health": "/health",
                        "ping": "/ping",
                        "docs": "/docs",
                    },
                    "mcpo_url": "http://localhost:8081",
                    "note": "This server provides health checks only. Use MCPO for REST API.",
                }
            )
