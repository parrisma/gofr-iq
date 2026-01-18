#!/usr/bin/env python3
"""
Reset Simulation Environment (Soft Reset)

This script wipes all data from Neo4j, ChromaDB, and document storage
to ensure a clean slate before running a new simulation. It preserves
the containers.

Usage:
    python simulation/reset_simulation_env.py [--force]

Prerequisites:
    - Neo4j and ChromaDB must be running and reachable.
    - Environment variables must be set (usually via wrapper script).
"""

import os
import sys
import argparse
import time
import shutil
from pathlib import Path
from neo4j import GraphDatabase
import chromadb
from chromadb.config import Settings

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

def check_env():
    """Ensure required environment variables are set."""
    required = [
        "GOFR_IQ_NEO4J_URI",
        "GOFR_IQ_NEO4J_USER",
        "GOFR_IQ_NEO4J_PASSWORD",
        "GOFR_IQ_CHROMADB_HOST",
        "GOFR_IQ_CHROMADB_PORT"
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"{RED}ERROR: Missing environment variables: {', '.join(missing)}{RESET}")
        print("Run this script via simulation/reset_simulation_env.sh")
        sys.exit(1)

def reset_neo4j():
    """Wipe all nodes and relationships from Neo4j."""
    uri = os.environ["GOFR_IQ_NEO4J_URI"]
    user = os.environ["GOFR_IQ_NEO4J_USER"]
    password = os.environ["GOFR_IQ_NEO4J_PASSWORD"]

    print(f"Connecting to Neo4j at {uri}...", end=" ")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        print(f"{GREEN}Connected{RESET}")
    except Exception as e:
        print(f"{RED}Failed{RESET}")
        print(f"  {e}")
        return False

    print("Wiping Neo4j database...", end=" ")
    try:
        with driver.session() as session:
            # Delete everything
            session.run("MATCH (n) DETACH DELETE n")
            # Verify empty
            count = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            if count == 0:
                print(f"{GREEN}✓ Cleared{RESET}")
            else:
                print(f"{RED}✗ Failed (count={count}){RESET}")
                return False
    except Exception as e:
        print(f"{RED}Error{RESET}")
        print(f"  {e}")
        return False
    finally:
        driver.close()
    return True


def init_neo4j_schema():
    """Initialize Neo4j schema with constraints and indexes."""
    print("Initializing Neo4j schema (constraints & indexes)...", end=" ")
    try:
        # Import here to avoid circular imports
        from app.services.graph_index import GraphIndex
        
        with GraphIndex() as graph:
            graph.init_schema()
        print(f"{GREEN}✓ Schema initialized{RESET}")
        return True
    except Exception as e:
        print(f"{RED}Error{RESET}")
        print(f"  {e}")
        return False

def reset_chroma():
    """Reset ChromaDB collections."""
    host = os.environ["GOFR_IQ_CHROMADB_HOST"]
    port = os.environ["GOFR_IQ_CHROMADB_PORT"]

    print(f"Connecting to ChromaDB at {host}:{port}...", end=" ")
    try:
        client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=Settings(allow_reset=True)
        )
        print(f"{GREEN}Connected{RESET}")
    except Exception as e:
        print(f"{RED}Failed{RESET}")
        print(f"  {e}")
        return False

    print("Wiping ChromaDB...", end=" ")
    try:
        client.reset()
        print(f"{GREEN}✓ Reset{RESET}")
    except Exception as e:
        print(f"{YELLOW}Reset not allowed or failed, trying collection deletion...{RESET}")
        try:
            cols = client.list_collections()
            for col in cols:
                client.delete_collection(col.name)
            print(f"{GREEN}✓ Collections deleted{RESET}")
        except Exception as ex:
            print(f"{RED}Error{RESET}")
            print(f"  {ex}")
            return False
    return True

def reset_storage():
    """Clear document and source storage directories."""
    # Get project root (simulation is one level up from this script)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    storage_root = project_root / "data" / "storage"
    
    docs_dir = storage_root / "documents"
    sources_dir = storage_root / "sources"
    
    print("Clearing document storage...", end=" ")
    try:
        if docs_dir.exists():
            for item in docs_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            print(f"{GREEN}✓ Cleared{RESET}")
        else:
            print(f"{GREEN}✓ Already empty{RESET}")
    except Exception as e:
        print(f"{RED}Error{RESET}")
        print(f"  {e}")
        return False
    
    print("Clearing source storage...", end=" ")
    try:
        if sources_dir.exists():
            for item in sources_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            print(f"{GREEN}✓ Cleared{RESET}")
        else:
            print(f"{GREEN}✓ Already empty{RESET}")
    except Exception as e:
        print(f"{RED}Error{RESET}")
        print(f"  {e}")
        return False
    
    return True

def verify_reset():
    """Verify all data has been cleared and schema is initialized."""
    print(f"\n{YELLOW}Verification:{RESET}")
    
    all_clear = True
    
    # Check Neo4j
    try:
        uri = os.environ["GOFR_IQ_NEO4J_URI"]
        user = os.environ["GOFR_IQ_NEO4J_USER"]
        password = os.environ["GOFR_IQ_NEO4J_PASSWORD"]
        
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            count = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            if count == 0:
                print(f"  Neo4j nodes: {GREEN}0{RESET} ✓")
            else:
                print(f"  Neo4j nodes: {RED}{count}{RESET} ✗")
                all_clear = False
            
            # Verify constraints exist
            constraints = session.run("SHOW CONSTRAINTS").data()
            constraint_count = len(constraints)
            # We expect at least 15+ constraints (GUIDs for all node types + singleton constraints)
            if constraint_count >= 15:
                print(f"  Neo4j constraints: {GREEN}{constraint_count}{RESET} ✓")
            else:
                print(f"  Neo4j constraints: {RED}{constraint_count} (expected >= 15){RESET} ✗")
                all_clear = False
        driver.close()
    except Exception as e:
        print(f"  Neo4j: {RED}Could not verify ({e}){RESET}")
        all_clear = False
    
    # Check ChromaDB
    try:
        host = os.environ["GOFR_IQ_CHROMADB_HOST"]
        port = os.environ["GOFR_IQ_CHROMADB_PORT"]
        
        client = chromadb.HttpClient(host=host, port=port)
        cols = client.list_collections()
        if len(cols) == 0:
            print(f"  ChromaDB collections: {GREEN}0{RESET} ✓")
        else:
            print(f"  ChromaDB collections: {RED}{len(cols)}{RESET} ✗")
            all_clear = False
    except Exception as e:
        print(f"  ChromaDB: {RED}Could not verify ({e}){RESET}")
        all_clear = False
    
    # Check document storage
    try:
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        storage_root = project_root / "data" / "storage"
        
        docs_dir = storage_root / "documents"
        doc_count = len(list(docs_dir.rglob("*.json"))) if docs_dir.exists() else 0
        
        if doc_count == 0:
            print(f"  Document files: {GREEN}0{RESET} ✓")
        else:
            print(f"  Document files: {RED}{doc_count}{RESET} ✗")
            all_clear = False
        
        sources_dir = storage_root / "sources"
        source_count = len(list(sources_dir.iterdir())) if sources_dir.exists() else 0
        
        if source_count == 0:
            print(f"  Source files: {GREEN}0{RESET} ✓")
        else:
            print(f"  Source files: {RED}{source_count}{RESET} ✗")
            all_clear = False
            
    except Exception as e:
        print(f"  Storage: {RED}Could not verify ({e}){RESET}")
        all_clear = False
    
    return all_clear

def main():
    parser = argparse.ArgumentParser(description="Reset Neo4j, ChromaDB, and document storage")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    args = parser.parse_args()

    check_env()

    if not args.force:
        print(f"{YELLOW}WARNING: This will delete ALL data in Neo4j, ChromaDB, and document storage.{RESET}")
        print(f"Target Neo4j: {os.environ['GOFR_IQ_NEO4J_URI']}")
        print(f"Target Chroma: {os.environ['GOFR_IQ_CHROMADB_HOST']}")
        print(f"Target Storage: data/storage/")
        response = input("Are you sure? (y/N) ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    success_neo = reset_neo4j()
    success_schema = init_neo4j_schema() if success_neo else False
    success_chroma = reset_chroma()
    success_storage = reset_storage()

    # Verify the reset
    verification_passed = verify_reset()

    if success_neo and success_schema and success_chroma and success_storage and verification_passed:
        print(f"\n{GREEN}Environment Reset Successful{RESET}")
        sys.exit(0)
    else:
        print(f"\n{RED}Environment Reset Failed or Incomplete{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()
