"""Graph Index Service using Neo4j

Provides graph-based storage for entity relationships in documents.
Supports nodes for Sources, Documents, Companies, Sectors, and Regions
with relationships like PRODUCED_BY, MENTIONS, BELONGS_TO.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable


class NodeLabel(str, Enum):
    """Node labels for the graph schema"""

    SOURCE = "Source"
    DOCUMENT = "Document"
    COMPANY = "Company"
    SECTOR = "Sector"
    REGION = "Region"
    GROUP = "Group"


class RelationType(str, Enum):
    """Relationship types for the graph schema"""

    PRODUCED_BY = "PRODUCED_BY"  # Document -> Source
    MENTIONS = "MENTIONS"  # Document -> Company
    BELONGS_TO = "BELONGS_TO"  # Company -> Sector, Document -> Region
    IN_GROUP = "IN_GROUP"  # Document -> Group, Source -> Group


@dataclass
class GraphNode:
    """Represents a node in the graph

    Attributes:
        label: Node label (type)
        guid: Unique identifier
        properties: Additional node properties
    """

    label: NodeLabel
    guid: str
    properties: dict = field(default_factory=dict)


@dataclass
class GraphRelationship:
    """Represents a relationship between nodes

    Attributes:
        type: Relationship type
        from_guid: Source node GUID
        to_guid: Target node GUID
        properties: Additional relationship properties
    """

    type: RelationType
    from_guid: str
    to_guid: str
    properties: dict = field(default_factory=dict)


@dataclass
class TraversalResult:
    """Result from a graph traversal query

    Attributes:
        nodes: List of nodes found
        relationships: List of relationships found
        paths: Raw path data
    """

    nodes: list[GraphNode] = field(default_factory=list)
    relationships: list[GraphRelationship] = field(default_factory=list)
    paths: list[dict] = field(default_factory=list)


class GraphIndex:
    """Neo4j-based graph index for entity relationships

    Provides:
    - Node management (create, read, delete)
    - Relationship management
    - Graph traversal queries
    - Schema initialization with constraints
    """

    # Default URI uses container name for gofr-net network
    DEFAULT_URI = "bolt://gofr-iq-neo4j:7687"

    def __init__(
        self,
        uri: str = DEFAULT_URI,
        username: str = "neo4j",
        password: str = "testpassword",
        database: str = "neo4j",
    ) -> None:
        """Initialize graph index

        Args:
            uri: Neo4j Bolt URI
            username: Neo4j username
            password: Neo4j password
            database: Database name
        """
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database

        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        """Get or create the Neo4j driver"""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
        return self._driver

    def close(self) -> None:
        """Close the Neo4j driver"""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def verify_connectivity(self) -> bool:
        """Verify connection to Neo4j

        Returns:
            True if connected, False otherwise
        """
        try:
            self.driver.verify_connectivity()
            return True
        except ServiceUnavailable:
            return False

    def _get_session(self) -> Session:
        """Get a new session"""
        return self.driver.session(database=self.database)

    def init_schema(self) -> None:
        """Initialize graph schema with constraints and indexes"""
        with self._get_session() as session:
            # Create uniqueness constraints for GUIDs
            for label in NodeLabel:
                constraint_name = f"{label.value.lower()}_guid_unique"
                session.run(
                    f"""
                    CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
                    FOR (n:{label.value})
                    REQUIRE n.guid IS UNIQUE
                    """
                )

            # Create indexes for common query patterns
            session.run(
                """
                CREATE INDEX document_created_at IF NOT EXISTS
                FOR (d:Document)
                ON (d.created_at)
                """
            )
            session.run(
                """
                CREATE INDEX document_language IF NOT EXISTS
                FOR (d:Document)
                ON (d.language)
                """
            )

    def create_node(
        self,
        label: NodeLabel,
        guid: str,
        properties: Optional[dict] = None,
    ) -> GraphNode:
        """Create a node in the graph

        Args:
            label: Node label
            guid: Unique identifier
            properties: Additional properties

        Returns:
            Created GraphNode
        """
        props = properties or {}
        props["guid"] = guid
        props["created_at"] = datetime.utcnow().isoformat()

        with self._get_session() as session:
            result = session.run(
                f"""
                MERGE (n:{label.value} {{guid: $guid}})
                SET n += $props
                RETURN n
                """,
                guid=guid,
                props=props,
            )
            record = result.single()
            if record:
                node_props = dict(record["n"])
                return GraphNode(
                    label=label,
                    guid=guid,
                    properties=node_props,
                )
            raise RuntimeError(f"Failed to create node with guid {guid}")

    def get_node(self, label: NodeLabel, guid: str) -> Optional[GraphNode]:
        """Get a node by label and GUID

        Args:
            label: Node label
            guid: Node GUID

        Returns:
            GraphNode if found, None otherwise
        """
        with self._get_session() as session:
            result = session.run(
                f"""
                MATCH (n:{label.value} {{guid: $guid}})
                RETURN n
                """,
                guid=guid,
            )
            record = result.single()
            if record:
                node_props = dict(record["n"])
                return GraphNode(
                    label=label,
                    guid=guid,
                    properties=node_props,
                )
            return None

    def delete_node(self, label: NodeLabel, guid: str) -> bool:
        """Delete a node and its relationships

        Args:
            label: Node label
            guid: Node GUID

        Returns:
            True if deleted, False if not found
        """
        with self._get_session() as session:
            result = session.run(
                f"""
                MATCH (n:{label.value} {{guid: $guid}})
                DETACH DELETE n
                RETURN count(n) as deleted
                """,
                guid=guid,
            )
            record = result.single()
            return record is not None and record["deleted"] > 0

    def create_relationship(
        self,
        rel_type: RelationType,
        from_label: NodeLabel,
        from_guid: str,
        to_label: NodeLabel,
        to_guid: str,
        properties: Optional[dict] = None,
    ) -> GraphRelationship:
        """Create a relationship between nodes

        Args:
            rel_type: Relationship type
            from_label: Source node label
            from_guid: Source node GUID
            to_label: Target node label
            to_guid: Target node GUID
            properties: Relationship properties

        Returns:
            Created GraphRelationship
        """
        props = properties or {}

        with self._get_session() as session:
            result = session.run(
                f"""
                MATCH (a:{from_label.value} {{guid: $from_guid}})
                MATCH (b:{to_label.value} {{guid: $to_guid}})
                MERGE (a)-[r:{rel_type.value}]->(b)
                SET r += $props
                RETURN r
                """,
                from_guid=from_guid,
                to_guid=to_guid,
                props=props,
            )
            record = result.single()
            if record:
                return GraphRelationship(
                    type=rel_type,
                    from_guid=from_guid,
                    to_guid=to_guid,
                    properties=dict(record["r"]) if record["r"] else {},
                )
            raise RuntimeError(
                f"Failed to create relationship from {from_guid} to {to_guid}"
            )

    def create_document_node(
        self,
        document_guid: str,
        source_guid: str,
        group_guid: str,
        title: str,
        language: str,
        created_at: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> GraphNode:
        """Create a document node with relationships

        Args:
            document_guid: Document GUID
            source_guid: Source GUID (creates PRODUCED_BY relationship)
            group_guid: Group GUID (creates IN_GROUP relationship)
            title: Document title
            language: Document language
            created_at: Document creation time
            metadata: Additional metadata

        Returns:
            Created document GraphNode
        """
        props: dict[str, Any] = {
            "title": title,
            "language": language,
            "source_guid": source_guid,
            "group_guid": group_guid,
        }
        if created_at:
            props["created_at"] = created_at.isoformat()
        if metadata:
            # Flatten metadata for Neo4j (no nested objects)
            for key, value in metadata.items():
                if isinstance(value, (str, int, float, bool)):
                    props[f"meta_{key}"] = value
                elif isinstance(value, list):
                    props[f"meta_{key}"] = value  # Neo4j supports lists

        # Create document node
        doc_node = self.create_node(NodeLabel.DOCUMENT, document_guid, props)

        # Create PRODUCED_BY relationship to source (if source exists)
        try:
            self.create_relationship(
                RelationType.PRODUCED_BY,
                NodeLabel.DOCUMENT,
                document_guid,
                NodeLabel.SOURCE,
                source_guid,
            )
        except RuntimeError:
            pass  # Source may not exist yet

        # Create IN_GROUP relationship
        try:
            self.create_relationship(
                RelationType.IN_GROUP,
                NodeLabel.DOCUMENT,
                document_guid,
                NodeLabel.GROUP,
                group_guid,
            )
        except RuntimeError:
            pass  # Group may not exist yet

        return doc_node

    def create_source_node(
        self,
        source_guid: str,
        name: str,
        source_type: str,
        group_guid: Optional[str] = None,
        properties: Optional[dict] = None,
    ) -> GraphNode:
        """Create a source node

        Args:
            source_guid: Source GUID
            name: Source name
            source_type: Source type
            group_guid: Optional group GUID
            properties: Additional properties

        Returns:
            Created source GraphNode
        """
        props = properties or {}
        props["name"] = name
        props["type"] = source_type

        source_node = self.create_node(NodeLabel.SOURCE, source_guid, props)

        if group_guid:
            try:
                self.create_relationship(
                    RelationType.IN_GROUP,
                    NodeLabel.SOURCE,
                    source_guid,
                    NodeLabel.GROUP,
                    group_guid,
                )
            except RuntimeError:
                pass

        return source_node

    def add_company_mention(
        self,
        document_guid: str,
        company_ticker: str,
        company_name: Optional[str] = None,
    ) -> GraphRelationship:
        """Add a company mention to a document

        Args:
            document_guid: Document GUID
            company_ticker: Company ticker symbol (used as GUID)
            company_name: Optional company name

        Returns:
            Created MENTIONS relationship
        """
        # Ensure company node exists
        props = {"ticker": company_ticker}
        if company_name:
            props["name"] = company_name
        self.create_node(NodeLabel.COMPANY, company_ticker, props)

        return self.create_relationship(
            RelationType.MENTIONS,
            NodeLabel.DOCUMENT,
            document_guid,
            NodeLabel.COMPANY,
            company_ticker,
        )

    def get_documents_by_source(self, source_guid: str) -> list[GraphNode]:
        """Get all documents produced by a source

        Args:
            source_guid: Source GUID

        Returns:
            List of document GraphNodes
        """
        with self._get_session() as session:
            result = session.run(
                """
                MATCH (d:Document)-[:PRODUCED_BY]->(s:Source {guid: $source_guid})
                RETURN d
                ORDER BY d.created_at DESC
                """,
                source_guid=source_guid,
            )
            return [
                GraphNode(
                    label=NodeLabel.DOCUMENT,
                    guid=record["d"]["guid"],
                    properties=dict(record["d"]),
                )
                for record in result
            ]

    def get_documents_mentioning_company(self, company_ticker: str) -> list[GraphNode]:
        """Get all documents mentioning a company

        Args:
            company_ticker: Company ticker symbol

        Returns:
            List of document GraphNodes
        """
        with self._get_session() as session:
            result = session.run(
                """
                MATCH (d:Document)-[:MENTIONS]->(c:Company {guid: $ticker})
                RETURN d
                ORDER BY d.created_at DESC
                """,
                ticker=company_ticker,
            )
            return [
                GraphNode(
                    label=NodeLabel.DOCUMENT,
                    guid=record["d"]["guid"],
                    properties=dict(record["d"]),
                )
                for record in result
            ]

    def get_related_documents(
        self,
        document_guid: str,
        max_depth: int = 2,
        limit: int = 10,
    ) -> TraversalResult:
        """Find documents related to a given document

        Finds documents that share:
        - Same source
        - Same company mentions
        - Same sector/region

        Args:
            document_guid: Starting document GUID
            max_depth: Maximum relationship depth
            limit: Maximum results

        Returns:
            TraversalResult with related nodes and relationships
        """
        with self._get_session() as session:
            # Find documents via shared companies
            result = session.run(
                """
                MATCH (d1:Document {guid: $guid})-[:MENTIONS]->(c:Company)<-[:MENTIONS]-(d2:Document)
                WHERE d1 <> d2
                RETURN DISTINCT d2, c, 'company' as via
                LIMIT $limit
                """,
                guid=document_guid,
                limit=limit,
            )

            nodes: list[GraphNode] = []
            relationships: list[GraphRelationship] = []

            for record in result:
                doc_node = GraphNode(
                    label=NodeLabel.DOCUMENT,
                    guid=record["d2"]["guid"],
                    properties=dict(record["d2"]),
                )
                nodes.append(doc_node)

                company_node = GraphNode(
                    label=NodeLabel.COMPANY,
                    guid=record["c"]["guid"],
                    properties=dict(record["c"]),
                )
                if company_node not in nodes:
                    nodes.append(company_node)

            # Also find documents from same source
            result2 = session.run(
                """
                MATCH (d1:Document {guid: $guid})-[:PRODUCED_BY]->(s:Source)<-[:PRODUCED_BY]-(d2:Document)
                WHERE d1 <> d2
                RETURN DISTINCT d2, s, 'source' as via
                LIMIT $limit
                """,
                guid=document_guid,
                limit=limit,
            )

            for record in result2:
                doc_node = GraphNode(
                    label=NodeLabel.DOCUMENT,
                    guid=record["d2"]["guid"],
                    properties=dict(record["d2"]),
                )
                if doc_node.guid not in [n.guid for n in nodes]:
                    nodes.append(doc_node)

            return TraversalResult(nodes=nodes, relationships=relationships)

    def count_nodes(self, label: Optional[NodeLabel] = None) -> int:
        """Count nodes in the graph

        Args:
            label: Optional label to filter by

        Returns:
            Node count
        """
        with self._get_session() as session:
            if label:
                result = session.run(
                    f"MATCH (n:{label.value}) RETURN count(n) as count"
                )
            else:
                result = session.run("MATCH (n) RETURN count(n) as count")
            record = result.single()
            return record["count"] if record else 0

    def clear(self) -> None:
        """Delete all nodes and relationships"""
        with self._get_session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def __repr__(self) -> str:
        return f"GraphIndex(uri={self.uri}, database={self.database})"

    def __enter__(self) -> "GraphIndex":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def create_graph_index(
    uri: str = "bolt://localhost:7687",
    username: str = "neo4j",
    password: str = "testpassword",
    database: str = "neo4j",
) -> GraphIndex:
    """Factory function to create a graph index

    Args:
        uri: Neo4j Bolt URI
        username: Neo4j username
        password: Neo4j password
        database: Database name

    Returns:
        Configured GraphIndex instance
    """
    return GraphIndex(
        uri=uri,
        username=username,
        password=password,
        database=database,
    )
