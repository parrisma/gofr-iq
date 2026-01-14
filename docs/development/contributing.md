# Contributing Guidelines

How to contribute to GOFR-IQ, from setup through pull request.

---

## Code of Conduct

We are committed to providing a welcoming and inclusive environment for all contributors.

- **Be respectful** - Treat all contributors with respect
- **Be collaborative** - Work together to solve problems
- **Be professional** - Keep discussions focused and constructive
- **Be patient** - Everyone is learning and growing

---

## Getting Started

### Step 1: Fork & Clone

```bash
# Fork the repository on GitHub
# https://github.com/parrisma/gofr-iq/fork

# Clone your fork
git clone https://github.com/your-username/gofr-iq.git
cd gofr-iq

# Add upstream remote
git remote add upstream https://github.com/parrisma/gofr-iq.git
```

### Step 2: Setup Development Environment

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Dev tools

# Install pre-commit hooks
pre-commit install

# Start Docker services
cd docker && docker-compose up -d && cd ..

# Verify setup
bash scripts/run_tests.sh
```

### Step 3: Create Feature Branch

```bash
# Update local main
git fetch upstream
git checkout main
git rebase upstream/main

# Create feature branch
git checkout -b feature/my-awesome-feature

# Or for bug fixes
git checkout -b fix/issue-description

# Or for documentation
git checkout -b docs/update-readme
```

---

## Development Workflow

### Before You Start

1. **Check existing issues** - Make sure feature/bug isn't already in progress
2. **Create/comment on issue** - Discuss approach before starting
3. **Read relevant docs** - Understand the component you're changing

### Make Your Changes

```bash
# Keep commits atomic and focused
git add specific_file.py
git commit -m "Brief description of change"

# Follow commit message format (see below)
```

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Scope**: Component affected (e.g., `ingest`, `query`, `auth`)

**Subject**: Brief description (max 50 chars)

**Body**: Detailed explanation (wrap at 72 chars)

**Footer**: Reference issues: `Closes #123`

**Example**:
```
feat(ingest): add language detection for APAC languages

Implement auto-detection for 8 APAC languages using langdetect.
Update DocumentCreate model to include language_detected flag.

- Supports: Chinese, Japanese, Korean, Thai, Vietnamese
- Falls back to English if confidence < 0.5
- Tests added for all supported languages

Closes #456
```

### Testing Your Changes

```bash
# Run tests for your component
pytest test/test_ingest_service.py -v

# Run full suite (before submitting PR)
bash scripts/run_tests.sh

# Check coverage
pytest test/ --cov=app --cov-report=term-missing

# Lint and format
black .
ruff check . --fix
mypy app/
```

### Update Documentation

Every user-facing change needs documentation:

```bash
# Add/update docstrings
# Update docs/ files
# Add examples if applicable

# Build docs locally (optional)
cd docs && make html && cd ..
```

---

## Pull Request Process

### Step 1: Prepare PR

```bash
# Rebase on latest main
git fetch upstream
git rebase upstream/main

# Force push to your fork (if needed)
git push -f origin feature/my-awesome-feature
```

### Step 2: Create PR on GitHub

**Title Format**: `[<type>] Brief description`

Examples:
- `[feat] Add language detection for APAC languages`
- `[fix] Correct duplicate detection threshold`
- `[docs] Update configuration reference`

**Description Template**:
```markdown
## Description
Brief summary of changes

## Problem Statement
What problem does this solve?

## Solution
How does this solve it?

## Testing
How did you test this?
- [ ] Added unit tests
- [ ] Updated integration tests
- [ ] Manual testing on [specify environment]

## Checklist
- [ ] Code follows style guide
- [ ] Tests passing (712 tests)
- [ ] Docstrings updated
- [ ] User documentation updated
- [ ] Commit messages follow format

## Related Issues
Closes #123
Relates to #456

## Screenshots (if UI change)
[Optional]
```

### Step 3: Address Review Comments

```bash
# Make requested changes
# Keep commits atomic for review clarity

# Respond to each comment
git add updated_file.py
git commit -m "Address feedback: [comment summary]"

# Push updates
git push origin feature/my-awesome-feature
```

### Step 4: Merge

Once approved:

```bash
# Ensure latest changes
git fetch upstream
git rebase upstream/main

# Rebase interactively to clean up commits (optional)
git rebase -i upstream/main

# Push final version
git push origin feature/my-awesome-feature

# Click "Merge" on GitHub
```

---

## Code Review Expectations

### What Reviewers Look For

1. **Correctness** - Does it work correctly?
2. **Style** - Does it follow conventions?
3. **Tests** - Is it adequately tested?
4. **Docs** - Are docs updated?
5. **Performance** - Does it degrade performance?
6. **Security** - Any security concerns?

### What Authors Should Expect

- **Constructive feedback** - Suggestions for improvement
- **Clarifying questions** - To understand intent
- **Time** - Reviews may take a few days

### Common Feedback Patterns

| Feedback | What to Do |
|----------|-----------|
| "Can you add a test for X?" | Add test and commit |
| "This doesn't follow style guide" | Run `black` and `ruff` |
| "Need to update docstring" | Update docstring |
| "Performance concern" | Profile and optimize |

---

## Areas for Contribution

### Good for First-Time Contributors

- [ ] Documentation improvements
- [ ] Bug fixes with failing tests provided
- [ ] Test coverage increases
- [ ] Code style/cleanup
- [ ] Performance optimizations

**Start with**: [good first issue](https://github.com/parrisma/gofr-iq/labels/good%20first%20issue) label

### Intermediate Contributions

- [ ] New search features
- [ ] Graph enhancements
- [ ] Integration improvements
- [ ] API additions

### Advanced Contributions

- [ ] New database backends
- [ ] Async/concurrency improvements
- [ ] Distributed architecture
- [ ] ML-based features

---

## Development Tips

### Useful Commands

```bash
# Watch tests - auto-run on changes
ptw test/ -- -v --tb=short

# Format code
black .

# Lint code
ruff check . --fix

# Type check
mypy app/

# Check coverage
pytest test/ --cov=app --cov-report=html

# View logs
docker-compose logs -f gofr-neo4j
```

### Debugging

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or use pytest breakpoint
pytest --pdb  # Drop into debugger on failure

# Print debugging
print(f"DEBUG: {variable}")

# Logging
import logging
logger = logging.getLogger(__name__)
logger.debug("Debug message")
```

### Performance Profiling

```python
import cProfile
import pstats

cProfile.run('ingest_service.ingest(...)', 'stats.prof')

p = pstats.Stats('stats.prof')
p.sort_stats('cumulative')
p.print_stats(10)  # Top 10
```

---

## Documentation Standards

### Docstring Format (Google Style)

```python
def ingest(
    self,
    title: str,
    content: str,
    source_guid: str,
    group_guid: str,
    language: str | None = None,
    metadata: dict[str, Any] | None = None
) -> IngestResult:
    """Ingest a document into the repository.
    
    Validates source, detects language, checks for duplicates,
    and indexes document across all backends.
    
    Args:
        title: Document title (required)
        content: Document content (max 20,000 words)
        source_guid: Source ID for this document
        group_guid: Group/tenant this document belongs to
        language: Language code (auto-detected if omitted)
        metadata: Optional metadata dict
    
    Returns:
        IngestResult with document details and status
    
    Raises:
        SourceValidationError: If source_guid invalid or not accessible
        WordCountError: If content exceeds 20,000 words
        PermissionError: If source not in user's groups
    
    Examples:
        Basic ingestion:
        >>> result = service.ingest(
        ...     title="Apple Earnings",
        ...     content="Apple reported...",
        ...     source_guid="reuters-guid",
        ...     group_guid="apac-research"
        ... )
        >>> result.guid
        '550e8400-...'
        
        With metadata:
        >>> result = service.ingest(
        ...     title="Breaking News",
        ...     content="...",
        ...     source_guid="source-guid",
        ...     group_guid="group-guid",
        ...     metadata={"author": "John Smith", "region": "APAC"}
        ... )
    """
```

### Comment Guidelines

```python
# Good: Explains WHY, not WHAT
# User must have write access to source's group before ingestion
# Documents are isolated by group for tenant separation
if user["groups"][0] not in user_groups:
    raise PermissionError(...)

# Bad: Explains WHAT (code already does this)
# Sources are global - any authenticated user can reference any source
if user["groups"][0] not in user_groups:

# Bad: Misleading comment
# This is fast  # Actually O(n^2)!
```

---

## Release Process

### Semantic Versioning

```
MAJOR.MINOR.PATCH
  v1.2.3
  
MAJOR: Breaking API changes
MINOR: New features (backward compatible)
PATCH: Bug fixes
```

### Release Checklist

- [ ] All tests passing
- [ ] Coverage >= 75%
- [ ] Docs updated
- [ ] CHANGELOG.md updated
- [ ] Version bumped in pyproject.toml
- [ ] Git tag created
- [ ] GitHub release created

---

## Getting Help

- **Questions**: Open GitHub Discussion
- **Bugs**: Create GitHub Issue with:
  - Clear description
  - Steps to reproduce
  - Expected vs actual behavior
  - Environment (OS, Python version, etc.)
  - Error logs/traceback
- **Design discussion**: Open GitHub Discussion in Architecture category

---

## Community

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: Design discussions and questions
- **Pull Requests**: Code contributions
- **Email**: [contact method if available]

---

## License

By contributing to GOFR-IQ, you agree that your contributions will be licensed under the MIT License.

---

## Related Documentation

- [Code Style Guide](code-style.md)
- [Testing Guidelines](testing.md)
- [Configuration Reference](../getting-started/configuration.md)
- [Architecture Overview](../architecture/overview.md)

