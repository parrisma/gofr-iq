# Development & Contribution Guide

This guide covers how to set up your environment, run tests, and contribute code to GOFR-IQ.

## 🛠️ Development Environment

### Do this first
1) Create venv: `python3.12 -m venv .venv && source .venv/bin/activate`
2) Install deps: `uv pip install -e .[dev]` (or pip + requirements files)
3) Run tests: `./scripts/run_tests.sh --mode unit`

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- `uv` (recommended) or `pip`

### Setup
```bash
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies (production + dev)
pip install -r requirements.txt
pip install -r requirements-dev.txt
# OR
uv pip install -e ".[dev]"
```

---

## 🧪 Testing

Run before you push.

```bash
# Fast loop (unit only, default)
./scripts/run_tests.sh --mode unit

# Integration (starts Vault/Chroma/Neo4j + MCP/MCPO/Web)
./scripts/run_tests.sh --mode integration --refresh-env

# Full suite (unit + integration)
./scripts/run_tests.sh --mode all --refresh-env

# Specific test file
pytest test/test_ingest_service.py

# With extra logging
pytest -vs test/test_client_tools.py
```

Test categories
| Path | Type | Description |
|------|------|-------------|
| `test/` | Unit | Fast, isolated tests mock external services. |
| `test/*_integration.py` | Integration | Uses real Docker services (Neo4j, Chroma, Vault). |

Integration and all modes automatically manage the Docker test stack; add `--refresh-env` on the first run (or whenever Vault/test secrets change) to regenerate `docker/.env` and `config/generated/secrets.env`.

---

## 📝 Code Style

**Fast loop**
```bash
black .
isort .
ruff .
```

Standards
- Python 3.12+; modern syntax
- Type hints required
- Docstrings for public methods

---

## 📦 Version Policy & Service Compatibility

We strictly pin versions of external services and their client libraries to ensure stability.

### Rule of Two
When upgrading a service (e.g., Neo4j), you must also upgrade the matching Python client and verify compatibility.

See [service_compatibility.md](development/service_compatibility.md) for the active matrix of pinned versions.

---

## 🤝 Contributing

1. **Fork & Branch**: Create a feature branch (`feature/my-change`).
2. **Develop**: Write code and **add tests**.
3. **Verify**: Run `./scripts/run_tests.sh` locally.
4. **Pull Request**: targeted at `main`.
    - PRs must pass CI.
    - Code coverage should not decrease.

---

## 🔍 Troubleshooting Dev Environment

**Tests failing with connection refused?**
- Ensure Docker services are running: `docker ps`
- Check ports in `.env` match your test config.
- Run verify: `curl http://localhost:8100/api/v1/heartbeat` (Chroma Dev)

**Vault issues?**
- Dev mode uses a fixed token: `gofr-dev-root-token`.
- Reset if needed: `docker compose restart vault`
