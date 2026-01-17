#!/usr/bin/env python3
"""
End-to-end simulation runner.
- Creates required groups/tokens in Vault
- Registers sources if missing
- Generates synthetic stories
- Ingests generated stories
"""
import argparse
import asyncio
import json
import os
import sys
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

from dotenv import dotenv_values  # type: ignore[import-untyped]  # noqa: E402
from gofr_common.auth.backends.vault import VaultGroupStore, VaultTokenStore  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_client import VaultClient  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_config import VaultConfig  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.groups import DuplicateGroupError, GroupRegistry  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.service import AuthService  # type: ignore[import-not-found]  # noqa: E402

from simulation.generate_synthetic_stories import SyntheticGenerator  # noqa: E402
from simulation import ingest_synthetic_stories as ingest  # noqa: E402
from simulation import load_universe_to_neo4j
from simulation import load_clients_to_neo4j

VAULT_INIT_FILE = PROJECT_ROOT / "docker" / ".vault-init.env"
DOCKER_ENV_FILE = PROJECT_ROOT / "docker" / ".env"
PORTS_ENV_FILE = PROJECT_ROOT / "lib" / "gofr-common" / "config" / "gofr_ports.env"
SIM_ENV_FILE = PROJECT_ROOT / "simulation" / ".env.synthetic"
BOOTSTRAP_TOKEN_FILE = PROJECT_ROOT / "config" / "generated" / "bootstrap_tokens.json"
DEFAULT_SOURCES = [
    "Global Wire",
    "The Daily Alpha",
    "Insider Whispers",
    "Regional Business Journal",
    "Silicon Circuits",
]
DEFAULT_GROUPS = ["apac_sales", "us_sales", "apac-sales", "us-sales"]
TOKEN_TTL_SECONDS = 86400 * 365


@dataclass
class Config:
    vault_addr: str
    vault_token: str
    jwt_secret: str
    openrouter_api_key: Optional[str]


def load_env(openrouter_key_arg: Optional[str], openrouter_file: Optional[Path]) -> Config:
    # The dev container is on gofr-net with same env as production
    # We just need Vault connection details which should already be set
    vault_token = os.environ.get("VAULT_TOKEN") or os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_ROOT_TOKEN")
    if not vault_token:
        raise RuntimeError("VAULT_TOKEN not found; ensure production environment is sourced")

    vault_addr = os.environ.get("VAULT_ADDR") or os.environ.get("GOFR_VAULT_URL")
    if not vault_addr:
        raise RuntimeError("VAULT_ADDR not set; set explicitly to the Vault service (e.g., http://gofr-vault:8201)")
    jwt_secret = os.environ.get("GOFR_JWT_SECRET") or os.environ.get("GOFR_IQ_JWT_SECRET")
    if not jwt_secret:
        raise RuntimeError("GOFR_JWT_SECRET not found; ensure production environment is sourced")

    # Load OpenRouter key: CLI arg > env var > file
    openrouter_api_key = openrouter_key_arg or os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not openrouter_api_key and openrouter_file and openrouter_file.exists():
        file_env = dotenv_values(openrouter_file)
        openrouter_api_key = file_env.get("GOFR_IQ_OPENROUTER_API_KEY")

    return Config(
        vault_addr=vault_addr,
        vault_token=vault_token,
        jwt_secret=jwt_secret,
        openrouter_api_key=openrouter_api_key,
    )


def init_auth(cfg: Config) -> AuthService:
    vault_config = VaultConfig(url=cfg.vault_addr, token=cfg.vault_token, mount_point="secret")
    client = VaultClient(vault_config)
    return AuthService(
        token_store=VaultTokenStore(client),
        group_registry=GroupRegistry(VaultGroupStore(client)),
        secret_key=cfg.jwt_secret,
    )


def ensure_groups(auth: AuthService, groups: List[str]):
    for name in groups:
        existing = auth.groups.get_group_by_name(name)
        if existing:
            continue
        try:
            auth.groups.create_group(name, description=f"Synthetic group {name}")
        except DuplicateGroupError:
            pass


def verify_groups(auth: AuthService, groups: List[str]):
    missing = []
    for name in groups:
        if auth.groups.get_group_by_name(name) is None:
            missing.append(name)
    if missing:
        raise RuntimeError(f"Missing groups: {missing}")


def mint_tokens(auth: AuthService, groups: List[str]) -> Dict[str, str]:
    tokens: Dict[str, str] = {}
    for group in groups:
        token = auth.create_token(groups=[group], expires_in_seconds=TOKEN_TTL_SECONDS)
        tokens[group] = token
    return tokens


def load_bootstrap_tokens_from_file() -> Optional[Dict[str, str]]:
    if not BOOTSTRAP_TOKEN_FILE.exists():
        return None
    data = json.loads(BOOTSTRAP_TOKEN_FILE.read_text())
    if "admin_token" in data and "public_token" in data:
        return {"admin": data["admin_token"], "public": data["public_token"]}
    return None


def load_bootstrap_tokens_from_vault(vault_addr: str, vault_token: str) -> Dict[str, str]:
    url = f"{vault_addr}/v1/secret/data/gofr/config/bootstrap-tokens/tokens"
    req = urllib.request.Request(url, headers={"X-Vault-Token": vault_token}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read())
    data = payload.get("data", {}).get("data", {})
    admin = data.get("admin_token")
    public = data.get("public_token")
    if not admin or not public:
        raise RuntimeError("Bootstrap tokens missing in Vault at secret/gofr/config/bootstrap-tokens/tokens")
    return {"admin": admin, "public": public}


def load_bootstrap_tokens(cfg) -> Dict[str, str]:
    tokens = load_bootstrap_tokens_from_file()
    if tokens:
        return tokens
    if not cfg.vault_token:
        raise RuntimeError("VAULT_TOKEN not set; cannot load bootstrap tokens from Vault")
    if not cfg.vault_addr:
        raise RuntimeError("VAULT_ADDR not set; cannot load bootstrap tokens from Vault")
    return load_bootstrap_tokens_from_vault(cfg.vault_addr, cfg.vault_token)


def fetch_vault_jwt(cfg: Config) -> str:
    url = f"{cfg.vault_addr}/v1/secret/data/gofr/config/jwt-signing-secret"
    req = urllib.request.Request(url, headers={"X-Vault-Token": cfg.vault_token}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read())
    value = payload.get("data", {}).get("data", {}).get("value")
    if not value:
        raise RuntimeError("JWT secret not found in Vault at secret/gofr/config/jwt-signing-secret")
    return value


def verify_tokens(tokens: Dict[str, str], required_groups: List[str]):
    missing = [g for g in required_groups if g not in tokens]
    if missing:
        raise RuntimeError(f"Missing tokens for groups: {missing}")


def write_sim_env(tokens: Dict[str, str], sources: List[str], openrouter_api_key: Optional[str]):
    env_lines = [
        f'GOFR_SYNTHETIC_TOKENS={json.dumps(tokens)}',
        f'GOFR_SYNTHETIC_SOURCES={json.dumps(sources)}',
    ]
    if openrouter_api_key:
        env_lines.append(f"GOFR_IQ_OPENROUTER_API_KEY={openrouter_api_key}")
    SIM_ENV_FILE.write_text("\n".join(env_lines) + "\n")


def list_sources() -> Dict[str, str]:
    # Reuse ingestion helper for parsing manage_source.sh output
    return ingest.load_sources()


def register_source(name: str, url: str, token: str):
    cmd = [
        str(PROJECT_ROOT / "scripts" / "manage_source.sh"),
        "create",
        "--docker",
        "--name",
        name,
        "--url",
        url,
        "--description",
        f"Synthetic source {name}",
        "--token",
        token,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60
    )
    if result.returncode != 0 and "already exists" not in result.stdout.lower():
        raise RuntimeError(f"Failed to register source {name}: {result.stderr or result.stdout}")


def ensure_sources(admin_token: str, expected: List[str]):
    existing = list_sources()
    to_create = [s for s in expected if s not in existing]
    if not to_create:
        return
    for src in to_create:
        normalized = src.lower().replace(" ", "")
        url = f"https://www.{normalized}.com"
        register_source(src, url, admin_token)


def generate_data(env_path: Path, count: int, output_dir: Path):
    generator = SyntheticGenerator(env_path=str(env_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    generator.generate_batch(count, output_dir)


def ingest_data(output_dir: Path, sources: Dict[str, str], tokens: Dict[str, str], verbose: bool = False):
    story_files = sorted(output_dir.glob("synthetic_*.json"))
    if not story_files:
        print(f"No documents found in {output_dir}")
        return

    # Pre-check: ensure every group used in stories has a token, and every source is known
    required_groups = set()
    required_sources = set()
    for story_file in story_files:
        try:
            import json as _json
            data = _json.loads(story_file.read_text())
            if "upload_as_group" in data:
                required_groups.add(data.get("upload_as_group"))
            if "source" in data:
                required_sources.add(data.get("source"))
        except Exception:
            continue

    missing_groups = [g for g in required_groups if g not in tokens]
    if missing_groups:
        raise RuntimeError(f"Missing tokens for groups referenced in stories: {missing_groups}")

    missing_sources = [s for s in required_sources if s not in sources]
    if missing_sources:
        raise RuntimeError(f"Sources not registered but referenced in stories: {missing_sources}")

    uploaded = 0
    failed = 0
    for idx, story_file in enumerate(story_files, 1):
        status, message, duration, _meta = ingest.process_story(
            story_file, sources, tokens, dry_run=False, verbose=verbose
        )
        prefix = f"[{idx}/{len(story_files)}] {story_file.name}"
        if status == "uploaded":
            print(f"{prefix} OK ({duration:.1f}s)")
            uploaded += 1
        elif status == "duplicate":
            print(f"{prefix} duplicate")
        else:
            print(f"{prefix} failed: {message}")
            failed += 1
    print(f"Uploaded {uploaded}, failed {failed}")


def main():
    parser = argparse.ArgumentParser(
        description="Run full simulation pipeline",
        epilog="Note: Must source production environment first: source docker/.vault-init.env && source docker/.env"
    )
    parser.add_argument("--count", type=int, default=10, help="Stories to generate")
    parser.add_argument("--output", type=Path, default=Path("simulation/test_output"), help="Output directory")
    parser.add_argument("--skip-generate", action="store_true", help="Skip generation and reuse existing files in output directory")
    parser.add_argument("--skip-universe", action="store_true", help="Skip loading universe (companies/relationships) to Neo4j")
    parser.add_argument("--skip-clients", action="store_true", help="Skip generating and loading clients to Neo4j")
    parser.add_argument("--init-groups-only", action="store_true", help="Create/verify groups then stop")
    parser.add_argument("--init-tokens-only", action="store_true", help="Create/verify tokens (and groups) then stop")
    parser.add_argument("--mint-tokens", action="store_true", help="Mint fresh tokens for all groups (admin/public remain bootstrap tokens)")
    parser.add_argument("--openrouter-key", type=str, help="OpenRouter API key (overrides env/file)")
    parser.add_argument(
        "--openrouter-key-file",
        type=Path,
        default=Path("simulation/.env.openrouter"),
        help="Path to temp env file containing GOFR_IQ_OPENROUTER_API_KEY",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose ingestion output")
    args = parser.parse_args()

    # Simulation runs in dev container on gofr-net - use same config as production services
    # All environment variables should already be set by docker-compose.yml or start-prod.sh
    
    cfg = load_env(args.openrouter_key, args.openrouter_key_file)
    vault_jwt = fetch_vault_jwt(cfg)
    if cfg.jwt_secret != vault_jwt:
        raise RuntimeError("GOFR_JWT_SECRET does not match Vault jwt-signing-secret; aborting.")
    auth = init_auth(cfg)

    ensure_groups(auth, DEFAULT_GROUPS)
    verify_groups(auth, DEFAULT_GROUPS)

    if args.init_groups_only:
        print("Groups created and verified; exiting (--init-groups-only)")
        return

    bootstrap_tokens = load_bootstrap_tokens(cfg)

    if args.mint_tokens:
        tokens = mint_tokens(auth, DEFAULT_GROUPS + ["admin", "public"])
    else:
        tokens = mint_tokens(auth, DEFAULT_GROUPS)
        tokens.update(bootstrap_tokens)

    verify_tokens(tokens, DEFAULT_GROUPS + ["admin", "public"])
    
    # Always ensure sources exist before any generation or ingestion
    ensure_sources(tokens["admin"], DEFAULT_SOURCES)
    write_sim_env(tokens, DEFAULT_SOURCES, cfg.openrouter_api_key)

    if args.init_tokens_only:
        print("Groups, tokens, and sources created/verified; .env.synthetic written; exiting (--init-tokens-only)")
        return

    # 1. Load Universe (Graph Topology)
    if not args.skip_universe:
        print("Loading Universe to Neo4j...")
        load_universe_to_neo4j.load_universe()

    # 2. Load Clients (Signal Receivers)
    if not args.skip_clients:
        print("Loading Clients to Neo4j...")
        # Optional: Generate clients file first?
        # The load_clients script calls ClientGenerator internally, so we just run it.
        load_clients_to_neo4j.load_clients()

    # 3. Generate Stories (Signal/Noise)
    if args.skip_generate:
        if not args.output.exists() or not any(args.output.glob("synthetic_*.json")):
            print(f"skip-generate set, but no existing synthetic_*.json in {args.output}")
            sys.exit(1)
        print(f"Reusing existing documents in {args.output}")
    else:
        generate_data(SIM_ENV_FILE, args.count, args.output)

    # 4. Ingest Stories
    sources = list_sources()
    ingest_data(args.output, sources, tokens, verbose=args.verbose)


if __name__ == "__main__":
    main()
