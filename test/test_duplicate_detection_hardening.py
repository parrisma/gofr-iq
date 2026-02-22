"""Tests for DuplicateDetector hardening (Milestone M3).

These are intentionally focused on the new behaviors added in M3:
- persisted content_hash lookup via Neo4j
- story_fingerprint use (and date component prevents cross-quarter false positives)
- embedding-based near-duplicate path (mocked for determinism)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.prompts.graph_extraction import EventDetection, GraphExtractionResult, InstrumentMention
from app.services.duplicate_detector import (
    DuplicateDetector,
    compute_content_hash,
    compute_story_fingerprint,
)
from app.services.embedding_index import SimilarityResult
from app.services.graph_index import GraphIndex, NodeLabel


@pytest.fixture
def graph_index(neo4j_config: dict[str, str | int]) -> GraphIndex:
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    index.init_schema()
    return index


def test_graph_persisted_content_hash_detects_duplicate(graph_index: GraphIndex) -> None:
    detector = DuplicateDetector()

    title = "AAPL earnings beat"
    content = "Apple reported quarterly results beating expectations."
    full_text = f"{title} {content}".strip()
    h = compute_content_hash(full_text)

    # Seed an existing document node with content_hash in Neo4j
    graph_index.create_node(
        NodeLabel.DOCUMENT,
        "doc-existing",
        {
            "title": title,
            "language": "en",
            "source_guid": "src-1",
            "group_guid": "group-1",
            "created_at": datetime.now(UTC).isoformat(),
            "content_hash": h,
        },
    )

    result = detector.check(
        title,
        content,
        "group-1",
        graph_index=graph_index,
        created_at=datetime.now(UTC),
    )

    assert result.is_duplicate is True
    assert result.duplicate_of == "doc-existing"
    assert result.method == "hash"


def test_story_fingerprint_prevents_cross_quarter_false_positive(graph_index: GraphIndex) -> None:
    detector = DuplicateDetector()

    now = datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC)
    last_quarter = now - timedelta(days=95)

    extraction = GraphExtractionResult(
        impact_score=80,
        impact_tier="GOLD",
        events=[EventDetection(event_type="EARNINGS", confidence=0.9, details={})],
        instruments=[InstrumentMention(ticker="AAPL", name="Apple")],
    )

    old_fp = compute_story_fingerprint(
        tickers=["AAPL"],
        event_type="EARNINGS",
        created_at=last_quarter,
    )
    graph_index.create_node(
        NodeLabel.DOCUMENT,
        "doc-old-quarter",
        {
            "title": "Apple earnings last quarter",
            "language": "en",
            "source_guid": "src-1",
            "group_guid": "group-1",
            "created_at": last_quarter.isoformat(),
            "story_fingerprint": old_fp,
        },
    )

    # Same tickers + event_type, but different date => different fingerprint => not duplicate by fingerprint
    result = detector.check(
        "Apple earnings this quarter",
        "Apple posted results again this quarter.",
        "group-1",
        graph_index=graph_index,
        created_at=now,
        extraction=extraction,
    )

    assert result.is_duplicate is False


def test_embedding_near_duplicate_path_is_used(monkeypatch) -> None:
    detector = DuplicateDetector(similarity_threshold=0.85)

    class _FakeEmbeddingIndex:
        def search(self, query, n_results=10, group_guids=None, include_content=True):
            return [
                SimilarityResult(
                    document_guid="doc-similar",
                    chunk_id="doc-similar_0",
                    content="",
                    score=0.91,
                    metadata={"created_at": datetime.utcnow().isoformat()},
                )
            ]

    result = detector.check(
        "Title A",
        "Some paraphrased content.",
        "group-1",
        embedding_index=_FakeEmbeddingIndex(),
        created_at=datetime.utcnow(),
    )

    assert result.is_duplicate is True
    assert result.duplicate_of == "doc-similar"
    assert result.method == "embedding"
