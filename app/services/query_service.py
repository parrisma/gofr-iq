"""Query Service for Hybrid Search

Orchestrates similarity search (ChromaDB) with graph enrichment (Neo4j)
and applies group-based access control, metadata filtering, and trust scoring.

Query Flow:
1. Validate user's permitted groups
2. Execute ChromaDB similarity search (filtered by groups)
3. Apply metadata filters (date, region, sector, language)
4. Enrich with Neo4j graph context (related entities)
5. Apply trust level scoring boost
6. Return ranked results
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional, TYPE_CHECKING

from app.services.document_store import DocumentStore
from app.services.embedding_index import EmbeddingIndex, SimilarityResult
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.source_registry import SourceRegistry
from app.logger import StructuredLogger

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

logger = StructuredLogger(__name__)


@dataclass
class QueryFilters:
    """Filters for query operations

    Attributes:
        date_from: Filter documents from this date (inclusive)
        date_to: Filter documents to this date (inclusive)
        regions: Filter by regions
        sectors: Filter by sectors
        companies: Filter by company tickers/names
        sources: Filter by source GUIDs
        languages: Filter by language codes
        min_impact_score: Minimum impact score (0-100)
        impact_tiers: Filter by impact tiers (PLATINUM, GOLD, SILVER, BRONZE, STANDARD)
        event_types: Filter by event type codes
        client_guid: Client GUID for personalization
    """

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    regions: Optional[list[str]] = None
    sectors: Optional[list[str]] = None
    companies: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    languages: Optional[list[str]] = None
    min_impact_score: Optional[float] = None
    impact_tiers: Optional[list[str]] = None
    event_types: Optional[list[str]] = None
    client_guid: Optional[str] = None


@dataclass
class ScoringWeights:
    """Weights for hybrid scoring

    Attributes:
        semantic: Weight for semantic similarity score (0-1)
        trust: Weight for source trust level boost (0-1)
        recency: Weight for recency boost (0-1)
        graph_boost: Bonus score for graph-expanded results (0-1)
    """

    semantic: float = 0.6
    trust: float = 0.2
    recency: float = 0.1
    graph_boost: float = 0.1  # Bonus for graph-discovered docs

    def __post_init__(self) -> None:
        """Validate weights sum to 1.0"""
        total = self.semantic + self.trust + self.recency + self.graph_boost
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")


@dataclass
class ClientNewsWeights:
    """Weights for top-client-news scoring

    Attributes:
        semantic: Weight for semantic similarity score (0-1)
        graph: Weight for graph relevance score (0-1)
        impact: Weight for impact score (0-1)
        recency: Weight for recency score (0-1)
    """

    semantic: float = 0.35
    graph: float = 0.35
    impact: float = 0.20
    recency: float = 0.10

    @classmethod
    def for_client_type(cls, client_type: str | None) -> "ClientNewsWeights":
        if client_type in {"LONG_ONLY", "PENSION"}:
            return cls(semantic=0.30, graph=0.30, impact=0.20, recency=0.20)
        return cls()


@dataclass
class QueryResult:
    """A single query result

    Attributes:
        document_guid: Document GUID
        title: Document title
        content_snippet: Relevant content snippet
        score: Combined relevance score (0-1)
        similarity_score: Raw semantic similarity score
        trust_score: Source trust level contribution
        recency_score: Recency contribution
        graph_score: Graph relationship contribution (for expanded results)
        source_guid: Source this document came from
        source_name: Source name
        language: Document language
        created_at: Document creation timestamp
        metadata: Additional document metadata
        graph_context: Related entities from graph
        impact_score: Document impact score (0-100)
        impact_tier: Impact tier (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
        event_type: Event type code
        discovered_via: How this result was found ('semantic', 'graph', 'both')
    """

    document_guid: str
    title: str
    content_snippet: str
    score: float
    similarity_score: float
    trust_score: float = 0.0
    recency_score: float = 0.0
    graph_score: float = 0.0
    source_guid: str = ""
    source_name: str = ""
    language: str = ""
    created_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)
    graph_context: dict = field(default_factory=dict)
    impact_score: Optional[float] = None
    impact_tier: Optional[str] = None
    event_type: Optional[str] = None
    discovered_via: str = "semantic"


@dataclass
class QueryResponse:
    """Response from a query operation

    Attributes:
        query: Original query text
        results: List of query results
        total_found: Total matching documents (before limit)
        filters_applied: Filters that were applied
        execution_time_ms: Query execution time in milliseconds
    """

    query: str
    results: list[QueryResult]
    total_found: int
    filters_applied: dict = field(default_factory=dict)
    execution_time_ms: float = 0.0


class QueryService:
    """Hybrid search service combining semantic similarity and graph context

    Provides:
    - Semantic similarity search via ChromaDB
    - Group-based access control
    - Metadata filtering
    - Graph enrichment via Neo4j
    - Trust level scoring boost
    """

    def __init__(
        self,
        embedding_index: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        graph_index: Optional[GraphIndex] = None,
        default_weights: Optional[ScoringWeights] = None,
    ) -> None:
        """Initialize query service

        Args:
            embedding_index: ChromaDB embedding index for similarity search
            document_store: Document storage for retrieving full documents
            source_registry: Source registry for trust levels
            graph_index: Optional Neo4j graph index for enrichment
            default_weights: Default scoring weights
        """
        self.embedding_index = embedding_index
        self.document_store = document_store
        self.source_registry = source_registry
        self.graph_index = graph_index
        self.default_weights = default_weights or ScoringWeights()

    def query(
        self,
        query_text: str,
        group_guids: list[str],
        n_results: int = 10,
        filters: Optional[QueryFilters] = None,
        weights: Optional[ScoringWeights] = None,
        include_graph_context: bool = True,
        enable_graph_expansion: bool = True,
    ) -> QueryResponse:
        """Execute hybrid search query with graph-expanded retrieval

        Combines semantic similarity search (ChromaDB) with graph traversal (Neo4j)
        to surface related documents that pure semantic search would miss.

        Args:
            query_text: Search query text
            group_guids: User's permitted group GUIDs (for access control)
            n_results: Maximum number of results to return
            filters: Optional query filters
            weights: Optional custom scoring weights
            include_graph_context: Whether to include graph enrichment metadata
            enable_graph_expansion: Whether to expand results via graph traversal

        Returns:
            QueryResponse with ranked results from both semantic and graph sources
        """
        import time

        start_time = time.time()
        filters = filters or QueryFilters()
        weights = weights or self.default_weights

        # Step 1: Execute ChromaDB similarity search with group filtering
        similarity_results = self._execute_similarity_search(
            query_text=query_text,
            group_guids=group_guids,
            n_results=n_results * 3,  # Fetch extra for filtering
            filters=filters,
        )

        # Step 2: Apply metadata filters
        filtered_results = self._apply_metadata_filters(
            results=similarity_results,
            filters=filters,
        )

        # Step 3: Build query results with scoring
        query_results = self._build_query_results(
            similarity_results=filtered_results,
            weights=weights,
        )
        
        # Track semantic result GUIDs to avoid duplicates
        semantic_guids = {r.document_guid for r in query_results}

        # Step 4: Graph-expanded retrieval (NEW)
        if enable_graph_expansion and self.graph_index:
            graph_expanded = self._expand_via_graph(
                semantic_results=query_results,
                group_guids=group_guids,
                weights=weights,
                exclude_guids=semantic_guids,
                max_expansion=n_results,  # Up to n_results additional docs
            )
            query_results.extend(graph_expanded)

        # Step 5: Add graph context if enabled
        if include_graph_context and self.graph_index:
            query_results = self._enrich_with_graph_context(query_results)

        # Step 6: Sort by final score and limit
        query_results.sort(key=lambda r: r.score, reverse=True)
        query_results = query_results[:n_results]

        execution_time = (time.time() - start_time) * 1000

        return QueryResponse(
            query=query_text,
            results=query_results,
            total_found=len(filtered_results) + len([r for r in query_results if r.discovered_via == "graph"]),
            filters_applied=self._filters_to_dict(filters),
            execution_time_ms=execution_time,
        )

    def get_top_client_news(
        self,
        client_guid: str,
        group_guids: list[str],
        limit: int = 3,
        time_window_hours: int = 24,
        include_portfolio: bool = True,
        include_watchlist: bool = True,
        include_lateral_graph: bool = True,
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
        weights: ClientNewsWeights | None = None,
        filters: QueryFilters | None = None,
        llm_service: "LLMService | None" = None,
    ) -> list[dict[str, Any]]:
        """Get top news for a client using hybrid graph + semantic search.

        Returns a ranked shortlist of news items personalized for the client.
        """
        if not self.graph_index:
            logger.warning("Top client news requested without graph index")
            return []

        if limit <= 0:
            return []

        profile = self._get_client_profile_context(client_guid, group_guids)
        if not profile:
            return []

        holdings = self._get_client_holdings(client_guid) if include_portfolio else []
        watchlist = self._get_client_watchlist(client_guid) if include_watchlist else []
        exclusions = self._get_client_exclusions(client_guid) if profile.get("esg_constrained") else {
            "companies": [],
            "sectors": [],
        }

        benchmark = profile.get("benchmark")
        holding_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        watchlist_tickers = [t for t in watchlist if t]

        if benchmark:
            watchlist_tickers.append(benchmark)

        resolved_min_impact = min_impact_score
        if resolved_min_impact is None:
            resolved_min_impact = profile.get("impact_threshold")

        resolved_impact_tiers = impact_tiers or ["PLATINUM", "GOLD", "SILVER"]
        weights = weights or ClientNewsWeights.for_client_type(profile.get("client_type"))

        now = datetime.utcnow()
        time_cutoff = now - timedelta(hours=time_window_hours)

        # ------------------------------------------------------------
        # Graph candidates
        # ------------------------------------------------------------
        graph_candidates: dict[str, dict[str, Any]] = {}

        def add_graph_candidates(
            docs: list[dict[str, Any]],
            reason: str,
            base_score: float,
            position_weights: dict[str, float] | None = None,
        ) -> None:
            for doc in docs:
                guid = doc.get("document_guid")
                if not guid:
                    continue
                entry = graph_candidates.setdefault(guid, {
                    "document_guid": guid,
                    "title": doc.get("title"),
                    "created_at": doc.get("created_at"),
                    "impact_score": doc.get("impact_score"),
                    "impact_tier": doc.get("impact_tier"),
                    "affected_instruments": doc.get("affected_instruments", []),
                    "reasons": set(),
                    "graph_score": 0.0,
                })
                entry["reasons"].add(reason)

                weight_boost = 0.0
                if position_weights:
                    for ticker in entry.get("affected_instruments", []):
                        weight_boost = max(weight_boost, position_weights.get(ticker, 0.0))

                entry["graph_score"] = max(
                    entry["graph_score"],
                    min(1.0, base_score + min(0.3, weight_boost)),
                )

        if holding_tickers:
            holding_weights = {h["ticker"]: h.get("weight", 0.0) for h in holdings if h.get("ticker")}
            direct_docs = self._get_documents_for_tickers(
                tickers=holding_tickers,
                group_guids=group_guids,
                min_impact_score=resolved_min_impact,
                impact_tiers=resolved_impact_tiers,
            )
            add_graph_candidates(direct_docs, "DIRECT_HOLDING", 1.0, holding_weights)

        if watchlist_tickers:
            watch_docs = self._get_documents_for_tickers(
                tickers=watchlist_tickers,
                group_guids=group_guids,
                min_impact_score=resolved_min_impact,
                impact_tiers=resolved_impact_tiers,
            )
            add_graph_candidates(watch_docs, "WATCHLIST", 0.8)

        if include_lateral_graph and holding_tickers:
            lateral = self._expand_lateral_tickers(holding_tickers)

            if lateral.get("competitors"):
                comp_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("competitors", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(comp_docs, "COMPETITOR", 0.6)

            if lateral.get("suppliers"):
                supply_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("suppliers", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(supply_docs, "SUPPLY_CHAIN", 0.6)

            if lateral.get("peers"):
                peer_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("peers", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(peer_docs, "PEER", 0.5)

        # ------------------------------------------------------------
        # Semantic candidates
        # ------------------------------------------------------------
        semantic_query = self._build_client_query_text(
            profile=profile,
            holdings=holding_tickers,
            watchlist=watchlist_tickers,
            llm_service=llm_service,
        )

        semantic_filters = filters or QueryFilters()
        if semantic_filters.date_from is None:
            semantic_filters.date_from = time_cutoff
        if semantic_filters.date_to is None:
            semantic_filters.date_to = now

        semantic_results = self.query(
            query_text=semantic_query,
            group_guids=group_guids,
            n_results=max(limit * 5, 15),
            filters=semantic_filters,
            include_graph_context=False,
            enable_graph_expansion=True,
        ).results

        for result in semantic_results:
            doc_guid = result.document_guid
            entry = graph_candidates.setdefault(doc_guid, {
                "document_guid": doc_guid,
                "title": result.title,
                "created_at": result.created_at.isoformat() if result.created_at else None,
                "impact_score": result.metadata.get("impact_score"),
                "impact_tier": result.metadata.get("impact_tier"),
                "affected_instruments": result.metadata.get("companies", []),
                "reasons": set(),
                "graph_score": 0.0,
            })
            entry["semantic_score"] = max(entry.get("semantic_score", 0.0), result.similarity_score)
            entry["reasons"].add("SEMANTIC_MATCH")

        # ------------------------------------------------------------
        # Apply time window + ESG exclusions
        # ------------------------------------------------------------
        candidates = list(graph_candidates.values())
        candidates = [c for c in candidates if self._within_time_window(c.get("created_at"), time_cutoff)]

        if exclusions["companies"] or exclusions["sectors"]:
            entities = self._get_document_entities([c["document_guid"] for c in candidates])
            filtered: list[dict[str, Any]] = []
            for c in candidates:
                doc_entities = entities.get(c["document_guid"], {"companies": [], "sectors": []})
                if self._violates_exclusions(doc_entities, exclusions):
                    continue
                filtered.append(c)
            candidates = filtered

        # ------------------------------------------------------------
        # Final scoring
        # ------------------------------------------------------------
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            impact_score = candidate.get("impact_score")
            impact_norm = self._normalize_impact_score(impact_score)

            created_at = self._parse_datetime(candidate.get("created_at"))
            recency = self._calculate_recency_score({"created_at": created_at}, now)

            semantic_score = candidate.get("semantic_score", 0.0)
            graph_score = candidate.get("graph_score", 0.0)

            final_score = (
                weights.semantic * semantic_score
                + weights.graph * graph_score
                + weights.impact * impact_norm
                + weights.recency * recency
            )

            reasons = sorted(candidate.get("reasons", set()))
            why = self._build_why_it_matters(
                title=candidate.get("title"),
                reasons=reasons,
                impact_score=impact_score,
                tickers=candidate.get("affected_instruments", []),
                llm_service=llm_service,
            )

            scored.append({
                "document_guid": candidate.get("document_guid"),
                "title": candidate.get("title"),
                "created_at": candidate.get("created_at"),
                "impact_score": impact_score,
                "impact_tier": candidate.get("impact_tier"),
                "affected_instruments": candidate.get("affected_instruments", []),
                "relevance_score": final_score,
                "reasons": reasons,
                "why_it_matters": why,
            })

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored[:limit]

    def _build_client_query_text(
        self,
        profile: dict[str, Any],
        holdings: list[str],
        watchlist: list[str],
        llm_service: "LLMService | None" = None,
    ) -> str:
        """Build semantic query text from client profile context."""
        base = (
            f"Client type: {profile.get('client_type', 'UNKNOWN')}. "
            f"Mandate: {profile.get('mandate_type', 'unspecified')}. "
            f"Horizon: {profile.get('horizon', 'unspecified')}. "
            f"ESG constrained: {profile.get('esg_constrained', False)}. "
        )
        tickers = " ".join(sorted(set(holdings + watchlist)))
        query = f"{base} Portfolio and watchlist tickers: {tickers}."

        if llm_service is None:
            return query

        try:
            from app.services.llm_service import ChatMessage

            prompt = (
                "Rewrite the following client context into a short search query "
                "for relevant market news. Keep it under 25 words and include key tickers. "
                "Return only the query text.\n\n"
                f"{query}"
            )
            result = llm_service.chat_completion(
                messages=[ChatMessage(role="user", content=prompt)],
            )
            return result.content.strip() or query
        except Exception:
            return query

    def _get_client_profile_context(
        self, client_guid: str, group_guids: list[str]
    ) -> dict[str, Any] | None:
        """Fetch core client profile info with group permission check."""
        if not self.graph_index:
            return None
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    WHERE g.guid IN $group_guids
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (cp)-[:BENCHMARKED_TO]->(b:Instrument)
                    RETURN c.guid AS client_guid,
                           c.impact_threshold AS impact_threshold,
                           ct.code AS client_type,
                           cp.mandate_type AS mandate_type,
                           cp.horizon AS horizon,
                           cp.esg_constrained AS esg_constrained,
                           b.ticker AS benchmark
                    """,
                    client_guid=client_guid,
                    group_guids=group_guids,
                )
                record = result.single()
                if not record:
                    return None
                return dict(record)
        except Exception:
            return None

    def _get_client_holdings(self, client_guid: str) -> list[dict[str, Any]]:
        if not self.graph_index:
            return []
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)-[h:HOLDS]->(i:Instrument)
                    RETURN i.ticker AS ticker, h.weight AS weight
                    """,
                    client_guid=client_guid,
                )
                return [dict(record) for record in result if record.get("ticker")]
        except Exception:
            return []

    def _get_client_watchlist(self, client_guid: str) -> list[str]:
        if not self.graph_index:
            return []
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)-[:WATCHES]->(i:Instrument)
                    RETURN DISTINCT i.ticker AS ticker
                    """,
                    client_guid=client_guid,
                )
                return [record["ticker"] for record in result if record.get("ticker")]
        except Exception:
            return []

    def _get_client_exclusions(self, client_guid: str) -> dict[str, list[str]]:
        if not self.graph_index:
            return {"companies": [], "sectors": []}
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (cp)-[:EXCLUDES]->(exCompany:Company)
                    OPTIONAL MATCH (cp)-[:EXCLUDES]->(exSector:Sector)
                    RETURN collect(DISTINCT exCompany.name) AS companies,
                           collect(DISTINCT exSector.name) AS sectors
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return {"companies": [], "sectors": []}
                return {
                    "companies": [c for c in record["companies"] if c],
                    "sectors": [s for s in record["sectors"] if s],
                }
        except Exception:
            return {"companies": [], "sectors": []}

    def _get_document_entities(self, document_guids: list[str]) -> dict[str, dict[str, list[str]]]:
        if not self.graph_index or not document_guids:
            return {}
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (d:Document)-[:AFFECTS]->(:Instrument)-[:ISSUED_BY]->(c:Company)-[:BELONGS_TO]->(s:Sector)
                    WHERE d.guid IN $guids
                    RETURN d.guid AS guid,
                           collect(DISTINCT c.name) AS companies,
                           collect(DISTINCT s.name) AS sectors
                    """,
                    guids=document_guids,
                )
                return {
                    record["guid"]: {
                        "companies": [c for c in record["companies"] if c],
                        "sectors": [s for s in record["sectors"] if s],
                    }
                    for record in result
                    if record.get("guid")
                }
        except Exception:
            return {}

    def _get_documents_for_tickers(
        self,
        tickers: list[str],
        group_guids: list[str],
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.graph_index or not tickers:
            return []
        query = """
        MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
        WHERE i.ticker IN $tickers
        MATCH (d)-[:IN_GROUP]->(g:Group)
        WHERE g.guid IN $group_guids
        """
        if min_impact_score is not None:
            query += "\n  AND d.impact_score >= $min_impact_score"
        if impact_tiers:
            query += "\n  AND d.impact_tier IN $impact_tiers"
        query += """
        RETURN d.guid AS document_guid,
               d.title AS title,
               d.created_at AS created_at,
               d.impact_score AS impact_score,
               d.impact_tier AS impact_tier,
               collect(DISTINCT i.ticker) AS affected_instruments
        ORDER BY d.created_at DESC
        LIMIT $limit
        """
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    query,
                    tickers=tickers,
                    group_guids=group_guids,
                    min_impact_score=min_impact_score,
                    impact_tiers=impact_tiers,
                    limit=limit,
                )
                return [dict(record) for record in result]
        except Exception:
            return []

    def _expand_lateral_tickers(self, tickers: list[str]) -> dict[str, list[str]]:
        if not self.graph_index or not tickers:
            return {"competitors": [], "suppliers": [], "peers": []}
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (i:Instrument)-[:ISSUED_BY]->(c:Company)
                    WHERE i.ticker IN $tickers
                    OPTIONAL MATCH (c)-[:COMPETES_WITH]-(cc:Company)-[:ISSUED_BY]->(ci:Instrument)
                    OPTIONAL MATCH (c)<-[:SUPPLIES_TO|:SUPPLIER_OF|:PARTNER_OF]-(sc:Company)-[:ISSUED_BY]->(si:Instrument)
                    OPTIONAL MATCH (c)-[:BELONGS_TO]->(s:Sector)<-[:BELONGS_TO]-(pc:Company)-[:ISSUED_BY]->(pi:Instrument)
                    RETURN collect(DISTINCT ci.ticker) AS competitors,
                           collect(DISTINCT si.ticker) AS suppliers,
                           collect(DISTINCT pi.ticker) AS peers
                    """,
                    tickers=tickers,
                )
                record = result.single()
                if not record:
                    return {"competitors": [], "suppliers": [], "peers": []}
                return {
                    "competitors": [t for t in record["competitors"] if t],
                    "suppliers": [t for t in record["suppliers"] if t],
                    "peers": [t for t in record["peers"] if t],
                }
        except Exception:
            return {"competitors": [], "suppliers": [], "peers": []}

    def _within_time_window(self, created_at: Any, cutoff: datetime) -> bool:
        if created_at is None:
            return True
        parsed = self._parse_datetime(created_at)
        if not parsed:
            return True
        if parsed.tzinfo is not None and cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=parsed.tzinfo)
        if parsed.tzinfo is None and cutoff.tzinfo is not None:
            parsed = parsed.replace(tzinfo=cutoff.tzinfo)
        return parsed >= cutoff

    def _normalize_impact_score(self, impact_score: Any) -> float:
        try:
            score = float(impact_score)
            return max(0.0, min(1.0, score / 100.0))
        except (TypeError, ValueError):
            return 0.0

    def _violates_exclusions(
        self,
        doc_entities: dict[str, list[str]],
        exclusions: dict[str, list[str]],
    ) -> bool:
        excluded_companies = {c.lower() for c in exclusions.get("companies", []) if c}
        excluded_sectors = {s.lower() for s in exclusions.get("sectors", []) if s}

        for company in doc_entities.get("companies", []):
            if company and company.lower() in excluded_companies:
                return True
        for sector in doc_entities.get("sectors", []):
            if sector and sector.lower() in excluded_sectors:
                return True
        return False

    def _build_why_it_matters(
        self,
        title: str | None,
        reasons: list[str],
        impact_score: Any,
        tickers: list[str],
        llm_service: "LLMService | None" = None,
    ) -> str:
        reason_text = ", ".join(reasons) if reasons else "relevant signal"
        ticker_text = ", ".join(tickers[:3]) if tickers else "client exposures"
        base = f"{reason_text} impacting {ticker_text}."

        if llm_service is None:
            return base

        try:
            from app.services.llm_service import ChatMessage

            prompt = (
                "Write a single short sentence (<=20 words) explaining why this news matters to the client. "
                "Use the reason and tickers.\n\n"
                f"Title: {title}\nReason: {reason_text}\nTickers: {ticker_text}\nImpact: {impact_score}\n"
            )
            result = llm_service.chat_completion(
                messages=[ChatMessage(role="user", content=prompt)],
            )
            return result.content.strip() or base
        except Exception:
            return base

    def _execute_similarity_search(
        self,
        query_text: str,
        group_guids: list[str],
        n_results: int,
        filters: QueryFilters,
    ) -> list[SimilarityResult]:
        """Execute ChromaDB similarity search"""
        return self.embedding_index.search(
            query=query_text,
            n_results=n_results,
            group_guids=group_guids if group_guids else None,
            source_guids=filters.sources,
            languages=filters.languages,
        )

    def _apply_metadata_filters(
        self,
        results: list[SimilarityResult],
        filters: QueryFilters,
    ) -> list[SimilarityResult]:
        """Apply in-memory metadata filters"""
        filtered: list[SimilarityResult] = []

        for result in results:
            # Get document metadata
            metadata = result.metadata

            # Date filtering
            if filters.date_from or filters.date_to:
                created_at_str = metadata.get("created_at")
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(str(created_at_str))
                        if filters.date_from and created_at < filters.date_from:
                            continue
                        if filters.date_to and created_at > filters.date_to:
                            continue
                    except (ValueError, TypeError):
                        pass  # Skip date filter if can't parse

            # Region filtering
            if filters.regions:
                doc_region = metadata.get("region", "")
                if doc_region not in filters.regions:
                    continue

            # Sector filtering
            if filters.sectors:
                doc_sectors = metadata.get("sectors", [])
                if isinstance(doc_sectors, str):
                    import json

                    try:
                        doc_sectors = json.loads(doc_sectors)
                    except json.JSONDecodeError:
                        doc_sectors = [doc_sectors]
                if not any(s in doc_sectors for s in filters.sectors):
                    continue

            # Company filtering
            if filters.companies:
                doc_companies = metadata.get("companies", [])
                if isinstance(doc_companies, str):
                    import json

                    try:
                        doc_companies = json.loads(doc_companies)
                    except json.JSONDecodeError:
                        doc_companies = [doc_companies]
                if not any(c in doc_companies for c in filters.companies):
                    continue

            filtered.append(result)

        return filtered

    def _build_query_results(
        self,
        similarity_results: list[SimilarityResult],
        weights: ScoringWeights,
    ) -> list[QueryResult]:
        """Build query results with scoring"""
        from datetime import timezone
        
        results: list[QueryResult] = []
        now = datetime.now(timezone.utc)

        # Group results by document to avoid duplicates
        doc_results: dict[str, list[SimilarityResult]] = {}
        for sim_result in similarity_results:
            doc_guid = sim_result.document_guid
            if doc_guid not in doc_results:
                doc_results[doc_guid] = []
            doc_results[doc_guid].append(sim_result)

        for doc_guid, sim_results in doc_results.items():
            # Use best similarity score for the document
            best_result = max(sim_results, key=lambda r: r.score)
            metadata = best_result.metadata

            # Get source trust level
            source_guid = str(metadata.get("source_guid", ""))
            trust_level = self._get_trust_level(source_guid)

            # Calculate recency score (newer = higher)
            recency_score = self._calculate_recency_score(metadata, now)

            # Calculate combined score
            combined_score = (
                weights.semantic * best_result.score
                + weights.trust * trust_level
                + weights.recency * recency_score
            )

            # Build result
            result = QueryResult(
                document_guid=doc_guid,
                title=str(metadata.get("title", "")),
                content_snippet=best_result.content[:500] if best_result.content else "",
                score=combined_score,
                similarity_score=best_result.score,
                trust_score=trust_level,
                recency_score=recency_score,
                source_guid=source_guid,
                source_name=str(metadata.get("source_name", "")),
                language=str(metadata.get("language", "")),
                created_at=self._parse_datetime(metadata.get("created_at")),
                metadata={
                    k: v
                    for k, v in metadata.items()
                    if k
                    not in (
                        "document_guid",
                        "source_guid",
                        "title",
                        "language",
                        "created_at",
                    )
                },
            )
            results.append(result)

        return results

    def _get_trust_level(self, source_guid: str) -> float:
        """Get trust level for a source (0-1)"""
        if not source_guid:
            return 0.5  # Default trust

        try:
            source = self.source_registry.get(source_guid)
            if source:
                # Map trust level enum to numeric score (0-1)
                trust_map = {
                    "high": 1.0,
                    "medium": 0.75,
                    "low": 0.5,
                    "unverified": 0.25,
                }
                return trust_map.get(source.trust_level.value, 0.5)
        except Exception:
            pass  # nosec B110

        return 0.5  # Default trust

    def _calculate_recency_score(
        self, metadata: dict[str, Any], now: datetime
    ) -> float:
        """Calculate recency score (0-1, newer = higher)"""
        from datetime import timezone
        
        created_at = self._parse_datetime(metadata.get("created_at"))
        if not created_at:
            return 0.5  # Default for unknown dates

        # Ensure both datetimes are timezone-aware for comparison
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Calculate days since creation
        days_old = (now - created_at).days
        if days_old < 0:
            days_old = 0

        # Exponential decay: score halves every 30 days
        decay_rate = 0.023  # ln(2) / 30
        score = 1.0 * (2.718 ** (-decay_rate * days_old))

        return max(0.0, min(1.0, score))

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _expand_via_graph(
        self,
        semantic_results: list[QueryResult],
        group_guids: list[str],
        weights: ScoringWeights,
        exclude_guids: set[str],
        max_expansion: int = 10,
    ) -> list[QueryResult]:
        """Expand results via graph traversal to find related documents
        
        This is the key hybrid integration: starting from semantic hits,
        traverse the graph to find documents connected via:
        - Shared instruments (AFFECTS relationships)
        - Peer companies (PEER_OF relationships)
        - Same event types (TRIGGERED_BY relationships)
        - Shared companies (MENTIONS relationships)
        
        Args:
            semantic_results: Initial results from semantic search
            group_guids: Permitted groups for access control
            weights: Scoring weights (graph_boost used for expanded docs)
            exclude_guids: Document GUIDs to exclude (already in results)
            max_expansion: Maximum number of expanded results
            
        Returns:
            List of graph-expanded QueryResults
        """
        if not self.graph_index:
            return []
            
        expanded_docs: dict[str, dict[str, Any]] = {}  # guid -> {score, via, ...}
        
        # For each semantic result, traverse the graph
        for result in semantic_results[:5]:  # Limit traversal to top 5
            try:
                # Get instruments this document affects
                instruments = self._get_document_instruments(result.document_guid)
                
                for inst_ticker in instruments:
                    # Find other documents affecting the same instrument
                    related = self._get_documents_affecting_instrument(
                        ticker=inst_ticker,
                        group_guids=group_guids,
                        limit=5,
                    )
                    for doc_guid, doc_data in related.items():
                        if doc_guid not in exclude_guids and doc_guid not in expanded_docs:
                            doc_data["via"] = f"instrument:{inst_ticker}"
                            doc_data["via_doc"] = result.document_guid
                            expanded_docs[doc_guid] = doc_data
                    
                    # Find documents affecting peer instruments
                    peer_tickers = self._get_peer_instruments(inst_ticker)
                    for peer_ticker in peer_tickers[:3]:  # Limit peer traversal
                        peer_related = self._get_documents_affecting_instrument(
                            ticker=peer_ticker,
                            group_guids=group_guids,
                            limit=3,
                        )
                        for doc_guid, doc_data in peer_related.items():
                            if doc_guid not in exclude_guids and doc_guid not in expanded_docs:
                                doc_data["via"] = f"peer:{inst_ticker}→{peer_ticker}"
                                doc_data["via_doc"] = result.document_guid
                                expanded_docs[doc_guid] = doc_data
                                
            except Exception:
                continue  # nosec B112 - Don't fail on graph traversal errors
                
        # Convert to QueryResults with graph-based scoring
        graph_results: list[QueryResult] = []
        now = datetime.now()
        
        for doc_guid, doc_data in list(expanded_docs.items())[:max_expansion]:
            # Calculate scores for graph-discovered documents
            trust_level = self._get_trust_level(doc_data.get("source_guid", ""))
            recency_score = self._calculate_recency_score(doc_data, now)
            
            # Graph-discovered docs get the graph_boost instead of semantic score
            # Their "semantic" contribution is 0, but they get full graph_boost
            combined_score = (
                weights.trust * trust_level
                + weights.recency * recency_score
                + weights.graph_boost * 1.0  # Full graph boost for discovered docs
            )
            
            graph_results.append(QueryResult(
                document_guid=doc_guid,
                title=doc_data.get("title", ""),
                content_snippet=doc_data.get("content", "")[:500],
                score=combined_score,
                similarity_score=0.0,  # Not from semantic search
                trust_score=trust_level,
                recency_score=recency_score,
                graph_score=weights.graph_boost,
                source_guid=doc_data.get("source_guid", ""),
                source_name=doc_data.get("source_name", ""),
                language=doc_data.get("language", ""),
                created_at=self._parse_datetime(doc_data.get("created_at")),
                metadata={"discovered_via": doc_data.get("via", "graph")},
                graph_context={"via": doc_data.get("via"), "via_doc": doc_data.get("via_doc")},
                impact_score=doc_data.get("impact_score"),
                impact_tier=doc_data.get("impact_tier"),
                event_type=doc_data.get("event_type"),
                discovered_via="graph",
            ))
            
        return graph_results

    def _get_document_instruments(self, document_guid: str) -> list[str]:
        """Get instruments affected by a document (via AFFECTS relationship)"""
        if not self.graph_index:
            return []
            
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (d:Document {guid: $guid})-[:AFFECTS]->(i:Instrument)
                    RETURN i.ticker AS ticker
                    """,
                    guid=document_guid,
                )
                return [record["ticker"] for record in result if record["ticker"]]
        except Exception:
            return []

    def _get_peer_instruments(self, ticker: str) -> list[str]:
        """Get peer instruments (via sector/company relationships)
        
        Note: PEER_OF relationships don't exist in current schema.
        Returns instruments in same sector as a proxy for peers.
        Traverses: Instrument -> Company -> Sector <- Company <- Instrument
        """
        if not self.graph_index:
            return []
            
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (i1:Instrument {ticker: $ticker})-[:ISSUED_BY]->(c1:Company)-[:BELONGS_TO]->(s:Sector)
                    MATCH (i2:Instrument)-[:ISSUED_BY]->(c2:Company)-[:BELONGS_TO]->(s)
                    WHERE i1.ticker <> i2.ticker
                    RETURN DISTINCT i2.ticker AS ticker
                    LIMIT 5
                    """,
                    ticker=ticker,
                )
                return [record["ticker"] for record in result if record["ticker"]]
        except Exception:
            return []

    def _get_documents_affecting_instrument(
        self,
        ticker: str,
        group_guids: list[str],
        limit: int = 10,
    ) -> dict[str, dict[str, Any]]:
        """Get documents that affect an instrument, respecting group permissions"""
        if not self.graph_index:
            return {}
            
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (d:Document)-[:AFFECTS]->(i:Instrument {ticker: $ticker})
                    MATCH (d)-[:IN_GROUP]->(g:Group)
                    WHERE g.guid IN $group_guids
                    OPTIONAL MATCH (d)-[:PRODUCED_BY]->(s:Source)
                    OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(e:EventType)
                    RETURN d.guid AS guid, d.title AS title,
                           d.created_at AS created_at, d.language AS language,
                           d.impact_score AS impact_score, d.impact_tier AS impact_tier,
                           e.code AS event_type,
                           s.guid AS source_guid, s.name AS source_name
                    ORDER BY d.created_at DESC
                    LIMIT $limit
                    """,
                    ticker=ticker,
                    group_guids=group_guids,
                    limit=limit,
                )
                return {
                    record["guid"]: dict(record)
                    for record in result
                    if record["guid"]
                }
        except Exception:
            return {}

    def _enrich_with_graph_context(
        self, results: list[QueryResult]
    ) -> list[QueryResult]:
        """Enrich results with graph context from Neo4j"""
        if not self.graph_index:
            return results

        for result in results:
            context: dict[str, Any] = {}

            # Get companies mentioned in this document
            try:
                companies = self._get_document_companies(result.document_guid)
                if companies:
                    context["companies"] = companies
            except Exception:
                pass  # nosec B110

            # Get related documents (same source or shared companies)
            try:
                related = self._get_related_documents(result.document_guid)
                if related:
                    context["related_documents"] = related[:5]  # Limit
            except Exception:
                pass  # nosec B110

            result.graph_context = context

        return results

    def _get_document_companies(self, document_guid: str) -> list[str]:
        """Get companies mentioned in a document"""
        if not self.graph_index:
            return []

        # This is a placeholder - actual implementation would query
        # for companies related to this specific document via Neo4j
        # For now, return empty list
        return []

    def _get_related_documents(self, document_guid: str) -> list[str]:
        """Get related documents from graph"""
        if not self.graph_index:
            return []

        try:
            traversal = self.graph_index.get_related_documents(
                document_guid=document_guid,
                max_depth=2,
                limit=5,
            )
            return [n.guid for n in traversal.nodes if n.label == NodeLabel.DOCUMENT]
        except Exception:
            return []

    def _filters_to_dict(self, filters: QueryFilters) -> dict[str, Any]:
        """Convert filters to dictionary for response"""
        result: dict[str, Any] = {}

        if filters.date_from:
            result["date_from"] = filters.date_from.isoformat()
        if filters.date_to:
            result["date_to"] = filters.date_to.isoformat()
        if filters.regions:
            result["regions"] = filters.regions
        if filters.sectors:
            result["sectors"] = filters.sectors
        if filters.companies:
            result["companies"] = filters.companies
        if filters.sources:
            result["sources"] = filters.sources
        if filters.languages:
            result["languages"] = filters.languages

        return result

    def __repr__(self) -> str:
        graph_info = "with graph" if self.graph_index else "no graph"
        return f"QueryService({graph_info})"


def create_query_service(
    embedding_index: EmbeddingIndex,
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    graph_index: Optional[GraphIndex] = None,
    default_weights: Optional[ScoringWeights] = None,
) -> QueryService:
    """Factory function to create a query service

    Args:
        embedding_index: ChromaDB embedding index
        document_store: Document storage
        source_registry: Source registry
        graph_index: Optional Neo4j graph index
        default_weights: Default scoring weights

    Returns:
        Configured QueryService instance
    """
    return QueryService(
        embedding_index=embedding_index,
        document_store=document_store,
        source_registry=source_registry,
        graph_index=graph_index,
        default_weights=default_weights,
    )
