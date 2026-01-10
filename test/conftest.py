"""Pytest configuration for gofr-iq tests.

This module provides pytest fixtures for the gofr-iq test suite.
Fixtures include test data stores, server managers, and sample data.

Phase 0 Fixtures:
    - data_store: Isolated DataStore instance with test data directory
    - sample_data: Pre-generated sample data (groups, sources, documents)
    - server_manager: ServerManager for integration tests
    - test_env: Environment variables for test mode

Auth Fixtures:
    - vault_auth_service: AuthService with Vault backend (shared with servers)
    - auth_service_isolated: AuthService with memory backend (isolated unit tests)
"""

import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Add project root and test directory to path - must be before fixtures import
project_root = Path(__file__).parent.parent
test_dir = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(test_dir))

from fixtures import DataStore, ServerManager  # noqa: E402


# =============================================================================
# Test Environment Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def test_env() -> dict[str, str]:
    """Provide test environment variables.
    
    CRITICAL: Most test configuration MUST come from run_tests.sh which sources
    gofr_ports.sh. This fixture only provides non-critical defaults.
    
    Required env vars (must be set by run_tests.sh):
    - GOFR_JWT_SECRET: Single JWT signing secret (from gofr_ports.sh)
    - GOFR_VAULT_URL: Test Vault URL
    - GOFR_VAULT_TOKEN: Test Vault token
    - GOFR_IQ_CHROMA_HOST/PORT: Test ChromaDB
    - GOFR_IQ_NEO4J_HOST/PORT: Test Neo4j
    
    Returns:
        Dictionary of non-critical environment defaults.
    
    Raises:
        ValueError: If required GOFR_JWT_SECRET is not set.
    """
    # Fail fast if JWT secret not set - this is critical for auth
    if not os.environ.get("GOFR_JWT_SECRET"):
        raise ValueError(
            "GOFR_JWT_SECRET not set. Run tests via ./scripts/run_tests.sh "
            "which sources gofr_ports.sh for the single JWT secret."
        )
    
    # Only non-critical defaults - everything else must come from run_tests.sh
    defaults = {
        "GOFR_IQ_ENV": "TEST",
        "GOFR_AUTH_BACKEND": "vault",
        "GOFR_VAULT_PATH_PREFIX": "gofr-test/auth",
        "GOFR_VAULT_MOUNT_POINT": "secret",
    }
    
    # Only return vars that aren't already set
    return {k: v for k, v in defaults.items() if k not in os.environ}


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(test_env: dict[str, str]) -> Generator[None, None, None]:
    """Set up test environment variables for the entire test session.
    
    Only sets variables that aren't already set by run_tests.sh.
    This ensures test infrastructure settings from run_tests.sh take precedence.
    
    This fixture runs automatically and sets environment variables
    needed for all tests.
    """
    # Store original values
    original_env = {key: os.environ.get(key) for key in test_env}
    
    # Set test values
    os.environ.update(test_env)
    
    yield
    
    # Restore original values
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# =============================================================================
# Auth Service Fixtures
# =============================================================================


# Common test group GUIDs - used across multiple test files
TEST_GROUP_A_GUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_GROUP_B_GUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEST_GROUP_ALPHA = "11111111-1111-1111-1111-111111111111"
TEST_GROUP_BETA = "22222222-2222-2222-2222-222222222222"
TEST_GROUP_PUBLIC = "00000000-0000-0000-0000-000000000000"
TEST_GROUP_LIFECYCLE = "11111111-1111-4111-8111-111111111111"


def _ensure_group(auth_service, group_id: str, name: str) -> None:
    """Create group if it doesn't exist."""
    try:
        auth_service.groups.create_group(group_id, name)
    except Exception:
        # Group may already exist - that's fine
        pass


@pytest.fixture(scope="session")
def vault_auth_service():
    """Create AuthService with Vault backend - shared across ALL tests.
    
    Uses the same Vault instance as running servers, so tokens
    created here are valid when calling MCPO/MCP/Web endpoints.
    
    This fixture requires Vault to be running (started by run_tests.sh).
    Pre-creates all common test groups to avoid InvalidGroupError.
    
    Returns:
        AuthService configured with Vault backend.
        
    Raises:
        pytest.skip: If GOFR_AUTH_BACKEND is not set to 'vault' or Vault unavailable.
    """
    from gofr_common.auth.backends import StorageUnavailableError
    from app.auth.factory import create_auth_service
    
    # Verify Vault backend is configured
    backend = os.environ.get("GOFR_AUTH_BACKEND", "")
    if backend != "vault":
        pytest.skip(f"Vault backend required, got: {backend or 'not set'}")
    
    # Single JWT secret - NO FALLBACKS
    # This must be set by run_tests.sh from gofr_ports.sh
    jwt_secret = os.environ.get("GOFR_JWT_SECRET")
    if not jwt_secret:
        pytest.fail(
            "GOFR_JWT_SECRET not set. Run tests via ./scripts/run_tests.sh "
            "which sources gofr_ports.sh for the single JWT secret."
        )
    
    try:
        auth = create_auth_service(secret_key=jwt_secret)
    except StorageUnavailableError as e:
        pytest.skip(f"Vault unavailable: {e}")
    
    # Pre-create ALL common test groups used across test files
    # Groups must exist before tokens can be created (auth v2 requirement)
    _ensure_group(auth, TEST_GROUP_A_GUID, "Group A")
    _ensure_group(auth, TEST_GROUP_B_GUID, "Group B")
    _ensure_group(auth, TEST_GROUP_ALPHA, "Auth Test Alpha")
    _ensure_group(auth, TEST_GROUP_BETA, "Auth Test Beta")
    _ensure_group(auth, TEST_GROUP_LIFECYCLE, "Test Lifecycle Group")
    # Note: "public" is auto-bootstrapped as reserved group
    
    # Groups used by test_group_access.py
    _ensure_group(auth, "admin-group", "Admin access group")
    _ensure_group(auth, "reader-group", "Read-only access group")
    _ensure_group(auth, "writer-group", "Write access group")
    _ensure_group(auth, "test-group", "Test group")
    _ensure_group(auth, "emea-reader", "EMEA reader group")
    _ensure_group(auth, "unknown-group", "Unknown group")
    _ensure_group(auth, "any-group", "Any group")
    
    # Groups used by test_group_service.py
    _ensure_group(auth, "primary-group", "Primary group")
    _ensure_group(auth, "secondary-group", "Secondary group")
    _ensure_group(auth, "only-group", "Only group")
    _ensure_group(auth, "read-group", "Read group")
    _ensure_group(auth, "write-group", "Write group")
    _ensure_group(auth, "other-group", "Other group")
    _ensure_group(auth, "my-group", "My group")
    _ensure_group(auth, "group-a", "Group A")
    _ensure_group(auth, "group-b", "Group B")
    _ensure_group(auth, "group-c", "Group C")
    _ensure_group(auth, "single-group", "Single group")
    _ensure_group(auth, "private-group", "Private group")
    _ensure_group(auth, "some-group", "Some group")
    _ensure_group(auth, "group-x", "Group X")
    _ensure_group(auth, "group-y", "Group Y")
    _ensure_group(auth, "group-1", "Group 1")
    _ensure_group(auth, "group-2", "Group 2")
    _ensure_group(auth, "not-my-group", "Not my group")
    
    # Groups used by test_group_service_auth.py
    _ensure_group(auth, "premium-group", "Premium group")
    
    # Groups used by test_source_tools_auth.py
    _ensure_group(auth, "regular-user-group", "Regular user group for auth testing")
    
    return auth


# Alias for backward compatibility - tests should use vault_auth_service
@pytest.fixture(scope="session")
def auth_service(vault_auth_service):
    """Alias for vault_auth_service - ALL auth tests use Vault backend.
    
    This ensures consistent behavior: every test that uses auth_service
    gets the Vault-backed AuthService, not an in-memory one.
    """
    return vault_auth_service


# NOTE: auth_service_isolated removed - ALL auth tests must use Vault backend
# This ensures tokens created in tests are valid when calling servers


@pytest.fixture(scope="session")
def vault_config() -> dict[str, str]:
    """Provide Vault configuration from environment.
    
    These values MUST be set by run_tests.sh - no fallback defaults.
    This ensures tests use the correct test containers.
    
    Returns:
        Dictionary with Vault connection details.
    
    Raises:
        ValueError: If required environment variables are not set.
    """
    url = os.environ.get("GOFR_VAULT_URL")
    token = os.environ.get("GOFR_VAULT_TOKEN")
    
    if not url:
        raise ValueError(
            "GOFR_VAULT_URL not set. Run tests via ./scripts/run_tests.sh "
            "which sets up the test environment correctly."
        )
    if not token:
        raise ValueError(
            "GOFR_VAULT_TOKEN not set. Run tests via ./scripts/run_tests.sh "
            "which sets up the test environment correctly."
        )
    
    return {
        "url": url,
        "token": token,
        "path_prefix": os.environ.get("GOFR_VAULT_PATH_PREFIX", "gofr-test/auth"),
        "mount_point": os.environ.get("GOFR_VAULT_MOUNT_POINT", "secret"),
    }


@pytest.fixture(scope="session")
def vault_available(vault_config: dict[str, str]) -> bool:
    """Check if Vault server is available.
    
    Returns:
        True if Vault server is reachable, False otherwise.
    """
    try:
        import hvac
        client = hvac.Client(
            url=vault_config["url"],
            token=vault_config["token"],
        )
        result = client.is_authenticated()
        if not result:
            print(f"\nVault auth failed - URL: {vault_config['url']}, Token: {vault_config['token'][:10]}...")
        return result
    except Exception as e:
        print(f"\nVault connection error: {e}")
        print(f"  URL: {vault_config['url']}")
        return False


# =============================================================================
# Bootstrap Token Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def bootstrap_auth(vault_auth_service) -> dict[str, str]:
    """Create bootstrap groups and tokens ONCE at session start.
    
    This is the SINGLE source of truth for admin/public tokens in tests.
    It ensures:
    - admin/public groups exist in Vault (created if needed)
    - admin/public tokens are created with the correct JWT secret (GOFR_JWT_SECRET)
    - All tests share the same tokens
    - Tokens are exported to environment for tests that read from env
    
    This fixture replaces the old run_bootstrap_auth() in run_tests.sh.
    
    Returns:
        Dictionary with 'admin_token' and 'public_token' keys.
    """
    # Reserved groups (admin, public) are auto-created by AuthService
    # But let's ensure they exist explicitly
    _ensure_group(vault_auth_service, "admin", "Administrator group")
    _ensure_group(vault_auth_service, "public", "Public access group")
    
    # Create bootstrap tokens with the shared JWT secret
    admin_token = vault_auth_service.create_token(groups=["admin"])
    public_token = vault_auth_service.create_token(groups=["public"])
    
    # Export to environment for tests/code that reads from env vars
    os.environ["GOFR_IQ_ADMIN_TOKEN"] = admin_token
    os.environ["GOFR_IQ_PUBLIC_TOKEN"] = public_token
    
    print(f"\n  Bootstrap auth: admin token ({len(admin_token)} chars), public token ({len(public_token)} chars)")
    
    return {
        "admin_token": admin_token,
        "public_token": public_token,
    }


@pytest.fixture(scope="session")
def public_token(bootstrap_auth: dict[str, str]) -> str:
    """Get the bootstrap public token.
    
    This token is created by the bootstrap_auth fixture at session start.
    It grants access to the 'public' group.
    
    Returns:
        JWT token string for public group.
    """
    return bootstrap_auth["public_token"]


@pytest.fixture(scope="session")
def admin_token(bootstrap_auth: dict[str, str]) -> str:
    """Get the bootstrap admin token.
    
    This token is created by the bootstrap_auth fixture at session start.
    It grants access to the 'admin' group for administrative operations.
    
    Returns:
        JWT token string for admin group.
    """
    return bootstrap_auth["admin_token"]


# =============================================================================
# Data Store Fixtures
# =============================================================================


@pytest.fixture
def data_store(tmp_path: Path) -> Generator[DataStore, None, None]:
    """Provide an isolated DataStore instance.
    
    Creates a temporary data store that is automatically cleaned up
    after the test completes.
    
    Args:
        tmp_path: Pytest's temporary directory fixture.
    
    Yields:
        Configured DataStore instance with directories created.
    
    Example:
        def test_something(data_store):
            data_store.write_json(data_store.groups_path / "test.json", {})
    """
    store = DataStore(base_path=tmp_path / "test_data")
    store.setup()
    yield store
    store.teardown(remove_all=True)


@pytest.fixture
def sample_data(data_store: DataStore) -> dict:
    """Provide pre-generated sample data.
    
    Generates and writes sample data to the data store, including:
    - 2 groups with token permissions
    - 3 sources across groups
    - 10 documents with varied characteristics
    
    Args:
        data_store: The DataStore fixture.
    
    Returns:
        Dictionary containing all generated data.
    
    Example:
        def test_documents(sample_data):
            assert len(sample_data["documents"]) == 10
    """
    return data_store.write_sample_data()


@pytest.fixture(scope="session")
def shared_data_store(tmp_path_factory: pytest.TempPathFactory) -> Generator[DataStore, None, None]:
    """Provide a session-scoped DataStore for expensive setup.
    
    Use this fixture when multiple tests need to share the same
    data store setup. The store persists across all tests in the session.
    
    Yields:
        Configured DataStore instance.
    """
    base_path = tmp_path_factory.mktemp("shared_data")
    store = DataStore(base_path=base_path)
    store.setup()
    yield store
    store.teardown(remove_all=True)


# =============================================================================
# Server Manager Fixtures
# =============================================================================


@pytest.fixture
def server_manager(tmp_path: Path) -> Generator[ServerManager, None, None]:
    """Provide a ServerManager instance for integration tests.
    
    Creates a server manager configured for the test environment.
    Servers are NOT started automatically - call start_all() when needed.
    
    Args:
        tmp_path: Pytest's temporary directory fixture.
    
    Yields:
        Configured ServerManager instance.
    
    Example:
        def test_integration(server_manager):
            server_manager.start_all()
            # Run integration tests...
    """
    manager = ServerManager(
        project_root=project_root,
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
    )
    yield manager
    manager.stop_all()


@pytest.fixture(scope="session")
def shared_server_manager(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[ServerManager, None, None]:
    """Provide a session-scoped ServerManager for integration tests.
    
    Use this fixture when multiple integration tests need to share
    the same running servers. More efficient than starting/stopping
    servers for each test.
    
    Yields:
        Configured ServerManager instance.
    """
    base_path = tmp_path_factory.mktemp("servers")
    manager = ServerManager(
        project_root=project_root,
        data_dir=base_path / "data",
        logs_dir=base_path / "logs",
    )
    yield manager
    manager.stop_all()


# =============================================================================
# ChromaDB Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def chromadb_config() -> dict[str, str | int]:
    """Provide ChromaDB server configuration from environment.
    
    These values MUST be set by run_tests.sh - no fallback defaults.
    This ensures tests use the correct test containers.
    
    Returns:
        Dictionary with host and port for ChromaDB server.
    
    Raises:
        ValueError: If required environment variables are not set.
    """
    host = os.environ.get("GOFR_IQ_CHROMA_HOST")
    port = os.environ.get("GOFR_IQ_CHROMA_PORT")
    
    if not host:
        raise ValueError(
            "GOFR_IQ_CHROMA_HOST not set. Run tests via ./scripts/run_tests.sh "
            "which sets up the test environment correctly."
        )
    if not port:
        raise ValueError(
            "GOFR_IQ_CHROMA_PORT not set. Run tests via ./scripts/run_tests.sh "
            "which sets up the test environment correctly."
        )
    
    return {
        "host": host,
        "port": int(port),
    }


@pytest.fixture(scope="session")
def chromadb_available(chromadb_config: dict[str, str | int]) -> bool:
    """Check if ChromaDB server is available and compatible.
    
    Returns:
        True if ChromaDB server is reachable and API-compatible, False otherwise.
    """
    try:
        import chromadb
        client = chromadb.HttpClient(
            host=str(chromadb_config["host"]),
            port=int(chromadb_config["port"]),
        )
        client.heartbeat()
        
        # Test actual collection creation to verify API compatibility
        test_collection_name = "api_test_collection"
        try:
            client.get_or_create_collection(name=test_collection_name)
            client.delete_collection(test_collection_name)
            return True
        except Exception:
            # API incompatibility (version mismatch)
            return False
    except Exception:
        return False


@pytest.fixture
def embedding_index(chromadb_config: dict[str, str | int]) -> Generator:
    """Provide an EmbeddingIndex connected to ChromaDB server.
    
    Creates a unique collection for each test and cleans up after.
    
    Yields:
        Configured EmbeddingIndex instance.
    """
    import uuid
    from app.services.embedding_index import EmbeddingIndex
    
    # Create unique collection name for this test
    collection_name = f"test_{uuid.uuid4().hex[:8]}"
    
    index = EmbeddingIndex(
        host=str(chromadb_config["host"]),
        port=int(chromadb_config["port"]),
        collection_name=collection_name,
    )
    
    yield index
    
    # Cleanup: delete the test collection
    try:
        index.client.delete_collection(collection_name)
    except Exception:
        pass  # Collection may not exist


# =============================================================================
# Neo4j Fixtures  
# =============================================================================


@pytest.fixture(scope="session")
def neo4j_config() -> dict[str, str | int]:
    """Provide Neo4j server configuration from environment.
    
    Returns:
        Dictionary with URI, user, and password for Neo4j server.
    """
    host = os.environ.get("GOFR_IQ_NEO4J_HOST", "gofr-iq-neo4j")
    port = int(os.environ.get("GOFR_IQ_NEO4J_BOLT_PORT", "7687"))
    return {
        "uri": f"bolt://{host}:{port}",
        "user": "neo4j",
        "password": os.environ.get("GOFR_IQ_NEO4J_PASSWORD", "testpassword"),
    }


@pytest.fixture(scope="session")
def neo4j_available(neo4j_config: dict[str, str | int]) -> bool:
    """Check if Neo4j server is available.
    
    Returns:
        True if Neo4j server is reachable, False otherwise.
    """
    try:
        from app.services.graph_index import GraphIndex
        index = GraphIndex(
            uri=str(neo4j_config["uri"]),
            password=str(neo4j_config["password"]),
        )
        result = index.verify_connectivity()
        index.close()
        return result
    except Exception:
        return False


@pytest.fixture
def graph_index(neo4j_config: dict[str, str | int]) -> Generator:
    """Provide a GraphIndex connected to Neo4j server.
    
    Creates a clean state for each test and clears after.
    
    Yields:
        Configured GraphIndex instance.
    """
    from app.services.graph_index import GraphIndex
    
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    
    # Clear before test
    index.clear()
    index.init_schema()
    
    yield index
    
    # Cleanup after test
    try:
        index.clear()
    except Exception:
        pass
    finally:
        index.close()


# =============================================================================
# Combined Infrastructure Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def infra_available(chromadb_available: bool, neo4j_available: bool, vault_available: bool) -> dict[str, bool]:
    """Check availability of all infrastructure components.
    
    Returns:
        Dictionary with availability status for each component.
    """
    return {
        "chromadb": chromadb_available,
        "neo4j": neo4j_available,
        "vault": vault_available,
        "all": chromadb_available and neo4j_available and vault_available,
    }


# =============================================================================
# Pytest Markers
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires running servers)",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (may be skipped in quick runs)",
    )
    config.addinivalue_line(
        "markers",
        "requires_chromadb: mark test as requiring ChromaDB server",
    )
    config.addinivalue_line(
        "markers",
        "requires_neo4j: mark test as requiring Neo4j server",
    )
    config.addinivalue_line(
        "markers",
        "requires_infra: mark test as requiring all infrastructure (ChromaDB + Neo4j)",
    )
    config.addinivalue_line(
        "markers",
        "requires_vault: mark test as requiring Vault server",
    )
    config.addinivalue_line(
        "markers",
        "vault: mark test as Vault backend integration test",
    )

