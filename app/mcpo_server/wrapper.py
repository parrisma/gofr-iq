"""MCPO wrapper implementation for GOFR-IQ MCP server.

Provides both authenticated and non-authenticated MCPO proxy modes.
The wrapper starts the mcpo CLI tool as a subprocess to expose the MCP server
as OpenAPI/REST endpoints.
"""

import asyncio
import logging
import os
import subprocess  # nosec B404
from typing import Optional

from app.logger import ConsoleLogger

logger = ConsoleLogger(name="mcpo_wrapper", level=logging.INFO)


# Ports must be set via environment variables - no defaults
# No default port values - callers must provide them


def _get_required_port(env_var: str) -> int:
    """Get required port from environment or raise error."""
    value = os.environ.get(env_var)
    if value is None:
        raise ValueError(f"Required environment variable {env_var} is not set")
    return int(value)


class MCPOWrapper:
    """Wrapper class for running MCPO proxy server."""

    def __init__(
        self,
        mcp_host: str = "localhost",
        mcp_port: Optional[int] = None,
        mcpo_port: Optional[int] = None,
        mcpo_api_key: Optional[str] = None,
        auth_token: Optional[str] = None,
        use_auth: bool = False,
    ):
        """Initialize MCPO wrapper.

        Args:
            mcp_host: Host where MCP server is running
            mcp_port: Port where MCP server is listening (required via arg or env)
            mcpo_port: Port for MCPO proxy to listen on (required via arg or env)
            mcpo_api_key: API key for client -> MCPO authentication (None = no API key)
            auth_token: JWT token for MCPO -> MCP authentication (if use_auth=True)
            use_auth: Whether to use authenticated mode
        """
        self.mcp_host = mcp_host
        self.mcp_port = mcp_port if mcp_port is not None else _get_required_port("GOFR_IQ_MCP_PORT")
        self.mcpo_port = mcpo_port if mcpo_port is not None else _get_required_port("GOFR_IQ_MCPO_PORT")
        self.mcpo_api_key = mcpo_api_key
        self.auth_token = auth_token
        self.use_auth = use_auth
        self.process: Optional[subprocess.Popen] = None

    def _build_mcpo_command(self) -> list[str]:
        """Build the MCPO command line."""
        mcp_url = f"http://{self.mcp_host}:{self.mcp_port}/mcp"

        # Base command - use uv tool run to execute mcpo
        cmd = [
            "uv",
            "tool",
            "run",
            "mcpo",
            "--port",
            str(self.mcpo_port),
            "--server-type",
            "streamable-http",
        ]

        # Add API key if provided
        if self.mcpo_api_key:
            cmd.extend(["--api-key", self.mcpo_api_key])

        # Add auth header if in authenticated mode
        if self.use_auth:
            if not self.auth_token:
                raise ValueError("auth_token required when use_auth=True")
            cmd.extend(["--header", f'{{"Authorization": "Bearer {self.auth_token}"}}'])

        # Add MCP server URL
        cmd.extend(["--", mcp_url])

        return cmd

    def start(self) -> None:
        """Start the MCPO proxy server."""
        cmd = self._build_mcpo_command()

        mode = "authenticated" if self.use_auth else "public (no auth)"

        # Print detailed startup banner
        banner = f"""
{'='*80}
  GOFR-IQ MCPO Wrapper - Starting
{'='*80}
  Mode:             {mode.upper()}
  MCPO Port:        {self.mcpo_port}
  MCP Target:       http://{self.mcp_host}:{self.mcp_port}/mcp
  API Key:          {'Configured' if self.mcpo_api_key else 'None (public access)'}
  JWT Token:        {'Configured' if self.auth_token else 'None'}
  
  OpenAPI Endpoints:
    - OpenAPI Spec:  http://localhost:{self.mcpo_port}/openapi.json
    - Health Check:  http://localhost:{self.mcpo_port}/health
    - Tools List:    http://localhost:{self.mcpo_port}/tools/list
  
  Container Network:
    - gofr-iq:       http://gofr-iq:{self.mcpo_port}
  
  Command: {' '.join(cmd)}
{'='*80}
        """
        print(banner)

        logger.info(
            f"Starting MCPO wrapper in {mode} mode",
            mcp_url=f"http://{self.mcp_host}:{self.mcp_port}/mcp",
            mcpo_port=self.mcpo_port,
            use_auth=self.use_auth,
            api_key_configured=self.mcpo_api_key is not None,
            jwt_token_configured=self.auth_token is not None,
        )

        try:
            self.process = subprocess.Popen(  # nosec B603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            logger.info("MCPO proxy started", pid=self.process.pid, command=" ".join(cmd))
            print(f"\n✓ MCPO Wrapper started (PID: {self.process.pid})\n")
        except Exception as e:
            logger.error("Failed to start MCPO proxy", error=str(e), command=" ".join(cmd))
            print(f"\n✗ FAILED to start MCPO: {str(e)}\n")
            raise

    def stop(self) -> None:
        """Stop the MCPO proxy server."""
        if self.process:
            logger.info("Stopping MCPO proxy", pid=self.process.pid, mcpo_port=self.mcpo_port)
            print(f"\nStopping MCPO Wrapper (PID: {self.process.pid})...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
                logger.info("MCPO proxy terminated gracefully", pid=self.process.pid)
                print("✓ MCPO Wrapper stopped gracefully\n")
            except subprocess.TimeoutExpired:
                logger.warning("MCPO proxy did not terminate, killing", pid=self.process.pid)
                print("⚠ MCPO Wrapper did not terminate, forcing kill...")
                self.process.kill()
                print("✓ MCPO Wrapper killed\n")
            self.process = None
        else:
            logger.warning("Stop called but MCPO proxy was not running")

    def is_running(self) -> bool:
        """Check if MCPO proxy is running."""
        running = self.process is not None and self.process.poll() is None
        if running and self.process:
            logger.debug("MCPO proxy status check", running=True, pid=self.process.pid)
        return running

    async def run_async(self) -> None:
        """Run MCPO proxy and wait for it to complete."""
        self.start()
        if self.process:
            # Wait for process to complete
            await asyncio.get_event_loop().run_in_executor(None, self.process.wait)


def start_mcpo_wrapper(
    mcp_host: str = "localhost",
    mcp_port: int = 0,
    mcpo_port: int = 0,
    mcpo_api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    use_auth: bool = False,
) -> MCPOWrapper:
    """Start MCPO wrapper for GOFR-IQ MCP server.

    Args:
        mcp_host: Hostname where MCP server is running (default: localhost)
        mcp_port: Port where MCP server is listening (from gofr-common config)
        mcpo_port: Port for MCPO proxy to listen on (from gofr-common config)
        mcpo_api_key: API key for client -> MCPO (default: from env or None for no auth)
        auth_token: JWT token for MCPO -> MCP (default: from env or None)
        use_auth: Whether to use authenticated mode (default: False)

    Returns:
        MCPOWrapper instance

    Environment Variables:
        GOFR_IQ_MCPO_API_KEY: API key for MCPO authentication (if not set, no API key required)
        GOFR_IQ_JWT_TOKEN: JWT token for MCP server authentication
        GOFR_IQ_MCPO_MODE: 'auth' or 'public' (overrides use_auth parameter)
    """
    # Resolve API key from environment if not explicitly provided
    if mcpo_api_key is None:
        mcpo_api_key = os.environ.get("GOFR_IQ_MCPO_API_KEY")

    # Resolve auth token
    if auth_token is None:
        auth_token = os.environ.get("GOFR_IQ_JWT_TOKEN")

    # Resolve auth mode from environment
    mode = os.environ.get("GOFR_IQ_MCPO_MODE", "").lower()
    if mode == "auth":
        use_auth = True
    elif mode == "public":
        use_auth = False

    wrapper = MCPOWrapper(
        mcp_host=mcp_host,
        mcp_port=mcp_port,
        mcpo_port=mcpo_port,
        mcpo_api_key=mcpo_api_key,
        auth_token=auth_token,
        use_auth=use_auth,
    )

    wrapper.start()
    return wrapper
