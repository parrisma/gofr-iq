"""Duplicate Detection Service - Phase 6.

Detects exact and near-duplicate documents at ingestion time.
Uses content hashing for exact matches and cosine similarity
for near-duplicates.

Duplicate documents are still stored (append-only) but flagged
with duplicate_of and duplicate_score fields.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models import Document
    from app.prompts.graph_extraction import GraphExtractionResult
    from app.services.embedding_index import EmbeddingIndex
    from app.services.graph_index import GraphIndex

__all__ = [
    "DuplicateDetector",
    "DuplicateResult",
    "compute_content_hash",
    "normalize_text",
    "tokenize",
    "cosine_similarity",
    "compute_story_fingerprint",
]


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DuplicateResult:
    """Result of duplicate detection check.

    Attributes:
        is_duplicate: Whether the document is a duplicate
        duplicate_of: GUID of the original document (if duplicate)
        score: Similarity score (1.0 for exact match)
        method: Detection method used ('hash' or 'similarity')
    """

    is_duplicate: bool
    duplicate_of: str | None = None
    score: float = 0.0
    method: str = ""

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "score": self.score,
            "method": self.method,
        }


@dataclass
class CandidateDocument:
    """Lightweight document representation for duplicate checking.

    Attributes:
        guid: Document GUID
        content_hash: SHA-256 hash of normalized content
        title: Document title
        content: Document content (for similarity calculation)
    """

    guid: str
    content_hash: str
    title: str = ""
    content: str = ""


# =============================================================================
# TEXT PROCESSING
# =============================================================================


def normalize_text(text: str) -> str:
    """Normalize text for comparison.

    Normalizations applied:
    - Lowercase
    - Remove extra whitespace
    - Collapse multiple spaces to single space
    - Strip leading/trailing whitespace

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    if not text:
        return ""

    # Lowercase
    normalized = text.lower()

    # Remove extra whitespace (multiple spaces, tabs, newlines)
    normalized = re.sub(r"\s+", " ", normalized)

    # Strip leading/trailing
    normalized = normalized.strip()

    return normalized


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of normalized text.

    Args:
        text: Input text

    Returns:
        Hexadecimal hash string
    """
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    """Tokenize text into words for similarity comparison.

    Simple word-based tokenization that works across languages:
    - Splits on whitespace and punctuation
    - Lowercases all tokens
    - Removes empty tokens

    Args:
        text: Input text

    Returns:
        List of tokens
    """
    if not text:
        return []

    # Lowercase
    text = text.lower()

    # Split on whitespace and common punctuation
    # Using \W+ which matches non-word characters (works for basic use cases)
    tokens = re.split(r"[\s\W]+", text, flags=re.UNICODE)

    # Filter empty tokens
    return [t for t in tokens if t]


def cosine_similarity(tokens1: list[str], tokens2: list[str]) -> float:
    """Compute cosine similarity between two token lists.

    Uses term frequency vectors for comparison.

    Args:
        tokens1: First token list
        tokens2: Second token list

    Returns:
        Similarity score between 0.0 and 1.0
    """
    if not tokens1 or not tokens2:
        return 0.0

    # Build term frequency dictionaries
    freq1: dict[str, int] = {}
    for token in tokens1:
        freq1[token] = freq1.get(token, 0) + 1

    freq2: dict[str, int] = {}
    for token in tokens2:
        freq2[token] = freq2.get(token, 0) + 1

    # Get all unique terms
    all_terms = set(freq1.keys()) | set(freq2.keys())

    # Compute dot product and magnitudes
    dot_product = 0.0
    magnitude1 = 0.0
    magnitude2 = 0.0

    for term in all_terms:
        v1 = freq1.get(term, 0)
        v2 = freq2.get(term, 0)
        dot_product += v1 * v2
        magnitude1 += v1 * v1
        magnitude2 += v2 * v2

    # Avoid division by zero
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    # Cosine similarity
    return dot_product / (magnitude1**0.5 * magnitude2**0.5)


def compute_story_fingerprint(
    *,
    tickers: list[str],
    event_type: str,
    created_at: datetime,
) -> str:
    """Compute a deterministic story fingerprint.

    Fingerprint is built from (sorted tickers, event_type, date) and is intended
    to be stable across paraphrases.
    """
    tickers_norm = sorted({t.strip().upper() for t in tickers if isinstance(t, str) and t.strip()})
    event_norm = (event_type or "OTHER").strip().upper() or "OTHER"
    date_key = created_at.date().isoformat()
    return f"{event_norm}|{date_key}|{','.join(tickers_norm)}"


# =============================================================================
# DUPLICATE DETECTOR
# =============================================================================


@dataclass
class DuplicateDetector:
    """Detects duplicate documents using hash and similarity matching.

    Supports two detection methods:
    1. Exact match: SHA-256 hash of normalized content
    2. Near-duplicate: Cosine similarity on tokenized content

    Attributes:
        similarity_threshold: Minimum similarity for near-duplicate (default 0.95)
        use_hash_detection: Enable exact hash matching (default True)
        use_similarity_detection: Enable similarity matching (default True)
    """

    similarity_threshold: float = 0.85
    use_hash_detection: bool = True
    use_similarity_detection: bool = True
    time_window_hours: int = 48
    fingerprint_window_hours: int = 24

    # Internal cache of known documents (hash -> guid)
    _hash_index: dict[str, str] = field(default_factory=dict)

    # Internal cache of documents for similarity (guid -> CandidateDocument)
    _similarity_index: dict[str, CandidateDocument] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize indexes if needed."""
        # Ensure indexes are initialized
        if not hasattr(self, "_hash_index") or self._hash_index is None:
            self._hash_index = {}
        if not hasattr(self, "_similarity_index") or self._similarity_index is None:
            self._similarity_index = {}

    def check(
        self,
        title: str,
        content: str,
        group: str | None = None,
        *,
        embedding_index: "EmbeddingIndex | None" = None,
        graph_index: "GraphIndex | None" = None,
        created_at: datetime | None = None,
        extraction: "GraphExtractionResult | None" = None,
    ) -> DuplicateResult:
        """Check if content is a duplicate.

        Checks in order:
        1. Exact hash match
        2. Similarity match (if enabled and no exact match)

        Args:
            title: Document title
            content: Document content
            group: Optional group filter (not used in basic implementation)

        Returns:
            DuplicateResult with detection details
        """
        # Combine title and content for full comparison
        full_text = f"{title} {content}".strip()

        if not full_text:
            return DuplicateResult(is_duplicate=False)

        created_at = created_at or datetime.utcnow()

        # 1. Check exact hash match (prefer persisted graph lookup if available)
        if self.use_hash_detection:
            content_hash = compute_content_hash(full_text)

            if graph_index is not None:
                try:
                    with graph_index._get_session() as session:
                        result = session.run(
                            """
                            MATCH (d:Document {content_hash: $content_hash})
                            WHERE $group_guid IS NULL OR d.group_guid = $group_guid
                            RETURN d.guid AS guid
                            LIMIT 1
                            """,
                            content_hash=content_hash,
                            group_guid=group,
                        )
                        record = result.single()
                        if record and record.get("guid"):
                            return DuplicateResult(
                                is_duplicate=True,
                                duplicate_of=str(record.get("guid")),
                                score=1.0,
                                method="hash",
                            )
                except Exception:  # nosec B110 - non-critical best-effort graph lookup
                    # Fall back to in-memory index if graph lookup fails
                    pass

            if content_hash in self._hash_index:
                original_guid = self._hash_index[content_hash]
                return DuplicateResult(
                    is_duplicate=True,
                    duplicate_of=original_guid,
                    score=1.0,
                    method="hash",
                )

        # 1b. Fingerprint check (requires extraction)
        if extraction is not None:
            try:
                tickers = [i.ticker for i in extraction.instruments if getattr(i, "ticker", None)]
                primary_event = extraction.primary_event
                event_type = primary_event.event_type if primary_event else "OTHER"
                fingerprint = compute_story_fingerprint(
                    tickers=tickers,
                    event_type=event_type,
                    created_at=created_at,
                )

                if graph_index is not None:
                    cutoff = (created_at - timedelta(hours=self.fingerprint_window_hours)).isoformat()
                    with graph_index._get_session() as session:
                        result = session.run(
                            """
                            MATCH (d:Document {story_fingerprint: $fingerprint})
                            WHERE ($group_guid IS NULL OR d.group_guid = $group_guid)
                              AND d.created_at >= $cutoff
                            RETURN d.guid AS guid
                            ORDER BY d.created_at DESC
                            LIMIT 1
                            """,
                            fingerprint=fingerprint,
                            group_guid=group,
                            cutoff=cutoff,
                        )
                        record = result.single()
                        if record and record.get("guid"):
                            return DuplicateResult(
                                is_duplicate=True,
                                duplicate_of=str(record.get("guid")),
                                score=1.0,
                                method="fingerprint",
                            )
            except Exception:  # nosec B110 - fingerprint is a best-effort signal
                pass

        # 2. Check semantic near-duplicate match via ChromaDB (preferred)
        if self.use_similarity_detection and embedding_index is not None:
            try:
                # Overfetch then filter by time window and group (group filtering is enforced in search())
                candidates = embedding_index.search(
                    query=full_text,
                    n_results=25,
                    group_guids=[group] if group else None,
                    include_content=False,
                )
                cutoff_dt = created_at - timedelta(hours=self.time_window_hours)

                best_guid: str | None = None
                best_score = 0.0
                for cand in candidates:
                    if not cand.document_guid:
                        continue
                    meta_created = cand.metadata.get("created_at")
                    if isinstance(meta_created, str) and meta_created:
                        try:
                            cand_dt = datetime.fromisoformat(meta_created.replace("Z", "+00:00"))
                        except ValueError:
                            cand_dt = None
                        if cand_dt is not None and cand_dt < cutoff_dt:
                            continue

                    if cand.score >= self.similarity_threshold and cand.score > best_score:
                        best_guid = cand.document_guid
                        best_score = cand.score

                if best_guid:
                    return DuplicateResult(
                        is_duplicate=True,
                        duplicate_of=best_guid,
                        score=best_score,
                        method="embedding",
                    )
            except Exception:  # nosec B110 - fallback to in-memory similarity if Chroma query fails
                pass

        # 3. Check similarity match (legacy in-memory token cosine)
        if self.use_similarity_detection and self._similarity_index:
            tokens = tokenize(full_text)
            best_match: CandidateDocument | None = None
            best_score = 0.0

            for candidate in self._similarity_index.values():
                candidate_text = f"{candidate.title} {candidate.content}".strip()
                candidate_tokens = tokenize(candidate_text)
                similarity = cosine_similarity(tokens, candidate_tokens)

                if similarity >= self.similarity_threshold and similarity > best_score:
                    best_match = candidate
                    best_score = similarity

            if best_match is not None:
                return DuplicateResult(
                    is_duplicate=True,
                    duplicate_of=best_match.guid,
                    score=best_score,
                    method="similarity",
                )

        return DuplicateResult(is_duplicate=False)

    def register(
        self,
        guid: str,
        title: str,
        content: str,
    ) -> None:
        """Register a document for future duplicate detection.

        Args:
            guid: Document GUID
            title: Document title
            content: Document content
        """
        full_text = f"{title} {content}".strip()
        content_hash = compute_content_hash(full_text)

        # Add to hash index
        self._hash_index[content_hash] = guid

        # Add to similarity index
        self._similarity_index[guid] = CandidateDocument(
            guid=guid,
            content_hash=content_hash,
            title=title,
            content=content,
        )

    def unregister(self, guid: str) -> bool:
        """Remove a document from the detector.

        Args:
            guid: Document GUID to remove

        Returns:
            True if document was found and removed
        """
        if guid not in self._similarity_index:
            return False

        candidate = self._similarity_index.pop(guid)

        # Remove from hash index
        if candidate.content_hash in self._hash_index:
            if self._hash_index[candidate.content_hash] == guid:
                del self._hash_index[candidate.content_hash]

        return True

    def check_and_register(
        self,
        guid: str,
        title: str,
        content: str,
        group: str | None = None,
    ) -> DuplicateResult:
        """Check for duplicate and register if not duplicate.

        Convenience method for ingestion workflow.

        Args:
            guid: Document GUID
            title: Document title
            content: Document content
            group: Optional group filter

        Returns:
            DuplicateResult with detection details
        """
        result = self.check(title, content, group)

        # Always register (append-only), but track original if duplicate
        self.register(guid, title, content)

        return result

    def load_documents(self, documents: Sequence[Document]) -> int:
        """Load existing documents into the detector.

        Args:
            documents: Sequence of Document objects

        Returns:
            Number of documents loaded
        """
        count = 0
        for doc in documents:
            self.register(doc.guid, doc.title, doc.content)
            count += 1
        return count

    def clear(self) -> None:
        """Clear all registered documents."""
        self._hash_index.clear()
        self._similarity_index.clear()

    @property
    def document_count(self) -> int:
        """Number of registered documents."""
        return len(self._similarity_index)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"DuplicateDetector("
            f"documents={self.document_count}, "
            f"threshold={self.similarity_threshold})"
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


# Default detector instance
_default_detector: DuplicateDetector | None = None


def get_default_detector() -> DuplicateDetector:
    """Get the default DuplicateDetector instance.

    Returns:
        Default DuplicateDetector
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = DuplicateDetector()
    return _default_detector


def check_duplicate(
    title: str,
    content: str,
    group: str | None = None,
) -> DuplicateResult:
    """Check if content is a duplicate using default detector.

    Args:
        title: Document title
        content: Document content
        group: Optional group filter

    Returns:
        DuplicateResult with detection details
    """
    return get_default_detector().check(title, content, group)
