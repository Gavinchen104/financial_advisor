"""Alembic environment.

Reads DATABASE_URL from the environment (overriding alembic.ini's
sqlalchemy.url) and uses src.db.Base.metadata as the autogenerate target.
"""

from logging.config import fileConfig

from sqlalchemy import pool

from alembic import context

from src.db import Base, DATABASE_URL, engine
import src.models  # noqa: F401 — registers models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Always honor the DATABASE_URL from the environment (via src.db).
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Reuse the app's engine (same URL normalization, pool settings).
    connectable = engine
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
