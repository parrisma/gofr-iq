# Centralized Configuration & Secret Management with Vault

This document details the end-to-end workflow for managing secrets and configuration in GOFR-IQ, from Vault initialization to document ingestion.

## 1. Directory Structure

```
gofr-iq/
├── config/
│   ├── base/
│   │   ├── infrastructure.env   # Ports, hosts (from gofr-common)
│   │   └── services.env         # Service-specific settings
│   ├── .vault-init.env          # Vault credentials (gitignored)
│   └── generated/               # Auto-generated (gitignored)
│       ├── secrets.env          # Secrets from Vault
│       └── docker.env           # Combined env for Docker
│
gofr-common/
└── scripts/
    ├── vault_secrets.py         # Extract secrets from Vault
    └── generate_envs.sh         # Single entry: writes secrets.env + docker/.env
```

## 2. Vault Namespace Organization

We use a clear separation between **static configuration** (used by scripts/bootstrap) and **dynamic runtime data** (managed by the Auth service).

**Token Storage Strategy:**
- Bootstrap tokens (admin, public) are created with **extended lifetime** (365 days)
- Token UUIDs are stored in `config/bootstrap-tokens/*` as **references**
- Actual JWT tokens are stored in `auth/tokens/{uuid}` by the Auth service
- Scripts resolve token UUIDs to JWTs by querying Auth service storage
- This avoids duplication and ensures single source of truth

```
secret/gofr/
├── config/                      # STATIC configuration & bootstrap secrets
│   ├── jwt-signing-secret       # Master key for token signing
│   ├── api-keys/
│   │   └── openrouter           # LLM API Key
│   ├── infra/
│   │   └── neo4j-password       # Database credentials
│   └── bootstrap-tokens/        # Token UUID references (not JWT strings!)
│       ├── admin-token-id       # UUID of admin token (365-day lifetime)
│       └── public-token-id      # UUID of public token (365-day lifetime)
│
└── auth/                        # DYNAMIC runtime data (Auth Service)
    ├── tokens/{uuid}            # All active tokens (indexed by UUID)
    │                            # Bootstrap tokens stored here with extended expiry
    └── groups/{group-id}        # Group definitions
```

---

## 3. End-to-End Workflow

The workflow is organized into **3 phases**: Bootstrap (one-time setup), Operations (day-to-day management), and Usage (simulation/testing).

### Phase 1: Bootstrap (One-Time Setup)

1. **Start Vault Container**
   ```bash
   cd docker && docker compose up -d gofr-vault
   ```

2. **Unseal Vault & Get Root Token**
   - Initialize Vault: `vault operator init -key-shares=1 -key-threshold=1`
   - **Output Handling**:
     - Create a secured file `docker/.vault-init.env` (gitignored!) containing:
       ```bash
       export VAULT_UNSEAL_KEY="<unseal-key>"
       export VAULT_ROOT_TOKEN="<root-token>"
       # For Vault CLI operations (accessing Vault API)
       export VAULT_TOKEN=$VAULT_ROOT_TOKEN
       export VAULT_ADDR="http://localhost:8200"
       ```
   - Source this file: `source docker/.vault-init.env`
   - Unseal Vault: `vault operator unseal $VAULT_UNSEAL_KEY`
   - **Result**: Vault is unsealed with root credentials in environment.
   
   **Note on Token Types:**
   - `VAULT_TOKEN`: HashiCorp Vault access token (for Vault API operations)
   - `GOFR_*_TOKEN`: Application JWT tokens (for GOFR service authentication)

2a. **Create Vault Service Token & Policy**
   
   Create a restricted Vault token for runtime services:
   
   ```bash
   # Create read-only policy for service access
   vault policy write gofr-service-read - <<EOF
   # Read access to config secrets
   path "secret/data/gofr/config/*" {
     capabilities = ["read", "list"]
   }
   
   # Read access to auth namespace (for token validation)
   path "secret/data/gofr/auth/*" {
     capabilities = ["read", "list"]
   }
   EOF
   
   # Create service token (no expiry, renewable)
   VAULT_SERVICE_TOKEN=$(vault token create \
     -policy=gofr-service-read \
     -no-default-policy \
     -period=768h \
     -display-name="gofr-services" \
     -format=json | jq -r '.auth.client_token')
   
   # Store for later use
   echo "export VAULT_SERVICE_TOKEN='$VAULT_SERVICE_TOKEN'" >> docker/.vault-init.env
   ```
   
   **Result**: `VAULT_SERVICE_TOKEN` available for secret extraction scripts.

3. **Atomic Bootstrap Process (`scripts/bootstrap.py`)**
   
   Single script that initializes everything in correct order:
   ```bash
   source docker/.vault-init.env  # Get VAULT_TOKEN (root)
   uv run scripts/bootstrap.py
   ```
   
   **Bootstrap executes atomically:**
   
   a. **Configure Vault Engines**
      - Enable KV v2 secret engine at `secret/` (if not exists)
      - Verify `VAULT_TOKEN` has admin access
   
   b. **Generate & Store Static Secrets**
      ```python
      # Generate JWT signing secret (32-byte random)
      jwt_secret = secrets.token_urlsafe(32)
      vault.secrets.kv.v2.create_or_update_secret(
          path="gofr/config/jwt-signing-secret",
          secret={"value": jwt_secret}
      )
      
      # Store external API keys (if provided)
      if openrouter_key:
          vault.secrets.kv.v2.create_or_update_secret(
              path="gofr/config/api-keys/openrouter",
              secret={"value": openrouter_key}
          )
      ```
   
   c. **Initialize Auth Service**
      ```python
      # Read JWT secret just stored
      auth = AuthService(
          token_store=VaultTokenStore(vault_client),
          group_registry=GroupRegistry(VaultGroupStore(vault_client)),
          secret_key=jwt_secret  # From step b
      )
      # GroupRegistry auto-creates reserved groups (admin, public)
      ```
   
   d. **Create Long-Lived Bootstrap Tokens**
      ```python
      # Create tokens with 365-day lifetime for bootstrap use
      admin_token_info = auth.create_token(
          groups=["admin"],
          expires_in_seconds=86400 * 365  # 1 year
      )
      public_token_info = auth.create_token(
          groups=["public"],
          expires_in_seconds=86400 * 365  # 1 year
      )
      # Returns: {"token": "JWT...", "jti": "uuid..."}
      ```
   
   e. **Store Token References (UUIDs Only)**
      ```python
      # Store UUIDs for reference lookup, NOT the JWT strings
      vault.secrets.kv.v2.create_or_update_secret(
          path="gofr/config/bootstrap-tokens/admin-token-id",
          secret={"value": admin_token_info["jti"]}
      )
      vault.secrets.kv.v2.create_or_update_secret(
          path="gofr/config/bootstrap-tokens/public-token-id",
          secret={"value": public_token_info["jti"]}
      )
      # Actual tokens stored in auth/tokens/{uuid} by Auth service
      ```
   
   f. **Output Bootstrap Summary**
      ```
      Bootstrap Complete!
      ===================
      Admin Token:  eyJhbGc... (save securely!)
      Public Token: eyJhbGc... (save securely!)
      
      Next Steps:
      1. Create service token with: vault token create -policy=gofr-service-read
      2. Run: ./scripts/generate_docker_env.sh
      3. Start services: cd docker && docker compose up -d
      ```
   
   **Token Rotation Strategy:**
   - Bootstrap tokens valid for 365 days
   - Add calendar reminder to rotate 30 days before expiry
   - Rotation procedure:
     ```bash
     # Re-run bootstrap (creates new tokens, updates references)
     source docker/.vault-init.env
     uv run scripts/bootstrap.py --rotate-tokens
     # Extract new tokens and update any external systems
     ```

### Phase 2: Operations (Day-to-Day Management)

This phase covers starting services and managing groups/sources.

#### 2.1. Start Services

Services are managed via standard `docker compose`:

```bash
# 1. Generate secrets.env and docker/.env in one step
source config/.vault-init.env
VAULT_TOKEN=$VAULT_SERVICE_TOKEN ./lib/gofr-common/scripts/generate_envs.sh

# 2. Start services (docker-compose reads docker/.env)
cd docker && docker compose up -d
```

**What `generate_envs.sh` does:**
- Calls `vault_secrets.py` with `VAULT_SERVICE_TOKEN` to fetch secrets
- Writes `config/generated/secrets.env`
- Reads `config/base/infrastructure.env`
- Reads `config/base/services.env`
- Combines everything into `docker/.env`

#### 2.2. Manage Groups & Sources

All management scripts follow the same preamble:

```bash
# 1. Generate envs (secrets.env + docker/.env) if not already done
source config/.vault-init.env
VAULT_TOKEN=$VAULT_SERVICE_TOKEN ./lib/gofr-common/scripts/generate_envs.sh

# 2. Source secrets (puts GOFR_ADMIN_TOKEN, GOFR_JWT_SECRET in env)
source config/generated/secrets.env

# 3. Now run management commands
./lib/gofr-common/scripts/auth_manager.sh groups create apac-sales --description "APAC Sales Team"
./scripts/manage_source.sh create --name "Reuters" --url "https://reuters.com"
```

**Key Script Dependencies:**

| Script | Responsibility | Secrets Access Pattern | Required Secrets |
|--------|----------------|------------------------|------------------|
| `generate_envs.sh` | Single entry: produces `secrets.env` + `docker/.env` | Uses `vault_secrets.py` with `VAULT_SERVICE_TOKEN` | `VAULT_SERVICE_TOKEN` |
| `vault_secrets.py` | Extract secrets from Vault (internal to generate_envs) | Reads Vault via `VAULT_SERVICE_TOKEN` | N/A (produces secrets) |
| `auth_manager.sh` | Token/group management | `source config/generated/secrets.env` | `GOFR_JWT_SECRET` |
| `manage_source.sh` | Create/verify sources | `source config/generated/secrets.env` | `GOFR_ADMIN_TOKEN` |
| `manage_document.sh` | Ingest/delete documents | `source config/generated/secrets.env` | `GOFR_TOKEN_{GROUP}` |

### 2.3. Test Automation (CI & Dev Containers)

Goal: run automated tests without a manual Vault unseal/`init` step.

**Model:** CI and dev containers use the test Vault stack started by `docker/manage-infra.sh start --test`, which runs Vault in dev mode (already unsealed) with a known dev token. Secrets are pulled the same way as production, but with test paths/tokens and ephemeral data.

**Baseline variables (set by CI or defaults in scripts):**
- `GOFR_JWT_SECRET`: test JWT signing key (generated if missing during tests)
- `GOFR_VAULT_DEV_TOKEN`: dev Vault token (defaults to `gofr-dev-root-token` in scripts)
- `VAULT_TOKEN`: set to `GOFR_VAULT_DEV_TOKEN` when calling `generate_envs.sh`

**Automation flow:**
1) Start test infra (Vault + ChromaDB + Neo4j):
    ```bash
    cd docker && ./manage-infra.sh start --test
    ```
    - Vault is already unsealed in dev mode; no operator unseal needed.

2) Generate envs for tests (writes `config/generated/secrets.env` and `docker/.env`):
    ```bash
    export VAULT_TOKEN="$GOFR_VAULT_DEV_TOKEN"
    ./lib/gofr-common/scripts/generate_envs.sh --mode test
    ```

3) Run tests (defaults start servers + infra when needed):
    ```bash
    ./scripts/run_tests.sh            # all tests
    ./scripts/run_tests.sh --unit     # unit only, no servers
    ./scripts/run_tests.sh --integration
    ```

**How tests get auth state without unseal:**
- `run_tests.sh` sets Vault endpoints to the test stack and seeds `VAULT_TOKEN` from `GOFR_VAULT_DEV_TOKEN` if present.
- Pytest session fixture (`test/conftest.py`) bootstraps admin/public groups and tokens inside the test Vault using `GOFR_JWT_SECRET`, so no pre-created JWTs are required.
- Secrets/env resolution uses `generate_envs.sh` in test mode; the Vault dev token is sufficient to read `secret/gofr-test/*` paths.

**CI checklist:**
- Ensure submodule `lib/gofr-common` is present (for `generate_envs.sh` and configs).
- Export (or let defaults provide) `GOFR_JWT_SECRET` and `GOFR_VAULT_DEV_TOKEN` before running tests.
- Call `docker/manage-infra.sh start --test` then `generate_envs.sh --mode test`, then `scripts/run_tests.sh`.
- No manual unseal or operator init is needed for test automation.
| `generate_synthetic_stories.py` | Create fake content | `source config/generated/secrets.env` | `GOFR_IQ_OPENROUTER_API_KEY` |
| `ingest_synthetic_stories.py` | Upload test stories | `source config/generated/secrets.env` | `GOFR_ADMIN_TOKEN`, `GOFR_TOKEN_{GROUP}` |

**Standard Pattern for All Scripts:**
```bash
# Step 1: Extract secrets (if not already done)
source config/.vault-init.env
VAULT_TOKEN=$VAULT_SERVICE_TOKEN ./lib/gofr-common/scripts/vault_secrets.py > config/generated/secrets.env

# Step 2: Source secrets
source config/generated/secrets.env

# Step 3: Run script (secrets now in environment)
./scripts/your_script.sh
```


### Phase 3: Usage (Simulation & Testing)

The simulation workflows generate and ingest synthetic data.

**All simulation scripts require explicit secrets sourcing:**

```bash
# 1. Ensure secrets are extracted (if not already done)
source config/.vault-init.env
VAULT_TOKEN=$VAULT_SERVICE_TOKEN ./lib/gofr-common/scripts/vault_secrets.py > config/generated/secrets.env

# 2. Source secrets into environment
source config/generated/secrets.env

# 3. Generate synthetic stories (uses GOFR_IQ_OPENROUTER_API_KEY)
uv run simulation/generate_synthetic_stories.py --count 10

# 4. Ingest stories (uses GOFR_ADMIN_TOKEN + GOFR_TOKEN_*)
uv run simulation/ingest_synthetic_stories.py
```



## 4. Summary of Responsibilities

| Component | Responsibility | Vault Access | Application Auth |
|-----------|----------------|--------------|------------------|
| **Bootstrap Script** | Initialize Vault, create secrets, mint tokens | `VAULT_ROOT_TOKEN` | N/A (creates tokens) |
| **vault_secrets.py** | Extract secrets from Vault to .env | `VAULT_SERVICE_TOKEN` (read-only) | N/A |
| **Auth Service** | Validate JWT tokens, map tokens→groups | `VAULT_TOKEN` (runtime) | `JWT_SIGNING_SECRET` |
| **Admin Scripts** | Create groups, sources | N/A (reads from .env) | `GOFR_ADMIN_TOKEN` (JWT) |
| **Ingestion Scripts** | Upload documents | N/A (reads from .env) | `GOFR_TOKEN_{GROUP}` (JWT) |
