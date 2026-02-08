#!/usr/bin/env python3
"""
Inject Golden Test Data directly into Neo4j/Chroma.
Bypasses the LLM extraction pipeline to ensure 100% deterministic inputs.
"""

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Mock env for config
if "NEO4J_PASSWORD" not in os.environ:
    env_file = PROJECT_ROOT / "docker" / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith("NEO4J_PASSWORD="):
                    os.environ["NEO4J_PASSWORD"] = line.strip().split("=", 1)[1]

from app.services.graph_index import GraphIndex
# Note: Skipping Chroma for this test - avatar feeds use Graph primarily

def inject_data(file_path: str):
    print(f"💉 Injecting test data from {file_path}...")
    
    with open(file_path) as f:
        docs = json.load(f)

    # Read directly from env vars that are set in docker/.env
    neo4j_uri = os.environ.get("GOFR_IQ_NEO4J_URI", "bolt://gofr-neo4j:7687")
    neo4j_password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GOFR_IQ_NEO4J_PASSWORD")
    if not neo4j_password:
        raise ValueError("NEO4J_PASSWORD or GOFR_IQ_NEO4J_PASSWORD must be set")
    
    graph = GraphIndex(uri=neo4j_uri, password=neo4j_password)
    
    # We won't strictly need Chroma for avatar "Maintenance" feed since it uses Graph mainly,
    # but "Opportunity" uses themes which are graph properties. 
    # Vector search is used for "Semantic Search" features mostly.
    # However, let's skip Chroma injection for this specific test to keep it simple and focused on the Graph/Avatar logic.
    
    with graph._get_session() as session:
        for doc in docs:
            print(f"   Writing {doc['guid']} ({doc['title'][:30]}...)")
            
            # 1. Create Document Node
            session.run("""
                MERGE (d:Document {guid: $guid})
                SET d.title = $title,
                    d.content = $content,
                    d.created_at = $created_at,
                    d.impact_score = $impact_score,
                    d.impact_tier = $impact_tier,
                    d.themes = $themes
            """, 
            guid=doc['guid'],
            title=doc['title'],
            content=doc['content'],
            created_at=doc['created_at'],
            impact_score=float(doc['simulated_impact']['score']),
            impact_tier=doc['simulated_impact']['tier'],
            themes=doc['simulated_impact']['themes']
            )

            # 2. Link to Group (Simulated)
            # Find the group-simulation UUID or just map to all for testing context
            # We'll use the hardcoded simulation group UUID if known, or look it up.
            # For robustness, let's lookup group-simulation.
            group_res = session.run("MATCH (g:Group {name: 'group-simulation'}) RETURN g.guid").single()
            if group_res:
                session.run("""
                    MATCH (d:Document {guid: $d_guid})
                    MATCH (g:Group {guid: $g_guid})
                    MERGE (d)-[:IN_GROUP]->(g)
                """, d_guid=doc['guid'], g_guid=group_res['g.guid'])

            # 3. Create AFFECTS relationships (Force deterministic graph)
            for ticker in doc['simulated_impact']['affects']:
                # Ensure instrument exists
                session.run("""
                    MERGE (i:Instrument {ticker: $ticker})
                    ON CREATE SET i.name = $ticker + ' Corp'
                """, ticker=ticker)
                
                # Link
                session.run("""
                    MATCH (d:Document {guid: $d_guid})
                    MATCH (i:Instrument {ticker: $ticker})
                    MERGE (d)-[r:AFFECTS]->(i)
                    SET r.impact_score = d.impact_score,
                        r.impact_tier = d.impact_tier
                """, d_guid=doc['guid'], ticker=ticker)

    print(f"✅ Injected {len(docs)} documents.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python inject_test_data.py <json_file>")
        sys.exit(1)
    inject_data(sys.argv[1])
