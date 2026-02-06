#!/usr/bin/env python3
"""
Setup Neo4j uniqueness constraints for singleton node types.

Run this BEFORE loading any data to ensure data integrity.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase

# Singleton node types and their unique key properties
CONSTRAINTS = [
    # Market structure singletons
    ("Instrument", "ticker"),      # One instrument per ticker
    ("Company", "ticker"),         # One company per ticker
    ("Factor", "factor_id"),       # One factor per ID
    ("Region", "code"),            # One region per code
    ("Sector", "code"),            # One sector per code
    ("EventType", "code"),         # One event type per code
    
    # Access control singletons
    ("Group", "guid"),             # One group per GUID
    ("Source", "guid"),            # One source per GUID
    
    # Client singletons
    ("Client", "guid"),            # One client per GUID
    ("ClientType", "code"),        # One client type per code
    ("ClientProfile", "guid"),     # One profile per GUID
    ("Portfolio", "guid"),         # One portfolio per GUID
    ("Watchlist", "guid"),         # One watchlist per GUID
    
    # Document is NOT a singleton - many documents allowed
    # ("Document", "guid"),        # Documents have guid but allow duplicates for versioning
]

def setup_constraints(uri: str, user: str, password: str) -> None:
    """Create uniqueness constraints on singleton node types."""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    
    with driver.session() as session:
        print("Setting up Neo4j uniqueness constraints...")
        
        for label, prop in CONSTRAINTS:
            constraint_name = f"unique_{label.lower()}_{prop}"
            
            # Check if constraint already exists
            check_query = """
            SHOW CONSTRAINTS
            WHERE name = $name
            """
            result = session.run(check_query, {"name": constraint_name})
            exists = result.single() is not None
            
            if exists:
                print(f"  ✓ {label}.{prop} constraint already exists")
                continue
            
            # Create the constraint
            create_query = f"""
            CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
            FOR (n:{label})
            REQUIRE n.{prop} IS UNIQUE
            """
            try:
                session.run(create_query)  # type: ignore[arg-type] - f-string query
                print(f"  ✅ Created constraint: {label}.{prop}")
            except Exception as e:
                print(f"  ❌ Failed to create {label}.{prop}: {e}")
        
        print("\nConstraint setup complete.")
        
        # Show all constraints
        print("\nActive constraints:")
        result = session.run("SHOW CONSTRAINTS")
        for record in result:
            print(f"  - {record['name']}: {record['labelsOrTypes']} {record['properties']}")
    
    driver.close()


def main():
    uri = os.environ.get("NEO4J_URI", "bolt://gofr-neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    
    if not password:
        print("ERROR: NEO4J_PASSWORD environment variable required")
        sys.exit(1)
    
    setup_constraints(uri, user, password)


if __name__ == "__main__":
    main()
