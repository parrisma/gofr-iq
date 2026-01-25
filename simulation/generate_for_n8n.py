#!/usr/bin/env python3
"""
Simple wrapper to generate synthetic stories for n8n ingestion testing.

Generates stories without validation_metadata field, outputting to test_output_n8n folder.

Usage:
    python simulation/generate_for_n8n.py --count 5
    python simulation/generate_for_n8n.py --count 10 --output simulation/test_output_n8n
"""

import argparse
import json
import sys
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.generate_synthetic_stories import SyntheticGenerator


def generate_for_n8n(count: int, output_dir: Path):
    """Generate stories without validation_metadata for n8n ingestion."""
    
    # Use the existing generator
    generator = SyntheticGenerator()
    
    # Generate to a temporary location
    temp_dir = output_dir.parent / ".temp_n8n_gen"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Generate stories with validation metadata
        generator.generate_batch(count, temp_dir)
        
        # Process files: remove validation_metadata and move to final location
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path in temp_dir.glob("*.json"):
            with open(file_path, "r") as f:
                data = json.load(f)
            
            # Remove validation_metadata
            if "validation_metadata" in data:
                del data["validation_metadata"]
            
            # Write to final location
            output_path = output_dir / file_path.name
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2)
            
            print(f"✓ Generated: {output_path.name}")
        
        # Cleanup temp directory
        for file_path in temp_dir.glob("*.json"):
            file_path.unlink()
        temp_dir.rmdir()
        
        print(f"\n✓ Generated {count} stories in {output_dir}")
        
    except Exception as e:
        print(f"Error: {e}")
        # Cleanup on error
        if temp_dir.exists():
            for file_path in temp_dir.glob("*.json"):
                file_path.unlink()
            temp_dir.rmdir()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic stories for n8n ingestion (without validation_metadata)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of stories to generate (default: 5)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="simulation/test_output_n8n",
        help="Output directory (default: simulation/test_output_n8n)"
    )
    
    args = parser.parse_args()
    
    # Resolve output directory
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parent.parent / output_dir
    
    print(f"Generating {args.count} stories for n8n ingestion...")
    print(f"Output directory: {output_dir}\n")
    
    generate_for_n8n(args.count, output_dir)


if __name__ == "__main__":
    main()
