"""Tests for alias resolution guardrails.

Milestone M0 asks for small unit tests covering alias resolution even before the
full Alias node pattern (M2) is implemented.

Current behavior: company lookup in `IngestService._resolve_company_guid` includes
an `aliases` array match in its Cypher query.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.ingest_service import IngestService


@dataclass
class _FakeResult:
    record: dict[str, object] | None

    def single(self) -> dict[str, object] | None:  # pragma: no cover - trivial
        return self.record


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, query: str, params: dict[str, object]) -> _FakeResult:  # pragma: no cover - exercised by tests
        self.calls.append((query, params))
        if not self._results:
            raise AssertionError("No more queued results for FakeSession.run()")
        return self._results.pop(0)


class TestResolveCompanyGuid:
    def test_returns_existing_company_guid(self) -> None:
        session = _FakeSession(
            results=[_FakeResult({"guid": "comp-googl", "name": "Alphabet Inc."})]
        )

        service = IngestService.__new__(IngestService)
        guid = service._resolve_company_guid(session, name="Alphabet")

        assert guid == "comp-googl"
        assert len(session.calls) == 1
        assert "any(alias IN c.aliases" in session.calls[0][0]

    def test_creates_company_when_missing(self) -> None:
        session = _FakeSession(results=[_FakeResult(None), _FakeResult(None)])

        service = IngestService.__new__(IngestService)
        guid = service._resolve_company_guid(session, name="Alphabet, Inc.")

        assert guid == "comp-alphabet-inc"
        assert len(session.calls) == 2

        first_query, first_params = session.calls[0]
        assert "MATCH (c:Company)" in first_query
        assert first_params == {"name": "Alphabet, Inc."}

        second_query, second_params = session.calls[1]
        assert "MERGE (c:Company {guid: $guid})" in second_query
        assert second_params["guid"] == "comp-alphabet-inc"
        assert second_params["name"] == "Alphabet, Inc."
        assert second_params["ticker"] == "ALPHABET-I"
