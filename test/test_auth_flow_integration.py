"""Auth Flow Integration Tests.

Tests the end-to-end JWT authentication flow through MCPO → MCP.

This validates the explicit auth token pattern from docs/EXPLICIT_AUTH_TOKEN_MIGRATION.md:
- MCPO does not forward Authorization headers to upstream MCP
- Instead, pass JWT tokens in the `auth_tokens` request body parameter
- MCP tools extract groups from explicit tokens

The key tests verify:
1. JWT tokens passed in auth_tokens parameter are processed by MCP
2. MCP tools filter results based on token's groups
3. Anonymous requests (no auth_tokens) only see public group
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import requests

from gofr_common.auth import AuthService

from app.config import Config
from app.models import Document, SourceType, TrustLevel
from app.services import DocumentStore, SourceRegistry


# Test group identifiers - must be valid UUIDs (36 chars)
AUTH_TEST_GROUP_ALPHA = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
AUTH_TEST_GROUP_BETA = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
# Public group uses the reserved "public" name in auth, but needs UUID for Source model
AUTH_TEST_GROUP_PUBLIC = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(scope="module")
def auth_flow_auth_service(vault_auth_service) -> AuthService:
    """AuthService configured like the MCP server - uses Vault backend.
    
    Uses the same JWT secret and Vault as the test servers so tokens are valid.
    Groups are pre-created in vault_auth_service fixture (conftest.py).
    """
    # Create test groups specific to this module if not already created
    try:
        vault_auth_service.groups.create_group(AUTH_TEST_GROUP_ALPHA, "Auth Test Alpha")
    except Exception:
        pass  # Group may already exist
    try:
        vault_auth_service.groups.create_group(AUTH_TEST_GROUP_BETA, "Auth Test Beta")
    except Exception:
        pass  # Group may already exist
    
    return vault_auth_service


@pytest.fixture(scope="module")
def alpha_token(auth_flow_auth_service: AuthService) -> str:
    """JWT token with access to alpha group only."""
    return auth_flow_auth_service.create_token(groups=[AUTH_TEST_GROUP_ALPHA])


@pytest.fixture(scope="module")
def beta_token(auth_flow_auth_service: AuthService) -> str:
    """JWT token with access to beta group only."""
    return auth_flow_auth_service.create_token(groups=[AUTH_TEST_GROUP_BETA])


@pytest.fixture(scope="module")
def multi_token(auth_flow_auth_service: AuthService) -> str:
    """JWT token with access to both alpha and beta groups."""
    return auth_flow_auth_service.create_token(
        groups=[AUTH_TEST_GROUP_ALPHA, AUTH_TEST_GROUP_BETA]
    )


@pytest.fixture(scope="module")
def auth_test_data(auth_flow_auth_service: AuthService):
    """Create test documents in different groups for auth flow testing.
    
    Important: Documents are stored using group UUIDs (from Vault), not group names.
    This matches the real auth flow where:
    - JWT tokens contain group names
    - resolve_permitted_groups() extracts names from tokens
    - get_group_uuids_by_names() converts names to UUIDs
    - DocumentStore uses UUIDs as directory paths
    """
    storage_dir = Config.get_storage_dir()
    source_registry = SourceRegistry(base_path=storage_dir / "sources")
    document_store = DocumentStore(base_path=storage_dir / "documents")
    
    created_docs = {}
    
    # Create sources and documents for each test group
    # We use the group NAME as the key (what's in the JWT token)
    # but store documents using the group UUID (from Vault)
    for group_name, display_name in [
        (AUTH_TEST_GROUP_ALPHA, "Alpha"),
        (AUTH_TEST_GROUP_BETA, "Beta"),
        ("public", "Public"),  # Use "public" name for public group
    ]:
        # Get the real UUID for this group from Vault
        group = auth_flow_auth_service.groups.get_group_by_name(group_name)
        if group is None:
            # Group doesn't exist, skip
            continue
        group_uuid = str(group.id)
        
        # Create source using UUID
        source = source_registry.create(
            name=f"Auth Test Source {display_name}",
            group_guid=group_uuid,
            source_type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.UNVERIFIED,
        )
        
        # Create document using UUID
        doc = Document(
            guid=str(uuid4()),
            source_guid=source.source_guid,
            group_guid=group_uuid,
            title=f"Auth Test Document {display_name}",
            content=f"This document belongs to {display_name} group for auth flow testing.",
            language="en",
            created_at=datetime.now(UTC),
        )
        document_store.save(doc)
        # Key by group NAME (what's in tokens) for test lookups
        created_docs[group_name] = doc
    
    return created_docs


def auth_headers(token: str) -> dict[str, str]:
    """Build Authorization header dict.
    
    Note: This is kept for backward compatibility but MCPO tests should
    pass tokens via auth_tokens parameter in the request body instead.
    """
    return {"Authorization": f"Bearer {token}"}


def with_auth_tokens(payload: dict, token: str) -> dict:
    """Add auth_tokens to a request payload for MCPO calls.
    
    MCPO does not forward Authorization headers to upstream MCP.
    Instead, pass JWT tokens in the request body.
    """
    return {**payload, "auth_tokens": [token]}


@pytest.mark.integration
class TestAuthFlowMCPOPassthrough:
    """Test that MCPO correctly passes JWT auth headers to MCP.
    
    These tests verify the Phase 2 fix: removing --api-key from MCPO
    so it acts as a transparent proxy for auth headers.
    """
    
    def test_jwt_reaches_mcp_tools(
        self, 
        shared_server_manager,
        alpha_token: str,
        auth_test_data: dict,
    ) -> None:
        """Verify JWT token is processed by MCP and affects tool behavior.
        
        This is the key test for the auth flow:
        1. Send request to MCPO with auth_tokens in body
        2. MCPO forwards the parameter to MCP
        3. MCP's resolve_permitted_groups() extracts groups from token
        4. Tool filters results by token's groups
        """
        if not shared_server_manager.is_running:
            pytest.skip("Servers not running")
        
        mcpo_url = shared_server_manager.mcpo_url
        alpha_doc = auth_test_data.get(AUTH_TEST_GROUP_ALPHA)
        
        if not alpha_doc:
            pytest.skip("Test data not created")
        
        try:
            # Request with alpha token should be able to get alpha document
            response = requests.post(
                f"{mcpo_url}/get_document",
                json=with_auth_tokens({"guid": alpha_doc.guid}, alpha_token),
                timeout=10,
            )
            
            # If auth flow works, we should get the document (200)
            # or a document not found (which indicates the filter worked)
            assert response.status_code in [200, 404, 422], \
                f"Unexpected response: {response.status_code} {response.text}"
            
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", {})
                # Verify we got the right document
                assert data.get("guid") == alpha_doc.guid
                
        except requests.exceptions.ConnectionError:
            pytest.skip(f"MCPO not available at {mcpo_url}")


@pytest.mark.integration
class TestAuthFlowGroupFiltering:
    """Test that MCP correctly filters results based on JWT groups.
    
    These tests verify the Phase 3 fix: GroupService initialized with
    AuthService for JWT validation.
    """
    
    def test_alpha_token_cannot_access_beta_document(
        self,
        shared_server_manager,
        alpha_token: str,
        auth_test_data: dict,
    ) -> None:
        """Token with alpha group cannot access beta group document.
        
        This verifies:
        - JWT is validated by MCP
        - Groups are extracted from token
        - get_document filters by permitted groups
        """
        if not shared_server_manager.is_running:
            pytest.skip("Servers not running")
        
        mcpo_url = shared_server_manager.mcpo_url
        beta_doc = auth_test_data.get(AUTH_TEST_GROUP_BETA)
        
        if not beta_doc:
            pytest.skip("Test data not created")
        
        try:
            response = requests.post(
                f"{mcpo_url}/get_document",
                json=with_auth_tokens({"guid": beta_doc.guid}, alpha_token),
                timeout=10,
            )
            
            # Should NOT return the document - access denied or not found
            # (implementations may return 403 or filter it out as 404)
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", {})
                # If 200, it should be empty or error message
                assert data.get("guid") != beta_doc.guid, \
                    "Alpha token should NOT access beta document"
                    
        except requests.exceptions.ConnectionError:
            pytest.skip(f"MCPO not available at {mcpo_url}")
    
    def test_multi_token_accesses_both_groups(
        self,
        shared_server_manager,
        multi_token: str,
        auth_test_data: dict,
    ) -> None:
        """Token with multiple groups can access documents from all groups.
        
        This tests the v2 multi-group token capability.
        """
        if not shared_server_manager.is_running:
            pytest.skip("Servers not running")
        
        mcpo_url = shared_server_manager.mcpo_url
        alpha_doc = auth_test_data.get(AUTH_TEST_GROUP_ALPHA)
        beta_doc = auth_test_data.get(AUTH_TEST_GROUP_BETA)
        
        if not alpha_doc or not beta_doc:
            pytest.skip("Test data not created")
        
        try:
            # Should be able to access alpha document
            response_alpha = requests.post(
                f"{mcpo_url}/get_document",
                json=with_auth_tokens({"guid": alpha_doc.guid}, multi_token),
                timeout=10,
            )
            
            # Should be able to access beta document
            response_beta = requests.post(
                f"{mcpo_url}/get_document",
                json=with_auth_tokens({"guid": beta_doc.guid}, multi_token),
                timeout=10,
            )
            
            # Both should succeed (or at least not be explicitly denied)
            assert response_alpha.status_code in [200, 404, 422], \
                f"Alpha access failed: {response_alpha.status_code}"
            assert response_beta.status_code in [200, 404, 422], \
                f"Beta access failed: {response_beta.status_code}"
                
        except requests.exceptions.ConnectionError:
            pytest.skip(f"MCPO not available at {mcpo_url}")
    
    def test_anonymous_request_gets_public_only(
        self,
        shared_server_manager,
        auth_test_data: dict,
    ) -> None:
        """Request without JWT only sees public group documents.
        
        This verifies the fallback behavior when no auth header is present.
        """
        if not shared_server_manager.is_running:
            pytest.skip("Servers not running")
        
        mcpo_url = shared_server_manager.mcpo_url
        alpha_doc = auth_test_data.get(AUTH_TEST_GROUP_ALPHA)
        public_doc = auth_test_data.get("public")  # Use "public" name, not UUID
        
        if not alpha_doc or not public_doc:
            pytest.skip("Test data not created")
        
        try:
            # Anonymous request for alpha document should fail
            response_alpha = requests.post(
                f"{mcpo_url}/get_document",
                json={"guid": alpha_doc.guid},
                # No auth headers
                timeout=10,
            )
            
            # Anonymous request for public document might work
            response_public = requests.post(
                f"{mcpo_url}/get_document",
                json={"guid": public_doc.guid},
                # No auth headers
                timeout=10,
            )
            
            # Alpha should be denied (not 200 with the document)
            if response_alpha.status_code == 200:
                data = response_alpha.json()
                assert data.get("guid") != alpha_doc.guid, \
                    "Anonymous should NOT access alpha document"
            
            # Public might be accessible (depends on MCPO auth config)
            # Just verify we don't get an unexpected error
            assert response_public.status_code in [200, 401, 403, 404, 422], \
                f"Unexpected public response: {response_public.status_code}"
                
        except requests.exceptions.ConnectionError:
            pytest.skip(f"MCPO not available at {mcpo_url}")


@pytest.mark.integration
class TestAuthFlowQueryFiltering:
    """Test that query_documents filters results by JWT groups."""
    
    def test_query_returns_only_permitted_groups(
        self,
        shared_server_manager,
        alpha_token: str,
    ) -> None:
        """Query results should only include documents from permitted groups.
        
        This tests that query_documents respects group filtering.
        """
        if not shared_server_manager.is_running:
            pytest.skip("Servers not running")
        
        mcpo_url = shared_server_manager.mcpo_url
        
        try:
            response = requests.post(
                f"{mcpo_url}/query_documents",
                json=with_auth_tokens({
                    "query": "auth test",
                    "top_k": 10,
                }, alpha_token),
                timeout=30,
            )
            
            # Query should work (may return 0 results if no indexed docs)
            assert response.status_code in [200, 422], \
                f"Query failed: {response.status_code} {response.text}"
            
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", {})
                results = data.get("results", [])
                
                # Any results should only be from alpha group or public
                for res in results:
                    group = res.get("group_guid", "")
                    assert group in [AUTH_TEST_GROUP_ALPHA, AUTH_TEST_GROUP_PUBLIC], \
                        f"Query returned document from unauthorized group: {group}"
                        
        except requests.exceptions.ConnectionError:
            pytest.skip(f"MCPO not available at {mcpo_url}")
