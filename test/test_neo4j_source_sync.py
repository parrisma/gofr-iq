"""Integration test for SourceRegistry Neo4j synchronization."""

import pytest
from app.services import SourceRegistry, GraphIndex
from app.models import SourceType, TrustLevel


@pytest.fixture
def source_registry_with_neo4j(tmp_path, graph_index):
    """Create a SourceRegistry with Neo4j sync enabled."""
    return SourceRegistry(
        base_path=tmp_path / "sources",
        graph_index=graph_index,
    )


class TestSourceRegistryNeo4jSync:
    """Test that SourceRegistry automatically syncs to Neo4j."""

    def test_source_create_syncs_to_neo4j(
        self,
        source_registry_with_neo4j: SourceRegistry,
        graph_index: GraphIndex,
    ) -> None:
        """Test that creating a source creates a Neo4j node."""
        # Create source via registry
        source = source_registry_with_neo4j.create(
            name="Test Neo4j Sync Source",
            source_type=SourceType.NEWS_AGENCY,
            region="APAC",
            languages=["en"],
            trust_level=TrustLevel.HIGH,
        )

        # Verify it exists in Neo4j
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (s:Source {source_guid: $guid})
                RETURN s.name as name, s.type as type, s.region as region,
                       s.trust_level as trust_level, s.active as active
                """,
                guid=source.source_guid,
            )
            record = result.single()

        assert record is not None, "Source should exist in Neo4j"
        assert record["name"] == "Test Neo4j Sync Source"
        assert record["type"] == "news_agency"
        assert record["region"] == "APAC"
        assert record["trust_level"] == "high"
        assert record["active"] is True

    def test_source_update_syncs_to_neo4j(
        self,
        source_registry_with_neo4j: SourceRegistry,
        graph_index: GraphIndex,
    ) -> None:
        """Test that updating a source updates the Neo4j node."""
        # Create source
        source = source_registry_with_neo4j.create(
            name="Update Test Source",
            source_type=SourceType.NEWS_AGENCY,
            region="APAC",
            trust_level=TrustLevel.HIGH,
        )

        # Update it
        source_registry_with_neo4j.update(
            source_guid=source.source_guid,
            region="US",
            trust_level=TrustLevel.MEDIUM,
        )

        # Verify update in Neo4j
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (s:Source {source_guid: $guid})
                RETURN s.region as region, s.trust_level as trust_level
                """,
                guid=source.source_guid,
            )
            record = result.single()

        assert record is not None
        assert record["region"] == "US"
        assert record["trust_level"] == "medium"

    def test_source_soft_delete_syncs_to_neo4j(
        self,
        source_registry_with_neo4j: SourceRegistry,
        graph_index: GraphIndex,
    ) -> None:
        """Test that soft deleting a source marks it inactive in Neo4j."""
        # Create source
        source = source_registry_with_neo4j.create(
            name="Soft Delete Test Source",
            source_type=SourceType.NEWS_AGENCY,
            region="APAC",
        )

        # Soft delete it
        source_registry_with_neo4j.soft_delete(source.source_guid)

        # Verify it's marked inactive in Neo4j
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (s:Source {source_guid: $guid})
                RETURN s.active as active
                """,
                guid=source.source_guid,
            )
            record = result.single()

        assert record is not None, "Source should still exist after soft delete"
        assert record["active"] is False, "Source should be marked inactive"

    def test_source_registry_without_graph_index_still_works(
        self,
        tmp_path,
    ) -> None:
        """Test that SourceRegistry works without Neo4j (graceful degradation)."""
        # Create registry without graph_index
        registry = SourceRegistry(base_path=tmp_path / "sources")

        # Should still work - no Neo4j sync, but no error either
        source = registry.create(
            name="No Neo4j Source",
            source_type=SourceType.NEWS_AGENCY,
        )

        assert source.source_guid is not None
        assert source.name == "No Neo4j Source"
