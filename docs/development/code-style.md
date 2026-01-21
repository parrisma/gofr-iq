# Code Style & Standards

Coding standards, conventions, and best practices for GOFR-IQ.

---

## Python Version & Dependencies

### Language Version

```python
# GOFR-IQ requires Python 3.12+
# Type hints are mandatory
# Use Python 3.12+ syntax (match statements, type unions, etc.)

from __future__ import annotations
from typing import Optional, Union
from dataclasses import dataclass
from enum import Enum

# Good: Use | for union types (3.12+)
def process(value: str | None = None) -> list[str] | None:
    pass

# Avoid: Old-style Union (pre-3.10)
from typing import Union
def process(value: Union[str, None] = None) -> Optional[list[str]]:
    pass
```

### Dependency Management

```bash
# Pin exact versions in requirements.txt
# Use conservative ranges for new dependencies

neo4j==5.15.0
chromadb==0.5.23
fastapi==0.109.1
pydantic==2.6.1

# Allow patch versions in constraints
fastapi>=0.100.0,<1.0.0
```

---

## Code Formatting

### Black Configuration

```bash
# Auto-format all code
black .

# Check without modifying
black --check .

# Configuration in pyproject.toml
[tool.black]
line-length = 100
target-version = ['py312']
```

### Import Sorting

```python
# Use isort for import organization
# Standard library
import os
import sys
from datetime import datetime
from pathlib import Path

# Third-party
import pytest
from pydantic import BaseModel

# Local
from app.models import Document
from app.services import IngestService

# Configuration in pyproject.toml
[tool.isort]
profile = "black"
line_length = 100
```

---

## Naming Conventions

### Variables & Functions

```python
# Good: lowercase with underscores (snake_case)
document_count = 0
def process_documents():
    pass

# Bad: camelCase or SCREAMING_SNAKE_CASE
documentCount = 0  # ❌
def processDocuments():  # ❌
    pass
DOCUMENT_COUNT = 0  # Only for constants
```

### Classes & Types

```python
# Good: PascalCase for classes
class IngestService:
    pass

class DocumentModel:
    pass

# Good: SCREAMING_SNAKE_CASE for constants
MAX_WORD_COUNT = 20_000
DEFAULT_DECAY_RATE = 0.1
TIMEOUT_SECONDS = 60

# Bad: lowercase for classes
class ingestservice:  # ❌
    pass
```

### Database/API Names

```python
# Neo4j nodes: PascalCase
class NodeLabel(str, Enum):
    DOCUMENT = "Document"
    CLIENT = "Client"
    INSTRUMENT = "Instrument"

# Neo4j relationships: SCREAMING_SNAKE_CASE
class RelationType(str, Enum):
    PRODUCED_BY = "PRODUCED_BY"
    AFFECTS = "AFFECTS"
    IN_GROUP = "IN_GROUP"

# API endpoints: kebab-case
/api/v1/search-documents
/api/v1/ingest-document
/api/v1/get-client-feed
```

---

## Type Hints

### Complete Type Hints

```python
# Good: Complete type hints for all functions
def ingest(
    self,
    title: str,
    content: str,
    source_guid: str,
    metadata: dict[str, Any] | None = None
) -> IngestResult:
    """Ingest a document."""
    pass

# Bad: Incomplete type hints
def ingest(self, title, content, source_guid, metadata=None):
    pass
```

### Union Types

```python
# Good: Use | syntax (Python 3.12+)
def get_document(guid: str) -> Document | None:
    pass

# Avoid: Old Union syntax
from typing import Union
def get_document(guid: str) -> Union[Document, None]:
    pass

# Good: Optional for single None alternative
def search(query: str, limit: int = 10) -> Optional[list[Document]]:
    pass
```

### Generic Types

```python
from typing import TypeVar, Generic

T = TypeVar('T')

class Cache(Generic[T]):
    def get(self, key: str) -> T | None:
        pass
    
    def set(self, key: str, value: T) -> None:
        pass

# Usage
cache: Cache[Document] = Cache()
doc = cache.get("doc-1")  # Type: Document | None
```

---

## Documentation Style

### Module Docstrings

```python
"""Query Service for Hybrid Search

Orchestrates similarity search (ChromaDB) with graph enrichment (Neo4j)
and applies group-based access control, metadata filtering, and trust scoring.

Query Flow:
    1. Validate user's permitted groups
    2. Execute ChromaDB similarity search
    3. Apply metadata filters
    4. Enrich with Neo4j context
    5. Apply trust scoring
    6. Return ranked results

Example:
    >>> service = QueryService(...)
    >>> results = service.search(
    ...     query="Apple earnings",
    ...     group_guid="apac-research"
    ... )
"""
```

### Class Docstrings

```python
class IngestService:
    """Service for ingesting documents into the repository.
    
    Orchestrates the full ingestion flow:
    1. Validate source exists
    2. Validate word count
    3. Detect language
    4. Check duplicates
    5. Store to file
    6. Index in embeddings
    7. Index in graph
    
    Attributes:
        document_store: Storage for documents
        source_registry: Registry for source validation
        max_word_count: Maximum allowed word count (default 20,000)
    """
```

### Function Docstrings (Google Style)

```python
def ingest(
    self,
    title: str,
    content: str,
    source_guid: str,
    group_guid: str,
    language: str | None = None
) -> IngestResult:
    """Ingest a document into the repository.
    
    Validates source, detects language, checks duplicates,
    and indexes document across all backends.
    
    Args:
        title: Document title (required)
        content: Document content (max 20,000 words)
        source_guid: Source ID for this document
        group_guid: Group/tenant this document belongs to
        language: Language code (auto-detected if omitted)
    
    Returns:
        IngestResult with document details and status
    
    Raises:
        SourceValidationError: If source_guid invalid
        WordCountError: If content exceeds 20,000 words
    
    Examples:
        >>> result = service.ingest(
        ...     title="Apple Earnings",
        ...     content="Apple reported...",
        ...     source_guid="reuters-guid",
        ...     group_guid="apac-research"
        ... )
        >>> result.guid
        '550e8400-...'
    """
```

---

## Error Handling

### Custom Exceptions

```python
# Good: Domain-specific exceptions
class IngestError(Exception):
    """Base exception for ingest errors."""
    pass

class SourceNotFoundError(IngestError):
    """Error when source is not found."""
    def __init__(self, source_guid: str, message: str = "Source not found"):
        self.source_guid = source_guid
        super().__init__(f"Source validation failed: {message}")

class WordCountError(IngestError):
    """Error when document exceeds word count limit."""
    def __init__(self, word_count: int, max_count: int = 20_000):
        self.word_count = word_count
        self.max_count = max_count
        super().__init__(f"Document exceeds {max_count} words: {word_count}")

# Usage
try:
    service.ingest(...)
except SourceNotFoundError as e:
    logger.error(f"Invalid source: {e.source_guid}")
except WordCountError as e:
    logger.error(f"Document too long: {e.word_count}/{e.max_count}")
```

### Exception Handling

```python
# Good: Specific exception handling
try:
    result = query_service.search(...)
except ChromaDBConnectionError:
    logger.error("ChromaDB unavailable")
    # Fallback or retry
except QueryTimeoutError:
    logger.warning("Query timed out")
    # Shortened results

# Bad: Catch-all exception handling
try:
    result = query_service.search(...)
except Exception:  # ❌ Too broad!
    pass
```

---

## Code Organization

### File Structure

```
app/
├── __init__.py              # Package initialization
├── config.py                # Configuration (env vars)
├── main.py                  # Entry point
├── models/
│   ├── __init__.py
│   ├── document.py          # Document model
│   ├── source.py            # Source model
│   └── ...
├── services/
│   ├── __init__.py
│   ├── ingest_service.py    # Ingest orchestration
│   ├── query_service.py     # Search orchestration
│   ├── graph_index.py       # Neo4j operations
│   ├── embedding_index.py   # ChromaDB operations
│   └── ...
├── tools/
│   ├── __init__.py
│   ├── ingest_tool.py       # MCP tool definition
│   └── ...
└── exceptions/
    ├── __init__.py
    └── errors.py            # Custom exceptions
```

### Class Organization

```python
class MyService:
    """Service description."""
    
    # 1. Class variables
    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    
    # 2. Constructor
    def __init__(self, dependency: SomeDependency):
        self.dependency = dependency
    
    # 3. Public methods (alphabetical)
    def delete(self, guid: str) -> bool:
        pass
    
    def get(self, guid: str) -> Model | None:
        pass
    
    def list(self, limit: int = 10) -> list[Model]:
        pass
    
    def save(self, model: Model) -> Model:
        pass
    
    # 4. Private helper methods (with _prefix)
    def _validate_input(self, data: dict) -> bool:
        pass
    
    def _retry_with_backoff(self, func, *args) -> Any:
        pass
```

---

## Testing Conventions

### Test File Organization

```python
class TestIngestService:
    """Tests for IngestService."""
    
    @pytest.fixture
    def service(self):
        """Setup service for tests."""
        return IngestService(...)
    
    # 1. Success cases
    def test_ingest_success(self, service):
        pass
    
    # 2. Error cases
    def test_ingest_invalid_source(self, service):
        pass
    
    def test_ingest_word_count_exceeded(self, service):
        pass
    
    # 3. Edge cases
    def test_ingest_empty_content(self, service):
        pass
    
    # 4. Integration
    def test_ingest_and_retrieve(self, service):
        pass
```

### Test Naming

```python
# Pattern: test_<method>_<condition>
def test_ingest_success():  # ✅
    pass

def test_ingest_fails_with_invalid_source():  # ✅
    pass

def test_duplicate_detection_with_similar_title():  # ✅
    pass

# Avoid: Vague names
def test_ingest():  # ❌
    pass

def test_search():  # ❌
    pass
```

---

## Performance Conventions

### Use type-safe queries

```python
# Good: Explicit types
documents: list[Document] = []
scores: dict[str, float] = {}

# Bad: Loose typing
documents = []  # Type unknown
scores = {}     # Type unknown
```

### Avoid N+1 queries

```python
# Bad: N+1 query problem
for document in documents:
    source = source_registry.get(document.source_guid)  # N queries!

# Good: Batch load
sources = {s.guid: s for s in source_registry.list()}
for document in documents:
    source = sources[document.source_guid]
```

### Cache expensive operations

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_client_profile(client_guid: str) -> ClientProfile:
    """Cached client profile lookup."""
    return graph_index.get_client_profile(client_guid)
```

---

## Security Conventions

### Input Validation

```python
# Good: Validate all inputs
def ingest(self, title: str, content: str) -> IngestResult:
    # Validate before use
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    
    if not content or len(content.split()) < 10:
        raise ValueError("Content too short")
    
    # Safe to use
    return self._ingest(title.strip(), content)

# Bad: Trust inputs
def ingest(self, title: str, content: str) -> IngestResult:
    return self._ingest(title, content)  # Could be dangerous
```

### Group Access Control

```python
# Good: Always check group membership
def query(self, query_text: str, user_groups: list[str]) -> QueryResponse:
    # Query filters by user's permitted groups
    results = self._search(query_text, groups=user_groups)
    return QueryResponse(results=results)

# Bad: Missing group check
def query(self, query_text: str) -> QueryResponse:
    # Returns all results regardless of user permissions!
    results = self._search(query_text)
    return QueryResponse(results=results)
```

---

## Linting & Static Analysis

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.1.1
    hooks:
      - id: black
  
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.2.0
    hooks:
      - id: ruff
        args: [--fix]
  
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
```

### Running Checks

```bash
# Format code
black .

# Lint
ruff check . --fix

# Type check
mypy app/

# All checks
pre-commit run --all-files
```

---

## Related Documentation

- [Testing Guidelines](testing.md)
- [Contributing Guidelines](contributing.md)
- [Architecture Overview](../architecture/overview.md)
