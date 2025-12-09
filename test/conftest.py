"""Pytest configuration for gofr-iq tests.

This module provides pytest fixtures for the gofr-iq test suite.
Fixtures include test data stores, server managers, and sample data.

Phase 0 Fixtures:
    - data_store: Isolated DataStore instance with test data directory
    - sample_data: Pre-generated sample data (groups, sources, documents)
    - server_manager: ServerManager for integration tests
    - test_env: Environment variables for test mode
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
    
    Returns:
        Dictionary of environment variables for test mode.
    """
    return {
        "GOFRIQ_ENV": "TEST",
        "GOFRIQ_JWT_SECRET": "test-secret-key-for-testing-do-not-use-in-prod",
        "GOFR_IQ_JWT_SECRET": "test-secret-key-for-testing-do-not-use-in-prod",
    }


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(test_env: dict[str, str]) -> Generator[None, None, None]:
    """Set up test environment variables for the entire test session.
    
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
    
    Returns:
        Dictionary with host and port for ChromaDB server.
    """
    return {
        "host": os.environ.get("GOFRIQ_CHROMADB_HOST", "gofr-iq-chromadb"),
        "port": int(os.environ.get("GOFRIQ_CHROMADB_PORT", "8000")),
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
    host = os.environ.get("GOFRIQ_NEO4J_HOST", "gofr-iq-neo4j")
    port = int(os.environ.get("GOFRIQ_NEO4J_BOLT_PORT", "7687"))
    return {
        "uri": f"bolt://{host}:{port}",
        "user": "neo4j",
        "password": os.environ.get("GOFRIQ_NEO4J_PASSWORD", "testpassword"),
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
def infra_available(chromadb_available: bool, neo4j_available: bool) -> dict[str, bool]:
    """Check availability of all infrastructure components.
    
    Returns:
        Dictionary with availability status for each component.
    """
    return {
        "chromadb": chromadb_available,
        "neo4j": neo4j_available,
        "all": chromadb_available and neo4j_available,
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

