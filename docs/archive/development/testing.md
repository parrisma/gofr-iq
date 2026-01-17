# Testing Strategy & Guidelines

Comprehensive guide to testing GOFR-IQ components, patterns, and best practices.

---

## Test Overview

### Current Test Suite

```
712 tests
  ├─ 100 passing ✅
  ├─ 612 passing ✅
  ├─ 1 skipped ⏭️
  └─ 0 failing ❌

Coverage: 76%
  ├─ Services: 85%
  ├─ Models: 90%
  ├─ Tools: 70%
  └─ Utilities: 65%
```

### Test Categories

| Category | Tests | Coverage | Purpose |
|----------|-------|----------|---------|
| **Unit** | 400+ | 80% | Individual functions, methods |
| **Integration** | 200+ | 75% | Service interactions |
| **E2E** | 50+ | 60% | Full user workflows |
| **Fixtures** | Setup/teardown | N/A | Test data management |

---

## Test Structure

### Directory Layout

```
test/
├── conftest.py                    # Fixtures, setup/teardown
├── test_ingest_service.py         # Unit: Ingestion
├── test_query_service.py          # Unit: Search
├── test_graph_index.py            # Unit: Neo4j
├── test_embedding_index.py        # Unit: ChromaDB
├── test_document_store.py         # Unit: File storage
├── test_duplicate_detection.py    # Unit: Deduplication
├── test_language_detector.py      # Unit: Language detection
├── test_graph_tools.py            # Integration: Graph operations
├── test_auth_flow_integration.py  # Integration: Auth
├── test_client_tools.py           # Integration: Tools
└── test_articles.py               # E2E: Full workflows
```

### Test File Naming

```python
# test_<component>.py for units
test_ingest_service.py
test_query_service.py
test_graph_index.py

# test_<domain>_integration.py for integrations
test_auth_flow_integration.py
test_ingest_integration.py

# test_<feature>.py for E2E
test_articles.py
test_feeds.py
```

---

## Writing Unit Tests

### Basic Pattern

```python
import pytest
from app.services.ingest_service import IngestService, IngestStatus

class TestIngestService:
    """Unit tests for IngestService."""
    
    @pytest.fixture
    def service(self):
        """Create service with mocked dependencies."""
        return IngestService(
            document_store=MockDocumentStore(),
            source_registry=MockSourceRegistry(),
            language_detector=MockLanguageDetector(),
            duplicate_detector=MockDuplicateDetector()
        )
    
    def test_ingest_success(self, service):
        """Test successful document ingestion."""
        result = service.ingest(
            title="Test Article",
            content="Content here" * 1000,  # >10 words
            source_guid="source-1",
            group_guid="group-1"
        )
        
        assert result.status == IngestStatus.SUCCESS
        assert result.word_count > 0
        assert result.language == "en"
        assert result.guid is not None
    
    def test_ingest_word_count_exceeded(self, service):
        """Test rejection of documents exceeding word limit."""
        with pytest.raises(WordCountError):
            service.ingest(
                title="Too Long",
                content="word " * 25000,  # >20K words
                source_guid="source-1",
                group_guid="group-1"
            )
    
    def test_ingest_duplicate(self, service):
        """Test duplicate detection and storage."""
        # First document
        result1 = service.ingest(
            title="Apple Earnings",
            content="Apple reported Q4 earnings...",
            source_guid="source-1",
            group_guid="group-1"
        )
        
        # Second document (similar)
        result2 = service.ingest(
            title="Apple Q4 Results",
            content="Apple reported quarterly earnings...",
            source_guid="source-1",
            group_guid="group-1"
        )
        
        assert result2.status == IngestStatus.DUPLICATE
        assert result2.duplicate_of == result1.guid
        assert result2.duplicate_score > 0.95
```

### Mocking Pattern

```python
from unittest.mock import Mock, MagicMock

class MockDocumentStore:
    """Mock document storage."""
    
    def __init__(self):
        self.documents = {}
    
    def save(self, document):
        self.documents[document.guid] = document
        return document
    
    def get(self, guid, group_guid):
        return self.documents.get(guid)

# Usage
mock_store = MockDocumentStore()
service = IngestService(document_store=mock_store)
```

---

## Integration Testing

### Pattern: Service-to-Service

```python
class TestIngestIntegration:
    """Integration tests for ingestion with real services."""
    
    @pytest.fixture
    def services(self, tmp_path):
        """Create real services with test databases."""
        document_store = DocumentStore(tmp_path / "documents")
        source_registry = SourceRegistry(tmp_path / "sources")
        embedding_index = EmbeddingIndex()  # Real ChromaDB
        graph_index = GraphIndex()  # Real Neo4j (test container)
        
        ingest_service = IngestService(
            document_store=document_store,
            source_registry=source_registry,
            embedding_index=embedding_index,
            graph_index=graph_index
        )
        
        query_service = QueryService(
            document_store=document_store,
            embedding_index=embedding_index,
            graph_index=graph_index
        )
        
        return {
            "ingest": ingest_service,
            "query": query_service,
            "store": document_store,
            "registry": source_registry
        }
    
    def test_ingest_and_query(self, services):
        """Test end-to-end: ingest, then query."""
        
        # Create source
        source = services["registry"].create(
            guid="source-1",
            name="Reuters",
            region="APAC"
        )
        
        # Ingest document
        ingest_result = services["ingest"].ingest(
            title="Market Analysis",
            content="The markets are..." * 100,
            source_guid=source.guid,
            group_guid="apac-research"
        )
        
        assert ingest_result.is_success
        
        # Query document
        query_results = services["query"].search(
            query="market analysis",
            group_guid="apac-research"
        )
        
        assert len(query_results) > 0
        assert query_results[0].document_guid == ingest_result.guid
```

---

## E2E Testing

### Pattern: Full Workflow

```python
class TestFullWorkflow:
    """End-to-end workflow tests."""
    
    @pytest.fixture
    def app_client(self):
        """Create FastAPI test client."""
        from fastapi.testclient import TestClient
        from app.main import app
        
        return TestClient(app)
    
    def test_full_workflow(self, app_client):
        """Test: ingest document via API, query, verify results."""
        
        # Create JWT token
        token = create_test_token(groups=["apac-research"])
        headers = {"Authorization": f"Bearer {token}"}
        
        # Ingest document via REST API
        ingest_response = app_client.post(
            "/api/v1/ingest",
            json={
                "title": "Apple Q4 Earnings",
                "content": "Apple reported Q4..." * 100,
                "source_guid": "source-1",
                "group_guid": "apac-research"
            },
            headers=headers
        )
        
        assert ingest_response.status_code == 201
        doc_guid = ingest_response.json()["guid"]
        
        # Search for document
        search_response = app_client.get(
            "/api/v1/search",
            params={"query": "Apple earnings"},
            headers=headers
        )
        
        assert search_response.status_code == 200
        results = search_response.json()["results"]
        assert any(r["document_guid"] == doc_guid for r in results)
        
        # Verify impact score was extracted
        assert results[0]["impact_score"] > 0
        assert results[0]["impact_tier"] in ["PLATINUM", "GOLD", "SILVER", "BRONZE"]
```

---

## Test Fixtures

### Common Fixtures (conftest.py)

```python
import pytest
from pathlib import Path

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create temporary data directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "documents").mkdir()
    (data_dir / "sources").mkdir()
    return data_dir

@pytest.fixture
def test_token():
    """Create valid test JWT token."""
    from datetime import datetime, timedelta, timezone
    import jwt
    
    payload = {
        "sub": "test-user",
        "groups": ["apac-research"],
        "scopes": ["read", "write"],
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    }
    
    return jwt.encode(payload, "test-secret", algorithm="HS256")

@pytest.fixture
def sample_document():
    """Sample document for testing."""
    return {
        "title": "Test Article",
        "content": "Content goes here." * 100,
        "source_guid": "source-1",
        "group_guid": "group-1",
        "language": "en"
    }

@pytest.fixture
def cleanup_neo4j():
    """Clean Neo4j between tests."""
    yield
    # Cleanup after test
    # Remove all nodes
```

---

## Parameterized Tests

### Testing Multiple Inputs

```python
import pytest

class TestLanguageDetection:
    """Test language detection with multiple languages."""
    
    @pytest.mark.parametrize("text,expected_lang", [
        ("Hello world, this is English.", "en"),
        ("Bonjour, ceci est français.", "fr"),
        ("你好，这是中文。", "zh"),
        ("こんにちは、これは日本語です。", "ja"),
    ])
    def test_detect_language(self, text, expected_lang):
        """Test detection for multiple languages."""
        detector = LanguageDetector()
        result = detector.detect(text)
        assert result.language == expected_lang
```

---

## Mocking External APIs

### Mocking OpenRouter API

```python
from unittest.mock import patch, Mock

class TestLLMExtraction:
    """Test LLM extraction with mocked API."""
    
    @patch("app.services.llm_service.openrouter_api")
    def test_extract_entities(self, mock_api):
        """Test entity extraction with mocked API."""
        
        # Mock API response
        mock_api.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=json.dumps({
                "primary_event": "earnings_beat",
                "impact_score": 75,
                "impact_tier": "GOLD",
                "instruments": [
                    {"ticker": "AAPL", "direction": "UP", "magnitude": "HIGH"}
                ]
            })))]
        )
        
        # Test
        llm_service = LLMService()
        result = llm_service.extract_entities("Apple reported Q4 earnings...")
        
        assert result.primary_event == "earnings_beat"
        assert result.impact_score == 75
        assert len(result.instruments) == 1
```

---

## Performance Testing

### Benchmarking

```python
import pytest
import time

class TestPerformance:
    """Performance/benchmark tests."""
    
    def test_ingest_throughput(self):
        """Measure ingestion throughput."""
        service = IngestService(...)
        
        start = time.time()
        for i in range(100):
            service.ingest(
                title=f"Article {i}",
                content="Content" * 100,
                source_guid="source-1",
                group_guid="group-1"
            )
        elapsed = time.time() - start
        
        # Should ingest ~100 docs in < 30 seconds (0.3s per doc)
        assert elapsed < 30
        throughput = 100 / elapsed
        print(f"Throughput: {throughput:.1f} docs/sec")
    
    def test_search_latency(self):
        """Measure search latency."""
        service = QueryService(...)
        
        start = time.time()
        results = service.search("test query")
        elapsed = time.time() - start
        
        # Search should be <1 second
        assert elapsed < 1.0
        print(f"Latency: {elapsed*1000:.0f}ms")
```

---

## Test Markers

### Organize Tests by Category

```python
# Mark tests with categories
@pytest.mark.slow
def test_full_workflow():
    """Full workflow (takes >5 seconds)."""
    pass

@pytest.mark.integration
def test_ingest_and_query():
    """Requires real services."""
    pass

@pytest.mark.skip(reason="Not implemented yet")
def test_feature_x():
    pass

# Run specific markers:
# pytest -m "not slow"        # Skip slow tests
# pytest -m integration       # Only integration tests
```

---

## Running Tests

### Run All Tests

```bash
cd /home/gofr/devroot/gofr-iq
source scripts/gofriq.env

# All tests with verbose output
pytest test/ -v

# With coverage report
pytest test/ --cov=app --cov-report=html

# Open coverage report
open htmlcov/index.html
```

### Run Specific Tests

```bash
# Single file
pytest test/test_ingest_service.py -v

# Single test class
pytest test/test_ingest_service.py::TestIngestService -v

# Single test method
pytest test/test_ingest_service.py::TestIngestService::test_ingest_success -v

# By marker
pytest -m integration -v
pytest -m "not slow" -v
```

### Watch Mode

```bash
# Install pytest-watch
pip install pytest-watch

# Auto-rerun tests on file changes
ptw test/ -- -v --tb=short
```

---

## Continuous Integration

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      neo4j:
        image: neo4j:latest
        env:
          NEO4J_AUTH: neo4j/password
      chromadb:
        image: chromadb/chroma:latest
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.12"
      
      - run: pip install -r requirements.txt
      - run: pytest test/ --cov=app
      - run: coverage report
```

---

## Best Practices

### 1. Use Fixtures for Setup

```python
# Good: Reusable, clean
@pytest.fixture
def ingest_service(tmp_path):
    return IngestService(...)

def test_something(ingest_service):
    result = ingest_service.ingest(...)
    assert result.is_success

# Bad: Duplicated setup
def test_something_1():
    service = IngestService(...)
    # ...

def test_something_2():
    service = IngestService(...)  # Duplicated!
    # ...
```

### 2. Test One Thing Per Test

```python
# Good: Single concern
def test_word_count_validation(service):
    with pytest.raises(WordCountError):
        service.ingest(..., content="x" * 25000)

# Bad: Multiple concerns
def test_ingest(service):
    # Tests validation
    # Tests storage
    # Tests indexing
    # Tests deduplication
    # All in one test!
```

### 3. Use Meaningful Names

```python
# Good: Clear what's being tested
def test_duplicate_detection_with_similar_title():
    pass

# Bad: Vague
def test_duplicate():
    pass
```

---

## Related Documentation

- [Configuration Reference](../getting-started/configuration.md)
- [Contributing Guidelines](contributing.md)
- [Code Style Guide](code-style.md)
- [Architecture Overview](../architecture/overview.md)
