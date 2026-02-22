"""Alias resolution service (Milestone M2).

Resolves identifier variants (tickers, name variants, etc.) to a canonical node GUID
using Neo4j Alias nodes.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from app.services.graph_index import GraphIndex


@dataclass
class AliasResolver:
    graph_index: GraphIndex
    max_cache_size: int = 2048
    _cache: "OrderedDict[tuple[str, str | None], str | None]" = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
    )

    def resolve(self, value: str, scheme: str | None = None) -> str | None:
        """Resolve (value, scheme) to a canonical guid.

        Args:
            value: Raw identifier value (e.g. ticker, name variant)
            scheme: Optional scheme (e.g. TICKER, ISIN, NAME_VARIANT)

        Returns:
            Canonical node guid if found, else None.
        """
        if not value:
            return None

        value_norm = value.strip()
        if not value_norm:
            return None

        scheme_norm = scheme.strip().upper() if scheme else None
        key = (value_norm.lower(), scheme_norm)

        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        resolved = self._resolve_uncached(value_norm, scheme_norm)
        self._cache[key] = resolved
        self._cache.move_to_end(key)

        if len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)

        return resolved

    def _resolve_uncached(self, value: str, scheme: str | None) -> str | None:
        if not self.graph_index:
            return None

        with self.graph_index._get_session() as session:
            result = session.run(
                """
                MATCH (a:Alias {value: $value})
                WHERE $scheme IS NULL OR a.scheme = $scheme
                OPTIONAL MATCH (a)-[:HAS_ALIAS]-(t)
                RETURN coalesce(t.guid, a.canonical_guid) AS guid
                LIMIT 1
                """,
                value=value,
                scheme=scheme,
            )
            record = result.single()
            if not record:
                return None
            guid = record.get("guid")
            if isinstance(guid, str) and guid:
                return guid
            return None
