"""Tests for test infrastructure - Phase 0 of implementation.

This module tests the test infrastructure components that support
all other tests in the gofr-iq project.

Phase 0 Steps:
    0.1 - DataStore creates directories
    0.2 - Sample data generation (future)
    0.3 - ServerManager (future)
    0.4 - conftest fixtures (future)
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add test directory to path for fixtures import - must be before fixtures import
_test_dir = Path(__file__).parent
if str(_test_dir) not in sys.path:
    sys.path.insert(0, str(_test_dir))

from fixtures import DataStore  # noqa: E402 - path setup required before import

if TYPE_CHECKING:
    from fixtures import ServerManager


class TestDataStoreSetup:
    """Tests for DataStore class - Phase 0, Step 0.1"""
    
    def test_data_store_creates_directories(self, tmp_path: Path):
        """Test that DataStore creates all required directories.
        
        Step 0.1: Verify DataStore creates the canonical directory
        structure for test data.
        """
        # Use a temporary directory for isolation
        store = DataStore(base_path=tmp_path / "test_data")
        
        # Initially not set up
        assert not store.is_setup
        
        # Set up the store
        store.setup()
        
        # Verify all directories are created
        assert store.is_setup
        assert store.documents_path.exists()
        assert store.sources_path.exists()
        assert store.groups_path.exists()
        assert store.chroma_path.exists()
        assert store.logs_path.exists()
        
        # Verify directory structure matches spec
        assert store.documents_path == tmp_path / "test_data" / "documents"
        assert store.sources_path == tmp_path / "test_data" / "sources"
        assert store.groups_path == tmp_path / "test_data" / "groups"
        assert store.chroma_path == tmp_path / "test_data" / "chroma"
        
        # Cleanup
        store.teardown(remove_all=True)
    
    def test_data_store_context_manager(self, tmp_path: Path):
        """Test DataStore works as a context manager."""
        store_path = tmp_path / "test_data"
        
        with DataStore(base_path=store_path) as store:
            assert store.is_setup
            assert store.documents_path.exists()
        
        # After context exit, should still have structure (not remove_all)
        assert store_path.exists()
    
    def test_data_store_teardown_removes_all(self, tmp_path: Path):
        """Test teardown with remove_all=True removes entire directory."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        assert store.base_path.exists()
        
        store.teardown(remove_all=True)
        
        assert not store.base_path.exists()
    
    def test_data_store_reset(self, tmp_path: Path):
        """Test reset clears content but preserves structure."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        # Create a test file
        test_file = store.groups_path / "test.json"
        test_file.write_text('{"test": true}')
        assert test_file.exists()
        
        # Reset
        store.reset()
        
        # Structure should exist, but file should be gone
        assert store.is_setup
        assert store.groups_path.exists()
        assert not test_file.exists()
    
    def test_data_store_group_paths(self, tmp_path: Path):
        """Test path generation methods for groups."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        
        # Test path methods
        docs_path = store.get_group_documents_path(group_guid)
        sources_path = store.get_group_sources_path(group_guid)
        group_path = store.get_group_path(group_guid)
        
        assert docs_path == store.documents_path / group_guid
        assert sources_path == store.sources_path / group_guid
        assert group_path == store.groups_path / f"{group_guid}.json"
        
        store.teardown(remove_all=True)
    
    def test_data_store_create_group_directory(self, tmp_path: Path):
        """Test creating directories for a new group."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        group_guid = store.generate_guid()
        
        docs_path, sources_path = store.create_group_directory(group_guid)
        
        assert docs_path.exists()
        assert sources_path.exists()
        assert docs_path == store.documents_path / group_guid
        assert sources_path == store.sources_path / group_guid
        
        store.teardown(remove_all=True)
    
    def test_data_store_write_read_json(self, tmp_path: Path):
        """Test JSON read/write utilities."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        test_data = {
            "guid": "test-guid",
            "name": "Test Group",
            "tokens": {"token_001": ["read", "write"]}
        }
        
        # Write
        path = store.groups_path / "test_group.json"
        store.write_json(path, test_data)
        
        assert path.exists()
        
        # Read
        loaded = store.read_json(path)
        
        assert loaded == test_data
        
        store.teardown(remove_all=True)
    
    def test_data_store_generate_guid(self):
        """Test GUID generation produces valid UUIDs."""
        guid1 = DataStore.generate_guid()
        guid2 = DataStore.generate_guid()
        
        # GUIDs should be unique
        assert guid1 != guid2
        
        # GUIDs should be valid UUID format (36 chars with hyphens)
        assert len(guid1) == 36
        assert guid1.count("-") == 4
    
    def test_data_store_default_path(self):
        """Test default base path is test/data."""
        store = DataStore()
        
        # Should be relative to test/fixtures/data_store.py
        expected_base = Path(__file__).parent / "data"
        assert store.base_path == expected_base
    
    def test_data_store_repr(self, tmp_path: Path):
        """Test string representation."""
        store = DataStore(base_path=tmp_path / "test_data")
        
        repr_str = repr(store)
        
        assert "DataStore" in repr_str
        assert "test_data" in repr_str
        assert "is_setup=False" in repr_str


class TestSampleDataGeneration:
    """Tests for sample data generation - Phase 0, Step 0.2"""
    
    def test_sample_data_generation(self, tmp_path: Path):
        """Test that sample data is generated with correct counts.
        
        Step 0.2: Verify sample data generation creates:
        - 2 groups
        - 3 tokens
        - 3 sources
        - 10 documents
        """
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        data = store.generate_sample_data()
        
        # Verify counts
        assert len(data["groups"]) == 2
        assert len(data["tokens"]) == 3
        assert len(data["sources"]) == 3
        assert len(data["documents"]) == 10
        
        store.teardown(remove_all=True)
    
    def test_sample_data_group_structure(self, tmp_path: Path):
        """Test that generated groups have required fields."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        for group in data["groups"]:
            assert "group_guid" in group
            assert "name" in group
            assert "description" in group
            assert "created_at" in group
            assert "updated_at" in group
            assert "active" in group
            assert "tokens" in group
            assert isinstance(group["tokens"], dict)
        
        store.teardown(remove_all=True)
    
    def test_sample_data_source_structure(self, tmp_path: Path):
        """Test that generated sources have required fields."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        for source in data["sources"]:
            assert "source_guid" in source
            assert "group_guid" in source
            assert "name" in source
            assert "type" in source
            assert "trust_level" in source
            assert source["trust_level"] in ["high", "medium", "low", "unverified"]
        
        store.teardown(remove_all=True)
    
    def test_sample_data_document_structure(self, tmp_path: Path):
        """Test that generated documents have required fields."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        for doc in data["documents"]:
            assert "guid" in doc
            assert "version" in doc
            assert "source_guid" in doc
            assert "group_guid" in doc
            assert "title" in doc
            assert "content" in doc
            assert "language" in doc
            assert "impact_score" in doc
            assert doc["impact_score"] in ["critical", "high", "medium", "low", "minimal"]
            assert "extracted" in doc
            assert "event_types" in doc["extracted"]
            assert "tags" in doc["extracted"]
            assert "companies" in doc["extracted"]
        
        store.teardown(remove_all=True)
    
    def test_sample_data_token_permissions(self, tmp_path: Path):
        """Test that tokens have proper permission structure."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        valid_permissions = {"create", "read", "update", "delete"}
        
        for token_id, group_perms in data["tokens"].items():
            assert isinstance(group_perms, list)
            for group_guid, perms in group_perms:
                assert isinstance(perms, list)
                for perm in perms:
                    assert perm in valid_permissions
        
        store.teardown(remove_all=True)
    
    def test_sample_data_language_diversity(self, tmp_path: Path):
        """Test that sample documents include multiple languages."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        languages = {doc["language"] for doc in data["documents"]}
        
        # Should have at least English and one other language
        assert "en" in languages
        assert len(languages) >= 2  # en + zh or ja
        
        store.teardown(remove_all=True)
    
    def test_sample_data_write_to_disk(self, tmp_path: Path):
        """Test that sample data can be written to disk."""
        store = DataStore(base_path=tmp_path / "test_data")
        store.setup()
        
        data = store.write_sample_data()
        
        # Verify groups written
        for group in data["groups"]:
            path = store.get_group_path(group["group_guid"])
            assert path.exists()
            loaded = store.read_json(path)
            assert loaded["group_guid"] == group["group_guid"]
        
        # Verify sources written
        for source in data["sources"]:
            path = store.get_source_path(source["group_guid"], source["source_guid"])
            assert path.exists()
        
        # Verify documents written (count files)
        doc_count = sum(1 for _ in store.documents_path.rglob("*.json"))
        assert doc_count == 10
        
        store.teardown(remove_all=True)
    
    def test_sample_data_group_source_relationship(self, tmp_path: Path):
        """Test that sources are correctly assigned to groups."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        group_guids = {g["group_guid"] for g in data["groups"]}
        
        # All sources should belong to valid groups
        for source in data["sources"]:
            assert source["group_guid"] in group_guids
        
        # Group 1 should have 2 sources, Group 2 should have 1
        g1_sources = [s for s in data["sources"] if s["group_guid"] == data["group_guids"][0]]
        g2_sources = [s for s in data["sources"] if s["group_guid"] == data["group_guids"][1]]
        
        assert len(g1_sources) == 2
        assert len(g2_sources) == 1
        
        store.teardown(remove_all=True)
    
    def test_sample_data_document_group_distribution(self, tmp_path: Path):
        """Test that documents are distributed across groups."""
        store = DataStore(base_path=tmp_path / "test_data")
        data = store.generate_sample_data()
        
        # Group 1 should have 7 documents, Group 2 should have 3
        g1_docs = [d for d in data["documents"] if d["group_guid"] == data["group_guids"][0]]
        g2_docs = [d for d in data["documents"] if d["group_guid"] == data["group_guids"][1]]
        
        assert len(g1_docs) == 7
        assert len(g2_docs) == 3
        
        store.teardown(remove_all=True)


class TestServerManager:
    """Tests for ServerManager class - Phase 0, Step 0.3"""
    
    def test_server_manager_import(self):
        """Test that ServerManager can be imported.
        
        Step 0.3: Verify ServerManager class is importable and has
        required attributes.
        """
        from fixtures import ServerManager
        
        assert ServerManager is not None
        assert hasattr(ServerManager, "start_all")
        assert hasattr(ServerManager, "stop_all")
        assert hasattr(ServerManager, "mcp_url")
        assert hasattr(ServerManager, "web_url")
    
    def test_server_manager_default_ports(self, tmp_path: Path):
        """Test default port configuration."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
            logs_dir=tmp_path / "logs",
        )
        
        # Test ports use offset from production (8160 vs 8060)
        assert manager.mcp_port == 8160
        assert manager.mcpo_port == 8161
        assert manager.web_port == 8162
    
    def test_server_manager_custom_ports(self, tmp_path: Path):
        """Test custom port configuration."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
            mcp_port=9000,
            mcpo_port=9001,
            web_port=9002,
        )
        
        assert manager.mcp_port == 9000
        assert manager.mcpo_port == 9001
        assert manager.web_port == 9002
    
    def test_server_manager_urls(self, tmp_path: Path):
        """Test URL generation."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
            host="127.0.0.1",
            mcp_port=8160,
            web_port=8162,
        )
        
        assert manager.mcp_url == "http://127.0.0.1:8160"
        assert manager.web_url == "http://127.0.0.1:8162"
    
    def test_server_manager_env_vars(self, tmp_path: Path):
        """Test environment variable generation."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
            logs_dir=tmp_path / "logs",
            jwt_secret="test-secret",
        )
        
        env = manager.get_env()
        
        assert env["GOFRIQ_ENV"] == "TEST"
        assert env["GOFRIQ_DATA"] == str(tmp_path / "data")
        assert env["GOFRIQ_JWT_SECRET"] == "test-secret"
        assert "GOFRIQ_MCP_PORT" in env
    
    def test_server_manager_status_when_stopped(self, tmp_path: Path):
        """Test server status reporting when not running."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
        )
        
        status = manager.get_server_status()
        
        assert "mcp" in status
        assert "mcpo" in status
        assert "web" in status
        
        for name, info in status.items():
            assert info["running"] is False
            assert info["pid"] is None
    
    def test_server_manager_is_running_when_stopped(self, tmp_path: Path):
        """Test is_running property when stopped."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
        )
        
        assert manager.is_running is False
    
    def test_server_manager_repr(self, tmp_path: Path):
        """Test string representation."""
        from fixtures import ServerManager
        
        manager = ServerManager(
            project_root=tmp_path,
            data_dir=tmp_path / "data",
        )
        
        repr_str = repr(manager)
        
        assert "ServerManager" in repr_str
        assert "stopped" in repr_str
        assert "8160" in repr_str  # mcp port
    
    def test_server_config_dataclass(self):
        """Test ServerConfig dataclass."""
        from fixtures import ServerConfig
        
        config = ServerConfig(name="test", port=8000, host="localhost")
        
        assert config.name == "test"
        assert config.port == 8000
        assert config.host == "localhost"
        assert config.url == "http://localhost:8000"
        assert config.is_running is False


class TestConftestFixtures:
    """Tests for conftest.py fixtures - Phase 0, Step 0.4"""
    
    def test_fixtures_available(self, data_store: "DataStore") -> None:
        """Test that data_store fixture is available and configured.
        
        Step 0.4: Verify conftest fixtures are properly configured.
        """
        assert data_store is not None
        assert data_store.is_setup
        assert data_store.documents_path.exists()
        assert data_store.groups_path.exists()
    
    def test_sample_data_fixture(self, sample_data: dict) -> None:
        """Test that sample_data fixture provides expected data."""
        assert sample_data is not None
        assert "groups" in sample_data
        assert "sources" in sample_data
        assert "documents" in sample_data
        assert len(sample_data["groups"]) == 2
        assert len(sample_data["documents"]) == 10
    
    def test_server_manager_fixture(self, server_manager: "ServerManager") -> None:
        """Test that server_manager fixture is available."""
        assert server_manager is not None
        assert hasattr(server_manager, "start_all")
        assert hasattr(server_manager, "stop_all")
        assert server_manager.is_running is False
    
    def test_data_store_isolation(
        self, data_store: "DataStore", tmp_path: Path
    ) -> None:
        """Test that data_store uses isolated temp directory."""
        # data_store should be in a subdirectory of tmp_path
        assert str(tmp_path) in str(data_store.base_path)
    
    def test_sample_data_writes_files(
        self, data_store: "DataStore", sample_data: dict
    ) -> None:
        """Test that sample_data fixture writes files to data_store."""
        # Check that group files exist
        for group in sample_data["groups"]:
            group_path = data_store.get_group_path(group["group_guid"])
            assert group_path.exists()
        
        # Check that document files exist
        doc_count = sum(1 for _ in data_store.documents_path.rglob("*.json"))
        assert doc_count == 10


