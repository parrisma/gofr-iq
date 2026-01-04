# Quick Start Guide

Get GOFR-IQ running in 5 minutes.

## Prerequisites

- Docker & Docker Compose installed
- 4GB+ RAM available
- Port 8180-8182, 7574, 7787, 8100 available

## Step 1: Get the Code

```bash
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq
```

## Step 2: Build & Start

```bash
cd docker
./build-dev.sh    # Build containers (~5-10 min first time)
./run-dev.sh      # Start all services
```

**Wait for**: "All services healthy" message

## Step 3: Enter Container

```bash
docker exec -it gofr-iq-dev bash
```

## Step 4: Verify Installation

```bash
# Run test suite
bash scripts/run_tests.sh

# Expected: 712 passing tests
```

## Step 5: Start MCP Server

```bash
# No auth mode (easier for testing)
python -m app.main_mcp --no-auth

# Or with auth
export GOFR_IQ_JWT_SECRET="your-secret-key"
python scripts/bootstrap_auth.py
python -m app.main_mcp
```

## Step 6: Try It Out

### Via Python
```python
from app.services import create_ingest_service

# Ingest a test document
ingest = create_ingest_service()
result = ingest.ingest_document(
    source_guid="test-source",
    title="Test Article",
    content="This is a test article about AAPL earnings.",
    language="en"
)
print(f"Ingested: {result.guid}")
```

### Via MCPO REST API
```bash
# Start MCPO in another terminal
bash scripts/run_mcpo.sh

# Query documents
curl http://localhost:8181/query_documents \
  -H "Content-Type: application/json" \
  -d '{"query_text": "AAPL earnings", "k": 10}'
```

## What's Running?

| Service | URL | Purpose |
|---------|-----|---------|
| MCP Server | http://localhost:8180 | MCP protocol endpoint |
| MCPO API | http://localhost:8181 | REST wrapper for MCP |
| Web UI | http://localhost:8182 | Web interface |
| ChromaDB | http://localhost:8100 | Vector database |
| Neo4j Browser | http://localhost:7574 | Graph database UI |

## Next Steps

- 📖 Read [Architecture Overview](../architecture/overview.md)
- 🔧 Configure [Environment Variables](configuration.md)
- 📝 Learn about [Document Ingestion](../features/document-ingestion.md)
- 🔐 Set up [Authentication](../architecture/authentication.md)

## Troubleshooting

### Ports in use
```bash
# Stop conflicting services
docker compose down
# Change ports in docker-compose.yml
```

### Out of memory
```bash
# Increase Docker memory to 4GB+
# Docker Desktop → Settings → Resources
```

### Tests failing
```bash
# Rebuild containers
cd docker && ./build-dev.sh --no-cache

# Check logs
docker compose logs chromadb neo4j
```

## Clean Up

```bash
# Stop all services
cd docker
docker compose down

# Remove volumes (deletes all data)
docker compose down -v
```
