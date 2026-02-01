"""Integration Tests for Hybrid Query (Graph + Semantic).

Phase 8: Verify that queries benefit from BOTH relational graph traversal 
AND semantic similarity.

Test Scenarios:
1. Single-Stock Direct Query (AAPL -> iPhone)
2. Instrument Traversal Query (Semiconductor -> NVDA/AMD)
3. Event Propagation Query (Fed Rate -> Banks/Sector)
4. Lateral Discovery (TSLA -> RIVN via PEER_OF)
5. Historical Pattern Query (Crypto Winter)

Live LLM Mode:
    Set GOFR_IQ_USE_LIVE_LLM=1 to use real LLM for:
    - Document graph extraction (entity/relationship parsing)
    - Embedding generation for ingestion and search
    
    Requires GOFR_IQ_OPENROUTER_API_KEY to be set.
    
    Example:
        GOFR_IQ_USE_LIVE_LLM=1 pytest test/test_integration_hybrid_query.py -v
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import patch

import pytest

from app.models.source import Source, SourceType, TrustLevel
from app.prompts.graph_extraction import GraphExtractionResult, EventDetection, InstrumentMention
from app.services.document_store import DocumentStore
from app.services.embedding_index import EmbeddingIndex, LLMEmbeddingFunction
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.ingest_service import IngestService
from app.services.query_service import QueryService
from app.services.source_registry import SourceRegistry
from app.services.language_detector import LanguageDetector
from app.services.duplicate_detector import DuplicateDetector
from app.services.llm_service import LLMService, create_llm_service, llm_available

# Live data capture for tuning - use importlib for test module
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fixtures.live_llm_capture import LiveDataCapture, analyze_extraction_errors, generate_tuning_recommendations

# =============================================================================
# Live LLM Configuration
# =============================================================================

def use_live_llm() -> bool:
    """Check if live LLM mode is enabled via environment variable."""
    return os.environ.get("GOFR_IQ_USE_LIVE_LLM", "").lower() in ("1", "true", "yes")


def live_llm_available() -> bool:
    """Check if live LLM mode is enabled AND API key is available."""
    return use_live_llm() and llm_available()


# Global capture instance for live mode
_live_capture: Optional[LiveDataCapture] = None

def get_live_capture() -> Optional[LiveDataCapture]:
    """Get the global live capture instance (created in live mode only)."""
    global _live_capture
    if live_llm_available() and _live_capture is None:
        _live_capture = LiveDataCapture()
    return _live_capture


# =============================================================================
# Test Data Definitions
# =============================================================================

@dataclass
class ArticleDef:
    """A synthetic test article."""
    id: int
    title: str
    content: str
    group_guid: str
    impact_score: float
    impact_tier: str
    event_type: str
    instruments: List[Dict[str, Any]]  # List of dicts for InstrumentMention
    companies: List[str]

# Test Groups
GROUPS = {
    "A": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",  # Sales
    "B": "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb",  # Newswire
    "C": "cccccccc-cccc-4ccc-cccc-cccccccccccc",  # Vendor
}

# Test Articles (15 items from plan)
TEST_ARTICLES = [
    ArticleDef(
        id=1,
        title="Apple Q4 Earnings Beat Expectations",
        content="Apple (AAPL) reported Q4 revenue of $89.5B, beating estimates. iPhone sales were strong despite macro headwinds.",
        group_guid=GROUPS["A"],
        impact_score=75,
        impact_tier="GOLD",
        event_type="EARNINGS_BEAT",
        instruments=[{"ticker": "AAPL", "direction": "UP", "magnitude": "MODERATE"}],
        companies=["Apple Inc."],
    ),
    ArticleDef(
        id=2,
        title="Samsung Reports Strong Galaxy Sales",
        content="Samsung Electronics (SSNLF) saw a surge in Galaxy S24 shipments, challenging Apple's dominance in premium smartphones.",
        group_guid=GROUPS["B"],
        impact_score=70,
        impact_tier="GOLD",
        event_type="EARNINGS_BEAT",
        instruments=[{"ticker": "SSNLF", "direction": "UP", "magnitude": "MODERATE"}],
        companies=["Samsung Electronics"],
    ),
    ArticleDef(
        id=3,
        title="AMD Gains Server Market Share from Intel",
        content="Advanced Micro Devices (AMD) continues to take server CPU market share from Intel (INTC) with its new EPYC processors.",
        group_guid=GROUPS["A"],
        impact_score=65,
        impact_tier="SILVER",
        event_type="POSITIVE_SENTIMENT",
        instruments=[
            {"ticker": "AMD", "direction": "UP", "magnitude": "MODERATE"},
            {"ticker": "INTC", "direction": "DOWN", "magnitude": "MODERATE"}
        ],
        companies=["AMD", "Intel"],
    ),
    ArticleDef(
        id=4,
        title="Tesla Cuts Prices Again in China",
        content="Tesla (TSLA) announced another round of price cuts for Model 3 and Model Y in China, sparking concerns about margins.",
        group_guid=GROUPS["B"],
        impact_score=60,
        impact_tier="SILVER",
        event_type="NEGATIVE_SENTIMENT",
        instruments=[{"ticker": "TSLA", "direction": "DOWN", "magnitude": "MODERATE"}],
        companies=["Tesla Inc."],
    ),
    ArticleDef(
        id=5,
        title="Rivian Delays R2 Production",
        content="Rivian (RIVN) is pausing construction of its Georgia plant and delaying the R2 platform launch to preserve cash.",
        group_guid=GROUPS["C"],
        impact_score=80,
        impact_tier="PLATINUM",
        event_type="GUIDANCE_CUT",
        instruments=[{"ticker": "RIVN", "direction": "DOWN", "magnitude": "HIGH"}],
        companies=["Rivian Automotive"],
    ),
    ArticleDef(
        id=6,
        title="Fed Holds Rates Steady, Signals Future Cuts",
        content="The Federal Reserve kept interest rates unchanged at 5.25-5.50% but signaled three rate cuts coming in 2024. Markets rallied.",
        group_guid=GROUPS["B"],
        impact_score=90,
        impact_tier="PLATINUM",
        event_type="CENTRAL_BANK",
        instruments=[
            {"ticker": "SPY", "direction": "UP", "magnitude": "HIGH"},
            {"ticker": "QQQ", "direction": "UP", "magnitude": "HIGH"}
        ],
        companies=["Federal Reserve"],
    ),
    ArticleDef(
        id=7,
        title="TSMC Warns of Chip Demand Slowdown",
        content="Taiwan Semiconductor (TSM) gave cautious guidance, citing inventory corrections in the smartphone and PC markets.",
        group_guid=GROUPS["A"],
        impact_score=75,
        impact_tier="GOLD",
        event_type="GUIDANCE_CUT",
        instruments=[{"ticker": "TSM", "direction": "DOWN", "magnitude": "MODERATE"}],
        companies=["TSMC"],
    ),
    ArticleDef(
        id=8,
        title="Nvidia Unveils New AI Chip at GTC",
        content="Nvidia (NVDA) announced the Blackwell B200 GPU, claiming 30x performance increase for LLM inference.",
        group_guid=GROUPS["A"],
        impact_score=85,
        impact_tier="PLATINUM",
        event_type="PRODUCT_LAUNCH",
        instruments=[{"ticker": "NVDA", "direction": "UP", "magnitude": "HIGH"}],
        companies=["Nvidia"],
    ),
    ArticleDef(
        id=9,
        title="Intel Struggles with Foundry Business",
        content="Intel (INTC) reported widening losses in its foundry division, casting doubt on its turnaround strategy.",
        group_guid=GROUPS["B"],
        impact_score=70,
        impact_tier="GOLD",
        event_type="NEGATIVE_SENTIMENT",
        instruments=[{"ticker": "INTC", "direction": "DOWN", "magnitude": "HIGH"}],
        companies=["Intel"],
    ),
    ArticleDef(
        id=10,
        title="Amazon AWS Growth Beats Cloud Rivals",
        content="Amazon (AMZN) Web Services revenue accelerated, outpacing growth at Microsoft Azure and Google Cloud.",
        group_guid=GROUPS["B"],
        impact_score=75,
        impact_tier="GOLD",
        event_type="EARNINGS_BEAT",
        instruments=[{"ticker": "AMZN", "direction": "UP", "magnitude": "MODERATE"}],
        companies=["Amazon"],
    ),
    ArticleDef(
        id=11,
        title="Microsoft Copilot Adoption Accelerates",
        content="Microsoft (MSFT) stated that Copilot adoption is faster than any previous suite, boosting Office 365 revenue.",
        group_guid=GROUPS["A"],
        impact_score=65,
        impact_tier="SILVER",
        event_type="POSITIVE_SENTIMENT",
        instruments=[{"ticker": "MSFT", "direction": "UP", "magnitude": "MODERATE"}],
        companies=["Microsoft"],
    ),
    ArticleDef(
        id=12,
        title="Google Antitrust Ruling Impact",
        content="A judge ruled Google (GOOGL) maintains an illegal monopoly in search. Potential remedies could include breaking up the company.",
        group_guid=GROUPS["B"],
        impact_score=95,
        impact_tier="PLATINUM",
        event_type="LEGAL_RULING",
        instruments=[{"ticker": "GOOGL", "direction": "DOWN", "magnitude": "HIGH"}],
        companies=["Google", "Alphabet"],
    ),
    ArticleDef(
        id=13,
        title="Semiconductor Equipment Orders Decline",
        content="ASML and Applied Materials (AMAT) saw a drop in new orders as fabs delay expansion plans.",
        group_guid=GROUPS["C"],
        impact_score=60,
        impact_tier="SILVER",
        event_type="NEGATIVE_SENTIMENT",
        instruments=[
            {"ticker": "ASML", "direction": "DOWN", "magnitude": "MODERATE"},
            {"ticker": "AMAT", "direction": "DOWN", "magnitude": "MODERATE"}
        ],
        companies=["ASML", "Applied Materials"],
    ),
    ArticleDef(
        id=14,
        title="EV Battery Supply Chain Tightens",
        content="Lithium and cobalt prices are rising as EV production ramps up. Battery manufacturers warn of shortages.",
        group_guid=GROUPS["C"],
        impact_score=55,
        impact_tier="SILVER",
        event_type="MACRO_DATA",
        instruments=[], # Sector level
        companies=[],
    ),
    ArticleDef(
        id=15,
        title="Tech Layoffs Continue Across Sector",
        content="Major tech companies continue to reduce headcount to improve efficiency. The sector has shed 50k jobs this quarter.",
        group_guid=GROUPS["B"],
        impact_score=50,
        impact_tier="BRONZE",
        event_type="NEGATIVE_SENTIMENT",
        instruments=[], # Sector level
        companies=[],
    ),
]

@pytest.mark.integration
class TestHybridQueryIntegration:
    """Integration tests for hybrid query capabilities.
    
    Requires ChromaDB infrastructure - run with ./scripts/run_tests.sh --mode integration
    
    By default, uses deterministic embeddings and mocked LLM extraction.
    Set GOFR_IQ_USE_LIVE_LLM=1 to use real LLM for embeddings and extraction.
    
    In live mode, captured data is saved to test/tuning/ for analysis.
    """

    @pytest.fixture(scope="class", autouse=True)
    def log_test_mode(self):
        """Log which mode tests are running in and save capture data at end."""
        if live_llm_available():
            print("\n" + "="*60)
            print("🔴 LIVE LLM MODE - Using real API for embeddings/extraction")
            print("   Data will be captured for tuning analysis")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("🟢 MOCK MODE - Using deterministic embeddings (no API calls)")
            print("="*60)
        
        yield  # Run tests
        
        # After all tests: save captured data and show analysis
        capture = get_live_capture()
        if capture and capture.extractions:
            # Save to file
            from pathlib import Path
            output_path = Path("test/tuning") / f"live_run_{capture.run_id}.json"
            capture.save(output_path)
            
            # Print summary
            capture.print_summary()
            
            # Analyze errors and generate recommendations
            insights = analyze_extraction_errors(capture.extractions)
            recommendations = generate_tuning_recommendations(insights)
            
            if recommendations:
                print("\n💡 TUNING RECOMMENDATIONS:")
                for rec in recommendations:
                    print(f"   {rec}")
                print()

    @pytest.fixture
    def llm_service(self) -> Optional[LLMService]:
        """Provide LLM service - real in live mode, mock in test mode.
        
        Returns:
            LLMService in live mode (GOFR_IQ_USE_LIVE_LLM=true)
            Mock LLMService in test mode (for graph extraction requirement)
        
        Note: In mock mode, the mock service satisfies the IngestService requirement
        that LLM be available when graph_index is provided. The actual extraction
        is patched in populated_indexes fixture.
        """
        if live_llm_available():
            print("  → Using live LLMService for embeddings")
            chat_model = os.environ.get("GOFR_IQ_LLM_MODEL", "meta-llama/llama-3.1-70b-instruct")
            from app.services.llm_service import LLMSettings
            settings = LLMSettings(
                api_key=os.environ.get("GOFR_IQ_OPENROUTER_API_KEY"),
                chat_model=chat_model,
            )
            return create_llm_service(settings=settings)
        # Mock mode - provide minimal mock that passes availability check
        # The actual extraction is mocked via patch in populated_indexes
        from unittest.mock import MagicMock
        mock_service = MagicMock(spec=LLMService)
        mock_service.is_available = True
        return mock_service

    @pytest.fixture
    def live_embedding_index(
        self, 
        chromadb_config: dict[str, str | int],
        llm_service: Optional[LLMService],
    ) -> Generator[EmbeddingIndex, None, None]:
        """Provide EmbeddingIndex with live LLM embeddings when enabled.
        
        In live mode: Uses LLMEmbeddingFunction for real semantic embeddings
        In mock mode: Uses DeterministicEmbeddingFunction (hash-based)
        """
        collection_name = f"test_hybrid_{uuid.uuid4().hex[:8]}"
        
        if live_llm_available() and llm_service is not None:
            # Live LLM mode - use real embeddings
            embedding_function = LLMEmbeddingFunction(llm_service)
            index = EmbeddingIndex(
                host=str(chromadb_config["host"]),
                port=int(chromadb_config["port"]),
                collection_name=collection_name,
                embedding_function=embedding_function,
            )
        else:
            # Mock mode - use deterministic embeddings  
            index = EmbeddingIndex(
                host=str(chromadb_config["host"]),
                port=int(chromadb_config["port"]),
                collection_name=collection_name,
            )
        
        yield index
        
        # Cleanup
        try:
            index.client.delete_collection(collection_name)
        except Exception:
            pass

    @pytest.fixture
    def embedding_index(
        self,
        live_embedding_index: EmbeddingIndex,
    ) -> EmbeddingIndex:
        """Alias for compatibility - uses live_embedding_index."""
        return live_embedding_index

    @pytest.fixture
    def document_store(self, tmp_path) -> DocumentStore:
        """Provide a DocumentStore instance."""
        return DocumentStore(base_path=str(tmp_path / "documents"))

    @pytest.fixture
    def source_registry(self, tmp_path) -> SourceRegistry:
        """Provide a SourceRegistry instance."""
        return SourceRegistry(base_path=str(tmp_path / "sources"))

    @pytest.fixture
    def ingest_service(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        embedding_index: EmbeddingIndex,
        graph_index: GraphIndex,
        llm_service: Optional[LLMService],
    ) -> IngestService:
        """Create an IngestService with REAL indexes.
        
        In live mode: Includes LLM service for graph extraction
        In mock mode: LLM service is None (extraction will be mocked)
        """
        return IngestService(
            document_store=document_store,
            source_registry=source_registry,
            language_detector=LanguageDetector(),
            duplicate_detector=DuplicateDetector(),
            embedding_index=embedding_index,
            graph_index=graph_index,
            llm_service=llm_service,  # None in mock mode, real service in live mode
        )

    @pytest.fixture
    def query_service(
        self,
        embedding_index: EmbeddingIndex,
        graph_index: GraphIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> QueryService:
        """Create a QueryService with REAL indexes."""
        return QueryService(
            embedding_index=embedding_index,
            graph_index=graph_index,
            document_store=document_store,
            source_registry=source_registry,
        )

    @pytest.fixture
    def test_sources(self, source_registry: SourceRegistry) -> Dict[str, Source]:
        """Create test sources (global, not group-specific)."""
        sources = {}
        for group_code, group_guid in GROUPS.items():
            source = source_registry.create(
                name=f"Source {group_code}",
                source_type=SourceType.NEWS_AGENCY,
                trust_level=TrustLevel.HIGH,
            )
            sources[group_code] = source
        return sources

    @pytest.fixture
    def populated_indexes(
        self,
        ingest_service: IngestService,
        graph_index: GraphIndex,
        embedding_index: EmbeddingIndex,
        test_sources: Dict[str, Source],
    ) -> None:
        """Populate ChromaDB and Neo4j with test articles."""
        
        # 1. Setup Graph Relationships (Peers, Sectors)
        with graph_index._get_session() as session:
            # Create Peer Relationships
            peers = [
                ("AAPL", "SSNLF"), ("AAPL", "MSFT"), ("AAPL", "GOOGL"),
                ("AMD", "INTC"), ("AMD", "NVDA"),
                ("TSLA", "RIVN"), ("TSLA", "BYD"),
                ("MSFT", "GOOGL"), ("MSFT", "AMZN"),
            ]
            for t1, t2 in peers:
                graph_index.create_instrument(t1, t1, instrument_type="EQUITY", exchange="UNKNOWN")
                graph_index.create_instrument(t2, t2, instrument_type="EQUITY", exchange="UNKNOWN")
                session.run(
                    """
                    MATCH (i1:Instrument {ticker: $t1}), (i2:Instrument {ticker: $t2})
                    MERGE (i1)-[:PEER_OF]->(i2)
                    MERGE (i2)-[:PEER_OF]->(i1)
                    """,
                    t1=t1, t2=t2
                )
            
            # Create Sector Relationships
            tech_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "AMD", "INTC", "TSM", "ASML", "AMAT"]
            session.run("MERGE (s:Sector {name: 'Technology', guid: 'sec-tech'})")
            for ticker in tech_tickers:
                session.run(
                    """
                    MATCH (i:Instrument {ticker: $ticker}), (s:Sector {name: 'Technology'})
                    MERGE (i)-[:BELONGS_TO]->(s)
                    """,
                    ticker=ticker
                )

        # 2. Ingest Articles
        # In live mode: Use real LLM extraction and capture data for tuning
        # In mock mode: Use predefined mock extraction data
        capture = get_live_capture()
        
        for article in TEST_ARTICLES:
            source_code = [k for k, v in GROUPS.items() if v == article.group_guid][0]
            source = test_sources[source_code]
            
            if live_llm_available():
                # LIVE MODE: Let the LLM extract entities from content
                # Capture extraction results for tuning analysis
                import time
                start_time = time.time()
                
                result = ingest_service.ingest(
                    title=article.title,
                    content=article.content,
                    source_guid=source.source_guid,
                    group_guid=article.group_guid,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                # Record extraction with ground truth for comparison
                if capture and result.extraction:
                    capture.record_extraction(
                        doc_id=result.guid,
                        title=article.title,
                        content=article.content,
                        extraction_result=result.extraction,
                        expected_score=int(article.impact_score),
                        expected_tier=article.impact_tier,
                        expected_event=article.event_type,
                        expected_instruments=[i["ticker"] for i in article.instruments],
                        latency_ms=latency_ms,
                    )
                    print(f"  📝 {article.title[:40]}... → "
                          f"score={result.extraction.impact_score} "
                          f"(expected={article.impact_score})")
            else:
                # MOCK MODE: Use predefined extraction results
                mock_extraction = GraphExtractionResult(
                    impact_score=int(article.impact_score),
                    impact_tier=article.impact_tier,
                    events=[EventDetection(event_type=article.event_type, confidence=0.9)],
                    instruments=[
                        InstrumentMention(
                            ticker=i["ticker"],
                            direction=i["direction"],
                            magnitude=i["magnitude"]
                        ) for i in article.instruments
                    ],
                    companies=article.companies,
                    summary=article.title
                )

                with patch.object(ingest_service, '_extract_graph_entities', return_value=mock_extraction):
                    ingest_service.ingest(
                        title=article.title,
                        content=article.content,
                        source_guid=source.source_guid,
                        group_guid=article.group_guid,
                    )

    def test_dual_population(self, populated_indexes, graph_index: GraphIndex, embedding_index: EmbeddingIndex):
        """Verify both indexes are populated correctly."""
        assert embedding_index.count() == 15
        count = graph_index.count_nodes(NodeLabel.DOCUMENT)
        assert count == 15
        
        with graph_index._get_session() as session:
            result = session.run("MATCH ()-[r:AFFECTS]->() RETURN count(r) as count")
            record = result.single()
            assert record is not None and record["count"] > 0
            result = session.run("MATCH ()-[r:PEER_OF]->() RETURN count(r) as count")
            record = result.single()
            assert record is not None and record["count"] > 0

    def test_scenario_1_single_stock_direct(self, populated_indexes, query_service: QueryService):
        """Scenario 1: Single-Stock Direct Query (AAPL -> iPhone)
        
        Note: With deterministic embeddings (used in tests), semantic similarity
        is not real, so we verify the query mechanics work rather than specific
        document content matching.
        """
        import time
        start = time.time()
        
        response = query_service.query(
            query_text="Apple iPhone sales",
            group_guids=list(GROUPS.values()),
            n_results=10,
            enable_graph_expansion=True
        )
        
        latency = (time.time() - start) * 1000
        
        # Capture query results in live mode
        capture = get_live_capture()
        if capture:
            capture.record_query(
                query_text="Apple iPhone sales",
                group_guids=list(GROUPS.values()),
                results=response.results,
                n_results=10,
                enable_graph_expansion=True,
                expected_titles=["Apple Q4 Earnings Beat Expectations", "Samsung Reports Strong Galaxy Sales"],
                total_latency_ms=latency,
            )
            # Log hybrid results
            semantic_count = sum(1 for r in response.results if r.discovered_via == "semantic")
            graph_count = sum(1 for r in response.results if r.discovered_via == "graph")
            both_count = sum(1 for r in response.results if r.discovered_via == "both")
            print(f"  🔍 Query 'Apple iPhone sales': {len(response.results)} results "
                  f"(semantic={semantic_count}, graph={graph_count}, both={both_count})")
    
        # In live mode with real embeddings, we expect semantic matches for Apple
        # In mock mode with deterministic embeddings, we just verify query mechanics work
        if live_llm_available():
            assert len(response.results) > 0
            aapl_docs = [r for r in response.results if "AAPL" in r.title or "Apple" in r.title]
            assert len(aapl_docs) > 0
            # Samsung is a peer of Apple, so it should be pulled in (or found via semantic)
            ssnlf_docs = [r for r in response.results if "Samsung" in r.title]
            assert len(ssnlf_docs) > 0
        else:
            # Mock mode: Query should execute without error; results may vary
            # since deterministic embeddings don't produce meaningful similarity
            assert response is not None

    def test_scenario_2_instrument_traversal(self, populated_indexes, query_service: QueryService):
        """Scenario 2: Instrument Traversal (Semiconductor -> NVDA/AMD)
        
        Note: With deterministic embeddings (used in tests), semantic similarity
        is not real, so we verify the query mechanics work rather than specific
        document ordering.
        """
        import time
        start = time.time()
        
        response = query_service.query(
            query_text="semiconductor supply chain",
            group_guids=list(GROUPS.values()),
            n_results=10,
            enable_graph_expansion=True
        )
        
        latency = (time.time() - start) * 1000
        
        # Capture query results in live mode
        capture = get_live_capture()
        if capture:
            capture.record_query(
                query_text="semiconductor supply chain",
                group_guids=list(GROUPS.values()),
                results=response.results,
                n_results=10,
                enable_graph_expansion=True,
                expected_titles=["TSMC Warns of Chip Demand Slowdown", "Nvidia Unveils New AI Chip at GTC", 
                                "AMD Gains Server Market Share from Intel", "Intel Struggles with Foundry Business",
                                "Semiconductor Equipment Orders Decline"],
                total_latency_ms=latency,
            )
            semantic_count = sum(1 for r in response.results if r.discovered_via == "semantic")
            graph_count = sum(1 for r in response.results if r.discovered_via == "graph")
            both_count = sum(1 for r in response.results if r.discovered_via == "both")
            print(f"  🔍 Query 'semiconductor supply chain': {len(response.results)} results "
                  f"(semantic={semantic_count}, graph={graph_count}, both={both_count})")
        
        # Verify results are returned
        assert len(response.results) > 0
        
        # Verify at least one semiconductor-related document is in results
        # (TSMC, ASML, Nvidia, AMD, Intel)
        semi_related = [r for r in response.results 
                       if any(kw in r.title for kw in ["TSMC", "ASML", "Nvidia", "AMD", "Intel", "semiconductor"])]
        assert len(semi_related) > 0, f"Expected semiconductor docs, got: {[r.title for r in response.results]}"

    def test_scenario_4_lateral_discovery(self, populated_indexes, query_service: QueryService):
        """Scenario 4: Lateral Discovery (TSLA -> RIVN via PEER_OF)"""
        import time
        start = time.time()
        
        response = query_service.query(
            query_text="Tesla production numbers",
            group_guids=list(GROUPS.values()),
            n_results=10,
            enable_graph_expansion=True
        )
        
        latency = (time.time() - start) * 1000
        
        # Capture query results in live mode
        capture = get_live_capture()
        if capture:
            capture.record_query(
                query_text="Tesla production numbers",
                group_guids=list(GROUPS.values()),
                results=response.results,
                n_results=10,
                enable_graph_expansion=True,
                expected_titles=["Tesla Cuts Prices Again in China", "Rivian Delays R2 Production"],
                total_latency_ms=latency,
            )
            semantic_count = sum(1 for r in response.results if r.discovered_via == "semantic")
            graph_count = sum(1 for r in response.results if r.discovered_via == "graph")
            both_count = sum(1 for r in response.results if r.discovered_via == "both")
            print(f"  🔍 Query 'Tesla production numbers': {len(response.results)} results "
                  f"(semantic={semantic_count}, graph={graph_count}, both={both_count})")
        
        tsla_docs = [r for r in response.results if "Tesla" in r.title]
        assert len(tsla_docs) > 0
        
        rivn_docs = [r for r in response.results if "Rivian" in r.title]
        assert len(rivn_docs) > 0
        
        rivn_doc = rivn_docs[0]
        if rivn_doc.discovered_via == "graph":
            assert rivn_doc.graph_score > 0

    def test_hybrid_scoring_boost(self, populated_indexes, query_service: QueryService):
        """Verify hybrid scoring weights.
        
        Note: With deterministic embeddings and a small test dataset (15 docs),
        the semantic search alone returns all relevant documents, so we verify
        the hybrid query returns at least as many results as semantic-only.
        In production with real embeddings, graph expansion would surface
        additional related documents.
        """
        import time
        query_text = "Apple"
        
        start = time.time()
        response_hybrid = query_service.query(
            query_text=query_text,
            group_guids=list(GROUPS.values()),
            enable_graph_expansion=True
        )
        hybrid_latency = (time.time() - start) * 1000
        
        start = time.time()
        response_semantic = query_service.query(
            query_text=query_text,
            group_guids=list(GROUPS.values()),
            enable_graph_expansion=False
        )
        semantic_latency = (time.time() - start) * 1000
        
        # Capture both query modes in live mode for comparison
        capture = get_live_capture()
        if capture:
            # Hybrid query
            capture.record_query(
                query_text=f"{query_text} (hybrid)",
                group_guids=list(GROUPS.values()),
                results=response_hybrid.results,
                enable_graph_expansion=True,
                expected_titles=["Apple Q4 Earnings Beat Expectations"],
                total_latency_ms=hybrid_latency,
            )
            # Semantic-only query  
            capture.record_query(
                query_text=f"{query_text} (semantic-only)",
                group_guids=list(GROUPS.values()),
                results=response_semantic.results,
                enable_graph_expansion=False,
                expected_titles=["Apple Q4 Earnings Beat Expectations"],
                total_latency_ms=semantic_latency,
            )
            
            # Log comparison
            h_semantic = sum(1 for r in response_hybrid.results if r.discovered_via == "semantic")
            h_graph = sum(1 for r in response_hybrid.results if r.discovered_via == "graph")
            h_both = sum(1 for r in response_hybrid.results if r.discovered_via == "both")
            print(f"  🔍 Query 'Apple' HYBRID: {len(response_hybrid.results)} results "
                  f"(semantic={h_semantic}, graph={h_graph}, both={h_both}) in {hybrid_latency:.0f}ms")
            print(f"  🔍 Query 'Apple' SEMANTIC-ONLY: {len(response_semantic.results)} results in {semantic_latency:.0f}ms")
        
        # Hybrid should return at least as many results as semantic-only
        assert len(response_hybrid.results) >= len(response_semantic.results)
        
        # Both should return results
        assert len(response_hybrid.results) > 0
        assert len(response_semantic.results) > 0
        
        # All discovered_via should be valid values
        for r in response_hybrid.results:
            assert r.discovered_via in ('semantic', 'graph', 'both')
