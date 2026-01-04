# GOFR-IQ Documentation

Complete documentation for the GOFR-IQ Financial News Intelligence Platform.

## Quick Navigation

### 🚀 New to GOFR-IQ?
- [Quick Start](getting-started/quick-start.md) - Get running in 5 minutes
- [What is GOFR-IQ?](../README.md#what-is-gofr-iq) - Functional overview
- [Architecture Overview](architecture/overview.md) - System design

### 📚 Getting Started
- [Quick Start Guide](getting-started/quick-start.md)
- [Installation](getting-started/installation.md)
- [Configuration](getting-started/configuration.md)

### 🏗️ Architecture
- [System Overview](architecture/overview.md) - Components and data flow
- [Authentication](architecture/authentication.md) - JWT and group access
- [Graph Design](architecture/graph-design.md) - Neo4j schema

### ✨ Features
- [Document Ingestion](features/document-ingestion.md) - How documents are processed
- [Hybrid Search](features/hybrid-search.md) - Vector + graph search
- [Client Feeds](features/client-feeds.md) - Personalized ranking
- [Group Access Control](features/group-access.md) - Permission model
- [Client Types](features/client-types.md) - Client profile taxonomy
- [Impact Ranking](features/impact-ranking.md) - Tier-based impact scoring

### 🔧 Development
- [Testing Guide](development/testing.md) - Running tests
- [Version Policy](development/version-policy.md) - Dependencies
- [Contributing](development/contributing.md) - How to contribute
- [Code Style](development/code-style.md) - Standards

### 📚 Getting Started (continued)
- [Service Compatibility](getting-started/service-compatibility.md) - External service versions

### 📖 Reference Documentation
- [Project Summary](reference/project-summary.md) - System overview
- [Implementation Details](reference/implementation-details.md) - Technical specifications
- [Design Review Report](reference/design-review.md) - Comprehensive design analysis
- [Browse all reference docs →](reference/)

### 📦 Archive
- [Migration Plans](archive/migration-plans/) - Historical auth migrations
- [Historical Documentation](archive/historical/) - Superseded patterns and docs

## Documentation Structure

```
docs/
├── README.md                    # Navigation hub (you are here)
├── getting-started/             # Setup and configuration
│   ├── quick-start.md
│   ├── installation.md
│   ├── configuration.md
│   └── service-compatibility.md
├── architecture/                # System design
│   ├── overview.md
│   ├── authentication.md
│   └── graph-design.md
├── features/                    # Feature documentation
│   ├── document-ingestion.md
│   ├── hybrid-search.md
│   ├── client-feeds.md
│   ├── group-access.md
│   ├── client-types.md
│   └── impact-ranking.md
├── development/                 # Developer guides
│   ├── testing.md
│   ├── contributing.md
│   ├── code-style.md
│   └── version-policy.md
├── reference/                   # Technical reference
    ├── README.md
    ├── project-summary.md
    ├── implementation-details.md
    └── design-review.md

```

## Contributing to Docs

Documentation uses Markdown format. To add or update docs:

1. Follow existing structure
2. Use clear headings and navigation
3. Include code examples
4. Add links between related docs
5. Test all code snippets

## Getting Help

- 📖 Start with [Quick Start](getting-started/quick-start.md)
- 🐛 Report issues on [GitHub](https://github.com/parrisma/gofr-iq/issues)
- 💬 Ask questions in [Discussions](https://github.com/parrisma/gofr-iq/discussions)
