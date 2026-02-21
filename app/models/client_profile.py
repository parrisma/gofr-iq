"""Client profile model.

This is a thin, tolerant Pydantic layer over the properties we store on the
Neo4j `ClientProfile` node (plus a few client-level fields returned alongside it).

Milestone M1 goal: allow `QueryService` to parse/validate profile context without
changing query semantics.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ConfigDict, model_validator


class ClientProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Client-level context returned by QueryService
    client_guid: str
    impact_threshold: float | None = None
    client_type: str | None = None

    # ClientProfile node properties
    mandate_type: str | None = None
    mandate_text: str | None = None
    horizon: str | None = None
    esg_constrained: bool | None = None

    # Enrichment fields (Phase 1 / M4)
    mandate_themes: list[str] = Field(default_factory=list)
    mandate_embedding: list[float] = Field(default_factory=list)

    # Parsed restrictions payload (stored as JSON string in Neo4j)
    restrictions: dict[str, Any] | None = None

    # Benchmark instrument ticker returned by QueryService
    benchmark: str | None = None

    # Input-only field used by Neo4j adapters; excluded from dumps
    restrictions_json: str | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _parse_restrictions_json(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        restrictions = data.get("restrictions")
        restrictions_json = data.get("restrictions_json")
        if restrictions is not None or not restrictions_json:
            return data

        try:
            parsed = json.loads(restrictions_json)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        updated = dict(data)
        updated["restrictions"] = parsed
        return updated

    @model_validator(mode="before")
    @classmethod
    def _coerce_theme_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        updated = dict(data)

        themes = updated.get("mandate_themes")
        if themes is None:
            updated["mandate_themes"] = []
            themes = updated.get("mandate_themes")
        if isinstance(themes, str) and themes:
            try:
                loaded = json.loads(themes)
                if isinstance(loaded, list):
                    updated["mandate_themes"] = loaded
            except (json.JSONDecodeError, TypeError):
                updated["mandate_themes"] = []

        embedding = updated.get("mandate_embedding")
        if embedding is None:
            updated["mandate_embedding"] = []
            embedding = updated.get("mandate_embedding")
        if isinstance(embedding, str) and embedding:
            try:
                loaded = json.loads(embedding)
                if isinstance(loaded, list):
                    updated["mandate_embedding"] = loaded
            except (json.JSONDecodeError, TypeError):
                updated["mandate_embedding"] = []

        return updated
