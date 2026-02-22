"""Load Alias records into Neo4j (Milestone M2).

Usage:
  uv run python scripts/load_aliases.py --input path/to/aliases.json

Input formats:
  - JSON: list of {"scheme": "TICKER", "value": "Alphabet", "canonical_guid": "inst-GOOGL"}
  - CSV: headers scheme,value,canonical_guid
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.logger import StructuredLogger
from app.services.graph_index import GraphIndex


logger = StructuredLogger(__name__)


def _load_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a list")
        rows: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append({
                "scheme": str(item.get("scheme") or "").strip(),
                "value": str(item.get("value") or "").strip(),
                "canonical_guid": str(item.get("canonical_guid") or "").strip(),
            })
        return rows

    if suffix in {".csv", ".tsv"}:
        dialect = "excel-tab" if suffix == ".tsv" else "excel"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, dialect=dialect)
            return [
                {
                    "scheme": (r.get("scheme") or "").strip(),
                    "value": (r.get("value") or "").strip(),
                    "canonical_guid": (r.get("canonical_guid") or "").strip(),
                }
                for r in reader
            ]

    raise ValueError(f"Unsupported input type: {suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load Alias nodes into Neo4j")
    parser.add_argument("--input", required=True, help="Path to aliases .json/.csv/.tsv")
    parser.add_argument("--neo4j-uri", default=None, help="Override Neo4j bolt URI")
    parser.add_argument("--neo4j-password", default=None, help="Override Neo4j password")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write")
    args = parser.parse_args()

    path = Path(args.input)
    rows = _load_rows(path)
    rows = [r for r in rows if r.get("scheme") and r.get("value") and r.get("canonical_guid")]
    logger.info(f"Alias loader: parsed {len(rows)} valid row(s) from {path}")

    if args.dry_run:
        return 0

    graph = GraphIndex(uri=args.neo4j_uri, password=args.neo4j_password)
    graph.init_schema()

    loaded = 0
    for row in rows:
        graph.upsert_alias(
            value=row["value"],
            scheme=row["scheme"],
            canonical_guid=row["canonical_guid"],
        )
        loaded += 1

    logger.info(f"Alias loader: loaded {loaded} alias(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
