#!/usr/bin/env python3
"""
End-to-end simulation runner.
- Creates required groups/tokens in Vault
- Registers sources if missing
- Generates synthetic stories
- Ingests generated stories
"""
import argparse
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

# SSOT: Import env module for bootstrap tokens
from gofr_common.gofr_env import get_admin_token, get_public_token, GofrEnvError  # noqa: E402 - path modification required before import

from gofr_common.auth.backends.vault import VaultGroupStore, VaultTokenStore  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_client import VaultClient  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_config import VaultConfig  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.groups import GroupRegistry  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.service import AuthService  # type: ignore[import-not-found]  # noqa: E402

from simulation.generate_synthetic_stories import SyntheticGenerator, MOCK_SOURCES  # noqa: E402
from simulation import ingest_synthetic_stories as ingest  # noqa: E402
from simulation import load_simulation_data  # noqa: E402

SECRETS_DIR = PROJECT_ROOT / "secrets"
DOCKER_ENV_FILE = PROJECT_ROOT / "docker" / ".env"
PORTS_ENV_FILE = PROJECT_ROOT / "lib" / "gofr-common" / "config" / "gofr_ports.env"
BOOTSTRAP_TOKEN_FILE = SECRETS_DIR / "bootstrap_tokens.json"
TOKEN_TTL_SECONDS = 86400 * 365


@dataclass
class Config:
    vault_addr: str
    vault_token: str
    jwt_secret: str
    openrouter_api_key: Optional[str]


def load_env(
    openrouter_key_arg: Optional[str],
    openrouter_file: Optional[Path],
    env_file: Path,
    secrets_dir: Path,
    ports_file: Path,
) -> Config:
    """Load env/secrets and fetch required secrets from Vault.

    Order of precedence:
    1) CLI args for OpenRouter key
    2) Existing environment
    3) Env files (ports, docker/.env)
    4) Vault fetch for JWT / Neo4j / OpenRouter
    """

    def merge_env_file(path: Path):
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)

    # Merge env files (ports first, then docker env)
    merge_env_file(ports_file)
    merge_env_file(env_file)

    # Simulation requires root token for admin operations (creating groups, fetching secrets)
    # Always prefer the root token from secrets file over any env var (which may be AppRole token)
    token_path = secrets_dir / "vault_root_token"
    if token_path.exists():
        vault_token = token_path.read_text().strip()
        os.environ["VAULT_TOKEN"] = vault_token  # Override any existing env var
    else:
        vault_token = os.environ.get("VAULT_TOKEN") or os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_ROOT_TOKEN")
    if not vault_token:
        raise RuntimeError("VAULT_TOKEN not found; ensure scripts/start-prod.sh was run")

    # Compute Vault address
    vault_addr = os.environ.get("VAULT_ADDR") or os.environ.get("GOFR_VAULT_URL")
    if not vault_addr:
        port = os.environ.get("GOFR_VAULT_PORT", "8201")
        vault_addr = f"http://gofr-vault:{port}"
    os.environ["VAULT_ADDR"] = vault_addr

    # Helpers to fetch secrets from Vault via docker exec (shared container)
    def fetch_secret(secret_path: str, field: str = "value") -> str:
        try:
            cmd = [
                "docker",
                "exec",
                "-e",
                "VAULT_ADDR=http://127.0.0.1:8201",
                "-e",
                f"VAULT_TOKEN={vault_token}",
                "gofr-vault",
                "vault",
                "kv",
                "get",
                f"-field={field}",
                secret_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            return result.stdout.strip()
        except Exception as exc:
            raise RuntimeError(f"Vault fetch failed for {secret_path}: {exc}")

    # JWT
    jwt_secret = os.environ.get("GOFR_JWT_SECRET") or os.environ.get("GOFR_IQ_JWT_SECRET")
    if not jwt_secret:
        jwt_secret = fetch_secret("secret/gofr/config/jwt-signing-secret")
        os.environ["GOFR_JWT_SECRET"] = jwt_secret
        os.environ["GOFR_IQ_JWT_SECRET"] = jwt_secret

    # Neo4j password
    neo4j_password = os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    if not neo4j_password:
        neo4j_password = fetch_secret("secret/gofr/config/neo4j-password")
        os.environ["GOFR_IQ_NEO4J_PASSWORD"] = neo4j_password

    # OpenRouter key
    openrouter_api_key = openrouter_key_arg or os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not openrouter_api_key and openrouter_file and openrouter_file.exists():
        for line in openrouter_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key == "GOFR_IQ_OPENROUTER_API_KEY":
                openrouter_api_key = value
                break
    if not openrouter_api_key:
        openrouter_api_key = fetch_secret("secret/gofr/config/api-keys/openrouter")
    os.environ["GOFR_IQ_OPENROUTER_API_KEY"] = openrouter_api_key

    # Infra defaults if missing
    os.environ.setdefault("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687")
    os.environ.setdefault("GOFR_IQ_NEO4J_USER", "neo4j")
    os.environ.setdefault("GOFR_IQ_CHROMADB_HOST", "gofr-chromadb")
    os.environ.setdefault("GOFR_IQ_CHROMADB_PORT", "8000")

    return Config(
        vault_addr=vault_addr,
        vault_token=vault_token,
        jwt_secret=jwt_secret,
        openrouter_api_key=openrouter_api_key,
    )


def discover_simulation_requirements() -> tuple:
    """
    Introspect simulation configuration to discover required groups and sources.
    
    For now, simplified to only use group-simulation.
    
    Returns:
        (groups, sources) - Lists of group names and source names needed for simulation
    """
    # Simplified: Just use group-simulation for all simulation data
    groups = ["group-simulation"]
    sources = []
    
    # Discover sources from story generator source registry
    try:
        sources = [s.name for s in MOCK_SOURCES]
    except Exception as e:
        print(f"⚠️  Could not discover sources from generator: {e}")
        sources = ["Global Wire", "The Daily Alpha", "Insider Whispers", 
                   "Regional Business Journal", "Silicon Circuits"]  # Fallback
    
    return groups, sources


def check_infrastructure() -> None:
    """Pre-flight infrastructure health checks with positive affirmations."""
    import http.client
    import socket
    
    print("🏥 Pre-flight infrastructure checks...")
    
    checks = {
        "Neo4j": (os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687"), "bolt"),
        "ChromaDB": (f"{os.environ.get('GOFR_IQ_CHROMADB_HOST', 'gofr-chromadb')}:{os.environ.get('GOFR_IQ_CHROMADB_PORT', '8000')}", "http"),
        "Vault": (os.environ.get("VAULT_ADDR", "http://gofr-vault:8201"), "http"),
    }
    
    all_ok = True
    for name, (uri, proto) in checks.items():
        try:
            if proto == "bolt":
                # Simple TCP check for Neo4j
                host, port = uri.replace("bolt://", "").split(":")
                sock = socket.create_connection((host, int(port)), timeout=2)
                sock.close()
                print(f"   ✅ {name:15s} reachable at {uri}")
            elif proto == "http":
                # HTTP HEAD or GET check
                parsed = uri.replace("http://", "").replace("https://", "")
                host_port = parsed.split("/")[0]
                if ":" in host_port:
                    host, port = host_port.split(":")
                else:
                    host, port = host_port, "80"
                conn = http.client.HTTPConnection(host, int(port), timeout=2)
                conn.request("HEAD", "/")
                conn.getresponse()  # Verify connection succeeds
                conn.close()
                print(f"   ✅ {name:15s} responding at {uri}")
        except Exception as e:
            print(f"   ❌ {name:15s} NOT REACHABLE: {e}")
            all_ok = False
    
    if not all_ok:
        raise RuntimeError("Infrastructure checks failed. Ensure all services are running.")
    print("✨ All infrastructure services ready.\n")


def validate_ingestion(expected_count: int) -> None:
    """Post-ingestion validation: check Neo4j and ChromaDB counts, verify graph relationships."""
    from neo4j import GraphDatabase
    import chromadb
    
    neo4j_uri = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687")
    neo4j_user = os.environ.get("GOFR_IQ_NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    chroma_host = os.environ.get("GOFR_IQ_CHROMADB_HOST", "gofr-chromadb")
    chroma_port = int(os.environ.get("GOFR_IQ_CHROMADB_PORT", "8000"))
    
    try:
        # Neo4j: count Document nodes
        if neo4j_password is None:
            print("   ⚠️  Neo4j password not set")
            return
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        with driver.session() as session:
            result = session.run("MATCH (d:Document) RETURN count(d) as count")
            record = result.single()
            neo4j_count = record["count"] if record else 0
        
        # ChromaDB: count documents in collection
        chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        collection = chroma_client.get_or_create_collection("documents")
        chroma_count = collection.count()
        
        print(f"   Neo4j Documents:  {neo4j_count}")
        print(f"   ChromaDB Entries: {chroma_count}")
        
        # Warn if counts seem too low
        if neo4j_count < expected_count:
            print(f"   ⚠️  Neo4j count ({neo4j_count}) less than expected ({expected_count})")
        else:
            print("   ✅ Neo4j ingestion verified")
        
        if chroma_count < expected_count:
            print(f"   ⚠️  ChromaDB count ({chroma_count}) less than expected ({expected_count})")
        else:
            print("   ✅ ChromaDB ingestion verified")
        
        # Validate graph relationships
        print("\n🔗 Validating graph relationships...")
        
        with driver.session() as session:
            # Check PRODUCED_BY relationships
            result = session.run("MATCH ()-[r:PRODUCED_BY]->() RETURN count(r) as count")
            record = result.single()
            produced_by_count = record["count"] if record else 0
            
            # Check AFFECTS relationships
            result = session.run("MATCH ()-[r:AFFECTS]->() RETURN count(r) as count")
            record = result.single()
            affects_count = record["count"] if record else 0
            
            # Check MENTIONS relationships
            result = session.run("MATCH ()-[r:MENTIONS]->() RETURN count(r) as count")
            record = result.single()
            mentions_count = record["count"] if record else 0
            
            # Check TRIGGERED_BY relationships
            result = session.run("MATCH ()-[r:TRIGGERED_BY]->() RETURN count(r) as count")
            record = result.single()
            triggered_by_count = record["count"] if record else 0
            
            # Check Source nodes
            result = session.run("MATCH (s:Source) RETURN count(s) as count")
            record = result.single()
            source_count = record["count"] if record else 0
            
            print(f"   Sources:      {source_count}")
            print(f"   PRODUCED_BY:  {produced_by_count} (documents → sources)")
            print(f"   AFFECTS:      {affects_count} (documents → instruments)")
            print(f"   MENTIONS:     {mentions_count} (documents → companies)")
            print(f"   TRIGGERED_BY: {triggered_by_count} (documents → event types)")
            
            # Warnings for missing relationships
            if produced_by_count == 0:
                print("   ⚠️  No PRODUCED_BY relationships - documents not linked to sources")
            elif produced_by_count < neo4j_count:
                print(f"   ⚠️  Only {produced_by_count}/{neo4j_count} documents linked to sources")
            else:
                print("   ✅ All documents linked to sources")
            
            if affects_count == 0:
                print("   ⚠️  No AFFECTS relationships - check graph extraction")
            else:
                print(f"   ✅ Graph extraction working ({affects_count} instrument impacts)")
            
            if mentions_count == 0:
                print("   ⚠️  No MENTIONS relationships - multi-entity tracking disabled")
            else:
                print(f"   ✅ Company mentions tracked ({mentions_count} secondary references)")
            
            if triggered_by_count == 0:
                print("   ⚠️  No TRIGGERED_BY relationships - event filtering disabled")
            else:
                print(f"   ✅ Event categorization working ({triggered_by_count} event triggers)")
        
        driver.close()
            
    except Exception as e:
        print(f"   ⚠️  Could not validate ingestion: {e}")
        print("   (This is informational; ingestion may still have succeeded)")


def init_auth(cfg: Config) -> AuthService:
    vault_config = VaultConfig(url=cfg.vault_addr, token=cfg.vault_token, mount_point="secret")
    client = VaultClient(vault_config)
    return AuthService(
        token_store=VaultTokenStore(client),
        group_registry=GroupRegistry(VaultGroupStore(client)),
        secret_key=cfg.jwt_secret,
    )


def ensure_groups(auth: AuthService, groups: List[str]):
    """
    Ensure groups exist and are active using auth_manager.sh.
    Restores defunct groups if needed.
    """
    import os
    import subprocess
    
    # Get admin token from environment
    admin_token = os.environ.get("ADMIN_TOKEN")
    if not admin_token:
        # Try to load from bootstrap tokens
        bootstrap = load_bootstrap_tokens_from_file()
        if bootstrap:
            admin_token = bootstrap.get("admin")
    
    if not admin_token:
        raise RuntimeError("Cannot ensure groups: ADMIN_TOKEN not found")
    
    for name in groups:
        # Use auth_manager.sh to create/restore group
        # auth_manager.sh will restore if defunct, create if missing, or report if active
        # All cases are success for our purposes
        subprocess.run(
            [
                "./lib/gofr-common/scripts/auth_manager.sh",
                "--docker",
                "groups",
                "create",
                name,
                "--description",
                f"Synthetic group {name}",
            ],
            capture_output=True,
            text=True,
        )


def verify_groups(auth: AuthService, groups: List[str]):
    missing = []
    for name in groups:
        if auth.groups.get_group_by_name(name) is None:
            missing.append(name)
    if missing:
        raise RuntimeError(f"Missing groups: {missing}")


def mint_tokens(auth: AuthService, groups: List[str]) -> Dict[str, str]:
    """
    Create fresh tokens for each group with unique names.
    Each simulation run gets new tokens to avoid stale/revoked token issues.
    """
    import random
    import time
    
    tokens: Dict[str, str] = {}
    # Use timestamp + random for uniqueness
    run_id = int(time.time() * 1000) % 100000
    
    for group in groups:
        # Create unique token name with timestamp-based suffix
        token_suffix = run_id + random.randint(0, 999)
        token_name = f"sim-{group.replace('_', '-')}-{token_suffix}"
        
        # Always create new token (don't reuse existing)
        token = auth.create_token(
            groups=[group],
            expires_in_seconds=TOKEN_TTL_SECONDS,
            name=token_name,
        )
        tokens[group] = token
    return tokens


def load_bootstrap_tokens_from_file() -> Optional[Dict[str, str]]:
    """Load bootstrap tokens via SSOT module."""
    try:
        admin = get_admin_token()
        public = get_public_token()
        return {"admin": admin, "public": public}
    except GofrEnvError:
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


def save_simulation_tokens(tokens: Dict[str, str], group_names: List[str]):
    """
    Save minted group tokens to simulation/tokens.json for later use/testing.
    
    This allows:
    1. Document ingestion to use group-specific tokens (not admin)
    2. Manual testing with saved JWT tokens
    3. Token reuse across simulation runs
    
    Saves group tokens + admin bootstrap token for reference.
    Does NOT save public token (not used in simulation).
    """
    token_file = PROJECT_ROOT / "simulation" / "tokens.json"
    
    # Build token map: group tokens + admin reference
    saved_tokens = {}
    for group in group_names:
        if group in tokens:
            saved_tokens[group] = tokens[group]
    
    # Add admin bootstrap token for reference (source management operations)
    if "admin" in tokens:
        saved_tokens["admin"] = tokens["admin"]
    
    # Write to file with pretty formatting
    with open(token_file, "w") as f:
        json.dump(saved_tokens, f, indent=2)
    
    print(f"   💾 Saved {len(saved_tokens)} tokens to simulation/tokens.json")
    print(f"      Groups: {', '.join(sorted(saved_tokens.keys()))}")


def list_sources(token: str) -> Dict[str, str]:
    # Reuse ingestion helper for parsing manage_source.sh output
    return ingest.load_sources(token)


def register_source(name: str, url: str, token: str, trust_level: int | None = None):
    """Register a source via manage_source.sh with optional trust level."""
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
    # Add trust level if provided
    if trust_level is not None:
        cmd.extend(["--trust-level", str(trust_level)])
    
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60
    )
    if result.returncode != 0 and "already exists" not in result.stdout.lower():
        raise RuntimeError(f"Failed to register source {name}: {result.stderr or result.stdout}")


def register_mock_sources_via_script(admin_token: str):
    """Register MOCK_SOURCES using manage_source.sh with proper trust levels."""
    from simulation.generate_synthetic_stories import MOCK_SOURCES
    
    print(f"   📋 Registering {len(MOCK_SOURCES)} mock sources via manage_source.sh...")
    created = 0
    existing = 0
    
    for mock_src in MOCK_SOURCES:
        # Create source using manage_source.sh with trust level
        normalized = mock_src.name.lower().replace(" ", "")
        url = f"https://www.{normalized}.com"
        
        cmd = [
            str(PROJECT_ROOT / "scripts" / "manage_source.sh"),
            "create",
            "--docker",
            "--name",
            mock_src.name,
            "--url",
            url,
            "--trust-level",
            str(mock_src.trust_level),
            "--token",
            admin_token,
        ]
        
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60
        )
        
        output = result.stdout + result.stderr
        
        # Check for "already exists" message first (MCP API returns this)
        if "already exists" in output.lower():
            existing += 1
            # Don't print - we don't want to spam the output
        elif result.returncode == 0:
            print(f"   ✓ {mock_src.name}: created (trust={mock_src.trust_level})")
            created += 1
        else:
            print(f"   ✗ {mock_src.name}: failed - {output[:200]}")
    
    print(f"   ✅ Created {created} sources, {existing} already existed")
    return created + existing


def ensure_sources(admin_token: str, expected: List[str] | None = None):
    """Ensure sources exist in MCP registry and Neo4j graph.
    
    Args:
        admin_token: Admin JWT token
        expected: Optional list of source names (legacy - will use MOCK_SOURCES instead)
    """
    # Register MOCK_SOURCES with proper trust levels via manage_source.sh
    # Sources are now automatically synced to Neo4j by SourceRegistry
    register_mock_sources_via_script(admin_token)
    print("   ✓ Sources registered via MCP and synced to Neo4j")


def count_existing_documents(output_dir: Path) -> int:
    """Count existing synthetic story files in output directory."""
    if not output_dir.exists():
        return 0
    return len(list(output_dir.glob("synthetic_*.json")))


def save_generation_metadata(output_dir: Path, count: int, model: str = "default"):
    """Save metadata about generated documents for cache validation."""
    metadata = {
        "count": count,
        "model": model,
        "timestamp": __import__('time').time(),
        "version": "1.0"
    }
    metadata_file = output_dir / ".generation_metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2))


def load_generation_metadata(output_dir: Path) -> Optional[dict]:
    """Load metadata about previously generated documents."""
    metadata_file = output_dir / ".generation_metadata.json"
    if not metadata_file.exists():
        return None
    try:
        return json.loads(metadata_file.read_text())
    except Exception:
        return None


def generate_data(count: int, output_dir: Path, regenerate: bool = False, model: Optional[str] = None):
    """Generate synthetic stories using SSOT module for token access.
    
    Args:
        count: Number of stories to generate
        output_dir: Directory to save generated stories
        regenerate: If False, reuse existing stories if count matches; if True, always generate new
        model: Optional LLM model name override
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if we can reuse existing documents
    if not regenerate:
        existing_count = count_existing_documents(output_dir)
        metadata = load_generation_metadata(output_dir)
        
        if existing_count >= count:
            if metadata and metadata.get("count") == existing_count:
                print(f"   ♻️  Reusing {existing_count} existing documents (use --regenerate to force new generation)")
                print(f"      Generated: {__import__('datetime').datetime.fromtimestamp(metadata.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}")
                return
            else:
                print(f"   ♻️  Found {existing_count} existing documents (requesting {count})")
                if existing_count > count:
                    print(f"      Will use the {count} most recent documents")
                    return
        elif existing_count > 0:
            print(f"   ⚠️  Found {existing_count} existing documents, but need {count}")
            print(f"      Generating {count - existing_count} additional documents...")
    
    # Generate new documents
    generator = SyntheticGenerator(model=model)
    generator.generate_batch(count, output_dir)
    save_generation_metadata(output_dir, count)


def ingest_data(output_dir: Path, sources: Dict[str, str], tokens: Dict[str, str], count: Optional[int] = None, verbose: bool = False):
    """Ingest stories from output directory. If count is specified, only process the most recent count files."""
    story_files = sorted(output_dir.glob("synthetic_*.json"), reverse=True)  # Newest first
    
    if count and count > 0:
        story_files = story_files[:count]
        print(f"Limiting ingestion to {count} most recent stories")
    
    if not story_files:
        print(f"No documents found in {output_dir}")
        return
    
    # Re-sort by name for stable processing order
    story_files = sorted(story_files)

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
            story_file, sources, dry_run=False, verbose=verbose
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
    
    print(f"\n📊 Ingestion complete: {uploaded} uploaded, {failed} failed")
    
    # Post-ingestion validation
    if uploaded > 0:
        print("\n🔍 Validating ingestion results...")
        validate_ingestion(expected_count=uploaded)


def main():
    parser = argparse.ArgumentParser(
        description="Run full simulation pipeline",
        epilog="Note: Run via ./simulation/run_simulation.sh which loads secrets from secrets/ directory"
    )
    parser.add_argument("--count", type=int, default=10, help="Stories to generate (0 = no generation/ingestion)")
    parser.add_argument("--output", type=Path, default=Path("simulation/test_output"), help="Output directory")
    parser.add_argument("--skip-generate", action="store_true", help="Skip generation and reuse existing files in output directory")
    parser.add_argument("--ingest-only", action="store_true", help="Only ingest existing documents (alias for --skip-generate)")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingestion stage")
    parser.add_argument("--validate-only", action="store_true", help="Run setup/validations only (implies --count 0, skip gen/ingest)")
    parser.add_argument("--regenerate", action="store_true", help="Force regeneration of stories even if cached versions exist")
    parser.add_argument("--skip-universe", action="store_true", help="Skip loading universe (companies/relationships) to Neo4j")
    parser.add_argument("--skip-clients", action="store_true", help="Skip generating and loading clients to Neo4j")
    parser.add_argument("--init-groups-only", action="store_true", help="Create/verify groups then stop")
    parser.add_argument("--init-tokens-only", action="store_true", help="Create/verify tokens (and groups) then stop")
    parser.add_argument("--mint-tokens", action="store_true", help="Mint fresh tokens for all groups (admin/public remain bootstrap tokens)")
    parser.add_argument("--model", type=str, default=None, help="LLM model name for story generation (default: $GOFR_IQ_LLM_MODEL or config default)")
    parser.add_argument("--openrouter-key", type=str, help="OpenRouter API key (overrides env/file)")
    parser.add_argument(
        "--openrouter-key-file",
        type=Path,
        default=Path("simulation/.env.openrouter"),
        help="Path to temp env file containing GOFR_IQ_OPENROUTER_API_KEY",
    )
    parser.add_argument("--env-file", type=Path, default=Path("docker/.env"), help="Path to docker env file (default: docker/.env)")
    parser.add_argument("--secrets-dir", type=Path, default=Path("secrets"), help="Path to secrets directory (default: secrets/)")
    parser.add_argument("--ports-file", type=Path, default=Path("lib/gofr-common/config/gofr_ports.env"), help="Path to ports env file")
    parser.add_argument("--verbose", action="store_true", help="Verbose ingestion output")
    args = parser.parse_args()

    # Derive effective flow flags
    effective_count = args.count
    skip_generate = args.skip_generate or args.ingest_only  # ingest-only implies skip-generate
    skip_ingest = args.skip_ingest

    if args.validate_only:
        effective_count = 0
        skip_generate = True
        skip_ingest = True

    if effective_count == 0:
        skip_generate = True
        skip_ingest = True

    env_path = args.env_file if args.env_file.is_absolute() else PROJECT_ROOT / args.env_file
    secrets_dir = args.secrets_dir if args.secrets_dir.is_absolute() else PROJECT_ROOT / args.secrets_dir
    ports_path = args.ports_file if args.ports_file.is_absolute() else PROJECT_ROOT / args.ports_file

    cfg = load_env(
        args.openrouter_key,
        args.openrouter_key_file,
        env_path,
        secrets_dir,
        ports_path,
    )
    
    # Pre-flight checks
    check_infrastructure()
    
    # ========================================================================
    # DISCOVER REQUIREMENTS FROM SIMULATION CONFIG
    # ========================================================================
    print("📋 Discovering simulation requirements...")
    required_groups, required_sources = discover_simulation_requirements()
    print(f"   Groups needed: {required_groups}")
    print(f"   Sources needed: {required_sources}")
    
    # SSOT: Trust JWT from environment (sourced from docker/.env by run_simulation.sh)
    # The shell wrapper already validated JWT exists; no need to re-fetch from Vault
    if not cfg.jwt_secret:
        raise RuntimeError("GOFR_JWT_SECRET not set; run via ./simulation/run_simulation.sh")
    auth = init_auth(cfg)

    # Create groups BEFORE loading universe (universe references simulation-group)
    ensure_groups(auth, required_groups)
    verify_groups(auth, required_groups)

    if args.init_groups_only:
        print("Groups created and verified; exiting (--init-groups-only)")
        return

    bootstrap_tokens = load_bootstrap_tokens(cfg)

    # Mint fresh tokens for simulation groups only
    # Admin/public come from bootstrap (long-lived)
    tokens = mint_tokens(auth, required_groups)
    tokens.update(bootstrap_tokens)  # Add admin and public from bootstrap

    verify_tokens(tokens, required_groups + ["admin", "public"])
    
    # Save tokens (group-simulation + admin) to simulation/tokens.json for later use/testing
    # This allows document ingestion to use group-specific tokens instead of admin
    save_simulation_tokens(tokens, required_groups)
    
    run_gate("auth")
    
    # Ensure sources exist BEFORE any generation or ingestion
    ensure_sources(tokens["admin"], required_sources)
    run_gate("sources")

    if args.init_tokens_only:
        print("Groups, tokens, and sources created/verified; exiting (--init-tokens-only)")
        return

    load_universe_flag = not args.skip_universe
    load_clients_flag = not args.skip_clients

    if load_universe_flag or load_clients_flag:
        print(f"Loading simulation data into Neo4j (universe={load_universe_flag}, clients={load_clients_flag})...")
        load_simulation_data.load_simulation_data(
            load_universe=load_universe_flag,
            load_clients=load_clients_flag,
        )
        if load_universe_flag:
            run_gate("universe")
        if load_clients_flag:
            run_gate("clients")
    else:
        print("Skipping universe/client load (--skip-universe and --skip-clients)")

    # 3. Generate Stories (Signal/Noise)
    if skip_generate:
        if not args.output.exists() or not any(args.output.glob("synthetic_*.json")):
            print(f"skip-generate set, but no existing synthetic_*.json in {args.output}")
            sys.exit(1)
        print(f"Reusing existing documents in {args.output}")
    else:
        generate_data(effective_count, args.output, regenerate=args.regenerate, model=args.model)
        run_gate("generation")

    # 4. Ingest Stories
    if skip_ingest:
        print("Skipping ingestion stage (skip-ingest or count=0)")
    else:
        sources = list_sources(tokens["admin"])
        ingest_count = None if skip_generate else effective_count
        ingest_data(args.output, sources, tokens, count=ingest_count, verbose=args.verbose)
        run_gate("ingestion")


def run_gate(gate_name: str):
    """Run stage gate check."""
    import subprocess
    print(f"   🔍 Verifying {gate_name.upper()} gate...")
    res = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "simulation/validate_simulation.py"), "--gate", gate_name], 
        capture_output=True, text=True
    )
    if res.returncode != 0:
        print(f"❌ Gate '{gate_name}' FAILED:")
        print(res.stdout)
        print(res.stderr)
        sys.exit(1)
    else:
        print(f"   ✅ Gate '{gate_name}' PASSED")


if __name__ == "__main__":
    main()

