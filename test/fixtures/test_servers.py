"""Server manager for spinning up test servers.

This module provides the ServerManager class that handles MCP/MCPO/Web
server lifecycle for integration testing. Servers are started with
test configuration pointing to the test data directory.

Server Ports (configurable):
    - MCP:  8060 (default)
    - MCPO: 8061 (default)
    - Web:  8062 (default)
"""

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ServerConfig:
    """Configuration for a single server instance.
    
    Attributes:
        name: Server identifier (mcp, mcpo, web)
        port: Port number to bind to
        host: Host address to bind to
        process: Running process handle (set after start)
        log_file: Path to server log file
    """
    name: str
    port: int
    host: str = "127.0.0.1"
    process: Optional[subprocess.Popen] = field(default=None, repr=False)
    log_file: Optional[Path] = None
    
    @property
    def url(self) -> str:
        """Get the server URL."""
        return f"http://{self.host}:{self.port}"
    
    @property
    def is_running(self) -> bool:
        """Check if the server process is running."""
        if self.process is None:
            return False
        return self.process.poll() is None


class ServerManager:
    """Manages MCP/MCPO/Web server lifecycle for testing.
    
    Starts servers with test configuration pointing to isolated test data.
    Automatically stops servers on teardown or when used as context manager.
    
    Attributes:
        project_root: Path to the project root directory
        data_dir: Path to the test data directory
        logs_dir: Path to the logs directory
        mcp_port: MCP server port
        mcpo_port: MCPO server port
        web_port: Web API server port
    
    Example:
        >>> manager = ServerManager(data_dir=tmp_path / "data")
        >>> manager.start_all()
        >>> # Run integration tests...
        >>> manager.stop_all()
        
        # Or use as context manager:
        >>> with ServerManager(data_dir=tmp_path / "data") as manager:
        ...     response = requests.get(manager.web_url + "/health")
    """
    
    # Default ports (can be overridden)
    DEFAULT_MCP_PORT = 8160   # Test ports offset from prod (8060)
    DEFAULT_MCPO_PORT = 8161
    DEFAULT_WEB_PORT = 8162
    
    def __init__(
        self,
        project_root: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        logs_dir: Optional[Path] = None,
        mcp_port: Optional[int] = None,
        mcpo_port: Optional[int] = None,
        web_port: Optional[int] = None,
        host: str = "127.0.0.1",
        jwt_secret: str = "test-secret-key-for-testing",
    ):
        """Initialize server manager.
        
        Args:
            project_root: Project root directory. Defaults to auto-detect.
            data_dir: Test data directory. Defaults to test/data.
            logs_dir: Logs directory. Defaults to logs/.
            mcp_port: MCP server port. Defaults to 8160.
            mcpo_port: MCPO server port. Defaults to 8161.
            web_port: Web API server port. Defaults to 8162.
            host: Host address to bind servers to. Defaults to 127.0.0.1.
            jwt_secret: JWT secret for authentication.
        """
        # Determine project root
        if project_root is None:
            # Navigate up from test/fixtures to project root
            project_root = Path(__file__).parent.parent.parent
        self.project_root = Path(project_root)
        
        # Set directories
        self.data_dir = Path(data_dir) if data_dir else self.project_root / "test" / "data"
        self.logs_dir = Path(logs_dir) if logs_dir else self.project_root / "logs"
        
        # Server configuration
        self.host = host
        self.jwt_secret = jwt_secret
        
        # Initialize server configs
        self._servers: dict[str, ServerConfig] = {
            "mcp": ServerConfig(
                name="mcp",
                port=mcp_port or self.DEFAULT_MCP_PORT,
                host=host,
            ),
            "mcpo": ServerConfig(
                name="mcpo",
                port=mcpo_port or self.DEFAULT_MCPO_PORT,
                host=host,
            ),
            "web": ServerConfig(
                name="web",
                port=web_port or self.DEFAULT_WEB_PORT,
                host=host,
            ),
        }
        
        self._started = False
    
    @property
    def mcp_url(self) -> str:
        """Get MCP server URL."""
        return self._servers["mcp"].url
    
    @property
    def mcpo_url(self) -> str:
        """Get MCPO server URL."""
        return self._servers["mcpo"].url
    
    @property
    def web_url(self) -> str:
        """Get Web API server URL."""
        return self._servers["web"].url
    
    @property
    def mcp_port(self) -> int:
        """Get MCP server port."""
        return self._servers["mcp"].port
    
    @property
    def mcpo_port(self) -> int:
        """Get MCPO server port."""
        return self._servers["mcpo"].port
    
    @property
    def web_port(self) -> int:
        """Get Web API server port."""
        return self._servers["web"].port
    
    @property
    def is_running(self) -> bool:
        """Check if any servers are running."""
        return any(s.is_running for s in self._servers.values())
    
    def get_env(self) -> dict[str, str]:
        """Get environment variables for server processes.
        
        Returns:
            Dictionary of environment variables.
        """
        env = os.environ.copy()
        env.update({
            "GOFR_IQ_ENV": "TEST",
            "GOFR_IQ_ROOT": str(self.project_root),
            "GOFR_IQ_DATA": str(self.data_dir),
            "GOFR_IQ_LOGS": str(self.logs_dir),
            "GOFR_IQ_STORAGE": str(self.data_dir / "storage"),
            "GOFR_IQ_TOKEN_STORE": str(self.logs_dir / "gofriq_tokens_test.json"),
            "GOFR_IQ_HOST": self.host,
            "GOFR_IQ_MCP_PORT": str(self.mcp_port),
            "GOFR_IQ_MCPO_PORT": str(self.mcpo_port),
            "GOFR_IQ_WEB_PORT": str(self.web_port),
            "GOFR_IQ_JWT_SECRET": self.jwt_secret,
            # gofr-common compatible vars
            "GOFR_IQ_JWT_SECRET": self.jwt_secret,
            "GOFR_IQ_TOKEN_STORE": str(self.logs_dir / "gofriq_tokens_test.json"),
            "GOFR_IQ_MCP_PORT": str(self.mcp_port),
            "GOFR_IQ_MCPO_PORT": str(self.mcpo_port),
            "GOFR_IQ_WEB_PORT": str(self.web_port),
        })
        return env
    
    def start_server(self, name: str, wait: bool = True, timeout: float = 10.0) -> bool:
        """Start a specific server.
        
        Args:
            name: Server name (mcp, mcpo, web).
            wait: Wait for server to be ready.
            timeout: Timeout in seconds for server startup.
        
        Returns:
            True if server started successfully.
        
        Raises:
            ValueError: If server name is invalid.
            RuntimeError: If server fails to start.
        """
        if name not in self._servers:
            raise ValueError(f"Unknown server: {name}. Valid: {list(self._servers.keys())}")
        
        server = self._servers[name]
        
        if server.is_running:
            return True
        
        # Create log file
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        server.log_file = self.logs_dir / f"test_{name}.log"
        
        # Build command based on server type
        # Note: These commands will be refined when actual server code exists
        cmd = self._build_server_command(name)
        
        if not cmd:
            # Server implementation not yet available - stub for testing
            return False
        
        # Start the process
        with open(server.log_file, "w") as log:
            server.process = subprocess.Popen(
                cmd,
                env=self.get_env(),
                cwd=self.project_root,
                stdout=log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,  # Create new process group
            )
        
        if wait:
            return self._wait_for_server(server, timeout)
        
        return True
    
    def _build_server_command(self, name: str) -> list[str]:
        """Build command to start a server.
        
        Returns empty list if server implementation doesn't exist yet.
        """
        server = self._servers[name]
        
        if name == "mcp":
            return [
                "uv", "run", "python", "-m", "app.main_mcp",
                "--port", str(server.port),
                "--host", server.host,
            ]
        elif name == "mcpo":
            # MCPO uses env vars for configuration
            return [
                "uv", "run", "python", "-m", "app.main_mcpo",
            ]
        elif name == "web":
            return [
                "uv", "run", "python", "-m", "app.main_web",
                "--port", str(server.port),
                "--host", server.host,
            ]
        
        return []
    
    def _wait_for_server(self, server: ServerConfig, timeout: float) -> bool:
        """Wait for server to be ready.
        
        Polls the server until it responds or timeout is reached.
        """
        import socket
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if process is still running
            if not server.is_running:
                return False
            
            # Try to connect
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1.0)
                    result = sock.connect_ex((server.host, server.port))
                    if result == 0:
                        return True
            except OSError:
                pass
            
            time.sleep(0.1)
        
        return False
    
    def stop_server(self, name: str, timeout: float = 5.0) -> bool:
        """Stop a specific server.
        
        Args:
            name: Server name (mcp, mcpo, web).
            timeout: Timeout in seconds for graceful shutdown.
        
        Returns:
            True if server stopped successfully.
        """
        if name not in self._servers:
            raise ValueError(f"Unknown server: {name}")
        
        server = self._servers[name]
        
        if not server.is_running or server.process is None:
            return True
        
        process = server.process  # Local reference for type checker
        
        # Send SIGTERM to process group
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        
        # Wait for graceful shutdown
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Force kill
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=1.0)
            except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
                pass
        
        server.process = None
        return True
    
    def start_all(self, wait: bool = True, timeout: float = 30.0) -> bool:
        """Start all servers.
        
        Args:
            wait: Wait for all servers to be ready.
            timeout: Total timeout for all servers.
        
        Returns:
            True if all servers started successfully.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        per_server_timeout = timeout / len(self._servers)
        
        results = []
        for name in self._servers:
            result = self.start_server(name, wait=wait, timeout=per_server_timeout)
            results.append(result)
        
        self._started = all(results)
        return self._started
    
    def stop_all(self, timeout: float = 15.0) -> bool:
        """Stop all servers.
        
        Args:
            timeout: Total timeout for stopping all servers.
        
        Returns:
            True if all servers stopped successfully.
        """
        per_server_timeout = timeout / len(self._servers)
        
        results = []
        for name in self._servers:
            result = self.stop_server(name, timeout=per_server_timeout)
            results.append(result)
        
        self._started = False
        return all(results)
    
    def get_server_status(self) -> dict[str, dict]:
        """Get status of all servers.
        
        Returns:
            Dictionary mapping server name to status info.
        """
        return {
            name: {
                "running": server.is_running,
                "port": server.port,
                "url": server.url,
                "pid": server.process.pid if server.process else None,
            }
            for name, server in self._servers.items()
        }
    
    def __enter__(self) -> "ServerManager":
        """Context manager entry - starts all servers."""
        self.start_all()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - stops all servers."""
        self.stop_all()
    
    def __repr__(self) -> str:
        status = "running" if self.is_running else "stopped"
        return f"ServerManager(status={status}, mcp={self.mcp_port}, mcpo={self.mcpo_port}, web={self.web_port})"
