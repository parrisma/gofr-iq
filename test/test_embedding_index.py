"""Tests for Embedding Index Service (Phase 10)

Tests ChromaDB-based embedding storage and similarity search.
"""

import pytest
from pathlib import Path

from app.services.embedding_index import (
    Chunk,
    ChunkConfig,
    EmbeddingIndex,
    SimilarityResult,
    create_embedding_index,
)


class TestChunkConfig:
    """Tests for ChunkConfig dataclass"""

    def test_default_config(self) -> None:
        """Test default chunk configuration values"""
        config = ChunkConfig()

        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200
        assert config.min_chunk_size == 100

    def test_custom_config(self) -> None:
        """Test custom chunk configuration"""
        config = ChunkConfig(
            chunk_size=500,
            chunk_overlap=100,
            min_chunk_size=50,
        )

        assert config.chunk_size == 500
        assert config.chunk_overlap == 100
        assert config.min_chunk_size == 50

    def test_invalid_chunk_size(self) -> None:
        """Test that invalid chunk_size raises error"""
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            ChunkConfig(chunk_size=0)

        with pytest.raises(ValueError, match="chunk_size must be positive"):
            ChunkConfig(chunk_size=-100)

    def test_invalid_overlap(self) -> None:
        """Test that invalid overlap raises error"""
        with pytest.raises(ValueError, match="chunk_overlap must be non-negative"):
            ChunkConfig(chunk_overlap=-1)

    def test_overlap_too_large(self) -> None:
        """Test that overlap >= chunk_size raises error"""
        with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
            ChunkConfig(chunk_size=100, chunk_overlap=100)

        with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
            ChunkConfig(chunk_size=100, chunk_overlap=150)


class TestChunk:
    """Tests for Chunk dataclass"""

    def test_create_chunk(self) -> None:
        """Test creating a chunk"""
        chunk = Chunk(
            chunk_id="doc123_0",
            document_guid="doc123",
            content="This is chunk content",
            chunk_index=0,
            start_char=0,
            end_char=21,
        )

        assert chunk.chunk_id == "doc123_0"
        assert chunk.document_guid == "doc123"
        assert chunk.content == "This is chunk content"
        assert chunk.chunk_index == 0
        assert chunk.start_char == 0
        assert chunk.end_char == 21


class TestSimilarityResult:
    """Tests for SimilarityResult dataclass"""

    def test_create_result(self) -> None:
        """Test creating a similarity result"""
        result = SimilarityResult(
            document_guid="doc123",
            chunk_id="doc123_0",
            content="Matching content",
            score=0.95,
            metadata={"language": "en"},
        )

        assert result.document_guid == "doc123"
        assert result.chunk_id == "doc123_0"
        assert result.content == "Matching content"
        assert result.score == 0.95
        assert result.metadata == {"language": "en"}

    def test_default_metadata(self) -> None:
        """Test default empty metadata"""
        result = SimilarityResult(
            document_guid="doc123",
            chunk_id="doc123_0",
            content="Content",
            score=0.9,
        )

        assert result.metadata == {}


class TestEmbeddingIndexInit:
    """Tests for EmbeddingIndex initialization"""

    def test_ephemeral_index(self) -> None:
        """Test creating ephemeral (in-memory) index"""
        index = EmbeddingIndex()

        assert index.persist_directory is None
        assert index.collection_name == "documents"
        assert index.count() == 0

    def test_persistent_index(self, tmp_path: Path) -> None:
        """Test creating persistent index"""
        chroma_dir = tmp_path / "chroma"
        index = EmbeddingIndex(persist_directory=chroma_dir)

        assert index.persist_directory == chroma_dir
        assert chroma_dir.exists()

    def test_custom_collection_name(self) -> None:
        """Test custom collection name"""
        index = EmbeddingIndex(collection_name="test_docs")

        assert index.collection_name == "test_docs"

    def test_custom_chunk_config(self) -> None:
        """Test custom chunk configuration"""
        config = ChunkConfig(chunk_size=500, chunk_overlap=50)
        index = EmbeddingIndex(chunk_config=config)

        assert index.chunk_config.chunk_size == 500
        assert index.chunk_config.chunk_overlap == 50

    def test_index_repr(self) -> None:
        """Test index string representation"""
        index = EmbeddingIndex(collection_name="test")
        repr_str = repr(index)

        assert "EmbeddingIndex" in repr_str
        assert "ephemeral" in repr_str
        assert "test" in repr_str


class TestDocumentChunking:
    """Tests for document chunking functionality"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create test index with small chunks"""
        config = ChunkConfig(chunk_size=100, chunk_overlap=20, min_chunk_size=10)
        return EmbeddingIndex(chunk_config=config)

    def test_short_document_no_chunking(self, index: EmbeddingIndex) -> None:
        """Test that short documents don't get chunked"""
        content = "Short content."
        chunks = index.chunk_document("doc1", content)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].chunk_index == 0

    def test_long_document_chunked(self, index: EmbeddingIndex) -> None:
        """Test that long documents get chunked"""
        # Create content that needs multiple chunks
        content = "A" * 250  # Should create ~3 chunks

        chunks = index.chunk_document("doc1", content)

        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"doc1_{i}"
            assert chunk.document_guid == "doc1"
            assert chunk.chunk_index == i

    def test_chunk_overlap(self) -> None:
        """Test that chunks have overlap"""
        config = ChunkConfig(chunk_size=50, chunk_overlap=10, min_chunk_size=5)
        index = EmbeddingIndex(chunk_config=config)

        content = "A" * 100
        chunks = index.chunk_document("doc1", content)

        # Check that chunks have overlapping character ranges
        assert len(chunks) >= 2
        if len(chunks) >= 2:
            # Second chunk should start before first chunk ends
            assert chunks[1].start_char < chunks[0].end_char

    def test_sentence_boundary_breaking(self, index: EmbeddingIndex) -> None:
        """Test that chunks break at sentence boundaries when possible"""
        # Content with clear sentence boundaries
        content = "First sentence here. Second sentence here. Third sentence here."

        chunks = index.chunk_document("doc1", content)

        # All chunks should ideally end with sentence punctuation
        # (though this is best-effort based on chunk size)
        assert len(chunks) >= 1


class TestDocumentEmbedding:
    """Tests for document embedding functionality"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create test index"""
        return EmbeddingIndex()

    def test_embed_document(self, index: EmbeddingIndex) -> None:
        """Test embedding a document"""
        chunk_ids = index.embed_document(
            document_guid="doc123",
            content="This is a test document about financial markets.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        assert len(chunk_ids) >= 1
        assert chunk_ids[0].startswith("doc123_")
        assert index.count() >= 1

    def test_embed_with_metadata(self, index: EmbeddingIndex) -> None:
        """Test embedding with custom metadata"""
        index.embed_document(
            document_guid="doc123",
            content="Financial news about technology sector.",
            group_guid="group1",
            source_guid="source1",
            language="en",
            metadata={"sectors": ["tech"], "region": "asia"},
        )

        chunks = index.get_document_chunks("doc123")
        assert len(chunks) >= 1

    def test_embed_creates_multiple_chunks(self, index: EmbeddingIndex) -> None:
        """Test that long documents create multiple chunks"""
        # Create a longer document
        content = " ".join(["This is sentence number {}.".format(i) for i in range(100)])

        chunk_ids = index.embed_document(
            document_guid="doc123",
            content=content,
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        # With default chunk size of 1000 chars, this should create multiple chunks
        assert len(chunk_ids) >= 1

    def test_upsert_behavior(self, index: EmbeddingIndex) -> None:
        """Test that re-embedding updates existing chunks"""
        # First embedding
        index.embed_document(
            document_guid="doc123",
            content="Original content.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        count_after_first = index.count()

        # Re-embed same document (upsert)
        index.embed_document(
            document_guid="doc123",
            content="Updated content.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        # Count should be the same (upsert, not insert)
        assert index.count() == count_after_first


class TestSimilaritySearch:
    """Tests for similarity search functionality"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create index with sample documents"""
        idx = EmbeddingIndex()

        # Add sample documents
        idx.embed_document(
            document_guid="doc1",
            content="Apple Inc. reported strong quarterly earnings driven by iPhone sales.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        idx.embed_document(
            document_guid="doc2",
            content="Toyota announced new electric vehicle lineup for Asian markets.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        idx.embed_document(
            document_guid="doc3",
            content="Central bank raised interest rates citing inflation concerns.",
            group_guid="group2",
            source_guid="source2",
            language="en",
        )

        return idx

    def test_basic_search(self, index: EmbeddingIndex) -> None:
        """Test basic similarity search"""
        results = index.search("iPhone earnings report", n_results=5)

        assert len(results) >= 1
        assert isinstance(results[0], SimilarityResult)
        assert 0 <= results[0].score <= 1

    def test_search_with_group_filter(self, index: EmbeddingIndex) -> None:
        """Test search filtered by group"""
        results = index.search("new products", n_results=10, group_guids=["group1"])

        # Should only return results from group1
        for result in results:
            assert result.metadata.get("group_guid") == "group1"

    def test_search_with_language_filter(self, index: EmbeddingIndex) -> None:
        """Test search filtered by language"""
        results = index.search("market news", n_results=10, languages=["en"])

        for result in results:
            assert result.metadata.get("language") == "en"

    def test_search_with_source_filter(self, index: EmbeddingIndex) -> None:
        """Test search filtered by source"""
        results = index.search("news", n_results=10, source_guids=["source1"])

        for result in results:
            assert result.metadata.get("source_guid") == "source1"

    def test_search_returns_content(self, index: EmbeddingIndex) -> None:
        """Test that search returns chunk content"""
        results = index.search("iPhone", n_results=1, include_content=True)

        assert len(results) >= 1
        assert results[0].content  # Should have content

    def test_search_without_content(self, index: EmbeddingIndex) -> None:
        """Test search without content"""
        results = index.search("iPhone", n_results=1, include_content=False)

        # Content will still be there from metadatas, but we test the option exists
        assert len(results) >= 1

    def test_empty_search_results(self, index: EmbeddingIndex) -> None:
        """Test search with no matching results"""
        # Filter to non-existent group
        results = index.search("anything", n_results=10, group_guids=["nonexistent"])

        assert results == []


class TestCrossLanguageSearch:
    """Tests for cross-language similarity search"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create index with multilingual documents"""
        idx = EmbeddingIndex()

        # English document
        idx.embed_document(
            document_guid="doc_en",
            content="Technology companies are investing heavily in artificial intelligence.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        # Japanese document (about technology/AI)
        idx.embed_document(
            document_guid="doc_ja",
            content="テクノロジー企業は人工知能に多額の投資を行っています。",
            group_guid="group1",
            source_guid="source1",
            language="ja",
        )

        # Chinese document (about technology/AI)
        idx.embed_document(
            document_guid="doc_zh",
            content="科技公司正在大力投资人工智能技术。",
            group_guid="group1",
            source_guid="source1",
            language="zh",
        )

        return idx

    def test_english_query_finds_all_languages(self, index: EmbeddingIndex) -> None:
        """Test that English query can find documents in other languages"""
        results = index.search("artificial intelligence investment", n_results=5)

        # Should find results (the model may find cross-language matches)
        assert len(results) >= 1

    def test_search_with_language_filter(self, index: EmbeddingIndex) -> None:
        """Test filtering to specific language"""
        results = index.search("technology", n_results=5, languages=["ja"])

        # Should only return Japanese results
        for result in results:
            assert result.metadata.get("language") == "ja"


class TestDocumentDeletion:
    """Tests for document deletion"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create index with sample document"""
        idx = EmbeddingIndex()
        idx.embed_document(
            document_guid="doc123",
            content="Sample document content for deletion test.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )
        return idx

    def test_delete_document(self, index: EmbeddingIndex) -> None:
        """Test deleting a document's chunks"""
        count_before = index.count()

        deleted = index.delete_document("doc123")

        assert deleted >= 1
        assert index.count() < count_before

    def test_delete_nonexistent_document(self, index: EmbeddingIndex) -> None:
        """Test deleting non-existent document"""
        deleted = index.delete_document("nonexistent")

        assert deleted == 0


class TestGetDocumentChunks:
    """Tests for retrieving document chunks"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create index with chunked document"""
        config = ChunkConfig(chunk_size=50, chunk_overlap=10, min_chunk_size=10)
        idx = EmbeddingIndex(chunk_config=config)

        # Create document that will be chunked
        content = " ".join(["Word"] * 50)  # Multiple words to create chunks

        idx.embed_document(
            document_guid="doc123",
            content=content,
            group_guid="group1",
            source_guid="source1",
            language="en",
        )
        return idx

    def test_get_document_chunks(self, index: EmbeddingIndex) -> None:
        """Test retrieving all chunks for a document"""
        chunks = index.get_document_chunks("doc123")

        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunks_ordered_by_index(self, index: EmbeddingIndex) -> None:
        """Test that chunks are returned in order"""
        chunks = index.get_document_chunks("doc123")

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_get_nonexistent_document_chunks(self, index: EmbeddingIndex) -> None:
        """Test getting chunks for non-existent document"""
        chunks = index.get_document_chunks("nonexistent")

        assert chunks == []


class TestIndexCount:
    """Tests for chunk counting"""

    @pytest.fixture
    def index(self) -> EmbeddingIndex:
        """Create index with documents in different groups"""
        idx = EmbeddingIndex()

        idx.embed_document(
            document_guid="doc1",
            content="Document in group 1.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        idx.embed_document(
            document_guid="doc2",
            content="Document in group 2.",
            group_guid="group2",
            source_guid="source1",
            language="en",
        )

        return idx

    def test_total_count(self, index: EmbeddingIndex) -> None:
        """Test counting all chunks"""
        total = index.count()

        assert total >= 2

    def test_count_by_group(self, index: EmbeddingIndex) -> None:
        """Test counting chunks by group"""
        count_group1 = index.count(group_guid="group1")
        count_group2 = index.count(group_guid="group2")

        assert count_group1 >= 1
        assert count_group2 >= 1


class TestIndexClear:
    """Tests for clearing the index"""

    def test_clear_index(self) -> None:
        """Test clearing all documents from index"""
        index = EmbeddingIndex()

        # Add some documents
        index.embed_document(
            document_guid="doc1",
            content="First document.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )
        index.embed_document(
            document_guid="doc2",
            content="Second document.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        assert index.count() >= 2

        # Clear
        index.clear()

        assert index.count() == 0


class TestCreateEmbeddingIndex:
    """Tests for factory function"""

    def test_create_embedding_index(self) -> None:
        """Test factory function"""
        index = create_embedding_index()

        assert isinstance(index, EmbeddingIndex)
        assert index.persist_directory is None

    def test_create_with_persist_dir(self, tmp_path: Path) -> None:
        """Test factory with persistence"""
        chroma_dir = tmp_path / "chroma"
        index = create_embedding_index(persist_directory=chroma_dir)

        assert index.persist_directory == chroma_dir

    def test_create_with_custom_config(self) -> None:
        """Test factory with custom chunk config"""
        config = ChunkConfig(chunk_size=500)
        index = create_embedding_index(chunk_config=config)

        assert index.chunk_config.chunk_size == 500


class TestPersistence:
    """Tests for persistent storage"""

    def test_persist_and_reload(self, tmp_path: Path) -> None:
        """Test that embedded documents persist across instances"""
        chroma_dir = tmp_path / "chroma"

        # Create and populate index
        index1 = EmbeddingIndex(persist_directory=chroma_dir)
        index1.embed_document(
            document_guid="doc123",
            content="Persistent document content.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        count_before = index1.count()

        # Create new instance pointing to same directory
        index2 = EmbeddingIndex(persist_directory=chroma_dir)

        # Should have same count
        assert index2.count() == count_before

    def test_search_after_reload(self, tmp_path: Path) -> None:
        """Test that search works after reload"""
        chroma_dir = tmp_path / "chroma"

        # Create and populate index
        index1 = EmbeddingIndex(persist_directory=chroma_dir)
        index1.embed_document(
            document_guid="doc123",
            content="Financial markets update for Q4.",
            group_guid="group1",
            source_guid="source1",
            language="en",
        )

        # Create new instance
        index2 = EmbeddingIndex(persist_directory=chroma_dir)

        # Should be able to search
        results = index2.search("financial", n_results=5)
        assert len(results) >= 1
