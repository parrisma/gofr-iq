# Avatar Feed Test Report

**Generated:** 2026-02-09T14:45:13.844520
**Test Suite:** Golden Test Set

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | 18 |
| Passed | 18 |
| Failed | 0 |
| Pass Rate | 100.0% |
| Empty Feeds | 0 |

## Test Results

| Client | Check | Result | Detail |
|--------|-------|--------|--------|
| INFRA | Theme vocabulary gate (0 violations) | PASS | All 21 distinct themes in VALID_THEMES (doc=9, cli... |
| INFRA | Schema completeness (all docs have required fields) | PASS | All docs complete |
| INFRA | Phantom instruments (0 hallucinated tickers) | PASS | No phantom instruments |
| Nebula Retirement Fund | See 'Truck Strike' in Maintenance | PASS | Found 'Heavy Truck Strike' in MAINTENANCE |
| Ironclad Short Strategies | See 'Truck Strike' in Maintenance | PASS | Found 'Heavy Truck Strike' in MAINTENANCE |
| Quantum Momentum | NOT see 'Truck Strike' (No Exposure) | PASS | Correctly filtered out |
| Green Horizon Capital | See 'Green Energy' in Maintenance | PASS | Found 'Green Energy Bill' in MAINTENANCE |
| Quantum Momentum | Filter low score (BankOne) | PASS | Correctly filtered (Score 25 < Threshold) |
| DiamondHands420 | See 'Blockchain Protocol' in Opportunity | PASS | Found 'Blockchain Protocol' in OPPORTUNITY |
| Quantum Momentum | See 'Blockchain Protocol' in Maintenance (watches FIN) | PASS | Found 'Blockchain Protocol' in MAINTENANCE |
| Nebula Retirement Fund | See 'Rate Hike' in Opportunity (rates theme) | PASS | Found 'Rate Hike' in OPPORTUNITY |
| Green Horizon Capital | See 'ESG Ethics' in Opportunity (esg theme) | PASS | Found 'ESG Activists Target' in OPPORTUNITY |
| Nebula Retirement Fund | NOT see 'Blockchain Protocol' in Opportunity | PASS | Correctly excluded (no blockchain theme) |
| DiamondHands420 | NOT see 'Rate Hike' in Opportunity (watches LUXE) | PASS | Correctly excluded (watches LUXE) |
| Quantum | Top-1 is 'Nexus Software' | PASS | Top title: Nexus Software Unveils Revolutionary Qu... |
| Green | Top-1 is 'Green Energy Bill' | PASS | Top title: New Green Energy Bill Passed: Major Sub... |
| Nebula | Top-1 is 'Truck Strike' | PASS | Top title: Heavy Truck Strike Threatens Logistics:... |
| Ironclad | Top-1 is 'Truck Strike' | PASS | Top title: Heavy Truck Strike Threatens Logistics:... |

## Per-Client KPIs

| Client | Coverage | Precision | Maintenance | Opportunity | Empty |
|--------|----------|-----------|-------------|-------------|-------|
| Nebula Retirement Fund | 100% | 100% | 2 | 1 | No |
| Ironclad Short Strategies | 100% | 100% | 2 | 0 | No |
| Quantum Momentum Partners | 100% | 100% | 2 | 0 | No |
| Green Horizon Capital | 100% | 100% | 2 | 1 | No |
| DiamondHands420 | 100% | 100% | 1 | 1 | No |
| Sunrise Long Opportunities | 0% | 100% | 1 | 0 | No |