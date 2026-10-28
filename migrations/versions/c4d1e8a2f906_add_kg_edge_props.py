"""add kg_edges.props and an upsert key for edges without an accession

Revision ID: c4d1e8a2f906
Revises: 7b3e9d2c4a1f
Create Date: 2026-10-28

Two gaps in the §4 schema that P2-B (seeding the curated graph) hit:

- Macro-sensitivity edges carry a direction ("inverse" / "positive") and an
  override flag, and the curated graph will want other per-edge metadata later.
  `props JSONB` mirrors kg_nodes.props.
- UNIQUE (src, dst, type, source, accession) never conflicts for curated/gics
  edges because their accession is NULL (NULLs compare distinct), so
  INSERT … ON CONFLICT could not make seeding idempotent. A partial unique
  index on (src, dst, type, source) WHERE accession IS NULL is the upsert key
  for those edges; filing edges keep the full constraint.

Postgres only — the kg tables do not exist on SQLite.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4d1e8a2f906'
down_revision: Union[str, Sequence[str], None] = '7b3e9d2c4a1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


PG_UPGRADE = [
    "ALTER TABLE kg_edges ADD COLUMN IF NOT EXISTS props JSONB NOT NULL DEFAULT '{}'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_edges_no_accession "
    "ON kg_edges (src, dst, type, source) WHERE accession IS NULL",
]

PG_DOWNGRADE = [
    "DROP INDEX IF EXISTS uq_kg_edges_no_accession",
    "ALTER TABLE kg_edges DROP COLUMN IF EXISTS props",
]


def upgrade() -> None:
    """Upgrade schema."""
    if _is_postgres():
        for stmt in PG_UPGRADE:
            op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""
    if _is_postgres():
        for stmt in PG_DOWNGRADE:
            op.execute(stmt)
