"""Tests for ClientProfile model parsing.

Milestone M1 introduces a Pydantic ClientProfile used to normalize Neo4j record
payloads without changing QueryService behavior.
"""

from __future__ import annotations

from app.models.client_profile import ClientProfile


class TestClientProfile:
    def test_restrictions_json_parsed_and_excluded(self) -> None:
        profile = ClientProfile.model_validate(
            {
                "client_guid": "client-123",
                "restrictions_json": "{\"impact_sustainability\": {\"impact_themes\": [\"clean_energy\"]}}",
            }
        )

        dumped = profile.model_dump()
        assert "restrictions_json" not in dumped
        assert dumped["restrictions"] == {"impact_sustainability": {"impact_themes": ["clean_energy"]}}
