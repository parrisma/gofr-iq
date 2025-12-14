# GOFR Docker Setup Guide

Lessons learned from configuring gofr-iq Docker deployment. Apply these patterns to other GOFR projects.

## 1. Environment Variable Naming Convention

**Standard**: Use `GOFR_<PROJECT>_` prefix (with underscore between GOFR and project name)

```bash
# Correct
GOFR_IQ_MCP_PORT=8080
GOFR_IQ_ENV=PROD
GOFR_IQ_AUTH_DISABLED=true

# Wrong
GOFRIQ_MCP_PORT=8080  # Missing underscore
```

**Fix command** to update all files in a project:
```bash
find . -type f \( -name "*.sh" -o -name "*.py" -o -name "*.md" \) \
  -not -path "./.git/*" -not -path "./.venv/*" \
  -exec sed -i 's/GOFRIQ_/GOFR_IQ_/g' {} \;
```

## 2. docker-compose.yml - Overriding Entrypoint

**Problem**: If Dockerfile uses `ENTRYPOINT` (not `CMD`), docker-compose `command:` won't override it.

**Solution**: Add `entrypoint:` to each service:

```yaml
services:
  mcp:
    image: gofr-iq-prod:latest
    user: gofr-iq
    working_dir: /home/gofr-iq
    entrypoint: ["/home/gofr-iq/.venv/bin/python"]
    command: ["-m", "app.main_mcp", "--host", "0.0.0.0", "--port", "8080", "--no-auth"]

  mcpo:
    image: gofr-iq-prod:latest
    user: gofr-iq
    working_dir: /home/gofr-iq
    entrypoint: ["/bin/sh", "-c"]
    command:
      - "/home/gofr-iq/.venv/bin/mcpo --host 0.0.0.0 --port 8081 --server-type streamable-http -- http://gofr-iq-mcp:8080/mcp"
```

## 3. Health Checks

**Problem**: Docker-compose doesn't interpolate `${VAR}` inside healthcheck test commands.

**Solution**: Use hardcoded ports in health checks:

```yaml
healthcheck:
  # For MCP/Web servers - accept any response (400 is OK, means server is alive)
  test: ["CMD-SHELL", "curl -s -o /dev/null http://localhost:8080/mcp || exit 1"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 15s

  # For MCPO - check /docs endpoint
  test: ["CMD", "curl", "-f", "http://localhost:8081/docs"]
```

## 4. Authentication Configuration

**Pattern**: Support no-auth mode via environment variable:

```bash
# In entrypoint scripts
AUTH_DISABLED="${GOFR_IQ_AUTH_DISABLED:-false}"
if [ "$AUTH_DISABLED" = "false" ] && [ -z "$JWT_SECRET" ]; then
    echo "ERROR: JWT_SECRET required or set GOFR_IQ_AUTH_DISABLED=true"
    exit 1
fi
# Set empty default for supervisor compatibility
export JWT_SECRET="${JWT_SECRET:-}"
```

**In Python**:
```python
# Check both --no-auth flag AND --auth-disabled/env var
require_auth = not (args.no_auth or args.auth_disabled)
```

## 5. Port Configuration

**Central config**: `lib/gofr-common/config/gofr_ports.sh`

```bash
# Port allocation per project (increments of 10)
# gofr-doc:  8040-8042
# gofr-plot: 8050-8052
# gofr-np:   8060-8062
# gofr-dig:  8070-8072
# gofr-iq:   8080-8082
```

**In project scripts** - export before docker-compose:
```bash
source "$PROJECT_ROOT/lib/gofr-common/config/gofr_ports.sh"
export GOFR_IQ_MCP_PORT GOFR_IQ_MCPO_PORT GOFR_IQ_WEB_PORT
```

**In docker-compose** - use defaults for standalone operation:
```yaml
ports:
  - "${GOFR_IQ_MCP_PORT:-8080}:${GOFR_IQ_MCP_PORT:-8080}"
```

## 6. Supervisor vs Direct Execution

**Option A: Supervisor** (single container, multiple processes)
- Use `entrypoint-prod.sh` with supervisor config
- Good for: swarm deployment, single container management
- Container runs: mcp + mcpo + web in one container

**Option B: Direct** (multiple containers, one process each)
- Override entrypoint in docker-compose
- Good for: local development, individual scaling
- Each service in separate container

## 7. Checklist for New GOFR Project

- [ ] Use `GOFR_<PROJECT>_` prefix for all env vars
- [ ] entrypoint-prod.sh: Set defaults for ports (8080, 8081, 8082)
- [ ] entrypoint-prod.sh: Handle auth disabled mode, default JWT_SECRET=""
- [ ] docker-compose.yml: Add `entrypoint:` + `user:` + `working_dir:` to each service
- [ ] docker-compose.yml: Health checks with hardcoded ports
- [ ] Python main_*.py: Check both `--no-auth` and `--auth-disabled` flags
- [ ] Source gofr_ports.sh and export vars before running docker-compose
