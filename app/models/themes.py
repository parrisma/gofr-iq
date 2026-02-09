"""Canonical theme vocabulary for gofr-iq.

Single source of truth for the controlled theme vocabulary used by:
- Document extraction (graph_extraction.py)
- Mandate enrichment (mandate_enrichment.py)
- Client profile updates (client_tools.py)
- Simulation / golden set validation (validate_test_set.py)

Add new themes here. All consumers import from this module.
"""

from __future__ import annotations

VALID_THEMES: frozenset[str] = frozenset({
    "ai", "semiconductor", "ev_battery", "supply_chain", "m_and_a",
    "rates", "fx", "credit", "esg", "energy_transition", "geopolitical",
    "japan", "china", "india", "korea", "fintech", "biotech",
    "real_estate", "commodities", "consumer", "defense", "cloud",
    "cybersecurity", "autonomous_vehicles", "blockchain",
})

__all__ = ["VALID_THEMES"]
