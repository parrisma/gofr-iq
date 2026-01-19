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

# SSOT: Import env module for bootstrap tokens
from lib.gofr_common.gofr_env import get_admin_token, get_public_token, GofrEnvError

from gofr_common.auth.backends.vault import VaultGroupStore, VaultTokenStore  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_client import VaultClient  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.backends.vault_config import VaultConfig  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.groups import DuplicateGroupError, GroupRegistry  # type: ignore[import-not-found]  # noqa: E402
from gofr_common.auth.service import AuthService  # type: ignore[import-not-found]  # noqa: E402

from simulation.generate_synthetic_stories import SyntheticGenerator, MOCK_SOURCES  # noqa: E402
from simulation import ingest_synthetic_stories as ingest  # noqa: E402
from simulation import load_simulation_data
from simulation.universe.builder import UniverseBuilder  # noqa: E402

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

    # Load OpenRouter key: CLI arg > env var (no file fallback; SSOT via Vault-derived env)
    openrouter_api_key = openrouter_key_arg or os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise RuntimeError("GOFR_IQ_OPENROUTER_API_KEY not found; ensure Vault-derived env is loaded")

    return Config(
        vault_addr=vault_addr,
        vault_token=vault_token,
        jwt_secret=jwt_secret,
        openrouter_api_key=openrouter_api_key,
    )


def discover_simulation_requirements() -> tuple:
    """
    Introspect simulation configuration to discover required groups and sources.
    
    Returns:
        (groups, sources) - Lists of group names and source names needed for simulation
    """
    groups = []
    sources = []
    
    # Discover groups from universe builder
    try:
        universe = UniverseBuilder()
        default_group = universe.get_default_group()
        groups.append(default_group["guid"])  # "group-simulation"
    except Exception as e:
        print(f"⚠️  Could not discover groups from universe: {e}")
        groups.append("group-simulation")  # Fallback
    
    # Discover sources from story generator source registry
    try:
        sources = [s.name for s in MOCK_SOURCES]
    except Exception as e:
        print(f"⚠️  Could not discover sources from generator: {e}")
        sources = ["Global Wire", "The Daily Alpha", "Insider Whispers", 
                   "Regional Business Journal", "Silicon Circuits"]  # Fallback
    
    # Add standard groups for backwards compatibility (can remove if not needed)
    additional_groups = ["apac_sales", "us_sales", "apac-sales", "us-sales"]
    groups.extend(additional_groups)
    
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
                resp = conn.getresponse()
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
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        with driver.session() as session:
            result = session.run("MATCH (d:Document) RETURN count(d) as count")
            neo4j_count = result.single()["count"]
        
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
            print(f"   ✅ Neo4j ingestion verified")
        
        if chroma_count < expected_count:
            print(f"   ⚠️  ChromaDB count ({chroma_count}) less than expected ({expected_count})")
        else:
            print(f"   ✅ ChromaDB ingestion verified")
        
        # Validate graph relationships
        print("\n🔗 Validating graph relationships...")
        
        with driver.session() as session:
            # Check PRODUCED_BY relationships
            result = session.run("MATCH ()-[r:PRODUCED_BY]->() RETURN count(r) as count")
            produced_by_count = result.single()["count"]
            
            # Check AFFECTS relationships
            result = session.run("MATCH ()-[r:AFFECTS]->() RETURN count(r) as count")
            affects_count = result.single()["count"]
            
            # Check MENTIONS relationships
            result = session.run("MATCH ()-[r:MENTIONS]->() RETURN count(r) as count")
            mentions_count = result.single()["count"]
            
            # Check TRIGGERED_BY relationships
            result = session.run("MATCH ()-[r:TRIGGERED_BY]->() RETURN count(r) as count")
            triggered_by_count = result.single()["count"]
            
            # Check Source nodes
            result = session.run("MATCH (s:Source) RETURN count(s) as count")
            source_count = result.single()["count"]
            
            print(f"   Sources:      {source_count}")
            print(f"   PRODUCED_BY:  {produced_by_count} (documents → sources)")
            print(f"   AFFECTS:      {affects_count} (documents → instruments)")
            print(f"   MENTIONS:     {mentions_count} (documents → companies)")
            print(f"   TRIGGERED_BY: {triggered_by_count} (documents → event types)")
            
            # Warnings for missing relationships
            if produced_by_count == 0:
                print(f"   ⚠️  No PRODUCED_BY relationships - documents not linked to sources")
            elif produced_by_count < neo4j_count:
                print(f"   ⚠️  Only {produced_by_count}/{neo4j_count} documents linked to sources")
            else:
                print(f"   ✅ All documents linked to sources")
            
            if affects_count == 0:
                print(f"   ⚠️  No AFFECTS relationships - check graph extraction")
            else:
                print(f"   ✅ Graph extraction working ({affects_count} instrument impacts)")
            
            if mentions_count == 0:
                print(f"   ⚠️  No MENTIONS relationships - multi-entity tracking disabled")
            else:
                print(f"   ✅ Company mentions tracked ({mentions_count} secondary references)")
            
            if triggered_by_count == 0:
                print(f"   ⚠️  No TRIGGERED_BY relationships - event filtering disabled")
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
        # Normalize group name for token naming (replace underscores with hyphens)
        token_name = f"sim-{group.replace('_', '-')}"
        
        # Check if token already exists
        existing_record = auth.get_token_by_name(token_name)
        if existing_record:
            # Reconstruct JWT from existing record
            import jwt
            payload = {
                "jti": str(existing_record.id),
                "groups": existing_record.groups,
                "iat": int(existing_record.created_at.timestamp()),
                "exp": int(existing_record.expires_at.timestamp()) if existing_record.expires_at else None,
                "nbf": int(existing_record.created_at.timestamp()),
                "aud": "gofr-api",
            }
            token = jwt.encode(payload, auth.secret_key, algorithm="HS256")
        else:
            # Create new token
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


def list_sources(token: str) -> Dict[str, str]:
    # Reuse ingestion helper for parsing manage_source.sh output
    return ingest.load_sources(token)


def register_source(name: str, url: str, token: str, trust_level: int = None):
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


def ensure_sources(admin_token: str, expected: List[str] = None):
    """Ensure sources exist in MCP registry and Neo4j graph.
    
    Args:
        admin_token: Admin JWT token
        expected: Optional list of source names (legacy - will use MOCK_SOURCES instead)
    """
    # Register MOCK_SOURCES with proper trust levels via manage_source.sh
    register_mock_sources_via_script(admin_token)
    
    # After ensuring sources exist in MCP, load them into Neo4j graph
    print("   📊 Loading sources into Neo4j graph...")
    try:
        from simulation import load_sources_to_neo4j
        source_count, rel_count = load_sources_to_neo4j.load_sources_to_neo4j()
        print(f"   ✓ Neo4j: {source_count} Source nodes, {rel_count} PRODUCED_BY relationships")
    except Exception as e:
        print(f"   ⚠️  Warning: Could not load sources to Neo4j: {e}")
        print("      Sources exist in MCP registry but may not be queryable in graph")


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


def generate_data(count: int, output_dir: Path, regenerate: bool = False):
    """Generate synthetic stories using SSOT module for token access.
    
    Args:
        count: Number of stories to generate
        output_dir: Directory to save generated stories
        regenerate: If False, reuse existing stories if count matches; if True, always generate new
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
    generator = SyntheticGenerator()
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
    parser.add_argument("--count", type=int, default=10, help="Stories to generate")
    parser.add_argument("--output", type=Path, default=Path("simulation/test_output"), help="Output directory")
    parser.add_argument("--skip-generate", action="store_true", help="Skip generation and reuse existing files in output directory")
    parser.add_argument("--regenerate", action="store_true", help="Force regeneration of stories even if cached versions exist")
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

    if args.mint_tokens:
        tokens = mint_tokens(auth, required_groups + ["admin", "public"])
    else:
        tokens = mint_tokens(auth, required_groups)
        tokens.update(bootstrap_tokens)

    verify_tokens(tokens, required_groups + ["admin", "public"])
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
    if args.skip_generate:
        if not args.output.exists() or not any(args.output.glob("synthetic_*.json")):
            print(f"skip-generate set, but no existing synthetic_*.json in {args.output}")
            sys.exit(1)
        print(f"Reusing existing documents in {args.output}")
    else:
        generate_data(args.count, args.output, regenerate=args.regenerate)
        run_gate("generation")

    # 4. Ingest Stories
    sources = list_sources(tokens["admin"])
    # Only ingest the count we generated (or all if skip-generate)
    ingest_count = None if args.skip_generate else args.count
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

