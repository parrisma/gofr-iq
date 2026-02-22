"""Tests for opportunity_bias scoring config (Milestone M5)."""

from __future__ import annotations

from app.services.query_service import ScoringConfig


def test_scoring_config_lambda_boundaries() -> None:
    c0 = ScoringConfig.from_opportunity_bias(0.0)
    assert c0.opportunity_bias == 0.0
    assert c0.direct_holding_base == 1.0
    assert c0.watchlist_base == 0.80
    assert c0.thematic_base == 0.50
    assert c0.vector_base == 0.40
    assert c0.competitor_base == 0.40
    assert c0.supplier_base == 0.60
    assert c0.peer_base == 0.40
    assert c0.recency_half_life_minutes == 60.0
    assert c0.vector_activation_threshold == 0.5

    c05 = ScoringConfig.from_opportunity_bias(0.5)
    assert c05.opportunity_bias == 0.5
    assert abs(c05.direct_holding_base - 0.8) < 1e-9
    assert abs(c05.thematic_base - 0.75) < 1e-9
    assert abs(c05.vector_base - 0.60) < 1e-9
    assert abs(c05.competitor_base - 0.55) < 1e-9
    assert abs(c05.supplier_base - 0.50) < 1e-9
    assert abs(c05.peer_base - 0.50) < 1e-9
    assert abs(c05.recency_half_life_minutes - 120.0) < 1e-9

    c1 = ScoringConfig.from_opportunity_bias(1.0)
    assert c1.opportunity_bias == 1.0
    assert abs(c1.direct_holding_base - 0.6) < 1e-9
    assert c1.thematic_base == 1.0
    assert c1.vector_base == 0.8
    assert abs(c1.competitor_base - 0.70) < 1e-9
    assert abs(c1.supplier_base - 0.40) < 1e-9
    assert abs(c1.peer_base - 0.60) < 1e-9
    assert abs(c1.recency_half_life_minutes - 180.0) < 1e-9


def test_scoring_config_lambda_clamps() -> None:
    c_neg = ScoringConfig.from_opportunity_bias(-123.0)
    assert c_neg.opportunity_bias == 0.0
    c_hi = ScoringConfig.from_opportunity_bias(123.0)
    assert c_hi.opportunity_bias == 1.0


def test_thematic_rises_with_lambda() -> None:
    low = ScoringConfig.from_opportunity_bias(0.0)
    high = ScoringConfig.from_opportunity_bias(1.0)
    assert high.thematic_base > low.thematic_base
