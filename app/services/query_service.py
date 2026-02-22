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
import json
import math
import os
from typing import Any, Optional, TYPE_CHECKING

from app.models import count_words
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

    def with_env_overrides(self) -> "ClientNewsWeights":
        """Apply optional env overrides and normalize to sum to 1.0.

        Supported env vars:
        - GOFR_IQ_CLIENT_NEWS_WEIGHT_SEMANTIC
        - GOFR_IQ_CLIENT_NEWS_WEIGHT_GRAPH
        - GOFR_IQ_CLIENT_NEWS_WEIGHT_IMPACT
        - GOFR_IQ_CLIENT_NEWS_WEIGHT_RECENCY

        If overrides are present but do not sum to 1.0, the weights are
        normalized proportionally (fail-closed to the default on invalid input).
        """

        def _read_float(key: str) -> float | None:
            raw = os.environ.get(key)
            if raw is None:
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        semantic = _read_float("GOFR_IQ_CLIENT_NEWS_WEIGHT_SEMANTIC")
        graph = _read_float("GOFR_IQ_CLIENT_NEWS_WEIGHT_GRAPH")
        impact = _read_float("GOFR_IQ_CLIENT_NEWS_WEIGHT_IMPACT")
        recency = _read_float("GOFR_IQ_CLIENT_NEWS_WEIGHT_RECENCY")

        if semantic is None and graph is None and impact is None and recency is None:
            return self

        proposed = ClientNewsWeights(
            semantic=self.semantic if semantic is None else semantic,
            graph=self.graph if graph is None else graph,
            impact=self.impact if impact is None else impact,
            recency=self.recency if recency is None else recency,
        )

        total = proposed.semantic + proposed.graph + proposed.impact + proposed.recency
        if total <= 0.0:
            logger.warning(
                "Invalid client news weight overrides (sum<=0); ignoring",
                total=total,
            )
            return self

        normalized = ClientNewsWeights(
            semantic=proposed.semantic / total,
            graph=proposed.graph / total,
            impact=proposed.impact / total,
            recency=proposed.recency / total,
        )
        logger.info(
            "Applied client news weight overrides",
            semantic=normalized.semantic,
            graph=normalized.graph,
            impact=normalized.impact,
            recency=normalized.recency,
        )
        return normalized

    @classmethod
    def for_client_type(cls, client_type: str | None) -> "ClientNewsWeights":
        if client_type in {"LONG_ONLY", "PENSION"}:
            return cls(semantic=0.30, graph=0.30, impact=0.20, recency=0.20).with_env_overrides()
        return cls().with_env_overrides()


@dataclass(frozen=True)
class ScoringConfig:
    """Dynamic scoring config derived from opportunity_bias (lambda)."""

    opportunity_bias: float
    direct_holding_base: float
    watchlist_base: float
    thematic_base: float
    vector_base: float
    competitor_base: float
    supplier_base: float
    peer_base: float
    vector_similarity_threshold: float = 0.5
    vector_activation_threshold: float = 0.5
    recency_half_life_minutes: float = 60.0

    @staticmethod
    def _env_float_clamped(key: str, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
        raw = os.environ.get(key)
        if raw is None:
            return default
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return default
        if val < lo:
            return lo
        if val > hi:
            return hi
        return val

    @classmethod
    def from_opportunity_bias(cls, opportunity_bias: float) -> "ScoringConfig":
        lam = float(opportunity_bias)
        if lam < 0.0:
            lam = 0.0
        if lam > 1.0:
            lam = 1.0

        vector_activation_threshold = cls._env_float_clamped(
            "GOFR_IQ_VECTOR_ACTIVATION_THRESHOLD",
            default=cls.vector_activation_threshold,
        )
        vector_similarity_threshold = cls._env_float_clamped(
            "GOFR_IQ_VECTOR_SIMILARITY_THRESHOLD",
            default=cls.vector_similarity_threshold,
        )

        return cls(
            opportunity_bias=lam,
            direct_holding_base=1.0 - (0.4 * lam),
            watchlist_base=0.80,
            thematic_base=0.5 + (0.5 * lam),
            vector_base=0.4 + (0.4 * lam),
            # Lateral relevance depends on the intended "mode":
            # - defense (lam=0): supplier/ops risk is most relevant
            # - offense (lam=1): peer/competitor relative-value is more relevant
            competitor_base=0.4 + (0.3 * lam),
            supplier_base=0.6 - (0.2 * lam),
            peer_base=0.4 + (0.2 * lam),
            vector_activation_threshold=vector_activation_threshold,
            vector_similarity_threshold=vector_similarity_threshold,
            # Recency should decay slower as we move toward opportunity bias.
            recency_half_life_minutes=60.0 + (120.0 * lam),
        )


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


# =============================================================================
# Avatar Feed Types (Two-Channel Model)
# =============================================================================


@dataclass
class AvatarFeedItem:
    """A single item in the client avatar feed.

    Attributes:
        document_guid: Document GUID
        title: Document title
        created_at: Document creation timestamp (ISO string)
        impact_score: Impact score (0-100)
        impact_tier: Impact tier (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
        affected_instruments: List of ticker symbols affected
        themes: List of document themes
        relevance_score: Computed relevance score for this client
        channel: Which feed channel this item belongs to (MAINTENANCE or OPPORTUNITY)
        reason: Human-readable explanation of why this item is relevant
    """

    document_guid: str
    title: str
    created_at: Optional[str]
    impact_score: Optional[float]
    impact_tier: Optional[str]
    affected_instruments: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    channel: str = "MAINTENANCE"
    reason: str = ""


@dataclass
class AvatarFeed:
    """Two-channel client avatar feed.

    The maintenance channel contains news about the client's existing positions
    (holdings + watchlist). The opportunity channel contains news matching the
    client's mandate themes but NOT overlapping with existing positions.

    Attributes:
        client_guid: Client GUID this feed was generated for
        maintenance: News about existing positions (holdings, watchlist)
        opportunity: New ideas matching mandate themes (excludes existing positions)
        combined: Merged and ranked list of all items
    """

    client_guid: str
    maintenance: list[AvatarFeedItem] = field(default_factory=list)
    opportunity: list[AvatarFeedItem] = field(default_factory=list)
    combined: list[AvatarFeedItem] = field(default_factory=list)


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
        opportunity_bias: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Get top news for a client using graph/ephemeral data only.

        This method is deterministic and does not perform any LLM calls.
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
        scoring = ScoringConfig.from_opportunity_bias(opportunity_bias)

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
                    "themes": doc.get("themes", []) if isinstance(doc.get("themes"), list) else [],
                    "reasons": set(),
                    "graph_score": 0.0,
                    "vector_score": 0.0,
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
            add_graph_candidates(direct_docs, "DIRECT_HOLDING", scoring.direct_holding_base, holding_weights)

        if watchlist_tickers:
            watch_docs = self._get_documents_for_tickers(
                tickers=watchlist_tickers,
                group_guids=group_guids,
                min_impact_score=resolved_min_impact,
                impact_tiers=resolved_impact_tiers,
            )
            add_graph_candidates(watch_docs, "WATCHLIST", scoring.watchlist_base)

        if include_lateral_graph and holding_tickers:
            lateral = self._expand_lateral_tickers(holding_tickers)

            if lateral.get("competitors"):
                comp_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("competitors", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(comp_docs, "COMPETITOR", scoring.competitor_base)

            if lateral.get("suppliers"):
                supply_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("suppliers", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(supply_docs, "SUPPLY_CHAIN", scoring.supplier_base)

            if lateral.get("peers"):
                peer_docs = self._get_documents_for_tickers(
                    tickers=lateral.get("peers", []),
                    group_guids=group_guids,
                    min_impact_score=resolved_min_impact,
                    impact_tiers=resolved_impact_tiers,
                )
                add_graph_candidates(peer_docs, "PEER", scoring.peer_base)

        # Thematic candidates: mandate_themes tags on documents
        mandate_themes = profile.get("mandate_themes") or []
        if not mandate_themes:
            mandate_themes = self._get_client_mandate_themes(client_guid)

        if mandate_themes:
            thematic_docs = self._get_documents_by_themes(
                themes=[t for t in mandate_themes if isinstance(t, str) and t],
                group_guids=group_guids,
                exclude_tickers=[],
                min_impact_score=resolved_min_impact,
                impact_tiers=resolved_impact_tiers,
                limit=50,
            )
            add_graph_candidates(thematic_docs, "THEMATIC", scoring.thematic_base)

        # Vector candidates: mandate embedding similarity (semantic "unknown knowns")
        if self.embedding_index and scoring.opportunity_bias > scoring.vector_activation_threshold:
            mandate_embedding = profile.get("mandate_embedding") or []
            mandate_text = profile.get("mandate_text")

            vector_hits: list[SimilarityResult] = []
            try:
                if isinstance(mandate_embedding, list) and mandate_embedding:
                    vector_hits = self.embedding_index.search_by_embedding(
                        query_embedding=mandate_embedding,
                        n_results=25,
                        group_guids=group_guids,
                        include_content=False,
                    )
                elif isinstance(mandate_text, str) and mandate_text.strip():
                    # Fallback: derive the query embedding from mandate_text at query time.
                    # This unblocks VECTOR even if client profiles have not been backfilled
                    # with a stored mandate_embedding in Neo4j.
                    vector_hits = self.embedding_index.search(
                        query=mandate_text.strip(),
                        n_results=25,
                        group_guids=group_guids,
                        include_content=False,
                    )
            except Exception:
                vector_hits = []

                best_sim: dict[str, float] = {}
                for hit in vector_hits:
                    if not hit.document_guid:
                        continue
                    if hit.score < scoring.vector_similarity_threshold:
                        continue
                    best_sim[hit.document_guid] = max(best_sim.get(hit.document_guid, 0.0), float(hit.score))

                if best_sim:
                    summaries = self._get_documents_by_guids(list(best_sim.keys()), group_guids)
                    for doc in summaries:
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
                            "themes": doc.get("themes", []) if isinstance(doc.get("themes"), list) else [],
                            "reasons": set(),
                            "graph_score": 0.0,
                            "vector_score": 0.0,
                        })
                        entry["reasons"].add("VECTOR")
                        sim = best_sim.get(guid, 0.0)
                        entry["vector_score"] = max(entry.get("vector_score", 0.0), min(1.0, scoring.vector_base * sim))

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
            recency = self._calculate_breaking_recency_score(
                created_at,
                now,
                half_life_minutes=scoring.recency_half_life_minutes,
            )

            graph_score = float(candidate.get("graph_score", 0.0) or 0.0)
            vector_score = float(candidate.get("vector_score", 0.0) or 0.0)

            reasons_set = candidate.get("reasons", set())
            distinct_paths = len(reasons_set) if isinstance(reasons_set, set) else 1
            influence_boost = min(0.3, 0.1 * max(0, distinct_paths - 1))

            pos_boost = 0.0
            if holdings:
                ranked = sorted(
                    [h for h in holdings if h.get("ticker")],
                    key=lambda x: float(x.get("weight") or 0.0),
                    reverse=True,
                )
                ticker_to_rank = {h["ticker"]: idx for idx, h in enumerate(ranked)}
                n = max(1, len(ranked))
                for t in candidate.get("affected_instruments", []) or []:
                    if t in ticker_to_rank:
                        rank = ticker_to_rank[t]
                        rank_percentile = 1.0 if n == 1 else 1.0 - (rank / (n - 1))
                        pos_boost = max(
                            pos_boost,
                            0.3 * (math.log(1 + rank_percentile) / math.log(2)),
                        )

            # Core scoring: graph and vector contribute independently.
            # This ensures weights.semantic is an actual knob (BUG-1) and avoids
            # max() erasing convergent evidence (MODEL-2).
            base_score = (
                weights.graph * graph_score
                + weights.semantic * vector_score
                + weights.impact * impact_norm
                + weights.recency * recency
            )

            # Boosts are explicitly capped to keep scores bounded.
            final_score = base_score + influence_boost + min(0.3, pos_boost)

            reasons = sorted(candidate.get("reasons", set()))
            # Build a deterministic baseline explanation first.
            # If LLM is enabled, we'll generate LLM "why" only for the final top-N
            # results (batched) after ranking to avoid O(candidates) chat calls.
            why_base = self._build_why_it_matters(
                title=candidate.get("title"),
                reasons=reasons,
                impact_score=impact_score,
                tickers=candidate.get("affected_instruments", []),
                llm_service=None,
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
                "why_it_matters_base": why_base,
            })

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Dedupe by normalized title to avoid repeated near-identical items
        # (common in simulation runs) crowding out other relevant stories.
        deduped: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for item in scored:
            title = item.get("title")
            norm = title.strip().lower() if isinstance(title, str) else ""
            if norm and norm in seen_titles:
                continue
            if norm:
                seen_titles.add(norm)
            deduped.append(item)

        return deduped[:limit]

    def _calculate_breaking_recency_score(
        self,
        created_at: datetime | None,
        now: datetime,
        half_life_minutes: float = 60.0,
    ) -> float:
        """Exponential recency decay with minute-scale half-life.

        $S_{recency} = e^{-ln(2) * age_mins / t_{1/2}}$
        """
        if not created_at:
            return 0.5
        if half_life_minutes <= 0:
            return 0.0

        # Treat naive datetimes as UTC-like; QueryService already uses utcnow() in this path.
        age_seconds = max(0.0, (now - created_at).total_seconds())
        age_minutes = age_seconds / 60.0
        return float(math.exp(-math.log(2) * (age_minutes / half_life_minutes)))

    def why_it_matters_to_client(
        self,
        client_guid: str,
        document_guid: str,
        group_guids: list[str],
        llm_service: "LLMService",
    ) -> dict[str, str]:
        """Generate LLM augmentation for a specific (client, document) pair.

        Returns two short strings:
        - why_it_matters: <= 30 words, client-specific
        - story_summary: <= 30 words, story-only
        """

        if not self.graph_index:
            raise RuntimeError("why_it_matters_to_client requires graph index")

        profile = self._get_client_profile_context(client_guid, group_guids)
        if not profile:
            raise RuntimeError("Client not found or not permitted")

        holdings = self._get_client_holdings(client_guid)
        watchlist = self._get_client_watchlist(client_guid)

        holding_tickers = [h.get("ticker") for h in holdings if h.get("ticker")]
        holding_weights = {h.get("ticker"): float(h.get("weight") or 0.0) for h in holdings if h.get("ticker")}
        watchlist_tickers = [t for t in watchlist if t]

        doc = self.document_store.load_with_access_check(
            guid=document_guid,
            permitted_groups=group_guids,
        )

        # Keep prompt bounded: include a truncated excerpt of content.
        content_words = doc.content.split()
        excerpt_words = content_words[:500]
        excerpt = " ".join(excerpt_words)

        client_context = {
            "client_guid": client_guid,
            "client_type": profile.get("client_type"),
            "mandate_type": profile.get("mandate_type"),
            "horizon": profile.get("horizon"),
            "esg_constrained": bool(profile.get("esg_constrained")),
            "impact_threshold": profile.get("impact_threshold"),
            "benchmark": profile.get("benchmark"),
            "restrictions": profile.get("restrictions"),
            "holdings": [
                {"ticker": t, "weight": holding_weights.get(t, 0.0)}
                for t in holding_tickers[:25]
            ],
            "watchlist": watchlist_tickers[:25],
        }

        document_context = {
            "document_guid": doc.guid,
            "title": doc.title,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "impact_score": doc.metadata.get("impact_score"),
            "impact_tier": doc.metadata.get("impact_tier"),
            "affected_instruments": doc.metadata.get("affected_instruments") or doc.metadata.get("companies"),
            "content_excerpt": excerpt,
        }

        try:
            from app.services.llm_service import ChatMessage

            prompt = (
                "You are assisting a sales trader briefing a client.\n"
                "Use ONLY the provided client context and story excerpt. Do NOT invent facts.\n\n"
                "Return ONLY valid JSON with exactly these keys:\n"
                "{\"why_it_matters\": \"...\", \"story_summary\": \"...\"}\n\n"
                "Constraints:\n"
                "- why_it_matters: max 30 words, must be specific to the client\n"
                "- story_summary: max 30 words, story-only summary\n\n"
                f"Client: {json.dumps(client_context, ensure_ascii=True)}\n"
                f"Story: {json.dumps(document_context, ensure_ascii=True)}\n"
            )

            result = llm_service.chat_completion(
                messages=[ChatMessage(role="user", content=prompt)],
                json_mode=True,
                temperature=0.2,
                max_tokens=250,
            )

            payload = result.as_json()
            if not isinstance(payload, dict):
                raise ValueError("LLM returned non-object JSON")

            why = payload.get("why_it_matters")
            summary = payload.get("story_summary")
            if not isinstance(why, str) or not isinstance(summary, str):
                raise ValueError("LLM JSON missing required string fields")

        except Exception as exc:
            raise RuntimeError(f"LLM augmentation failed: {exc}")

        def _truncate_to_words(text: str, max_words: int) -> str:
            words = text.split()
            if len(words) <= max_words:
                return text.strip()
            return " ".join(words[:max_words]).strip()

        why = _truncate_to_words(why, 30)
        summary = _truncate_to_words(summary, 30)

        # Defensive validation (after truncation)
        if count_words(why) > 30:
            why = _truncate_to_words(why, 30)
        if count_words(summary) > 30:
            summary = _truncate_to_words(summary, 30)

        return {
            "why_it_matters": why,
            "story_summary": summary,
        }

    # =========================================================================
    # AVATAR FEED (Two-Channel Model)
    # =========================================================================

    def get_client_avatar_feed(
        self,
        client_guid: str,
        group_guids: list[str],
        limit: int = 10,
        time_window_hours: int = 24,
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
    ) -> AvatarFeed:
        """Get client news feed using the two-channel avatar model.

        Channel 1 (MAINTENANCE): News affecting holdings/watchlist.
        Channel 2 (OPPORTUNITY): Mandate-themed news NOT affecting existing positions.

        This method is deterministic and does not use LLM at query time.
        Themes and mandate_themes are precomputed at ingest/profile-update time.

        Args:
            client_guid: Client GUID
            group_guids: Permitted group GUIDs (access control)
            limit: Maximum total items (split between channels)
            time_window_hours: How far back to look
            min_impact_score: Minimum impact score filter
            impact_tiers: Optional impact tier filter.
                If omitted, MAINTENANCE does not filter by tier (holdings/watchlist).
                OPPORTUNITY defaults to high-signal tiers (PLATINUM, GOLD, SILVER, BRONZE, STANDARD).

        Returns:
            AvatarFeed with maintenance, opportunity, and combined lists
        """
        if not self.graph_index:
            logger.warning("Avatar feed requested without graph index")
            return AvatarFeed(client_guid=client_guid)

        if limit <= 0:
            return AvatarFeed(client_guid=client_guid)

        # Load client context
        profile = self._get_client_profile_context(client_guid, group_guids)
        if not profile:
            return AvatarFeed(client_guid=client_guid)

        holdings = self._get_client_holdings(client_guid)
        watchlist = self._get_client_watchlist(client_guid)

        holding_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        watchlist_tickers = [t for t in watchlist if t]
        all_position_tickers = list(set(holding_tickers + watchlist_tickers))

        # DEBUG: Log avatar feed inputs
        logger.info(f"[AVATAR_DEBUG] client_guid={client_guid} holdings={holding_tickers} watchlist={watchlist_tickers} all_tickers={all_position_tickers} group_guids={group_guids}")

        # Add benchmark to watchlist if present
        benchmark = profile.get("benchmark")
        if benchmark and benchmark not in all_position_tickers:
            watchlist_tickers.append(benchmark)
            all_position_tickers.append(benchmark)

        resolved_min_impact = min_impact_score
        if resolved_min_impact is None:
            resolved_min_impact = profile.get("impact_threshold")

        maintenance_impact_tiers = impact_tiers
        opportunity_impact_tiers = impact_tiers or [
            "PLATINUM",
            "GOLD",
            "SILVER",
            "BRONZE",
            "STANDARD",
        ]

        now = datetime.utcnow()
        time_cutoff = now - timedelta(hours=time_window_hours)

        # Weights for position size
        holding_weights = {h["ticker"]: h.get("weight", 0.0) for h in holdings if h.get("ticker")}

        # ─────────────────────────────────────────────────────────────────────
        # CHANNEL 1: MAINTENANCE (news about what the client owns)
        # ─────────────────────────────────────────────────────────────────────
        maintenance_items: list[AvatarFeedItem] = []

        if all_position_tickers:
            position_docs = self._get_documents_for_tickers(
                tickers=all_position_tickers,
                group_guids=group_guids,
                min_impact_score=resolved_min_impact,
                impact_tiers=maintenance_impact_tiers,
                limit=limit * 3,  # Fetch extra for filtering
            )
            # DEBUG: Log query results
            logger.info(f"[AVATAR_DEBUG] position_docs count={len(position_docs)} docs={[d.get('title','?')[:30] for d in position_docs]}")

            for doc in position_docs:
                if not self._within_time_window(doc.get("created_at"), time_cutoff):
                    continue

                affected = doc.get("affected_instruments", [])
                matched_holdings = [t for t in affected if t in holding_tickers]
                matched_watchlist = [t for t in affected if t in watchlist_tickers and t not in holding_tickers]

                # Build reason
                if matched_holdings:
                    reason = f"Affects your {', '.join(matched_holdings[:3])} position"
                elif matched_watchlist:
                    reason = f"Affects your watchlist: {', '.join(matched_watchlist[:3])}"
                else:
                    reason = "Affects your positions"

                # Score: impact × recency × position_weight
                impact_norm = self._normalize_impact_score(doc.get("impact_score"))
                created_at = self._parse_datetime(doc.get("created_at"))
                recency = self._calculate_recency_score({"created_at": created_at}, now)
                position_weight = max(
                    (holding_weights.get(t, 0.0) for t in affected),
                    default=0.0,
                )
                # Minimum weight of 0.5 for watchlist items
                position_weight = max(position_weight, 0.5) if matched_watchlist and not matched_holdings else max(position_weight, 1.0)

                score = impact_norm * recency * position_weight

                maintenance_items.append(AvatarFeedItem(
                    document_guid=doc.get("document_guid", ""),
                    title=doc.get("title", ""),
                    created_at=doc.get("created_at"),
                    impact_score=doc.get("impact_score"),
                    impact_tier=doc.get("impact_tier"),
                    affected_instruments=affected,
                    themes=doc.get("themes", []) or [],
                    relevance_score=score,
                    channel="MAINTENANCE",
                    reason=reason,
                ))

        # ─────────────────────────────────────────────────────────────────────
        # CHANNEL 2: OPPORTUNITY (mandate-themed news, excludes positions)
        # ─────────────────────────────────────────────────────────────────────
        opportunity_items: list[AvatarFeedItem] = []

        # Get mandate_themes from profile (stored on ClientProfile node)
        mandate_themes = self._get_client_mandate_themes(client_guid)

        if mandate_themes:
            theme_docs = self._get_documents_by_themes(
                themes=mandate_themes,
                group_guids=group_guids,
                exclude_tickers=all_position_tickers,
                min_impact_score=resolved_min_impact,
                impact_tiers=opportunity_impact_tiers,
                limit=limit * 3,
            )

            for doc in theme_docs:
                if not self._within_time_window(doc.get("created_at"), time_cutoff):
                    continue

                doc_themes = doc.get("themes", []) or []
                matched_themes = [t for t in doc_themes if t in mandate_themes]

                if not matched_themes:
                    continue

                reason = f"Matches your {', '.join(matched_themes[:3])} focus"

                # Score: theme_fit × impact × recency
                impact_norm = self._normalize_impact_score(doc.get("impact_score"))
                created_at = self._parse_datetime(doc.get("created_at"))
                recency = self._calculate_recency_score({"created_at": created_at}, now)
                theme_fit = len(matched_themes) / len(mandate_themes) if mandate_themes else 0.0

                score = theme_fit * impact_norm * recency

                opportunity_items.append(AvatarFeedItem(
                    document_guid=doc.get("document_guid", ""),
                    title=doc.get("title", ""),
                    created_at=doc.get("created_at"),
                    impact_score=doc.get("impact_score"),
                    impact_tier=doc.get("impact_tier"),
                    affected_instruments=doc.get("affected_instruments", []) or [],
                    themes=doc_themes,
                    relevance_score=score,
                    channel="OPPORTUNITY",
                    reason=reason,
                ))

        # ─────────────────────────────────────────────────────────────────────
        # MERGE & RANK
        # ─────────────────────────────────────────────────────────────────────
        # Dedupe by document_guid (maintenance wins if in both)
        maintenance_guids = {item.document_guid for item in maintenance_items}
        opportunity_items = [item for item in opportunity_items if item.document_guid not in maintenance_guids]

        # Sort each channel by score
        maintenance_items.sort(key=lambda x: x.relevance_score, reverse=True)
        opportunity_items.sort(key=lambda x: x.relevance_score, reverse=True)

        # Combined: interleave, then sort by score
        all_items = maintenance_items + opportunity_items
        all_items.sort(key=lambda x: x.relevance_score, reverse=True)

        # Limit results
        half_limit = limit // 2
        return AvatarFeed(
            client_guid=client_guid,
            maintenance=maintenance_items[:half_limit],
            opportunity=opportunity_items[:half_limit],
            combined=all_items[:limit],
        )

    def _get_client_mandate_themes(self, client_guid: str) -> list[str]:
        """Get mandate_themes from the client's profile.

        Returns an empty list if no profile or no mandate_themes set.
        """
        if not self.graph_index:
            return []
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PROFILE]->(cp:ClientProfile)
                    RETURN cp.mandate_themes AS mandate_themes
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return []
                themes = record.get("mandate_themes")
                if themes is None:
                    return []
                # Handle JSON string or list
                if isinstance(themes, str):
                    try:
                        themes = json.loads(themes)
                    except json.JSONDecodeError:
                        return []
                return [t for t in themes if isinstance(t, str) and t]
        except Exception:
            return []

    def _build_client_query_text(
        self,
        profile: dict[str, Any],
        holdings: list[str],
        watchlist: list[str],
        llm_service: "LLMService | None" = None,
    ) -> str:
        """Build semantic query text from client profile context.
        
        Incorporates:
        - Client type, mandate_type, horizon, ESG flag
        - mandate_text (free-form investment description)
        - impact_themes from restrictions (for relevance boosting)
        - Portfolio and watchlist tickers
        """
        base = (
            f"Client type: {profile.get('client_type', 'UNKNOWN')}. "
            f"Mandate: {profile.get('mandate_type', 'unspecified')}. "
            f"Horizon: {profile.get('horizon', 'unspecified')}. "
            f"ESG constrained: {profile.get('esg_constrained', False)}. "
        )
        
        # Add mandate_text if present (contributes to semantic matching)
        mandate_text = profile.get("mandate_text")
        if mandate_text:
            # Truncate for query efficiency (first 500 chars)
            truncated = mandate_text[:500].strip()
            base += f"Investment mandate: {truncated}. "
        
        # Add impact themes from restrictions (for relevance boosting)
        restrictions = profile.get("restrictions") or {}
        impact_sustainability = restrictions.get("impact_sustainability") or {}
        impact_themes = impact_sustainability.get("impact_themes") or []
        if impact_themes:
            themes_str = ", ".join(impact_themes[:10])  # Limit to 10 themes
            base += f"Impact themes: {themes_str}. "
        
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
        """Fetch core client profile info with group permission check.
        
        Returns profile including mandate_text and parsed restrictions for
        semantic query building and exclusion filtering.
        """
        if not self.graph_index:
            return None
        try:
            from app.models.client_profile import ClientProfile

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
                           cp.mandate_text AS mandate_text,
                              cp.mandate_themes AS mandate_themes,
                              cp.mandate_embedding AS mandate_embedding,
                           cp.horizon AS horizon,
                           cp.esg_constrained AS esg_constrained,
                           cp.restrictions AS restrictions_json,
                           b.ticker AS benchmark
                    """,
                    client_guid=client_guid,
                    group_guids=group_guids,
                )
                record = result.single()
                if not record:
                    return None
                profile_dict = dict(record)

                # Validate + normalize via Pydantic without changing the downstream
                # dict contract used by get_top_client_news / avatar feeds.
                profile = ClientProfile.model_validate(profile_dict)
                return profile.model_dump()
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
        """Get client exclusions from both graph relationships and restrictions.
        
        Combines:
        - Graph EXCLUDES relationships (Company, Sector nodes)
        - restrictions.ethical_sector.excluded_industries from profile JSON
        
        Returns dict with 'companies' and 'sectors' lists.
        """
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
                           collect(DISTINCT exSector.name) AS sectors,
                           cp.restrictions AS restrictions_json
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return {"companies": [], "sectors": []}
                
                companies = [c for c in record["companies"] if c]
                sectors = [s for s in record["sectors"] if s]
                
                # Add excluded_industries from restrictions JSON
                restrictions_json = record.get("restrictions_json")
                if restrictions_json:
                    try:
                        restrictions = json.loads(restrictions_json)
                        ethical_sector = restrictions.get("ethical_sector") or {}
                        excluded_industries = ethical_sector.get("excluded_industries") or []
                        # Add to sectors list (industries map to sectors)
                        for industry in excluded_industries:
                            if industry and industry not in sectors:
                                sectors.append(industry)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                return {
                    "companies": companies,
                    "sectors": sectors,
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
        ORDER BY created_at DESC
        LIMIT $limit
        """
        try:
            logger.info(f"[AVATAR_DEBUG] Query: tickers={tickers}, group_guids={group_guids}, impact_tiers={impact_tiers}, min_impact={min_impact_score}")
            with self.graph_index._get_session() as session:
                result = session.run(
                    query,
                    tickers=tickers,
                    group_guids=group_guids,
                    min_impact_score=min_impact_score,
                    impact_tiers=impact_tiers,
                    limit=limit,
                )
                docs = [dict(record) for record in result]
                logger.info(f"[AVATAR_DEBUG] _get_documents_for_tickers returned {len(docs)} docs for tickers={tickers}")
                return docs
        except Exception as e:
            logger.error(f"[AVATAR_DEBUG] _get_documents_for_tickers EXCEPTION: {e}")
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
                    OPTIONAL MATCH (c)<-[:SUPPLIES_TO|SUPPLIER_OF|PARTNER_OF]-(sc:Company)-[:ISSUED_BY]->(si:Instrument)
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

    def _get_documents_by_themes(
        self,
        themes: list[str],
        group_guids: list[str],
        exclude_tickers: list[str],
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get documents matching themes but NOT affecting excluded tickers.

        Used for the OPPORTUNITY channel: find mandate-relevant news that is
        novel (doesn't overlap with existing holdings/watchlist).

        Args:
            themes: List of theme strings to match (controlled vocabulary)
            group_guids: Permitted group GUIDs for access control
            exclude_tickers: Tickers to exclude (client's positions)
            min_impact_score: Minimum impact score filter
            impact_tiers: Impact tier filter
            limit: Maximum results

        Returns:
            List of document dicts with themes and affected_instruments
        """
        if not self.graph_index or not themes:
            return []

        query = """
        MATCH (d:Document)-[:IN_GROUP]->(g:Group)
        WHERE g.guid IN $group_guids
          AND d.themes IS NOT NULL
          AND any(t IN d.themes WHERE t IN $themes)
        """

        if min_impact_score is not None:
            query += "\n  AND d.impact_score >= $min_impact_score"
        if impact_tiers:
            query += "\n  AND d.impact_tier IN $impact_tiers"

        # Get affected instruments to filter out overlap with existing positions
        query += """
        OPTIONAL MATCH (d)-[:AFFECTS]->(i:Instrument)
        WITH d, collect(DISTINCT i.ticker) AS tickers
        """

        # Exclude documents that affect any of the client's existing tickers
        if exclude_tickers:
            query += """
        WHERE NONE(t IN tickers WHERE t IN $exclude_tickers)
        """

        query += """
        RETURN d.guid AS document_guid,
               d.title AS title,
               d.created_at AS created_at,
               d.impact_score AS impact_score,
               d.impact_tier AS impact_tier,
               d.themes AS themes,
               tickers AS affected_instruments
        ORDER BY created_at DESC
        LIMIT $limit
        """

        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    query,
                    themes=themes,
                    group_guids=group_guids,
                    exclude_tickers=exclude_tickers or [],
                    min_impact_score=min_impact_score,
                    impact_tiers=impact_tiers,
                    limit=limit,
                )
                return [dict(record) for record in result]
        except Exception as e:
            logger.warning(f"Error fetching documents by themes: {e}")
            return []

    def _get_documents_by_guids(
        self,
        document_guids: list[str],
        group_guids: list[str],
    ) -> list[dict[str, Any]]:
        """Hydrate basic document fields for a set of guids with group access check."""
        if not self.graph_index or not document_guids:
            return []
        try:
            with self.graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (d:Document)
                    WHERE d.guid IN $guids
                    MATCH (d)-[:IN_GROUP]->(g:Group)
                    WHERE g.guid IN $group_guids
                    OPTIONAL MATCH (d)-[:AFFECTS]->(i:Instrument)
                    OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(e:EventType)
                    RETURN d.guid AS document_guid,
                           d.title AS title,
                           d.created_at AS created_at,
                           d.impact_score AS impact_score,
                           d.impact_tier AS impact_tier,
                           d.themes AS themes,
                           e.code AS event_type,
                           collect(DISTINCT i.ticker) AS affected_instruments
                    """,
                    guids=document_guids,
                    group_guids=group_guids,
                )
                return [dict(r) for r in result]
        except Exception:
            return []

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
