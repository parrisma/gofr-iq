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
    InstrumentType,
    ImpactTier,
    EventCategory,
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

    def test_node_labels_existing(self) -> None:
        """Test existing node labels are defined"""
        assert NodeLabel.SOURCE.value == "Source"
        assert NodeLabel.DOCUMENT.value == "Document"
        assert NodeLabel.COMPANY.value == "Company"
        assert NodeLabel.SECTOR.value == "Sector"
        assert NodeLabel.REGION.value == "Region"
        assert NodeLabel.GROUP.value == "Group"

    def test_node_labels_market_domain(self) -> None:
        """Test market domain node labels"""
        assert NodeLabel.INSTRUMENT.value == "Instrument"
        assert NodeLabel.INDEX.value == "Index"
        assert NodeLabel.FACTOR.value == "Factor"
        assert NodeLabel.EVENT_TYPE.value == "EventType"

    def test_node_labels_client_domain(self) -> None:
        """Test client domain node labels"""
        assert NodeLabel.CLIENT_TYPE.value == "ClientType"
        assert NodeLabel.CLIENT.value == "Client"
        assert NodeLabel.CLIENT_PROFILE.value == "ClientProfile"
        assert NodeLabel.PORTFOLIO.value == "Portfolio"
        assert NodeLabel.WATCHLIST.value == "Watchlist"
        assert NodeLabel.POSITION.value == "Position"


class TestRelationType:
    """Tests for RelationType enum"""

    def test_relation_types_existing(self) -> None:
        """Test existing relationship types are defined"""
        assert RelationType.PRODUCED_BY.value == "PRODUCED_BY"
        assert RelationType.MENTIONS.value == "MENTIONS"
        assert RelationType.BELONGS_TO.value == "BELONGS_TO"
        assert RelationType.IN_GROUP.value == "IN_GROUP"

    def test_relation_types_document_market(self) -> None:
        """Test document to market relationship types"""
        assert RelationType.AFFECTS.value == "AFFECTS"
        assert RelationType.TRIGGERED_BY.value == "TRIGGERED_BY"

    def test_relation_types_document_client(self) -> None:
        """Test document to client relationship types"""
        assert RelationType.RELEVANT_TO.value == "RELEVANT_TO"
        assert RelationType.DELIVERED_TO.value == "DELIVERED_TO"

    def test_relation_types_client_hierarchy(self) -> None:
        """Test client hierarchy relationship types"""
        assert RelationType.IS_TYPE_OF.value == "IS_TYPE_OF"
        assert RelationType.HAS_PROFILE.value == "HAS_PROFILE"
        assert RelationType.HAS_PORTFOLIO.value == "HAS_PORTFOLIO"
        assert RelationType.HAS_WATCHLIST.value == "HAS_WATCHLIST"

    def test_relation_types_client_market(self) -> None:
        """Test client to market relationship types"""
        assert RelationType.HOLDS.value == "HOLDS"
        assert RelationType.WATCHES.value == "WATCHES"
        assert RelationType.BENCHMARKED_TO.value == "BENCHMARKED_TO"
        assert RelationType.EXCLUDES.value == "EXCLUDES"
        assert RelationType.SUBSCRIBED_TO.value == "SUBSCRIBED_TO"
        assert RelationType.EXPOSED_TO.value == "EXPOSED_TO"

    def test_relation_types_market_structure(self) -> None:
        """Test market structure relationship types"""
        assert RelationType.PEER_OF.value == "PEER_OF"
        assert RelationType.CONSTITUENT_OF.value == "CONSTITUENT_OF"
        assert RelationType.ISSUED_BY.value == "ISSUED_BY"
        assert RelationType.TRACKS.value == "TRACKS"


class TestInstrumentType:
    """Tests for InstrumentType enum"""

    def test_instrument_types(self) -> None:
        """Test all instrument types are defined"""
        assert InstrumentType.STOCK.value == "STOCK"
        assert InstrumentType.ETF.value == "ETF"
        assert InstrumentType.ADR.value == "ADR"
        assert InstrumentType.CRYPTO.value == "CRYPTO"


class TestImpactTier:
    """Tests for ImpactTier enum"""

    def test_impact_tiers(self) -> None:
        """Test all impact tiers are defined"""
        assert ImpactTier.PLATINUM.value == "PLATINUM"
        assert ImpactTier.GOLD.value == "GOLD"
        assert ImpactTier.SILVER.value == "SILVER"
        assert ImpactTier.BRONZE.value == "BRONZE"
        assert ImpactTier.STANDARD.value == "STANDARD"


class TestEventCategory:
    """Tests for EventCategory enum"""

    def test_event_categories(self) -> None:
        """Test event categories are defined"""
        assert EventCategory.EARNINGS.value == "Earnings"
        assert EventCategory.CORPORATE_ACTION.value == "Corporate Action"
        assert EventCategory.MACRO.value == "Macro"


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


# =============================================================================
# NEW TESTS FOR ENHANCED GRAPH MODEL
# =============================================================================


class TestInstrumentMethods:
    """Tests for instrument node methods"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        yield index
        index.clear()
        index.close()

    def test_create_instrument(self, graph_index: GraphIndex) -> None:
        """Test creating an instrument node"""
        inst = graph_index.create_instrument(
            ticker="AAPL",
            name="Apple Inc",
            instrument_type="STOCK",
            exchange="NASDAQ",
            currency="USD",
            country="US",
        )
        
        assert inst.guid == "AAPL:NASDAQ"
        assert inst.properties["ticker"] == "AAPL"
        assert inst.properties["instrument_type"] == "STOCK"

    def test_create_instrument_with_company(self, graph_index: GraphIndex) -> None:
        """Test creating instrument with ISSUED_BY relationship"""
        # Create company first
        graph_index.create_node(NodeLabel.COMPANY, "AAPL", {"name": "Apple Inc"})
        
        graph_index.create_instrument(
            ticker="AAPL",
            name="Apple Inc",
            instrument_type="STOCK",
            exchange="NASDAQ",
            company_guid="AAPL",
        )
        
        # Verify relationship exists
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (i:Instrument {guid: $guid})-[:ISSUED_BY]->(c:Company)
                RETURN c.guid AS company_guid
                """,
                guid="AAPL:NASDAQ",
            )
            record = result.single()
            assert record is not None
            assert record["company_guid"] == "AAPL"

    def test_get_instrument(self, graph_index: GraphIndex) -> None:
        """Test getting an instrument by ticker"""
        graph_index.create_instrument(
            ticker="MSFT",
            name="Microsoft",
            instrument_type="STOCK",
            exchange="NASDAQ",
        )
        
        inst = graph_index.get_instrument("MSFT", "NASDAQ")
        assert inst is not None
        assert inst.properties["ticker"] == "MSFT"


class TestEventTypeMethods:
    """Tests for event type node methods"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        yield index
        index.clear()
        index.close()

    def test_create_event_type(self, graph_index: GraphIndex) -> None:
        """Test creating an event type"""
        event = graph_index.create_event_type(
            code="EARNINGS_BEAT",
            name="Earnings Beat",
            category="Earnings",
            base_impact=70,
            default_tier="GOLD",
            decay_lambda=0.10,
        )
        
        assert event.guid == "EARNINGS_BEAT"
        assert event.properties["category"] == "Earnings"
        assert event.properties["base_impact"] == 70

    def test_get_event_type(self, graph_index: GraphIndex) -> None:
        """Test getting an event type"""
        graph_index.create_event_type(
            code="M&A_ANNOUNCE",
            name="M&A Announcement",
            category="Corporate Action",
            base_impact=95,
        )
        
        event = graph_index.get_event_type("M&A_ANNOUNCE")
        assert event is not None
        assert event.properties["base_impact"] == 95


class TestClientMethods:
    """Tests for client node methods"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index with client type and group"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        
        # Create prerequisite nodes
        index.create_client_type("HEDGE_FUND", "Hedge Fund", 10, 30, 0.10)
        index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Test Group"})
        index.create_node(NodeLabel.INDEX, "SPX", {"name": "S&P 500"})
        
        yield index
        index.clear()
        index.close()

    def test_create_client_type(self, graph_index: GraphIndex) -> None:
        """Test creating a client type"""
        ct = graph_index.create_client_type(
            code="LONG_ONLY",
            name="Long Only Asset Manager",
            default_alert_frequency=5,
            default_impact_threshold=50,
        )
        
        assert ct.guid == "LONG_ONLY"
        assert ct.properties["default_alert_frequency"] == 5

    def test_create_client(self, graph_index: GraphIndex) -> None:
        """Test creating a client"""
        client = graph_index.create_client(
            guid="client-001",
            name="Citadel",
            client_type_code="HEDGE_FUND",
            group_guid="grp-1",
        )
        
        assert client.guid == "client-001"
        assert client.properties["name"] == "Citadel"
        
        # Verify IS_TYPE_OF relationship
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (c:Client {guid: $guid})-[:IS_TYPE_OF]->(ct:ClientType)
                RETURN ct.code AS type_code
                """,
                guid="client-001",
            )
            record = result.single()
            assert record is not None
            assert record["type_code"] == "HEDGE_FUND"

    def test_create_client_profile(self, graph_index: GraphIndex) -> None:
        """Test creating a client profile with benchmark"""
        # Create client first
        graph_index.create_client("client-002", "BlackRock", "HEDGE_FUND", "grp-1")
        
        profile = graph_index.create_client_profile(
            guid="profile-001",
            client_guid="client-002",
            mandate_type="relative",
            benchmark_guid="SPX",
            turnover_rate="low",
            esg_constrained=True,
            horizon="long",
        )
        
        assert profile.guid == "profile-001"
        assert profile.properties["esg_constrained"] is True
        
        # Verify BENCHMARKED_TO relationship
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (cp:ClientProfile {guid: $guid})-[:BENCHMARKED_TO]->(idx:Index)
                RETURN idx.guid AS index_guid
                """,
                guid="profile-001",
            )
            record = result.single()
            assert record is not None
            assert record["index_guid"] == "SPX"


class TestPortfolioMethods:
    """Tests for portfolio and watchlist methods"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index with client and instruments"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        
        # Create prerequisites
        index.create_client_type("HEDGE_FUND", "Hedge Fund")
        index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Test Group"})
        index.create_client("client-001", "Test Client", "HEDGE_FUND", "grp-1")
        index.create_instrument("AAPL", "Apple", "STOCK", "NASDAQ")
        index.create_instrument("MSFT", "Microsoft", "STOCK", "NASDAQ")
        
        yield index
        index.clear()
        index.close()

    def test_create_portfolio_and_add_holding(self, graph_index: GraphIndex) -> None:
        """Test creating a portfolio and adding holdings"""
        portfolio = graph_index.create_portfolio(
            guid="portfolio-001",
            client_guid="client-001",
            as_of_date=datetime(2025, 12, 9),
        )
        
        assert portfolio.guid == "portfolio-001"
        
        # Add holdings
        holding = graph_index.add_holding(
            portfolio_guid="portfolio-001",
            instrument_guid="AAPL:NASDAQ",
            weight=0.25,
            shares=1000,
        )
        
        assert holding.type == RelationType.HOLDS
        assert holding.properties["weight"] == 0.25

    def test_create_watchlist_and_add_instrument(self, graph_index: GraphIndex) -> None:
        """Test creating a watchlist and adding instruments"""
        watchlist = graph_index.create_watchlist(
            guid="watchlist-001",
            client_guid="client-001",
            name="Tech Stocks",
            alert_threshold=40,
        )
        
        assert watchlist.guid == "watchlist-001"
        
        # Add to watchlist
        watch = graph_index.add_to_watchlist(
            watchlist_guid="watchlist-001",
            instrument_guid="MSFT:NASDAQ",
            alert_threshold=50,
        )
        
        assert watch.type == RelationType.WATCHES
        assert watch.properties["alert_threshold"] == 50


class TestDocumentImpactMethods:
    """Tests for document impact methods"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create test graph index with document and event types"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        
        # Create prerequisites
        index.create_node(NodeLabel.SOURCE, "src-1", {"name": "Reuters"})
        index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Test Group"})
        index.create_document_node("doc-001", "src-1", "grp-1", "AAPL Beats Q4", "en")
        index.create_event_type("EARNINGS_BEAT", "Earnings Beat", "Earnings", 70)
        index.create_instrument("AAPL", "Apple", "STOCK", "NASDAQ")
        
        yield index
        index.clear()
        index.close()

    def test_set_document_impact(self, graph_index: GraphIndex) -> None:
        """Test setting impact properties on a document"""
        doc = graph_index.set_document_impact(
            document_guid="doc-001",
            impact_score=75.0,
            impact_tier="GOLD",
            decay_lambda=0.10,
            event_type_code="EARNINGS_BEAT",
        )
        
        assert doc is not None
        assert doc.properties["impact_score"] == 75.0
        assert doc.properties["impact_tier"] == "GOLD"
        
        # Verify TRIGGERED_BY relationship
        with graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (d:Document {guid: $guid})-[:TRIGGERED_BY]->(e:EventType)
                RETURN e.code AS event_code
                """,
                guid="doc-001",
            )
            record = result.single()
            assert record is not None
            assert record["event_code"] == "EARNINGS_BEAT"

    def test_add_document_affects(self, graph_index: GraphIndex) -> None:
        """Test adding AFFECTS relationship"""
        affects = graph_index.add_document_affects(
            document_guid="doc-001",
            instrument_guid="AAPL:NASDAQ",
            direction="positive",
            magnitude=0.05,
            confidence=0.9,
        )
        
        assert affects.type == RelationType.AFFECTS
        assert affects.properties["direction"] == "positive"
        assert affects.properties["magnitude"] == 0.05


class TestClientFeedQuery:
    """Tests for client feed query"""

    @pytest.fixture
    def graph_index(self) -> Generator[GraphIndex, None, None]:
        """Create a complete test graph for feed testing"""
        uri = NEO4J_URI
        password = NEO4J_PASSWORD
        index = GraphIndex(uri=uri, password=password)
        index.clear()
        index.init_schema()
        
        # Create group
        index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Test Group"})
        
        # Create client with portfolio
        index.create_client_type("HEDGE_FUND", "Hedge Fund")
        index.create_client("client-001", "Test HF", "HEDGE_FUND", "grp-1")
        index.create_portfolio("portfolio-001", "client-001")
        
        # Create instruments
        index.create_instrument("AAPL", "Apple", "STOCK", "NASDAQ")
        index.create_instrument("MSFT", "Microsoft", "STOCK", "NASDAQ")
        
        # Add holding
        index.add_holding("portfolio-001", "AAPL:NASDAQ", 0.20)
        
        # Create source and documents
        index.create_node(NodeLabel.SOURCE, "src-1", {"name": "Reuters"})
        
        # Document about AAPL (in portfolio)
        index.create_document_node("doc-001", "src-1", "grp-1", "AAPL Earnings", "en")
        index.set_document_impact("doc-001", 80.0, "GOLD", 0.10)
        index.add_document_affects("doc-001", "AAPL:NASDAQ", "positive", 0.05)
        
        # Document about MSFT (not in portfolio)
        index.create_document_node("doc-002", "src-1", "grp-1", "MSFT News", "en")
        index.set_document_impact("doc-002", 60.0, "SILVER", 0.15)
        index.add_document_affects("doc-002", "MSFT:NASDAQ")
        
        yield index
        index.clear()
        index.close()

    def test_get_client_feed_basic(self, graph_index: GraphIndex) -> None:
        """Test basic client feed retrieval"""
        feed = graph_index.get_client_feed(
            client_guid="client-001",
            permitted_groups=["grp-1"],
            limit=10,
        )
        
        # Should return documents, with AAPL doc ranked higher due to portfolio position
        assert len(feed) >= 1
        
        # Find the AAPL document in results
        aapl_docs = [f for f in feed if "AAPL" in (f.get("affected_instruments") or [])]
        assert len(aapl_docs) >= 1

    def test_get_client_feed_with_impact_filter(self, graph_index: GraphIndex) -> None:
        """Test client feed with impact tier filter"""
        feed = graph_index.get_client_feed(
            client_guid="client-001",
            permitted_groups=["grp-1"],
            impact_tiers=["GOLD", "PLATINUM"],
            limit=10,
        )
        
        # Should only return GOLD+ tier documents
        for doc in feed:
            assert doc.get("impact_tier") in ["GOLD", "PLATINUM"]

    def test_get_client_feed_permission_enforcement(self, graph_index: GraphIndex) -> None:
        """Test that feed respects group permissions"""
        # Query with wrong group should return nothing
        feed = graph_index.get_client_feed(
            client_guid="client-001",
            permitted_groups=["wrong-group"],
            limit=10,
        )
        
        assert len(feed) == 0
