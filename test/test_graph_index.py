"""Tests for Graph Index Service (Phase 11)

Tests Neo4j-based graph storage for entity relationships.
Requires Neo4j server running (./docker/start-neo4j.sh).
"""

import os
import pytest
from datetime import datetime
from typing import Generator

# Skip all tests if neo4j is not installed
neo4j = pytest.importorskip("neo4j")

from app.services.graph_index import (  # noqa: E402
    GraphIndex,
    GraphNode,
    GraphRelationship,
    NodeLabel,
    RelationType,
    TraversalResult,
    create_graph_index,
)


# Check if Neo4j is available
def neo4j_available() -> bool:
    """Check if Neo4j server is running"""
    # Use container name for gofr-net network
    uri = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-iq-neo4j:7687")
    password = os.environ.get("GOFR_IQ_NEO4J_PASSWORD", "testpassword")
    try:
        index = GraphIndex(uri=uri, password=password)
        result = index.verify_connectivity()
        index.close()
        return result
    except Exception:
        return False


# Default Neo4j connection settings for tests
NEO4J_URI = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-iq-neo4j:7687")
NEO4J_PASSWORD = os.environ.get("GOFR_IQ_NEO4J_PASSWORD", "testpassword")


# Skip tests if Neo4j is not available
pytestmark = pytest.mark.skipif(
    not neo4j_available(),
    reason="Neo4j server not available. Run ./docker/start-neo4j.sh"
)


class TestNodeLabel:
    """Tests for NodeLabel enum"""

    def test_node_labels(self) -> None:
        """Test all node labels are defined"""
        assert NodeLabel.SOURCE.value == "Source"
        assert NodeLabel.DOCUMENT.value == "Document"
        assert NodeLabel.COMPANY.value == "Company"
        assert NodeLabel.SECTOR.value == "Sector"
        assert NodeLabel.REGION.value == "Region"
        assert NodeLabel.GROUP.value == "Group"


class TestRelationType:
    """Tests for RelationType enum"""

    def test_relation_types(self) -> None:
        """Test all relationship types are defined"""
        assert RelationType.PRODUCED_BY.value == "PRODUCED_BY"
        assert RelationType.MENTIONS.value == "MENTIONS"
        assert RelationType.BELONGS_TO.value == "BELONGS_TO"
        assert RelationType.IN_GROUP.value == "IN_GROUP"


class TestGraphNode:
    """Tests for GraphNode dataclass"""

    def test_create_graph_node(self) -> None:
        """Test creating a graph node"""
        node = GraphNode(
            label=NodeLabel.DOCUMENT,
            guid="doc-123",
            properties={"title": "Test Doc"},
        )

        assert node.label == NodeLabel.DOCUMENT
        assert node.guid == "doc-123"
        assert node.properties["title"] == "Test Doc"

    def test_default_properties(self) -> None:
        """Test default empty properties"""
        node = GraphNode(label=NodeLabel.SOURCE, guid="src-123")
        assert node.properties == {}


class TestGraphRelationship:
    """Tests for GraphRelationship dataclass"""

    def test_create_relationship(self) -> None:
        """Test creating a relationship"""
        rel = GraphRelationship(
            type=RelationType.PRODUCED_BY,
            from_guid="doc-123",
            to_guid="src-456",
            properties={"weight": 1.0},
        )

        assert rel.type == RelationType.PRODUCED_BY
        assert rel.from_guid == "doc-123"
        assert rel.to_guid == "src-456"
        assert rel.properties["weight"] == 1.0


class TestGraphIndexConnection:
    """Tests for GraphIndex connection"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        yield index
        index.close()

    def test_verify_connectivity(self, graph_index: GraphIndex) -> None:
        """Test connection verification"""
        assert graph_index.verify_connectivity() is True

    def test_repr(self, graph_index: GraphIndex) -> None:
        """Test string representation"""
        repr_str = repr(graph_index)
        assert "GraphIndex" in repr_str
        assert "bolt://" in repr_str

    def test_context_manager(self) -> None:
        """Test context manager protocol"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        with GraphIndex(uri=uri, password=password) as index:
            assert index.verify_connectivity() is True


class TestGraphIndexSchema:
    """Tests for graph schema initialization"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index and clear it"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        yield index
        index.clear()
        index.close()

    def test_init_schema(self, graph_index: GraphIndex) -> None:
        """Test schema initialization creates constraints"""
        # Should not raise
        graph_index.init_schema()

    def test_init_schema_idempotent(self, graph_index: GraphIndex) -> None:
        """Test schema can be initialized multiple times"""
        graph_index.init_schema()
        graph_index.init_schema()  # Should not raise


class TestNodeOperations:
    """Tests for node CRUD operations"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index and clear it"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        yield index
        index.clear()
        index.close()

    def test_create_node(self, graph_index: GraphIndex) -> None:
        """Test creating a node"""
        node = graph_index.create_node(
            NodeLabel.SOURCE,
            "src-123",
            {"name": "Test Source"},
        )

        assert node.label == NodeLabel.SOURCE
        assert node.guid == "src-123"
        assert node.properties["name"] == "Test Source"
        assert "created_at" in node.properties

    def test_get_node(self, graph_index: GraphIndex) -> None:
        """Test getting a node"""
        graph_index.create_node(
            NodeLabel.SOURCE,
            "src-123",
            {"name": "Test Source"},
        )

        node = graph_index.get_node(NodeLabel.SOURCE, "src-123")

        assert node is not None
        assert node.guid == "src-123"
        assert node.properties["name"] == "Test Source"

    def test_get_nonexistent_node(self, graph_index: GraphIndex) -> None:
        """Test getting a node that doesn't exist"""
        node = graph_index.get_node(NodeLabel.SOURCE, "nonexistent")
        assert node is None

    def test_delete_node(self, graph_index: GraphIndex) -> None:
        """Test deleting a node"""
        graph_index.create_node(NodeLabel.SOURCE, "src-123")

        deleted = graph_index.delete_node(NodeLabel.SOURCE, "src-123")

        assert deleted is True
        assert graph_index.get_node(NodeLabel.SOURCE, "src-123") is None

    def test_delete_nonexistent_node(self, graph_index: GraphIndex) -> None:
        """Test deleting a node that doesn't exist"""
        deleted = graph_index.delete_node(NodeLabel.SOURCE, "nonexistent")
        assert deleted is False

    def test_count_nodes(self, graph_index: GraphIndex) -> None:
        """Test counting nodes"""
        assert graph_index.count_nodes() == 0

        graph_index.create_node(NodeLabel.SOURCE, "src-1")
        graph_index.create_node(NodeLabel.SOURCE, "src-2")
        graph_index.create_node(NodeLabel.DOCUMENT, "doc-1")

        assert graph_index.count_nodes() == 3
        assert graph_index.count_nodes(NodeLabel.SOURCE) == 2
        assert graph_index.count_nodes(NodeLabel.DOCUMENT) == 1


class TestRelationshipOperations:
    """Tests for relationship operations"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index with some nodes"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()

        # Create some test nodes
        index.create_node(NodeLabel.SOURCE, "src-123", {"name": "Test Source"})
        index.create_node(NodeLabel.DOCUMENT, "doc-456", {"title": "Test Doc"})
        index.create_node(NodeLabel.COMPANY, "AAPL", {"name": "Apple Inc"})

        yield index
        index.clear()
        index.close()

    def test_create_relationship(self, graph_index: GraphIndex) -> None:
        """Test creating a relationship"""
        rel = graph_index.create_relationship(
            RelationType.PRODUCED_BY,
            NodeLabel.DOCUMENT,
            "doc-456",
            NodeLabel.SOURCE,
            "src-123",
        )

        assert rel.type == RelationType.PRODUCED_BY
        assert rel.from_guid == "doc-456"
        assert rel.to_guid == "src-123"

    def test_create_relationship_with_properties(self, graph_index: GraphIndex) -> None:
        """Test creating a relationship with properties"""
        rel = graph_index.create_relationship(
            RelationType.MENTIONS,
            NodeLabel.DOCUMENT,
            "doc-456",
            NodeLabel.COMPANY,
            "AAPL",
            {"count": 5, "sentiment": "positive"},
        )

        assert rel.properties.get("count") == 5
        assert rel.properties.get("sentiment") == "positive"


class TestDocumentNodeOperations:
    """Tests for document-specific operations"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index with source"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()

        # Create a source and group for relationships
        index.create_node(NodeLabel.SOURCE, "src-123", {"name": "Test Source"})
        index.create_node(NodeLabel.GROUP, "grp-456", {"name": "Test Group"})

        yield index
        index.clear()
        index.close()

    def test_create_document_node(self, graph_index: GraphIndex) -> None:
        """Test creating a document node with relationships"""
        doc = graph_index.create_document_node(
            document_guid="doc-789",
            source_guid="src-123",
            group_guid="grp-456",
            title="Test Document",
            language="en",
            created_at=datetime(2024, 1, 15, 10, 30),
            metadata={"region": "APAC", "sectors": ["tech", "finance"]},
        )

        assert doc.guid == "doc-789"
        assert doc.properties["title"] == "Test Document"
        assert doc.properties["language"] == "en"
        assert doc.properties["meta_region"] == "APAC"
        assert doc.properties["meta_sectors"] == ["tech", "finance"]

    def test_create_source_node(self, graph_index: GraphIndex) -> None:
        """Test creating a source node"""
        source = graph_index.create_source_node(
            source_guid="src-new",
            name="New Source",
            source_type="news_feed",
            group_guid="grp-456",
        )

        assert source.guid == "src-new"
        assert source.properties["name"] == "New Source"
        assert source.properties["type"] == "news_feed"

    def test_add_company_mention(self, graph_index: GraphIndex) -> None:
        """Test adding company mention to document"""
        # First create document
        graph_index.create_document_node(
            document_guid="doc-789",
            source_guid="src-123",
            group_guid="grp-456",
            title="Test Document",
            language="en",
        )

        # Add company mention
        rel = graph_index.add_company_mention(
            document_guid="doc-789",
            company_ticker="TSLA",
            company_name="Tesla Inc",
        )

        assert rel.type == RelationType.MENTIONS
        assert rel.to_guid == "TSLA"


class TestGraphTraversal:
    """Tests for graph traversal queries"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph with interconnected nodes"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()

        # Create test graph
        index.create_node(NodeLabel.SOURCE, "src-1", {"name": "Source 1"})
        index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Group 1"})

        # Create documents from same source
        index.create_document_node("doc-1", "src-1", "grp-1", "Doc 1", "en")
        index.create_document_node("doc-2", "src-1", "grp-1", "Doc 2", "en")
        index.create_document_node("doc-3", "src-1", "grp-1", "Doc 3", "ja")

        # Add company mentions
        index.add_company_mention("doc-1", "AAPL", "Apple")
        index.add_company_mention("doc-2", "AAPL", "Apple")
        index.add_company_mention("doc-2", "GOOG", "Google")
        index.add_company_mention("doc-3", "GOOG", "Google")

        yield index
        index.clear()
        index.close()

    def test_get_documents_by_source(self, graph_index: GraphIndex) -> None:
        """Test getting documents by source"""
        docs = graph_index.get_documents_by_source("src-1")

        assert len(docs) == 3
        guids = [d.guid for d in docs]
        assert "doc-1" in guids
        assert "doc-2" in guids
        assert "doc-3" in guids

    def test_get_documents_mentioning_company(self, graph_index: GraphIndex) -> None:
        """Test getting documents mentioning a company"""
        docs = graph_index.get_documents_mentioning_company("AAPL")

        assert len(docs) == 2
        guids = [d.guid for d in docs]
        assert "doc-1" in guids
        assert "doc-2" in guids

    def test_get_related_documents(self, graph_index: GraphIndex) -> None:
        """Test finding related documents"""
        result = graph_index.get_related_documents("doc-1")

        # Should find doc-2 via AAPL and via same source
        # Should find doc-3 via same source
        assert len(result.nodes) >= 1
        guids = [n.guid for n in result.nodes if n.label == NodeLabel.DOCUMENT]
        assert "doc-2" in guids  # Shares AAPL


class TestGraphIndexClear:
    """Tests for clearing the graph"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        yield index
        index.close()

    def test_clear(self, graph_index: GraphIndex) -> None:
        """Test clearing all nodes"""
        graph_index.create_node(NodeLabel.SOURCE, "src-1")
        graph_index.create_node(NodeLabel.DOCUMENT, "doc-1")

        assert graph_index.count_nodes() == 2

        graph_index.clear()

        assert graph_index.count_nodes() == 0


class TestCreateGraphIndex:
    """Tests for factory function"""

    def test_create_graph_index(self) -> None:
        """Test factory function"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD

        index = create_graph_index(uri=uri, password=password)

        assert isinstance(index, GraphIndex)
        assert index.verify_connectivity() is True
        index.close()


class TestGraphIndexWithoutServer:
    """Tests that don't require Neo4j server"""

    # Override module-level skip
    pytestmark = []  # type: ignore[assignment]

    def test_graph_node_creation(self) -> None:
        """Test GraphNode can be created without server"""
        node = GraphNode(
            label=NodeLabel.DOCUMENT,
            guid="test-guid",
            properties={"key": "value"},
        )
        assert node.guid == "test-guid"

    def test_traversal_result_creation(self) -> None:
        """Test TraversalResult can be created without server"""
        result = TraversalResult(
            nodes=[GraphNode(NodeLabel.DOCUMENT, "doc-1")],
            relationships=[],
        )
        assert len(result.nodes) == 1
