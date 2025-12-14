#!/usr/bin/env python3
"""Create a new group with JWT token for gofr-iq.

This is a project-specific wrapper that calls the shared create_group.py script
from gofr-common with the GOFR_IQ prefix.

Usage:
    python scripts/create_group.py <group-name> [options]

Examples:
    # Create a group with default 30-day expiry
    python scripts/create_group.py reuters-feed

    # Create a group with custom expiry (7 days)
    python scripts/create_group.py sales-team --expires 604800

    # Create a group and save token to file
    python scripts/create_group.py alternative-data --output tokens/alt-data.token

    # List all existing groups
    python scripts/create_group.py --list

Environment Variables:
    GOFR_IQ_JWT_SECRET     JWT signing secret (required)
    GOFR_IQ_TOKEN_STORE    Path to token store (default: data/auth/tokens.json)
"""

import subprocess
import sys
from pathlib import Path

# Find the shared script in gofr-common
script_dir = Path(__file__).parent
common_script = script_dir.parent / "lib" / "gofr-common" / "scripts" / "create_group.py"

if not common_script.exists():
    print(f"ERROR: Shared script not found at {common_script}", file=sys.stderr)
    print("Make sure gofr-common is properly installed in lib/", file=sys.stderr)
    sys.exit(1)

# Call the shared script with GOFR_IQ prefix
args = ["python", str(common_script), "--prefix", "GOFR_IQ"] + sys.argv[1:]

try:
    subprocess.run(args, check=True)
except subprocess.CalledProcessError as e:
    sys.exit(e.returncode)
except KeyboardInterrupt:
    sys.exit(130)
