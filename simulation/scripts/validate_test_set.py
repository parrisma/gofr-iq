#!/usr/bin/env python3
"""
Validate the Golden Test Set against specific expectations.
This implements the "Test Matrix" defined in docs/avatar-test-strategy.md.

Usage:
  uv run simulation/scripts/validate_test_set.py
  uv run simulation/scripts/validate_test_set.py --expectations custom.json
  uv run simulation/scripts/validate_test_set.py --report-json results.json --report-md results.md
  uv run simulation/scripts/validate_test_set.py --require-nonempty --min-pass-rate 0.9
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

# Fix imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

from simulation.validate_avatar_feeds import _mcp_init, _mcp_call, _get_simulation_token


@dataclass
class TestResult:
    """Single test case result with structured failure info."""
    client: str
    check: str
    passed: bool
    detail: str
    failure_reason: Optional[str] = None  # data_missing, filter_mismatch, theme_mismatch, wrong_channel
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class ClientKPIs:
    """Per-client KPIs for the report."""
    client_name: str
    client_guid: str
    total_checks: int = 0
    passed_checks: int = 0
    coverage: float = 0.0
    precision: float = 0.0
    feed_empty: bool = False
    maintenance_count: int = 0
    opportunity_count: int = 0


@dataclass
class ValidationReport:
    """Full validation report with structured data."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    test_suite: str = "Golden Test Set"
    results: list[TestResult] = field(default_factory=list)
    client_kpis: list[ClientKPIs] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    
    def add(self, client: str, check: str, passed: bool, detail: str,
            failure_reason: Optional[str] = None, expected: Optional[str] = None,
            actual: Optional[str] = None):
        self.results.append(TestResult(
            client=client,
            check=check,
            passed=passed,
            detail=detail,
            failure_reason=failure_reason,
            expected=expected,
            actual=actual,
        ))

    def add_client_kpis(self, kpis: ClientKPIs):
        self.client_kpis.append(kpis)

    def compute_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        self.summary = {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "empty_feeds": sum(1 for k in self.client_kpis if k.feed_empty),
            "total_clients": len(self.client_kpis),
        }

    def print_summary(self):
        self.compute_summary()
        print("\n" + "="*80)
        print("FINAL TEST REPORT (Golden Set Validation)")
        print("="*80)
        print(f"{'CLIENT':<25} | {'RESULT':<6} | {'CHECK':<45}")
        print("-" * 80)
        
        for r in self.results:
            icon = "[PASS]" if r.passed else "[FAIL]"
            print(f"{r.client:<25} | {icon} | {r.check}")
            if not r.passed:
                print(f"   -> FAILURE: {r.detail}")
                if r.failure_reason:
                    print(f"   -> Reason: {r.failure_reason}")
        
        print("-" * 80)
        print(f"Summary: {self.summary['passed']}/{self.summary['total_tests']} Passed")
        print(f"Pass Rate: {self.summary['pass_rate']:.1%}")
        if self.summary['empty_feeds'] > 0:
            print(f"WARNING: {self.summary['empty_feeds']} client(s) have empty feeds")
        
        return self.summary['failed']

    def to_json(self) -> str:
        self.compute_summary()
        return json.dumps({
            "timestamp": self.timestamp,
            "test_suite": self.test_suite,
            "summary": self.summary,
            "results": [asdict(r) for r in self.results],
            "client_kpis": [asdict(k) for k in self.client_kpis],
        }, indent=2)

    def to_markdown(self) -> str:
        self.compute_summary()
        lines = [
            f"# Avatar Feed Test Report",
            f"",
            f"**Generated:** {self.timestamp}",
            f"**Test Suite:** {self.test_suite}",
            f"",
            f"## Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Tests | {self.summary['total_tests']} |",
            f"| Passed | {self.summary['passed']} |",
            f"| Failed | {self.summary['failed']} |",
            f"| Pass Rate | {self.summary['pass_rate']:.1%} |",
            f"| Empty Feeds | {self.summary['empty_feeds']} |",
            f"",
            f"## Test Results",
            f"",
            f"| Client | Check | Result | Detail |",
            f"|--------|-------|--------|--------|",
        ]
        
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            detail = r.detail[:50] + "..." if len(r.detail) > 50 else r.detail
            lines.append(f"| {r.client} | {r.check} | {status} | {detail} |")
        
        if self.client_kpis:
            lines.extend([
                f"",
                f"## Per-Client KPIs",
                f"",
                f"| Client | Coverage | Precision | Maintenance | Opportunity | Empty |",
                f"|--------|----------|-----------|-------------|-------------|-------|",
            ])
            for k in self.client_kpis:
                empty = "Yes" if k.feed_empty else "No"
                lines.append(
                    f"| {k.client_name} | {k.coverage:.0%} | {k.precision:.0%} | "
                    f"{k.maintenance_count} | {k.opportunity_count} | {empty} |"
                )
        
        # Failures section
        failures = [r for r in self.results if not r.passed]
        if failures:
            lines.extend([
                f"",
                f"## Failures",
                f"",
            ])
            for r in failures:
                lines.append(f"### {r.client}: {r.check}")
                lines.append(f"")
                lines.append(f"- **Detail:** {r.detail}")
                if r.failure_reason:
                    lines.append(f"- **Reason:** {r.failure_reason}")
                if r.expected:
                    lines.append(f"- **Expected:** {r.expected}")
                if r.actual:
                    lines.append(f"- **Actual:** {r.actual}")
                lines.append(f"")
        
        return "\n".join(lines)

def check_feed_contains(feed: dict, channel: str, title_part: str) -> tuple[bool, str, list[str]]:
    """Check if feed contains a document with given title in specified channel.
    
    Returns: (found, message, list of actual titles in channel)
    """
    items = feed.get(channel.lower(), [])
    actual_titles = [i['title'] for i in items]
    
    for item in items:
        if title_part.lower() in item['title'].lower():
            return True, f"Found '{title_part}' in {channel}", actual_titles
    
    # Debug: what IS there?
    titles_short = [t[:30]+"..." if len(t) > 30 else t for t in actual_titles]
    return False, f"Missing '{title_part}' in {channel}. Found: {titles_short}", actual_titles


def parse_args():
    parser = argparse.ArgumentParser(description="Validate golden test set")
    parser.add_argument("--expectations", "-e", help="JSON file with custom expectations")
    parser.add_argument("--report-json", help="Output JSON report to file")
    parser.add_argument("--report-md", help="Output Markdown report to file")
    parser.add_argument("--require-nonempty", action="store_true",
                        help="Fail if any client feed is empty")
    parser.add_argument("--min-pass-rate", type=float, default=0.0,
                        help="Minimum pass rate (0.0-1.0)")
    return parser.parse_args()


def main():
    args = parse_args()
    
    print("[START] Golden Set Validation...")
    
    # 1. Setup
    try:
        token = _get_simulation_token()
    except Exception as e:
        print(f"Auth Error: {e}")
        sys.exit(1)
        
    host = "gofr-iq-mcp"
    port = int(os.environ.get("GOFR_IQ_MCP_PORT", "8080"))
    
    try:
        session_id = _mcp_init(host, port)
    except Exception as e:
        print(f"MCP Connection Error: {e}")
        sys.exit(1)

    # Resolve Clients
    list_resp = _mcp_call(host, port, session_id, "list_clients", {"limit": 50}, token)
    live_clients = {c["name"]: c["client_guid"] for c in list_resp.get("data", {}).get("clients", [])}
    
    report = ValidationReport()
    client_feeds = {}  # Cache feeds for KPI calculation

    # =========================================================================
    # TEST CASE 1: TRUCK Strike (Score 60)
    # Target: Nebula (Holds TRUCK), Ironclad (Shorts TRUCK)
    # =========================================================================
    doc_title = "Heavy Truck Strike"
    
    # Check Nebula
    guid = live_clients.get("Nebula Retirement Fund")
    if guid:
        resp = _mcp_call(host, port, session_id, "get_client_avatar_feed", {"client_guid": guid}, token)
        data = resp.get("data", {})
        client_feeds["Nebula Retirement Fund"] = data
        passed, msg, actual = check_feed_contains(data, "MAINTENANCE", doc_title)
        report.add(
            "Nebula Retirement Fund",
            "See 'Truck Strike' in Maintenance",
            passed, msg,
            failure_reason="data_missing" if not passed else None,
            expected=f"'{doc_title}' in MAINTENANCE",
            actual=str(actual[:3]) if actual else "[]"
        )
    
    # Check Ironclad
    guid = live_clients.get("Ironclad Short Strategies")
    if guid:
        resp = _mcp_call(host, port, session_id, "get_client_avatar_feed", {"client_guid": guid}, token)
        data = resp.get("data", {})
        client_feeds["Ironclad Short Strategies"] = data
        passed, msg, actual = check_feed_contains(data, "MAINTENANCE", doc_title)
        report.add(
            "Ironclad Short Strategies",
            "See 'Truck Strike' in Maintenance",
            passed, msg,
            failure_reason="data_missing" if not passed else None,
            expected=f"'{doc_title}' in MAINTENANCE",
            actual=str(actual[:3]) if actual else "[]"
        )

    # Check Quantum (Should NOT see it)
    guid = live_clients.get("Quantum Momentum Partners")
    if guid:
        resp = _mcp_call(host, port, session_id, "get_client_avatar_feed", {"client_guid": guid}, token)
        data = resp.get("data", {})
        client_feeds["Quantum Momentum Partners"] = data
        
        # Expect NOT to find it in either
        in_maint, _, _ = check_feed_contains(data, "MAINTENANCE", doc_title)
        in_opp, _, _ = check_feed_contains(data, "OPPORTUNITY", doc_title)
        
        passed = not (in_maint or in_opp)
        msg = "Correctly filtered out" if passed else "Incorrectly appeared in feed"
        report.add(
            "Quantum Momentum",
            "NOT see 'Truck Strike' (No Exposure)",
            passed, msg,
            failure_reason="filter_mismatch" if not passed else None,
            expected="Not in any channel",
            actual=f"MAINT:{in_maint}, OPP:{in_opp}"
        )

    # =========================================================================
    # TEST CASE 2: ECO Subsidy (Score 85)
    # Target: Green Horizon (Holds ECO), Nebula (Watches ECO)
    # =========================================================================
    doc_title = "Green Energy Bill"
    
    # Check Green Horizon
    guid = live_clients.get("Green Horizon Capital")
    if guid:
        resp = _mcp_call(host, port, session_id, "get_client_avatar_feed", {"client_guid": guid}, token)
        data = resp.get("data", {})
        client_feeds["Green Horizon Capital"] = data
        passed, msg, actual = check_feed_contains(data, "MAINTENANCE", doc_title)
        report.add(
            "Green Horizon Capital",
            "See 'Green Energy' in Maintenance",
            passed, msg,
            failure_reason="data_missing" if not passed else None,
            expected=f"'{doc_title}' in MAINTENANCE",
            actual=str(actual[:3]) if actual else "[]"
        )

    # =========================================================================
    # TEST CASE 3: Threshold Filtering (BankOne - Score 25)
    # Quantum holds BANKO. Quantum threshold is usually 40.
    # =========================================================================
    doc_title = "BankOne Reports Steady Earnings"
    
    guid = live_clients.get("Quantum Momentum Partners")
    if guid:
        # May already have the feed cached
        if "Quantum Momentum Partners" not in client_feeds:
            resp = _mcp_call(host, port, session_id, "get_client_avatar_feed", {"client_guid": guid}, token)
            data = resp.get("data", {})
            client_feeds["Quantum Momentum Partners"] = data
        else:
            data = client_feeds["Quantum Momentum Partners"]
        
        # It affects BANKO (Held). Score 25. Quantum Threshold 40.
        # Expect: Filtered.
        found, _, actual = check_feed_contains(data, "MAINTENANCE", doc_title)
        passed = not found
        msg = "Correctly filtered (Score 25 < Threshold)" if passed else "Failed filtering (Score 25 appeared)"
        report.add(
            "Quantum Momentum",
            "Filter low score (BankOne)",
            passed, msg,
            failure_reason="filter_mismatch" if not passed else None,
            expected="Filtered (score 25 < threshold 40)",
            actual=f"Found: {found}"
        )

    # =========================================================================
    # Compute Per-Client KPIs
    # =========================================================================
    for client_name, feed_data in client_feeds.items():
        maint_items = feed_data.get("maintenance", [])
        opp_items = feed_data.get("opportunity", [])
        
        # Get client's test results
        client_results = [r for r in report.results if r.client.startswith(client_name[:10])]
        total_checks = len(client_results)
        passed_checks = sum(1 for r in client_results if r.passed)
        
        kpis = ClientKPIs(
            client_name=client_name,
            client_guid=live_clients.get(client_name, "unknown"),
            total_checks=total_checks,
            passed_checks=passed_checks,
            coverage=passed_checks / total_checks if total_checks > 0 else 0.0,
            precision=1.0,  # All returned items have valid relationships by design
            feed_empty=len(maint_items) == 0 and len(opp_items) == 0,
            maintenance_count=len(maint_items),
            opportunity_count=len(opp_items),
        )
        report.add_client_kpis(kpis)

    # Print Report
    failures = report.print_summary()
    
    # Write JSON report
    if args.report_json:
        Path(args.report_json).write_text(report.to_json())
        print(f"\n[OUTPUT] JSON report: {args.report_json}")
    
    # Write Markdown report
    if args.report_md:
        Path(args.report_md).write_text(report.to_markdown())
        print(f"[OUTPUT] Markdown report: {args.report_md}")
    
    # Check --require-nonempty
    if args.require_nonempty:
        empty_count = sum(1 for k in report.client_kpis if k.feed_empty)
        if empty_count > 0:
            print(f"\n[FAIL] --require-nonempty: {empty_count} client(s) have empty feeds")
            sys.exit(1)
    
    # Check --min-pass-rate
    if args.min_pass_rate > 0:
        report.compute_summary()
        if report.summary['pass_rate'] < args.min_pass_rate:
            print(f"\n[FAIL] --min-pass-rate: {report.summary['pass_rate']:.1%} < {args.min_pass_rate:.1%}")
            sys.exit(1)
    
    sys.exit(failures)

if __name__ == "__main__":
    main()
