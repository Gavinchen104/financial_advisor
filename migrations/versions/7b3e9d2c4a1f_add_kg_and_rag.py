"""add kg and rag tables

Revision ID: 7b3e9d2c4a1f
Revises: 0eef0be1c2f9
Create Date: 2026-10-28

Dialect-aware, per docs/PROJECT2-PLAN.md §4:

- PostgreSQL: the pgvector extension, the knowledge graph with provenance
  (kg_nodes / kg_edges / kg_facts), filings (filing_docs / filing_chunks with a
  halfvec(768) HNSW index and a generated tsvector + GIN index), and ask_log.
- SQLite (tests, local dev without Postgres): only ask_log, with generic types
  (JSON instead of JSONB / TEXT[], Integer autoincrement instead of BIGSERIAL).
  The RAG feature itself needs Postgres — see src/rag/config.py uses_postgres().

Requires pgvector >= 0.7 (halfvec). docker-compose uses pgvector/pgvector:pg16;
on a hosted Postgres check `SELECT extversion FROM pg_extension WHERE extname='vector'`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7b3e9d2c4a1f'
down_revision: Union[str, Sequence[str], None] = '0eef0be1c2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    # Works in offline (--sql) mode too, unlike op.get_bind().
    return op.get_context().dialect.name == "postgresql"


# Executed one statement at a time (psycopg3 prefers single statements).
PG_UPGRADE = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    # ---- knowledge graph with provenance ----
    """CREATE TABLE kg_nodes (
        id    TEXT PRIMARY KEY,            -- 'NVDA' | 'macro:10y_treasury_yield' | 'filing:<accession>' | 'org:<slug>'
        type  TEXT NOT NULL,               -- company | macro | filing | org
        name  TEXT NOT NULL,
        props JSONB NOT NULL DEFAULT '{}'  -- gics_*, aliases[], form, period_end, url, ...
    )""",
    """CREATE TABLE kg_edges (
        id         BIGSERIAL PRIMARY KEY,
        src        TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
        dst        TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
        type       TEXT NOT NULL,          -- competes_with | supplies_to | strategic_partner | macro_sensitivity | filed
        weight     REAL,
        source     TEXT NOT NULL,          -- curated | gics | filing
        accession  TEXT,                   -- filing supporting the edge (source='filing')
        evidence   TEXT,                   -- verbatim quote from that filing
        confidence TEXT,                   -- low | medium | high
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (src, dst, type, source, accession)
    )""",
    "CREATE INDEX ix_kg_edges_src ON kg_edges (src)",
    "CREATE INDEX ix_kg_edges_dst ON kg_edges (dst)",
    "CREATE INDEX ix_kg_edges_type ON kg_edges (type)",
    """CREATE TABLE kg_facts (
        id            BIGSERIAL PRIMARY KEY,
        node_id       TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
        metric        TEXT NOT NULL,       -- revenue | net_income | eps_diluted | price | trailing_pe | ...
        value         NUMERIC NOT NULL,
        unit          TEXT NOT NULL,       -- USD | USD/shares | shares | ratio
        period_end    DATE,
        fiscal_period TEXT,                -- FY2024 | Q2-2025 | snapshot
        source        TEXT NOT NULL,       -- xbrl | yfinance
        accession     TEXT,
        as_of         TIMESTAMPTZ NOT NULL,
        UNIQUE (node_id, metric, fiscal_period, source)
    )""",
    "CREATE INDEX ix_kg_facts_node_id ON kg_facts (node_id)",
    # ---- filings and chunks ----
    """CREATE TABLE filing_docs (
        accession   TEXT PRIMARY KEY,
        ticker      TEXT NOT NULL,
        cik         TEXT NOT NULL,
        form        TEXT NOT NULL,
        period_end  DATE,
        filed_at    DATE,
        source_url  TEXT NOT NULL,
        corpus      TEXT NOT NULL DEFAULT 'live',  -- 'live' | 'financebench' (local eval only)
        embed_model TEXT NOT NULL,
        embed_dim   INT NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        n_chunks    INT
    )""",
    "CREATE INDEX ix_filing_docs_ticker ON filing_docs (ticker)",
    """CREATE TABLE filing_chunks (
        id        BIGSERIAL PRIMARY KEY,
        accession TEXT NOT NULL REFERENCES filing_docs ON DELETE CASCADE,
        ticker    TEXT NOT NULL,
        corpus    TEXT NOT NULL,
        section   TEXT,                    -- item_1 | item_1a | item_7 | item_7a | item_8 | ... | page (PDF)
        page      INT,                     -- FinanceBench PDFs only (1-indexed)
        ord       INT NOT NULL,
        text      TEXT NOT NULL,
        embedding halfvec(768) NOT NULL,
        tsv       tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
    )""",
    "CREATE INDEX ix_filing_chunks_embedding ON filing_chunks USING hnsw (embedding halfvec_cosine_ops)",
    "CREATE INDEX ix_filing_chunks_tsv ON filing_chunks USING gin (tsv)",
    "CREATE INDEX ix_filing_chunks_corpus_ticker_section ON filing_chunks (corpus, ticker, section)",
    "CREATE INDEX ix_filing_chunks_accession ON filing_chunks (accession)",
]

# Reverse dependency order. The extension stays (other objects may use it).
PG_DOWNGRADE = [
    "DROP TABLE IF EXISTS filing_chunks",
    "DROP TABLE IF EXISTS filing_docs",
    "DROP TABLE IF EXISTS kg_facts",
    "DROP TABLE IF EXISTS kg_edges",
    "DROP TABLE IF EXISTS kg_nodes",
]


def upgrade() -> None:
    """Upgrade schema."""
    if _is_postgres():
        for stmt in PG_UPGRADE:
            op.execute(stmt)

    # ask_log exists on both dialects. Types mirror src/models.py AskLog.
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    tickers_type = sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")
    op.create_table(
        'ask_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('tickers', tickers_type, nullable=True),
        sa.Column('intent', sa.Text(), nullable=True),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('abstained', sa.Boolean(), nullable=True),
        sa.Column('grounding_passed', sa.Boolean(), nullable=True),
        sa.Column('regenerated', sa.Boolean(), nullable=True),
        sa.Column('citations', json_type, nullable=True),
        sa.Column('evidence_ids', json_type, nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ask_log_created_at'), 'ask_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_ask_log_user_id'), 'ask_log', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ask_log_user_id'), table_name='ask_log')
    op.drop_index(op.f('ix_ask_log_created_at'), table_name='ask_log')
    op.drop_table('ask_log')

    if _is_postgres():
        for stmt in PG_DOWNGRADE:
            op.execute(stmt)
