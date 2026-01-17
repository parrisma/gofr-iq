# Configuration Management Strategy

## 1. Executive Summary

This document proposes a unified, minimal configuration strategy for the **GOFR Ecosystem** that:
1. **Centralizes shared config in `gofr-common`** (infra, ports, env loading, validation)
2. **Localizes only module-specific fields** in each `gofr-<module>` (e.g., LLM, pipelines)
3. **Uses a single loader path** across services, scripts, tests, Docker/K8s
4. **Validates at startup** with clear required/optional rules per environment

The strategy follows the **12-Factor App** methodology, strictly separating config from code.

## 2. Configuration Hierarchy

Configuration values are resolved in the following priority order (highest to lowest):

1. **Explicit Overrides**: Arguments passed directly to constructors.
2. **Environment Variables**: `GOFR_*` (Global) and `GOFR_IQ_*` (Module-specific) variables.
3. **.env File**: Local development overrides.
4. **Shared Defaults**: Defined in `gofr-common`.
5. **Code Defaults**: Fallback values for module-specific settings.

## 3. Implementation Plan

### Current Status (Jan 2026)
- ✅ **COMPLETE**: gofr-common ships `EnvLoader` (.env → env vars → overrides) and routes `BaseConfig`/`InfrastructureConfig` through it.
- ✅ **COMPLETE**: Ports are data-only in `config/gofr_ports.env` with cached loader, test offsets, and convenience constants (`PORTS`, `GOFR_*_PORTS`).
- ✅ **COMPLETE**: Scripts read `.env` via shell sourcing and Python EnvLoader; `python-dotenv` dependency added.
- ✅ **COMPLETE**: hvac dependency added for Vault integration tests.
- ✅ **COMPLETE**: All 622 gofr-common tests pass with zero skips (including 29 Vault integration tests).
- ✅ **COMPLETE**: gofr-iq migrated to new config model - `GofrIqConfig` extends `InfrastructureConfig`; all legacy APIs removed.
- ✅ **COMPLETE**: Main servers (main_mcp.py, mcp_server.py) and services (llm_service.py) updated to use `get_config()`.
- ✅ **COMPLETE**: All 754 gofr-iq tests pass (0 failed, 0 skipped) with new config model.
- ✅ **COMPLETE**: OpenRouter API key added to `lib/gofr-common/.env` - all LLM integration tests passing.
- ✅ **COMPLETE**: Fixed embedding type conversion in `llm_service.py` for proper float casting.

### Phase 1: Shared Configuration Library (gofr-common)

Provide the only engine for loading and validating configuration.

**gofr-common Responsibilities (no duplication in modules):**
- `EnvLoader`: deterministic load order (.env, env vars, overrides)
- `BaseConfig`: env/mode, project_root, logging mode, validation entrypoint
- `InfrastructureConfig`: vault, neo4j, chroma, shared secrets
- `PortConfig`: ports loaded from `.env` (data-only)
- `validate()`: required/optional rules per environment (PROD strict, TEST permissive)

### Phase 2: Module-Specific Config (one class per module)

Each module adds only its unique fields by subclassing `InfrastructureConfig`.

- `GofrIqConfig(InfrastructureConfig)`: LLM settings (OpenRouter API, models), inherits all infrastructure config
- `GofrDigConfig(InfrastructureConfig)`: pipeline settings, source registry options (when implemented)
- Other modules follow the same pattern

### Phase 3: Ports as Data (.env only)

Convert `lib/gofr-common/config/gofr_ports.sh` → `gofr_ports.env` (data-only, no wrapper, no coexistence):

```bash
# lib/gofr-common/config/gofr_ports.env
# GOFR Service Port Configuration

# GOFR-IQ (Intelligence & Query)
GOFR_IQ_MCP_PORT=8080
GOFR_IQ_MCPO_PORT=8081
GOFR_IQ_WEB_PORT=8082

# GOFR-DIG (Data Ingestion)
GOFR_DIG_MCP_PORT=8070
GOFR_DIG_MCPO_PORT=8071
GOFR_DIG_WEB_PORT=8072

# Infrastructure
GOFR_VAULT_PORT=8201
GOFR_NEO4J_HTTP_PORT=7474
GOFR_NEO4J_BOLT_PORT=7687
GOFR_CHROMA_PORT=8000
```

**Benefits**:
- ✅ Standard format understood by Docker, Python (`python-dotenv`), and shell
- ✅ No executable code—just data
- ✅ Version-controlled defaults
- ✅ Simpler programmatic parsing

### Phase 4: Service Migration

Refactor services to accept config objects (no direct `os.environ` access):
- IngestService, QueryService, GraphIndex, EmbeddingIndex, LLMService, etc.
- Pass `config` into constructors/factories; forbid globals

### Phase 5: Test Suite Migration

Update test suites across all modules to rely on configuration objects rather than environment variable patching.

#### **gofr-common Test Suite**:
- Create base test fixtures (`base_test_config`) for other modules to inherit.
- Update `gofr-common` tests to use new `BaseConfig` and `InfrastructureConfig`.
- Ensure configuration factory patterns are testable and well-documented.

#### **gofr-iq Test Suite** (700+ tests):
- Replace `os.environ` patching with `test_config` fixtures.
- Update `conftest.py` to use `GofrIqConfig.from_env()` with test overrides.
- Refactor integration tests to use standardized port resolution.
- Update unit tests to accept config objects via dependency injection.

#### **Other GOFR Modules** (gofr-dig, gofr-plot, etc.):
- Apply same patterns as gofr-iq once base patterns are established.
- Leverage shared test fixtures from `gofr-common`.

### Phase 6: Script & Environment Synchronization

- Migrate all scripts to load `.env` (no `.sh` sourcing)
- Respect `GOFR_ENV` consistently across scripts
- Handle test offsets in Python (not shell)
- `gofriq.env` loads common `.env` ports first, then module overrides

## 4. Environment Strategy

| Feature | PROD | TEST | DEV |
|---------|------|------|-----|
| **Data Dir** | `/data` | `/test/data` | `/data` |
| **Secrets** | Vault / K8s Secrets | Mock / Env Vars | `.env` file |
| **Validation** | Strict (Fail Fast) | Permissive | Warn Only |
| **Logging** | JSON / Info | Text / Debug | Text / Info |

## 5. Kubernetes & Docker Integration

### Docker Compose
Connects naturally via `environment` section:
```yaml
environment:
  # Shared Infrastructure (handled by gofr-common)
  - GOFR_ENV=PROD
  - GOFR_NEO4J_URI=bolt://gofr-neo4j:7687
  
  # Module Specifics (handled by gofr-iq)
  - GOFR_IQ_LLM_MODEL=anthropic/claude-opus-4
```

### Kubernetes
Maps `ConfigMap` and `Secret` to environment variables. Allows sharing common config maps across pods (e.g., `gofr-infra-config`) while keeping module specifics separate (`gofr-iq-config`).

## 6. Testing Strategy

Tests use the `test_config` fixture to inject isolated configuration:
```python
@pytest.fixture
def test_config(tmp_path):
    # Initializes GofrIqConfig which inherits base logic from gofr-common
    return GofrIqConfig.from_env(
        env="TEST",
        project_root=tmp_path,
        # ... isolated infrastructure ...
    )
```

### Test Results

#### gofr-common
- **622 tests passed** (0 failed, 0 skipped)
- Includes 29 Vault integration tests
- All infrastructure tests passing (Vault, Neo4j, ChromaDB connection validation)

#### gofr-iq
- **754 tests passed** (0 failed, 0 skipped)
- Full integration tests with real infrastructure
- End-to-end LLM tests with OpenRouter API
- Authentication tests with Vault backend
- Graph-based ranking and hybrid query tests
- Multi-service orchestration (MCP, Web, MCPO servers)

## 7. Migration Checklist

### gofr-common (Base Library)
1) [x] Create `BaseConfig` and `InfrastructureConfig` classes
2) [x] Implement `EnvLoader` with `.env` file support and single load path
3) [x] Create `PortConfig` / loader to read ports from `.env` (data-only)
4) [x] **Convert `gofr_ports.sh` → `gofr_ports.env`** (single source; no wrappers)
5) [x] **Run gofr-common test suite (no fails, no skips) before changes** _(593 tests passing baseline)_
6) [x] **Refactor gofr-common test suite** to use new config patterns _(EnvLoader tests added, configs updated)_
7) [x] **Run gofr-common test suite (no fails, no skips) after changes** _(622 tests passing, 0 skipped)_
8) [x] Update gofr-common documentation

### gofr-iq (Module Implementation)
1) [x] **Run gofr-iq test suite (no fails, no skips) before changes** _(Baseline: 736 passing, 18 skipped without OpenRouter API key)_
2) [x] Create `GofrIqConfig` extending `InfrastructureConfig` _(adds LLM/ChromaDB settings to inherited infra config)_
3) [x] Move LLM and Graph specifics to module config _(openrouter_api_key, llm_model, embedding_model, etc.)_
4) [x] Refactor `app/config.py` to use inheritance model _(CLEAN - removed all legacy API; GofrIqConfig → InfrastructureConfig → BaseConfig with get_config() singleton)_
5) [x] Update `scripts/run_tests.sh` to load `.env` files _(sources gofr_ports.env + gofr-common/.env; calculates test port offsets)_
6) [x] Create `lib/gofr-common/.env` with shared secrets _(GOFR_JWT_SECRET, GOFR_VAULT_DEV_TOKEN, GOFR_IQ_OPENROUTER_API_KEY, defaults)_
7) [x] **Refactor services to use GofrIqConfig** _(Updated: main_mcp.py, main.py, mcp_server.py, llm_service.py - all use get_config() or config parameter)_
8) [x] **Test and fix any remaining issues** _(Fixed: import errors, attribute mismatches, os import, embedding type conversion)_
9) [x] **Run gofr-iq test suite (no fails, no skips) after refactoring** _(COMPLETE: 754 tests passing, 0 failed, 0 skipped)_

**Status**: ✅ **MIGRATION COMPLETE** - All legacy configuration code removed. Clean inheritance model established (GofrIqConfig → InfrastructureConfig → BaseConfig). All 754 tests passing with real infrastructure (Vault, ChromaDB, Neo4j) and LLM integration via OpenRouter API.

### System-wide Updates
1) [x] Replace all `gofr_ports.sh` sourcing with `.env` loading _(gofr-common and gofr-iq test runners updated)_
2) [x] Remove obsolete files _(Removed: lib/gofr-common/config/defunct_gofr_ports.sh, test/test_end_to_end_ingest_query.py.backup, test/test_end_to_end_ingest_query.py.bak)_
3) [x] Update Docker scripts to use `.env` files instead of sourcing `.sh`:
   - [x] `docker/run-dev.sh` - migrated to gofr_ports.env
   - [x] `docker/run-prod.sh` - migrated to gofr_ports.env
   - [x] `docker/run-vault.sh` - migrated to gofr_ports.env
   - [x] `docker/start-swarm.sh` - migrated to gofr_ports.env
4) [x] Update Docker entrypoints to use `.env` files:
   - [x] `docker/entrypoint-dev.sh` - already migrated (no port refs)
   - [x] `docker/entrypoint-prod.sh` - migrated to gofr_ports.env
5) [x] Update `docker-compose.yml` comments and documentation:
   - [x] Remove references to sourcing `gofr_ports.sh`
   - [x] Document `.env` file usage pattern (export via grep/xargs)
   - [ ] Add `env_file` directives where appropriate (optional enhancement)
6) [x] Update `docker-compose-test.yml` comments and documentation:
   - [x] Remove references to sourcing `gofr_ports.sh`
   - [x] Document test port offset pattern and manage-infra.sh usage
7) [x] Update management scripts:
   - [x] `scripts/manage_source.sh` - migrated to gofr_ports.env
   - [x] `scripts/manage_document.sh` - migrated to gofr_ports.env
8) [x] Update CI/CD pipelines to set proper `GOFR_ENV` mode _(No CI/CD pipelines found in repository - skipped)_
9) [x] Document configuration patterns in central location _(this document)_

**Priority Actions:**
- ✅ **High**: Remove defunct_gofr_ports.sh and .backup files (COMPLETE)
- ✅ **High**: Update docker-compose.yml comments to reflect .env usage (COMPLETE)
- ✅ **High**: Migrate Docker scripts (run-*.sh, start-swarm.sh) to .env (COMPLETE)
- ✅ **High**: Update entrypoint-prod.sh to use .env (COMPLETE)
- ✅ **Low**: Migrate management scripts (manage_source.sh, manage_document.sh) (COMPLETE)
- ✅ **Low**: CI/CD pipeline updates (No pipelines found - N/A)

**System-wide Migration Status**: ✅ **COMPLETE** - All scripts, Docker files, and documentation updated to use `.env` file pattern. No remaining references to `gofr_ports.sh` in active codebase.

### Other GOFR Modules (gofr-dig, gofr-plot, etc.)
1) [ ] Create module-specific config classes extending `BaseConfig`
2) [ ] Refactor module test suites
3) [ ] Update module scripts and documentation

