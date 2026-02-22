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

# SSOT: Use the centralized environment module
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))
from gofr_common.gofr_env import (  # noqa: E402 - path modification required before import
    get_admin_token,
    get_token_for_group,
    get_workspace_root,
    GofrEnvError,
)

# Configuration
TEST_OUTPUT = Path(__file__).parent / "test_output"
WORKSPACE_ROOT = get_workspace_root()


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


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
    
    existing = load_sources(admin_token) # Get actual existing sources from API
    
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
                "--docker",
                "--token", admin_token
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_ROOT)
            if result.returncode != 0:
                print(f"{Colors.RED}Failed to create source {mock_src.name}: {result.stderr}{Colors.RESET}")
            else:
                 # Extract GUID from output if possible, or just re-load sources later
                 print("    Created.")

def load_sources(token: str) -> Dict[str, str]:
    """Build source name → GUID mapping from manage_source.sh (raw JSON to avoid truncation)."""
    try:
        result = subprocess.run(
            ["./scripts/manage_source.sh", "list", "--docker", "--json", "--token", token],
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
    metadata: Dict = {},
    verbose: bool = False
) -> Tuple[bool, str, float]:
    """
    Ingest a single document using manage_document.sh.
    
    Returns:
        (success: bool, message: str, duration: float)
    """
    start_time = time.time()
    
    # Write content to temp file to avoid shell escaping issues
    import tempfile
    content_file = None
    
    try:
        # Create temp file with content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            content_file = f.name
        
        cmd = [
            "./scripts/manage_document.sh",
            "ingest",
            "--docker",
            "--source-guid", source_guid,
            "--title", title,
            "--content-file", content_file,
            "--token", token,
        ]

        # TODO: Pass metadata once manage_document.sh supports --metadata
        # if metadata:
        #     cmd.extend(["--metadata", json.dumps(metadata)])
        
        if verbose:
            safe_cmd = list(cmd)
            if "--token" in safe_cmd:
                try:
                    token_idx = safe_cmd.index("--token") + 1
                    if token_idx < len(safe_cmd):
                        safe_cmd[token_idx] = "[REDACTED]"
                except ValueError:
                    pass
            print(f"    CMD: {safe_cmd}")
            print(f"    Content file: {content_file}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=WORKSPACE_ROOT,
            timeout=120  # 2 minute timeout for LLM extraction
        )
        
        duration = time.time() - start_time
        output = result.stdout + result.stderr
        
        if verbose:
            print(f"    Exit code: {result.returncode}")
            if result.returncode != 0:
                print(f"    Output: {output[:300]}")
        
        # Classify result based on exit code first, then parse JSON response
        if result.returncode == 0:
            # Try to parse the actual response JSON to get real status
            import json
            import re
            
            # Extract JSON from response (look for the inner JSON in "text" field)
            json_match = re.search(r'"text":\s*"(\{[^"]*\})"', output.replace('\n', '').replace('\\n', '\n'))
            if json_match:
                try:
                    # Unescape the JSON string
                    inner_json = json_match.group(1).replace('\\n', '\n').replace('\\"', '"')
                    response_data = json.loads(inner_json)
                    
                    actual_status = response_data.get("data", {}).get("status", "")
                    actual_error = response_data.get("data", {}).get("error", "")
                    is_duplicate = response_data.get("data", {}).get("is_duplicate", False)
                    
                    if actual_status == "success":
                        return True, "success", duration
                    elif is_duplicate or "duplicate" in response_data.get("message", "").lower():
                        # Only report duplicate if actually a duplicate (not a failed extraction)
                        if actual_error:
                            return False, f"failed: {actual_error[:150]}", duration
                        return False, "duplicate", duration
                    elif actual_error:
                        return False, f"failed: {actual_error[:150]}", duration
                    else:
                        return False, f"status={actual_status}", duration
                except (json.JSONDecodeError, KeyError):
                    pass  # Fall through to simple text matching
            
            # Fallback: simple text matching (legacy behavior)
            if '"status": "success"' in output and '"error"' not in output:
                return True, "success", duration
            elif "already exists" in output.lower():
                return False, "duplicate", duration
            elif '"error":' in output:
                # Extract error message
                error_match = re.search(r'"error":\s*"([^"]+)"', output)
                if error_match:
                    return False, f"failed: {error_match.group(1)[:100]}", duration
                return False, "failed: unknown error", duration
            return True, "success", duration
        else:
            # Non-zero exit - check for specific errors
            if "usage:" in output.lower():
                return False, f"usage_error: {output[:200]}", duration
            elif "unauthorized" in output.lower() or "401" in output:
                return False, f"auth_error: {output[:100]}", duration
            elif "error" in output.lower():
                return False, f"error: {output[:100]}", duration
            else:
                return False, f"failed (exit {result.returncode}): {output[:100]}", duration
            
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return False, "timeout after 120s", duration
    except Exception as e:
        duration = time.time() - start_time
        return False, f"exception: {e}", duration
    finally:
        # Clean up temp file
        if content_file:
            import os
            try:
                os.unlink(content_file)
            except OSError:
                pass


def process_story(
    story_file: Path,
    sources: Dict[str, str],
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
        
        # Resolve token via SSOT module
        try:
            token = get_token_for_group(group)
        except GofrEnvError:
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
        
        # Prepare metadata for ingestion
        # We pass validated metadata for the graph to use
        ingest_metadata = {
            "source_type": story.get("source_type", "NEWS_WIRE"),
            "event_type": story.get("event_type"),
            "published_at": story.get("published_at"),
            "meta_source_name": story.get("meta_source_name"), 
            "trust_level": story.get("trust_level", 5),
            "group_guid": story.get("group_guid"),
            "validation_metadata": metadata  # Nest the full validation metadata for later checking
        }

        # Perform ingestion
        success, message, duration = ingest_document(
            source_guid, title, content, token, ingest_metadata, verbose
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
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of documents to process (0 = all)"
    )
    args = parser.parse_args()
    
    print("=== Synthetic Document Ingestion ===\n")
    
    # Load configuration via SSOT module
    # Use group-simulation token for document operations (principle of least privilege)
    # Admin token only needed for source registration (done by run_simulation.py)
    print("Loading tokens via SSOT module...", end=" ")
    try:
        # Use admin token for initial source operations (fallback if no group token exists)
        # After first run, group-simulation token will be used automatically
        admin_token = get_admin_token()
        print(f"{Colors.GREEN}✓{Colors.RESET}")
    except GofrEnvError as e:
        print(f"{Colors.RED}✗{Colors.RESET}")
        print(f"  {e}")
        return 1
    
    # Ensure Simulation Sources exist
    ensure_sources_exist(admin_token)
    
    print("Loading sources from registry...", end=" ")
    # Use group-simulation token if available (created by run_simulation.py)
    try:
        sources_token = get_token_for_group("group-simulation")
    except GofrEnvError:
        # Fallback to admin token if group-simulation not available
        sources_token = admin_token
    sources = load_sources(sources_token)
    print(f"{Colors.GREEN}✓{Colors.RESET} ({len(sources)} sources)")
    
    if args.dry_run:
        print(f"\n{Colors.YELLOW}DRY RUN MODE - No documents will be uploaded{Colors.RESET}\n")
    
    # Discover documents
    story_files = sorted(TEST_OUTPUT.glob("synthetic_*.json"))
    
    # Apply limit if specified
    if args.limit > 0:
        story_files = story_files[:args.limit]
        print(f"\nProcessing {len(story_files)} documents (limited from total)\n")
    else:
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
            story_file, sources, args.dry_run, args.verbose
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
            if "auth_error" in message:
                 print(f"{Colors.RED}CRITICAL: Authentication failed. Aborting run.{Colors.RESET}")
                 return 1
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
