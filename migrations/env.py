"""Alembic environment.

Reads DATABASE_URL from the environment (overriding alembic.ini's
sqlalchemy.url) and uses src.db.Base.metadata as the autogenerate target.

Two overrides exist for tests and tooling:
- `cfg.set_main_option("sqlalchemy.url", url)` before `command.upgrade(cfg, ...)`
  migrates a different database. The pg test fixture uses this to migrate the
  pgvector test DB while the app engine stays on SQLite.
- `cfg.attributes["connection"]` runs the migration on a caller-owned connection.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

from src.db import Base, DATABASE_URL, engine
import src.models  # noqa: F401 — registers models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini carries a placeholder URL. Honor an explicit override from the
# caller, otherwise DATABASE_URL (already normalized by src.db).
_ini_url = config.get_main_option("sqlalchemy.url") or ""
url = DATABASE_URL if (not _ini_url or _ini_url.startswith("driver://")) else _ini_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

target_metadata = Base.metadata

# The RAG tables (docs/PROJECT2-PLAN.md §4) are Postgres-only and are created
# with raw DDL in their migration, not from Base.metadata. Hide them from
# autogenerate so `alembic revision --autogenerate` never proposes dropping them.
RAG_PG_ONLY_TABLES = {"kg_nodes", "kg_edges", "kg_facts", "filing_docs", "filing_chunks"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in RAG_PG_ONLY_TABLES:
        return False
    if type_ == "index" and getattr(obj, "table", None) is not None and obj.table.name in RAG_PG_ONLY_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    if url == DATABASE_URL:
        # Reuse the app's engine (same URL normalization, pool settings).
        connectable = engine
    else:
        connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as conn:
        _run(conn)
    if connectable is not engine:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
