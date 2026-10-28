"""
Pytest fixtures.

CRITICAL: we override DATABASE_URL, SECRET_KEY, and GEMINI_API_KEY BEFORE any
`from src.*` import. src.db creates the SQLAlchemy engine at import time from
env vars, and src.agent constructs the Gemini client at import time. If we
import those modules with the real env in scope, tests would either hit the
dev DB or blow up on missing keys.

Postgres + pgvector tests (@pytest.mark.pg) use a second database given by
PG_TEST_URL — or a Postgres DATABASE_URL captured here before the override —
and run with `uv run pytest -m pg`. See docs/PROJECT2-PLAN.md.
"""

import os
import tempfile
from pathlib import Path

import pytest

# ---------- env setup (runs before any src.* import) ----------
# Capture a Postgres URL for the pg tests before pointing the app at SQLite.
_ORIGINAL_DATABASE_URL = os.environ.get("DATABASE_URL", "")
PG_TEST_URL = os.environ.get("PG_TEST_URL") or (
    _ORIGINAL_DATABASE_URL if _ORIGINAL_DATABASE_URL.startswith(("postgres://", "postgresql")) else ""
)

_TMP_DIR = Path(tempfile.mkdtemp(prefix="stockify_tests_"))
_TEST_DB_PATH = _TMP_DIR / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key-long-enough-for-jwt"
os.environ["GEMINI_API_KEY"] = "test-gemini-key-not-used"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key-not-used"
os.environ["SEC_USER_AGENT"] = "Stockify tests test@example.com"
os.environ["ENV"] = "dev"

# Now safe to import
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from src.db import Base, SessionLocal, engine, normalize_database_url  # noqa: E402
from src import models  # noqa: E402,F401 — registers models on Base

_ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"
_ALEMBIC_CFG = Config(str(_ALEMBIC_INI))


# ---------- fixtures ----------
@pytest.fixture(autouse=True)
def _reset_db():
    """Drop and recreate all tables before each test. Ensures isolation.

    We skip real alembic migrations in tests — too slow per-test — and instead
    create tables via Base.metadata.create_all, then stamp alembic to head so
    init_db()'s `alembic upgrade head` is a no-op.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    command.stamp(_ALEMBIC_CFG, "head")
    yield
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def db() -> Session:
    """Direct DB session for arranging test state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client. Cookies flow automatically between calls on the
    same client instance, so auth sessions work end-to-end."""
    from src.api import app
    # Disable the slowapi rate limiter in tests — otherwise multi-call tests
    # would trip 429s when they hammer the same endpoint.
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    """Test client with an already-signed-up user. Cookie is set on the client."""
    r = client.post("/auth/signup", json={
        "email": "alex@example.com",
        "password": "hunter2hunter2",
        "display_name": "Alex",
    })
    assert r.status_code == 201, f"signup failed: {r.text}"
    return client


@pytest.fixture
def brief_fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "briefs"


# ---------- Postgres + pgvector (@pytest.mark.pg) ----------
@pytest.fixture(scope="session")
def pg_engine():
    """Engine on the pgvector test database, migrated to head via Alembic.

    Skips when PG_TEST_URL is unset. When it is set (CI service, docker
    compose) the database must be reachable: a connection error fails the
    test instead of skipping, so CI can't go green without Postgres.
    """
    if not PG_TEST_URL:
        pytest.skip("needs Postgres + pgvector: set PG_TEST_URL (see docker-compose.yml, ci.yml)")
    url = normalize_database_url(PG_TEST_URL)
    pg = create_engine(url, pool_pre_ping=True, future=True)
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ConfigParser interpolation
    command.upgrade(cfg, "head")
    yield pg
    pg.dispose()


@pytest.fixture
def pg_conn(pg_engine):
    """Connection on the pg test DB inside a transaction that is always rolled back."""
    with pg_engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
