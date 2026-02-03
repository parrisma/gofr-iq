"""Tests for CPCS scoring with mandate_text

Tests verify that mandate_text contributes 50% to the Mandate section of CPCS.
"""

from __future__ import annotations

import pytest

from app.services.client_service import ClientService
from unittest.mock import MagicMock


@pytest.fixture
def client_service() -> ClientService:
    """Create ClientService with mocked GraphIndex"""
    mock_graph_index = MagicMock()
    return ClientService(mock_graph_index)


def test_cpcs_neither_mandate_fields(client_service: ClientService):
    """Test CPCS when neither mandate_type nor mandate_text is present"""
    data = {
        "client_props": {},
        "profile_props": {},
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 0.0 (neither field present)
    assert result["breakdown"]["mandate"]["score"] == 0.0
    assert result["breakdown"]["mandate"]["value"] == 0.0
    assert result["breakdown"]["mandate"]["details"]["mandate_type"] is False
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is False
    
    # Check missing fields
    assert "Mandate Type (client_profile.mandate_type)" in result["missing_fields"]
    assert "Mandate Description (client_profile.mandate_text)" in result["missing_fields"]


def test_cpcs_mandate_type_only(client_service: ClientService):
    """Test CPCS when only mandate_type is present"""
    data = {
        "client_props": {},
        "profile_props": {
            "mandate_type": "equity_long_short"
        },
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 0.5 (50% from mandate_type)
    assert result["breakdown"]["mandate"]["score"] == 0.5
    assert result["breakdown"]["mandate"]["value"] == 0.175  # 0.5 * 0.35
    assert result["breakdown"]["mandate"]["details"]["mandate_type"] is True
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is False
    
    # Check missing fields
    assert "Mandate Type (client_profile.mandate_type)" not in result["missing_fields"]
    assert "Mandate Description (client_profile.mandate_text)" in result["missing_fields"]


def test_cpcs_mandate_text_only(client_service: ClientService):
    """Test CPCS when only mandate_text is present"""
    data = {
        "client_props": {},
        "profile_props": {
            "mandate_text": "Our fund focuses on US technology stocks with strong ESG ratings."
        },
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 0.5 (50% from mandate_text)
    assert result["breakdown"]["mandate"]["score"] == 0.5
    assert result["breakdown"]["mandate"]["value"] == 0.175  # 0.5 * 0.35
    assert result["breakdown"]["mandate"]["details"]["mandate_type"] is False
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is True
    
    # Check missing fields
    assert "Mandate Type (client_profile.mandate_type)" in result["missing_fields"]
    assert "Mandate Description (client_profile.mandate_text)" not in result["missing_fields"]


def test_cpcs_both_mandate_fields(client_service: ClientService):
    """Test CPCS when both mandate_type and mandate_text are present"""
    data = {
        "client_props": {},
        "profile_props": {
            "mandate_type": "equity_long_short",
            "mandate_text": "Our fund focuses on US technology stocks with strong ESG ratings."
        },
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 1.0 (100% - both fields present)
    assert result["breakdown"]["mandate"]["score"] == 1.0
    assert result["breakdown"]["mandate"]["value"] == 0.35  # 1.0 * 0.35
    assert result["breakdown"]["mandate"]["details"]["mandate_type"] is True
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is True
    
    # Check missing fields
    assert "Mandate Type (client_profile.mandate_type)" not in result["missing_fields"]
    assert "Mandate Description (client_profile.mandate_text)" not in result["missing_fields"]


def test_cpcs_mandate_text_empty_string(client_service: ClientService):
    """Test CPCS when mandate_text is empty string (should not count)"""
    data = {
        "client_props": {},
        "profile_props": {
            "mandate_type": "equity_long_short",
            "mandate_text": ""
        },
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 0.5 (only mandate_type counts, empty string doesn't)
    assert result["breakdown"]["mandate"]["score"] == 0.5
    assert result["breakdown"]["mandate"]["value"] == 0.175
    assert result["breakdown"]["mandate"]["details"]["mandate_type"] is True
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is False


def test_cpcs_mandate_text_whitespace_only(client_service: ClientService):
    """Test CPCS when mandate_text is only whitespace (should not count)"""
    data = {
        "client_props": {},
        "profile_props": {
            "mandate_text": "   \n\t  "
        },
        "holding_count": 1,
        "watchlist_count": 0,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Mandate section should be 0.0 (whitespace-only doesn't count)
    assert result["breakdown"]["mandate"]["score"] == 0.0
    assert result["breakdown"]["mandate"]["details"]["mandate_text"] is False


def test_cpcs_full_profile_with_mandate_text(client_service: ClientService):
    """Test full CPCS calculation with all fields including mandate_text"""
    data = {
        "client_props": {
            "primary_contact": "john@example.com",
            "alert_frequency": "daily"
        },
        "profile_props": {
            "mandate_type": "equity_long_short",
            "mandate_text": "Focus on US tech with ESG screening",
            "esg_constrained": True
        },
        "holding_count": 5,
        "watchlist_count": 3,
        "exclude_count": 0,
        "benchmark_count": 0
    }
    
    result = client_service._compute_score(data)
    
    # Holdings: 1.0 * 0.35 = 0.35
    # Mandate: 1.0 * 0.35 = 0.35 (both mandate_type and mandate_text present)
    # Constraints: 1.0 * 0.20 = 0.20
    # Engagement: 1.0 * 0.10 = 0.10
    # Total: 1.0
    assert result["score"] == 1.0
    assert result["breakdown"]["mandate"]["score"] == 1.0
    assert result["breakdown"]["mandate"]["value"] == 0.35
    assert len(result["missing_fields"]) == 0
