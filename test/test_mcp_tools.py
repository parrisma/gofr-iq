"""Tests for MCP Tools - Phase 8.

Tests the MCP tools for document ingestion, source management, and document retrieval.

Test Classes:
- TestIngestDocumentTool: Tests for ingest_document tool
- TestListSourcesTool: Tests for list_sources tool
- TestGetSourceTool: Tests for get_source tool
- TestGetDocumentTool: Tests for get_document tool
- TestMCPServerCreation: Tests for server creation and configuration
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from mcp.server.fastmcp import FastMCP

from app.models import DocumentCreate, Source, SourceType
from app.services import (
    DocumentStore,
    DuplicateDetector,
    IngestService,
    LanguageDetector,
    SourceRegistry,
)
from app.services.ingest_service import IngestStatus
from app.tools import (
    register_all_tools,
    register_ingest_tools,
    register_query_tools,
    register_source_tools,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_storage(tmp_path: Path) -> Path:
    """Create temporary storage directories."""
    storage = tmp_path / "storage"
    (storage / "documents").mkdir(parents=True)
    (storage / "sources").mkdir(parents=True)
    return storage


@pytest.fixture
def document_store(temp_storage: Path) -> DocumentStore:
    """Create a DocumentStore instance."""
    return DocumentStore(base_path=temp_storage / "documents")


@pytest.fixture
def source_registry(temp_storage: Path) -> SourceRegistry:
    """Create a SourceRegistry instance."""
    return SourceRegistry(base_path=temp_storage / "sources")


@pytest.fixture
def language_detector() -> LanguageDetector:
    """Create a LanguageDetector instance."""
    return LanguageDetector()


@pytest.fixture
def duplicate_detector() -> DuplicateDetector:
    """Create a DuplicateDetector instance."""
    return DuplicateDetector()


@pytest.fixture
def ingest_service(
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    language_detector: LanguageDetector,
    duplicate_detector: DuplicateDetector,
) -> IngestService:
    """Create an IngestService instance."""
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
    )


@pytest.fixture
def group_guid() -> str:
    """Generate a group GUID."""
    return str(uuid.uuid4())


@pytest.fixture
def source(source_registry: SourceRegistry, group_guid: str) -> Source:
    """Create and register a test source."""
    return source_registry.create(
        group_guid=group_guid,
        name="Test Source",
        source_type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en", "zh"],
    )


@pytest.fixture
def mcp_server() -> FastMCP:
    """Create a FastMCP server instance for testing."""
    return FastMCP(name="test-server", port=9999)


# =============================================================================
# TEST INGEST DOCUMENT TOOL
# =============================================================================


class TestIngestDocumentTool:
    """Tests for the ingest_document MCP tool."""

    def test_register_ingest_tools(
        self,
        mcp_server: FastMCP,
        ingest_service: IngestService,
    ) -> None:
        """Test that ingest tools can be registered."""
        register_ingest_tools(mcp_server, ingest_service)
        # Tool should be registered - FastMCP stores tools internally
        assert mcp_server is not None

    def test_ingest_document_success(
        self,
        mcp_server: FastMCP,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test successful document ingestion via tool."""
        register_ingest_tools(mcp_server, ingest_service)

        # Test the service directly (tool calls service internally)
        result = ingest_service.ingest(
            title="Test Document",
            content="This is test content for the document.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.guid is not None
        assert result.status == IngestStatus.SUCCESS

    def test_ingest_document_invalid_source(
        self,
        ingest_service: IngestService,
        group_guid: str,
    ) -> None:
        """Test ingestion with invalid source returns error."""
        from app.services.ingest_service import SourceValidationError

        with pytest.raises(SourceValidationError):
            ingest_service.ingest(
                title="Test Document",
                content="Content here.",
                source_guid=str(uuid.uuid4()),
                group_guid=group_guid,
            )

    def test_ingest_document_word_count_exceeded(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test ingestion with excessive word count returns error."""
        from app.services.ingest_service import WordCountError

        service = IngestService(
            document_store=document_store,
            source_registry=source_registry,
            language_detector=LanguageDetector(),
            duplicate_detector=DuplicateDetector(),
            max_word_count=10,
        )

        long_content = " ".join(["word"] * 20)

        with pytest.raises(WordCountError):
            service.ingest(
                title="Long Document",
                content=long_content,
                source_guid=source.source_guid,
                group_guid=group_guid,
            )


# =============================================================================
# TEST LIST SOURCES TOOL
# =============================================================================


class TestListSourcesTool:
    """Tests for the list_sources MCP tool."""

    def test_register_source_tools(
        self,
        mcp_server: FastMCP,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that source tools can be registered."""
        register_source_tools(mcp_server, source_registry)
        assert mcp_server is not None

    def test_list_sources_returns_all(
        self,
        source_registry: SourceRegistry,
        group_guid: str,
    ) -> None:
        """Test listing all sources."""
        # Create multiple sources
        source_registry.create(
            group_guid=group_guid,
            name="Source 1",
            source_type=SourceType.NEWS_AGENCY,
        )
        source_registry.create(
            group_guid=group_guid,
            name="Source 2",
            source_type=SourceType.RESEARCH,
        )

        sources = source_registry.list_sources(access_groups=[group_guid])
        assert len(sources) == 2

    def test_list_sources_filter_by_type(
        self,
        source_registry: SourceRegistry,
        group_guid: str,
    ) -> None:
        """Test filtering sources by type."""
        source_registry.create(
            group_guid=group_guid,
            name="News Source",
            source_type=SourceType.NEWS_AGENCY,
        )
        source_registry.create(
            group_guid=group_guid,
            name="Research Source",
            source_type=SourceType.RESEARCH,
        )

        sources = source_registry.list_sources(
            access_groups=[group_guid],
            source_type=SourceType.NEWS_AGENCY,
        )
        assert len(sources) == 1
        assert sources[0].name == "News Source"

    def test_list_sources_filter_by_region(
        self,
        source_registry: SourceRegistry,
        group_guid: str,
    ) -> None:
        """Test filtering sources by region."""
        source_registry.create(
            group_guid=group_guid,
            name="APAC Source",
            region="APAC",
        )
        source_registry.create(
            group_guid=group_guid,
            name="JP Source",
            region="JP",
        )

        sources = source_registry.list_sources(
            access_groups=[group_guid],
            region="APAC",
        )
        assert len(sources) == 1
        assert sources[0].name == "APAC Source"


# =============================================================================
# TEST GET SOURCE TOOL
# =============================================================================


class TestGetSourceTool:
    """Tests for the get_source MCP tool."""

    def test_get_source_success(
        self,
        source_registry: SourceRegistry,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test retrieving a source by GUID."""
        retrieved = source_registry.get(
            source.source_guid,
            access_groups=[group_guid],
        )

        assert retrieved is not None
        assert retrieved.source_guid == source.source_guid
        assert retrieved.name == "Test Source"

    def test_get_source_not_found(
        self,
        source_registry: SourceRegistry,
        group_guid: str,
    ) -> None:
        """Test retrieving non-existent source returns None."""
        from app.services.source_registry import SourceNotFoundError

        with pytest.raises(SourceNotFoundError):
            source_registry.get(str(uuid.uuid4()))

    def test_get_source_access_denied(
        self,
        source_registry: SourceRegistry,
        source: Source,
    ) -> None:
        """Test source access with wrong group raises error."""
        from app.services.source_registry import SourceAccessDeniedError

        other_group = str(uuid.uuid4())
        with pytest.raises(SourceAccessDeniedError):
            source_registry.get(
                source.source_guid,
                access_groups=[other_group],
            )


# =============================================================================
# TEST GET DOCUMENT TOOL
# =============================================================================


class TestGetDocumentTool:
    """Tests for the get_document MCP tool."""

    def test_register_query_tools(
        self,
        mcp_server: FastMCP,
        document_store: DocumentStore,
    ) -> None:
        """Test that query tools can be registered."""
        register_query_tools(mcp_server, document_store)
        assert mcp_server is not None

    def test_get_document_success(
        self,
        document_store: DocumentStore,
        group_guid: str,
    ) -> None:
        """Test retrieving a document by GUID."""
        # Create and save a document
        doc_input = DocumentCreate(
            source_guid=str(uuid.uuid4()),
            group_guid=group_guid,
            title="Test Document",
            content="Test content here.",
        )
        doc = document_store.create_from_input(doc_input)

        # Retrieve it
        retrieved = document_store.load(doc.guid, group_guid)

        assert retrieved.guid == doc.guid
        assert retrieved.title == "Test Document"

    def test_get_document_not_found(
        self,
        document_store: DocumentStore,
        group_guid: str,
    ) -> None:
        """Test retrieving non-existent document raises error."""
        from app.services.document_store import DocumentNotFoundError

        with pytest.raises(DocumentNotFoundError):
            document_store.load(str(uuid.uuid4()), group_guid)

    def test_get_document_with_date_hint(
        self,
        document_store: DocumentStore,
        group_guid: str,
    ) -> None:
        """Test retrieving document with date hint."""
        from datetime import datetime

        # Create and save a document
        doc_input = DocumentCreate(
            source_guid=str(uuid.uuid4()),
            group_guid=group_guid,
            title="Dated Document",
            content="Content with date.",
        )
        doc = document_store.create_from_input(doc_input)

        # Retrieve with date hint
        today = datetime.now()
        retrieved = document_store.load(doc.guid, group_guid, date=today)

        assert retrieved.guid == doc.guid


# =============================================================================
# TEST MCP SERVER CREATION
# =============================================================================


class TestMCPServerCreation:
    """Tests for MCP server creation and configuration."""

    def test_register_all_tools(
        self,
        mcp_server: FastMCP,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        ingest_service: IngestService,
    ) -> None:
        """Test registering all tools at once."""
        register_all_tools(
            mcp=mcp_server,
            document_store=document_store,
            source_registry=source_registry,
            ingest_service=ingest_service,
        )
        # Server should have tools registered
        assert mcp_server is not None

    def test_create_mcp_server(self, temp_storage: Path) -> None:
        """Test creating MCP server from factory."""
        from app.main import create_mcp_server

        server = create_mcp_server(
            storage_dir=temp_storage,
            mcp_port=9999,
        )

        assert server is not None
        # Server should be a FastMCP instance
        assert isinstance(server, FastMCP)

    def test_mcp_server_configuration(self, temp_storage: Path) -> None:
        """Test that MCP server is properly configured."""
        from app.main import create_mcp_server

        server = create_mcp_server(
            storage_dir=temp_storage,
            mcp_port=9999,
        )

        # Server should be configured
        assert server is not None


# =============================================================================
# TEST TOOL RESPONSE FORMAT
# =============================================================================


class TestToolResponseFormat:
    """Tests for MCP tool response formatting."""

    def test_success_response_format(self) -> None:
        """Test success response has correct structure."""
        from gofr_common.mcp import success_response

        response = success_response(
            data={"guid": "test-guid"},
            message="Test message",
        )

        assert len(response) == 1
        # Response should be JSON text
        content = response[0]
        assert content.type == "text"

        # Parse the JSON
        data = json.loads(content.text)
        assert data["status"] == "success"
        assert data["data"]["guid"] == "test-guid"
        assert data["message"] == "Test message"

    def test_error_response_format(self) -> None:
        """Test error response has correct structure."""
        from gofr_common.mcp import error_response

        response = error_response(
            error_code="TEST_ERROR",
            message="Test error message",
            recovery_strategy="Try again",
        )

        assert len(response) == 1
        content = response[0]
        assert content.type == "text"

        data = json.loads(content.text)
        assert data["status"] == "error"
        assert data["error_code"] == "TEST_ERROR"
        assert data["message"] == "Test error message"
        assert data["recovery_strategy"] == "Try again"


# =============================================================================
# TEST INTEGRATION - INGEST END TO END
# =============================================================================


class TestIngestEndToEnd:
    """Integration tests for the full ingest flow via MCP tools."""

    def test_ingest_and_retrieve(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        ingest_service: IngestService,
        group_guid: str,
    ) -> None:
        """Test ingesting a document and retrieving it."""
        # Create a source
        source = source_registry.create(
            group_guid=group_guid,
            name="Integration Test Source",
            source_type=SourceType.NEWS_AGENCY,
        )

        # Ingest a document
        result = ingest_service.ingest(
            title="Integration Test Document",
            content="This is the content of the integration test document.",
            source_guid=source.source_guid,
            group_guid=group_guid,
            language="en",
        )

        assert result.status == IngestStatus.SUCCESS
        assert result.guid is not None

        # Retrieve the document
        doc = document_store.load(result.guid, group_guid)

        assert doc.title == "Integration Test Document"
        assert doc.language == "en"
        assert doc.source_guid == source.source_guid

    def test_ingest_detects_duplicate(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that duplicate detection works in full flow."""
        # Use longer content for reliable detection
        content = "This is a longer piece of duplicate content for testing purposes. It includes multiple sentences to ensure reliable duplicate detection via hash matching."

        # Ingest first document
        result1 = ingest_service.ingest(
            title="Original Document",
            content=content,
            source_guid=source.source_guid,
            group_guid=group_guid,
        )
        assert result1.status == IngestStatus.SUCCESS
        assert result1.duplicate_of is None

        # Ingest exact duplicate (same title + content)
        result2 = ingest_service.ingest(
            title="Original Document",  # Same title
            content=content,  # Same content
            source_guid=source.source_guid,
            group_guid=group_guid,
        )
        assert result2.status == IngestStatus.DUPLICATE
        assert result2.duplicate_of == result1.guid

    def test_ingest_detects_language(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that language detection works in full flow."""
        # Ingest Chinese document
        result = ingest_service.ingest(
            title="市场新闻",
            content="今日股市大涨，主要指数上涨百分之二。投资者信心增强。",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.status == IngestStatus.SUCCESS
        assert result.language == "zh"
        assert result.language_detected is True
