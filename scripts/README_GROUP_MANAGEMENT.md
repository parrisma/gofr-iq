# Group Management Scripts

Scripts for creating and managing groups in gofr-iq and other GOFR projects.

## Overview

Groups in GOFR projects represent **content sources** and enforce strict access control. Each group has one or more JWT tokens that grant access to that group's content.

This is a **shared implementation** - the core script lives in `gofr-common/scripts/create_group.py` and can be used by any GOFR project (gofr-iq, gofr-np, gofr-dig, etc.).

## Quick Start

### Create a Group (gofr-iq)

```bash
# Set JWT secret (required)
export GOFR_IQ_JWT_SECRET='your-secret-key'

# Create a group with default 30-day token expiry
./scripts/create_group.sh reuters-feed

# Create a group with custom 7-day expiry
./scripts/create_group.sh sales-team --expires 604800

# Save token to file
./scripts/create_group.sh alternative-data --output tokens/alt-data.token
```

### List Existing Groups

```bash
./scripts/create_group.sh --list
```

Output example:
```
=== Existing Groups ===

Group                          Tokens     Latest Expires           
-----------------------------------------------------------------
reuters-feed                   1          2025-01-13T10:30:00 (29d left)
sales-team-nyc                 2          2025-01-10T14:20:00 (26d left)
alternative-data               1          2025-12-21T09:15:00 (6d left)

Total groups: 3
```

## Scripts

### Shared Script: `lib/gofr-common/scripts/create_group.py`

Core implementation that works across all GOFR projects. Can be called directly with the `--prefix` parameter.

**Direct Usage:**
```bash
# gofr-iq
python lib/gofr-common/scripts/create_group.py --prefix GOFR_IQ <group-name>

# gofr-np (news processing)
python lib/gofr-common/scripts/create_group.py --prefix GOFR_NP <group-name>

# gofr-dig (digital intelligence)
python lib/gofr-common/scripts/create_group.py --prefix GOFR_DIG <group-name>
```

**Options:**
- `--prefix PREFIX` - Environment variable prefix (required, e.g., 'GOFR_IQ', 'GOFR_NP')
- `--expires SECONDS` - Token expiry in seconds (default: 2592000 = 30 days)
- `--output FILE` - Save token to file
- `--list` - List all existing groups
- `--token-store PATH` - Custom token store path

### Project Wrapper: `create_group.py`

Python wrapper that calls the shared script with the project-specific prefix (GOFR_IQ).

**Usage:**
```bash
python scripts/create_group.py <group-name> [options]
```

Automatically sets `--prefix GOFR_IQ` and validates environment.

**Options:**
- `--expires SECONDS` - Token expiry in seconds (default: 2592000 = 30 days)
- `--output FILE` - Save token to file
- `--list` - List all existing groups
- `--token-store PATH` - Custom token store path (default: data/auth/tokens.json)

**Examples:**
```bash
# Create group
python scripts/create_group.py reuters-feed

# Custom expiry (7 days)
python scripts/create_group.py sales-team --expires 604800

# Save to file
python scripts/create_group.py alt-data --output tokens/alt.token

# List groups
python scripts/create_group.py --list
```

### Bash Wrapper: `create_group.sh`

Bash script that sources environment and calls the shared script.

**Usage:**
```bash
./scripts/create_group.sh <group-name> [options]
```

Automatically:
- Sources `scripts/gofriq.env`
- Activates virtual environment if present
- Validates `GOFR_IQ_JWT_SECRET`
- Calls shared script with `--prefix GOFR_IQ`

## Architecture

```
lib/gofr-common/scripts/
└── create_group.py          # Shared implementation (works for all GOFR projects)

scripts/
├── create_group.py          # gofr-iq wrapper (calls shared with --prefix GOFR_IQ)
└── create_group.sh          # Bash convenience wrapper
```

The shared script in `gofr-common` provides the core functionality, while project-specific wrappers provide convenience and project-specific defaults.

## Using in Other GOFR Projects

To use this in another GOFR project (e.g., gofr-np):

1. **Create project wrapper** (`scripts/create_group.py`):
```python
#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

common_script = Path(__file__).parent.parent / "lib" / "gofr-common" / "scripts" / "create_group.py"
args = ["python", str(common_script), "--prefix", "GOFR_NP"] + sys.argv[1:]
subprocess.run(args, check=True)
```

2. **Create bash wrapper** (`scripts/create_group.sh`):
```bash
#!/bin/bash
exec python lib/gofr-common/scripts/create_group.py --prefix GOFR_NP "$@"
```

3. **Use it**:
```bash
export GOFR_NP_JWT_SECRET='your-secret'
./scripts/create_group.sh financial-news
```

## Group Concepts

### What is a Group?

A group represents a **content source** in gofr-iq:
- `"public"` - Default group for unauthenticated access
- `"reuters-feed"` - Premium newswire content
- `"sales-team-nyc"` - Internal sales intelligence
- `"alternative-data"` - Proprietary data vendor

### Group Access Model

- **One token = One group** (strict 1:1 relationship)
- Users needing access to multiple groups get multiple tokens
- No admin bypass - even admins need proper group tokens
- Server-side enforcement - groups cannot be spoofed by clients

### After Creating a Group

Once you create a group token:

1. **Use token in API calls:**
   ```
   Authorization: Bearer <your-token>
   ```

2. **Create sources for the group:**
   ```python
   # Token's group is automatically used
   create_source(
       name="Reuters Business News",
       source_type="NEWS_AGENCY",
       trust_level="HIGH"
   )
   ```

3. **Ingest documents:**
   ```python
   # Documents automatically assigned to token's group
   ingest_document(
       title="Fed Holds Rates Steady",
       content="...",
       source_guid="<source-guid>"
   )
   ```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GOFR_IQ_JWT_SECRET` | JWT signing secret (required) | None |
| `GOFR_IQ_TOKEN_STORE` | Path to token store | `data/auth/tokens.json` |

## Token Storage

Tokens are stored in JSON format at `data/auth/tokens.json`:

```json
{
  "eyJhbGc...": {
    "group": "reuters-feed",
    "issued_at": "2025-12-14T10:00:00.000000",
    "expires_at": "2026-01-13T10:00:00.000000",
    "not_before": "2025-12-14T10:00:00.000000"
  }
}
```

## Security Notes

1. **Protect your JWT secret** - Store `GOFR_IQ_JWT_SECRET` securely
2. **Rotate tokens regularly** - Use `--expires` to set appropriate expiry
3. **One token per group** - Don't share tokens across groups
4. **Backup token store** - Keep backups of `data/auth/tokens.json`

## Troubleshooting

### Error: GOFR_IQ_JWT_SECRET not set

```bash
export GOFR_IQ_JWT_SECRET='your-secret-key'
```

Or add to `scripts/gofriq.env`:
```bash
export GOFR_IQ_JWT_SECRET='your-secret-key'
```

### Group already exists

Creating another token for an existing group is allowed. The script will warn you and ask for confirmation.

### Token expired

Create a new token:
```bash
./scripts/create_group.sh existing-group --expires 2592000
```

## See Also

- [Group Access Control Plan](../docs/GROUP_ACCESS_CONTROL_PLAN.md)
- [Docker Setup Guide](../docs/DOCKER_SETUP_GUIDE.md)
- [MCP Server Documentation](../docs/)
