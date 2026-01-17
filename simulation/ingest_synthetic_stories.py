#!/usr/bin/env python3
"""
Ingest synthetic test documents from test_output directory.

Usage:
    uv run python simulation/ingest_synthetic_stories.py [--dry-run] [--verbose]

Options:
    --dry-run    Parse documents without uploading
    --verbose    Show detailed progress including source and group info
"""

import json
import sys
import subprocess
import time
import argparse
from pathlib import Path
from typing import Dict, Tuple
from dotenv import dotenv_values

# Configuration
ENV_FILE = Path(__file__).parent / ".env.synthetic"
TEST_OUTPUT = Path(__file__).parent / "test_output"
WORKSPACE_ROOT = Path(__file__).parent.parent


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def load_tokens() -> Dict[str, str]:
    """Load JWT tokens from .env.synthetic."""
    try:
        config = dotenv_values(ENV_FILE)
        tokens_str = config.get("GOFR_SYNTHETIC_TOKENS", "{}")
        
        # Parse JSON string
        tokens = json.loads(tokens_str)
        
        if not tokens:
            raise ValueError("GOFR_SYNTHETIC_TOKENS is empty")
        
        return tokens
    except Exception as e:
        print(f"{Colors.RED}ERROR: Failed to load tokens from {ENV_FILE}{Colors.RESET}")
        print(f"  {e}")
        sys.exit(1)


def load_sources_from_registry():
    """Build source guid map from local simulation registry instead of querying the API."""
    from simulation.generate_synthetic_stories import MOCK_SOURCES
    return {s.name: s.guid for s in MOCK_SOURCES}

def ensure_sources_exist(token: str):
    """Ensures that the synthetic sources exist in the Source Registry via the API."""
    from simulation.generate_synthetic_stories import MOCK_SOURCES
    
    # We use the admin token to create sources
    admin_token = token
    
    print(f"{Colors.BLUE}Checking Source Registry for synthetic sources...{Colors.RESET}")
    
    existing = load_sources() # Get actual existing sources from API
    
    for mock_src in MOCK_SOURCES:
        if mock_src.name in existing:
            print(f"  ✓ {mock_src.name} exists ({existing[mock_src.name]})")
            # Ideally we check/update trust level here, but for now we assume it's okay or we update it
        else:
            print(f"  + Creating {mock_src.name}...")
            # Create Source via curl/manage_source.sh
            # We use manage_source.sh create command
            cmd = [
                "./scripts/manage_source.sh", "create",
                mock_src.name,
                "--description", mock_src.style_guide[:100], # Truncate desc
                "--trust-level", str(mock_src.trust_level),
                "--type", "news_wire",
                "--region", "global",
                "--docker"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_ROOT)
            if result.returncode != 0:
                print(f"{Colors.RED}Failed to create source {mock_src.name}: {result.stderr}{Colors.RESET}")
            else:
                 # Extract GUID from output if possible, or just re-load sources later
                 print(f"    Created.")

def load_sources() -> Dict[str, str]:
    """Build source name → GUID mapping from manage_source.sh (raw JSON to avoid truncation)."""
    try:
        result = subprocess.run(
            ["./scripts/manage_source.sh", "list", "--docker", "--json"],
            capture_output=True,
            text=True,
            cwd=WORKSPACE_ROOT,
            timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"manage_source.sh failed: {result.stderr or result.stdout}")

        # result.stdout is JSON string from inner MCP response
        payload = json.loads(result.stdout)
        if isinstance(payload, str):
            payload = json.loads(payload)
        sources_json = payload.get("data", {}).get("sources", [])
        sources = {src.get("name"): src.get("source_guid") for src in sources_json if src.get("name")}
        return sources
    except Exception as e:
        print(f"{Colors.RED}ERROR: Failed to load sources{Colors.RESET}")
        print(f"  {e}")
        sys.exit(1)


def ingest_document(
    source_guid: str,
    title: str,
    content: str,
    token: str,
    verbose: bool = False
) -> Tuple[bool, str, float]:
    """
    Ingest a single document using manage_document.sh.
    
    Returns:
        (success: bool, message: str, duration: float)
    """
    start_time = time.time()
    
    try:
        cmd = [
            "./scripts/manage_document.sh",
            "ingest",
            "--source-guid", source_guid,
            "--title", title,
            "--content", content,
            "--token", token,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=WORKSPACE_ROOT,
            timeout=120  # 2 minute timeout for LLM extraction
        )
        
        duration = time.time() - start_time
        output = result.stdout + result.stderr
        
        # Classify result
        if "already exists" in output.lower() or "duplicate" in output.lower():
            return False, "duplicate", duration
        elif "document uploaded" in output.lower() or "success" in output.lower():
            return True, "success", duration
        elif "authentication" in output.lower() or "auth" in output.lower():
            return False, f"auth_error: {output[:100]}", duration
        elif "error" in output.lower():
            return False, f"error: {output[:100]}", duration
        elif result.returncode == 0:
            return True, "success", duration
        else:
            return False, f"failed (exit {result.returncode}): {output[:100]}", duration
            
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return False, "timeout after 120s", duration
    except Exception as e:
        duration = time.time() - start_time
        return False, f"exception: {e}", duration


def process_story(
    story_file: Path,
    sources: Dict[str, str],
    tokens: Dict[str, str],
    dry_run: bool = False,
    verbose: bool = False
) -> Tuple[str, str, float, dict]:
    """
    Process a single synthetic story.
    
    Returns:
        (status: str, message: str, duration: float, metadata: dict)
        status: 'uploaded' | 'duplicate' | 'failed'
    """
    try:
        # Read and parse JSON
        with open(story_file) as f:
            story = json.load(f)
        
        # Extract required fields
        source_name = story.get("source")
        group = story.get("upload_as_group")
        title = story.get("title")
        content = story.get("story_body")
        
        # Validate required fields
        if not all([source_name, group, title, content]):
            missing = []
            if not source_name:
                missing.append("source")
            if not group:
                missing.append("upload_as_group")
            if not title:
                missing.append("title")
            if not content:
                missing.append("story_body")
            return "failed", f"missing fields: {', '.join(missing)}", 0.0, {}
        
        # Resolve source GUID
        source_guid = sources.get(source_name)
        if not source_guid:
            return "failed", f"unknown source: {source_name}", 0.0, {}
        
        # Resolve token
        token = tokens.get(group)
        if not token:
            return "failed", f"no token for group: {group}", 0.0, {}
        
        metadata = {
            "source": source_name,
            "source_guid": source_guid[:8] + "...",
            "group": group,
            "title_preview": title[:50] + ("..." if len(title) > 50 else "")
        }
        
        # Dry run - just validate
        if dry_run:
            return "validated", "would upload", 0.0, metadata
        
        # Perform ingestion
        success, message, duration = ingest_document(
            source_guid, title, content, token, verbose
        )
        
        if success:
            status = "uploaded"
        elif "duplicate" in message:
            status = "duplicate"
        else:
            status = "failed"
        
        return status, message, duration, metadata
        
    except json.JSONDecodeError as e:
        return "failed", f"invalid JSON: {e}", 0.0, {}
    except Exception as e:
        return "failed", f"exception: {e}", 0.0, {}


def main():
    """Main ingestion workflow."""
    parser = argparse.ArgumentParser(
        description="Ingest synthetic test documents"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate documents without uploading"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress including source and group info"
    )
    args = parser.parse_args()
    
    print("=== Synthetic Document Ingestion ===\n")
    
    # Load configuration
    print("Loading tokens from .env.synthetic...", end=" ")
    tokens = load_tokens()
    print(f"{Colors.GREEN}✓{Colors.RESET} ({len(tokens)} groups)")
    
    # Ensure Simulation Sources exist
    admin_token = tokens.get("admin")
    if admin_token:
        ensure_sources_exist(admin_token)
    else:
        print(f"{Colors.RED}No admin token found, skipping source creation check.{Colors.RESET}")
    
    print("Loading sources from registry...", end=" ")
    sources = load_sources()
    print(f"{Colors.GREEN}✓{Colors.RESET} ({len(sources)} sources)")
    
    if args.dry_run:
        print(f"\n{Colors.YELLOW}DRY RUN MODE - No documents will be uploaded{Colors.RESET}\n")
    
    # Discover documents
    story_files = sorted(TEST_OUTPUT.glob("synthetic_*.json"))
    print(f"\nFound {len(story_files)} synthetic documents to process\n")
    
    if not story_files:
        print(f"{Colors.RED}No documents found in {TEST_OUTPUT}{Colors.RESET}")
        return 1
    
    # Process each document
    uploaded = 0
    skipped = 0
    failed = 0
    failed_docs = []
    total_time = 0.0
    
    for i, story_file in enumerate(story_files, 1):
        status, message, duration, metadata = process_story(
            story_file, sources, tokens, args.dry_run, args.verbose
        )
        
        total_time += duration
        
        # Format output
        prefix = f"[{i}/{len(story_files)}]"
        filename = story_file.name
        
        if args.verbose and metadata:
            print(f"\n{prefix} {Colors.BLUE}{filename}{Colors.RESET}")
            print(f"  Source: {metadata['source']} ({metadata['source_guid']})")
            print(f"  Group: {metadata['group']}")
            print(f"  Title: {metadata['title_preview']}")
            print("  Status: ", end="")
        else:
            print(f"{prefix} {filename:50s} ", end="")
        
        # Status indicator
        if status == "uploaded" or status == "validated":
            print(f"{Colors.GREEN}✓ Uploaded{Colors.RESET} ({duration:.1f}s)")
            uploaded += 1
        elif status == "duplicate":
            print(f"{Colors.YELLOW}⊘ Duplicate{Colors.RESET}")
            skipped += 1
        else:  # failed
            print(f"{Colors.RED}✗ Failed{Colors.RESET}: {message}")
            failed += 1
            failed_docs.append((filename, message))
    
    # Summary
    print(f"\n{'='*70}")
    print(f"Summary: {Colors.GREEN}{uploaded} uploaded{Colors.RESET}, "
          f"{Colors.YELLOW}{skipped} skipped{Colors.RESET}, "
          f"{Colors.RED}{failed} failed{Colors.RESET}")
    print(f"Total time: {total_time:.1f}s")
    print(f"{'='*70}")
    
    # Show failed documents
    if failed_docs:
        print(f"\n{Colors.RED}Failed Documents:{Colors.RESET}")
        for filename, error in failed_docs:
            print(f"  {filename}")
            print(f"    → {error}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
