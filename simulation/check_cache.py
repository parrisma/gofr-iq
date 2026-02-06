#!/usr/bin/env python3
"""
Quick utility to check document cache status.

Usage:
    ./simulation/check_cache.py
    ./simulation/check_cache.py --output simulation/test_output_tech
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.run_simulation import (  # noqa: E402 - path modification required before import
    count_existing_documents,
    load_generation_metadata
)


def main():
    parser = argparse.ArgumentParser(description="Check document cache status")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("simulation/test_output"),
        help="Output directory to check"
    )
    args = parser.parse_args()
    
    output_dir = args.output
    count = count_existing_documents(output_dir)
    meta = load_generation_metadata(output_dir)
    
    print("📦 Document Cache Status")
    print("=" * 60)
    print(f"Location:  {output_dir}")
    print(f"Documents: {count}")
    
    if meta:
        import datetime
        gen_time = datetime.datetime.fromtimestamp(meta['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Generated: {gen_time}")
        print(f"Model:     {meta.get('model', 'unknown')}")
        print(f"Version:   {meta.get('version', 'unknown')}")
        print()
        print("💡 Cache Benefits:")
        print("  • Reuses these documents on reset (no API cost)")
        print("  • Fast iteration (seconds vs minutes)")
        print("  • Consistent test data across runs")
        print()
        print("🔄 Usage:")
        print("  • Normal run:  ./simulation/run_simulation.sh --count 10")
        print("  • Regenerate:  ./simulation/run_simulation.sh --count 10 --regenerate")
        print("  • Clear cache: rm -f simulation/test_output/synthetic_*.json")
    elif count > 0:
        print()
        print("⚠️  Warning: Documents exist but no metadata found")
        print("   Run with --regenerate to rebuild cache metadata")
    else:
        print()
        print("ℹ️  No cached documents found")
        print("   Generate with: ./simulation/run_simulation.sh --count 10")


if __name__ == "__main__":
    main()
