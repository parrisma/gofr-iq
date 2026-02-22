"""Backfill mandate_themes and mandate_embedding for existing ClientProfile nodes.

This is intended for simulation/demo environments and is idempotent.

Usage:
  uv run python scripts/backfill_client_mandates.py --limit 50
  uv run python scripts/backfill_client_mandates.py --group-name group-simulation --limit 200
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project imports resolve (same pattern as simulation runner)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "gofr-common" / "src"))

# Auto-load docker/.env if present (bridge NEO4J_PASSWORD -> GOFR_IQ_NEO4J_PASSWORD)
_docker_env = PROJECT_ROOT / "docker" / ".env"
if _docker_env.exists():
    for line in _docker_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

# Bridge common env var names to GOFR_IQ_* names expected by GraphIndex
if not os.environ.get("GOFR_IQ_NEO4J_PASSWORD") and os.environ.get("NEO4J_PASSWORD"):
    os.environ["GOFR_IQ_NEO4J_PASSWORD"] = os.environ["NEO4J_PASSWORD"]
if not os.environ.get("GOFR_IQ_NEO4J_URI"):
    os.environ["GOFR_IQ_NEO4J_URI"] = "bolt://gofr-neo4j:7687"

from app.logger import StructuredLogger
from app.services.graph_index import GraphIndex
from app.services.llm_service import create_llm_service
from app.services.mandate_enrichment import extract_themes_from_mandate


logger = StructuredLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ClientProfile mandate enrichment")
    parser.add_argument("--limit", type=int, default=200, help="Max profiles to process")
    parser.add_argument(
        "--group-name",
        type=str,
        default=None,
        help=(
            "Optional Group.name to scope the backfill (recommended: group-simulation). "
            "If omitted, backfills all ClientProfile nodes with mandate_text." 
        ),
    )
    parser.add_argument("--neo4j-uri", default=None, help="Override Neo4j bolt URI")
    parser.add_argument("--neo4j-password", default=None, help="Override Neo4j password")
    args = parser.parse_args()

    graph = GraphIndex(uri=args.neo4j_uri, password=args.neo4j_password)
    graph.init_schema()

    with create_llm_service() as llm:
        with graph._get_session() as session:
            if args.group_name:
                rows = session.run(
                    """
                    MATCH (g:Group {name: $group_name})<-[:IN_GROUP]-(c:Client)-[:HAS_PROFILE]->(cp:ClientProfile)
                    WHERE cp.mandate_text IS NOT NULL AND trim(cp.mandate_text) <> ''
                        AND (cp.mandate_themes IS NULL OR size(cp.mandate_themes) = 0 OR cp.mandate_embedding IS NULL)
                    RETURN c.name AS client_name, cp.guid AS guid, cp.mandate_text AS mandate_text
                    LIMIT $limit
                    """,
                    group_name=str(args.group_name),
                    limit=int(args.limit),
                )
            else:
                rows = session.run(
                    """
                    MATCH (c:Client)-[:HAS_PROFILE]->(cp:ClientProfile)
                    WHERE cp.mandate_text IS NOT NULL AND trim(cp.mandate_text) <> ''
                        AND (cp.mandate_themes IS NULL OR size(cp.mandate_themes) = 0 OR cp.mandate_embedding IS NULL)
                    RETURN c.name AS client_name, cp.guid AS guid, cp.mandate_text AS mandate_text
                    LIMIT $limit
                    """,
                    limit=int(args.limit),
                )

            candidates = [dict(r) for r in rows]

        total = len(candidates)
        scope = f"group={args.group_name}" if args.group_name else "all"
        print(f"Backfill candidates: {total} ({scope})", flush=True)

        if total == 0:
            print("Nothing to do.", flush=True)
            return 0

        t_start = time.time()
        updated = 0
        for i, row in enumerate(candidates, 1):
            guid = row.get("guid")
            mandate_text = row.get("mandate_text")
            client_name = row.get("client_name", guid)
            if not isinstance(guid, str) or not isinstance(mandate_text, str):
                continue

            print(f"  [{i}/{total}] {client_name}...", end="", flush=True)

            themes_result = extract_themes_from_mandate(mandate_text, llm)
            embedding: list[float] | None = None
            try:
                embedding = llm.generate_embedding(mandate_text)
            except Exception as exc:
                print(f" embedding FAILED: {exc}", flush=True)
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
            elapsed = time.time() - t_start
            print(f" OK themes={themes_result.themes} emb={'yes' if embedding else 'no'} ({elapsed:.0f}s)", flush=True)

        elapsed_total = time.time() - t_start
        print(f"Backfill complete: updated={updated}/{total} in {elapsed_total:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
