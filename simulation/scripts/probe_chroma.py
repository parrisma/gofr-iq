#!/usr/bin/env python3
"""
Chroma Probe Tool for Avatar Testing.

Verify document embeddings exist in ChromaDB and check metadata.

Usage:
  uv run simulation/scripts/probe_chroma.py --document "doc-test-01"
  uv run simulation/scripts/probe_chroma.py --query "truck strike" --limit 5
  uv run simulation/scripts/probe_chroma.py --stats
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Fix imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment
env_file = PROJECT_ROOT / "docker" / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)

from app.config import GofrIqConfig
from app.services.vector_store import VectorStore


def probe_document(store: VectorStore, guid_part: str):
    """Check if a document exists in ChromaDB by GUID (partial match)."""
    print(f"\n[PROBE] Document: '{guid_part}'")
    
    # Get all documents and filter by GUID
    # ChromaDB doesn't have a direct "get by partial ID" so we query with metadata
    try:
        results = store._collection.get(
            where={"$or": [
                {"document_guid": {"$eq": guid_part}},
            ]},
            include=["metadatas", "documents"]
        )
    except Exception:
        # Fallback: try getting all and filter
        results = store._collection.get(include=["metadatas", "documents"])
    
    found = False
    for i, meta in enumerate(results.get("metadatas", [])):
        doc_guid = meta.get("document_guid", "")
        if guid_part.lower() in doc_guid.lower():
            found = True
            print(f"   [FOUND] GUID: {doc_guid}")
            print(f"   Title: {meta.get('title', 'N/A')}")
            print(f"   Impact Score: {meta.get('impact_score', 'N/A')}")
            print(f"   Impact Tier: {meta.get('impact_tier', 'N/A')}")
            print(f"   Source GUID: {meta.get('source_guid', 'N/A')}")
            
            # Show content snippet
            docs = results.get("documents", [])
            if i < len(docs) and docs[i]:
                content = docs[i][:200] + "..." if len(docs[i]) > 200 else docs[i]
                print(f"   Content: {content}")
            print()
    
    if not found:
        print("   [NOT FOUND] No document matching that GUID.")


def probe_query(store: VectorStore, query: str, limit: int = 5):
    """Run a similarity search and show top results."""
    print(f"\n[PROBE] Query: '{query}' (limit={limit})")
    
    results = store.search(query, k=limit)
    
    if not results:
        print("   [NO RESULTS] No similar documents found.")
        return
    
    print(f"   Found {len(results)} results:")
    print("-" * 70)
    
    for i, doc in enumerate(results, 1):
        meta = doc.metadata
        score = getattr(doc, "score", None) or meta.get("score", "N/A")
        print(f"   {i}. {meta.get('title', 'Untitled')}")
        print(f"      GUID: {meta.get('document_guid', 'N/A')}")
        print(f"      Score: {score}")
        print(f"      Impact: {meta.get('impact_score', 'N/A')} ({meta.get('impact_tier', 'N/A')})")
        print()


def probe_stats(store: VectorStore):
    """Show collection statistics."""
    print("\n[PROBE] ChromaDB Collection Stats")
    print("-" * 50)
    
    count = store._collection.count()
    print(f"   Total Documents: {count}")
    
    if count == 0:
        print("   [EMPTY] Collection has no documents.")
        return
    
    # Sample some documents to show metadata structure
    sample = store._collection.get(limit=5, include=["metadatas"])
    
    print(f"\n   Sample Metadata Fields:")
    if sample.get("metadatas"):
        meta = sample["metadatas"][0]
        for key in sorted(meta.keys()):
            print(f"      - {key}: {type(meta[key]).__name__}")
    
    # Count by impact tier
    print(f"\n   Documents by Impact Tier:")
    all_docs = store._collection.get(include=["metadatas"])
    tier_counts = {}
    for meta in all_docs.get("metadatas", []):
        tier = meta.get("impact_tier", "UNKNOWN")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    
    for tier in ["PLATINUM", "GOLD", "SILVER", "BRONZE", "STANDARD", "UNKNOWN"]:
        if tier in tier_counts:
            print(f"      {tier}: {tier_counts[tier]}")


def main():
    parser = argparse.ArgumentParser(description="Probe ChromaDB for avatar testing")
    parser.add_argument("--document", "-d", help="Document GUID (partial match)")
    parser.add_argument("--query", "-q", help="Similarity search query")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Number of results for query")
    parser.add_argument("--stats", "-s", action="store_true", help="Show collection statistics")
    
    args = parser.parse_args()
    
    if not any([args.document, args.query, args.stats]):
        parser.print_help()
        sys.exit(1)
    
    # Initialize
    print("[INIT] Connecting to ChromaDB...")
    config = GofrIqConfig()
    store = VectorStore(config)
    print(f"   Host: {config.CHROMADB_HOST}:{config.CHROMADB_PORT}")
    print(f"   Collection: {store._collection.name}")
    
    # Run probes
    if args.stats:
        probe_stats(store)
    
    if args.document:
        probe_document(store, args.document)
    
    if args.query:
        probe_query(store, args.query, args.limit)


if __name__ == "__main__":
    main()
