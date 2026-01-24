#!/usr/bin/env python3
"""
AppRole Setup Script
====================
The Identity Factory for GOFR services.

This script uses the bootstrap Root Token to:
1. Validate AppRole auth + required policies (no global writes in consumer mode)
2. Provision AppRoles for each service
3. Generate and export credentials (RoleID + SecretID)

Usage:
    uv run scripts/setup_approle.py

Outputs:
    ./secrets/service_creds/gofr-mcp.json
    ./secrets/service_creds/gofr-web.json
"""

import sys
import json
import os
import stat
from pathlib import Path

# Add project root and gofr-common to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "gofr-common" / "src"))

try:
    from gofr_common.auth.backends.vault_config import VaultConfig
    from gofr_common.auth.backends.vault_client import VaultClient
    from gofr_common.auth.admin import VaultAdmin
    from gofr_common.auth.policies import POLICIES
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("Ensure you're running with: uv run scripts/setup_approle.py")
    sys.exit(1)

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
SECRETS_DIR = PROJECT_ROOT / "secrets"
CREDS_DIR = SECRETS_DIR / "service_creds"
ROOT_TOKEN_FILE = SECRETS_DIR / "vault_root_token"

SERVICES = {
    # Service Name : Policy Name
    "gofr-mcp": "gofr-mcp-policy",
    "gofr-web": "gofr-web-policy",
}

def ensure_creds_dir():
    """Ensure service credentials directory exists."""
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    # 0700 - Only owner can traverse/read
    CREDS_DIR.chmod(stat.S_IRWXU)


def require_approle_enabled(admin: VaultAdmin) -> None:
    """Fail fast if AppRole auth mount is not enabled (consumer mode expects it)."""
    auth_methods = admin._hvac.sys.list_auth_methods()
    if "approle/" not in auth_methods or auth_methods["approle/"]["type"] != "approle":
        print("❌ AppRole auth method is not enabled. Run shared Vault bootstrap first.")
        sys.exit(1)


def require_policy(admin: VaultAdmin, policy_name: str) -> None:
    """Ensure a policy exists; fail with guidance if missing."""
    try:
        admin._hvac.sys.read_policy(policy_name)
    except Exception:
        print(f"❌ Policy '{policy_name}' not found. Run shared Vault bootstrap to install policies.")
        sys.exit(1)

def get_root_token() -> str:
    """Read root token from secure enclave."""
    if not ROOT_TOKEN_FILE.exists():
        print(f"❌ Root token not found at {ROOT_TOKEN_FILE}")
        print("   Run 'uv run scripts/bootstrap.py' first.")
        sys.exit(1)
    return ROOT_TOKEN_FILE.read_text().strip()

def main():
    print("\n" + "="*70)
    print("🔐 GOFR Identity Factory (AppRole Setup)")
    print("="*70)

    # 1. Setup Connection
    vault_addr = os.getenv('VAULT_ADDR', 'http://gofr-vault:8201')
    root_token = get_root_token()
    
    print(f"• Connecting to Vault at {vault_addr}...")
    config = VaultConfig(url=vault_addr, token=root_token)
    client = VaultClient(config)
    admin = VaultAdmin(client)

    # 2. Enable Auth
    print("• Validating AppRole auth and policies (consumer mode)...")
    require_approle_enabled(admin)
    for policy in POLICIES.keys():
        require_policy(admin, policy)
    print("  ✅ AppRole enabled and policies present")

    # 4. Provision Services
    ensure_creds_dir()
    
    print("\n• Provisioning Identities:")
    for service, policy in SERVICES.items():
        print(f"  [ {service} ]")
        try:
            # Create/Update Role
            admin.provision_service_role(service, policy)
            print(f"    - Role configured with policy '{policy}'")
            
            # Generate Credentials
            creds = admin.generate_service_credentials(service)
            print("    - Credentials generated")
            
            # Export to File
            # Use 0644 so container users can read (directory is 0700 protected)
            outfile = CREDS_DIR / f"{service}.json"
            outfile.write_text(json.dumps(creds, indent=2))
            outfile.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH) # 0644
            print(f"    - Saved to {outfile} (0644)")
            
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            sys.exit(1)

    print("\n" + "="*70)
    print("🎉 Identity Provisioning Complete!")
    print(f"📁 Credentials stored in {CREDS_DIR}/")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
