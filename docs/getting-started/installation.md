# Installation & Setup Guide

Complete step-by-step installation guide for GOFR-IQ development, testing, and production deployments.

---

## System Requirements

### Development Machine

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| **OS** | Linux/macOS | Ubuntu 22.04+ / macOS 13+ |
| **Python** | 3.11 | 3.12 (with pip, venv) |
| **Docker** | 20.10 | 25.0+ (with Compose 2.0+) |
| **Memory** | 8 GB | 16 GB (for Neo4j + ChromaDB) |
| **Disk** | 20 GB | 50 GB (for databases) |
| **Git** | 2.40+ | Latest stable |

### External APIs (Required)

- **OpenRouter API Key** - For LLM extraction
- **Vault Server** - For production auth (optional for dev)

---

## Quick Start (5 minutes)

### 1. Clone Repository

```bash
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq
```

### 2. Set Environment Variables

```bash
# Copy environment template
cp scripts/gofriq.env.example scripts/gofriq.env

# Edit with your API keys
nano scripts/gofriq.env

# Set at minimum:
export GOFR_IQ_OPENROUTER_API_KEY="sk-or-v1-..."
export GOFR_IQ_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

### 3. Start Docker Containers

```bash
cd docker

# Start all services (Neo4j, ChromaDB, Vault)
docker-compose up -d

# Wait for services to be ready (2-3 minutes)
docker-compose logs -f gofr-iq
```

### 4. Run Tests

```bash
cd ..
source scripts/gofriq.env
bash scripts/run_tests.sh
```

**Expected**: 712 tests passing, 1 skipped, 0 failures ✅

### 5. Start MCP Server

```bash
# In separate terminal
source scripts/gofriq.env
bash scripts/run_mcp.sh
```

**Expected**: Server listening on port 8080

---

## Development Setup (30 minutes)

### Step 1: System Packages

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    git \
    docker.io \
    docker-compose \
    jq

# macOS (with Homebrew)
brew install python@3.12 git docker
```

### Step 2: Python Environment

```bash
# Create virtual environment
python3.12 -m venv .venv

# Activate it
source .venv/bin/activate  # Linux/macOS
# or
.\.venv\Scripts\activate  # Windows

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -r requirements.txt

# Verify
python -c "import gofr_common; print('✅ Ready')"
```

### Step 3: Configure Environment

```bash
# Source environment
source scripts/gofriq.env

# Generate JWT secret
export GOFR_IQ_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Get OpenRouter API key
# 1. Go to https://openrouter.ai/keys
# 2. Create new key
# 3. Set:
export GOFR_IQ_OPENROUTER_API_KEY="sk-or-v1-YOUR_KEY_HERE"

# Verify configuration
echo $GOFR_IQ_JWT_SECRET
echo $GOFR_IQ_OPENROUTER_API_KEY
```

### Step 4: Start Docker Services

```bash
cd docker

# Build images (optional, pre-built available)
docker-compose build

# Start services
docker-compose up -d

# Monitor startup
docker-compose logs -f

# Wait for all to be healthy (check HEALTHCHECK)
docker-compose ps

# Expected output:
# NAME                 STATUS
# gofr-neo4j          Up (healthy)
# gofr-chromadb       Up (healthy)
# gofr-vault          Up (healthy)
```

### Step 5: Database Initialization

```bash
# Neo4j indexes
docker exec gofr-neo4j cypher-shell -u neo4j -p yourpassword << 'EOF'
CREATE CONSTRAINT doc_guid IF NOT EXISTS 
FOR (d:Document) REQUIRE d.guid IS UNIQUE;

CREATE INDEX doc_impact IF NOT EXISTS 
FOR (d:Document) ON (d.impact_tier, d.created_at);

CREATE INDEX doc_created IF NOT EXISTS 
FOR (d:Document) ON (d.created_at);
EOF

# ChromaDB ready (auto-initializes)
curl http://localhost:8000/api/v1/heartbeat

# Vault ready
curl http://localhost:8200/v1/sys/health
```

### Step 6: Run Tests

```bash
cd ..
source scripts/gofriq.env

# Run all tests
bash scripts/run_tests.sh

# Run specific test
pytest test/test_ingest_service.py -v

# Run with coverage
pytest --cov=app test/ --cov-report=html
```

### Step 7: Start Development Servers

**Terminal 1: MCP Server**
```bash
source scripts/gofriq.env
bash scripts/run_mcp.sh
# Server running on http://localhost:8080
```

**Terminal 2: MCPO Server (OpenAPI)**
```bash
source scripts/gofriq.env
bash scripts/run_mcpo.sh
# OpenAPI spec: http://localhost:8081/openapi.json
# Swagger UI: http://localhost:8081/docs
```

**Terminal 3: Web API**
```bash
source scripts/gofriq.env
bash scripts/run_web.sh
# REST API: http://localhost:8082/docs
```

---

## Production Deployment

### Step 1: Infrastructure

#### Option A: Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Create overlay network
docker network create --driver overlay gofr-net

# Create secrets
echo "your-jwt-secret" | docker secret create gofr_jwt_secret -
echo "sk-or-v1-..." | docker secret create gofr_api_key -

# Deploy stack
docker stack deploy -c docker/docker-compose.yml gofr-prod
```

#### Option B: Kubernetes

```bash
# Create namespace
kubectl create namespace gofr-iq

# Create secrets
kubectl create secret generic gofr-secrets \
  --from-literal=jwt-secret="..." \
  --from-literal=api-key="..." \
  -n gofr-iq

# Deploy
kubectl apply -f k8s/deployment.yml -n gofr-iq
```

### Step 2: Vault Setup (Production Auth)

```bash
# Initialize Vault
vault operator init

# Unseal vault (save keys!)
vault operator unseal <key1>
vault operator unseal <key2>
vault operator unseal <key3>

# Login with root token
vault login <root_token>

# Enable KV secret engine
vault secrets enable -version=2 secret

# Create gofr-iq auth path
vault kv put secret/gofr-iq/auth \
  jwt_secret="..." \
  api_key="..."

# Configure AppRole (for production)
vault auth enable approle

vault write auth/approle/role/gofr-iq \
  token_ttl=1h \
  policies="gofr-iq"

vault read auth/approle/role/gofr-iq/role-id
vault write -f auth/approle/role/gofr-iq/secret-id
```

### Step 3: Environment Configuration

```bash
# Production environment file
cat > /etc/gofr-iq/gofr-iq.env << 'EOF'
# Production settings
export GOFR_IQ_ENV=PROD
export GOFR_IQ_HOST=0.0.0.0
export GOFR_IQ_LOG_LEVEL=INFO

# Auth (Vault)
export GOFR_AUTH_BACKEND=vault
export GOFR_VAULT_URL=https://vault.example.com:8200
export GOFR_VAULT_ROLE_ID="role-id"
export GOFR_VAULT_SECRET_ID="secret-id"

# Databases
export GOFR_IQ_NEO4J_URI=bolt://neo4j.example.com:7687
export GOFR_IQ_NEO4J_PASSWORD="secure-password"
export GOFR_IQ_CHROMA_HOST=chromadb.example.com
export GOFR_IQ_CHROMA_PORT=8000

# LLM
export GOFR_IQ_OPENROUTER_API_KEY="sk-or-v1-..."

# Monitoring
export GOFR_IQ_LOG_LEVEL=INFO
export GOFR_IQ_LOG_FILE=/var/log/gofr-iq/app.log
EOF

# Verify
source /etc/gofr-iq/gofr-iq.env
echo $GOFR_IQ_ENV
```

### Step 4: Health Checks

```bash
#!/bin/bash
# health-check.sh - Run periodically

# Neo4j
curl -u neo4j:password http://localhost:7474/db/neo4j/data/

# ChromaDB
curl http://localhost:8000/api/v1/heartbeat

# MCP Server
curl http://localhost:8080/health

# Check logs for errors
tail -50 /var/log/gofr-iq/app.log | grep ERROR
```

### Step 5: Backups

```bash
#!/bin/bash
# Backup script - run daily

BACKUP_DIR="/backups/gofr-iq"
DATE=$(date +%Y-%m-%d)

# Neo4j backup
docker exec gofr-neo4j neo4j-admin dump \
  --to-path=/backups/neo4j-$DATE.dump

# ChromaDB backup
cp -r /data/chromadb /backups/chromadb-$DATE/

# Documents backup
tar -czf /backups/documents-$DATE.tar.gz /data/storage/documents/

# Upload to S3
aws s3 cp /backups/ s3://backups.example.com/gofr-iq/$DATE/ --recursive

# Clean old backups (keep 30 days)
find /backups -name "neo4j-*.dump" -mtime +30 -delete
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find what's using port
lsof -i :8080

# Kill process
kill -9 <PID>

# Or change port
export GOFR_IQ_MCP_PORT=9080
```

### Docker Compose Issues

```bash
# View logs
docker-compose logs -f gofr-neo4j

# Restart service
docker-compose restart gofr-neo4j

# Full reset (careful!)
docker-compose down -v  # Remove volumes
docker-compose up -d
```

### JWT Secret Issues

```bash
# Regenerate
export GOFR_IQ_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Verify it's set
echo $GOFR_IQ_JWT_SECRET

# Update in production
# (Need to regenerate all user tokens after change)
```

### API Key Issues

```bash
# Verify key format
echo $GOFR_IQ_OPENROUTER_API_KEY
# Should start with: sk-or-v1-

# Test API key
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $GOFR_IQ_OPENROUTER_API_KEY"
```

### Database Connection Issues

```bash
# Test Neo4j
python -c "
from py2neo import Graph
g = Graph('bolt://localhost:7687', auth=('neo4j', 'password'))
print(g.database.name)
"

# Test ChromaDB
curl http://localhost:8000/api/v1/heartbeat
```

---

## Verification Checklist

- [ ] Python 3.12+ installed
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip list`)
- [ ] Docker services running (`docker-compose ps`)
- [ ] Database indexes created
- [ ] Tests passing (712 passing, 0 failing)
- [ ] MCP server responding (`curl http://localhost:8080/health`)
- [ ] OpenRouter API key valid
- [ ] JWT secret generated and exported
- [ ] All environment variables set (`env | grep GOFR_IQ`)

---

## Next Steps

1. **Read Quick Start**: [docs/getting-started/quick-start.md](quick-start.md)
2. **Review Configuration**: [docs/getting-started/configuration.md](configuration.md)
3. **Understand Architecture**: [docs/architecture/overview.md](../architecture/overview.md)
4. **Ingest Your First Document**: Try the ingestion example
5. **Run Your First Query**: Try semantic search

---

## Getting Help

- **Issues**: Create GitHub issue with error logs
- **Docs**: Check [docs/README.md](../README.md) for full documentation
- **Debugging**: Enable debug logs: `export GOFR_IQ_LOG_LEVEL=DEBUG`
- **Performance**: Check `logs/gofr-iq.log` for slow operations

---

## Related Documentation

- [Quick Start Guide](quick-start.md)
- [Configuration Reference](configuration.md)
- [Architecture Overview](../architecture/overview.md)
- [Docker Setup Guide](../../docs/DOCKER_SETUP_GUIDE.md)
