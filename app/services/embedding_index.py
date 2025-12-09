"""Embedding Index Service using ChromaDB

Provides semantic embedding storage and similarity search for documents.
Supports chunking for long documents and cross-language search via
multilingual embedding models.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, cast

import chromadb
from chromadb.api.types import Documents, Embeddings
from chromadb.config import Settings as ChromaSettings


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers"""

    def __call__(self, input: Documents) -> Embeddings: ...


class DeterministicEmbeddingFunction:
    """Simple deterministic embedding function for testing

    Generates consistent embeddings based on text hash.
    NOT suitable for production - use a real embedding model.
    
    Implements the ChromaDB EmbeddingFunction interface without
    inheriting to avoid complex generic type issues.
    """

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    @staticmethod
    def is_legacy() -> bool:
        """Return whether this is a legacy embedding function (required by ChromaDB)"""
        return True

    @staticmethod
    def name() -> str:
        """Return the name of this embedding function (required by ChromaDB)"""
        return "deterministic-test"

    def _embed_text(self, text: str) -> list[float]:
        """Generate deterministic embedding from single text"""
        text_str = str(text) if text else ""
        hash_bytes = hashlib.sha256(text_str.encode()).digest()
        embedding: list[float] = []
        for i in range(self.dimensions):
            byte_idx = i % len(hash_bytes)
            value = (hash_bytes[byte_idx] / 255.0) * 2 - 1
            embedding.append(value)
        return embedding

    def __call__(self, input: Documents) -> Embeddings:
        """Generate deterministic embeddings from text (batch)"""
        embeddings: list[list[float]] = []
        for text in input:
            embeddings.append(self._embed_text(str(text) if text else ""))
        return cast(Embeddings, embeddings)

    def embed_documents(self, input: list[str]) -> Embeddings:
        """Embed a list of documents (required by ChromaDB)"""
        return self(cast(Documents, input))

    def embed_query(self, input: str) -> Embeddings:
        """Embed a single query (required by ChromaDB)
        
        Returns a list containing the single query embedding.
        """
        return self(cast(Documents, [input]))


@dataclass
class ChunkConfig:
    """Configuration for document chunking

    Attributes:
        chunk_size: Maximum characters per chunk (default: 1000)
        chunk_overlap: Character overlap between chunks (default: 200)
        min_chunk_size: Minimum chunk size to create (default: 100)
    """

    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_chunk_size: int = 100

    def __post_init__(self) -> None:
        """Validate chunk configuration"""
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        if self.min_chunk_size < 0:
            raise ValueError("min_chunk_size must be non-negative")


@dataclass
class Chunk:
    """A chunk of document content

    Attributes:
        chunk_id: Unique chunk identifier
        document_guid: Parent document GUID
        content: Chunk text content
        chunk_index: Position in document (0-based)
        start_char: Starting character position
        end_char: Ending character position
    """

    chunk_id: str
    document_guid: str
    content: str
    chunk_index: int
    start_char: int
    end_char: int


@dataclass
class SimilarityResult:
    """Result from similarity search

    Attributes:
        document_guid: Document GUID
        chunk_id: Chunk identifier
        content: Chunk content
        score: Similarity score (0-1, higher is more similar)
        metadata: Additional metadata from the chunk
    """

    document_guid: str
    chunk_id: str
    content: str
    score: float
    metadata: dict = field(default_factory=dict)


class EmbeddingIndex:
    """ChromaDB-based embedding index for document storage and search

    Provides:
    - Document embedding with automatic chunking
    - Similarity search across documents
    - Group-based access filtering
    - Cross-language search support (via multilingual model)
    """

    # Default collection name
    DEFAULT_COLLECTION = "documents"

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        collection_name: str = DEFAULT_COLLECTION,
        chunk_config: Optional[ChunkConfig] = None,
        embedding_function: Optional[EmbeddingProvider] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Initialize embedding index

        Args:
            persist_directory: Directory for persistent storage (local mode).
                              If None and no host, uses ephemeral in-memory storage.
            collection_name: Name of the ChromaDB collection
            chunk_config: Configuration for document chunking
            embedding_function: Custom embedding function. If None, uses
                              DeterministicEmbeddingFunction for testing.
                              For production, inject a real embedding model.
            host: ChromaDB server host (HTTP client mode). If provided,
                  persist_directory is ignored.
            port: ChromaDB server port (default: 8000)
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.chunk_config = chunk_config or ChunkConfig()
        self.host = host
        self.port = port or 8000
        
        # Use provided embedding function or default to deterministic (for testing)
        # Note: For HTTP client mode, custom embedding functions must be registered
        # server-side. We only use custom functions for ephemeral/local modes.
        self._embedding_function = embedding_function or DeterministicEmbeddingFunction()

        # Initialize ChromaDB client
        if host:
            # HTTP client mode - connect to ChromaDB server
            self._client = chromadb.HttpClient(
                host=host,
                port=self.port,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            # For HTTP mode, don't pass custom embedding function
            # The server will use its default embedding function
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
            )
        elif persist_directory:
            # Local persistent mode
            persist_directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(persist_directory),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            # Get or create collection with embedding function
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
                embedding_function=cast(Any, self._embedding_function),
            )
        else:
            # Local ephemeral mode
            self._client = chromadb.EphemeralClient(
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            # Get or create collection with embedding function
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
                embedding_function=cast(Any, self._embedding_function),
            )

    @property
    def client(self) -> Any:
        """Get the ChromaDB client"""
        return self._client

    @property
    def collection(self) -> Any:
        """Get the document collection"""
        return self._collection

    def chunk_document(self, document_guid: str, content: str) -> list[Chunk]:
        """Split document content into chunks

        Args:
            document_guid: Document GUID
            content: Full document content

        Returns:
            List of Chunk objects
        """
        chunks: list[Chunk] = []

        # Handle short content that doesn't need chunking
        if len(content) <= self.chunk_config.chunk_size:
            chunk = Chunk(
                chunk_id=f"{document_guid}_0",
                document_guid=document_guid,
                content=content,
                chunk_index=0,
                start_char=0,
                end_char=len(content),
            )
            return [chunk]

        # Split into chunks with overlap
        start = 0
        chunk_index = 0

        while start < len(content):
            end = min(start + self.chunk_config.chunk_size, len(content))

            # Try to break at sentence boundary if not at end
            if end < len(content):
                # Look for sentence endings within last 20% of chunk
                search_start = start + int(self.chunk_config.chunk_size * 0.8)
                search_region = content[search_start:end]

                # Find last sentence boundary
                for boundary in [". ", ".\n", "! ", "!\n", "? ", "?\n"]:
                    last_boundary = search_region.rfind(boundary)
                    if last_boundary != -1:
                        end = search_start + last_boundary + len(boundary)
                        break

            chunk_content = content[start:end].strip()

            # Only create chunk if it meets minimum size
            if len(chunk_content) >= self.chunk_config.min_chunk_size:
                chunk = Chunk(
                    chunk_id=f"{document_guid}_{chunk_index}",
                    document_guid=document_guid,
                    content=chunk_content,
                    chunk_index=chunk_index,
                    start_char=start,
                    end_char=end,
                )
                chunks.append(chunk)
                chunk_index += 1

            # Move start position with overlap
            # Ensure we always advance by at least 1 character to avoid infinite loop
            new_start = end - self.chunk_config.chunk_overlap
            if new_start <= start:
                new_start = start + 1
            start = new_start

            # Break if we've processed all content
            if end >= len(content):
                break

        return chunks

    def embed_document(
        self,
        document_guid: str,
        content: str,
        group_guid: str,
        source_guid: str,
        language: str,
        metadata: Optional[dict] = None,
    ) -> list[str]:
        """Embed a document into the index

        Args:
            document_guid: Unique document identifier
            content: Document text content
            group_guid: Group this document belongs to
            source_guid: Source this document came from
            language: Document language code (e.g., 'en', 'ja')
            metadata: Additional metadata to store

        Returns:
            List of chunk IDs that were created
        """
        # Chunk the document
        chunks = self.chunk_document(document_guid, content)

        # Prepare data for ChromaDB
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = []

        for chunk in chunks:
            chunk_meta = {
                "document_guid": document_guid,
                "group_guid": group_guid,
                "source_guid": source_guid,
                "language": language,
                "chunk_index": chunk.chunk_index,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
            }
            if metadata:
                # Add custom metadata (flatten to strings for ChromaDB)
                for key, value in metadata.items():
                    if isinstance(value, (list, dict)):
                        import json

                        chunk_meta[key] = json.dumps(value)
                    else:
                        chunk_meta[key] = value
            metadatas.append(chunk_meta)

        # Add to collection (upsert to handle re-embedding)
        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        return ids

    def search(
        self,
        query: str,
        n_results: int = 10,
        group_guids: Optional[list[str]] = None,
        source_guids: Optional[list[str]] = None,
        languages: Optional[list[str]] = None,
        include_content: bool = True,
    ) -> list[SimilarityResult]:
        """Search for similar documents

        Args:
            query: Search query text
            n_results: Maximum number of results to return
            group_guids: Filter to specific groups (for access control)
            source_guids: Filter to specific sources
            languages: Filter to specific languages
            include_content: Whether to include chunk content in results

        Returns:
            List of SimilarityResult objects, sorted by similarity
        """
        # Build where clause for filtering
        where_filters: list[dict[str, Any]] = []

        if group_guids:
            where_filters.append({"group_guid": {"$in": group_guids}})

        if source_guids:
            where_filters.append({"source_guid": {"$in": source_guids}})

        if languages:
            where_filters.append({"language": {"$in": languages}})

        # Combine filters
        where: dict[str, Any] | None = None
        if len(where_filters) == 1:
            where = where_filters[0]
        elif len(where_filters) > 1:
            where = {"$and": where_filters}

        # Execute query
        include: list[Any] = ["metadatas", "distances"]
        if include_content:
            include.append("documents")

        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=cast(Any, where),
            include=cast(Any, include),
        )

        # Convert to SimilarityResult objects
        similarity_results: list[SimilarityResult] = []

        if not results["ids"] or not results["ids"][0]:
            return similarity_results

        ids = results["ids"][0]
        distances = results.get("distances")
        distances_list = distances[0] if distances else []
        metadatas = results.get("metadatas")
        metadatas_list = metadatas[0] if metadatas else []
        documents = results.get("documents")
        documents_list = documents[0] if documents else []

        for i, chunk_id in enumerate(ids):
            meta = metadatas_list[i] if i < len(metadatas_list) else {}
            distance = distances_list[i] if i < len(distances_list) else 1.0
            content = documents_list[i] if i < len(documents_list) else ""

            # Convert cosine distance to similarity score (1 - distance)
            # ChromaDB returns distance, we want similarity
            score = 1.0 - float(distance)

            result = SimilarityResult(
                document_guid=str(meta.get("document_guid", "")),
                chunk_id=chunk_id,
                content=str(content) if content else "",
                score=score,
                metadata=dict(meta) if meta else {},
            )
            similarity_results.append(result)

        return similarity_results

    def delete_document(self, document_guid: str) -> int:
        """Delete all chunks for a document

        Args:
            document_guid: Document GUID to delete

        Returns:
            Number of chunks deleted
        """
        # Get chunks for this document
        results = self._collection.get(
            where={"document_guid": document_guid},
            include=[],  # Just need IDs
        )

        if not results["ids"]:
            return 0

        # Delete chunks
        self._collection.delete(ids=results["ids"])
        return len(results["ids"])

    def get_document_chunks(self, document_guid: str) -> list[Chunk]:
        """Get all chunks for a document

        Args:
            document_guid: Document GUID

        Returns:
            List of Chunk objects
        """
        results = self._collection.get(
            where={"document_guid": document_guid},
            include=cast(Any, ["documents", "metadatas"]),
        )

        chunks: list[Chunk] = []
        metadatas = results.get("metadatas") or []
        documents = results.get("documents") or []

        for i, chunk_id in enumerate(results["ids"]):
            meta = dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {}
            content = documents[i] if i < len(documents) else ""

            chunk = Chunk(
                chunk_id=chunk_id,
                document_guid=document_guid,
                content=str(content) if content else "",
                chunk_index=int(cast(int, meta.get("chunk_index", 0))) if meta else 0,
                start_char=int(cast(int, meta.get("start_char", 0))) if meta else 0,
                end_char=int(cast(int, meta.get("end_char", 0))) if meta else 0,
            )
            chunks.append(chunk)

        # Sort by chunk index
        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def count(self, group_guid: Optional[str] = None) -> int:
        """Count chunks in the index

        Args:
            group_guid: Optional group filter

        Returns:
            Number of chunks
        """
        if group_guid:
            results = self._collection.get(
                where={"group_guid": group_guid},
                include=[],
            )
            return len(results["ids"])
        return self._collection.count()

    def clear(self) -> None:
        """Clear all documents from the index"""
        # Delete the collection and recreate it
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=cast(Any, self._embedding_function),
        )

    def __repr__(self) -> str:
        if self.host:
            mode_info = f"http://{self.host}:{self.port}"
        elif self.persist_directory:
            mode_info = f"path={self.persist_directory}"
        else:
            mode_info = "ephemeral"
        return (
            f"EmbeddingIndex({mode_info}, "
            f"collection={self.collection_name}, "
            f"count={self.count()})"
        )


def create_embedding_index(
    persist_directory: Optional[Path] = None,
    collection_name: str = EmbeddingIndex.DEFAULT_COLLECTION,
    chunk_config: Optional[ChunkConfig] = None,
    embedding_function: Optional[EmbeddingProvider] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> EmbeddingIndex:
    """Factory function to create an embedding index

    Args:
        persist_directory: Directory for persistent storage (local mode)
        collection_name: Name of the ChromaDB collection
        chunk_config: Configuration for document chunking
        embedding_function: Custom embedding function for production use
        host: ChromaDB server host (HTTP client mode)
        port: ChromaDB server port (default: 8000)

    Returns:
        Configured EmbeddingIndex instance
    """
    return EmbeddingIndex(
        persist_directory=persist_directory,
        collection_name=collection_name,
        chunk_config=chunk_config,
        embedding_function=embedding_function,
        host=host,
        port=port,
    )
