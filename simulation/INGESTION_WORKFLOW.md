# Synthetic Data Ingestion Workflow

## Overview
This document describes the complete workflow for setting up groups, tokens, sources, and ingesting synthetic test documents into GOFR-IQ.

## Prerequisites
- Docker containers running (vault, mcp, mcpo, web, chromadb, neo4j)
- Environment variables loaded from `lib/gofr-common/.env`
- Vault initialized and unsealed with root token from your `vault-secrets.env`

## Workflow Steps

### 1. Bootstrap System
**Purpose**: Initialize Vault authentication backend and verify infrastructure

**Commands**:
```bash
# Verify infrastructure is running
cd /home/gofr/devroot/gofr-iq/docker
docker compose ps

# Verify Vault is accessible
docker exec gofr-vault vault status
```

**Validation**: All containers should show "Up" status, Vault should show "Sealed: false"

---

### 2. Create Groups
**Purpose**: Establish authorization groups matching `.env.synthetic` configuration

**Groups to Create** (from `GOFR_SYNTHETIC_TOKENS`):
- `public` - Open access group
- `apac-sales` - APAC sales team access
- `us-sales` - US sales team access

**Commands**:
```bash
cd /home/gofr/devroot/gofr-iq
source lib/gofr-common/.env

# Create public group
./lib/gofr-common/scripts/auth_manager.sh --docker groups create \
  --name public \
  --description "Public access group"

# Create apac-sales group
./lib/gofr-common/scripts/auth_manager.sh --docker groups create \
  --name apac-sales \
  --description "APAC Sales team access"

# Create us-sales group  
./lib/gofr-common/scripts/auth_manager.sh --docker groups create \
  --name us-sales \
  --description "US Sales team access"
```

**Validation**:
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
# Should show: public, apac-sales, us-sales, admin
```

---

### 3. Create and Save Tokens
**Purpose**: Generate JWT authentication tokens for each group and save for ingestion

**Tokens to Create**:
1. **public-token** - Access to public group only
2. **apac-sales-token** - Access to apac-sales group only
3. **us-sales-token** - Access to us-sales group only
4. **admin-token** - Access to ALL groups (for admin operations)

**Commands**:
```bash
cd /home/gofr/devroot/gofr-iq
source lib/gofr-common/.env

# Create public token (30 day expiry)
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups public \
  --expires 2592000 \
  --output /tmp/public-token.txt

# Create apac-sales token
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups apac-sales \
  --expires 2592000 \
  --output /tmp/apac-sales-token.txt

# Create us-sales token
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups us-sales \
  --expires 2592000 \
  --output /tmp/us-sales-token.txt

# Create admin token (access to all groups, 10 year expiry)
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups admin,public,apac-sales,us-sales \
  --expires 315360000 \
  --output /tmp/admin-token.txt
```

**Save Tokens to Environment**:
```bash
# Update simulation/.env.synthetic with actual JWT tokens
cat > simulation/.env.synthetic << EOF
# Synthetic Data Generation Configuration

# List of simulated news sources
GOFR_SYNTHETIC_SOURCES=["Bloomberg", "Reuters", "Wall Street Journal", "TechCrunch", "MyCo APAC Research", "Financial Times", "MyCo US Research"]

# Map of user groups to upload tokens (JWT format)
GOFR_SYNTHETIC_TOKENS={
  "public": "$(cat /tmp/public-token.txt)",
  "apac-sales": "$(cat /tmp/apac-sales-token.txt)",
  "us-sales": "$(cat /tmp/us-sales-token.txt)"
}

# Admin token for management operations
GOFR_ADMIN_TOKEN=$(cat /tmp/admin-token.txt)

# OpenRouter API Key for LLM generation
GOFR_IQ_OPENROUTER_API_KEY=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
EOF
```

**Validation**:
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
# Should show 4 new tokens (public, apac-sales, us-sales, admin)

# Verify JWT format (should have 3 segments separated by dots)
cat /tmp/public-token.txt | grep -o '\.' | wc -l
# Should output: 2
```

---

### 4. Create Sources
**Purpose**: Register news sources matching `.env.synthetic` configuration

**Sources to Create** (from `GOFR_SYNTHETIC_SOURCES`):
- Bloomberg (news_agency)
- Reuters (news_agency)
- Wall Street Journal (news_agency)
- TechCrunch (news_agency)
- MyCo APAC Research (research)
- Financial Times (news_agency)
- MyCo US Research (research)

**Commands**:
```bash
cd /home/gofr/devroot/gofr-iq
source lib/gofr-common/.env
ADMIN_TOKEN=$(cat /tmp/admin-token.txt)

# Create Bloomberg
./scripts/manage_source.sh create \
  --name "Bloomberg" \
  --type news_agency \
  --languages en

# Create Reuters
./scripts/manage_source.sh create \
  --name "Reuters" \
  --type news_agency \
  --languages en

# Create Wall Street Journal
./scripts/manage_source.sh create \
  --name "Wall Street Journal" \
  --type news_agency \
  --languages en

# Create TechCrunch
./scripts/manage_source.sh create \
  --name "TechCrunch" \
  --type news_agency \
  --languages en

# Create MyCo APAC Research
./scripts/manage_source.sh create \
  --name "MyCo APAC Research" \
  --type research \
  --languages en

# Create Financial Times
./scripts/manage_source.sh create \
  --name "Financial Times" \
  --type news_agency \
  --languages en

# Create MyCo US Research
./scripts/manage_source.sh create \
  --name "MyCo US Research" \
  --type research \
  --languages en
```

**Save Source GUIDs**:
```bash
# List sources and save GUIDs to mapping file
./scripts/manage_source.sh list > /tmp/sources.txt

# Create source mapping file for ingestion script
python3 << 'EOF'
import json
import subprocess

result = subprocess.run(
    ['./scripts/manage_source.sh', 'list'],
    capture_output=True,
    text=True,
    cwd='/home/gofr/devroot/gofr-iq'
)

# Parse output and create mapping
# This would need to parse the actual output format
# Store as: {"Bloomberg": "guid", "Reuters": "guid", ...}
EOF
```

**Validation**:
```bash
./scripts/manage_source.sh list
# Should show 7 sources (Bloomberg, Reuters, WSJ, TechCrunch, MyCo APAC, FT, MyCo US)
```

---

### 5. Parse and Upload Synthetic Documents
**Purpose**: Ingest all generated synthetic documents using document-specified tokens and sources

**Document Structure**:
Each synthetic JSON document contains:
```json
{
  "source": "Reuters",                    // Maps to source GUID
  "upload_as_group": "apac-sales",       // Maps to JWT token
  "token": "gofr-sim-apac-token",        // Legacy reference (ignore)
  "title": "News regarding Company X",
  "story_body": "Full article text...",
  "validation_metadata": {
    "scenario": "Peer Exclusion",
    "base_ticker": "SHIP",
    "expected_tier": "SILVER"
  }
}
```

**Automated Ingestion Script**:

The `simulation/ingest_synthetic_stories.py` script automates the entire ingestion process:

**Features**:
- ✅ Automatically loads JWT tokens from `.env.synthetic`
- ✅ Automatically discovers source GUIDs from registry
- ✅ Maps document fields: `source` → GUID, `upload_as_group` → token
- ✅ Classifies results: Uploaded ✓ / Duplicate ⊘ / Failed ✗
- ✅ Fails fast on missing sources or tokens (no fallbacks)
- ✅ Colored output with timing information
- ✅ Lists failed documents for manual review

**Usage**:

```bash
cd /home/gofr/devroot/gofr-iq

# Normal ingestion
uv run python simulation/ingest_synthetic_stories.py

# Dry run (validate without uploading)
uv run python simulation/ingest_synthetic_stories.py --dry-run

# Verbose mode (show source/group details)
uv run python simulation/ingest_synthetic_stories.py --verbose
```

**Expected Output**:
```
=== Synthetic Document Ingestion ===

Loading tokens from .env.synthetic... ✓ (3 groups)
Loading sources from registry... ✓ (7 sources)

Found 58 synthetic documents to process

[1/58] synthetic_1768144198_0_SHIP.json                ✓ Uploaded (2.3s)
[2/58] synthetic_1768144216_1_VELO.json                ⊘ Duplicate
[3/58] synthetic_1768144236_2_NXS.json                 ✓ Uploaded (3.1s)
...

======================================================================
Summary: 35 uploaded, 20 skipped, 3 failed
Total time: 142.5s
======================================================================
```

**Validation**:
```bash
# Query for documents with admin token
ADMIN_TOKEN=$(cat /tmp/admin-token.txt)

# Test query across all groups
./scripts/manage_document.sh query \
  --query "defense OR logistics OR banking" \
  --n-results 20 \
  --token "$ADMIN_TOKEN"

# Should return documents from all groups

# Test apac-sales specific query
APAC_TOKEN=$(cat /tmp/apac-sales-token.txt)
./scripts/manage_document.sh query \
  --query "technology" \
  --n-results 10 \
  --token "$APAC_TOKEN"

# Should only return documents uploaded with apac-sales group

# Verify ingestion completed successfully
# Check for 0 failed documents in ingestion output
```

---

## Complete Setup Script

```bash
#!/bin/bash
# complete_synthetic_setup.sh - Complete workflow automation

set -e  # Exit on error

cd /home/gofr/devroot/gofr-iq
source lib/gofr-common/.env

echo "=== Step 1: Verify Bootstrap ==="
docker compose -f docker/docker-compose.yml ps

echo -e "\n=== Step 2: Create Groups ==="
./lib/gofr-common/scripts/auth_manager.sh --docker groups create --name public --description "Public access"
./lib/gofr-common/scripts/auth_manager.sh --docker groups create --name apac-sales --description "APAC Sales"
./lib/gofr-common/scripts/auth_manager.sh --docker groups create --name us-sales --description "US Sales"
./lib/gofr-common/scripts/auth_manager.sh --docker groups list

echo -e "\n=== Step 3: Create Tokens ==="
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups public --expires 2592000 --output /tmp/public-token.txt
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups apac-sales --expires 2592000 --output /tmp/apac-sales-token.txt
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups us-sales --expires 2592000 --output /tmp/us-sales-token.txt
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups admin,public,apac-sales,us-sales --expires 315360000 --output /tmp/admin-token.txt

echo "Tokens created and saved to /tmp/*-token.txt"

echo -e "\n=== Step 4: Create Sources ==="
for source in "Bloomberg:news_agency" "Reuters:news_agency" "Wall Street Journal:news_agency" "TechCrunch:news_agency" "MyCo APAC Research:research" "Financial Times:news_agency" "MyCo US Research:research"; do
  name="${source%:*}"
  type="${source#*:}"
  ./scripts/manage_source.sh create --name "$name" --type "$type" --languages en
done
./scripts/manage_source.sh list

echo -e "\n=== Step 5: Update .env.synthetic with tokens ==="
cat > simulation/.env.synthetic << EOF
# Synthetic Data Generation Configuration
GOFR_SYNTHETIC_SOURCES=["Bloomberg", "Reuters", "Wall Street Journal", "TechCrunch", "MyCo APAC Research", "Financial Times", "MyCo US Research"]
GOFR_SYNTHETIC_TOKENS={"public": "$(cat /tmp/public-token.txt)", "apac-sales": "$(cat /tmp/apac-sales-token.txt)", "us-sales": "$(cat /tmp/us-sales-token.txt)"}
GOFR_ADMIN_TOKEN=$(cat /tmp/admin-token.txt)
GOFR_IQ_OPENROUTER_API_KEY=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
EOF

echo -e "\n=== Step 6: Ingest Synthetic Documents ==="
uv run python simulation/ingest_synthetic_stories.py

echo -e "\n=== Setup Complete ==="
echo "Tokens saved in: /tmp/*-token.txt"
echo "Admin token: $(cat /tmp/admin-token.txt | head -c 20)..."
```

---

## Validation Checklist

- [ ] All Docker containers running
- [ ] Vault unsealed and accessible
- [ ] 3 groups created: public, apac-sales, us-sales
- [ ] 4 tokens created with JWT format (contains 2 dots)
- [ ] 7 sources created with GUIDs
- [ ] Tokens saved to .env.synthetic
- [ ] Ingestion script completes with 0 failed documents
- [ ] Query with admin token returns documents from all groups
- [ ] Query with group-specific token returns only that group's documents

---

## Troubleshooting

### Token Authentication Errors
**Symptom**: "Invalid token error=Not enough segments"
**Cause**: Using token ID instead of JWT token value
**Solution**: Use actual JWT token string from token creation output

### Missing Source or Token
**Symptom**: "unknown source: <name>" or "no token for group: <group>"
**Cause**: Source not created or token not in .env.synthetic
**Solution**: 
- Verify sources exist: `./scripts/manage_source.sh list`
- Verify .env.synthetic has all tokens in JSON format
- Run with `--dry-run` to validate without uploading

### Document Already Exists
**Symptom**: Duplicate detection prevents upload
**Cause**: Document was previously ingested
**Solution**: This is expected behavior - deduplication working correctly. Documents shown as "⊘ Duplicate" are skipped.

### LLM Extraction Failures
**Symptom**: "LLM extraction failed" with rollback
**Cause**: OpenRouter API key invalid or quota exceeded
**Solution**: Verify API key in .env.synthetic is current and has available credits

### Ingestion Script Errors
**Symptom**: Script fails to load tokens or sources
**Cause**: Missing .env.synthetic or sources not created
**Solution**: 
- Ensure .env.synthetic exists with GOFR_SYNTHETIC_TOKENS in JSON format
- Create sources before running ingestion (Step 4)
- Use `--verbose` flag to see detailed error messages

---

## Notes

1. **Token Security**: JWT tokens are sensitive credentials. Store securely and rotate regularly.

2. **Token Expiry**: Default tokens expire after 30 days. Admin token expires after ~10 years.

3. **Group Access**: Documents are only queryable by tokens with access to the upload group.

4. **Source Matching**: Source names in synthetic documents must exactly match created source names.

5. **Validation Metadata**: Each synthetic document includes `validation_metadata` for testing graph extraction quality.
