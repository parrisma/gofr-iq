#!/usr/bin/env python3
"""
Post-simulation validation: verify Neo4j and ChromaDB state.

Usage:
    python simulation/validate_simulation.py [--expected-docs N] [--verbose]
"""
import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# SSOT: Import env module
from lib.gofr_common.gofr_env import get_admin_token, GofrEnvError


def validate_neo4j(verbose: bool = False) -> dict:
    """Check Neo4j for expected graph structure.
    
    Note: Expects GOFR_IQ_NEO4J_PASSWORD to be set in environment
          (typically via run_simulation.sh which sources Vault secrets).
    """
    from neo4j import GraphDatabase
    
    neo4j_uri = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687")
    neo4j_user = os.environ.get("GOFR_IQ_NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    
    if not neo4j_password:
        print("   ⚠️  GOFR_IQ_NEO4J_PASSWORD not set - skipping Neo4j validation")
        print("      (Run via run_simulation.sh to get proper environment)")
        return {}
    
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    counts = {}
    with driver.session() as session:
        # Count key node types
        for label in ["Company", "Factor", "Client", "Document", "Source"]:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
            counts[label] = result.single()["count"]
        
        # Count relationships
        result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
        counts["Relationships"] = result.single()["count"]
    
    driver.close()
    
    if verbose:
        print("\n📊 Neo4j Graph State:")
        for label, count in counts.items():
            print(f"   {label:20s}: {count:5d}")
    
    return counts


def validate_chromadb(verbose: bool = False) -> dict:
    """Check ChromaDB for document embeddings."""
    import chromadb
    
    chroma_host = os.environ.get("GOFR_IQ_CHROMADB_HOST", "gofr-chromadb")
    chroma_port = int(os.environ.get("GOFR_IQ_CHROMADB_PORT", "8000"))
    
    # Simple check if port is open first? No, client handles it.
    
    counts = {}
    try:
        # We need to construct client carefully. 
        # In newer chroma clients, HttpClient is preferred for remote.
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        
        try:
            collection = client.get_collection("documents")
            counts["Documents"] = collection.count()
        except ValueError: # Collection might not exist
             counts["Documents"] = 0
             
    except Exception as e:
        print(f"⚠️  Could not check ChromaDB: {e}")
        counts["Documents"] = 0
    
    if verbose:
        print("\n📚 ChromaDB State:")
        print(f"   Documents: {counts['Documents']}")
    
    return counts

def check_gate(gate: str, verbose: bool = False) -> bool:
    """Execute specific stage checks."""
    print(f"🚧 Checking Gate: {gate.upper()}...")
    
    if gate == "auth":
        try:
            get_admin_token()  # Will raise GofrEnvError if not available
            print("   ✓ Bootstrap tokens available via SSOT module")
            return True
        except GofrEnvError as e:
            print(f"   ❌ Bootstrap tokens not available: {e}")
            return False

    elif gate == "sources":
        # Check MCP for Sources (sources are in MCP registry, not Neo4j)
        import subprocess
        
        try:
            admin_token = get_admin_token()
        except GofrEnvError:
            print("   ❌ No admin token available to check sources")
            return False
        
        result = subprocess.run(
            ["./scripts/manage_source.sh", "list", "--docker", "--json", "--token", admin_token],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30
        )
        if result.returncode != 0:
            print(f"   ❌ Failed to list sources: {result.stderr}")
            return False
        
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, str):
                payload = json.loads(payload)
            sources = payload.get("data", {}).get("sources", [])
            src_count = len(sources)
        except Exception as e:
            print(f"   ❌ Failed to parse sources response: {e}")
            return False
        
        print(f"   Found {src_count} sources in MCP registry")
        if src_count >= 5:
            print(f"   ✓ Sources gate passed (expected >= 5)")
            return True
        else:
            print(f"   ❌ Sources gate failed (found {src_count}, expected >= 5)")
            return False

    elif gate == "universe":
        counts = validate_neo4j(verbose=False)
        companies = counts.get("Company", 0)
        factors = counts.get("Factor", 0)
        print(f"   Found Companies={companies}, Factors={factors}")
        
        # We expect 16 companies and 5 factors
        if companies >= 16 and factors >= 5:
            print(f"   ✓ Universe gate passed")
            return True
        else:
             print(f"   ❌ Universe gate failed (expected Companies>=16, Factors>=5)")
             return False

    elif gate == "clients":
        counts = validate_neo4j(verbose=False)
        clients = counts.get("Client", 0)
        print(f"   Found Clients={clients}")
        if clients >= 3:
            print(f"   ✓ Clients gate passed")
            return True
        else:
            print(f"   ❌ Clients gate failed (expected >= 3)")
            return False

    elif gate == "generation":
        output_dir = PROJECT_ROOT / "simulation/test_output"
        if not output_dir.exists():
            print(f"   ❌ Output directory not found: {output_dir}")
            return False
        
        files = list(output_dir.glob("synthetic_*.json"))
        count = len(files)
        print(f"   Found {count} synthetic story files")
        
        # We might accept 0 if skipping generation, but the gate implies updated state.
        # Let's warning if 0 but pass? No, gate checks SHOULD fail if data is missing.
        # But run_simulation.sh uses --skip-generate. 
        # If the user ran with --skip-generate, files should still exist from previous run 
        # OR they might not exist if it's a fresh run without generation (which is invalid for ingestion).
        # We'll enforce > 0.
        if count > 0:
            print(f"   ✓ Generation gate passed")
            return True
        else:
            print(f"   ❌ Generation gate failed (0 files found)")
            return False

    elif gate == "ingestion":
        # Check consistency between files, neo4j, and chroma
        output_dir = PROJECT_ROOT / "simulation/test_output"
        file_count = len(list(output_dir.glob("synthetic_*.json")))
        
        neo4j_counts = validate_neo4j(verbose=False)
        doc_nodes = neo4j_counts.get("Document", 0)
        
        chroma_counts = validate_chromadb(verbose=False)
        embeddings = chroma_counts.get("Documents", 0)
        
        print(f"   Files: {file_count}, Neo4j Nodes: {doc_nodes}, Embeddings: {embeddings}")
        
        if doc_nodes == 0:
            print(f"   ❌ Ingestion gate failed (0 Document nodes)")
            return False
            
        # Each document may create multiple embedding chunks, so embeddings >= doc_nodes
        if embeddings < doc_nodes:
             print(f"   ❌ Ingestion gate failed (fewer embeddings than documents)")
             return False
             
        print(f"   ✓ Ingestion gate passed (embeddings/doc ratio: {embeddings/doc_nodes:.1f})")
        return True

    else:
        print(f"   ❌ Unknown gate: {gate}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Validate simulation state")
    parser.add_argument("--expected-docs", type=int, help="Expected document count")
    parser.add_argument("--verbose", action="store_true", help="Show detailed counts")
    parser.add_argument("--gate", type=str, choices=["auth", "sources", "universe", "clients", "generation", "ingestion"], 
                        help="Run specific stage gate check")
    args = parser.parse_args()
    
    # Gate mode
    if args.gate:
        success = check_gate(args.gate, args.verbose)
        sys.exit(0 if success else 1)

    # Full Validation Mode (legacy/default)
    print("🔍 Validating simulation state...\n")
    
    try:
        neo4j_counts = validate_neo4j(verbose=args.verbose)
        chroma_counts = validate_chromadb(verbose=args.verbose)
        
        # Basic sanity checks
        issues = []
        
        # Skip Neo4j checks if validation was skipped (no password)
        if not neo4j_counts:
            print("\n⚠️  Neo4j validation skipped (environment not configured)")
            print("   Run via ./simulation/run_simulation.sh for full validation")
        else:
            if neo4j_counts.get("Company", 0) == 0:
                issues.append("No Company nodes in Neo4j (universe not loaded?)")
            
            if neo4j_counts.get("Client", 0) == 0:
                issues.append("No Client nodes in Neo4j (clients not loaded?)")
            
            if neo4j_counts.get("Document", 0) == 0:
                issues.append("No Document nodes in Neo4j (stories not ingested?)")
            
            if neo4j_counts.get("Source", 0) == 0:
                issues.append("No Source nodes in Neo4j (sources not registered?)")
            
            if args.expected_docs and neo4j_counts.get("Document", 0) < args.expected_docs:
                issues.append(
                    f"Neo4j has {neo4j_counts['Document']} documents, expected at least {args.expected_docs}"
                )
        
        if args.expected_docs and chroma_counts.get("Documents", 0) < args.expected_docs:
            issues.append(
                f"ChromaDB has {chroma_counts['Documents']} documents, expected at least {args.expected_docs}"
            )
        
        print("\n" + "=" * 70)
        if issues:
            print("⚠️  Validation Issues Found:")
            for issue in issues:
                print(f"   • {issue}")
            print("=" * 70)
            return 1
        else:
            print("✅ All validation checks passed!")
            print("=" * 70)
            return 0
            
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
