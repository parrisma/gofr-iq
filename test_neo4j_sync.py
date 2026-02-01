#!/usr/bin/env python3
"""Test script to verify SourceRegistry Neo4j synchronization."""

import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from neo4j import GraphDatabase
from app.services import SourceRegistry, GraphIndex
from app.models import SourceType, TrustLevel


def main():
    print("=" * 80)
    print("Testing SourceRegistry → Neo4j Synchronization")
    print("=" * 80)
    
    # Create services
    storage_path = Path("/tmp/test_neo4j_sync")
    storage_path.mkdir(exist_ok=True)
    
    graph_index = GraphIndex()
    source_registry = SourceRegistry(
        base_path=storage_path / "sources",
        graph_index=graph_index,
    )
    
    print("\n✓ Services initialized")
    
    # Test 1: Create source
    print("\n[Test 1] Creating source...")
    source = source_registry.create(
        name="Test Reuters",
        source_type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.HIGH,
    )
    print(f"  Created source: {source.source_guid}")
    
    # Verify in Neo4j
    with graph_index._get_session() as session:
        result = session.run(
            """
            MATCH (s:Source {source_guid: $guid})
            RETURN s.name as name, s.type as type, s.region as region,
                   s.trust_level as trust_level, s.active as active
            """,
            guid=source.source_guid,
        )
        record = result.single()
        if record:
            print(f"  ✓ Found in Neo4j:")
            print(f"    - name: {record['name']}")
            print(f"    - type: {record['type']}")
            print(f"    - region: {record['region']}")
            print(f"    - trust_level: {record['trust_level']}")
            print(f"    - active: {record['active']}")
        else:
            print("  ✗ NOT FOUND in Neo4j!")
            return False
    
    # Test 2: Update source
    print("\n[Test 2] Updating source...")
    updated_source = source_registry.update(
        source_guid=source.source_guid,
        region="US",
        trust_level=TrustLevel.MEDIUM,
    )
    print(f"  Updated source: {updated_source.source_guid}")
    
    # Verify update in Neo4j
    with graph_index._get_session() as session:
        result = session.run(
            """
            MATCH (s:Source {source_guid: $guid})
            RETURN s.region as region, s.trust_level as trust_level
            """,
            guid=source.source_guid,
        )
        record = result.single()
        if record:
            print(f"  ✓ Updated in Neo4j:")
            print(f"    - region: {record['region']}")
            print(f"    - trust_level: {record['trust_level']}")
            if record['region'] == 'US' and record['trust_level'] == 'medium':
                print("  ✓ Update verified correctly")
            else:
                print("  ✗ Update mismatch!")
                return False
        else:
            print("  ✗ NOT FOUND in Neo4j after update!")
            return False
    
    # Test 3: Soft delete source
    print("\n[Test 3] Soft deleting source...")
    deleted_source = source_registry.soft_delete(source.source_guid)
    print(f"  Soft deleted source: {deleted_source.source_guid}")
    
    # Verify soft delete in Neo4j
    with graph_index._get_session() as session:
        result = session.run(
            """
            MATCH (s:Source {source_guid: $guid})
            RETURN s.active as active
            """,
            guid=source.source_guid,
        )
        record = result.single()
        if record:
            print(f"  ✓ Still in Neo4j (soft delete):")
            print(f"    - active: {record['active']}")
            if record['active'] == False:
                print("  ✓ Soft delete verified correctly")
            else:
                print("  ✗ Should be inactive!")
                return False
        else:
            print("  ✗ NOT FOUND in Neo4j after soft delete!")
            return False
    
    # Cleanup
    print("\n[Cleanup] Removing test source from Neo4j...")
    with graph_index._get_session() as session:
        session.run(
            "MATCH (s:Source {source_guid: $guid}) DELETE s",
            guid=source.source_guid,
        )
    print("  ✓ Cleanup complete")
    
    # Close connections
    graph_index.close()
    
    print("\n" + "=" * 80)
    print("✓ All Neo4j synchronization tests PASSED")
    print("=" * 80)
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
