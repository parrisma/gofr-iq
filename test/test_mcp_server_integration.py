"""Integration tests for MCP Server.

Simple tests to verify MCP server CLI and basic functionality.
For full MCP protocol compliance testing, use the MCP Python client library
with a running server (see gofr-plot/test/mcp/ for reference).

Note: Complex integration tests removed - will be reviewed and added later.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
class TestMCPServerCLI:
    """Tests for MCP server CLI options."""
    
    def test_help_option(self):
        """Test that --help shows usage information."""
        result = subprocess.run(
            [sys.executable, "-m", "app.main_mcp", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "gofr-iq MCP Server" in result.stdout
        assert "--host" in result.stdout
        assert "--port" in result.stdout
        assert "--no-auth" in result.stdout
    
    def test_invalid_option(self):
        """Test that invalid options show error."""
        result = subprocess.run(
            [sys.executable, "-m", "app.main_mcp", "--invalid-option"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode != 0
        assert "unrecognized arguments" in result.stderr or "error" in result.stderr.lower()
