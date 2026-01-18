"""Basic Ingest Service - Phase 7.

Orchestrates document ingestion without external indexes.
Validates source, word count, detects language, checks duplicates,
and stores documents to the canonical file store.

Full ingest flow (Phase 7 - file-only):
1. Validate source_guid exists
2. Validate word count (max 20,000)
3. Generate document GUID (UUID v4)
4. Detect language (auto-detect if not provided)
5. Check for duplicates
6. Store to canonical file store
7. LLM extraction (impact score, events, instruments)
8. Update graph with extracted entities
9. Return { guid, status, duplicate_of?, language }

External indexing (Elasticsearch, ChromaDB, Neo4j) will be added in later phases.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models import Document, DocumentCreate, count_words
from app.services.document_store import DocumentNotFoundError, DocumentStore
from app.services.duplicate_detector import DuplicateDetector, DuplicateResult
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.language_detector import LanguageDetector, LanguageResult
from app.services.source_registry import SourceNotFoundError, SourceRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.prompts.graph_extraction import GraphExtractionResult
    from app.services.llm_service import LLMService

__all__ = [
    "IngestError",
    "IngestResult",
    "IngestService",
    "IngestStatus",
    "LLMExtractionError",
    "SourceValidationError",
    "WordCountError",
]


# =============================================================================
# EXCEPTIONS
# =============================================================================


class IngestError(Exception):
    """Base exception for ingest errors."""

    pass


class SourceValidationError(IngestError):
    """Error validating source during ingestion."""

    def __init__(self, source_guid: str, message: str = "Source not found") -> None:
        self.source_guid = source_guid
        super().__init__(f"Source validation failed for '{source_guid}': {message}")


class WordCountError(IngestError):
    """Error when document exceeds word count limit."""

    def __init__(self, word_count: int, max_count: int = 20_000) -> None:
        self.word_count = word_count
        self.max_count = max_count
        super().__init__(
            f"Document exceeds word count limit: {word_count} > {max_count}"
        )


class LLMExtractionError(IngestError):
    """Error when LLM extraction fails and is required."""

    def __init__(self, message: str = "LLM extraction failed") -> None:
        super().__init__(message)


# =============================================================================
# DATA CLASSES
# =============================================================================


class IngestStatus(str, Enum):
    """Status of document ingestion."""

    SUCCESS = "success"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass
class IngestResult:
    """Result of document ingestion.

    Attributes:
        guid: Document GUID (UUID v4)
        status: Ingestion status (success, duplicate, failed)
        language: Detected or provided language
        language_detected: Whether language was auto-detected
        duplicate_of: Original document GUID if duplicate
        duplicate_score: Similarity score if duplicate
        word_count: Number of words in content
        error: Error message if failed
        created_at: Timestamp when document was created
        extraction: LLM extraction result (impact, events, instruments)
    """

    guid: str
    status: IngestStatus
    language: str = "en"
    language_detected: bool = False
    duplicate_of: str | None = None
    duplicate_score: float | None = None
    word_count: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extraction: "GraphExtractionResult | None" = None

    @property
    def is_success(self) -> bool:
        """Check if ingestion was successful."""
        return self.status == IngestStatus.SUCCESS

    @property
    def is_duplicate(self) -> bool:
        """Check if document was flagged as duplicate."""
        return self.status == IngestStatus.DUPLICATE

    @property
    def is_failed(self) -> bool:
        """Check if ingestion failed."""
        return self.status == IngestStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "guid": self.guid,
            "status": self.status.value,
            "language": self.language,
            "language_detected": self.language_detected,
            "word_count": self.word_count,
            "created_at": self.created_at.isoformat(),
        }
        if self.duplicate_of:
            result["duplicate_of"] = self.duplicate_of
        if self.duplicate_score is not None:
            result["duplicate_score"] = self.duplicate_score
        if self.error:
            result["error"] = self.error
        if self.extraction:
            result["extraction"] = self.extraction.to_dict()
        return result


# =============================================================================
# INGEST SERVICE
# =============================================================================


@dataclass
class IngestService:
    """Service for ingesting documents into the repository.

    Orchestrates the full ingestion flow:
    1. Validate source exists
    2. Validate word count
    3. Generate document GUID
    4. Detect language
    5. Check duplicates
    6. Store to file
    7. LLM extraction (if available)
    8. Update graph with extracted entities

    Attributes:
        document_store: Storage for documents
        source_registry: Registry for source validation
        language_detector: Language detection service
        duplicate_detector: Duplicate detection service
        embedding_index: Optional embedding index for semantic search
        graph_index: Optional graph index for entity relationships
        llm_service: Optional LLM service for content extraction
        max_word_count: Maximum allowed word count (default 20,000)
    """

    document_store: DocumentStore
    source_registry: SourceRegistry
    language_detector: LanguageDetector = field(default_factory=LanguageDetector)
    duplicate_detector: DuplicateDetector = field(default_factory=DuplicateDetector)
    embedding_index: EmbeddingIndex | None = None
    graph_index: GraphIndex | None = None
    llm_service: "LLMService | None" = None
    max_word_count: int = 20_000

    def _extract_graph_entities(
        self,
        doc: Document,
        require_extraction: bool = True,
    ) -> "GraphExtractionResult | None":
        """Extract graph entities from document using LLM
        
        Args:
            doc: Document to analyze
            require_extraction: If True, raise error when LLM unavailable or fails
            
        Returns:
            Extraction result or None if LLM not available and not required
            
        Raises:
            LLMExtractionError: If require_extraction=True and extraction fails
        """
        # Import here to avoid circular imports
        from app.prompts.graph_extraction import (
            GRAPH_EXTRACTION_SYSTEM_PROMPT,
            build_extraction_prompt,
            create_default_result,
            parse_extraction_response,
        )
        from app.services.llm_service import ChatMessage, LLMServiceError

        if not self.llm_service or not self.llm_service.is_available:
            if require_extraction:
                raise LLMExtractionError("LLM service not available for graph extraction")
            return None
            
        try:
            # Build the extraction prompt
            user_prompt = build_extraction_prompt(
                content=doc.content,
                title=doc.title,
                source_name=doc.metadata.get("source_name"),
                published_at=doc.metadata.get("published_at"),
            )
            
            # Call LLM with system prompt
            result = self.llm_service.chat_completion(
                messages=[
                    ChatMessage(role="system", content=GRAPH_EXTRACTION_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ],
                json_mode=True,
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=1000,
            )
            
            # Parse the response
            extraction_result = parse_extraction_response(result.content)
            
            # DEBUG: Log extracted companies
            if extraction_result and extraction_result.companies:
                print(f"   DEBUG EXTRACT: Found {len(extraction_result.companies)} companies: {extraction_result.companies}")
            else:
                print(f"   DEBUG EXTRACT: No companies found in extraction")
            
            return extraction_result
            
        except LLMServiceError as e:
            if require_extraction:
                raise LLMExtractionError(f"LLM extraction failed: {e}") from e
            # Log but don't fail ingestion when not required
            print(f"LLM extraction failed for {doc.guid}: {e}")
            return create_default_result()

    def _apply_extraction_to_graph(
        self,
        document_guid: str,
        extraction: GraphExtractionResult,
    ) -> None:
        """Apply extracted entities to the graph
        
        Creates relationships between the document and:
        - EventTypes (TRIGGERED_BY)
        - Instruments (AFFECTS)
        - Companies (MENTIONS)
        
        Args:
            document_guid: Document GUID
            extraction: Extraction result from LLM
        """
        if not self.graph_index:
            return
        
        # Map LLM event types to graph EventType codes
        # LLM returns specific types like EARNINGS_BEAT, EARNINGS_MISS
        # Graph uses simplified categories like EARNINGS, M&A
        EVENT_TYPE_MAPPING = {
            "EARNINGS_BEAT": "EARNINGS",
            "EARNINGS_MISS": "EARNINGS",
            "EARNINGS_WARNING": "EARNINGS",
            "GUIDANCE_RAISE": "EARNINGS",
            "GUIDANCE_CUT": "EARNINGS",
            "M&A_ANNOUNCE": "M&A",
            "M&A_RUMOR": "M&A",
            "IPO": "M&A",
            "SECONDARY": "M&A",
            "BUYBACK": "M&A",
            "DIVIDEND_CHANGE": "EARNINGS",
            "ACTIVIST": "M&A",
            "INSIDER_TXN": "EXEC_CHANGE",
            "INDEX_ADD": "REGULATORY",
            "INDEX_DELETE": "REGULATORY",
            "INDEX_REBAL": "REGULATORY",
            "RATING_UPGRADE": "EARNINGS",
            "RATING_DOWNGRADE": "EARNINGS",
            "FDA_APPROVAL": "FDA_APPROVAL",
            "FDA_REJECTION": "FDA_APPROVAL",
            "LEGAL_RULING": "LITIGATION",
            "FRAUD_SCANDAL": "LITIGATION",
            "MGMT_CHANGE": "EXEC_CHANGE",
            "PRODUCT_LAUNCH": "PRODUCT_LAUNCH",
            "CONTRACT_WIN": "PRODUCT_LAUNCH",
            "CONTRACT_LOSS": "PRODUCT_LAUNCH",
            "MACRO_DATA": "MACRO_ECON",
            "CENTRAL_BANK": "MACRO_ECON",
            "GEOPOLITICAL": "MACRO_ECON",
            "POSITIVE_SENTIMENT": "EARNINGS",  # Default to earnings category
            "NEGATIVE_SENTIMENT": "EARNINGS",  # Default to earnings category
            "OTHER": None,  # Skip generic OTHER events
        }
            
        # Get primary event type code and map it
        primary_event = extraction.primary_event
        llm_event_code = primary_event.event_type if primary_event else None
        graph_event_code = EVENT_TYPE_MAPPING.get(llm_event_code) if llm_event_code else None
        
        # DEBUG: Log event mapping
        if llm_event_code:
            if graph_event_code:
                print(f"   DEBUG EVENT: {llm_event_code} -> {graph_event_code}")
            else:
                print(f"   DEBUG EVENT: {llm_event_code} -> SKIPPED (no mapping)")
        
        # Set document impact properties
        self.graph_index.set_document_impact(
            document_guid=document_guid,
            impact_score=extraction.impact_score,
            impact_tier=extraction.impact_tier,
            event_type_code=graph_event_code,  # Use mapped code
        )
        
        # Create AFFECTS relationships for instruments
        with self.graph_index.driver.session() as session:
            for inst in extraction.instruments:
                if not inst.ticker:
                    continue

                # Reuse shared instrument nodes (inst-<ticker>) if present; create canonical otherwise
                instrument_guid = self._resolve_instrument_guid(
                    session=session,
                    ticker=inst.ticker,
                    name=inst.name or inst.ticker,
                )

                # Map direction to expected values
                direction_map = {
                    "UP": "positive",
                    "DOWN": "negative",
                    "MIXED": "neutral",
                    "NEUTRAL": "neutral",
                }
                direction = direction_map.get(inst.direction, "neutral")
                
                # Map magnitude to numeric value
                magnitude_map = {
                    "HIGH": 0.05,
                    "MODERATE": 0.02,
                    "LOW": 0.01,
                }
                magnitude = magnitude_map.get(inst.magnitude, 0.01)
                
                try:
                    self.graph_index.add_document_affects(
                        document_guid=document_guid,
                        instrument_guid=instrument_guid,
                        direction=direction,
                        magnitude=magnitude,
                    )
                except Exception as e:
                    print(f"Failed to create AFFECTS for {inst.ticker}: {e}")
            
            # Create MENTIONS relationships for all companies
            # This allows tracking of secondary/contextual company references
            if extraction.companies:
                print(f"   DEBUG: Found {len(extraction.companies)} companies to link: {extraction.companies[:3]}")
            
            for company_name in extraction.companies:
                if not company_name:
                    continue
                    
                try:
                    # Find company by name (case-insensitive fuzzy match)
                    company_result = session.run(
                        """
                        MATCH (c:Company)
                        WHERE toLower(c.name) CONTAINS toLower($name)
                           OR toLower($name) CONTAINS toLower(c.name)
                           OR any(alias IN c.aliases WHERE toLower(alias) CONTAINS toLower($name))
                        RETURN c.guid AS guid, c.name AS name
                        ORDER BY size(c.name) ASC
                        LIMIT 1
                        """,
                        {"name": company_name}
                    ).single()
                    
                    if company_result:
                        company_guid = company_result["guid"]
                        company_name_matched = company_result["name"]
                        self.graph_index.add_company_mention(
                            document_guid=document_guid,
                            company_ticker=company_guid,  # Using guid as ticker identifier
                            company_name=company_name_matched,
                        )
                        print(f"   DEBUG: Created MENTIONS: {company_name} -> {company_name_matched}")
                    else:
                        print(f"   DEBUG: No match found for company: {company_name}")
                except Exception as e:
                    # Silently skip unresolved companies (may be external/not in universe)
                    print(f"   DEBUG: Error creating MENTIONS for {company_name}: {e}")

    def _resolve_instrument_guid(self, session, ticker: str, name: str) -> str:
        """Return shared Instrument guid for ticker, creating canonical inst-<ticker> if missing."""
        # Prefer existing shared instruments (created by universe loader) before creating new
        record = session.run(
            """
            MATCH (i:Instrument {ticker: $ticker})
            RETURN i.guid AS guid
            ORDER BY CASE WHEN i.guid STARTS WITH 'inst-' THEN 0 ELSE 1 END, i.guid
            LIMIT 1
            """,
            {"ticker": ticker},
        ).single()
        if record and record["guid"]:
            return record["guid"]

        guid = f"inst-{ticker}"
        session.run(
            """
            MERGE (i:Instrument {guid: $guid})
            SET i.ticker = $ticker,
                i.name = coalesce(i.name, $name),
                i.instrument_type = coalesce(i.instrument_type, 'STOCK'),
                i.exchange = coalesce(i.exchange, 'UNKNOWN'),
                i.currency = coalesce(i.currency, 'USD'),
                i.simulation_id = coalesce(i.simulation_id, 'phase1')
            """,
            {"guid": guid, "ticker": ticker, "name": name},
        )

        return guid

    def ingest(
        self,
        title: str,
        content: str,
        source_guid: str,
        group_guid: str,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Ingest a document into the repository.

        Args:
            title: Document title
            content: Document content
            source_guid: GUID of the source
            group_guid: GUID of the group this document belongs to
            language: Language code (auto-detected if not provided)
            metadata: Optional metadata dictionary

        Returns:
            IngestResult with document details

        Raises:
            SourceValidationError: If source_guid is invalid
            WordCountError: If content exceeds word count limit
        """
        # Import APAC_LANGUAGES at module level
        from app.services.language_detector import APAC_LANGUAGES

        # Step 1: Generate document GUID first (so we can return it on error)
        doc_guid = str(uuid.uuid4())

        # Step 2: Validate source exists (sources are now global, not group-specific)
        try:
            source = self.source_registry.get(source_guid)
            if source is None:
                raise SourceValidationError(source_guid)
        except SourceNotFoundError:
            # Fallback: Try to find source by name from metadata (for simulation compatibility)
            # Story files may reference mock source GUIDs that don't exist, but names match
            source_name = metadata.get("meta_source_name") if metadata else None
            if source_name:
                source = self.source_registry.find_by_name(source_name)
                if source:
                    # Update source_guid to use the actual source's GUID
                    source_guid = source.source_guid
                    self.logger.debug(f"Source GUID {source_guid} not found, using name lookup: {source_name} -> {source.source_guid}")
                else:
                    raise SourceValidationError(source_guid)
            else:
                raise SourceValidationError(source_guid)

        # Step 3: Validate word count
        word_count = count_words(content)
        if word_count > self.max_word_count:
            raise WordCountError(word_count, self.max_word_count)

        # Step 4: Detect language
        lang_result: LanguageResult
        language_detected = False
        if language:
            # Use provided language
            lang_result = LanguageResult(
                language=language,
                confidence=1.0,
                detected_code=language,
                is_apac=language in APAC_LANGUAGES,
            )
        else:
            # Auto-detect language
            lang_result = self.language_detector.detect(f"{title} {content}")
            language_detected = True

        # Step 5: Check for duplicates
        dup_result: DuplicateResult = self.duplicate_detector.check(title, content)

        # Step 6: Create document model
        doc = Document(
            guid=doc_guid,
            source_guid=source_guid,
            group_guid=group_guid,
            title=title,
            content=content,
            language=lang_result.language,
            language_detected=language_detected,
            word_count=word_count,
            version=1,
            duplicate_of=dup_result.duplicate_of,
            duplicate_score=dup_result.score if dup_result.is_duplicate else 0.0,
            metadata=metadata or {},
        )

        # Step 7: Store to file
        self.document_store.save(doc)

        # Step 8 & 9: Indexing with Rollback
        try:
            # Step 8: Index in ChromaDB (if configured)
            if self.embedding_index:
                # Include title and created_at in embedding metadata for query results
                embedding_metadata = {
                    "title": doc.title,
                    "created_at": doc.created_at.isoformat() if doc.created_at else "",
                    **(doc.metadata or {}),
                }
                self.embedding_index.embed_document(
                    document_guid=doc.guid,
                    content=doc.content,
                    group_guid=doc.group_guid,
                    source_guid=doc.source_guid,
                    language=doc.language,
                    metadata=embedding_metadata,
                )

            # Step 9: Index in Neo4j (if configured)
            if self.graph_index:
                # Ensure Source exists (P0 Fix) and set source_name in metadata
                source_name = doc.metadata.get("source_name") or f"Source-{doc.source_guid}"
                
                # Ensure source_name is in metadata for graph storage (meta_source_name)
                if "source_name" not in doc.metadata:
                    doc.metadata["source_name"] = source_name
                
                try:
                    self.graph_index.create_source_node(
                        source_guid=doc.source_guid, 
                        name=source_name,
                        source_type=doc.metadata.get("source_type", "synthetic"),
                        group_guid=doc.group_guid,
                        properties={"reliability": doc.metadata.get("reliability", 0.8)}
                    )
                except Exception:
                    pass # Ignore if already exists (MERGE handles duplicates)

                self.graph_index.create_document_node(
                    document_guid=doc.guid,
                    source_guid=doc.source_guid,
                    group_guid=doc.group_guid,
                    title=doc.title,
                    language=doc.language,
                    created_at=doc.created_at,
                    metadata=doc.metadata,
                )

            # Step 10: LLM extraction (required when graph is configured)
            # If we have a graph index, we MUST have entity extraction to populate relationships.
            # Fail hard if graph is enabled but LLM service is missing.
            if self.graph_index and not self.llm_service:
                raise LLMExtractionError(
                    "Graph index is enabled but LLM service is not available. "
                    "Entity extraction is required for graph relationships. "
                    "Ensure GOFR_IQ_OPENROUTER_API_KEY is set."
                )
            
            require_extraction = bool(self.graph_index)
            extraction = self._extract_graph_entities(doc, require_extraction=require_extraction)

            # Step 11: Update graph with extracted entities (if extraction succeeded)
            if extraction and self.graph_index:
                self._apply_extraction_to_graph(doc.guid, extraction)

        except Exception as e:
            # Rollback on failure
            print(f"Error indexing document {doc.guid}: {e}. Rolling back.")

            # 1. Remove from file store
            try:
                self.document_store.delete(doc.guid, doc.group_guid, doc.created_at)
            except Exception as rollback_error:
                print(f"CRITICAL: Failed to rollback file store for {doc.guid}: {rollback_error}")

            # 2. Remove from embedding index
            if self.embedding_index:
                try:
                    self.embedding_index.delete_document(doc.guid)
                except Exception as rollback_error:
                    print(f"CRITICAL: Failed to rollback embedding index for {doc.guid}: {rollback_error}")

            # 3. Remove from graph index
            if self.graph_index:
                try:
                    self.graph_index.delete_node(NodeLabel.DOCUMENT, doc.guid)
                except Exception as rollback_error:
                    print(f"CRITICAL: Failed to rollback graph index for {doc.guid}: {rollback_error}")

            return IngestResult(
                guid=doc_guid,
                status=IngestStatus.FAILED,
                language=lang_result.language,
                language_detected=language_detected,
                word_count=word_count,
                error=f"Indexing failed: {str(e)}",
                created_at=doc.created_at,
            )

        # Step 12: Register with duplicate detector for future checks
        self.duplicate_detector.register(doc_guid, title, content)

        # Determine status
        status = IngestStatus.DUPLICATE if dup_result.is_duplicate else IngestStatus.SUCCESS

        return IngestResult(
            guid=doc_guid,
            status=status,
            language=lang_result.language,
            language_detected=language_detected,
            duplicate_of=dup_result.duplicate_of,
            duplicate_score=dup_result.score if dup_result.is_duplicate else None,
            word_count=word_count,
            created_at=doc.created_at,
            extraction=extraction,
        )

    def ingest_from_input(
        self,
        input_data: DocumentCreate,
    ) -> IngestResult:
        """Ingest a document from a DocumentCreate input model.

        Args:
            input_data: Document creation input (contains group_guid)

        Returns:
            IngestResult with document details
        """
        return self.ingest(
            title=input_data.title,
            content=input_data.content,
            source_guid=input_data.source_guid,
            group_guid=input_data.group_guid,
            language=input_data.language,
            metadata=input_data.metadata,
        )

    def ingest_batch(
        self,
        documents: Sequence[DocumentCreate],
        stop_on_error: bool = False,
    ) -> list[IngestResult]:
        """Ingest multiple documents.

        Args:
            documents: Sequence of DocumentCreate inputs
            stop_on_error: Stop on first error (default False)

        Returns:
            List of IngestResult for each document
        """
        results: list[IngestResult] = []

        for doc_input in documents:
            try:
                result = self.ingest_from_input(doc_input)
                results.append(result)
            except IngestError as e:
                error_result = IngestResult(
                    guid=str(uuid.uuid4()),
                    status=IngestStatus.FAILED,
                    error=str(e),
                )
                results.append(error_result)
                if stop_on_error:
                    break

        return results

    def get_document(self, guid: str, group_guid: str) -> Document | None:
        """Retrieve a document by GUID.

        Args:
            guid: Document GUID
            group_guid: Group GUID for lookup

        Returns:
            Document if found, None otherwise
        """
        try:
            return self.document_store.load(guid, group_guid=group_guid)
        except DocumentNotFoundError:
            return None

    def load_existing_documents(self, group_guid: str) -> int:
        """Load existing documents into duplicate detector.

        Call this on startup to populate the duplicate detector
        with previously ingested documents.

        Args:
            group_guid: Group GUID to load documents from

        Returns:
            Number of documents loaded
        """
        documents = self.document_store.list_by_group(group_guid=group_guid)
        return self.duplicate_detector.load_documents(documents)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"IngestService("
            f"max_words={self.max_word_count}, "
            f"duplicates={self.duplicate_detector.document_count})"
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_ingest_service(
    storage_path: str | Path,
    max_word_count: int = 20_000,
    embedding_index: EmbeddingIndex | None = None,
    graph_index: GraphIndex | None = None,
    llm_service: LLMService | None = None,
) -> IngestService:
    """Create an IngestService with standard configuration.

    Args:
        storage_path: Path to storage directory
        max_word_count: Maximum word count (default 20,000)
        embedding_index: Optional embedding index
        graph_index: Optional graph index
        llm_service: Optional LLM service for content extraction

    Returns:
        Configured IngestService
    """
    storage_path = Path(storage_path)

    document_store = DocumentStore(base_path=storage_path / "documents")
    source_registry = SourceRegistry(base_path=storage_path / "sources")
    language_detector = LanguageDetector()
    duplicate_detector = DuplicateDetector()

    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
        embedding_index=embedding_index,
        graph_index=graph_index,
        llm_service=llm_service,
        max_word_count=max_word_count,
    )
