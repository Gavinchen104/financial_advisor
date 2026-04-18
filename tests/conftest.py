"""
Pytest fixtures.

CRITICAL: we override DATABASE_URL, SECRET_KEY, and GEMINI_API_KEY BEFORE any
`from src.*` import. src.db creates the SQLAlchemy engine at import time from
env vars, and src.agent constructs the Gemini client at import time. If we
import those modules with the real env in scope, tests would either hit the
dev DB or blow up on missing keys.
"""

import os
import tempfile
from pathlib import Path

import pytest

# ---------- env setup (runs before any src.* import) ----------
_TMP_DIR = Path(tempfile.mkdtemp(prefix="stockify_tests_"))
_TEST_DB_PATH = _TMP_DIR / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key-long-enough-for-jwt"
os.environ["GEMINI_API_KEY"] = "test-gemini-key-not-used"
os.environ["ENV"] = "dev"

# Now safe to import
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.db import Base, SessionLocal, engine  # noqa: E402
from src import models  # noqa: E402,F401 — registers models on Base


# ---------- fixtures ----------
@pytest.fixture(autouse=True)
def _reset_db():
    """Drop and recreate all tables before each test. Ensures isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


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
