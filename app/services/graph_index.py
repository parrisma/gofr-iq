"""Graph Index Service using Neo4j

Provides graph-based storage for entity relationships in documents.
Supports a rich domain model for news ranking and client matching:
- Content: Sources, Documents
- Market: Instruments, Companies, Sectors, Regions, Indexes, Factors, EventTypes
- Client: ClientTypes, Clients, ClientProfiles, Portfolios, Watchlists
- Access Control: Groups

See docs/graph_architecture.md for full schema documentation.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable


class NodeLabel(str, Enum):
    """Node labels for the graph schema
    
    Organized into domains:
    - Content: SOURCE, DOCUMENT
    - Market: COMPANY, SECTOR, REGION, INSTRUMENT, INDEX, FACTOR, EVENT_TYPE
    - Client: CLIENT_TYPE, CLIENT, CLIENT_PROFILE, PORTFOLIO, WATCHLIST, POSITION
    - Access: GROUP
    """

    # Content Domain
    SOURCE = "Source"
    DOCUMENT = "Document"
    
    # Market Domain - Reference Data
    COMPANY = "Company"
    SECTOR = "Sector"
    REGION = "Region"
    INSTRUMENT = "Instrument"
    INDEX = "Index"
    FACTOR = "Factor"
    EVENT_TYPE = "EventType"
    
    # Client Domain
    CLIENT_TYPE = "ClientType"
    CLIENT = "Client"
    CLIENT_PROFILE = "ClientProfile"
    PORTFOLIO = "Portfolio"
    WATCHLIST = "Watchlist"
    POSITION = "Position"
    
    # Access Control
    GROUP = "Group"


class InstrumentType(str, Enum):
    """Types of tradeable instruments"""
    
    STOCK = "STOCK"
    ADR = "ADR"
    GDR = "GDR"
    ETF = "ETF"
    ETN = "ETN"
    REIT = "REIT"
    MLP = "MLP"
    SPAC = "SPAC"
    CRYPTO = "CRYPTO"
    CRYPTO_ETF = "CRYPTO_ETF"
    INDEX = "INDEX"
    PREFERRED = "PREFERRED"
    WARRANT = "WARRANT"
    RIGHT = "RIGHT"


class ImpactTier(str, Enum):
    """News impact tier classification"""
    
    PLATINUM = "PLATINUM"  # Top 1% - Market moving
    GOLD = "GOLD"          # Next 2% - High impact
    SILVER = "SILVER"      # Next 10% - Notable
    BRONZE = "BRONZE"      # Next 20% - Moderate
    STANDARD = "STANDARD"  # Bottom 67% - Routine


class EventCategory(str, Enum):
    """Event type categories"""
    
    EARNINGS = "Earnings"
    GUIDANCE = "Guidance"
    CORPORATE_ACTION = "Corporate Action"
    OWNERSHIP = "Ownership"
    INDEX = "Index"
    ANALYST = "Analyst"
    REGULATORY = "Regulatory"
    LEGAL = "Legal"
    MANAGEMENT = "Management"
    BUSINESS = "Business"
    MACRO = "Macro"
    SENTIMENT = "Sentiment"


class RelationType(str, Enum):
    """Relationship types for the graph schema
    
    Organized by domain:
    - Content relationships
    - Document → Market relationships
    - Document → Client relationships
    - Client hierarchy relationships
    - Client → Market relationships
    - Market structure relationships
    """

    # Existing - Content relationships
    PRODUCED_BY = "PRODUCED_BY"      # Document -> Source
    MENTIONS = "MENTIONS"            # Document -> Company
    BELONGS_TO = "BELONGS_TO"        # Company -> Sector, Document -> Region
    IN_GROUP = "IN_GROUP"            # Document, Source, Client -> Group
    
    # Document -> Market relationships
    AFFECTS = "AFFECTS"              # Document -> Instrument (with direction, magnitude)
    TRIGGERED_BY = "TRIGGERED_BY"    # Document -> EventType (with confidence)
    
    # Document -> Client relationships
    RELEVANT_TO = "RELEVANT_TO"      # Document -> ClientProfile (with score, reasons)
    DELIVERED_TO = "DELIVERED_TO"    # Document -> Client (audit trail)
    
    # Client hierarchy relationships
    IS_TYPE_OF = "IS_TYPE_OF"        # Client -> ClientType
    HAS_PROFILE = "HAS_PROFILE"      # Client -> ClientProfile
    HAS_PORTFOLIO = "HAS_PORTFOLIO"  # Client -> Portfolio
    HAS_WATCHLIST = "HAS_WATCHLIST"  # Client -> Watchlist
    
    # Client -> Market relationships
    HOLDS = "HOLDS"                  # Portfolio -> Instrument (with weight, shares)
    WATCHES = "WATCHES"              # Watchlist -> Instrument (with alert_threshold)
    BENCHMARKED_TO = "BENCHMARKED_TO"  # ClientProfile -> Index
    EXCLUDES = "EXCLUDES"            # ClientProfile -> Company/Sector (with reason)
    SUBSCRIBED_TO = "SUBSCRIBED_TO"  # Client -> Sector/Region/EventType (with priority)
    EXPOSED_TO = "EXPOSED_TO"        # Portfolio -> Factor (with loading)
    
    # Market structure relationships
    PEER_OF = "PEER_OF"              # Company -> Company (with correlation)
    CONSTITUENT_OF = "CONSTITUENT_OF"  # Instrument -> Index (with weight)
    ISSUED_BY = "ISSUED_BY"          # Instrument -> Company
    TRACKS = "TRACKS"                # Instrument -> Index/Instrument (ETF underlying)


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

    def __init__(
        self,
        uri: Optional[str] = None,
        username: str = "neo4j",
        password: str = "testpassword",  # nosec B107
        database: str = "neo4j",
    ) -> None:
        """Initialize graph index

        Args:
            uri: Neo4j Bolt URI (required: set GOFR_IQ_NEO4J_URI or pass explicitly)
            username: Neo4j username
            password: Neo4j password
            database: Database name
        """
        if uri is None:
            uri = os.environ.get("GOFR_IQ_NEO4J_URI")
            if uri is None:
                raise ValueError("Neo4j URI is required: set GOFR_IQ_NEO4J_URI or pass uri parameter")
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
        """Initialize graph schema with constraints and indexes
        
        Creates:
        - Uniqueness constraints on GUIDs for all node types
        - Composite uniqueness for Instrument (ticker + exchange)
        - Performance indexes for common query patterns
        - Full-text search index for document content
        """
        with self._get_session() as session:
            # Create uniqueness constraints for GUIDs on all node types
            for label in NodeLabel:
                constraint_name = f"{label.value.lower()}_guid_unique"
                session.run(
                    f"""
                    CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
                    FOR (n:{label.value})
                    REQUIRE n.guid IS UNIQUE
                    """
                )

            # Composite uniqueness for Instrument (ticker + exchange)
            session.run(
                """
                CREATE CONSTRAINT instrument_ticker_exchange IF NOT EXISTS
                FOR (i:Instrument)
                REQUIRE (i.ticker, i.exchange) IS UNIQUE
                """
            )
            
            # EventType code uniqueness
            session.run(
                """
                CREATE CONSTRAINT eventtype_code_unique IF NOT EXISTS
                FOR (e:EventType)
                REQUIRE e.code IS UNIQUE
                """
            )
            
            # ClientType code uniqueness
            session.run(
                """
                CREATE CONSTRAINT clienttype_code_unique IF NOT EXISTS
                FOR (ct:ClientType)
                REQUIRE ct.code IS UNIQUE
                """
            )

            # Performance indexes for Document queries
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
            session.run(
                """
                CREATE INDEX document_impact IF NOT EXISTS
                FOR (d:Document)
                ON (d.impact_tier, d.created_at)
                """
            )
            session.run(
                """
                CREATE INDEX document_impact_score IF NOT EXISTS
                FOR (d:Document)
                ON (d.impact_score)
                """
            )
            
            # Index for Instrument lookups
            session.run(
                """
                CREATE INDEX instrument_ticker IF NOT EXISTS
                FOR (i:Instrument)
                ON (i.ticker)
                """
            )
            session.run(
                """
                CREATE INDEX instrument_type IF NOT EXISTS
                FOR (i:Instrument)
                ON (i.instrument_type)
                """
            )
            
            # Index for Company lookups
            session.run(
                """
                CREATE INDEX company_ticker IF NOT EXISTS
                FOR (c:Company)
                ON (c.ticker)
                """
            )
            
            # Index for Client lookups
            session.run(
                """
                CREATE INDEX client_name IF NOT EXISTS
                FOR (c:Client)
                ON (c.name)
                """
            )
            
            # Index for Group lookups (critical for permission queries)
            session.run(
                """
                CREATE INDEX group_guid_lookup IF NOT EXISTS
                FOR (g:Group)
                ON (g.guid)
                """
            )
            
            # Index for EventType lookups
            session.run(
                """
                CREATE INDEX eventtype_code IF NOT EXISTS
                FOR (e:EventType)
                ON (e.code)
                """
            )
            
            # Composite index for client feed queries (impact + date)
            session.run(
                """
                CREATE INDEX document_feed_query IF NOT EXISTS
                FOR (d:Document)
                ON (d.impact_tier, d.impact_score, d.created_at)
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

    # =========================================================================
    # INSTRUMENT METHODS
    # =========================================================================

    def create_instrument(
        self,
        ticker: str,
        name: str,
        instrument_type: str,
        exchange: str,
        currency: str = "USD",
        country: str | None = None,
        isin: str | None = None,
        company_guid: str | None = None,
        properties: dict | None = None,
    ) -> GraphNode:
        """Create an instrument node
        
        Args:
            ticker: Instrument ticker symbol
            name: Instrument name
            instrument_type: Type (STOCK, ETF, ADR, etc.)
            exchange: Exchange code (NYSE, NASDAQ, etc.)
            currency: Trading currency (default USD)
            country: Country code
            isin: ISIN identifier
            company_guid: GUID of issuing company (creates ISSUED_BY relationship)
            properties: Additional properties
            
        Returns:
            Created instrument GraphNode
        """
        guid = f"{ticker}:{exchange}"  # Composite key
        props = properties or {}
        props.update({
            "ticker": ticker,
            "name": name,
            "instrument_type": instrument_type,
            "exchange": exchange,
            "currency": currency,
        })
        if country:
            props["country"] = country
        if isin:
            props["isin"] = isin
            
        instrument_node = self.create_node(NodeLabel.INSTRUMENT, guid, props)
        
        # Create ISSUED_BY relationship to company if provided
        if company_guid:
            try:
                self.create_relationship(
                    RelationType.ISSUED_BY,
                    NodeLabel.INSTRUMENT,
                    guid,
                    NodeLabel.COMPANY,
                    company_guid,
                )
            except RuntimeError:
                pass  # Company may not exist
                
        return instrument_node

    def get_instrument(self, ticker: str, exchange: str = "NYSE") -> GraphNode | None:
        """Get an instrument by ticker and exchange
        
        Args:
            ticker: Instrument ticker
            exchange: Exchange code (default NYSE)
            
        Returns:
            GraphNode if found, None otherwise
        """
        guid = f"{ticker}:{exchange}"
        return self.get_node(NodeLabel.INSTRUMENT, guid)

    # =========================================================================
    # EVENT TYPE METHODS
    # =========================================================================

    def create_event_type(
        self,
        code: str,
        name: str,
        category: str,
        base_impact: int = 50,
        default_tier: str = "SILVER",
        decay_lambda: float = 0.15,
    ) -> GraphNode:
        """Create an event type node
        
        Args:
            code: Event type code (e.g., "EARNINGS_BEAT")
            name: Human-readable name
            category: Event category (Earnings, M&A, etc.)
            base_impact: Base impact score (0-100)
            default_tier: Default impact tier
            decay_lambda: Decay rate for relevance
            
        Returns:
            Created event type GraphNode
        """
        props = {
            "code": code,
            "name": name,
            "category": category,
            "base_impact": base_impact,
            "default_tier": default_tier,
            "decay_lambda": decay_lambda,
        }
        return self.create_node(NodeLabel.EVENT_TYPE, code, props)

    def get_event_type(self, code: str) -> GraphNode | None:
        """Get an event type by code"""
        return self.get_node(NodeLabel.EVENT_TYPE, code)

    # =========================================================================
    # CLIENT METHODS
    # =========================================================================

    def create_client_type(
        self,
        code: str,
        name: str,
        default_alert_frequency: int = 10,
        default_impact_threshold: int = 50,
        default_decay_lambda: float = 0.15,
    ) -> GraphNode:
        """Create a client type template
        
        Args:
            code: Client type code (HEDGE_FUND, LONG_ONLY, etc.)
            name: Human-readable name
            default_alert_frequency: Default alerts per day
            default_impact_threshold: Minimum impact score for alerts
            default_decay_lambda: Default decay rate
            
        Returns:
            Created client type GraphNode
        """
        props = {
            "code": code,
            "name": name,
            "default_alert_frequency": default_alert_frequency,
            "default_impact_threshold": default_impact_threshold,
            "default_decay_lambda": default_decay_lambda,
        }
        return self.create_node(NodeLabel.CLIENT_TYPE, code, props)

    def create_client(
        self,
        guid: str,
        name: str,
        client_type_code: str,
        group_guid: str,
        properties: dict | None = None,
    ) -> GraphNode:
        """Create a client node
        
        Args:
            guid: Client GUID
            name: Client name (e.g., "Citadel")
            client_type_code: Client type code (creates IS_TYPE_OF relationship)
            group_guid: Group GUID (creates IN_GROUP relationship)
            properties: Additional properties (overrides for defaults)
            
        Returns:
            Created client GraphNode
        """
        props = properties or {}
        props["name"] = name
        
        client_node = self.create_node(NodeLabel.CLIENT, guid, props)
        
        # Create IS_TYPE_OF relationship
        try:
            self.create_relationship(
                RelationType.IS_TYPE_OF,
                NodeLabel.CLIENT,
                guid,
                NodeLabel.CLIENT_TYPE,
                client_type_code,
            )
        except RuntimeError:
            pass
            
        # Create IN_GROUP relationship
        try:
            self.create_relationship(
                RelationType.IN_GROUP,
                NodeLabel.CLIENT,
                guid,
                NodeLabel.GROUP,
                group_guid,
            )
        except RuntimeError:
            pass
            
        return client_node

    def create_client_profile(
        self,
        guid: str,
        client_guid: str,
        mandate_type: str | None = None,
        benchmark_guid: str | None = None,
        turnover_rate: str | None = None,
        esg_constrained: bool = False,
        horizon: str | None = None,
        properties: dict | None = None,
    ) -> GraphNode:
        """Create a client profile
        
        Args:
            guid: Profile GUID
            client_guid: Client GUID (creates HAS_PROFILE relationship)
            mandate_type: Mandate type (absolute, relative, etc.)
            benchmark_guid: Benchmark index GUID (creates BENCHMARKED_TO relationship)
            turnover_rate: Expected turnover (low, medium, high)
            esg_constrained: Whether ESG constraints apply
            horizon: Investment horizon
            properties: Additional properties
            
        Returns:
            Created profile GraphNode
        """
        props = properties or {}
        if mandate_type:
            props["mandate_type"] = mandate_type
        if turnover_rate:
            props["turnover_rate"] = turnover_rate
        if horizon:
            props["horizon"] = horizon
        props["esg_constrained"] = esg_constrained
        
        profile_node = self.create_node(NodeLabel.CLIENT_PROFILE, guid, props)
        
        # Create HAS_PROFILE relationship from client
        try:
            self.create_relationship(
                RelationType.HAS_PROFILE,
                NodeLabel.CLIENT,
                client_guid,
                NodeLabel.CLIENT_PROFILE,
                guid,
            )
        except RuntimeError:
            pass
            
        # Create BENCHMARKED_TO relationship if benchmark provided
        if benchmark_guid:
            try:
                self.create_relationship(
                    RelationType.BENCHMARKED_TO,
                    NodeLabel.CLIENT_PROFILE,
                    guid,
                    NodeLabel.INDEX,
                    benchmark_guid,
                )
            except RuntimeError:
                pass
                
        return profile_node

    def create_portfolio(
        self,
        guid: str,
        client_guid: str,
        as_of_date: datetime | None = None,
        properties: dict | None = None,
    ) -> GraphNode:
        """Create a portfolio node
        
        Args:
            guid: Portfolio GUID
            client_guid: Client GUID (creates HAS_PORTFOLIO relationship)
            as_of_date: Portfolio date
            properties: Additional properties
            
        Returns:
            Created portfolio GraphNode
        """
        props = properties or {}
        if as_of_date:
            props["as_of_date"] = as_of_date.isoformat()
            
        portfolio_node = self.create_node(NodeLabel.PORTFOLIO, guid, props)
        
        # Create HAS_PORTFOLIO relationship
        try:
            self.create_relationship(
                RelationType.HAS_PORTFOLIO,
                NodeLabel.CLIENT,
                client_guid,
                NodeLabel.PORTFOLIO,
                guid,
            )
        except RuntimeError:
            pass
            
        return portfolio_node

    def add_holding(
        self,
        portfolio_guid: str,
        instrument_guid: str,
        weight: float,
        shares: int | None = None,
        avg_cost: float | None = None,
    ) -> GraphRelationship:
        """Add a holding to a portfolio
        
        Args:
            portfolio_guid: Portfolio GUID
            instrument_guid: Instrument GUID
            weight: Position weight (0-1)
            shares: Number of shares
            avg_cost: Average cost basis
            
        Returns:
            Created HOLDS relationship
        """
        props: dict[str, Any] = {"weight": weight}
        if shares is not None:
            props["shares"] = shares
        if avg_cost is not None:
            props["avg_cost"] = avg_cost
            
        return self.create_relationship(
            RelationType.HOLDS,
            NodeLabel.PORTFOLIO,
            portfolio_guid,
            NodeLabel.INSTRUMENT,
            instrument_guid,
            props,
        )

    def create_watchlist(
        self,
        guid: str,
        client_guid: str,
        name: str,
        alert_threshold: int = 50,
        properties: dict | None = None,
    ) -> GraphNode:
        """Create a watchlist node
        
        Args:
            guid: Watchlist GUID
            client_guid: Client GUID (creates HAS_WATCHLIST relationship)
            name: Watchlist name
            alert_threshold: Minimum impact score for alerts
            properties: Additional properties
            
        Returns:
            Created watchlist GraphNode
        """
        props = properties or {}
        props["name"] = name
        props["alert_threshold"] = alert_threshold
        
        watchlist_node = self.create_node(NodeLabel.WATCHLIST, guid, props)
        
        # Create HAS_WATCHLIST relationship
        try:
            self.create_relationship(
                RelationType.HAS_WATCHLIST,
                NodeLabel.CLIENT,
                client_guid,
                NodeLabel.WATCHLIST,
                guid,
            )
        except RuntimeError:
            pass
            
        return watchlist_node

    def add_to_watchlist(
        self,
        watchlist_guid: str,
        instrument_guid: str,
        alert_threshold: int | None = None,
    ) -> GraphRelationship:
        """Add an instrument to a watchlist
        
        Args:
            watchlist_guid: Watchlist GUID
            instrument_guid: Instrument GUID
            alert_threshold: Override alert threshold for this instrument
            
        Returns:
            Created WATCHES relationship
        """
        props: dict[str, Any] = {"added_at": datetime.utcnow().isoformat()}
        if alert_threshold is not None:
            props["alert_threshold"] = alert_threshold
            
        return self.create_relationship(
            RelationType.WATCHES,
            NodeLabel.WATCHLIST,
            watchlist_guid,
            NodeLabel.INSTRUMENT,
            instrument_guid,
            props,
        )

    # =========================================================================
    # DOCUMENT IMPACT METHODS
    # =========================================================================

    def set_document_impact(
        self,
        document_guid: str,
        impact_score: float,
        impact_tier: str,
        decay_lambda: float = 0.15,
        event_type_code: str | None = None,
    ) -> GraphNode:
        """Set impact properties on a document
        
        Args:
            document_guid: Document GUID
            impact_score: Impact score (0-100)
            impact_tier: Impact tier (PLATINUM, GOLD, etc.)
            decay_lambda: Decay rate
            event_type_code: Primary event type (creates TRIGGERED_BY relationship)
            
        Returns:
            Updated document GraphNode
        """
        props = {
            "impact_score": impact_score,
            "impact_tier": impact_tier,
            "decay_lambda": decay_lambda,
        }
        
        with self._get_session() as session:
            result = session.run(
                """
                MATCH (d:Document {guid: $guid})
                SET d += $props
                RETURN d
                """,
                guid=document_guid,
                props=props,
            )
            record = result.single()
            if not record:
                raise RuntimeError(f"Document not found: {document_guid}")
                
        # Create TRIGGERED_BY relationship if event type provided
        if event_type_code:
            try:
                self.create_relationship(
                    RelationType.TRIGGERED_BY,
                    NodeLabel.DOCUMENT,
                    document_guid,
                    NodeLabel.EVENT_TYPE,
                    event_type_code,
                )
            except RuntimeError:
                pass
                
        return self.get_node(NodeLabel.DOCUMENT, document_guid)  # type: ignore

    def add_document_affects(
        self,
        document_guid: str,
        instrument_guid: str,
        direction: str | None = None,
        magnitude: float | None = None,
        confidence: float = 1.0,
    ) -> GraphRelationship:
        """Record that a document affects an instrument
        
        Args:
            document_guid: Document GUID
            instrument_guid: Instrument GUID
            direction: Impact direction (positive, negative, neutral)
            magnitude: Expected price impact magnitude
            confidence: Confidence score (0-1)
            
        Returns:
            Created AFFECTS relationship
        """
        props: dict[str, Any] = {"confidence": confidence}
        if direction:
            props["direction"] = direction
        if magnitude is not None:
            props["magnitude"] = magnitude
            
        return self.create_relationship(
            RelationType.AFFECTS,
            NodeLabel.DOCUMENT,
            document_guid,
            NodeLabel.INSTRUMENT,
            instrument_guid,
            props,
        )

    # =========================================================================
    # CLIENT FEED QUERIES
    # =========================================================================

    def get_client_feed(
        self,
        client_guid: str,
        permitted_groups: list[str],
        limit: int = 50,
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
        include_portfolio: bool = True,
        include_watchlist: bool = True,
    ) -> list[dict[str, Any]]:
        """Get ranked news feed for a client
        
        Returns documents relevant to the client's portfolio and watchlist,
        respecting group permissions and applying time-decay.
        
        Args:
            client_guid: Client GUID
            permitted_groups: List of group GUIDs the client can access
            limit: Maximum results
            min_impact_score: Minimum impact score filter
            impact_tiers: Filter by impact tiers
            include_portfolio: Include portfolio holdings
            include_watchlist: Include watchlist instruments
            
        Returns:
            List of documents with relevance scores
        """
        # Build the query dynamically based on options
        query = """
        // Get client and their instruments
        MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(cg:Group)
        WHERE cg.guid IN $permitted_groups
        
        // Get documents in permitted groups
        MATCH (d:Document)-[:IN_GROUP]->(g:Group)
        WHERE g.guid IN $permitted_groups
        """
        
        if min_impact_score is not None:
            query += f"\n  AND d.impact_score >= {min_impact_score}"
            
        if impact_tiers:
            tiers_str = ", ".join(f"'{t}'" for t in impact_tiers)
            query += f"\n  AND d.impact_tier IN [{tiers_str}]"
        
        query += """
        
        // Find documents affecting instruments in portfolio or watchlist
        OPTIONAL MATCH (d)-[affects:AFFECTS]->(inst:Instrument)
        OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)-[holds:HOLDS]->(inst)
        OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(inst)
        
        // Scoring weights calibrated to graph_architecture.md:
        // - Position weight * 100: Higher positions get proportionally more weight
        // - Watchlist: 50 points (elevated from 25 - watchlist = active interest)
        // - Benchmark constituent: add 30 points via separate query if needed
        WITH d, inst, affects, holds, w,
             CASE WHEN holds IS NOT NULL THEN holds.weight * 100 ELSE 0 END AS position_boost,
             CASE WHEN w IS NOT NULL THEN 50 ELSE 0 END AS watchlist_boost,
             COALESCE(d.impact_score, 0) AS base_score,
             COALESCE(d.decay_lambda, 0.15) AS decay_lambda
        
        WHERE (holds IS NOT NULL OR w IS NOT NULL OR inst IS NULL)
        
        // Calculate relevance without time decay for now (date parsing is complex)
        WITH d, inst,
             base_score + position_boost + watchlist_boost AS total_score,
             base_score AS decayed_score
        
        RETURN DISTINCT d.guid AS document_guid,
               d.title AS title,
               d.impact_score AS impact_score,
               d.impact_tier AS impact_tier,
               d.created_at AS created_at,
               collect(DISTINCT inst.ticker) AS affected_instruments,
               max(total_score) AS relevance_score,
               max(decayed_score) AS current_relevance
        ORDER BY current_relevance DESC
        LIMIT $limit
        """
        
        with self._get_session() as session:
            result = session.run(
                query,  # type: ignore[arg-type]  # Dynamic query construction
                client_guid=client_guid,
                permitted_groups=permitted_groups,
                limit=limit,
            )
            return [dict(record) for record in result]

    def get_documents_by_source(
        self,
        source_guid: str,
        permitted_groups: list[str] | None = None,
    ) -> list[GraphNode]:
        """Get all documents produced by a source

        Args:
            source_guid: Source GUID
            permitted_groups: If provided, only return docs in these groups

        Returns:
            List of document GraphNodes
        """
        with self._get_session() as session:
            if permitted_groups:
                query = """
                MATCH (d:Document)-[:PRODUCED_BY]->(s:Source {guid: $source_guid})
                MATCH (d)-[:IN_GROUP]->(g:Group)
                WHERE g.guid IN $permitted_groups
                RETURN d
                ORDER BY d.created_at DESC
                """
                result = session.run(
                    query,
                    source_guid=source_guid,
                    permitted_groups=permitted_groups,
                )
            else:
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

    def get_documents_mentioning_company(
        self,
        company_ticker: str,
        permitted_groups: list[str] | None = None,
    ) -> list[GraphNode]:
        """Get all documents mentioning a company

        Args:
            company_ticker: Company ticker symbol
            permitted_groups: If provided, only return docs in these groups

        Returns:
            List of document GraphNodes
        """
        with self._get_session() as session:
            if permitted_groups:
                query = """
                MATCH (d:Document)-[:MENTIONS]->(c:Company {guid: $ticker})
                MATCH (d)-[:IN_GROUP]->(g:Group)
                WHERE g.guid IN $permitted_groups
                RETURN d
                ORDER BY d.created_at DESC
                """
                result = session.run(
                    query,
                    ticker=company_ticker,
                    permitted_groups=permitted_groups,
                )
            else:
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
        permitted_groups: list[str] | None = None,
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
            permitted_groups: If provided, only return docs in these groups

        Returns:
            TraversalResult with related nodes and relationships
        """
        with self._get_session() as session:
            # Find documents via shared companies
            if permitted_groups:
                query_company = """
                MATCH (d1:Document {guid: $guid})-[:MENTIONS]->(c:Company)<-[:MENTIONS]-(d2:Document)
                MATCH (d2)-[:IN_GROUP]->(g:Group)
                WHERE d1 <> d2 AND g.guid IN $permitted_groups
                RETURN DISTINCT d2, c, 'company' as via
                LIMIT $limit
                """
                result = session.run(
                    query_company,
                    guid=document_guid,
                    limit=limit,
                    permitted_groups=permitted_groups,
                )
            else:
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
            if permitted_groups:
                query_source = """
                MATCH (d1:Document {guid: $guid})-[:PRODUCED_BY]->(s:Source)<-[:PRODUCED_BY]-(d2:Document)
                MATCH (d2)-[:IN_GROUP]->(g:Group)
                WHERE d1 <> d2 AND g.guid IN $permitted_groups
                RETURN DISTINCT d2, s, 'source' as via
                LIMIT $limit
                """
                result2 = session.run(
                    query_source,
                    guid=document_guid,
                    limit=limit,
                    permitted_groups=permitted_groups,
                )
            else:
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
    password: str = "testpassword",  # nosec B107
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
