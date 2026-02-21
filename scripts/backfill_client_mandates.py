"""Backfill mandate_themes and mandate_embedding for existing ClientProfile nodes.

This is intended for simulation/demo environments and is idempotent.

Usage:
  uv run python scripts/backfill_client_mandates.py --limit 50
"""

from __future__ import annotations

import argparse

from app.logger import StructuredLogger
from app.services.graph_index import GraphIndex
from app.services.llm_service import create_llm_service
from app.services.mandate_enrichment import extract_themes_from_mandate


logger = StructuredLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ClientProfile mandate enrichment")
    parser.add_argument("--limit", type=int, default=200, help="Max profiles to process")
    parser.add_argument("--neo4j-uri", default=None, help="Override Neo4j bolt URI")
    parser.add_argument("--neo4j-password", default=None, help="Override Neo4j password")
    args = parser.parse_args()

    graph = GraphIndex(uri=args.neo4j_uri, password=args.neo4j_password)
    graph.init_schema()

    with create_llm_service() as llm:
        with graph._get_session() as session:
            rows = session.run(
                """
                MATCH (cp:ClientProfile)
                WHERE cp.mandate_text IS NOT NULL AND trim(cp.mandate_text) <> ''
                  AND (cp.mandate_themes IS NULL OR size(cp.mandate_themes) = 0 OR cp.mandate_embedding IS NULL)
                RETURN cp.guid AS guid, cp.mandate_text AS mandate_text
                LIMIT $limit
                """,
                limit=int(args.limit),
            )
            candidates = [dict(r) for r in rows]

        logger.info(f"Backfill candidates: {len(candidates)}")

        updated = 0
        for row in candidates:
            guid = row.get("guid")
            mandate_text = row.get("mandate_text")
            if not isinstance(guid, str) or not isinstance(mandate_text, str):
                continue

            themes_result = extract_themes_from_mandate(mandate_text, llm)
            embedding: list[float] | None = None
            try:
                embedding = llm.generate_embedding(mandate_text)
            except Exception:
                embedding = None

            with graph._get_session() as session:
                session.run(
                    """
                    MATCH (cp:ClientProfile {guid: $guid})
                    SET cp.mandate_themes = $themes
                    """,
                    guid=guid,
                    themes=themes_result.themes,
                )
                if embedding is not None:
                    session.run(
                        """
                        MATCH (cp:ClientProfile {guid: $guid})
                        SET cp.mandate_embedding = $embedding
                        """,
                        guid=guid,
                        embedding=embedding,
                    )

            updated += 1

        logger.info(f"Backfill completed: updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
