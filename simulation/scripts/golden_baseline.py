#!/usr/bin/env python3
"""
Golden Run Management for Avatar Feed Regression Testing.

Commands:
  save    - Save current test results as the new golden baseline
  diff    - Compare current run against saved golden baseline
  show    - Show the current golden baseline

Usage:
  uv run simulation/scripts/golden_baseline.py save --from results.json
  uv run simulation/scripts/golden_baseline.py diff --current results.json
  uv run simulation/scripts/golden_baseline.py show
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FILE = PROJECT_ROOT / "simulation" / "test_data" / "golden_baseline.json"


def cmd_save(args):
    """Save current results as golden baseline."""
    if not args.from_file:
        print("[ERROR] --from is required for save command")
        sys.exit(1)
    
    source = Path(args.from_file)
    if not source.exists():
        print(f"[ERROR] Source file not found: {source}")
        sys.exit(1)
    
    with open(source) as f:
        data = json.load(f)
    
    # Add golden metadata
    data["golden_saved_at"] = datetime.now().isoformat()
    data["golden_source"] = str(source)
    
    # Save
    GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"[SUCCESS] Golden baseline saved to: {GOLDEN_FILE}")
    print(f"   Tests: {data.get('summary', {}).get('total_tests', 'N/A')}")
    print(f"   Pass Rate: {data.get('summary', {}).get('pass_rate', 0):.1%}")


def cmd_diff(args):
    """Compare current results against golden baseline."""
    if not args.current:
        print("[ERROR] --current is required for diff command")
        sys.exit(1)
    
    current_path = Path(args.current)
    if not current_path.exists():
        print(f"[ERROR] Current results file not found: {current_path}")
        sys.exit(1)
    
    if not GOLDEN_FILE.exists():
        print(f"[ERROR] No golden baseline found at: {GOLDEN_FILE}")
        print("Run 'golden_baseline.py save --from <file>' first.")
        sys.exit(1)
    
    with open(GOLDEN_FILE) as f:
        golden = json.load(f)
    
    with open(current_path) as f:
        current = json.load(f)
    
    # Compare summaries
    g_summary = golden.get("summary", {})
    c_summary = current.get("summary", {})
    
    print("="*70)
    print("REGRESSION COMPARISON")
    print("="*70)
    print(f"Golden baseline from: {golden.get('golden_saved_at', 'unknown')}")
    print(f"Current run from: {current.get('timestamp', 'unknown')}")
    print()
    
    # Summary diff
    print("SUMMARY COMPARISON:")
    print("-"*50)
    metrics = ["total_tests", "passed", "failed", "pass_rate", "empty_feeds"]
    has_regression = False
    
    for metric in metrics:
        g_val = g_summary.get(metric, 0)
        c_val = c_summary.get(metric, 0)
        
        if metric == "pass_rate":
            g_str = f"{g_val:.1%}"
            c_str = f"{c_val:.1%}"
            delta = c_val - g_val
            delta_str = f"{delta:+.1%}"
            # Regression if pass rate decreased
            is_worse = delta < -0.001
        elif metric in ["failed", "empty_feeds"]:
            g_str = str(g_val)
            c_str = str(c_val)
            delta = c_val - g_val
            delta_str = f"{delta:+d}"
            # Regression if failures increased
            is_worse = delta > 0
        else:
            g_str = str(g_val)
            c_str = str(c_val)
            delta = c_val - g_val
            delta_str = f"{delta:+d}"
            is_worse = False
        
        status = "[REGR]" if is_worse else "[OK]  "
        if is_worse:
            has_regression = True
        
        print(f"  {status} {metric:<15} Golden: {g_str:<8} Current: {c_str:<8} Delta: {delta_str}")
    
    # Per-test diff
    print()
    print("PER-TEST COMPARISON:")
    print("-"*50)
    
    g_results = {(r["client"], r["check"]): r["passed"] for r in golden.get("results", [])}
    c_results = {(r["client"], r["check"]): r for r in current.get("results", [])}
    
    new_failures = []
    fixed = []
    
    for key, c_result in c_results.items():
        g_passed = g_results.get(key)
        c_passed = c_result["passed"]
        
        if g_passed is None:
            # New test
            status = "[NEW] " if c_passed else "[NEW-FAIL]"
            print(f"  {status} {key[0]}: {key[1]}")
        elif g_passed and not c_passed:
            # Regression
            new_failures.append((key, c_result))
            print(f"  [REGR]  {key[0]}: {key[1]}")
            print(f"          Was: PASS, Now: FAIL - {c_result.get('detail', '')}")
        elif not g_passed and c_passed:
            # Fixed
            fixed.append(key)
            print(f"  [FIXED] {key[0]}: {key[1]}")
    
    # Summary
    print()
    print("="*70)
    if has_regression or new_failures:
        print(f"[REGRESSION DETECTED]")
        print(f"  New failures: {len(new_failures)}")
        print(f"  Fixed: {len(fixed)}")
        sys.exit(1)
    else:
        print(f"[NO REGRESSION]")
        print(f"  Fixed: {len(fixed)}")
        sys.exit(0)


def cmd_show(args):
    """Show current golden baseline."""
    if not GOLDEN_FILE.exists():
        print(f"[INFO] No golden baseline found at: {GOLDEN_FILE}")
        sys.exit(0)
    
    with open(GOLDEN_FILE) as f:
        golden = json.load(f)
    
    print("="*70)
    print("GOLDEN BASELINE")
    print("="*70)
    print(f"Saved at: {golden.get('golden_saved_at', 'unknown')}")
    print(f"Source: {golden.get('golden_source', 'unknown')}")
    print()
    
    summary = golden.get("summary", {})
    print(f"Total Tests: {summary.get('total_tests', 'N/A')}")
    print(f"Passed: {summary.get('passed', 'N/A')}")
    print(f"Failed: {summary.get('failed', 'N/A')}")
    print(f"Pass Rate: {summary.get('pass_rate', 0):.1%}")
    print()
    
    print("Test Results:")
    for r in golden.get("results", []):
        status = "[PASS]" if r["passed"] else "[FAIL]"
        print(f"  {status} {r['client']}: {r['check']}")


def main():
    parser = argparse.ArgumentParser(description="Golden baseline management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # save
    save_parser = subparsers.add_parser("save", help="Save results as golden baseline")
    save_parser.add_argument("--from", dest="from_file", required=True,
                             help="JSON results file to save as golden")
    
    # diff
    diff_parser = subparsers.add_parser("diff", help="Compare against golden baseline")
    diff_parser.add_argument("--current", required=True,
                             help="Current JSON results file to compare")
    
    # show
    subparsers.add_parser("show", help="Show current golden baseline")
    
    args = parser.parse_args()
    
    if args.command == "save":
        cmd_save(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "show":
        cmd_show(args)


if __name__ == "__main__":
    main()
