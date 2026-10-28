"""
Seed the Postgres knowledge graph (kg_nodes / kg_edges) from the compiled JSON
graph, with provenance: curated edges get source='curated', GICS peer edges
source='gics', and every edge keeps its weight and rationale (as `evidence`).
Macro direction/override live in kg_edges.props. See docs/PROJECT2-PLAN.md P2-B.

Idempotent: re-running updates in place, keeps edge ids, and prunes curated/gics
edges that left the JSON. Nodes are never deleted (filing edges hang off them).

Run:
    uv run python scripts/seed_kg.py --dry-run     # counts only, no DB needed
    uv run python scripts/seed_kg.py               # needs a Postgres DATABASE_URL
                                                   # (docker compose up -d db; alembic upgrade head)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.knowledge_graph.graph import _GRAPH_PATH  # noqa: E402
from src.rag import kg_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", type=Path, default=_GRAPH_PATH, help="compiled graph JSON (default: the checked-in one)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be written; touch no database")
    parser.add_argument("--no-prune", action="store_true", help="keep curated/gics edges that are no longer in the JSON")
    args = parser.parse_args()

    if not args.graph.exists():
        print(f"Graph not found at {args.graph}. Run: uv run python scripts/build_knowledge_graph.py", file=sys.stderr)
        return 2
    with open(args.graph) as f:
        data = json.load(f)

    report, _, _ = kg_store.plan_seed(data)
    print(report.summary())
    if args.dry_run:
        return 0

    from src.rag.config import uses_postgres

    if not uses_postgres():
        print(
            "\nDATABASE_URL is not Postgres. The knowledge-graph tables exist only on Postgres + pgvector "
            "(docker compose up -d db; set DATABASE_URL=postgresql+psycopg://stockify:stockify_dev@localhost:5432/stockify).",
            file=sys.stderr,
        )
        return 2

    from src.db import engine

    with engine.begin() as conn:
        report = kg_store.seed_graph(conn, data, prune=not args.no_prune)
    print()
    print(report.summary())
    print("\nThe app serves the DB-backed graph on its next graph reload (get_graph() refreshes every 15 min; restart to force).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
