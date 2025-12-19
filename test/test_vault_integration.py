"""Vault backend integration tests.

These tests verify the end-to-end flow with Vault as the auth backend.
They ensure that tokens created by tests are valid when making requests
to the running servers (MCP, MCPO, Web).

This solves the original problem: tests created tokens in an in-memory
store, but servers validated against a file-based store. With Vault,
both tests and servers share the same token store.

Requirements:
    - Vault container running (started by run_tests.sh)
    - MCP/MCPO/Web servers running (started by run_tests.sh)
    - GOFR_AUTH_BACKEND=vault environment variable set

Run with:
    ./scripts/run_tests.sh -m vault
    ./scripts/run_tests.sh test/test_vault_integration.py
"""

import os
import pytest
import requests


# Test groups used in this module - must be pre-created in Vault
VAULT_TEST_GROUPS = [
    ("test-group", "Test group for vault tests"),
    ("persistence-test", "Persistence test group"),
    ("revoke-test", "Revocation test group"),
    ("integration-test-group", "Integration test group"),
    ("stateless-test", "Stateless verification test group"),
    ("admin", "Admin group"),
]


def _ensure_vault_groups(auth_service):
    """Pre-create all test groups in Vault."""
    for group_id, group_name in VAULT_TEST_GROUPS:
        try:
            auth_service.groups.create_group(group_id, group_name)
        except Exception:
            pass  # Group may already exist


pytestmark = [
    pytest.mark.integration,
    pytest.mark.vault,
    pytest.mark.requires_vault,
]


class TestVaultBackend:
    """Tests requiring Vault infrastructure."""
    
    @pytest.fixture(autouse=True)
    def check_vault_backend(self, vault_auth_service):
        """Skip tests if Vault backend is not configured, ensure groups exist."""
        backend = os.environ.get("GOFR_AUTH_BACKEND", "")
        if backend != "vault":
            pytest.skip(f"Vault backend required, got: {backend or 'not set'}")
        # Pre-create test groups
        _ensure_vault_groups(vault_auth_service)
    
    @pytest.fixture
    def mcpo_url(self) -> str:
        """Get MCPO server URL from environment."""
        port = os.environ.get("GOFR_IQ_MCPO_PORT", "8181")
        return f"http://localhost:{port}"
    
    @pytest.fixture
    def web_url(self) -> str:
        """Get Web server URL from environment."""
        port = os.environ.get("GOFR_IQ_WEB_PORT", "8182")
        return f"http://localhost:{port}"
    
    def test_vault_auth_service_creates_valid_token(self, vault_auth_service):
        """AuthService with Vault backend can create and verify tokens."""
        # Create a token
        token = vault_auth_service.create_token(
            groups=["test-group"],
            expires_in_seconds=3600,
        )
        assert token is not None
        
        # Verify the token
        token_info = vault_auth_service.verify_token(token)
        assert token_info is not None
        assert "test-group" in token_info.groups
    
    def test_token_persistence_in_vault(self, vault_auth_service):
        """Token created is persisted in Vault and can be retrieved."""
        # Create a token
        token = vault_auth_service.create_token(
            groups=["persistence-test"],
            expires_in_seconds=3600,
        )
        
        # Verify the token - this reads from Vault
        token_info = vault_auth_service.verify_token(token, require_store=True)
        assert token_info is not None
        assert "persistence-test" in token_info.groups
    
    def test_token_revocation_in_vault(self, vault_auth_service):
        """Token can be revoked in Vault."""
        # Create a token
        token = vault_auth_service.create_token(
            groups=["revoke-test"],
            expires_in_seconds=3600,
        )
        
        # Verify token is valid
        token_info = vault_auth_service.verify_token(token)
        assert token_info is not None
        
        # Revoke the token
        vault_auth_service.revoke_token(token)
        
        # Verify token is now invalid
        from gofr_common.auth import TokenRevokedError
        with pytest.raises(TokenRevokedError):
            vault_auth_service.verify_token(token, require_store=True)
    
    def test_token_shared_between_test_and_mcpo(
        self,
        vault_auth_service,
        mcpo_url: str,
    ):
        """Token created in test is valid when calling MCPO server.
        
        This is the key test that validates the Vault migration works.
        Previously, this failed because tests used in-memory store but
        servers used file-based store.
        """
        # Create a token with the same auth service that servers use
        token = vault_auth_service.create_token(
            groups=["integration-test-group"],
            expires_in_seconds=3600,
        )
        
        # Make a request to MCPO with the token
        # Try the /docs endpoint first (should work without auth)
        try:
            response = requests.get(f"{mcpo_url}/docs", timeout=5)
            if response.status_code != 200:
                pytest.skip("MCPO server not running")
        except requests.exceptions.ConnectionError:
            pytest.skip("MCPO server not running")
        
        # Try calling a tool endpoint with the token in body (MCPO doesn't forward headers)
        response = requests.post(
            f"{mcpo_url}/list_sources",
            json={"auth_tokens": [token]},
            timeout=10,
        )
        
        # We expect 200 if the tool works
        # We should NOT get 401 (unauthorized) or 403 (forbidden)
        # because our Vault-backed token should be valid
        assert response.status_code in (200, 422), \
            f"Unexpected status {response.status_code}: {response.text}"
    
    def test_stateless_jwt_verification_works(self, vault_auth_service):
        """Tokens can be verified statelessly (without Vault lookup).
        
        This is used by GroupService for group extraction.
        """
        # Create a token
        token = vault_auth_service.create_token(
            groups=["stateless-test"],
            expires_in_seconds=3600,
        )
        
        # Verify without requiring store lookup
        token_info = vault_auth_service.verify_token(token, require_store=False)
        assert token_info is not None
        assert "stateless-test" in token_info.groups


class TestVaultInfrastructure:
    """Tests for Vault infrastructure availability."""
    
    def test_vault_is_running(self, vault_available: bool):
        """Vault container is running and accessible."""
        assert vault_available, "Vault server is not available"
    
    def test_vault_config_is_set(self, vault_config: dict):
        """Vault configuration is properly set from environment."""
        assert vault_config["url"], "GOFR_VAULT_URL not set"
        assert vault_config["token"], "GOFR_VAULT_TOKEN not set"
        assert vault_config["path_prefix"], "GOFR_VAULT_PATH_PREFIX not set"
    
    def test_env_backend_is_vault(self):
        """Environment is configured for Vault backend."""
        backend = os.environ.get("GOFR_AUTH_BACKEND")
        assert backend == "vault", \
            f"Expected GOFR_AUTH_BACKEND=vault, got {backend}"


class TestOriginalFailingTests:
    """Re-run the tests that were originally failing due to token store mismatch.
    
    These tests should now pass with the Vault backend.
    """
    
    @pytest.fixture(autouse=True)
    def check_vault_backend(self, vault_auth_service):
        """Skip tests if Vault backend is not configured, ensure groups exist."""
        backend = os.environ.get("GOFR_AUTH_BACKEND", "")
        if backend != "vault":
            pytest.skip(f"Vault backend required, got: {backend or 'not set'}")
        # Pre-create test groups
        _ensure_vault_groups(vault_auth_service)
    
    @pytest.fixture
    def mcpo_url(self) -> str:
        """Get MCPO server URL from environment."""
        port = os.environ.get("GOFR_IQ_MCPO_PORT", "8181")
        return f"http://localhost:{port}"
    
    def test_jwt_reaches_mcp_tools_via_mcpo(
        self,
        vault_auth_service,
        mcpo_url: str,
    ):
        """JWT token created by test reaches MCP tools via MCPO.
        
        This was test_jwt_reaches_mcp_tools - failed because token store mismatch.
        """
        # Create token with admin group
        token = vault_auth_service.create_token(
            groups=["admin", "test-group"],
            expires_in_seconds=3600,
        )
        
        # Check MCPO is running
        try:
            response = requests.get(f"{mcpo_url}/docs", timeout=5)
            if response.status_code != 200:
                pytest.skip("MCPO server not running")
        except requests.exceptions.ConnectionError:
            pytest.skip("MCPO server not running")
        
        # Call a tool with the token in body (MCPO doesn't forward headers)
        response = requests.post(
            f"{mcpo_url}/list_sources",
            json={"auth_tokens": [token]},
            timeout=10,
        )
        
        # Token should be valid - no auth errors
        assert response.status_code != 401, "Token was rejected (401)"
        assert response.status_code != 403, "Token was forbidden (403)"
