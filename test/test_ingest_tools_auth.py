"""Authentication tests for Ingest Tools.

Tests ingest_document and validate_document authentication behavior.
"""

import json
from unittest.mock import MagicMock

import pytest

from app.services.group_service import init_group_service
from app.tools.ingest_tools import register_ingest_tools

# Test constants
TEST_SOURCE_GUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
TEST_GROUP_GUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def parse_tool_response(response):
    """Parse MCP tool response to dict."""
    if hasattr(response, "__iter__"):
        for item in response:
            if hasattr(item, "text"):
                return json.loads(item.text)
    return {}


@pytest.fixture
def mock_ingest_service():
    """Mock ingest service for testing."""
    from app.services.ingest_service import IngestResult, IngestStatus
    from app.services.language_detector import LanguageResult
    from app.services.duplicate_detector import DuplicateResult
    from app.models.source import Source, SourceType, TrustLevel
    from datetime import datetime

    service = MagicMock()
    
    # Mock ingest result
    service.ingest.return_value = IngestResult(
        guid="doc-guid-1234",
        status=IngestStatus.SUCCESS,
        language="en",
        language_detected=True,
        word_count=50,
        created_at=datetime.utcnow(),
    )
    
    # Mock source_registry for validate_document
    mock_source = Source(
        source_guid=TEST_SOURCE_GUID,
        group_guid=TEST_GROUP_GUID,
        name="Test Source",
        type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.MEDIUM,
    )
    service.source_registry = MagicMock()
    service.source_registry.get.return_value = mock_source
    
    # Mock language_detector
    service.language_detector = MagicMock()
    service.language_detector.detect.return_value = LanguageResult(
        language="en",
        confidence=0.95,
        detected_code="en",
        is_apac=False,
    )
    
    # Mock duplicate_detector
    service.duplicate_detector = MagicMock()
    service.duplicate_detector.check.return_value = DuplicateResult(
        is_duplicate=False,
        duplicate_of=None,
        score=0.0,
    )
    
    # Mock max_word_count
    service.max_word_count = 20000
    
    return service


@pytest.fixture
def ingest_document_fn(mock_ingest_service):
    """Extract the ingest_document function from registered tools."""
    from mcp.server.fastmcp import FastMCP
    
    server = FastMCP("test-server")
    register_ingest_tools(server, mock_ingest_service)
    
    for tool in server._tool_manager._tools.values():
        if tool.name == "ingest_document":
            return tool.fn
    
    raise RuntimeError("ingest_document tool not found")


@pytest.fixture
def validate_document_fn(mock_ingest_service):
    """Extract the validate_document function from registered tools."""
    from mcp.server.fastmcp import FastMCP
    
    server = FastMCP("test-server")
    register_ingest_tools(server, mock_ingest_service)
    
    for tool in server._tool_manager._tools.values():
        if tool.name == "validate_document":
            return tool.fn
    
    raise RuntimeError("validate_document tool not found")


class TestIngestDocumentAuth:
    """Tests for ingest_document authentication."""

    def test_ingest_document_no_token_fails(self, vault_auth_service, ingest_document_fn, mock_ingest_service):
        """ingest_document fails without authentication token."""
        init_group_service(auth_service=vault_auth_service)
        
        response = ingest_document_fn(
            title="Test Article",
            content="This is test content for the document.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=None,
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED"
        mock_ingest_service.ingest.assert_not_called()

    def test_ingest_document_with_valid_token_succeeds(self, vault_auth_service, ingest_document_fn, mock_ingest_service):
        """ingest_document succeeds with valid authentication token."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = ingest_document_fn(
            title="Test Article",
            content="This is test content for the document.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Authenticated user should be able to ingest, got: {result}"
        mock_ingest_service.ingest.assert_called_once()


class TestValidateDocumentAuth:
    """Tests for validate_document authentication."""

    def test_validate_document_no_token_fails(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document fails without authentication token."""
        init_group_service(auth_service=vault_auth_service)
        
        response = validate_document_fn(
            title="Test Article",
            content="This is test content for the document.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=None,
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED"

    def test_validate_document_with_valid_token_succeeds(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document succeeds with valid authentication token."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = validate_document_fn(
            title="Test Article",
            content="This is test content for the document.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Authenticated user should be able to validate, got: {result}"


class TestValidateDocumentChecks:
    """Tests for validate_document validation checks."""

    def test_validate_document_checks_source(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document verifies source exists."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = validate_document_fn(
            title="Test Article",
            content="This is test content for the document.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("source_valid") is True
        assert data.get("source_name") == "Test Source"
        mock_ingest_service.source_registry.get.assert_called_once()

    def test_validate_document_invalid_source(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document reports invalid source."""
        from app.services.source_registry import SourceNotFoundError
        
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        # Make source lookup fail
        mock_ingest_service.source_registry.get.side_effect = SourceNotFoundError(TEST_SOURCE_GUID)
        
        response = validate_document_fn(
            title="Test Article",
            content="This is test content.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("source_valid") is False
        assert data.get("valid") is False
        assert any("Source not found" in issue for issue in data.get("issues", []))

    def test_validate_document_checks_word_count(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document reports word count."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        content = "This is test content with multiple words for counting."
        
        response = validate_document_fn(
            title="Test Article",
            content=content,
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert "word_count" in data
        assert data.get("word_count") > 0
        assert data.get("word_count_valid") is True

    def test_validate_document_word_count_exceeded(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document reports when word count exceeds limit."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        # Set low word limit
        mock_ingest_service.max_word_count = 5
        
        content = "This is test content with many more words than allowed."
        
        response = validate_document_fn(
            title="Test Article",
            content=content,
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("word_count_valid") is False
        assert data.get("valid") is False
        assert any("Word count exceeds" in issue for issue in data.get("issues", []))

    def test_validate_document_detects_language(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document auto-detects language."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = validate_document_fn(
            title="Test Article",
            content="This is English content.",
            source_guid=TEST_SOURCE_GUID,
            language=None,  # Auto-detect
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("language") == "en"
        assert data.get("language_confidence") == 0.95
        assert data.get("language_provided") is False
        mock_ingest_service.language_detector.detect.assert_called_once()

    def test_validate_document_uses_provided_language(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document uses provided language without detection."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = validate_document_fn(
            title="Test Article",
            content="This is content.",
            source_guid=TEST_SOURCE_GUID,
            language="zh",  # Explicitly provided
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("language") == "zh"
        assert data.get("language_confidence") == 1.0
        assert data.get("language_provided") is True
        # Detector should not be called when language is provided
        mock_ingest_service.language_detector.detect.assert_not_called()

    def test_validate_document_checks_duplicates(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document checks for duplicates."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = validate_document_fn(
            title="Test Article",
            content="This is test content.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("is_duplicate") is False
        mock_ingest_service.duplicate_detector.check.assert_called_once()

    def test_validate_document_reports_duplicate(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document reports when document is duplicate."""
        from app.services.duplicate_detector import DuplicateResult
        
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        # Make duplicate check return a match
        mock_ingest_service.duplicate_detector.check.return_value = DuplicateResult(
            is_duplicate=True,
            duplicate_of="original-doc-guid",
            score=0.95,
        )
        
        response = validate_document_fn(
            title="Duplicate Article",
            content="This is duplicate content.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        data = result.get("data", {})
        
        assert data.get("is_duplicate") is True
        assert data.get("duplicate_of") == "original-doc-guid"
        assert data.get("duplicate_score") == 0.95
        # Duplicate is a warning, not an error - document is still valid
        assert data.get("valid") is True
        assert any("duplicate" in issue.lower() for issue in data.get("issues", []))

    def test_validate_document_does_not_store(self, vault_auth_service, validate_document_fn, mock_ingest_service):
        """validate_document does not store the document."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        validate_document_fn(
            title="Test Article",
            content="This is test content.",
            source_guid=TEST_SOURCE_GUID,
            auth_tokens=[token],
        )
        
        # Verify ingest was NOT called
        mock_ingest_service.ingest.assert_not_called()


class TestIngestToolsRegistration:
    """Tests that all ingest tools are properly registered."""

    def test_all_ingest_tools_registered(self, mock_ingest_service):
        """Verify both ingest tools are registered."""
        from mcp.server.fastmcp import FastMCP
        
        server = FastMCP("test-server")
        register_ingest_tools(server, mock_ingest_service)
        
        tool_names = [tool.name for tool in server._tool_manager._tools.values()]
        
        expected_tools = [
            "ingest_document",
            "validate_document",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Tool '{tool_name}' not registered"
        
        assert len([t for t in tool_names if t in expected_tools]) == 2
