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

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.logger import session_logger
from app.models import Document, DocumentCreate, count_words
from app.services.document_store import DocumentNotFoundError, DocumentStore
from app.services.duplicate_detector import (
    DuplicateDetector,
    DuplicateResult,
    compute_content_hash,
    compute_story_fingerprint,
)
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.language_detector import LanguageDetector, LanguageResult
from app.services.source_registry import SourceNotFoundError, SourceRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.prompts.graph_extraction import GraphExtractionResult
    from app.services.alias_resolver import AliasResolver
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
    alias_resolver: "AliasResolver | None" = None
    llm_service: "LLMService | None" = None
    max_word_count: int = 20_000
    strict_ticker_validation: bool = False

    def __post_init__(self) -> None:
        if self.graph_index and self.alias_resolver is None:
            from app.services.alias_resolver import AliasResolver

            self.alias_resolver = AliasResolver(self.graph_index)

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
            
            # Log extracted companies
            if extraction_result and extraction_result.companies:
                session_logger.debug(f"LLM extraction found {len(extraction_result.companies)} companies: {extraction_result.companies}")
            else:
                session_logger.debug("LLM extraction found no companies")
            
            return extraction_result
            
        except LLMServiceError as e:
            if require_extraction:
                session_logger.error(f"LLM extraction failed for {doc.guid}: {e}")
                raise LLMExtractionError(f"LLM extraction failed: {e}") from e
            # Log but don't fail ingestion when not required
            session_logger.warning(f"LLM extraction failed for {doc.guid}: {e}")
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
        
        # Log event mapping
        if llm_event_code:
            if graph_event_code:
                session_logger.debug(f"Event mapping: {llm_event_code} -> {graph_event_code}")
            else:
                session_logger.debug(f"Event mapping: {llm_event_code} -> SKIPPED (no mapping)")
        
        # Set document impact properties
        self.graph_index.set_document_impact(
            document_guid=document_guid,
            impact_score=extraction.impact_score,
            impact_tier=extraction.impact_tier,
            event_type_code=graph_event_code,  # Use mapped code
        )

        # Persist themes on the Document node (for query-time filtering)
        if extraction.themes:
            self.graph_index.set_document_themes(
                document_guid=document_guid,
                themes=extraction.themes,
            )
        
        # Create AFFECTS relationships for instruments
        accepted_tickers = 0
        rejected_tickers = 0
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

                if instrument_guid is None:
                    rejected_tickers += 1
                    continue

                accepted_tickers += 1

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
                    session_logger.error(f"Failed to create AFFECTS for {inst.ticker}: {e}")

            total_tickers = accepted_tickers + rejected_tickers
            if total_tickers > 0:
                session_logger.info(
                    f"Ticker validation: {accepted_tickers}/{total_tickers} accepted"
                    + (f", {rejected_tickers} rejected" if rejected_tickers else "")
                )
            
            # Create MENTIONS relationships for all companies
            # Auto-create companies if they don't exist (like instruments)
            if extraction.companies:
                session_logger.debug(f"Found {len(extraction.companies)} companies to link: {extraction.companies[:3]}")
            
            for company_name in extraction.companies:
                if not company_name:
                    continue
                    
                try:
                    # Resolve or create company (like _resolve_instrument_guid)
                    company_guid = self._resolve_company_guid(
                        session=session,
                        name=company_name,
                    )
                    
                    self.graph_index.add_company_mention(
                        document_guid=document_guid,
                        company_ticker=company_guid,
                        company_name=company_name,
                    )
                    session_logger.debug(f"Created MENTIONS: document -> {company_name} ({company_guid})")
                except Exception as e:
                    session_logger.warning(f"Error creating MENTIONS for {company_name}: {e}")

    def _resolve_instrument_guid(self, session, ticker: str, name: str) -> str | None:
        """Return shared Instrument guid for ticker, creating canonical inst-<ticker> if missing.

        When strict_ticker_validation is True, returns None for tickers not already
        in the instrument universe instead of auto-creating phantom nodes.
        """
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

        # Milestone M2: attempt alias resolution before auto-creating.
        if self.alias_resolver:
            try:
                # Primary: ticker-level alias (if present)
                resolved = self.alias_resolver.resolve(ticker, scheme="TICKER")
                if resolved:
                    return resolved

                # Secondary: name-variant alias (common in newswire)
                resolved = self.alias_resolver.resolve(name, scheme="NAME_VARIANT")
                if resolved:
                    return resolved
            except Exception:  # nosec B110 - alias resolution must not break ingestion
                # Alias resolution should never break ingestion; fall back to existing behavior.
                pass

        # Strict mode: reject tickers not in the known universe
        if self.strict_ticker_validation:
            session_logger.warning(
                f"Ticker '{ticker}' not in instrument universe -- skipping AFFECTS edge"
            )
            return None

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

    def _augment_extraction_with_regex_tickers(
        self,
        content: str,
        extraction: "GraphExtractionResult",
    ) -> int:
        """Scan article text for known tickers the LLM missed and add them.

        Loads the known instrument universe from Neo4j (cached per service
        instance), then does a case-sensitive word-boundary scan of the
        content.  Any known ticker found in the text but absent from the
        LLM extraction is appended as an InstrumentMention with direction
        NEUTRAL and reason 'regex-detected'.

        Returns the number of tickers added.
        """
        if not self.graph_index:
            return 0

        # Lazy-cache the universe ticker set
        if not hasattr(self, "_universe_tickers"):
            try:
                with self.graph_index.driver.session() as session:
                    result = session.run("MATCH (i:Instrument) RETURN i.ticker AS t")
                    self._universe_tickers: set[str] = {
                        r["t"] for r in result if r["t"]
                    }
            except Exception as e:
                session_logger.warning(f"Could not load instrument universe for regex fallback: {e}")
                self._universe_tickers = set()

        if not self._universe_tickers:
            return 0

        from app.prompts.graph_extraction import InstrumentMention

        # Tickers already extracted by LLM
        llm_tickers = {inst.ticker for inst in extraction.instruments}

        import re
        added = 0
        for ticker in self._universe_tickers:
            if ticker in llm_tickers:
                continue
            # Word-boundary match, case-sensitive (tickers are uppercase)
            # Matches "NXS" but not "ANXIETY" or "nxs"
            if re.search(rf"\b{re.escape(ticker)}\b", content):
                extraction.instruments.append(
                    InstrumentMention(
                        ticker=ticker,
                        name=ticker,
                        direction="NEUTRAL",
                        magnitude="LOW",
                        reason="regex-detected",
                    )
                )
                added += 1

        if added:
            session_logger.info(
                f"Regex ticker fallback added {added} ticker(s): "
                f"{[i.ticker for i in extraction.instruments if i.reason == 'regex-detected']}"
            )

        return added

    def _resolve_company_guid(self, session, name: str) -> str:
        """Return Company guid for name, creating if missing.
        
        First tries fuzzy match on existing companies, then creates new if not found.
        Company guid format: comp-<normalized_name>
        """
        # Normalize name for guid generation (lowercase, replace spaces with hyphens)
        normalized = name.lower().replace(" ", "-").replace(".", "").replace(",", "")[:50]
        
        # Try fuzzy match on existing companies first
        record = session.run(
            """
            MATCH (c:Company)
            WHERE toLower(c.name) CONTAINS toLower($name)
               OR toLower($name) CONTAINS toLower(c.name)
               OR any(alias IN c.aliases WHERE toLower(alias) CONTAINS toLower($name))
            RETURN c.guid AS guid, c.name AS name
            ORDER BY size(c.name) ASC
            LIMIT 1
            """,
            {"name": name},
        ).single()
        
        if record and record["guid"]:
            return record["guid"]
        
        # Create new company
        guid = f"comp-{normalized}"
        session.run(
            """
            MERGE (c:Company {guid: $guid})
            SET c.name = coalesce(c.name, $name),
                c.ticker = coalesce(c.ticker, $ticker),
                c.aliases = coalesce(c.aliases, []),
                c.simulation_id = coalesce(c.simulation_id, 'extracted')
            """,
            {"guid": guid, "name": name, "ticker": normalized.upper()[:10]},
        )
        session_logger.info(f"Auto-created company: {name} ({guid})")
        
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
        session_logger.info(f"Starting document ingestion: guid={doc_guid}, title='{title[:50]}...', source={source_guid}, group={group_guid}")

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
                    # Update source_guid to use the actual source's GUID (name lookup fallback)
                    source_guid = source.source_guid
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

        # Step 5: Prepare a provisional document for extraction/duplicate checks
        provisional_doc = Document(
            guid=doc_guid,
            source_guid=source_guid,
            group_guid=group_guid,
            title=title,
            content=content,
            language=lang_result.language,
            language_detected=language_detected,
            word_count=word_count,
            version=1,
            duplicate_of=None,
            duplicate_score=0.0,
            metadata=metadata or {},
        )

        doc = provisional_doc
        saved_to_file = False

        # Step 6+: Extraction/duplicate decision + indexing with Rollback
        try:

            # Step 8: LLM extraction FIRST (before embedding, so we can include impact_score in metadata)
            # If we have a graph index, we MUST have entity extraction to populate relationships.
            # Fail hard if graph is enabled but LLM service is missing.
            if self.graph_index and not self.llm_service:
                raise LLMExtractionError(
                    "Graph index is enabled but LLM service is not available. "
                    "Entity extraction is required for graph relationships. "
                    "Ensure the OpenRouter API key is available via Vault (gofr/config/api-keys/openrouter) "
                    "or set GOFR_IQ_OPENROUTER_API_KEY as an override."
                )
            
            require_extraction = bool(self.graph_index)
            extraction = self._extract_graph_entities(provisional_doc, require_extraction=require_extraction)

            # Step 5b: Duplicate detection after extraction so we can include fingerprints.
            dup_result: DuplicateResult = self.duplicate_detector.check(
                title,
                content,
                group_guid,
                embedding_index=self.embedding_index,
                graph_index=self.graph_index,
                created_at=provisional_doc.created_at,
                extraction=extraction,
            )

            # Final document model (persisted) keeps the provisional created_at.
            doc = provisional_doc.model_copy(
                update={
                    "duplicate_of": dup_result.duplicate_of,
                    "duplicate_score": dup_result.score if dup_result.is_duplicate else 0.0,
                }
            )

            # Step 7: Store to file
            self.document_store.save(doc)
            saved_to_file = True

            # Step 9: Index in ChromaDB (if configured)
            # Include extraction results (impact_score, impact_tier) in metadata
            if self.embedding_index:
                # Include title and created_at in embedding metadata for query results
                embedding_metadata = {
                    "title": doc.title,
                    "created_at": doc.created_at.isoformat() if doc.created_at else "",
                    **(doc.metadata or {}),
                }
                
                # Add impact scores from extraction if available
                if extraction:
                    embedding_metadata["impact_score"] = extraction.impact_score
                    embedding_metadata["impact_tier"] = extraction.impact_tier
                
                self.embedding_index.embed_document(
                    document_guid=doc.guid,
                    content=doc.content,
                    group_guid=doc.group_guid,
                    source_guid=doc.source_guid,
                    language=doc.language,
                    metadata=embedding_metadata,
                )

            # Step 10: Index in Neo4j (if configured)
            if self.graph_index:
                # Ensure Source exists (P0 Fix) and set source_name in metadata
                source_name = doc.metadata.get("source_name") or f"Source-{doc.source_guid}"
                
                # Ensure source_name is in metadata for graph storage (meta_source_name)
                if "source_name" not in doc.metadata:
                    doc.metadata["source_name"] = source_name
                
                # Get trust_level from the source object (already validated above)
                trust_level = None
                if source and source.trust_level:
                    # Convert TrustLevel enum to integer (1-10 scale)
                    trust_level_map = {
                        "high": 10,
                        "medium": 7,
                        "low": 5,
                        "unverified": 3,
                    }
                    trust_level = trust_level_map.get(source.trust_level.value, 5)
                
                try:
                    source_props = {
                        "reliability": doc.metadata.get("reliability", 0.8)
                    }
                    if trust_level is not None:
                        source_props["trust_level"] = trust_level
                    
                    self.graph_index.create_source_node(
                        source_guid=doc.source_guid, 
                        name=source_name,
                        source_type=doc.metadata.get("source_type", "synthetic"),
                        group_guid=doc.group_guid,
                        properties=source_props
                    )
                except Exception:  # nosec B110 - MERGE handles duplicates, ignore already exists
                    pass

                self.graph_index.create_document_node(
                    document_guid=doc.guid,
                    source_guid=doc.source_guid,
                    group_guid=doc.group_guid,
                    title=doc.title,
                    language=doc.language,
                    created_at=doc.created_at,
                    metadata=doc.metadata,
                    content_hash=compute_content_hash(f"{doc.title} {doc.content}".strip()),
                    story_fingerprint=(
                        None
                        if not extraction
                        else compute_story_fingerprint(
                            tickers=[i.ticker for i in extraction.instruments if i.ticker],
                            event_type=(extraction.primary_event.event_type if extraction.primary_event else "OTHER"),
                            created_at=doc.created_at,
                        )
                    ),
                )

            # Step 11: Update graph with extracted entities (if extraction succeeded)
            if extraction and self.graph_index:
                # Regex ticker fallback: catch known tickers the LLM missed
                self._augment_extraction_with_regex_tickers(doc.content, extraction)
                self._apply_extraction_to_graph(doc.guid, extraction)

        except Exception as e:
            # Rollback on failure
            session_logger.error(f"Error indexing document {doc_guid}: {e}. Rolling back.")

            # 1. Remove from file store
            if saved_to_file:
                try:
                    self.document_store.delete(doc.guid, doc.group_guid, doc.created_at)
                except Exception as rollback_error:
                    session_logger.error(f"CRITICAL: Failed to rollback file store for {doc_guid}: {rollback_error}")

            # 2. Remove from embedding index
            if self.embedding_index:
                try:
                    self.embedding_index.delete_document(doc_guid)
                except Exception as rollback_error:
                    session_logger.error(f"CRITICAL: Failed to rollback embedding index for {doc_guid}: {rollback_error}")

            # 3. Remove from graph index
            if self.graph_index:
                try:
                    self.graph_index.delete_node(NodeLabel.DOCUMENT, doc_guid)
                except Exception as rollback_error:
                    session_logger.error(f"CRITICAL: Failed to rollback graph index for {doc_guid}: {rollback_error}")

            return IngestResult(
                guid=doc_guid,
                status=IngestStatus.FAILED,
                language=lang_result.language,
                language_detected=language_detected,
                word_count=word_count,
                error=f"Indexing failed: {str(e)}",
                created_at=provisional_doc.created_at,
            )

        # Step 12: Register with duplicate detector for future checks
        self.duplicate_detector.register(doc_guid, title, content)

        # Determine status
        status = IngestStatus.DUPLICATE if dup_result.is_duplicate else IngestStatus.SUCCESS
        
        # Log successful ingestion
        if status == IngestStatus.SUCCESS:
            session_logger.info(f"Document ingested successfully: guid={doc_guid}, language={lang_result.language}, words={word_count}" + 
                              (f", extraction: {len(extraction.companies) if extraction else 0} companies" if extraction else ""))
        else:
            session_logger.info(f"Document marked as duplicate: guid={doc_guid}, duplicate_of={dup_result.duplicate_of}, score={dup_result.score:.2f}")

        return IngestResult(
            guid=doc_guid,
            status=status,
            language=lang_result.language,
            language_detected=language_detected,
            duplicate_of=dup_result.duplicate_of,
            duplicate_score=dup_result.score if dup_result.is_duplicate else None,
            word_count=word_count,
            created_at=provisional_doc.created_at,
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
    language_detector = LanguageDetector()
    duplicate_detector = DuplicateDetector()

    # Initialize SourceRegistry with Neo4j sync if graph_index is provided
    source_registry = SourceRegistry(
        base_path=storage_path / "sources",
        graph_index=graph_index,
    )

    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
        embedding_index=embedding_index,
        graph_index=graph_index,
        llm_service=llm_service,
        max_word_count=max_word_count,
        strict_ticker_validation=os.environ.get("GOFR_IQ_STRICT_TICKER_VALIDATION", "").lower() in ("1", "true", "yes"),
    )
